"""
Threads API 댓글 감지 및 대댓글
공식 Meta Graph API 사용 — Playwright 불필요
- 최근 7일 story 게시글의 댓글 감지
- Groq API로 자연스러운 대댓글 생성 후 포스팅
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from hashlib import md5

import requests

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import THREADS_ACCESS_TOKEN, THREADS_USER_ID, THREADS_USERNAME, DATA_DIR
from generator.reply import generate_reply

logger = logging.getLogger(__name__)

RECENT_POSTS_PATH = os.path.join(DATA_DIR, "recent_posts.json")
REPLIED_PATH = os.path.join(DATA_DIR, "replied_comments.json")
GRAPH_BASE = "https://graph.threads.net/v1.0"


def _api(method: str, path: str, **kwargs) -> dict:
    url = f"{GRAPH_BASE}{path}"
    resp = requests.request(method, url, timeout=30, **kwargs)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Threads API 오류: {data['error']}")
    return data


# ── 데이터 I/O ────────────────────────────────────────────────────────────────

def load_recent_posts() -> list[dict]:
    if not os.path.exists(RECENT_POSTS_PATH):
        return []
    with open(RECENT_POSTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_recent_posts(posts: list[dict]):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(RECENT_POSTS_PATH, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


def add_recent_post(post_url: str, post_id: str = "", post_type: str = "story", product_code: str = ""):
    """게시글 URL + API post_id 등록 (댓글 감지 대상). product_code는 키워드 자동답변용."""
    if not post_url and not post_id:
        return
    posts = load_recent_posts()
    if post_url and any(p.get("url") == post_url for p in posts):
        return
    posts.append({
        "url": post_url or "",
        "post_id": post_id or "",
        "posted_at": datetime.now().isoformat(),
        "post_type": post_type,
        "product_code": product_code or "",
    })
    # 7일 지난 것 제거
    cutoff = datetime.now() - timedelta(days=7)
    posts = [p for p in posts if datetime.fromisoformat(p["posted_at"]) > cutoff]
    save_recent_posts(posts)
    logger.info(f"최근 포스트 등록: {post_url or post_id}")


def load_replied() -> dict:
    if not os.path.exists(REPLIED_PATH):
        return {}
    with open(REPLIED_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_replied(data: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(REPLIED_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _comment_key(reply_id: str, text: str) -> str:
    return md5(f"{reply_id}:{text[:80]}".encode()).hexdigest()[:12]


# ── 키워드 자동 답변 ('나도/링크' 류 댓글 → 상품코드 안내) ────────────────────
_KEYWORD_ALWAYS = ("링크", "구매처", "어디서 사", "어디서사", "정보 좀", "정보좀", "알려줘", "알려주", "궁금")
_KEYWORD_SHORT  = ("나도", "저도", "주세요", "보내줘", "부탁")  # 짧은 댓글일 때만 (오탐 방지)


def _is_keyword_comment(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if any(k in t for k in _KEYWORD_ALWAYS):
        return True
    return len(t) <= 25 and any(k in t for k in _KEYWORD_SHORT)


def _keyword_reply(product_code: str) -> str:
    return f"프로필 링크 들어가서 [{product_code}] 검색하면 나와 👀"


_OWN_USERNAME = None


def _get_own_username() -> str:
    """내 계정 핸들 조회 (자기 댓글에 답글 다는 루프 방지용) — API 1회 후 캐시"""
    global _OWN_USERNAME
    if _OWN_USERNAME is not None:
        return _OWN_USERNAME
    try:
        data = _api(
            "GET",
            f"/{THREADS_USER_ID}",
            params={"fields": "username", "access_token": THREADS_ACCESS_TOKEN},
        )
        _OWN_USERNAME = (data.get("username") or "").lstrip("@")
    except Exception:
        _OWN_USERNAME = (THREADS_USERNAME or "").lstrip("@")
    return _OWN_USERNAME


# ── API 로직 ──────────────────────────────────────────────────────────────────

def get_replies(post_id: str) -> list[dict]:
    """게시글의 모든 직접 댓글 조회"""
    if not post_id or not THREADS_ACCESS_TOKEN:
        return []
    try:
        data = _api(
            "GET",
            f"/{post_id}/replies",
            params={
                "fields": "id,text,username,timestamp",
                "access_token": THREADS_ACCESS_TOKEN,
            },
        )
        return data.get("data", [])
    except Exception as e:
        logger.warning(f"댓글 조회 실패 ({post_id}): {e}")
        return []


def post_reply_to_thread(parent_post_id: str, reply_text: str) -> bool:
    """특정 게시글에 대댓글 작성 (API 기반)"""
    if not THREADS_ACCESS_TOKEN or not THREADS_USER_ID:
        logger.warning("API 토큰 없음 — 대댓글 건너뜀")
        return False
    try:
        # 1단계: 대댓글 컨테이너 생성 (reply_to_id 지정)
        container = _api(
            "POST",
            f"/{THREADS_USER_ID}/threads",
            params={
                "media_type": "TEXT",
                "text": reply_text,
                "reply_to_id": parent_post_id,
                "access_token": THREADS_ACCESS_TOKEN,
            },
        )
        container_id = container["id"]
        logger.info(f"  대댓글 컨테이너: {container_id}")

        # 2단계: 대기 후 게시
        time.sleep(15)
        _api(
            "POST",
            f"/{THREADS_USER_ID}/threads_publish",
            params={
                "creation_id": container_id,
                "access_token": THREADS_ACCESS_TOKEN,
            },
        )
        logger.info(f"  대댓글 게시: {reply_text[:40]}")
        return True

    except Exception as e:
        logger.error(f"대댓글 포스팅 실패: {e}")
        return False


# ── 메인 실행 ─────────────────────────────────────────────────────────────────

async def check_and_reply_comments():
    """최근 story 게시글 댓글 감지 → 자동 대댓글 (API 기반)"""
    import asyncio

    if not THREADS_ACCESS_TOKEN:
        logger.warning("THREADS_ACCESS_TOKEN 미설정 — 댓글 기능 건너뜀")
        return

    posts = load_recent_posts()
    # story/manual/casual 전 타입 댓글 응답 (기존 story 한정 → manual 게시글 무응답 버그 수정)
    target_posts = [p for p in posts if p.get("post_id")]

    if not target_posts:
        logger.info("댓글 확인할 포스트 없음")
        return

    replied = load_replied()
    reply_count = 0
    own = _get_own_username()
    logger.info(f"댓글 확인 시작: {len(target_posts)}개 포스트 (내 계정: @{own})")

    for post in target_posts:
        post_id = post.get("post_id", "")
        url = post.get("url", "")
        if not post_id:
            logger.debug(f"post_id 없음 (구 데이터), 건너뜀: {url}")
            continue

        try:
            replies = get_replies(post_id)
            if not replies:
                logger.info(f"댓글 없음: {post_id}")
                continue

            post_replied = set(replied.get(post_id, []))
            new_replies = [
                r for r in replies
                if _comment_key(r.get("id", ""), r.get("text", "")) not in post_replied
            ]

            # 내 계정 댓글(이전 자동답글)은 응답 대상에서 제외 + 처리완료 마킹 (자기증식 루프 방지)
            if own:
                mine = [r for r in new_replies
                        if (r.get("username", "") or "").lstrip("@").lower() == own.lower()]
                if mine:
                    for r in mine:
                        post_replied.add(_comment_key(r.get("id", ""), r.get("text", "")))
                    replied[post_id] = list(post_replied)
                    save_replied(replied)
                    new_replies = [r for r in new_replies if r not in mine]

            if not new_replies:
                logger.info(f"새 댓글 없음: {post_id}")
                continue

            logger.info(f"새 댓글 {len(new_replies)}개: {post_id}")

            # ── 1) 키워드 댓글('나도/링크' 류): 각 댓글에 직접 코드 안내 ──
            product_code = post.get("product_code", "")
            kw_hits = [r for r in new_replies if _is_keyword_comment(r.get("text", ""))] if product_code else []
            for r in kw_hits[:5]:  # 회당 최대 5개 (초과분은 다음 회차)
                if post_reply_to_thread(r.get("id", ""), _keyword_reply(product_code)):
                    post_replied.add(_comment_key(r.get("id", ""), r.get("text", "")))
                    replied[post_id] = list(post_replied)
                    save_replied(replied)
                    reply_count += 1
                    await asyncio.sleep(10)

            # ── 2) 일반 댓글: 각 댓글에 개별 대댓글 (해당 댓글 id로 reply_to_id 지정) ──
            others = [r for r in new_replies if r not in kw_hits]
            for r in others[:3]:  # 회당 최대 3개
                comment_text = f"@{r.get('username', '?')}: {r.get('text', '')}"
                reply_text = generate_reply(comment_text)
                if not reply_text:
                    continue
                success = post_reply_to_thread(r.get("id", ""), reply_text)
                if success:
                    post_replied.add(_comment_key(r.get("id", ""), r.get("text", "")))
                    replied[post_id] = list(post_replied)
                    save_replied(replied)
                    reply_count += 1
                    await asyncio.sleep(15)

        except Exception as e:
            logger.error(f"댓글 처리 오류 ({post_id}): {e}")

    logger.info(f"대댓글 완료: {reply_count}개")
