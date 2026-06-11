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

# 카테고리별 키워드 풀 — (키워드, 카테고리힌트) 튜플
# 데이터랩 트렌딩 카테고리명과 동일한 키로 구성
SEARCH_KEYWORDS_BY_CATEGORY: dict[str, list[tuple[str, str]]] = {
    "생활/건강": [
        # 주방
        ("자동 계란 삶기 기계", "주방"),
        ("자동 비누 거품기 센서", "주방"),
        ("전동 와인오프너 자동", "주방"),
        ("전동 후추 소금 그라인더", "주방"),
        ("자동 캔오프너 전동", "주방"),
        ("주방 음식물 쓰레기통 자동", "주방"),
        ("전기 주전자 미니 소형", "주방"),
        ("실리콘 주방 도구 세트", "주방"),
        ("냉장고 정리함 서랍 수납", "주방"),
        # 청소·생활
        ("욕실 전동 청소 솔 회전", "생활"),
        ("이불 압축팩 전동펌프", "생활"),
        ("신발 건조기 냄새 제거", "생활"),
        ("자동 센서 쓰레기통", "생활"),
        ("UV 살균 칫솔 케이스", "생활"),
        ("전동 칫솔 소닉 방수", "생활"),
        ("자동 핸드 워시 거품 센서", "생활"),
        ("전동 청소기 미니 무선 소형", "생활"),
        ("스팀 청소기 가정용", "생활"),
        ("욕실 배수구 청소 도구", "생활"),
        ("창문 청소기 전동 유리창", "생활"),
        ("세탁조 클리너 드럼세탁기 청소", "생활"),
        # 건강
        ("코골이 방지 자동 기기", "건강"),
        ("혈압계 가정용 디지털 자동", "건강"),
        ("체지방계 스마트 체중계", "건강"),
        ("경피 전기자극 마사지 패드", "건강"),
        ("발 각질 제거기 전동", "건강"),
        ("온열 발마사지기 전동", "건강"),
        # 반려동물
        ("고양이 자동 레이저 장난감", "반려동물"),
        ("강아지 간식 발사기 자동", "반려동물"),
        ("고양이 자동 급수기 분수", "반려동물"),
        ("반려동물 자동 급식기 타이머", "반려동물"),
        ("강아지 고양이 자동화장실", "반려동물"),
        ("펫 드라이룸 건조기", "반려동물"),
    ],
    "화장품/미용": [
        ("전동 두피 마사지기 샤워", "뷰티"),
        ("눈 온열 마사지기 찜질", "뷰티"),
        ("목 견인 스트레칭 기기", "뷰티"),
        ("LED 마스크 피부 관리기", "뷰티"),
        ("초음파 세안기 피부 관리", "뷰티"),
        ("미세전류 리프팅 기기", "뷰티"),
        ("전동 마사지건 근육 이완", "뷰티"),
        ("두피 스케일러 전동", "뷰티"),
        ("피부 수분 측정기 디지털", "뷰티"),
        ("고주파 피부 탄력 기기", "뷰티"),
        ("전동 속눈썹 고데기 미니", "뷰티"),
        ("전동 면도기 방수 충전식", "뷰티"),
        ("헤어 드라이어 이온 고속", "뷰티"),
        ("고데기 무선 충전식 미니", "뷰티"),
        ("목 어깨 마사지기 온열 전동", "뷰티"),
    ],
    "가구/인테리어": [
        ("LED 무드등 별빛 프로젝터", "인테리어"),
        ("자동 아로마 디퓨저 초음파", "인테리어"),
        ("스마트 플러그 타이머 앱", "인테리어"),
        ("소형 공기청정기 미니", "인테리어"),
        ("자동 가습기 초음파 미니", "인테리어"),
        ("감성 수면등 수유등", "인테리어"),
        ("냉방 에어쿨러 이동식 소형", "인테리어"),
        ("제습기 소형 가정용 미니", "인테리어"),
        ("서랍 수납함 정리함 옷장", "인테리어"),
        ("벽걸이 선반 무타공 부착식", "인테리어"),
        ("감성 커튼 방한 암막", "인테리어"),
    ],
    "디지털/가전": [
        ("목걸이 선풍기 휴대용", "디지털"),
        ("미니 빔프로젝터 가정용", "디지털"),
        ("무선 충전 고속 멀티", "디지털"),
        ("휴대용 블루투스 스피커 방수", "디지털"),
        ("스마트워치 혈압 혈당 측정", "디지털"),
        ("보조배터리 대용량 고속충전", "디지털"),
        ("USB 허브 멀티포트 C타입", "디지털"),
        ("무선 이어폰 블루투스 노이즈캔슬링", "디지털"),
        ("휴대용 미니 선풍기 탁상용", "디지털"),
        ("스마트 LED 조명 앱 제어", "디지털"),
        ("소형 캠코더 블랙박스 액션캠", "디지털"),
    ],
    "스포츠/레저": [
        ("폼롤러 근막 마사지 전동", "스포츠"),
        ("스마트 줄넘기 카운트", "스포츠"),
        ("미니 홈트 기구 접이식", "스포츠"),
        ("요가 매트 미끄럼 방지", "스포츠"),
        ("자동 공기주입 볼 펌프", "스포츠"),
        ("가정용 운동기구 다이어트", "스포츠"),
        ("휴대용 캠핑 의자 접이식", "스포츠"),
        ("낚시 쿨러백 보냉 가방", "스포츠"),
        ("등산 트레킹 폴 접이식", "스포츠"),
        ("스트레칭 밴드 저항 밴드 세트", "스포츠"),
    ],
    "출산/육아": [
        ("아기 모니터 카메라 무선", "육아"),
        ("전동 착유기 유축기 휴대용", "육아"),
        ("자동 젖병 소독 건조기", "육아"),
        ("아기 전동 코 흡입기", "육아"),
        ("유아 전동 그네 자동", "육아"),
        ("아기 체온계 비접촉 이마", "육아"),
        ("유아 칫솔 전동 소형", "육아"),
        ("아기 흡입 식판 실리콘 세트", "육아"),
    ],
}

# 전체 키워드 플랫 리스트 (트렌드 데이터 없을 때 폴백용)
SEARCH_KEYWORDS: list[tuple[str, str]] = [
    kw for kws in SEARCH_KEYWORDS_BY_CATEGORY.values() for kw in kws
]


def _build_keyword_order(
    trending_cats: list[str] | None,
    priority_keywords: list[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    """검색 키워드 우선순위 빌드.

    우선순위 (위에서 아래로):
    1. priority_keywords (시즌·모멘텀 부스트된 키워드) — 맨 앞
    2. trending_cats 카테고리 키워드 — 그 다음
    3. 나머지 — 마지막

    priority_keywords가 SEARCH_KEYWORDS에도 있으면 중복 제거 (뒤에서 제외).
    """
    priority = list(priority_keywords or [])
    seen_keys = {kw for kw, _ in priority}

    if trending_cats:
        cat_block: list[tuple[str, str]] = []
        others: list[tuple[str, str]] = []
        for cat_name, kw_list in SEARCH_KEYWORDS_BY_CATEGORY.items():
            for kw, hint in kw_list:
                if kw in seen_keys:
                    continue
                if cat_name in trending_cats:
                    cat_block.append((kw, hint))
                else:
                    others.append((kw, hint))
        return priority + cat_block + others

    rest = [(kw, hint) for kw, hint in SEARCH_KEYWORDS if kw not in seen_keys]
    return priority + rest

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
    ["두피마사지", "두피 마사지", "두피스케일러"],
    ["눈마사지", "눈 마사지", "온열마사지", "아이마스크"],
    ["공기청정기"],
    ["로봇청소기", "청소기"],
    ["에어프라이어"],
    ["가습기"],
    ["제습기"],
    ["선풍기", "써큘레이터", "목걸이선풍기", "탁상용선풍기"],
    ["블루투스 스피커", "블루투스스피커"],
    ["고양이 자동", "강아지 자동", "반려동물 자동"],
    ["고양이 급수기", "자동 급수기", "자동급식기"],
    ["코골이"],
    ["신발건조기", "신발 건조기"],
    ["이불압축", "이불 압축"],
    ["쓰레기통 자동", "센서 쓰레기통"],
    ["계란 삶기", "자동계란"],
    ["비누거품기", "폼 디스펜서", "핸드워시"],
    ["아로마 디퓨저", "초음파디퓨저"],
    ["프로젝터 무드등", "별빛 조명", "무드등"],
    ["혈압계", "자동혈압"],
    ["체중계", "체지방계"],
    ["전동칫솔", "소닉칫솔"],
    ["보조배터리", "파워뱅크"],
    ["무선이어폰", "블루투스이어폰"],
    ["헤어드라이어", "고데기"],
    ["스팀청소기", "스팀 청소"],
    ["체온계", "비접촉체온"],
    ["유축기", "착유기"],
    ["빔프로젝터", "미니프로젝터"],
    ["캠핑의자", "접이식의자"],
    ["폼롤러", "근막마사지"],
    ["압축팩", "여행압축"],
    ["그라인더", "소금후추그라인더", "소금 후추 그라인더", "후추밀"],
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
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    resp = requests.get(API_URL, headers=headers, params=params, timeout=10, verify=False)
    resp.raise_for_status()
    return resp.json().get("items", [])


def fetch_image_by_name(name: str) -> str:
    """상품명으로 네이버 쇼핑 검색 → 대표 이미지 URL 1개 반환.
    어드민 URL 직접 등록 등으로 이미지가 없는 상품 보충용 (공식 API, 무료)."""
    if not name or not (NAVER_CLIENT_ID and NAVER_CLIENT_SECRET):
        return ""
    try:
        keyword = _clean_name(_strip_html(name)).strip()[:40] or name[:40]
        for item in _fetch_items(keyword, display=5):
            img = (item.get("image") or "").strip()
            if img.startswith("http"):
                logger.info(f"  네이버 이미지 보충 성공: {keyword[:25]}")
                return img
    except Exception as e:
        logger.warning(f"네이버 이미지 보충 실패: {e}")
    return ""


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


_BRAND_RE = re.compile(r"\b[A-Z][A-Z0-9\-]{1,}\b")


def is_chinese_seller_style(name: str) -> bool:
    """중국 셀러 키워드 스터핑 패턴 — 한국어 단어(2자+) 반복 + 영문 브랜드 없음.

    예시 차단:
    - "우드 인테리어 삼각 튼튼한건조대 원룸 화이트 우드"  (우드 2회)
    - "휴대용 의류건조기 ... 휴대용 200w"                 (휴대용 2회)
    예시 통과:
    - "PONTE 독일 다기능 스팀청소기 핸디 ..."             (PONTE 브랜드)
    - "밥도둑세상 국내산간재미 간재미무침 1k 1kg 1개"      (반복 없음)
    """
    if _BRAND_RE.search(name):
        return False
    korean_words = re.findall(r"[가-힣]{2,}", name)
    if len(set(korean_words)) < len(korean_words):
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

    # ── 중국 셀러 키워드 스터핑 패턴 필터 (014/015형 재발 방지) ─────────────
    if is_chinese_seller_style(name):
        logger.info(f"  중국셀러 패턴 필터: {name[:40]}")
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
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        resp = requests.head(url, allow_redirects=True, timeout=8,
                             headers={"User-Agent": "Mozilla/5.0"}, verify=False)
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


def scrape_deals(
    max_items: int = MAX_PRODUCTS_PER_RUN,
    trending_cats: list[str] | None = None,
    priority_keywords: list[tuple[str, str]] | None = None,
) -> list[dict]:
    """상품 수집 (네이버 쇼핑 API).

    검색 우선순위: priority_keywords(시즌·모멘텀) → trending_cats → 나머지.
    쿠팡 판매 상품만 통과.
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        logger.error("네이버 API 키 미설정")
        return []

    keywords = _build_keyword_order(trending_cats, priority_keywords)
    if priority_keywords:
        logger.info(f"시즌·모멘텀 우선 키워드 {len(priority_keywords)}개 배치")
    if trending_cats:
        logger.info(f"트렌딩 카테고리 우선 검색: {trending_cats}")

    coupang_products: list[dict] = []
    all_products: list[dict] = []
    seen_names: set[str] = set()
    seen_types: set[str] = set()

    for keyword, cat_hint in keywords:
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
