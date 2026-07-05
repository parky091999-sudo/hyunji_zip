"""
사전 상품 선정 — 매일 오전 9시 KST 실행
내일 자동포스팅 후보 3개를 선정하여 data/pending_post.json 에 저장
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

from config import (
    DATA_DIR, LOG_DIR, MAX_PRODUCTS_PER_RUN,
    YOUTUBE_API_KEY, NAVER_CLIENT_ID,
)
from generator.content import generate_post

PENDING_PATH     = os.path.join(DATA_DIR, "pending_post.json")
POSTED_IDS_PATH  = os.path.join(DATA_DIR, "posted_ids.json")
REJECTED_PATH    = os.path.join(DATA_DIR, "rejected_products.json")
CANDIDATES_COUNT = 6  # 하루 2개씩 포스팅하므로 여유있게 6개 준비

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


def _extract_page_key(url: str) -> str:
    m = re.search(r"pageKey=(\d+)", url or "")
    return m.group(1) if m else ""


def _load_rejected_urls() -> set[str]:
    if not os.path.exists(REJECTED_PATH):
        return set()
    urls = json.load(open(REJECTED_PATH, encoding="utf-8")).get("urls", [])
    # pageKey 기준으로 비교 (ctag·lptag 차이 무시)
    keys = set()
    for u in urls:
        pk = _extract_page_key(u)
        if pk:
            keys.add(pk)
        else:
            keys.add(u)
    return keys


def _product_key(product: dict) -> str:
    url = product.get("product_url", "")
    return url[:80] if url else product.get("name", "")[:20]


async def _collect_products(need: int, posted_ids: set[str], rejected_urls: set[str] | None = None) -> list[dict]:
    rejected_urls = rejected_urls or set()
    products = []

    def _is_rejected(p: dict) -> bool:
        url = p.get("product_url", "")
        if not url:
            return False
        pk = _extract_page_key(url)
        return (pk and pk in rejected_urls) or url in rejected_urls

    if YOUTUBE_API_KEY:
        logger.info("YouTube 트렌딩 수집...")
        from scraper.youtube_trending import scrape_trending_products
        yt = scrape_trending_products(max_items=need)
        for p in yt:
            if _product_key(p) not in posted_ids and not _is_rejected(p):
                products.append(p)
        logger.info(f"  → YouTube {len(products)}개")

    if len(products) < need and NAVER_CLIENT_ID:
        logger.info(f"네이버 쇼핑으로 {need - len(products)}개 보충...")
        from scraper.naver_shopping import scrape_deals

        # ── 시즌 키워드 + 모멘텀 부스트 ──────────────────────────────────────
        priority_keywords: list[tuple[str, str]] = []
        try:
            from scraper.seasonal_keywords import get_seasonal_keywords
            seasonal = get_seasonal_keywords()
            if seasonal:
                logger.info(f"  시즌 키워드({datetime.now(KST).month}월) {len(seasonal)}개")
                try:
                    from scraper.naver_datalab import get_keyword_momentum
                    kw_only = [kw for kw, _ in seasonal]
                    scores  = get_keyword_momentum(kw_only)
                    # 모멘텀 점수 높은 순으로 시즌 키워드 정렬 (점수 없으면 원래 순서)
                    priority_keywords = sorted(
                        seasonal,
                        key=lambda x: scores.get(x[0], 1.0),
                        reverse=True,
                    )
                    if scores:
                        logger.info(
                            f"  모멘텀 정렬 후 Top3: {[k for k,_ in priority_keywords[:3]]}"
                        )
                except Exception as e:
                    logger.warning(f"  모멘텀 조회 스킵: {e}")
                    priority_keywords = seasonal
        except Exception as e:
            logger.warning(f"  시즌 키워드 스킵: {e}")

        try:
            from scraper.naver_datalab import get_trending_categories
            trending_cats = get_trending_categories(top_n=3)
            logger.info(f"  데이터랩 트렌딩 카테고리: {trending_cats or '없음'}")
        except Exception as e:
            logger.warning(f"데이터랩 카테고리 스킵: {e}")
            trending_cats = None

        extra = scrape_deals(
            max_items=need - len(products),
            trending_cats=trending_cats,
            priority_keywords=priority_keywords,
        )
        for p in extra:
            if _product_key(p) not in posted_ids and p not in products and not _is_rejected(p):
                products.append(p)
        logger.info(f"  → 누적 {len(products)}개")

    if len(products) < need:
        logger.info("쿠팡 홈 폴백...")
        try:
            from scraper.coupang import scrape_homepage_deals
            extra = await scrape_homepage_deals(max_items=need - len(products))
            for p in extra:
                if _product_key(p) not in posted_ids and p not in products and not _is_rejected(p):
                    products.append(p)
        except Exception as e:
            logger.warning(f"쿠팡 홈 스크래퍼 실패 (Playwright 미설치 등): {e}")

    if len(products) < need:
        logger.info("프리셋 리스트 폴백...")
        from scraper.preset import get_next_preset_product
        while len(products) < need:
            p = get_next_preset_product(posted_ids | {_product_key(x) for x in products})
            if not p or _is_rejected(p):
                break
            products.append(p)

    return products[:need]


async def run():
    logger.info("=" * 50)
    logger.info(f"사전선정 시작: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    logger.info("=" * 50)

    tomorrow = (datetime.now(KST) + timedelta(days=1)).strftime("%Y-%m-%d")
    posted_ids    = _load_posted_ids()
    rejected_urls = _load_rejected_urls()

    # 기존 pending_post에서 유효한 후보 유지 (반려/제외 아닌 것)
    existing_good: list[dict] = []
    if os.path.exists(PENDING_PATH):
        with open(PENDING_PATH, encoding="utf-8") as f:
            existing_pending = json.load(f)
        if existing_pending.get("for_date") == tomorrow:
            for c in existing_pending.get("candidates", []):
                url    = c.get("product", {}).get("product_url", "")
                status = c.get("status", "pending")
                pk     = _extract_page_key(url)
                is_blocked   = (pk and pk in rejected_urls) or url in rejected_urls
                is_posted    = bool(url and url[:80] in posted_ids)
                if status not in ("rejected", "excluded", "used") and not is_blocked and not is_posted:
                    existing_good.append(c)
            logger.info(f"기존 유효 후보 {len(existing_good)}개 유지")

    # 기존 후보 중 post_text 없는 것 본문 재생성
    regen_count = 0
    for c in existing_good:
        if not c.get("post_text", "").strip():
            product = c.get("product", {})
            logger.info(f"  기존 후보 본문 재생성: {product.get('name','')[:40]}")
            content = generate_post(product, assign_code_now=False)
            if content:
                c["post_text"] = content.get("post_text_1", "")
                regen_count += 1

    need = CANDIDATES_COUNT - len(existing_good)
    if need <= 0:
        if regen_count > 0:
            pending = {
                "for_date":     tomorrow,
                "generated_at": datetime.now(KST).isoformat(),
                "candidates":   existing_good[:CANDIDATES_COUNT],
            }
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(PENDING_PATH, "w", encoding="utf-8") as f:
                json.dump(pending, f, ensure_ascii=False, indent=2)
            logger.info(f"본문 재생성 저장 완료: {regen_count}개")
        else:
            logger.info(f"후보가 이미 {CANDIDATES_COUNT}개 — 종료")
        return

    # 기존 후보 URL도 중복 방지용으로 posted_ids에 포함
    existing_urls = {c.get("product", {}).get("product_url", "")[:80] for c in existing_good}
    temp_posted   = posted_ids | existing_urls

    products = await _collect_products(need, temp_posted, rejected_urls)
    if not products:
        logger.warning("수집 상품 없음 — 기존 후보만 유지")
        if not existing_good:
            return

    new_candidates: list[dict] = []
    for product in products:
        logger.info(f"콘텐츠 생성: {product.get('name', '')[:40]}")
        content = generate_post(product, assign_code_now=False)
        if not content:
            continue
        new_candidates.append({
            "product":       content["product"],
            "post_text":     content["post_text_1"],
            "image_url":     content.get("image_url", ""),
            "detail_images": content.get("detail_images", []),
            "product_code":  "",
            "status":        "pending",
        })

    all_candidates = existing_good + new_candidates

    # 카테고리별 균형 및 과포화 상품(그라인더, 식기세척기 등) 배제한 후보 선택
    def _select_balanced(candidates: list, count: int) -> list:
        """카테고리별로 균형있게 후보를 선택하고 과포화 키워드 및 중복 상품 배제"""
        if not candidates:
            return []

        # 최근 포스팅 카테고리 빈도 및 과포화 단어 집계
        recent_cat_counts = {}
        saturated_kw = {"그라인더", "후추", "소금", "식기세척기", "식세기", "선풍기", "손풍기", "건조기", "휴지통", "쓰레기통", "마스크", "티스푼"}
        reg_path = os.path.join(DATA_DIR, "product_registry.json")
        if os.path.exists(reg_path):
            try:
                reg_data = json.load(open(reg_path, encoding="utf-8"))
                for v in list(reg_data.get("products", {}).values())[-20:]:
                    if v.get("posted"):
                        c_cat = v.get("category", "기타")
                        recent_cat_counts[c_cat] = recent_cat_counts.get(c_cat, 0) + 1
            except Exception:
                pass

        # 카테고리별 그룹화 및 과포화 상품 후순위 밀기
        by_category = {}
        for c in candidates:
            cat = c.get("product", {}).get("category_hint", "기타")
            p_name = c.get("product", {}).get("name", "")
            if any(sk in p_name for sk in saturated_kw):
                logger.info(f"  과포화 키워드 포함으로 배제/후순위: {p_name[:30]}")
                continue
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(c)

        # 만약 과포화 제외 후 후보가 부족하면 과포화 상품도 포함하되 뒤쪽으로
        if sum(len(v) for v in by_category.values()) < count:
            for c in candidates:
                cat = c.get("product", {}).get("category_hint", "기타")
                if c not in by_category.get(cat, []):
                    by_category.setdefault(cat, []).append(c)

        logger.info(f"카테고리별 후보: {[(k, len(v)) for k, v in sorted(by_category.items())]}")

        # 최근 포스팅 빈도가 적은 카테고리부터 우선 정렬하여 라운드-로빈 선택
        selected = []
        category_idx = {cat: 0 for cat in by_category}
        sorted_cats = sorted(by_category.keys(), key=lambda k: (recent_cat_counts.get(k, 0), k))
        logger.info(f"카테고리 우선순위 (최근 적은 순): {sorted_cats}")

        while len(selected) < count:
            remaining = sum(
                len(by_category[cat]) - category_idx[cat] for cat in sorted_cats
            )
            if remaining <= 0:
                break
            for cat in sorted_cats:
                if len(selected) >= count:
                    break
                if category_idx[cat] < len(by_category[cat]):
                    selected.append(by_category[cat][category_idx[cat]])
                    category_idx[cat] += 1

        logger.info(f"선택 완료: {len(selected)}개 (카테고리별 균형)")
        for cat in sorted(by_category.keys()):
            count_selected = sum(1 for c in selected if c.get("product", {}).get("category_hint") == cat)
            logger.info(f"  {cat:15} {count_selected}개")

        return selected[:count]

    balanced = _select_balanced(all_candidates, CANDIDATES_COUNT)

    pending = {
        "for_date":     tomorrow,
        "generated_at": datetime.now(KST).isoformat(),
        "candidates":   balanced if balanced else all_candidates[:CANDIDATES_COUNT],
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PENDING_PATH, "w", encoding="utf-8") as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)

    logger.info(f"pending_post.json 저장 완료 — 기존 {len(existing_good)}개 + 신규 {len(new_candidates)}개 중 {CANDIDATES_COUNT}개 균형선택 (for {tomorrow})")


if __name__ == "__main__":
    asyncio.run(run())
