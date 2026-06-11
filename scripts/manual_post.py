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
    # KST 게이트: 저녁 골든(19시~) 정렬, 14시 이후 도착은 19시까지 대기, 새벽 차단
    from scripts.post_gate import kst_gate
    if not await kst_gate(19.0, 23.5, max_wait_h=5.0, label="manual"):
        return
    skip_delay = os.getenv("SKIP_DELAY", "false").lower() == "true"
    if not skip_delay:
        delay = random.randint(0, 15)  # 최대 15분 (기존 55분에서 축소)
        if delay:
            logger.info(f"랜덤 딜레이: {delay}분 대기...")
            await asyncio.sleep(delay * 60)

    logger.info("=" * 50)
    logger.info(f"수동 포스팅 시작: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    logger.info("=" * 50)

    # 오늘 이미 수동 포스팅 '성공'했으면 건너뜀 (실패 건은 보정 크론이 재시도)
    today_str = datetime.now(KST).strftime("%Y-%m-%d")
    if os.path.exists(FEED_POSTS_PATH):
        feed = _load_json(FEED_POSTS_PATH, [])
        if any(
            p.get("timestamp", "")[:10] == today_str
            and p.get("post_type") == "manual"
            and p.get("status") == "posted"
            for p in feed
        ):
            logger.info(f"오늘({today_str}) 수동 포스팅 이미 완료 — 건너뜀")
            return

    queue = _load_json(QUEUE_PATH, [])
    if not queue:
        logger.info("수동 큐가 비어 있습니다 — 종료")
        return

    # 첫 번째 항목 참조 — 포스팅 '성공' 시에만 큐에서 제거 (실패 시 보정 크론이 재시도)
    MAX_FAILS = 3

    def _record_failure(reason: str) -> None:
        """실패 횟수 기록. MAX_FAILS 도달 시 큐에서 폐기해 무한 재시도 방지."""
        queue[0]["fail_count"] = int(queue[0].get("fail_count", 0) or 0) + 1
        if queue[0]["fail_count"] >= MAX_FAILS:
            dropped = queue.pop(0)
            logger.error(
                f"수동 큐 항목 {MAX_FAILS}회 연속 실패({reason}) → 폐기: "
                f"{dropped.get('product', {}).get('name', '')[:40]}"
            )
        else:
            logger.warning(
                f"수동 포스팅 실패({reason}) — 큐 유지, "
                f"재시도 {queue[0]['fail_count']}/{MAX_FAILS}"
            )
        _save_json(QUEUE_PATH, queue)

    item = queue[0]

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

    if not post_text.strip():
        logger.error("포스팅 텍스트 생성 실패")
        _record_failure("텍스트 생성 실패")
        return

    logger.info(f"포스팅: {product.get('name', '')[:40]} [{code}]")

    # ── 이미지 보충: 원본 이미지 없으면 네이버 검색으로 확보 (010 메론 무사진 재발 방지)
    if not image_url:
        try:
            from scraper.naver_shopping import fetch_image_by_name
            image_url = fetch_image_by_name(product.get("name", ""))
            if image_url:
                product["image_url"] = image_url
        except Exception as e:
            logger.warning(f"이미지 보충 실패: {e}")

    # ── 언어 게이트: 포스팅 직전 외국어 최종 차단 (012 한자 유출 재발 방지)
    from generator.content import ensure_korean
    post_text = ensure_korean(post_text, product, code)

    # AI 이미지 생성 — 성공 시 교체, 실패 시 원본 유지
    try:
        from generator.image_gen import generate_and_upload_images
        ai_imgs = generate_and_upload_images(product, post_text)
        if ai_imgs:
            detail_imgs = ai_imgs
            # 원본 image_url 은 비우지 않고 carousel 전멸 시 폴백으로 사용
            logger.info(f"AI 이미지 {len(ai_imgs)}장으로 교체")
        else:
            logger.info("AI 이미지 생성 실패 → 원본 이미지 유지")
    except Exception as e:
        logger.warning(f"AI 이미지 생성 오류: {e}")

    from poster.threads import post_thread_api, find_recent_post_by_marker
    from poster.comment_replier import add_recent_post

    # ── 멱등 가드: 동일 코드 게시글이 이미 있으면 게시 생략, 기록만 복구
    result = None
    already = None
    if code:
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

    if result:
        # 성공 — 이제 큐에서 제거
        queue.pop(0)
        _save_json(QUEUE_PATH, queue)

        posted_ids = set(_load_json(POSTED_IDS_PATH, []))
        key = _product_key(product)
        if key:
            posted_ids.add(key)
        _save_json(POSTED_IDS_PATH, sorted(posted_ids))
        # 페이지 노출용 posted 플래그
        if code:
            from generator.registry import mark_posted
            from generator.content import generate_short_name
            short_name = generate_short_name(product)
            mark_posted(code, category=product.get("category_hint", ""), short_name=short_name)
    else:
        # 실패 — 큐 유지 + 실패 횟수 기록 (보정 크론이 재시도)
        _record_failure("Threads API 오류")

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
        add_recent_post(post_url, post_id, "manual", code)
        # 첫 댓글로 상품 페이지 링크 (가드복구 글은 이미 달려있을 수 있어 스킵)
        if code and not already:
            try:
                from poster.threads import post_product_link_comment
                post_product_link_comment(post_id, code)
            except Exception as e:
                logger.warning(f"링크 댓글 실패(무시): {e}")

    logger.info(f"수동 포스팅 완료: {status} | {post_url or '(URL 없음)'}")

    try:
        import generate_page, generate_feed_page
        generate_page.main()
        generate_feed_page.main()
    except Exception as e:
        logger.error(f"페이지 생성 오류: {e}")


if __name__ == "__main__":
    asyncio.run(run())
