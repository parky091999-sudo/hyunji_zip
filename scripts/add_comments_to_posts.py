"""
기존 포스팅 글에 상품 페이지 링크 댓글 일괄 추가 (1회성 백필)
- 링크: https://parky091999-sudo.github.io/hyunji_zip/r/{code}.html
- threads_url(shortcode)을 API media id로 변환해 댓글 작성
- replied_comments.json 으로 멱등 보장 (재실행해도 중복 안 달림)
"""
import asyncio
import json
import logging
import os
import sys
from hashlib import md5

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import DATA_DIR, LOG_DIR

FEED_POSTS_PATH = os.path.join(DATA_DIR, "feed_posts.json")
MAX_COMMENTS_PER_RUN = 25  # rate limit 보호

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "add_comments.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("add_comments_to_posts")


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _shortcode(url: str) -> str:
    return url.rstrip("/").split("/post/")[-1] if "/post/" in (url or "") else ""


async def run():
    from poster.threads import fetch_my_posts, post_product_link_comment
    from poster.comment_replier import load_replied, save_replied

    logger.info("=" * 50)
    logger.info("기존 포스팅 링크 댓글 백필 시작")

    feed = _load_json(FEED_POSTS_PATH, [])
    replied = load_replied()

    targets = [
        p for p in feed
        if p.get("status") == "posted"
        and p.get("product_code") and p.get("product_code") != "preview"
        and p.get("threads_url")
    ]
    if not targets:
        logger.info("대상 없음")
        return

    # permalink(shortcode) → 실제 media id 매핑 (API 1회)
    my_posts = fetch_my_posts(limit=100)
    sc_to_id = {}
    for mp in my_posts:
        sc = _shortcode(mp.get("permalink", ""))
        if sc:
            sc_to_id[sc] = mp.get("id", "")
    logger.info(f"대상 {len(targets)}개 / 내 게시글 매핑 {len(sc_to_id)}개")

    added = 0
    for i, post in enumerate(targets, 1):
        if added >= MAX_COMMENTS_PER_RUN:
            logger.info(f"회당 상한({MAX_COMMENTS_PER_RUN}) 도달 — 나머지는 재실행 시 처리")
            break

        code = post.get("product_code", "")
        sc = _shortcode(post.get("threads_url", ""))
        name = (post.get("product_name") or "")[:28]
        post_id = sc_to_id.get(sc, "")

        if not post_id:
            logger.warning(f"[{i}] {name} [{code}] — media id 매칭 실패 (오래된 글일 수 있음)")
            continue

        # 멱등 키 (code 기반 — 같은 글에 한 번만)
        key = md5(f"linkcomment:{post_id}:{code}".encode()).hexdigest()[:12]
        done = set(replied.get(post_id, []))
        if key in done:
            logger.info(f"[{i}] {name} [{code}] — 이미 처리됨")
            continue

        logger.info(f"[{i}/{len(targets)}] {name} [{code}] 댓글 추가...")
        reply_id = post_product_link_comment(post_id, code, product_url=post.get("product_url"))
        if reply_id:
            done.add(key)
            replied[post_id] = list(done)
            save_replied(replied)
            added += 1
            await asyncio.sleep(8)
        else:
            logger.warning("  실패 — 다음으로")

    logger.info(f"완료: {added}개 댓글 추가")


if __name__ == "__main__":
    asyncio.run(run())
