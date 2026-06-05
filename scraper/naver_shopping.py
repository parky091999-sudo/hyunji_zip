"""
네이버 쇼핑 API 스크래퍼
- 뷰티 키워드 검색으로 할인 상품 수집
- 무료 25,000건/일 (네이버 개발자센터 앱 등록 필요)
- 할인율: hprice(최고가) vs lprice(최저가) 차이로 근사 계산
"""
import requests
import logging
import sys
import os
import json
import re
from datetime import datetime
from itertools import cycle

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import (
    DATA_DIR, MAX_PRODUCTS_PER_RUN,
    NAVER_CLIENT_ID, NAVER_CLIENT_SECRET,
    REQUIRE_BRAND, CHECK_RATING, MIN_REVIEW_COUNT, MIN_RATING,
)

logger = logging.getLogger(__name__)

API_URL = "https://openapi.naver.com/v1/search/shop.json"

# 카테고리별 키워드 — (키워드, 카테고리힌트) 튜플
SEARCH_KEYWORDS = [
    # 주방 — 특이한 자동화 가젯
    ("자동 계란 삶기 기계", "주방"),
    ("전동 채칼 회오리 채썰기", "주방"),
    ("자동 비누 거품기 센서", "주방"),
    ("전동 와인오프너 자동", "주방"),
    ("분리형 계란 분리기", "주방"),
    # 청소/정리 — 비포&애프터 반응
    ("욕실 전동 청소 솔 회전", "생활"),
    ("이불 압축팩 전동펌프", "생활"),
    ("신발 건조기 냄새 제거", "생활"),
    ("자동 센서 쓰레기통", "생활"),
    # 뷰티/홈케어 — 셀프케어 트렌드
    ("전동 두피 마사지기 샤워", "뷰티"),
    ("눈 온열 마사지기 찜질", "뷰티"),
    ("전동 발뒤꿈치 각질 제거기", "뷰티"),
    ("목 견인 스트레칭 기기", "뷰티"),
    # 반려동물 — 동물 반응 영상 바이럴
    ("고양이 자동 레이저 장난감", "반려동물"),
    ("강아지 간식 발사기 자동", "반려동물"),
    ("고양이 자동 급수기 분수", "반려동물"),
    # 수면/건강 — 공감 폭발 키워드
    ("코골이 방지 자동 기기", "건강"),
    ("수면 무호흡 방지 기기", "건강"),
    # 인테리어/감성 소품
    ("LED 무드등 별빛 프로젝터", "인테리어"),
    ("자동 아로마 디퓨저 초음파", "인테리어"),
]

MIN_LPRICE = 15_000  # 15,000원 미만 단순 소품 제외

# ── 차단 키워드 (공업용/업소용/저품질 자동 필터) ────────────────────────────
# 이런 상품은 올리기 전에 자체 차단
BLOCKED_KEYWORDS = [
    # 공업/산업/업소용 장비
    "슬라이서", "절단기", "분쇄기", "탈피기", "박피기", "채칼기계",
    "업소용", "상업용", "공업용", "산업용", "영업용", "식당용", "주방장비",
    # 공업 스펙 수치 (일반 소비자 상품에 없는 표현)
    "kg/h", "r/min", "1400r", "가공량",
    # B2B / 도매
    "도매", "대량구매", "벌크", "박스단위",
    # 직구 / 중국 직배송 느낌
    "직구", "해외직구",
    # 부품류
    "교체부품", "부품만", "스페어",
    # 작업/안전 장비
    "소방", "안전모", "작업복", "방진마스크", "방진장갑",
]


def is_blocked_product(name: str) -> bool:
    """공업용/저품질/B2B 상품 차단"""
    return any(kw in name for kw in BLOCKED_KEYWORDS)


_TYPE_GROUPS: list[list[str]] = [
    ["led마스크", "led 마스크", "피부관리기", "피부 관리 led", "led피부관리"],
    ["마사지의자", "안마의자", "마사지 의자"],
    ["안마기", "마사지기", "마사지건", "마사지 건"],
    ["두피마사지", "두피 마사지"],
    ["눈마사지", "눈 마사지", "온열마사지", "아이마스크"],
    ["공기청정기"],
    ["로봇청소기", "청소기"],
    ["에어프라이어"],
    ["가습기"],
    ["제습기"],
    ["선풍기", "써큘레이터"],
    ["블루투스 스피커", "블루투스스피커"],
    ["고양이 자동", "강아지 자동", "반려동물 자동"],
    ["고양이 급수기", "자동 급수기"],
    ["코골이"],
    ["신발건조기", "신발 건조기"],
    ["이불압축", "이불 압축"],
    ["쓰레기통 자동", "센서 쓰레기통"],
    ["계란 삶기", "자동계란"],
    ["채칼", "회오리채썰기"],
    ["비누거품기", "폼 디스펜서"],
    ["아로마 디퓨저", "초음파디퓨저"],
    ["프로젝터 무드등", "별빛 조명", "무드등"],
]


def _get_product_type(name: str) -> str | None:
    name_lower = name.lower().replace(" ", "")
    for group in _TYPE_GROUPS:
        for kw in group:
            if kw.replace(" ", "") in name_lower:
                return group[0]
    return None


_NAME_NOISE = re.compile(
    r"(\[.*?\])"
    r"|(\(.*?직영.*?\))"
    r"|(,\s*\d+개$)"
    r"|(\s{2,})",
    re.IGNORECASE,
)


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _clean_name(name: str) -> str:
    cleaned = _NAME_NOISE.sub(" ", name).strip()
    cleaned = re.sub(r"^[\s\-_,/|]+|[\s\-_,/|]+$", "", cleaned)
    return cleaned if cleaned else name


def _fetch_items(keyword: str, display: int = 30) -> list[dict]:
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {"query": keyword, "display": display, "sort": "sim"}
    resp = requests.get(API_URL, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json().get("items", [])


def _calc_discount_rate(lprice: int, hprice: int) -> int:
    if hprice > 0 and lprice > 0 and hprice > lprice:
        return round((1 - lprice / hprice) * 100)
    return 0


def _is_bad_name(name: str) -> bool:
    words = name.split()
    if len(words) >= 10:
        return True
    noise_patterns = ["블랙을", "실버 1개", "블루를", "화이트를", "측정기용"]
    if any(p in name for p in noise_patterns):
        return True
    return False


def _has_chinese(text: str) -> bool:
    for ch in text:
        cp = ord(ch)
        if (0x4E00 <= cp <= 0x9FFF
                or 0x3400 <= cp <= 0x4DBF
                or 0xF900 <= cp <= 0xFAFF):
            return True
    return False


def _to_product(item: dict, category_hint: str = "") -> dict | None:
    raw_name = _strip_html(item.get("title", ""))
    if not raw_name:
        return None

    name = _clean_name(raw_name)

    if _is_bad_name(name):
        return None

    if _has_chinese(name):
        return None

    # ── 차단 키워드 필터 (공업용/업소용 등) ──────────────────────────────────
    if is_blocked_product(name):
        logger.info(f"  차단 키워드 필터: {name[:40]}")
        return None

    if REQUIRE_BRAND:
        brand = (item.get("brand") or "").strip()
        maker = (item.get("maker") or "").strip()
        if not brand and not maker:
            return None

    lprice = int(item.get("lprice", 0) or 0)
    hprice = int(item.get("hprice", 0) or 0)

    if lprice < MIN_LPRICE:
        return None

    discount_rate = _calc_discount_rate(lprice, hprice)

    return {
        "name": name,
        "price": f"{lprice:,}원",
        "original_price": f"{hprice:,}원" if hprice else "",
        "discount_rate": discount_rate,
        "image_url": item.get("image", ""),
        "product_url": item.get("link", ""),
        "badge": item.get("mallName", ""),
        "brand": (item.get("brand") or item.get("maker") or "").strip(),
        "category": item.get("category3", item.get("category2", "")),
        "category_hint": category_hint,
        "mall_name": item.get("mallName", ""),
        "source": "naver_shopping",
        "scraped_at": datetime.now().isoformat(),
    }


def _check_coupang_rating(product: dict) -> bool:
    """
    Playwright로 쿠팡 상품 페이지 접속 → 별점/리뷰수 확인
    - 별점 정보를 정상적으로 가져왔는데 0점이면 차단 (신규/미검증 상품)
    - Playwright 인프라 오류(브라우저 미설치, 네트워크 타임아웃 등)는
      차단하지 않고 통과 처리 (검증 불가 → 허용)
    """
    if not CHECK_RATING:
        return True

    url = product.get("product_url", "")
    if not url:
        return False

    try:
        resp = requests.head(url, allow_redirects=True, timeout=8,
                             headers={"User-Agent": "Mozilla/5.0"})
        final_url = resp.url
        if "coupang.com" not in final_url:
            logger.info(f"  쿠팡 상품 아님 — 차단: {url[:50]}")
            return False
    except Exception as e:
        logger.warning(f"  리다이렉트 확인 실패 ({e}) — 통과 처리")
        final_url = url  # 원본 URL로 Playwright 시도

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page.goto(final_url, wait_until="domcontentloaded", timeout=20000)

            rating_val, review_cnt = 0.0, 0

            # JSON-LD에서 aggregateRating 파싱
            for script in page.query_selector_all('script[type="application/ld+json"]'):
                try:
                    data = json.loads(script.inner_text())
                    if isinstance(data, list):
                        data = data[0] if data else {}
                    ar = data.get("aggregateRating", {})
                    if ar:
                        rating_val = float(ar.get("ratingValue", 0) or 0)
                        review_cnt = int(ar.get("reviewCount") or ar.get("ratingCount") or 0)
                        if rating_val > 0:
                            break
                except Exception:
                    continue

            # JSON-LD 없으면 페이지 텍스트에서 패턴 추출
            if rating_val == 0:
                try:
                    content = page.content()
                    m = re.search(r'"ratingValue"\s*:\s*"?([\d.]+)"?', content)
                    rc = re.search(r'"reviewCount"\s*:\s*"?(\d+)"?', content)
                    if m:
                        rating_val = float(m.group(1))
                    if rc:
                        review_cnt = int(rc.group(1))
                except Exception:
                    pass

            browser.close()

        if rating_val == 0:
            logger.info(f"  별점 정보 없음 (신규/미검증 상품) → 차단: {product.get('name','')[:30]}")
            return False

        product["rating"] = rating_val
        product["review_count"] = review_cnt
        logger.info(f"  → ★{rating_val} 리뷰 {review_cnt}개")

        if int(review_cnt or 0) < MIN_REVIEW_COUNT:
            logger.info(f"  → 리뷰 부족 ({review_cnt} < {MIN_REVIEW_COUNT}) 제외")
            return False
        if float(rating_val or 0) < MIN_RATING:
            logger.info(f"  → 별점 미달 (★{rating_val} < ★{MIN_RATING}) 제외")
            return False

        return True

    except Exception as e:
        # Playwright 인프라 오류 (브라우저 미설치, OS 라이브러리 누락 등)
        # 상품 자체의 문제가 아니므로 차단하지 않고 통과
        logger.warning(f"  → Playwright 오류로 별점 확인 불가: {e} — 통과 처리")
        return True


def scrape_deals(max_items: int = MAX_PRODUCTS_PER_RUN) -> list[dict]:
    """상품 수집 (네이버 쇼핑 API) — 다양한 카테고리, 쿠팡 판매 상품 우선"""
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        logger.error("네이버 API 키 미설정")
        return []

    coupang_products: list[dict] = []
    all_products: list[dict] = []
    seen_names: set[str] = set()
    seen_types: set[str] = set()

    for keyword, cat_hint in SEARCH_KEYWORDS:
        if len(coupang_products) >= max_items:
            break
        try:
            logger.info(f"네이버 쇼핑 검색: '{keyword}'")
            items = _fetch_items(keyword)
            logger.info(f"  → {len(items)}개 항목 수신")

            for item in items:
                product = _to_product(item, category_hint=cat_hint)
                if not product:
                    continue

                key = product["name"][:8]
                if key in seen_names:
                    continue
                seen_names.add(key)

                is_coupang = (
                    "쿠팡" in product["mall_name"]
                    or "coupang" in product.get("product_url", "").lower()
                )
                if is_coupang:
                    ptype = _get_product_type(product["name"])
                    if ptype and ptype in seen_types:
                        logger.info(f"  유형 중복 제외 [{ptype}]: {product['name'][:30]}")
                        continue
                    if ptype:
                        seen_types.add(ptype)
                    if not _check_coupang_rating(product):
                        continue
                    coupang_products.append(product)
                    logger.info(f"  [쿠팡/{cat_hint}] {product['name'][:40]} | {product['price']}")
                else:
                    all_products.append(product)

        except requests.HTTPError as e:
            logger.error(f"API 오류 ({keyword}): {e}")
            break
        except Exception as e:
            logger.warning(f"키워드 오류 ({keyword}): {e}")

    result = coupang_products[:max_items]

    # 쿠팡 상품 0개 → 더 넓은 키워드로 폴백 재시도
    if not result:
        logger.warning("쿠팡 상품 0개 → 폴백 키워드로 재시도...")
        fallback_keywords = [
            ("생활용품 인기 추천", "생활"),
            ("주방용품 베스트 추천", "주방"),
            ("뷰티 인기 추천", "뷰티"),
            ("생활 가전 인기", "생활"),
        ]
        for kw, cat_hint in fallback_keywords:
            if len(result) >= max_items:
                break
            try:
                items = _fetch_items(kw)
                for item in items:
                    product = _to_product(item, category_hint=cat_hint)
                    if not product:
                        continue
                    if not (
                        "쿠팡" in product["mall_name"]
                        or "coupang" in product.get("product_url", "").lower()
                    ):
                        continue
                    key = product["name"][:8]
                    if key in seen_names:
                        continue
                    seen_names.add(key)
                    result.append(product)
                    logger.info(f"  [폴백/{cat_hint}] {product['name'][:40]}")
                    if len(result) >= max_items:
                        break
            except Exception as e:
                logger.warning(f"폴백 키워드 오류 ({kw}): {e}")

    logger.info(f"최종 수집: {len(result)}개 (쿠팡만)")
    return result


scrape_beauty_deals = scrape_deals


def save_products(products: list[dict], filename: str = "products.json"):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    logger.info(f"저장: {path}")
    return path


def load_products(filename: str = "products.json") -> list[dict]:
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


async def run():
    import asyncio
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    products = scrape_beauty_deals()
    if products:
        save_products(products)
        print(f"\n수집된 상품 {len(products)}개:")
        for p in products:
            print(f"  [{p['discount_rate']}%] {p['name'][:45]} | {p['price']} | {p['mall_name']}")
    else:
        print("수집된 상품이 없습니다.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(run())
