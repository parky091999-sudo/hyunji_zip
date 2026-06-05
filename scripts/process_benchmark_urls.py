"""
URL 처리 스크립트 — admin.html에서 등록한 쿠팡 URL을 처리하여
data/manual_candidates.json 후보 목록에 추가
"""
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import DATA_DIR, LOG_DIR, NAVER_CLIENT_ID

PENDING_URLS_PATH  = os.path.join(DATA_DIR, "pending_benchmark_urls.json")
CANDIDATES_PATH    = os.path.join(DATA_DIR, "manual_candidates.json")
MAX_PER_BATCH      = 20

KST = timezone(timedelta(hours=9))

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "process_urls.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("process_urls")


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _resolve_url(url: str) -> str:
    """단축/파트너스/inpock 등 모든 링크를 최종 쿠팡 상품 URL로 추적"""
    url = url.strip()
    # 이미 쿠팡 직접 상품 URL이면 바로 반환
    if re.search(r"coupang\.com/vp/products/\d+", url):
        return url
    try:
        import requests, urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=12, verify=False, allow_redirects=True)
        final = resp.url
        html  = resp.text

        # 1. 최종 URL 자체가 쿠팡이면 반환
        m = re.search(r"(https?://(?:www\.)?coupang\.com/vp/products/\d+[^\s\"'&]*)", final)
        if m:
            return m.group(1)

        # 2. HTML 내 쿠팡 상품 URL 탐색
        #    - link.coupang.com 파트너스 링크 우선
        m2 = re.search(r"(https://link\.coupang\.com/[^\s\"'<>&]+)", html)
        if m2:
            # 파트너스 단축 링크를 다시 따라가기
            try:
                r2 = requests.get(m2.group(1), headers=headers, timeout=8, verify=False, allow_redirects=True)
                m3 = re.search(r"(https?://(?:www\.)?coupang\.com/vp/products/\d+[^\s\"'&]*)", r2.url)
                if m3:
                    return m3.group(1)
            except Exception:
                pass

        # 3. HTML 내 직접 coupang.com/vp/products URL
        m4 = re.search(r"(https?://(?:www\.)?coupang\.com/vp/products/\d+[^\s\"'<>&]*)", html)
        if m4:
            return m4.group(1)

        # 4. inpock 페이지: JSON-LD 또는 data 속성에서 상품 URL 추출
        # {"url":"https://link.coupang.com/..."}  또는  data-link="..."
        m5 = re.search(r'"(?:url|link|href)"\s*:\s*"(https://link\.coupang\.com/[^"]+)"', html)
        if m5:
            try:
                r3 = requests.get(m5.group(1), headers=headers, timeout=8, verify=False, allow_redirects=True)
                m6 = re.search(r"(https?://(?:www\.)?coupang\.com/vp/products/\d+[^\s\"'&]*)", r3.url)
                if m6:
                    return m6.group(1)
            except Exception:
                pass

        return final   # 최종 URL 반환 (쿠팡 아닐 수 있음 — 이후 필터링)
    except Exception as e:
        logger.warning(f"  URL 추적 실패 ({url[:60]}): {e}")
        return url


def _fetch_product_info_naver(name: str) -> dict:
    """네이버 쇼핑에서 상품 정보 보충"""
    if not NAVER_CLIENT_ID:
        return {}
    try:
        import requests, urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        from config import NAVER_CLIENT_SECRET
        headers = {
            "X-Naver-Client-Id":     NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        }
        resp = requests.get(
            "https://openapi.naver.com/v1/search/shop.json",
            headers=headers,
            params={"query": name[:40], "display": 1},
            timeout=8, verify=False,
        )
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            if items:
                item = items[0]
                price = item.get("lprice", "")
                return {
                    "price": f"{int(price):,}원" if price else "",
                    "brand": re.sub(r"<[^>]+>", "", item.get("brand", "")),
                    "category_hint": item.get("category1", ""),
                }
    except Exception as e:
        logger.warning(f"네이버 보충 실패: {e}")
    return {}


def _fetch_page_title(url: str) -> str:
    """상품 페이지 title 태그에서 상품명 추출"""
    try:
        import requests, urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=10, verify=False, allow_redirects=True)
        if resp.status_code == 200:
            m = re.search(r"<title[^>]*>([^<]+)</title>", resp.text, re.I)
            if m:
                title = m.group(1).strip()
                # "상품명 - 쿠팡" 형식에서 상품명만
                title = re.sub(r"\s*[-|]\s*(쿠팡|Coupang).*$", "", title, flags=re.I).strip()
                return title
        # 최종 URL (리다이렉트 후)
        if resp.url != url:
            return resp.url
    except Exception as e:
        logger.warning(f"페이지 타이틀 수집 실패 ({url[:60]}): {e}")
    return ""


def _fetch_thumbnail(url: str) -> str:
    """상품 페이지 og:image 추출"""
    try:
        import requests, urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=10, verify=False, allow_redirects=True)
        if resp.status_code == 200:
            m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](https?://[^"\']+)', resp.text)
            if m:
                return m.group(1)
    except Exception:
        pass
    return ""


def process_url(url: str) -> dict | None:
    """URL 1개 처리 → candidate dict 반환"""
    logger.info(f"처리 중: {url[:80]}")

    # 단축/파트너스/inpock 등 → 최종 쿠팡 URL 추적
    resolved = _resolve_url(url)
    logger.info(f"  → 최종 URL: {resolved[:80]}")

    # 쿠팡이 아닌 URL이 나오면 건너뜀
    if "coupang.com" not in resolved:
        logger.warning(f"  쿠팡 URL 아님, 건너뜀")
        return None

    product_url = resolved

    # 상품명
    title = _fetch_page_title(resolved)
    if not title:
        logger.warning(f"  상품명 수집 실패, 건너뜀")
        return None

    logger.info(f"  상품명: {title[:50]}")

    # 썸네일
    image_url = _fetch_thumbnail(resolved)

    # 네이버로 가격/브랜드 보충
    extra = _fetch_product_info_naver(title)

    product = {
        "name":         title,
        "product_url":  product_url,
        "image_url":    image_url,
        "price":        extra.get("price", ""),
        "brand":        extra.get("brand", ""),
        "category_hint": extra.get("category_hint", ""),
        "source":       "url_input",
    }

    return {
        "product":        product,
        "source_account": "url_input",
        "added_at":       datetime.now(KST).isoformat(),
    }


def run():
    logger.info("=" * 50)
    logger.info(f"URL 처리 시작: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    logger.info("=" * 50)

    pending = _load_json(PENDING_URLS_PATH, {"urls": []})
    urls = pending.get("urls", [])
    if not urls:
        logger.info("처리할 URL 없음")
        return

    logger.info(f"{len(urls)}개 URL 처리 예정")

    existing = _load_json(CANDIDATES_PATH, {"scanned_at": "", "candidates": []})
    candidates = existing.get("candidates", [])
    existing_urls = {c.get("product", {}).get("product_url", "")[:80] for c in candidates}

    added = 0
    for url in urls[:MAX_PER_BATCH]:
        try:
            c = process_url(url)
            if not c:
                continue
            key = c["product"].get("product_url", "")[:80]
            if key in existing_urls:
                logger.info(f"  이미 존재, 건너뜀")
                continue
            candidates.insert(0, c)
            existing_urls.add(key)
            added += 1
        except Exception as e:
            logger.error(f"URL 처리 오류 ({url[:60]}): {e}")

    # 최대 100개 유지
    candidates = candidates[:100]

    result = {
        "scanned_at": existing.get("scanned_at", ""),
        "updated_at": datetime.now(KST).isoformat(),
        "candidates": candidates,
    }
    _save_json(CANDIDATES_PATH, result)

    # pending URL 초기화
    _save_json(PENDING_URLS_PATH, {"urls": [], "submitted_at": "", "processed_at": datetime.now(KST).isoformat()})

    logger.info(f"완료: {added}개 추가, 총 {len(candidates)}개 후보")


if __name__ == "__main__":
    run()
