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
from config import THREADS_ACCESS_TOKEN, THREADS_USER_ID, DATA_DIR
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


def add_recent_post(post_url: str, post_id: str = "", post_type: str = "story"):
    """story 게시글 URL + API post_id 등록 (댓글 감지 대상)"""
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
    story_posts = [p for p in posts if p.get("post_type") == "story"]

    if not story_posts:
        logger.info("댓글 확인할 포스트 없음")
        return

    replied = load_replied()
    reply_count = 0
    logger.info(f"댓글 확인 시작: {len(story_posts)}개 포스트")

    for post in story_posts:
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

            if not new_replies:
                logger.info(f"새 댓글 없음: {post_id}")
                continue

            logger.info(f"새 댓글 {len(new_replies)}개: {post_id}")

            # 여러 댓글을 맥락으로 묶어 대댓글 1개 생성
            combined = "\n".join([
                f"@{r.get('username', '?')}: {r.get('text', '')}"
                for r in new_replies[:3]
            ])
            reply_text = generate_reply(combined)
            if not reply_text:
                continue

            success = post_reply_to_thread(post_id, reply_text)
            if success:
                for r in new_replies:
                    post_replied.add(_comment_key(r.get("id", ""), r.get("text", "")))
                replied[post_id] = list(post_replied)
                save_replied(replied)
                reply_count += 1
                await asyncio.sleep(15)

        except Exception as e:
            logger.error(f"댓글 처리 오류 ({post_id}): {e}")

    logger.info(f"대댓글 완료: {reply_count}개")
