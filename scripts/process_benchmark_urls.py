"""
컬렉션 URL 처리 스크립트
- inpock 등 JS 렌더링 페이지: Playwright로 렌더링 + 네트워크 응답 캡처
- 개별 쿠팡/파트너스 URL: requests로 처리
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

from config import DATA_DIR, LOG_DIR, NAVER_CLIENT_ID

PENDING_URLS_PATH  = os.path.join(DATA_DIR, "pending_benchmark_urls.json")
CANDIDATES_PATH    = os.path.join(DATA_DIR, "manual_candidates.json")
SOURCES_PATH       = os.path.join(DATA_DIR, "collection_sources.json")
MAX_PER_PAGE       = 30
MAX_TOTAL          = 100

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

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import requests

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


# ── 유틸 ─────────────────────────────────────────────────────────────────────

def _load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _get(url, timeout=15):
    try:
        return requests.get(url, headers=_HEADERS, timeout=timeout, verify=False, allow_redirects=True)
    except Exception as e:
        logger.warning(f"  GET 실패 ({url[:60]}): {e}")
        return None


def _product_id(url: str) -> str | None:
    m = re.search(r"/products/(\d+)", url)
    return m.group(1) if m else None


def _extract_coupang_urls(text: str) -> list[str]:
    """텍스트에서 쿠팡 관련 URL 모두 추출"""
    urls = []
    urls += re.findall(r'https://link\.coupang\.com/[A-Za-z0-9/_\-?=&%.]+', text)
    urls += re.findall(r'https?://(?:www\.)?coupang\.com/vp/products/\d+[^\s"\'<>&]*', text)
    return urls


def _follow_to_coupang(url: str) -> str | None:
    """어떤 링크든 최종 쿠팡 상품 URL로 추적"""
    if re.search(r"coupang\.com/vp/products/\d+", url):
        return re.search(r"(https?://(?:www\.)?coupang\.com/vp/products/\d+)", url).group(1)
    resp = _get(url, timeout=10)
    if not resp:
        return None
    for src in [resp.url, resp.text]:
        m = re.search(r"(https?://(?:www\.)?coupang\.com/vp/products/\d+)", src)
        if m:
            return m.group(1)
    return None


# ── 네이버 정보 보충 ──────────────────────────────────────────────────────────

def _naver_enrich(name: str) -> dict:
    if not NAVER_CLIENT_ID:
        return {}
    try:
        from config import NAVER_CLIENT_SECRET
        resp = requests.get(
            "https://openapi.naver.com/v1/search/shop.json",
            headers={
                "X-Naver-Client-Id":     NAVER_CLIENT_ID,
                "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
            },
            params={"query": name[:40], "display": 1},
            timeout=8, verify=False,
        )
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            if items:
                it = items[0]
                price = it.get("lprice", "")
                return {
                    "price":         f"{int(price):,}원" if price else "",
                    "brand":         re.sub(r"<[^>]+>", "", it.get("brand", "")),
                    "category_hint": it.get("category1", ""),
                }
    except Exception as e:
        logger.warning(f"  네이버 보충 실패: {e}")
    return {}


# ── 쿠팡 상품 정보 ────────────────────────────────────────────────────────────

def _fetch_coupang_product(product_url: str) -> dict | None:
    resp = _get(product_url)
    if not resp or resp.status_code != 200:
        return None
    html = resp.text
    name = ""
    m = re.search(r'<title[^>]*>([^<]+)</title>', html, re.I)
    if m:
        name = re.sub(r'\s*[-|]\s*(쿠팡|Coupang).*$', '', m.group(1), flags=re.I).strip()
    if not name:
        return None
    img = ""
    m2 = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](https?://[^"\']+)', html)
    if m2:
        img = m2.group(1)
    return {"name": name, "image_url": img, "product_url": product_url}


# ── Playwright 기반 inpock 스크래퍼 ──────────────────────────────────────────

async def _scrape_with_playwright(page_url: str) -> list[str]:
    """
    Playwright로 페이지를 렌더링하고 네트워크 응답에서 쿠팡 URL 추출
    JS 렌더링 SPA(inpock 등)에 사용
    """
    from playwright.async_api import async_playwright

    collected_urls: list[str] = []
    collected_texts: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            user_agent=_HEADERS["User-Agent"],
            locale="ko-KR",
        )
        page = await context.new_page()

        # 네트워크 응답 캡처
        async def on_response(response):
            url = response.url
            if any(kw in url for kw in ["coupang", "inpock", "api"]):
                try:
                    body = await response.text()
                    collected_texts.append(body)
                except Exception:
                    pass

        page.on("response", on_response)

        try:
            await page.goto(page_url, wait_until="networkidle", timeout=30000)
            # 스크롤해서 lazy-load 항목 로드
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1000)
            # 최종 HTML도 추가
            html = await page.content()
            collected_texts.append(html)
        except Exception as e:
            logger.warning(f"  Playwright 페이지 로드 실패: {e}")
        finally:
            await browser.close()

    # 수집된 모든 텍스트에서 URL 추출
    seen = set()
    for text in collected_texts:
        for u in _extract_coupang_urls(text):
            key = u[:80]
            if key not in seen:
                seen.add(key)
                collected_urls.append(u)

    logger.info(f"  Playwright 수집: {len(collected_urls)}개 링크")
    return collected_urls


# ── 컬렉션 페이지 처리 ────────────────────────────────────────────────────────

async def _scrape_collection(page_url: str, source_label: str) -> list[dict]:
    """컬렉션/프로필 페이지에서 상품 목록 수집"""
    logger.info(f"[컬렉션] {page_url} → @{source_label}")

    # 1단계: requests로 빠르게 시도
    raw_urls: list[str] = []
    resp = _get(page_url)
    if resp:
        raw_urls = _extract_coupang_urls(resp.text)
        logger.info(f"  requests: {len(raw_urls)}개 링크")

    # 2단계: JS 렌더링 필요하면 Playwright 사용
    if len(raw_urls) < 3:
        logger.info(f"  JS 렌더링 필요 → Playwright 시도")
        raw_urls = await _scrape_with_playwright(page_url)

    if not raw_urls:
        logger.warning(f"  링크 없음 — 건너뜀")
        return []

    # 중복 제거
    seen_keys: set[str] = set()
    unique_urls = []
    for u in raw_urls:
        key = u[:80]
        if key not in seen_keys:
            seen_keys.add(key)
            unique_urls.append(u)

    logger.info(f"  고유 링크 {len(unique_urls)}개 → 쿠팡 URL 변환 시작")

    candidates: list[dict] = []
    seen_pids: set[str] = set()

    for lnk in unique_urls:
        if len(candidates) >= MAX_PER_PAGE:
            break

        coupang_url = _follow_to_coupang(lnk)
        if not coupang_url:
            continue

        pid = _product_id(coupang_url)
        if not pid or pid in seen_pids:
            continue
        seen_pids.add(pid)

        product_info = _fetch_coupang_product(coupang_url)
        if not product_info:
            continue

        extra = _naver_enrich(product_info["name"])
        product = {
            "name":          product_info["name"],
            "product_url":   coupang_url,
            "image_url":     product_info.get("image_url", ""),
            "price":         extra.get("price", ""),
            "brand":         extra.get("brand", ""),
            "category_hint": extra.get("category_hint", ""),
            "source":        "collection_scrape",
        }
        candidates.append({
            "product":        product,
            "source_account": source_label,
            "added_at":       datetime.now(KST).isoformat(),
        })
        logger.info(f"  [{len(candidates)}] {product['name'][:40]}")

    logger.info(f"  → {len(candidates)}개 수집 완료")
    return candidates


# ── 개별 상품 URL 처리 ────────────────────────────────────────────────────────

def _process_single_url(url: str) -> dict | None:
    coupang_url = _follow_to_coupang(url)
    if not coupang_url:
        return None
    product_info = _fetch_coupang_product(coupang_url)
    if not product_info:
        return None
    extra = _naver_enrich(product_info["name"])
    return {
        "product": {
            "name":          product_info["name"],
            "product_url":   coupang_url,
            "image_url":     product_info.get("image_url", ""),
            "price":         extra.get("price", ""),
            "brand":         extra.get("brand", ""),
            "category_hint": extra.get("category_hint", ""),
            "source":        "direct_url",
        },
        "source_account": "직접입력",
        "added_at":       datetime.now(KST).isoformat(),
    }


# ── 메인 ─────────────────────────────────────────────────────────────────────

async def run():
    logger.info("=" * 50)
    logger.info(f"URL 처리 시작: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    logger.info("=" * 50)

    pending = _load_json(PENDING_URLS_PATH, {"urls": []})
    urls = [u.strip() for u in pending.get("urls", []) if u.strip()]

    # pending이 비어있으면 저장된 소스 전체 재스캔
    if not urls:
        sources_data = _load_json(SOURCES_PATH, {"sources": []})
        saved = [s["url"] for s in sources_data.get("sources", [])]
        if saved:
            logger.info(f"pending 없음 → 저장된 소스 {len(saved)}개 재스캔")
            urls = saved
        else:
            logger.info("처리할 URL 없음")
            return

    logger.info(f"{len(urls)}개 URL 처리 시작")

    existing   = _load_json(CANDIDATES_PATH, {"scanned_at": "", "candidates": []})
    candidates = existing.get("candidates", [])
    existing_pids = {_product_id(c.get("product", {}).get("product_url", "")) for c in candidates} - {None}

    total_added = 0

    for url in urls:
        is_single = (
            re.search(r"coupang\.com/vp/products/\d+", url)
            or "link.coupang.com" in url
        )

        if is_single:
            logger.info(f"[단일] {url[:60]}")
            c = _process_single_url(url)
            if c:
                pid = _product_id(c["product"]["product_url"])
                if pid and pid not in existing_pids:
                    existing_pids.add(pid)
                    candidates.insert(0, c)
                    total_added += 1
        else:
            # 컬렉션/프로필 페이지
            label = [s for s in url.rstrip("/").split("/") if s][-1]
            new_items = await _scrape_collection(url, label)
            for c in new_items:
                pid = _product_id(c["product"]["product_url"])
                if pid and pid not in existing_pids:
                    existing_pids.add(pid)
                    candidates.insert(0, c)
                    total_added += 1

    candidates = candidates[:MAX_TOTAL]

    _save_json(CANDIDATES_PATH, {
        "scanned_at": existing.get("scanned_at", ""),
        "updated_at": datetime.now(KST).isoformat(),
        "candidates": candidates,
    })

    # 컬렉션 URL 영구 저장 (재스캔용)
    sources_data = _load_json(SOURCES_PATH, {"sources": [], "updated_at": ""})
    existing_source_urls = {s["url"] for s in sources_data.get("sources", [])}
    for url in urls:
        if url not in existing_source_urls:
            label = [s for s in url.rstrip("/").split("/") if s][-1]
            sources_data["sources"].append({
                "url":        url,
                "label":      label,
                "added_at":   datetime.now(KST).isoformat(),
            })
            existing_source_urls.add(url)
    sources_data["updated_at"] = datetime.now(KST).isoformat()
    _save_json(SOURCES_PATH, sources_data)
    logger.info(f"컬렉션 소스 누적: 총 {len(sources_data['sources'])}개 저장됨")

    _save_json(PENDING_URLS_PATH, {
        "urls": [], "submitted_at": "",
        "processed_at": datetime.now(KST).isoformat(),
    })

    logger.info(f"완료: {total_added}개 신규 추가, 총 {len(candidates)}개 후보")


if __name__ == "__main__":
    asyncio.run(run())
