"""
저녁 자동 포스팅 — 매일 오후 7시 KST 실행
1순위: pending_post.json 의 승인(또는 미반려) 후보 사용 (두 번째)
2순위: 실시간 수집 폴백
"""
import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import DATA_DIR, LOG_DIR, MAX_PRODUCTS_PER_RUN, YOUTUBE_API_KEY, NAVER_CLIENT_ID, photo_gate_days

PENDING_PATH    = os.path.join(DATA_DIR, "pending_post.json")
QUEUE_PATH      = os.path.join(DATA_DIR, "manual_queue.json")
POSTED_IDS_PATH = os.path.join(DATA_DIR, "posted_ids.json")
FEED_POSTS_PATH = os.path.join(DATA_DIR, "feed_posts.json")

KST = timezone(timedelta(hours=9))

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "evening_post.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("evening_post")


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

    # 크론 지연(실측 7~12h)으로 preselect가 저장한 for_date(=내일)가 실제 게시일보다
    # 앞서는 드리프트가 상시 발생 → today/yesterday 고정 비교는 매일 불일치해 실시간
    # 폴백(저품질 상품 → 본문 게이트 실패 → 미발행)으로 샜다(2026-07-16 규명).
    # 후보는 날짜와 무관하게 유효(posted_ids가 재게시 차단)하므로 '어제 이후'를 폭넓게 수용.
    file_date = pending.get("for_date", "")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", file_date) or file_date < yesterday:
        logger.info(f"  pending_post 날짜 부적합 (기대: >={yesterday}, 파일: {file_date or '없음'})")
        return None
    if file_date < today:
        logger.info(f"  pending_post 과거 후보 사용 (파일: {file_date})")
    elif file_date > today:
        logger.info(f"  pending_post 선행 후보 사용 (파일: {file_date}) — 크론 지연 드리프트 흡수")

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
    """pending_post 없을 때 실시간 수집. 각 폴백 단계마다 posted 필터링 후
    fresh가 0이면 다음 폴백으로 넘어가야 chain이 끊기지 않음."""
    posted_ids = set(_load_json(POSTED_IDS_PATH, []))
    new: list = []

    def _fresh(ps: list) -> list:
        return [p for p in ps if _product_key(p) not in posted_ids]

    if YOUTUBE_API_KEY:
        from scraper.youtube_trending import scrape_trending_products
        new = _fresh(scrape_trending_products(max_items=MAX_PRODUCTS_PER_RUN))

    if not new and NAVER_CLIENT_ID:
        from scraper.naver_shopping import scrape_deals
        new = _fresh(scrape_deals(max_items=MAX_PRODUCTS_PER_RUN))

    if not new:
        from scraper.coupang import scrape_homepage_deals
        new = _fresh(await scrape_homepage_deals(max_items=MAX_PRODUCTS_PER_RUN))

    if not new:
        from scraper.preset import get_next_preset_product
        p = get_next_preset_product(posted_ids)
        if p:
            new = [p]

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
    # KST 게이트: 저녁 19:00~21:30 (저녁 황금시간)
    from scripts.post_gate import kst_gate, photo_posted_within, coupang_posted_today
    if not await kst_gate(19.0, 21.5, max_wait_h=4.0, label="evening"):
        return
    # 페이즈별 사진 상품글 간격(2026-07-13): growth=3일, 수익화(7/31~)=격일. config에서 자동 전환
    if photo_posted_within(days=photo_gate_days(), label="evening"):
        return
    # 하루 1쿠파스 상한 — 오늘 영상(osmu)이 먼저 나갔으면 사진은 다음날로 미뤄 겹침 방지
    if coupang_posted_today(label="evening"):
        return
    skip_delay = os.getenv("SKIP_DELAY", "false").lower() == "true"
    if not skip_delay:
        delay = random.randint(0, 10)
        if delay:
            logger.info(f"랜덤 딜레이: {delay}분 대기...")
            await asyncio.sleep(delay * 60)

    logger.info("=" * 50)
    logger.info(f"저녁 포스팅 시작: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    logger.info("=" * 50)

    # 오늘 이미 저녁 포스팅 완료했으면 건너뜀
    today_str = datetime.now(KST).strftime("%Y-%m-%d")
    if os.path.exists(FEED_POSTS_PATH):
        feed = json.load(open(FEED_POSTS_PATH, encoding="utf-8"))
        if any(
            p.get("timestamp", "")[:10] == today_str
            and p.get("post_type") == "auto_evening"
            and p.get("status") == "posted"
            for p in feed
        ):
            logger.info(f"오늘({today_str}) 저녁 포스팅 이미 완료 — 건너뜀")
            return

    # 1. pending_post.json 에서 후보 선택
    from_pending = False
    from_queue = False
    candidate = _pick_from_pending()

    # 2. 없으면 manual_queue 사용 (큐 있으면 폴백보다 우선 — 검증된 본문/이미지)
    if not candidate:
        queue = _load_json(QUEUE_PATH, [])
        if queue:
            cand = queue[0]
            cand.setdefault("status", "pending")
            candidate = cand
            from_queue = True
            logger.info(f"[큐 사용] {cand.get('product',{}).get('name','')[:40]}")

    # 3. 없으면 실시간 수집
    if not candidate:
        logger.info("[폴백] 실시간 수집 모드...")
        candidate = await _collect_fallback()
    elif from_queue:
        pass
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
    if not code or code == "preview":
        code = registered_code
        if code and f"[{code}]" not in post_text:
            post_text += f"\n\n[{code}] 정보는 댓글에 👇"

    # 이미지 보충
    if not image_url:
        try:
            from scraper.naver_shopping import fetch_image_by_name
            image_url = fetch_image_by_name(product.get("name", ""))
            if image_url:
                product["image_url"] = image_url
                if code and code not in ("", "preview"):
                    from generator.registry import update_image
                    update_image(code, image_url, verified=False)
                    logger.warning(f"이미지 이름검색 보충 — 실제 상품 일치 확인 필요 [{code}]")
        except Exception as e:
            logger.warning(f"이미지 보충 실패: {e}")

    # 언어 + 잘림 + 외국어 게이트
    from generator.content import ensure_korean, ensure_not_truncated
    post_text = ensure_korean(post_text, product, code)
    post_text = ensure_not_truncated(post_text, product, code)
    if not post_text:
        logger.warning(f"본문 게이트 실패 → 게시 skip [{code}]: {product.get('name','')[:40]}")
        return

    # 이미지 구성(2026-07-13 개편): 실사진 우선, AI는 폴백 — auto_post와 동일
    base = [image_url] if (image_url and image_url.startswith("http")) else []
    real_carousel = [u for u in (detail_imgs or []) if u and u.startswith("http")]
    if len(real_carousel) >= 2:
        detail_imgs = real_carousel
        logger.info(f"실사진 carousel {len(detail_imgs)}장 — AI 생성 생략")
    else:
        try:
            from generator.image_gen import generate_and_upload_images
            ai_imgs = generate_and_upload_images(product, post_text)
            if ai_imgs:
                detail_imgs = base + ai_imgs
                logger.info(f"실사진 부족 → 원본 1장 + AI 보조 {len(ai_imgs)}장 = {len(detail_imgs)}장 carousel")
            elif base:
                detail_imgs = base
                logger.info("AI 생성 실패 → 원본만 단일 이미지 게시")
        except Exception as e:
            logger.warning(f"AI 이미지 생성 오류: {e}")

    logger.info(f"포스팅: {product.get('name', '')[:40]} [{code}]")

    # 발행 직전 재판정 — 게이트 통과 후 생성하는 몇 분 사이 osmu 영상이 먼저 나가는
    # 레이스 차단(2026-07-16 사진+영상 같은 날 겹침 실사고). 최신 feed를 당겨 다시 확인.
    from scripts.post_gate import refresh_shared_feed
    refresh_shared_feed(label="evening")
    if coupang_posted_today(label="evening(직전 재판정)"):
        return

    # 멱등 가드
    result = None
    already = None
    if code:
        from poster.threads import find_recent_post_by_marker
        already = find_recent_post_by_marker(f"[{code}]")
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
        if from_queue:
            q = _load_json(QUEUE_PATH, [])
            if q:
                q.pop(0)
                _save_json(QUEUE_PATH, q)

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
        "post_type":     "auto_evening",  # 저녁 포스팅 표시
    })
    _save_json(FEED_POSTS_PATH, feed[:200])

    if post_url and post_id:
        add_recent_post(post_url, post_id, "story", code)
        # 첫 댓글로 상품 페이지 링크 (가드복구 글은 이미 달려있을 수 있어 스킵)
        if code and not already:
            try:
                from poster.threads import post_product_link_comment
                post_product_link_comment(post_id, code, product_url=product.get("product_url"))
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

    logger.info("저녁 포스팅 완료!")


if __name__ == "__main__":
    asyncio.run(run())
