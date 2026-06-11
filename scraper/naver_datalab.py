"""
네이버 데이터랩 트렌드 API
1차: 쇼핑인사이트 API (/datalab/shopping/categories) — 카테고리별 쇼핑 트렌드
2차: 검색어트렌드 API (/datalab/search) — 카테고리 대표 키워드 검색량 (폴백)
"""
import requests
import logging
from datetime import datetime, timedelta
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET

logger = logging.getLogger(__name__)

SHOPPING_URL = "https://openapi.naver.com/v1/datalab/shopping/categories"
SEARCH_URL   = "https://openapi.naver.com/v1/datalab/search"

# 쇼핑인사이트 카테고리 코드 (최대 3개 제한)
SHOPPING_CATEGORIES = [
    {"name": "생활/건강",   "param": ["50000008"]},
    {"name": "화장품/미용", "param": ["50000002"]},
    {"name": "디지털/가전", "param": ["50000003"]},
]

# 검색어트렌드 폴백: 카테고리별 대표 쇼핑 키워드
SEARCH_KEYWORD_GROUPS = [
    {"groupName": "생활/건강",    "keywords": ["생활꿀템", "주방용품", "생활가전"]},
    {"groupName": "화장품/미용",  "keywords": ["스킨케어", "화장품", "뷰티템"]},
    {"groupName": "가구/인테리어","keywords": ["인테리어용품", "가구", "홈데코"]},
    {"groupName": "디지털/가전",  "keywords": ["가전제품", "스마트기기", "IT제품"]},
    {"groupName": "스포츠/레저",  "keywords": ["운동용품", "홈트레이닝", "스포츠"]},
]


def _make_headers() -> dict:
    return {
        "X-Naver-Client-Id":     NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        "Content-Type": "application/json",
    }


def _get_date_range() -> tuple[str, str]:
    end_date   = datetime.now() - timedelta(days=1)
    start_date = end_date - timedelta(weeks=4)
    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


def _parse_scores(results: list) -> dict[str, float]:
    scores: dict[str, float] = {}
    for item in results:
        name   = item.get("title") or item.get("groupName") or ""
        data   = item.get("data", [])
        recent = data[-2:] if len(data) >= 2 else data
        score  = sum(d.get("ratio", 0) for d in recent) / max(len(recent), 1)
        scores[name] = score
        logger.info(f"  트렌드: {name} = {score:.1f}")
    return scores


def _try_shopping_insight(start_date: str, end_date: str) -> dict[str, float] | None:
    body = {
        "startDate": start_date,
        "endDate":   end_date,
        "timeUnit":  "week",
        "category":  SHOPPING_CATEGORIES,
    }
    try:
        resp = requests.post(SHOPPING_URL, json=body, headers=_make_headers(), timeout=10)
        resp.raise_for_status()
        scores = _parse_scores(resp.json().get("results", []))
        if scores:
            logger.info("쇼핑인사이트 API 성공")
        return scores or None
    except requests.HTTPError as e:
        body_text = e.response.text[:300] if e.response else ""
        logger.warning(f"쇼핑인사이트 {e.response.status_code if e.response else '?'}: {body_text}")
        return None
    except Exception as e:
        logger.warning(f"쇼핑인사이트 오류: {e}")
        return None


def _try_search_trend(start_date: str, end_date: str) -> dict[str, float] | None:
    body = {
        "startDate":     start_date,
        "endDate":       end_date,
        "timeUnit":      "week",
        "keywordGroups": SEARCH_KEYWORD_GROUPS,
    }
    try:
        resp = requests.post(SEARCH_URL, json=body, headers=_make_headers(), timeout=10)
        resp.raise_for_status()
        scores = _parse_scores(resp.json().get("results", []))
        if scores:
            logger.info("검색어트렌드 API 성공 (폴백)")
        return scores or None
    except requests.HTTPError as e:
        body_text = e.response.text[:300] if e.response else ""
        logger.warning(f"검색어트렌드 {e.response.status_code if e.response else '?'}: {body_text}")
        return None
    except Exception as e:
        logger.warning(f"검색어트렌드 오류: {e}")
        return None


def get_keyword_momentum(keywords: list[str]) -> dict[str, float]:
    """주어진 키워드들의 최근 모멘텀 점수 반환.

    점수 = avg(최근 2주 ratio) / avg(직전 4주 ratio).
    1.0 = 평년 수준, 1.3+ = 상승 추세 (시즌 진입), 0.7- = 하락.

    네이버 데이터랩 search API 1회당 최대 5개 키워드 그룹 처리 가능.
    빈 입력, API 키 없음, 에러 시 빈 dict 반환 (호출부에서 정렬 안 함).
    """
    if not keywords or not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return {}

    # 데이터랩 search API 제약: keywordGroups 최대 5개, 각 그룹 keywords 최대 20개
    BATCH = 5
    end_date   = datetime.now() - timedelta(days=1)
    start_date = end_date - timedelta(weeks=6)
    sd, ed = start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")

    scores: dict[str, float] = {}
    for i in range(0, len(keywords), BATCH):
        chunk = keywords[i:i + BATCH]
        body = {
            "startDate":     sd,
            "endDate":       ed,
            "timeUnit":      "week",
            "keywordGroups": [
                {"groupName": kw, "keywords": [kw]} for kw in chunk
            ],
        }
        try:
            resp = requests.post(SEARCH_URL, json=body, headers=_make_headers(), timeout=10)
            resp.raise_for_status()
            for item in resp.json().get("results", []):
                name = item.get("title") or ""
                data = item.get("data", [])
                if len(data) < 6:
                    continue
                recent = sum(d.get("ratio", 0) for d in data[-2:]) / 2
                baseline = sum(d.get("ratio", 0) for d in data[-6:-2]) / 4
                if baseline > 0:
                    scores[name] = recent / baseline
        except Exception as e:
            logger.warning(f"키워드 모멘텀 조회 실패 ({chunk}): {e}")
            continue

    if scores:
        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
        logger.info(f"모멘텀 Top: {[(k, f'{v:.2f}x') for k, v in top]}")
    return scores


def get_trending_categories(top_n: int = 3) -> list[str]:
    """최근 4주 트렌드 기준 상위 카테고리 이름 목록 반환"""
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        logger.warning("네이버 API 키 없음 — 데이터랩 스킵")
        return []

    start_date, end_date = _get_date_range()

    scores = _try_shopping_insight(start_date, end_date)
    if not scores:
        scores = _try_search_trend(start_date, end_date)

    if not scores:
        logger.warning("데이터랩 모든 API 실패 — 트렌드 없이 진행")
        return []

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top    = [name for name, _ in ranked[:top_n]]
    logger.info(f"트렌딩 Top {top_n}: {top}")
    return top
