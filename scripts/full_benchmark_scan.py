"""
전체 벤치마크 스캔 — 주 1회 (일요일 밤 23시 KST) + 수동 트리거
네이버 데이터랩 트렌드 + 쇼핑 키워드 기반으로 50개 후보 수집.

이전: Playwright로 타 계정 Threads 크롤링 → GitHub Actions IP 차단으로 항상 실패.
현재: 공식 네이버 쇼핑 API + 데이터랩 트렌드 기반 키워드 검색 → 안정적.
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

CANDIDATES_PATH = os.path.join(DATA_DIR, "manual_candidates.json")
REJECTED_PATH   = os.path.join(DATA_DIR, "rejected_products.json")
MAX_CANDIDATES  = 50
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

# 카테고리별 검색 키워드 풀 (시즌 반영)
SEARCH_POOLS = {
    "생활/청소": ["스팀청소기", "무선청소기", "욕실 청소용품", "세탁조클리너", "배수구청소솔", "스크래퍼 청소"],
    "주방": ["에어프라이어", "실리콘주걱세트", "원터치밀폐용기", "과일탈수기", "냉장고정리함"],
    "디지털/가전": ["미니선풍기 USB", "휴대용 선풍기", "넥밴드 선풍기", "USB 냉각패드", "소형 제습기"],
    "먹는거": ["간식 추천 쿠팡", "캐릭터 젤리", "수입 과자", "건강 견과류", "냉동 밀키트"],
    "뷰티": ["더마 롤러", "미백 앰플", "클렌징 오일", "쿠션팩트", "두피 스케일러"],
    "인테리어": ["무타공 선반", "자석 메모보드", "감성 무드등", "원목 쟁반", "북유럽 캔들"],
    "수납/정리": ["서랍 칸막이", "케이블정리 클립", "신발정리대", "냉장고 수납박스", "다이소 스타일 수납"],
}


def _load_rejected() -> set:
    try:
        d = json.load(open(REJECTED_PATH, encoding="utf-8"))
        urls = d if isinstance(d, list) else d.get("urls", [])
        return set(urls)
    except Exception:
        return set()


def run():
    from scraper.naver_shopping import _fetch_items, _to_product, _is_chinese_seller_style

    logger.info("=" * 50)
    logger.info(f"벤치마크 스캔 시작: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")

    rejected = _load_rejected()

    # 기존 선택된 항목 보존
    existing_selected = {}
    if os.path.exists(CANDIDATES_PATH):
        try:
            old = json.load(open(CANDIDATES_PATH, encoding="utf-8"))
            for c in old.get("candidates", []):
                if c.get("selected") and c.get("product", {}).get("product_url"):
                    url = c["product"]["product_url"]
                    existing_selected[url] = c
        except Exception:
            pass

    seen_urls = set(existing_selected.keys())
    candidates = []

    for category, keywords in SEARCH_POOLS.items():
        if len(candidates) >= MAX_CANDIDATES:
            break
        logger.info(f"카테고리: {category}")
        for kw in keywords:
            if len(candidates) >= MAX_CANDIDATES:
                break
            try:
                logger.info(f"  검색: {kw}")
                items = _fetch_items(kw)
                logger.info(f"    → {len(items)}개 항목 수신")

                for item in items:
                    if len(candidates) >= MAX_CANDIDATES:
                        break
                    p = _to_product(item, category_hint=category)
                    if not p:
                        continue

                    # 중국산/저품질 필터
                    if _is_chinese_seller_style(p.get("name", "")):
                        continue

                    url = p.get("product_url", "")
                    if not url or url in seen_urls or url in rejected:
                        continue

                    seen_urls.add(url)
                    candidates.append({
                        "product": p,
                        "source_account": f"검색:{kw}",
                        "selected": False,
                    })
                    logger.info(f"  ✅ [{category}] {p.get('name','')[:40]}")

                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"  키워드 오류({kw}): {e}")

    preserved = list(existing_selected.values())
    final = (preserved + candidates)[:MAX_CANDIDATES]

    result = {
        "scanned_at": datetime.now(KST).isoformat(),
        "candidates": final,
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CANDIDATES_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    logger.info(f"완료: {len(final)}개 후보 저장 (보존 {len(preserved)}개 + 신규 {len(candidates)}개)")


if __name__ == "__main__":
    run()
