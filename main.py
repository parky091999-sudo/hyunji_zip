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
from config import SCHEDULE_TIMES, MAX_PRODUCTS_PER_RUN, LOG_DIR, NAVER_CLIENT_ID, DATA_DIR, YOUTUBE_API_KEY
from scraper.coupang import scrape_homepage_deals
from scraper.naver_shopping import scrape_deals, save_products
from generator.content import generate_posts_batch
from poster.threads import post_all_products
from poster.comment_replier import add_recent_post, check_and_reply_comments
from poster.engager import run_engagement_session

POSTED_IDS_PATH  = os.path.join(DATA_DIR, "posted_ids.json")
FEED_POSTS_PATH  = os.path.join(DATA_DIR, "feed_posts.json")
QUEUE_PATH       = os.path.join(DATA_DIR, "priority_queue.json")


# ── 우선순위 큐 관리 ──────────────────────────────────────────────────────────

def load_priority_queue() -> list:
    if not os.path.exists(QUEUE_PATH):
        return []
    with open(QUEUE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_priority_queue(queue: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


def pop_from_queue() -> dict | None:
    """큐에서 최고 우선순위 항목 1개를 꺼내 반환 (pop)"""
    queue = load_priority_queue()
    if not queue:
        return None
    queue.sort(key=lambda x: (x.get("priority", 99), x.get("added_at", "")))
    entry = queue.pop(0)
    save_priority_queue(queue)
    src = entry.get("source", "?")
    acct = f" (@{entry['benchmark_account']})" if "benchmark_account" in entry else ""
    logger.info(f"  큐 팝: priority={entry.get('priority')} / {src}{acct}")
    return entry.get("product")


# ── 피드 데이터 관리 ─────────────────────────────────────────────────────────

def load_feed_posts() -> list[dict]:
    if not os.path.exists(FEED_POSTS_PATH):
        return []
    with open(FEED_POSTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_feed_posts(posts: list[dict]):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(FEED_POSTS_PATH, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


def append_feed_entries(contents: list[dict], status: str = "generated") -> list[dict]:
    """콘텐츠 목록을 feed_posts.json 맨 앞에 추가"""
    now = datetime.now().isoformat()
    new_entries = [
        {
            "timestamp":     now,
            "product_code":  c.get("product_code", ""),
            "product_name":  c.get("product", {}).get("name", ""),
            "product_image": c.get("product", {}).get("image_url", ""),
            "product_url":   c.get("product", {}).get("product_url", ""),
            "post_text":     c.get("post_text_1", ""),
            "threads_url":   None,
            "status":        status,
        }
        for c in contents if c
    ]
    existing = load_feed_posts()
    merged   = new_entries + existing
    save_feed_posts(merged[:200])  # 최근 200개만 보관
    return new_entries


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
    import random as _random
    skip_delay = os.getenv("SKIP_DELAY", "false").lower() == "true"
    if not skip_delay:
        delay_min = _random.randint(0, 120)  # 9:00~11:00 KST 사이 랜덤 포스팅
        if delay_min > 0:
            logger.info(f"랜덤 딜레이: {delay_min}분 대기 중...")
            await asyncio.sleep(delay_min * 60)

    logger.info("=" * 50)
    logger.info(f"파이프라인 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 50)

    # 1단계: 상품 선정 (우선순위 큐 → 자동 수집)
    products = []

    queue      = load_priority_queue()
    has_p1     = any(x.get("priority", 99) == 1 for x in queue)
    has_p2     = any(x.get("priority", 99) == 2 for x in queue)
    queue_size = len(queue)

    # 벤치마킹: 큐가 3개 미만이면 보충 시도
    if queue_size < 3:
        logger.info(f"[1/3] 큐 잔여 {queue_size}개 → 벤치마킹 계정 스캔...")
        try:
            from scraper.threads_benchmark import run_benchmark
            added = run_benchmark()
            if added:
                # 큐 다시 로드
                queue  = load_priority_queue()
                has_p1 = any(x.get("priority", 99) == 1 for x in queue)
                has_p2 = any(x.get("priority", 99) == 2 for x in queue)
        except Exception as e:
            logger.warning(f"  벤치마킹 오류 (계속 진행): {e}")

    # 우선순위 큐에서 상품 선정
    # P1(수동): 항상 우선 사용
    # P2(벤치마크): 70% 확률로 사용 (30%는 자동 수집으로 신선도 유지)
    import random as _random
    use_queue = (
        has_p1
        or (has_p2 and _random.random() < 0.70)
    )

    if use_queue and queue:
        logger.info("[1/3] 우선순위 큐에서 상품 선정...")
        product = pop_from_queue()
        if product:
            products = [product]
            src_tag = "(수동)" if has_p1 else "(벤치마크)"
            logger.info(f"  → 큐 상품 선정 {src_tag}: {product.get('name', '')[:40]}")

    if not products:
        logger.info("[1/3] 자동 수집 모드...")
        if YOUTUBE_API_KEY:
            logger.info("  YouTube 트렌딩 상품 수집...")
            from scraper.youtube_trending import scrape_trending_products
            products = scrape_trending_products(max_items=MAX_PRODUCTS_PER_RUN)
            logger.info(f"  → YouTube {len(products)}개 수집")

        if len(products) < MAX_PRODUCTS_PER_RUN and NAVER_CLIENT_ID:
            needed = MAX_PRODUCTS_PER_RUN - len(products)
            logger.info(f"  네이버 쇼핑으로 {needed}개 보충...")
            extra = scrape_deals(max_items=needed)
            products.extend(extra)

        if not products:
            logger.info("  YouTube/네이버 결과 없음 → 쿠팡 홈 폴백...")
            products = await scrape_homepage_deals(max_items=MAX_PRODUCTS_PER_RUN)

        if not products:
            logger.info("  쿠팡 홈 폴백도 없음 → 프리셋 리스트 확인...")
            try:
                from scraper.preset import get_next_preset_product
                posted_ids_now = load_posted_ids()
                preset_product = get_next_preset_product(posted_ids_now)
                if preset_product:
                    products = [preset_product]
                    logger.info(f"  → 프리셋 상품 사용: {preset_product.get('name', '')[:40]}")
            except Exception as e:
                logger.warning(f"  프리셋 폴백 오류: {e}")

    if not products:
        logger.warning("수집된 상품이 없습니다 (프리셋 포함). 파이프라인 종료.")
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
    logger.info("[2/5] AI 게시글 생성...")
    contents = generate_posts_batch(new_products)
    logger.info(f"  → {len(contents)}개 게시글 생성 완료")

    # 피드 데이터 저장 (포스팅 전 "generated" 상태로 기록)
    feed_entries = append_feed_entries(contents, status="generated")
    logger.info(f"  → 피드 데이터 저장: {len(feed_entries)}개")

    # 3단계: 쓰레드 포스팅
    logger.info("[3/5] 쓰레드 포스팅...")
    posting_ok = False
    try:
        posted_urls, story_post_infos = await post_all_products(contents)
        # 성공한 상품만 posted_ids에 저장
        for url in posted_urls:
            posted_ids.add(url[:80] if url else "")
        posted_ids.discard("")
        save_posted_ids(posted_ids)
        # story 게시글 URL + post_id 등록 (댓글 감지 대상)
        for info in story_post_infos:
            add_recent_post(info.get("post_url", ""), info.get("post_id", ""), "story")
        logger.info(f"  → {len(posted_urls)}개 포스팅 완료")
        posting_ok = len(posted_urls) > 0

        # 포스팅 성공 시 피드 상태 + threads_url 업데이트
        if posting_ok:
            existing = load_feed_posts()
            codes = {e["product_code"] for e in feed_entries}
            url_map = {
                contents[i].get("product_code", ""): info.get("post_url")
                for i, info in enumerate(story_post_infos)
            }
            for entry in existing:
                if entry["product_code"] in codes and entry["status"] == "generated":
                    if entry.get("timestamp", "") >= feed_entries[0].get("timestamp", ""):
                        entry["status"] = "posted"
                        post_url = url_map.get(entry["product_code"])
                        if post_url:
                            entry["threads_url"] = post_url
            save_feed_posts(existing)
    except Exception as e:
        logger.error(f"포스팅 오류: {e} — 페이지 업데이트는 계속 진행")

    # 4단계: 이전 게시글 댓글 감지 → 자동 대댓글
    logger.info("[4/5] 댓글 대댓글 확인...")
    try:
        await check_and_reply_comments()
    except Exception as e:
        logger.error(f"대댓글 오류: {e}")

    # 5단계: 타 계정 게시글에 자연스러운 댓글 (노출 확대)
    logger.info("[5/5] 타 계정 게시글 댓글 활동...")
    try:
        await run_engagement_session(max_comments=10)
    except Exception as e:
        logger.error(f"댓글 활동 오류: {e}")

    # 페이지 자동 생성 (상품 페이지 + 피드 페이지)
    logger.info("페이지 업데이트 중...")
    try:
        import generate_page
        import generate_feed_page
        generate_page.main()
        generate_feed_page.main()
        logger.info("  → docs/index.html, docs/feed.html 생성 완료")
    except Exception as e:
        logger.error(f"페이지 생성 오류: {e}")

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
    parser.add_argument("--no-delay", action="store_true", help="랜덤 딜레이 없이 즉시 실행 (테스트용)")
    args = parser.parse_args()

    if args.no_delay:
        os.environ["SKIP_DELAY"] = "true"

    if args.schedule:
        run_scheduled()
    else:
        run_once()
