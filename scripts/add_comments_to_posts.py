"""
기존 포스팅 글에 상품 정보 댓글 추가
feed_posts.json의 17개 포스팅에 대해 product_code 기반으로 상품 정보 링크 댓글 달기
"""
import asyncio
import json
import logging
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import DATA_DIR, LOG_DIR

FEED_POSTS_PATH = os.path.join(DATA_DIR, "feed_posts.json")

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


async def run():
    from poster.threads import create_reply
    from poster.comment_replier import load_replied, save_replied

    logger.info("=" * 50)
    logger.info("기존 포스팅 글에 댓글 추가 시작")

    feed = _load_json(FEED_POSTS_PATH, [])
    replied = load_replied()

    # product_code와 threads_url이 있는 포스팅만 대상
    targets = [
        p for p in feed
        if p.get("product_code") and p.get("product_code") != "preview"
        and p.get("threads_url")
    ]

    if not targets:
        logger.info("댓글 추가 대상 없음")
        return

    logger.info(f"대상 포스팅: {len(targets)}개")
    comment_count = 0

    for i, post in enumerate(targets, 1):
        code = post.get("product_code", "")
        url = post.get("threads_url", "")
        name = post.get("product_name", "")[:30]

        if not code or not url:
            continue

        logger.info(f"[{i}/{len(targets)}] {name} [{code}]")

        # Threads URL에서 post_id 추출 (URL 형식: https://www.threads.com/@kkul_pick711/post/DZcsIV1lsgq)
        try:
            post_id = url.split("/post/")[-1] if "/post/" in url else None
            if not post_id:
                logger.warning(f"  post_id 추출 실패: {url}")
                continue

            # 댓글 텍스트
            comment_text = f"상품 정보: kkul-pick.com/r/[{code}]"

            # 이미 댓글 추가된 post인지 확인
            replied_set = set(replied.get(post_id, []))
            from hashlib import md5
            comment_key = md5(f"{post_id}:{comment_text[:80]}".encode()).hexdigest()[:12]

            if comment_key in replied_set:
                logger.info(f"  이미 댓글 추가됨 (스킵)")
                continue

            # 댓글 추가
            reply_id = create_reply(post_id, comment_text)
            if reply_id:
                logger.info(f"  댓글 추가 완료: {reply_id}")
                replied_set.add(comment_key)
                replied[post_id] = list(replied_set)
                save_replied(replied)
                comment_count += 1
                # API rate limit 고려
                if i < len(targets):
                    await asyncio.sleep(5)
            else:
                logger.warning(f"  댓글 추가 실패")

        except Exception as e:
            logger.error(f"  처리 오류: {e}")

    logger.info(f"완료: {comment_count}개 댓글 추가")


if __name__ == "__main__":
    asyncio.run(run())
