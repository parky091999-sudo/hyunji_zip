"""
수동 큐 포스팅 — 매일 낮 12:05 KST 실행
manual_queue.json 의 첫 번째 상품을 포스팅하고 큐에서 제거
"""
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import DATA_DIR, LOG_DIR

QUEUE_PATH      = os.path.join(DATA_DIR, "manual_queue.json")
POSTED_IDS_PATH = os.path.join(DATA_DIR, "posted_ids.json")
FEED_POSTS_PATH = os.path.join(DATA_DIR, "feed_posts.json")

KST = timezone(timedelta(hours=9))

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "manual_post.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("manual_post")


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _product_key(product: dict) -> str:
    url = product.get("product_url", "")
    return url[:80] if url else product.get("name", "")[:20]


async def run():
    import random
    skip_delay = os.getenv("SKIP_DELAY", "false").lower() == "true"
    if not skip_delay:
        delay = random.randint(0, 55)
        if delay:
            logger.info(f"랜덤 딜레이: {delay}분 대기...")
            await asyncio.sleep(delay * 60)

    logger.info("=" * 50)
    logger.info(f"수동 포스팅 시작: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    logger.info("=" * 50)

    queue = _load_json(QUEUE_PATH, [])
    if not queue:
        logger.info("수동 큐가 비어 있습니다 — 종료")
        return

    # 첫 번째 항목 꺼내기
    item = queue.pop(0)
    _save_json(QUEUE_PATH, queue)

    product     = item.get("product", {})
    post_text   = item.get("post_text", "")
    image_url   = item.get("image_url") or product.get("image_url", "")
    detail_imgs = item.get("detail_images", [])

    # 코드 할당
    code = item.get("product_code", "")
    if not code or code == "preview":
        from generator.registry import assign_code
        code = assign_code(
            product.get("product_url", ""),
            product.get("name", ""),
            product.get("image_url", ""),
        ) or ""

    # post_text가 비어있으면 AI로 자동 생성
    if not post_text.strip():
        logger.info("post_text 없음 → AI 자동 생성 중...")
        try:
            from generator.content import generate_post
            content = generate_post(product)
            if content:
                post_text   = content.get("post_text_1", "")
                detail_imgs = detail_imgs or content.get("detail_images", [])
                image_url   = image_url or content.get("image_url", "")
                code        = code or content.get("product_code", "")
                logger.info("  AI 생성 완료")
        except Exception as e:
            logger.warning(f"  AI 생성 실패: {e}")

    # 코드 검색 문구 없으면 추가
    if code and "프로필 링크에서" not in post_text:
        post_text = post_text + f"\n\n제품 정보는 프로필 링크에서 [{code}] 검색 👆"

    # 파트너스 링크 추가 (link.coupang.com 형태만)
    product_url = product.get("product_url", "")
    if product_url and "link.coupang.com" in product_url and product_url not in post_text:
        post_text += f"\n👉 {product_url}"

    if not post_text.strip():
        logger.error("포스팅 텍스트 생성 실패 — 종료")
        return

    logger.info(f"포스팅: {product.get('name', '')[:40]} [{code}]")

    from poster.threads import post_thread_api
    from poster.comment_replier import add_recent_post

    try:
        result = post_thread_api(
            post_text=post_text,
            image_url=image_url,
            detail_images=detail_imgs,
        )
    except Exception as e:
        logger.error(f"포스팅 실패: {e}")
        result = None

    post_url = result.get("post_url") if result else None
    post_id  = result.get("post_id")  if result else None
    status   = "posted" if result else "failed"

    if result:
        posted_ids = set(_load_json(POSTED_IDS_PATH, []))
        key = _product_key(product)
        if key:
            posted_ids.add(key)
        _save_json(POSTED_IDS_PATH, sorted(posted_ids))
        # 페이지 노출용 posted 플래그
        if code:
            from generator.registry import mark_posted
            mark_posted(code)

    feed = _load_json(FEED_POSTS_PATH, [])
    feed.insert(0, {
        "timestamp":     datetime.now(KST).isoformat(),
        "product_code":  code,
        "product_name":  product.get("name", ""),
        "product_image": product.get("image_url", ""),
        "product_url":   product.get("product_url", ""),
        "post_text":     post_text,
        "threads_url":   post_url,
        "status":        status,
        "post_type":     "manual",
    })
    _save_json(FEED_POSTS_PATH, feed[:200])

    if post_url and post_id:
        add_recent_post(post_url, post_id, "manual")

    logger.info(f"수동 포스팅 완료: {status} | {post_url or '(URL 없음)'}")

    try:
        import generate_page, generate_feed_page
        generate_page.main()
        generate_feed_page.main()
    except Exception as e:
        logger.error(f"페이지 생성 오류: {e}")


if __name__ == "__main__":
    asyncio.run(run())
