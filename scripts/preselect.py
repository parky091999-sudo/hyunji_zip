"""
사전 상품 선정 — 매일 오전 9시 KST 실행
내일 자동포스팅 후보 3개를 선정하여 data/pending_post.json 에 저장
"""
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import (
    DATA_DIR, LOG_DIR, MAX_PRODUCTS_PER_RUN,
    YOUTUBE_API_KEY, NAVER_CLIENT_ID,
)
from generator.content import generate_post

PENDING_PATH     = os.path.join(DATA_DIR, "pending_post.json")
POSTED_IDS_PATH  = os.path.join(DATA_DIR, "posted_ids.json")
CANDIDATES_COUNT = 3

KST = timezone(timedelta(hours=9))

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "preselect.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("preselect")


def _load_posted_ids() -> set[str]:
    if not os.path.exists(POSTED_IDS_PATH):
        return set()
    with open(POSTED_IDS_PATH, encoding="utf-8") as f:
        return set(json.load(f))


def _product_key(product: dict) -> str:
    url = product.get("product_url", "")
    return url[:80] if url else product.get("name", "")[:20]


async def _collect_products(need: int, posted_ids: set[str]) -> list[dict]:
    products = []

    if YOUTUBE_API_KEY:
        logger.info("YouTube 트렌딩 수집...")
        from scraper.youtube_trending import scrape_trending_products
        yt = scrape_trending_products(max_items=need)
        for p in yt:
            if _product_key(p) not in posted_ids:
                products.append(p)
        logger.info(f"  → YouTube {len(products)}개")

    if len(products) < need and NAVER_CLIENT_ID:
        logger.info(f"네이버 쇼핑으로 {need - len(products)}개 보충...")
        from scraper.naver_shopping import scrape_deals
        extra = scrape_deals(max_items=need - len(products))
        for p in extra:
            if _product_key(p) not in posted_ids and p not in products:
                products.append(p)
        logger.info(f"  → 누적 {len(products)}개")

    if len(products) < need:
        logger.info("쿠팡 홈 폴백...")
        from scraper.coupang import scrape_homepage_deals
        extra = await scrape_homepage_deals(max_items=need - len(products))
        for p in extra:
            if _product_key(p) not in posted_ids and p not in products:
                products.append(p)

    if len(products) < need:
        logger.info("프리셋 리스트 폴백...")
        from scraper.preset import get_next_preset_product
        while len(products) < need:
            p = get_next_preset_product(posted_ids | {_product_key(x) for x in products})
            if not p:
                break
            products.append(p)

    return products[:need]


async def run():
    logger.info("=" * 50)
    logger.info(f"사전선정 시작: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    logger.info("=" * 50)

    tomorrow = (datetime.now(KST) + timedelta(days=1)).strftime("%Y-%m-%d")
    posted_ids = _load_posted_ids()

    products = await _collect_products(CANDIDATES_COUNT, posted_ids)
    if not products:
        logger.warning("수집 상품 없음 — pending_post.json 업데이트 건너뜀")
        return

    candidates = []
    for product in products:
        logger.info(f"콘텐츠 생성: {product.get('name', '')[:40]}")
        content = generate_post(product)
        if not content:
            continue
        candidates.append({
            "product":       content["product"],
            "post_text":     content["post_text_1"],
            "image_url":     content.get("image_url", ""),
            "detail_images": content.get("detail_images", []),
            "product_code":  content.get("product_code", ""),
            "status":        "pending",   # pending | approved | rejected
        })

    pending = {
        "for_date":     tomorrow,
        "generated_at": datetime.now(KST).isoformat(),
        "candidates":   candidates,
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PENDING_PATH, "w", encoding="utf-8") as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)

    logger.info(f"pending_post.json 저장 완료 — {len(candidates)}개 후보 (for {tomorrow})")


if __name__ == "__main__":
    asyncio.run(run())
