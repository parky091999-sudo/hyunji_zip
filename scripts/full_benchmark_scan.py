"""
전체 벤치마크 스캔 — 주 1회 (일요일 밤 11시 KST) + 수동 트리거
29개 계정 전체 스캔 → 최대 50개 상품 후보 → data/manual_candidates.json 저장

threads_benchmark.py 의 Playwright 기반 파싱 로직을 재활용.
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import DATA_DIR, LOG_DIR

ACCOUNTS_PATH   = os.path.join(DATA_DIR, "benchmark_accounts.json")
CANDIDATES_PATH = os.path.join(DATA_DIR, "manual_candidates.json")
MAX_CANDIDATES  = 50
REQUEST_DELAY   = 3   # 계정 간 대기 (Playwright 부하 고려)

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


def _load_accounts() -> list:
    if not os.path.exists(ACCOUNTS_PATH):
        return []
    with open(ACCOUNTS_PATH, encoding="utf-8") as f:
        return [a for a in json.load(f) if a.get("active", True)]


def run():
    # threads_benchmark.py 의 검증된 함수들 재활용
    from scraper.threads_benchmark import (
        _fetch_posts,
        _extract_product_names,
        _search_naver,
    )

    logger.info("=" * 50)
    logger.info(f"전체 벤치마크 스캔 시작: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")

    accounts = _load_accounts()
    logger.info(f"스캔 대상: {len(accounts)}개 계정")

    # 기존 파일에서 이미 '선택됨' 항목 보존
    existing_selected = {}
    if os.path.exists(CANDIDATES_PATH):
        with open(CANDIDATES_PATH, encoding="utf-8") as f:
            old = json.load(f)
        for c in old.get("candidates", []):
            if c.get("selected"):
                url = c.get("product", {}).get("product_url", "")
                if url:
                    existing_selected[url] = c

    seen_urls: set[str] = set(existing_selected.keys())
    candidates: list[dict] = []

    for acc in accounts:
        if len(candidates) >= MAX_CANDIDATES:
            break

        username = acc["username"]
        logger.info(f"스캔: @{username}")

        try:
            posts = _fetch_posts(username)
            if not posts:
                logger.info(f"  → 게시글 없음")
                time.sleep(REQUEST_DELAY)
                continue

            logger.info(f"  → {len(posts)}개 게시글 파싱")
            names = _extract_product_names(posts, username)
            logger.info(f"  → 상품명 추출: {names}")

            for name in names:
                if len(candidates) >= MAX_CANDIDATES:
                    break

                product = _search_naver(name)
                if not product:
                    continue

                url = product.get("product_url", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                candidates.append({
                    "product":         product,
                    "source_account":  username,
                    "selected":        False,
                })
                logger.info(f"  ✅ {product['name'][:45]} | {product.get('price', '')}")

            time.sleep(REQUEST_DELAY)

        except Exception as e:
            logger.warning(f"  오류 ({username}): {e}")
            time.sleep(REQUEST_DELAY)

    # 기존 선택 항목 앞에 보존 + 새 후보 합치기
    preserved = list(existing_selected.values())
    final = (preserved + candidates)[:MAX_CANDIDATES]

    result = {
        "scanned_at": datetime.now(KST).isoformat(),
        "candidates": final,
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CANDIDATES_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    logger.info(f"완료: {len(final)}개 후보 저장 (선택보존 {len(preserved)}개 + 신규 {len(candidates)}개)")


if __name__ == "__main__":
    run()
