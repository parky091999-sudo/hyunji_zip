"""
우리 계정(@hyunji_ssi)이 최근 단 대댓글 감사 — 외국어/오인식 답글 식별 + 삭제.

흐름:
1. recent_posts.json에 등록된 최근 게시글들의 replies 조회
2. 우리 계정 username 의 답글만 필터
3. has_foreign_chars로 외국어 포함 답글 식별 (한자/일본어/태국어 등)
4. --dry-run (기본): 출력만 / --delete: Threads API DELETE 호출
"""
import argparse
import json
import logging
import os
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import DATA_DIR, THREADS_ACCESS_TOKEN, THREADS_USER_ID, THREADS_USERNAME
from generator.content import has_foreign_chars
from generator.reply import _LATIN_RE, _looks_truncated_reply

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("audit_my_replies")

GRAPH = "https://graph.threads.net/v1.0"
RECENT_POSTS_PATH = os.path.join(DATA_DIR, "recent_posts.json")
REPLIED_PATH = os.path.join(DATA_DIR, "replied_comments.json")


def _api(method, path, **kw):
    r = requests.request(method, f"{GRAPH}{path}", timeout=30, **kw)
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"Threads API: {data['error']}")
    return data


def _own_username():
    data = _api("GET", f"/{THREADS_USER_ID}",
                params={"fields": "username", "access_token": THREADS_ACCESS_TOKEN})
    return (data.get("username") or THREADS_USERNAME or "").lstrip("@")


def collect_my_replies(own):
    """recent_posts에 등록된 게시글들의 replies 중 우리가 단 것만 수집."""
    if not os.path.exists(RECENT_POSTS_PATH):
        logger.warning("recent_posts.json 없음")
        return []
    posts = json.load(open(RECENT_POSTS_PATH, encoding="utf-8"))
    out = []
    for p in posts:
        post_id = p.get("post_id", "")
        if not post_id:
            continue
        try:
            data = _api("GET", f"/{post_id}/replies", params={
                "fields": "id,text,username,timestamp,reply_to",
                "access_token": THREADS_ACCESS_TOKEN,
            })
        except Exception as e:
            logger.warning(f"replies 조회 실패 {post_id}: {e}")
            continue
        for r in data.get("data", []):
            uname = (r.get("username") or "").lstrip("@").lower()
            if uname == own.lower():
                out.append({
                    "reply_id": r.get("id", ""),
                    "text":     r.get("text", ""),
                    "ts":       r.get("timestamp", ""),
                    "post_id":  post_id,
                    "post_url": p.get("url", ""),
                    "parent":   (r.get("reply_to") or {}).get("id", ""),
                })
    return out


def is_misclassified(text: str) -> bool:
    """오인식 의심 휴리스틱: 'X 맛있어/좋아/대박' 같이 한 단어를 음식·상품으로 받은 형태"""
    if not text:
        return False
    suspect_endings = ("맛있어", "맛있다", "맛있음", "좋아해", "좋더라", "대박이야")
    parts = text.strip().split()
    if len(parts) <= 4:
        return any(text.strip().endswith(s) for s in suspect_endings)
    return False


def fetch_parent_text(parent_id: str) -> str:
    if not parent_id:
        return ""
    try:
        d = _api("GET", f"/{parent_id}", params={
            "fields": "text", "access_token": THREADS_ACCESS_TOKEN,
        })
        return d.get("text", "") or ""
    except Exception:
        return ""


def delete_reply(reply_id: str) -> bool:
    try:
        _api("DELETE", f"/{reply_id}",
             params={"access_token": THREADS_ACCESS_TOKEN})
        return True
    except Exception as e:
        logger.error(f"삭제 실패 {reply_id}: {e}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delete", action="store_true", help="실제 삭제 (기본은 dry-run)")
    args = ap.parse_args()

    if not THREADS_ACCESS_TOKEN:
        logger.error("THREADS_ACCESS_TOKEN 없음")
        sys.exit(1)

    own = _own_username()
    logger.info(f"내 계정: @{own}")

    mine = collect_my_replies(own)
    logger.info(f"수집된 내 답글: {len(mine)}개")

    flagged = []
    for r in mine:
        text = r["text"]
        reason = []
        if has_foreign_chars(text):
            reason.append("외국어")
        if _LATIN_RE.search(text):
            reason.append("영어")
        if _looks_truncated_reply(text):
            reason.append("잘림")
        if is_misclassified(text):
            reason.append("단어오인식")
        if reason:
            r["reason"] = ", ".join(reason)
            r["parent_text"] = fetch_parent_text(r["parent"])
            flagged.append(r)

    print(f"\n=== 문제 답글 {len(flagged)}개 ===\n")
    for r in flagged:
        print(f"[{r['reason']}] reply_id={r['reply_id']}  ts={r['ts'][:19]}")
        print(f"  답글: {r['text']}")
        if r.get("parent_text"):
            print(f"  원댓글: {r['parent_text'][:80]}")
        print(f"  게시글: {r['post_url']}")
        print()

    if not flagged:
        print("문제 답글 없음")
        return

    if not args.delete:
        print("dry-run 모드 — 실제 삭제하려면 --delete 추가")
        return

    print("\n=== 삭제 실행 ===")
    deleted_ids = []
    for r in flagged:
        if delete_reply(r["reply_id"]):
            print(f"✓ 삭제됨: {r['reply_id']}")
            deleted_ids.append(r["reply_id"])
        else:
            print(f"✗ 실패: {r['reply_id']}")

    # replied_comments에서도 해당 부모 댓글 키 제거 → 다음 사이클에 다시 답글 시도 가능
    if deleted_ids and os.path.exists(REPLIED_PATH):
        try:
            replied = json.load(open(REPLIED_PATH, encoding="utf-8"))
            # 부모 댓글 key를 알기 어렵지만, 삭제한 답글의 부모 댓글이 새로 처리되도록
            # 해당 post의 처리 기록 일부를 제거 (보수적: post 전체 기록 유지)
            json.dump(replied, open(REPLIED_PATH, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"replied_comments 정리 실패: {e}")

    print(f"\n총 {len(deleted_ids)}/{len(flagged)}건 삭제 완료")


if __name__ == "__main__":
    main()
