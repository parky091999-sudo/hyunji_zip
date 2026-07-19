"""인스타 DM 자동발송 봇 (2026-07-19 신설, 사용자 지시).

영상 릴스 첫 댓글 CTA("댓글에 '키워드' 남기면 DM으로 보내드릴게")의 실제 발송 주체.
지금까지는 등록부(docs/dm_keywords.json)와 CTA만 있고 발송 코드가 없어 DM이 안 나갔다.

동작:
  1) docs/dm_keywords.json 의 계정별(media_id → keyword·code) 등록부를 읽는다
  2) 각 미디어의 최근 댓글을 조회해 키워드가 포함된 댓글을 찾는다
  3) 비공개 답장(Private Reply)으로 상품 링크 DM 발송 + 댓글에 "DM 보냈어요 📩" 공개 답글
  4) data/dm_replied.json 에 comment_id 기록(중복 방지)

제약:
  - Private Reply는 댓글 작성 후 7일 이내만 가능(그 이전 댓글은 스킵·기록만)
  - 토큰에 메시징 권한(instagram_business_manage_messages) 필요 — 없으면 명확히 로그.

실행: EC2 크론 `run_coupang.sh dm_bot` (시간당 1회). 로컬 수동 실행도 동일.
"""
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))

KW_PATH      = os.path.join(ROOT, "docs", "dm_keywords.json")
REPLIED_PATH = os.path.join(ROOT, "data", "dm_replied.json")
GRAPH        = "https://graph.instagram.com/v21.0"
LANDING      = "https://hyunjissi.hyunjiunni.com/r/{code}.html"
MAX_MEDIA    = 12          # 최근 등록 미디어만 스캔(오래된 건 7일 창 지나 의미 없음)
MAX_DM_PER_RUN = 15        # 폭주·레이트리밋 방어

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dm_bot")

# 계정별 토큰 env 매핑 — jiniee 슬롯은 유진 릴스 수익화(7/31~)와 함께 채워진다
ACCOUNT_TOKENS = {
    "hyunji": ("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID"),
    "jiniee": ("INSTAGRAM_JINIEE_ACCESS_TOKEN", "INSTAGRAM_JINIEE_USER_ID"),
}


def _load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def _dm_text(name: str, code: str, keyword: str) -> str:
    return (f"'{keyword}' 남겨줘서 고마워! 🤍\n"
            f"{name} 정보 여기서 바로 볼 수 있어 👇\n"
            f"{LANDING.format(code=code)}\n\n"
            "* 쿠팡 파트너스 활동의 일환으로, 일정액의 수수료를 제공받습니다.")


def _me_username(token: str) -> str:
    try:
        r = requests.get(f"{GRAPH}/me", params={"fields": "username", "access_token": token}, timeout=15)
        return (r.json() or {}).get("username", "")
    except Exception:
        return ""


def _comments(media_id: str, token: str) -> list[dict]:
    try:
        r = requests.get(f"{GRAPH}/{media_id}/comments",
                         params={"fields": "id,text,username,timestamp", "limit": 50,
                                 "access_token": token}, timeout=20)
        return (r.json() or {}).get("data", []) or []
    except Exception as e:
        logger.warning(f"댓글 조회 실패({media_id}): {str(e)[:80]}")
        return []


def _private_reply(comment_id: str, text: str, token: str) -> tuple[bool, str]:
    """댓글에 비공개 답장 DM. 반환 (성공여부, 오류메시지)."""
    try:
        r = requests.post(f"{GRAPH}/me/messages",
                          json={"recipient": {"comment_id": comment_id},
                                "message": {"text": text}},
                          params={"access_token": token}, timeout=20)
        if r.status_code == 200:
            return True, ""
        return False, r.text[:200]
    except Exception as e:
        return False, str(e)[:200]


def _public_ack(comment_id: str, token: str):
    try:
        requests.post(f"{GRAPH}/{comment_id}/replies",
                      data={"message": "DM 보냈어! 📩 확인해줘", "access_token": token}, timeout=15)
    except Exception:
        pass


def run():
    kw_map = _load(KW_PATH, {})
    replied = _load(REPLIED_PATH, {})
    accounts = (kw_map.get("accounts") or {})
    now = datetime.now(timezone.utc)
    sent = skipped_old = 0
    perm_error_logged = False

    for acct, media_map in accounts.items():
        media = (media_map or {}).get("media") or {}
        if not media:
            continue
        tok_env, _uid_env = ACCOUNT_TOKENS.get(acct, ("", ""))
        token = os.environ.get(tok_env, "").strip() if tok_env else ""
        if not token:
            logger.info(f"[{acct}] 토큰 없음({tok_env}) — 스킵")
            continue
        my_name = _me_username(token)
        recent = sorted(media.items(), key=lambda kv: kv[1].get("added_at", 0), reverse=True)[:MAX_MEDIA]
        for media_id, info in recent:
            kw, code, name = info.get("keyword", ""), info.get("code", ""), info.get("name", "")
            if not (kw and code):
                continue
            for c in _comments(media_id, token):
                cid, text, user = c.get("id", ""), c.get("text", "") or "", c.get("username", "")
                if not cid or cid in replied or (my_name and user == my_name):
                    continue
                if kw not in text:
                    continue
                ts = c.get("timestamp", "")
                try:
                    age = now - datetime.fromisoformat(ts.replace("+0000", "+00:00"))
                except Exception:
                    age = timedelta(0)
                if age > timedelta(days=7):
                    # Private Reply 7일 창 초과 — 발송 불가, 재시도 방지 기록만
                    replied[cid] = {"skipped": "7d_window", "media": media_id, "at": now.isoformat()}
                    skipped_old += 1
                    continue
                if sent >= MAX_DM_PER_RUN:
                    break
                ok, err = _private_reply(cid, _dm_text(name, code, kw), token)
                if ok:
                    _public_ack(cid, token)
                    replied[cid] = {"code": code, "media": media_id, "user": user, "at": now.isoformat()}
                    sent += 1
                    logger.info(f"[{acct}] DM 발송: [{code}] ← @{user} ('{kw}')")
                else:
                    if ("permission" in err.lower() or "OAuth" in err or '"code":10' in err
                            or '"code":200' in err) and not perm_error_logged:
                        logger.error(
                            f"[{acct}] ★DM 권한 오류 — 토큰에 메시징 권한(instagram_business_manage_messages)이 "
                            f"없을 가능성. Meta 개발자 콘솔에서 스코프 포함 토큰 재발급 필요(사용자 액션). 원문: {err}")
                        perm_error_logged = True
                    else:
                        logger.warning(f"[{acct}] DM 실패({cid}): {err}")

    json.dump(replied, open(REPLIED_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    logger.info(f"완료 — 발송 {sent}건, 7일 초과 스킵 {skipped_old}건, 기록 {len(replied)}건")


if __name__ == "__main__":
    run()
