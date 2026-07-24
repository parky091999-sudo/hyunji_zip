"""발행 후 QC 게이트 — 스레드 캡션 점검·로깅 (2026-07-23 신설, 2026-07-24 보완).

스레드 단문은 마커 누출(**, [[, ##)이 유일한 실질 리스크(설명은 사진/첫댓글이 대체).
발행을 막지 않고 data/qc_log.jsonl 에 판정 기록(FAIL은 qc_fail.jsonl 분리), 롤링으로 무한증가 방지.
(옵트인) QC_LLM_JUDGE=1 이면 캡션↔상품 의미 일치를 LLM 1콜로 판정([073] 그라인더 훅 불일치 대응).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("publish_qc")
KST = timezone(timedelta(hours=9))
_DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_QC_LOG = os.path.join(_DATA, "qc_log.jsonl")
_QC_FAIL = os.path.join(_DATA, "qc_fail.jsonl")
_MAX_LINES = 800
_MAX_FAIL_LINES = 300


def check_caption(text: str) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    for mk in ("**", "[[", "]]", "##"):
        if mk in (text or ""):
            issues.append(("FAIL", f"기호 누출 '{mk}'"))
    return issues


def qc_llm_relevance(subject: str, context: str) -> list[tuple[str, str]]:
    """(옵트인 QC_LLM_JUDGE=1) 캡션이 상품과 의미상 맞는지 LLM 1콜 판정. 오탐 여지라 WARN만."""
    if os.environ.get("QC_LLM_JUDGE", "").strip() not in ("1", "true", "on"):
        return []
    key = os.environ.get("GOOGLE_API_KEY", "")
    if not key or not subject or not context:
        return []
    try:
        from google import genai
        client = genai.Client(api_key=key)
        prompt = (f"상품: {context}\n게시글 훅: {subject}\n\n"
                  "이 훅이 상품과 의미상 맞나? 훅이 전혀 다른 소재를 말하면 불일치야.\n"
                  "첫 줄 MATCH 또는 MISMATCH, 둘째 줄 12자 이내 이유.")
        r = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        head = (r.text or "").strip().splitlines()
        if head and head[0].strip().upper().startswith("MISMATCH"):
            reason = head[1][:20] if len(head) > 1 else ""
            return [("WARN", f"훅↔상품 불일치 의심({reason})")]
    except Exception as e:
        logger.warning(f"[QC] LLM 심판 오류(무시): {e}")
    return []


def _append_rolling(path: str, rec: dict, cap: int) -> None:
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > cap * 1.25:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines[-cap:])
    except Exception as e:
        logger.warning(f"QC 로그 기록 실패({os.path.basename(path)}): {e}")


def record(channel: str, ident: str, text: str, extra_issues=None) -> str:
    """캡션 점검(+옵션 extra_issues) → 판정·기록. 판정 문자열 반환."""
    issues = check_caption(text) + list(extra_issues or [])
    v = "FAIL" if any(s == "FAIL" for s, _ in issues) else ("WARN" if issues else "OK")
    rec = {"ts": datetime.now(KST).isoformat(timespec="seconds"), "channel": channel,
           "id": str(ident), "verdict": v, "issues": [f"{s}:{m}" for s, m in issues],
           "metrics": {"chars": len(text or "")}}
    _append_rolling(_QC_LOG, rec, _MAX_LINES)
    if v == "FAIL":
        _append_rolling(_QC_FAIL, rec, _MAX_FAIL_LINES)
    tag = {"OK": "✅", "WARN": "⚠️", "FAIL": "🔴"}.get(v, "?")
    logger.info(f"[QC {tag} {v}] {channel} {ident} — {'; '.join(m for _, m in issues) or 'clean'}")
    return v
