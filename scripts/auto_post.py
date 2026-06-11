"""
자동 포스팅 — 매일 오전 8:05 KST 실행
1순위: pending_post.json 의 승인(또는 미반려) 후보 사용
2순위: 실시간 수집 폴백 (main.py 방식)
"""
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import DATA_DIR, LOG_DIR, MAX_PRODUCTS_PER_RUN, YOUTUBE_API_KEY, NAVER_CLIENT_ID

PENDING_PATH    = os.path.join(DATA_DIR, "pending_post.json")
POSTED_IDS_PATH = os.path.join(DATA_DIR, "posted_ids.json")
FEED_POSTS_PATH = os.path.join(DATA_DIR, "feed_posts.json")

KST = timezone(timedelta(hours=9))

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "auto_post.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("auto_post")


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


def _mark_pending_used(product_url: str) -> None:
    """포스팅 완료된 후보의 status를 'used'로 업데이트"""
    pending = _load_json(PENDING_PATH, {})
    for c in pending.get("candidates", []):
        if c.get("product", {}).get("product_url", "") == product_url:
            c["status"] = "used"
            break
    _save_json(PENDING_PATH, pending)


def _pick_from_pending() -> dict | None:
    """pending_post.json 에서 오늘/어제 날짜 후보 중 포스팅할 것 선택 (카테고리 분산)"""
    pending = _load_json(PENDING_PATH, {})
    today = datetime.now(KST).strftime("%Y-%m-%d")
    yesterday = (datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d")

    file_date = pending.get("for_date", "없음")
    if file_date not in (today, yesterday):
        logger.info(f"  pending_post 날짜 불일치 (기대: {today}, 파일: {file_date})")
        return None
    if file_date == yesterday:
        logger.info(f"  pending_post 날짜 1일 초과 (어제 후보 사용)")

    candidates = pending.get("candidates", [])
    if not candidates:
        logger.info("  pending_post 후보 없음")
        return None

    posted_ids = set(_load_json(POSTED_IDS_PATH, []))

    def _not_posted(c: dict) -> bool:
        url = c.get("product", {}).get("product_url", "")
        return not (url and url[:80] in posted_ids)

    # 사용 가능한 후보 (반려되지 않은 것)
    available = [c for c in candidates if c.get("status") != "rejected" and _not_posted(c)]

    if not available:
        logger.info("  pending 후보 전부 이미 포스팅/반려됨 → 실시간 수집으로 폴백")
        return None

    # 우선: 명시 승인된 것
    approved = [c for c in available if c.get("status") == "approved"]
    if approved:
        selected = approved[0]
        cat = selected.get("product", {}).get("category_hint", "기타")
        logger.info(f"  [승인된 후보] {selected['product'].get('name', '')[:40]} ({cat})")
        return selected

    # 기본: 첫 번째 미사용 (preselect에서 이미 카테고리 균형)
    selected = available[0]
    cat = selected.get("product", {}).get("category_hint", "기타")
    logger.info(f"  [기본 후보] {selected['product'].get('name', '')[:40]} ({cat})")
    return selected


async def _collect_fallback() -> dict | None:
    """pending_post 없을 때 실시간 수집"""
    posted_ids = set(_load_json(POSTED_IDS_PATH, []))
    products = []

    if YOUTUBE_API_KEY:
        from scraper.youtube_trending import scrape_trending_products
        products = scrape_trending_products(max_items=MAX_PRODUCTS_PER_RUN)

    if not products and NAVER_CLIENT_ID:
        from scraper.naver_shopping import scrape_deals
        products = scrape_deals(max_items=MAX_PRODUCTS_PER_RUN)

    if not products:
        from scraper.coupang import scrape_homepage_deals
        products = await scrape_homepage_deals(max_items=MAX_PRODUCTS_PER_RUN)

    if not products:
        from scraper.preset import get_next_preset_product
        p = get_next_preset_product(posted_ids)
        if p:
            products = [p]

    new = [p for p in products if _product_key(p) not in posted_ids]
    if not new:
        return None

    from generator.content import generate_post
    content = generate_post(new[0])
    if not content:
        return None

    return {
        "product":       content["product"],
        "post_text":     content["post_text_1"],
        "image_url":     content.get("image_url", ""),
        "detail_images": content.get("detail_images", []),
        "product_code":  content.get("product_code", ""),
        "status":        "pending",
    }


async def run():
    import random
    # KST 게이트: 새벽 차단, 11시 전 도착 시 11시까지 대기(최대 4h) — 점심 골든타임 정렬
    from scripts.post_gate import kst_gate
    if not await kst_gate(11.0, 23.0, max_wait_h=4.0, label="auto"):
        return
    skip_delay = os.getenv("SKIP_DELAY", "false").lower() == "true"
    if not skip_delay:
        delay = random.randint(0, 15)  # 최대 15분 (기존 55분에서 축소)
        if delay:
            logger.info(f"랜덤 딜레이: {delay}분 대기...")
            await asyncio.sleep(delay * 60)

    logger.info("=" * 50)
    logger.info(f"자동 포스팅 시작: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    logger.info("=" * 50)

    # 오늘 이미 아침 자동 포스팅 완료했으면 건너뜀 (post_type이 "auto" 또는 "auto_evening")
    today_str = datetime.now(KST).strftime("%Y-%m-%d")
    if os.path.exists(FEED_POSTS_PATH):
        feed = json.load(open(FEED_POSTS_PATH, encoding="utf-8"))
        auto_posted_today = any(
            p.get("timestamp", "")[:10] == today_str
            and p.get("post_type") == "auto"
            and p.get("status") == "posted"
            for p in feed
        )
        if auto_posted_today:
            logger.info(f"오늘({today_str}) 아침 자동 포스팅 완료 — 건너뜀")
            return

    # 1. pending_post.json 에서 후보 선택
    from_pending = False
    candidate = _pick_from_pending()

    # 2. 없으면 실시간 수집
    if not candidate:
        logger.info("[폴백] 실시간 수집 모드...")
        candidate = await _collect_fallback()
    else:
        from_pending = True

    if not candidate:
        logger.warning("포스팅할 상품 없음 — 종료")
        return

    # 3. 편집된 텍스트면 포스팅 전 AI 다듬기
    if candidate.get("edited") and candidate.get("post_text"):
        logger.info("편집된 텍스트 감지 → AI 다듬기 실행...")
        try:
            from generator.content import polish_post
            polished = polish_post(candidate["post_text"], candidate.get("product", {}))
            if polished:
                candidate["post_text"] = polished
                logger.info("  다듬기 완료")
            else:
                logger.info("  다듬기 실패 → 편집본 그대로 사용")
        except Exception as e:
            logger.warning(f"  다듬기 오류: {e}")

    # 4. 포스팅
    from poster.threads import post_thread_api
    from poster.comment_replier import add_recent_post, check_and_reply_comments
    from poster.engager import run_engagement_session

    product     = candidate["product"]
    post_text   = candidate["post_text"]
    image_url   = candidate.get("image_url") or product.get("image_url", "")
    detail_imgs = candidate.get("detail_images", [])
    code        = candidate.get("product_code", "")

    # registry 등록 보장
    from generator.registry import assign_code
    registered_code = assign_code(
        product.get("product_url", ""),
        product.get("name", ""),
        product.get("image_url", ""),
    ) or ""
    if not code:
        code = registered_code
        if code and "프로필 링크에서" not in post_text:
            post_text += f"\n\n제품 정보는 프로필 링크에서 [{code}] 검색 👆"

    # 이미지 보충
    if not image_url:
        try:
            from scraper.naver_shopping import fetch_image_by_name
            image_url = fetch_image_by_name(product.get("name", ""))
            if image_url:
                product["image_url"] = image_url
        except Exception as e:
            logger.warning(f"이미지 보충 실패: {e}")

    # 언어 게이트
    from generator.content import ensure_korean
    post_text = ensure_korean(post_text, product, code)

    # AI 이미지 생성
    try:
        from generator.image_gen import generate_and_upload_images
        ai_imgs = generate_and_upload_images(product, post_text)
        if ai_imgs:
            detail_imgs = ai_imgs
            logger.info(f"AI 이미지 {len(ai_imgs)}장으로 교체")
        else:
            logger.info("AI 이미지 생성 실패 → 원본 이미지 유지")
    except Exception as e:
        logger.warning(f"AI 이미지 생성 오류: {e}")

    logger.info(f"포스팅: {product.get('name', '')[:40]} [{code}]")

    # 멱등 가드
    result = None
    already = None
    if code:
        from poster.threads import find_recent_post_by_marker
        already = find_recent_post_by_marker(f"[{code}] 검색")
        if already:
            logger.warning(f"Threads에 [{code}] 게시글 이미 존재 → 중복 게시 차단, 기록만 복구")
            result = already

    if result is None:
        try:
            result = post_thread_api(
                post_text=post_text,
                image_url="" if (detail_imgs and detail_imgs != [image_url]) else image_url,
                detail_images=detail_imgs,
                fallback_image_url=image_url,
            )
        except Exception as e:
            logger.error(f"포스팅 실패: {e}")
            result = None

    post_url = result.get("post_url") if result else None
    post_id  = result.get("post_id")  if result else None
    status   = "posted" if result else "failed"

    # posted_ids 업데이트
    if result:
        posted_ids = set(_load_json(POSTED_IDS_PATH, []))
        key = _product_key(product)
        if key:
            posted_ids.add(key)
        _save_json(POSTED_IDS_PATH, sorted(posted_ids))
        if code:
            from generator.registry import mark_posted
            from generator.content import generate_short_name
            short_name = generate_short_name(product)
            mark_posted(code, category=product.get("category_hint", ""), short_name=short_name)
        if from_pending:
            _mark_pending_used(product.get("product_url", ""))

    # feed_posts 업데이트
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
        "post_type":     "auto",
    })
    _save_json(FEED_POSTS_PATH, feed[:200])

    if post_url and post_id:
        add_recent_post(post_url, post_id, "story", code)
        # 첫 댓글로 상품 페이지 링크 (가드복구 글은 이미 달려있을 수 있어 스킵)
        if code and not already:
            try:
                from poster.threads import post_product_link_comment
                post_product_link_comment(post_id, code)
            except Exception as e:
                logger.warning(f"링크 댓글 실패(무시): {e}")

    logger.info(f"포스팅 완료: {status} | {post_url or '(URL 없음)'}")

    # 댓글 대댓글
    try:
        await check_and_reply_comments()
    except Exception as e:
        logger.error(f"대댓글 오류: {e}")

    # 타 계정 활동
    try:
        await run_engagement_session(max_comments=10)
    except Exception as e:
        logger.error(f"댓글 활동 오류: {e}")

    # 페이지 업데이트
    try:
        import generate_page, generate_feed_page
        generate_page.main()
        generate_feed_page.main()
    except Exception as e:
        logger.error(f"페이지 생성 오류: {e}")

    logger.info("자동 포스팅 완료!")


if __name__ == "__main__":
    asyncio.run(run())
