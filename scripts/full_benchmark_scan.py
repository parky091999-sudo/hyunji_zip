"""
전체 벤치마크 스캔 — 주 1회 (일요일 밤 11시 KST)
29개 계정 전체 스캔 → 최대 50개 상품 후보 → data/manual_candidates.json 저장
콘텐츠(post_text)는 미리 생성하지 않음 — 사용자가 선택 후 admin에서 편집 가능
"""
import json
import logging
import os
import sys
import time
import re
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import DATA_DIR, LOG_DIR, GROQ_API_KEY, NAVER_CLIENT_ID, NAVER_CLIENT_SECRET

ACCOUNTS_PATH    = os.path.join(DATA_DIR, "benchmark_accounts.json")
CANDIDATES_PATH  = os.path.join(DATA_DIR, "manual_candidates.json")
MAX_CANDIDATES   = 50
MAX_PER_ACCOUNT  = 3
REQUEST_DELAY    = 2

KST = timezone(timedelta(hours=9))

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "benchmark_scan.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("full_benchmark_scan")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://www.threads.net/",
}


def _load_accounts() -> list:
    if not os.path.exists(ACCOUNTS_PATH):
        return []
    with open(ACCOUNTS_PATH, encoding="utf-8") as f:
        return [a for a in json.load(f) if a.get("active", True)]


def _fetch_profile_posts(username: str) -> list[str]:
    """Threads 프로필에서 게시글 텍스트 목록 수집"""
    import requests
    url = f"https://www.threads.net/@{username}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=12)
        if resp.status_code != 200:
            return []
        html = resp.text

        # Next.js __NEXT_DATA__ JSON 파싱
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if not m:
            return []
        data = json.loads(m.group(1))

        texts = []
        raw = json.dumps(data, ensure_ascii=False)
        # 게시글 텍스트 패턴
        for match in re.finditer(r'"text_post_app_body_items":\[.*?"text"\s*:\s*"([^"]{20,400})"', raw):
            txt = match.group(1).replace("\\n", "\n")
            if txt and not any(t == txt for t in texts):
                texts.append(txt)
            if len(texts) >= MAX_PER_ACCOUNT:
                break

        if not texts:
            for match in re.finditer(r'"caption"\s*:\s*\{\s*"text"\s*:\s*"([^"]{20,400})"', raw):
                txt = match.group(1).replace("\\n", "\n")
                if txt and not any(t == txt for t in texts):
                    texts.append(txt)
                if len(texts) >= MAX_PER_ACCOUNT:
                    break

        return texts[:MAX_PER_ACCOUNT]
    except Exception as e:
        logger.debug(f"프로필 파싱 실패 ({username}): {e}")
        return []


def _extract_product_names(texts: list[str], account: str) -> list[str]:
    """Groq으로 텍스트에서 상품명 추출"""
    if not GROQ_API_KEY or not texts:
        return []
    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        combined = "\n---\n".join(texts[:MAX_PER_ACCOUNT])
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{
                "role": "user",
                "content": (
                    "다음은 한국 Threads 쇼핑 계정의 게시글들이야.\n"
                    "각 게시글에서 소개하는 구체적인 상품명을 최대 3개 추출해줘.\n"
                    "규칙:\n"
                    "- 카테고리(생활용품, 주방템 등) X, 구체적 상품명 O\n"
                    "- 한 줄에 상품명 1개\n"
                    "- 상품이 없으면 '없음' 출력\n\n"
                    f"게시글:\n{combined}"
                ),
            }],
            max_tokens=120,
            temperature=0.1,
        )
        raw = resp.choices[0].message.content.strip()
        names = [l.strip().lstrip("-•·0123456789. ") for l in raw.splitlines() if l.strip() and l.strip() != "없음"]
        return [n for n in names if len(n) >= 3][:MAX_PER_ACCOUNT]
    except Exception as e:
        logger.warning(f"Groq 추출 실패 ({account}): {e}")
        return []


def _find_coupang_product(name: str) -> dict | None:
    """네이버 쇼핑 API로 쿠팡 상품 검색"""
    if not NAVER_CLIENT_ID:
        return None
    import requests
    headers = {
        "X-Naver-Client-Id":     NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/shop.json",
            headers=headers,
            params={"query": name, "display": 15, "sort": "sim"},
            timeout=10,
        )
        resp.raise_for_status()
        for item in resp.json().get("items", []):
            mall = item.get("mallName", "")
            link = item.get("link", "")
            if "쿠팡" in mall or "coupang" in link.lower():
                raw_name = re.sub(r"<[^>]+>", "", item.get("title", name)).strip()
                lp = int(item.get("lprice", 0) or 0)
                return {
                    "name":        raw_name,
                    "price":       f"{lp:,}원" if lp else "",
                    "image_url":   item.get("image", ""),
                    "product_url": link,
                    "brand":       (item.get("brand") or item.get("maker") or "").strip(),
                    "source":      "benchmark",
                }
        return None
    except Exception as e:
        logger.debug(f"네이버 검색 오류 ({name}): {e}")
        return None


def run():
    logger.info("=" * 50)
    logger.info(f"전체 벤치마크 스캔 시작: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    logger.info("=" * 50)

    accounts = _load_accounts()
    logger.info(f"스캔 대상: {len(accounts)}개 계정")

    # 기존 후보 중 이미 선택된 것의 URL 목록 보존
    existing = {}
    if os.path.exists(CANDIDATES_PATH):
        with open(CANDIDATES_PATH, encoding="utf-8") as f:
            old = json.load(f)
        for c in old.get("candidates", []):
            if c.get("selected"):
                url = c.get("product", {}).get("product_url", "")
                if url:
                    existing[url] = c  # 선택된 항목은 유지

    seen_urls: set[str] = set(existing.keys())
    seen_names: set[str] = set()
    candidates = []

    for acc in accounts:
        if len(candidates) >= MAX_CANDIDATES:
            break
        username = acc["username"]
        logger.info(f"스캔: @{username}")
        try:
            texts = _fetch_profile_posts(username)
            if not texts:
                logger.info(f"  → 게시글 없음")
                time.sleep(REQUEST_DELAY)
                continue
            names = _extract_product_names(texts, username)
            logger.info(f"  → {len(names)}개 상품명 추출: {names}")
            for name in names:
                if len(candidates) >= MAX_CANDIDATES:
                    break
                key = name[:6]
                if key in seen_names:
                    continue
                seen_names.add(key)
                product = _find_coupang_product(name)
                if not product:
                    continue
                url = product.get("product_url", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                candidates.append({
                    "product":          product,
                    "source_account":   username,
                    "selected":         False,
                })
                logger.info(f"  ✅ {product['name'][:45]} | {product.get('price', '')}")
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            logger.warning(f"  오류 ({username}): {e}")
            time.sleep(REQUEST_DELAY)

    # 기존에 선택된 항목은 앞에 붙여서 보존
    preserved = list(existing.values())
    final_candidates = preserved + candidates

    result = {
        "scanned_at":  datetime.now(KST).isoformat(),
        "candidates":  final_candidates[:MAX_CANDIDATES],
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CANDIDATES_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    logger.info(f"완료: {len(final_candidates)}개 후보 저장 (manual_candidates.json)")


if __name__ == "__main__":
    run()
