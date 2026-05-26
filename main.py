"""
메인 파이프라인 진입점
실행: python main.py           → 즉시 1회 실행
실행: python main.py --schedule → 스케줄 모드 (하루 2~3회 자동)
"""
import asyncio
import logging
import os
import sys
import argparse
from datetime import datetime

import schedule
import time

import json

sys.path.append(os.path.dirname(__file__))
from config import SCHEDULE_TIMES, MAX_PRODUCTS_PER_RUN, LOG_DIR, NAVER_CLIENT_ID, DATA_DIR
from scraper.coupang import scrape_homepage_deals
from scraper.naver_shopping import scrape_deals, save_products
from generator.content import generate_posts_batch
from poster.threads import post_all_products

POSTED_IDS_PATH = os.path.join(DATA_DIR, "posted_ids.json")


def load_posted_ids() -> set[str]:
    if not os.path.exists(POSTED_IDS_PATH):
        return set()
    with open(POSTED_IDS_PATH, encoding="utf-8") as f:
        return set(json.load(f))


def save_posted_ids(ids: set[str]):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(POSTED_IDS_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, ensure_ascii=False, indent=2)


def _product_key(product: dict) -> str:
    """상품 고유 키 — URL 앞 80자 또는 상품명 앞 20자"""
    url = product.get("product_url", "")
    if url:
        return url[:80]
    return product.get("name", "")[:20]

os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "pipeline.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("main")


async def run_pipeline():
    """전체 파이프라인 1회 실행"""
    logger.info("=" * 50)
    logger.info(f"파이프라인 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 50)

    # 1단계: 상품 수집 (네이버 쇼핑 API 우선 → 쿠팡 홈 폴백)
    if NAVER_CLIENT_ID:
        logger.info("[1/3] 네이버 쇼핑 API로 상품 수집...")
        products = scrape_deals(max_items=MAX_PRODUCTS_PER_RUN)
    else:
        products = []

    if not products:
        logger.info("[1/3] 네이버 API 미설정 또는 결과 없음 → 쿠팡 홈 폴백...")
        products = await scrape_homepage_deals(max_items=MAX_PRODUCTS_PER_RUN)

    if not products:
        logger.warning("수집된 상품이 없습니다. 파이프라인 종료.")
        return

    save_products(products)

    # 중복 필터링
    posted_ids = load_posted_ids()
    new_products = [p for p in products if _product_key(p) not in posted_ids]
    skipped = len(products) - len(new_products)
    if skipped:
        logger.info(f"  → 이미 포스팅된 상품 {skipped}개 제외")
    if not new_products:
        logger.warning("새 상품이 없습니다 (전부 중복). 파이프라인 종료.")
        return
    logger.info(f"  → {len(new_products)}개 새 상품 수집 완료")

    # 2단계: AI 콘텐츠 생성
    logger.info("[2/3] AI 게시글 생성...")
    contents = generate_posts_batch(new_products)
    logger.info(f"  → {len(contents)}개 게시글 생성 완료")

    # 3단계: 쓰레드 포스팅 (로그인 1회로 전체 처리)
    logger.info("[3/3] 쓰레드 포스팅...")
    try:
        posted_urls = await post_all_products(contents)
        # 성공한 상품만 posted_ids에 저장
        for url in posted_urls:
            posted_ids.add(url[:80] if url else "")
        posted_ids.discard("")
        save_posted_ids(posted_ids)
        logger.info(f"  → {len(posted_urls)}개 포스팅 완료, 중복 방지 목록 저장")
    except Exception as e:
        logger.error(f"포스팅 오류: {e}")

    logger.info("파이프라인 완료!")


def run_once():
    """동기 wrapper"""
    asyncio.run(run_pipeline())


def run_scheduled():
    """스케줄 모드 - 설정된 시간에 자동 실행"""
    logger.info(f"스케줄 모드 시작 - 실행 시간: {', '.join(SCHEDULE_TIMES)}")

    for t in SCHEDULE_TIMES:
        schedule.every().day.at(t).do(run_once)

    logger.info("스케줄러 대기 중... (Ctrl+C로 종료)")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="쿠팡 → 쓰레드 자동 포스팅 파이프라인")
    parser.add_argument("--schedule", action="store_true", help="스케줄 모드로 실행")
    args = parser.parse_args()

    if args.schedule:
        run_scheduled()
    else:
        run_once()
