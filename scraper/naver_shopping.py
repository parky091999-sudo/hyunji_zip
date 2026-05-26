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
)

logger = logging.getLogger(__name__)

API_URL = "https://openapi.naver.com/v1/search/shop.json"

# 카테고리별 키워드 — (키워드, 카테고리힌트) 튜플
SEARCH_KEYWORDS = [
    # 뷰티
    ("스킨케어 추천", "뷰티"),
    ("선크림 추천", "뷰티"),
    ("에센스 추천", "뷰티"),
    ("마스크팩 추천", "뷰티"),
    ("클렌징 추천", "뷰티"),
    # 생활용품
    ("주방용품 추천", "생활"),
    ("생활용품 특가", "생활"),
    ("욕실용품 추천", "생활"),
    # 식품
    ("간식 추천", "식품"),
    ("건강식품 추천", "식품"),
    ("음료 추천", "식품"),
    # 패션/잡화
    ("여성의류 추천", "패션"),
    ("가방 추천", "패션"),
]

MIN_LPRICE = 3_000

# 상품명에서 제거할 광고성/불필요 패턴
_NAME_NOISE = re.compile(
    r"(\[.*?\])"                   # [특가] [타임딜] 등 대괄호 문구
    r"|(\(.*?직영.*?\))"           # (본사직영) 등
    r"|(,\s*\d+개$)"               # 끝의 수량 표기 ",  1개"
    r"|(\s{2,})",                  # 연속 공백
    re.IGNORECASE,
)


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _clean_name(name: str) -> str:
    """상품명에서 광고성 문구 제거"""
    cleaned = _NAME_NOISE.sub(" ", name).strip()
    # 앞뒤 특수문자 정리
    cleaned = re.sub(r"^[\s\-_,/|]+|[\s\-_,/|]+$", "", cleaned)
    return cleaned if cleaned else name


def _fetch_items(keyword: str, display: int = 30) -> list[dict]:
    """네이버 쇼핑 API 호출"""
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {"query": keyword, "display": display, "sort": "sim"}
    resp = requests.get(API_URL, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json().get("items", [])


def _calc_discount_rate(lprice: int, hprice: int) -> int:
    """최고가 대비 최저가 할인율"""
    if hprice > 0 and lprice > 0 and hprice > lprice:
        return round((1 - lprice / hprice) * 100)
    return 0


def _to_product(item: dict, category_hint: str = "") -> dict | None:
    """네이버 API 응답 → 파이프라인 공통 포맷"""
    raw_name = _strip_html(item.get("title", ""))
    if not raw_name:
        return None

    name = _clean_name(raw_name)

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
        "brand": item.get("brand", ""),
        "category": item.get("category3", item.get("category2", "")),
        "category_hint": category_hint,
        "mall_name": item.get("mallName", ""),
        "source": "naver_shopping",
        "scraped_at": datetime.now().isoformat(),
    }


def scrape_deals(max_items: int = MAX_PRODUCTS_PER_RUN) -> list[dict]:
    """상품 수집 (네이버 쇼핑 API) — 다양한 카테고리, 쿠팡 판매 상품 우선"""
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        logger.error("네이버 API 키 미설정 — .env에 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 추가 필요")
        return []

    coupang_products: list[dict] = []
    all_products: list[dict] = []
    seen_names: set[str] = set()

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
                key = product["name"][:15]
                if key in seen_names:
                    continue
                seen_names.add(key)

                is_coupang = "쿠팡" in product["mall_name"]
                if is_coupang:
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
    if len(result) < max_items:
        needed = max_items - len(result)
        result += all_products[:needed]
        if all_products:
            logger.info(f"  쿠팡 상품 부족 → 기타 mall 상품 {needed}개 추가")

    logger.info(f"최종 수집: {len(result)}개 (쿠팡 {len(coupang_products)}개 포함)")
    return result


# 하위 호환용 alias
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
        print(f"\n수집된 뷰티 상품 {len(products)}개:")
        for p in products:
            print(f"  [{p['discount_rate']}%] {p['name'][:45]} | {p['price']} | {p['mall_name']}")
    else:
        print("수집된 상품이 없습니다.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(run())
