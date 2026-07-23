"""발행 후 QC 게이트 — 스레드 캡션 점검·로깅 (2026-07-23 사용자 지시 '발행시 점검').

스레드 단문은 마커 누출(**, [[, ##)이 유일한 실질 리스크(설명은 사진/첫댓글이 대체).
발행을 막지 않고 data/qc_log.jsonl 에 판정을 남긴다(사후 점검·추적용).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("publish_qc")
KST = timezone(timedelta(hours=9))
_QC_LOG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "qc_log.jsonl")


def check_caption(text: str) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    for mk in ("**", "[[", "]]", "##"):
        if mk in (text or ""):
            issues.append(("FAIL", f"기호 누출 '{mk}'"))
    return issues


def record(channel: str, ident: str, text: str) -> str:
    issues = check_caption(text)
    v = "FAIL" if issues else "OK"
    rec = {"ts": datetime.now(KST).isoformat(timespec="seconds"), "channel": channel,
           "id": str(ident), "verdict": v, "issues": [f"{s}:{m}" for s, m in issues],
           "metrics": {"chars": len(text or "")}}
    try:
        with open(_QC_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"QC 로그 기록 실패: {e}")
    if issues:
        logger.warning(f"[QC 🔴 FAIL] {channel} {ident} — {'; '.join(m for _, m in issues)}")
    else:
        logger.info(f"[QC ✅ OK] {channel} {ident}")
    return v
