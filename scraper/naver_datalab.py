"""
네이버 데이터랩 쇼핑 인사이트 API
- 카테고리별 최근 트렌드 점수 조회
- 트렌딩 카테고리 우선순위 반환
"""
import requests
import logging
from datetime import datetime, timedelta
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET

logger = logging.getLogger(__name__)

DATALAB_URL = "https://openapi.naver.com/v1/datalab/shopping/categories"

# 데이터랩 카테고리 코드 (네이버 공식)
# 식품은 계정 컨셉(생활꿀템)과 안 맞아서 제외
CATEGORIES = [
    {"name": "생활/건강",    "param": ["50000009"]},
    {"name": "화장품/미용",  "param": ["50000003"]},
    {"name": "가구/인테리어","param": ["50000005"]},
    {"name": "디지털/가전",  "param": ["50000004"]},
    {"name": "스포츠/레저",  "param": ["50000008"]},
    {"name": "출산/육아",    "param": ["50000006"]},
]


def get_trending_categories(top_n: int = 3) -> list[str]:
    """최근 4주 트렌드 점수 기준으로 상위 카테고리 이름 목록 반환"""
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        logger.warning("네이버 API 키 없음 — 데이터랩 스킵")
        return []

    end_date   = datetime.now()
    start_date = end_date - timedelta(weeks=4)

    body = {
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate":   end_date.strftime("%Y-%m-%d"),
        "timeUnit":  "week",
        "category":  CATEGORIES,
    }
    headers = {
        "X-Naver-Client-Id":     NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(DATALAB_URL, json=body, headers=headers, timeout=10)
        resp.raise_for_status()
        results = resp.json().get("results", [])

        scores: dict[str, float] = {}
        for item in results:
            name = item["title"]
            data = item.get("data", [])
            # 최근 2주 평균으로 현재 트렌드 점수 계산
            recent = data[-2:] if len(data) >= 2 else data
            score  = sum(d.get("ratio", 0) for d in recent) / max(len(recent), 1)
            scores[name] = score
            logger.info(f"  데이터랩 트렌드: {name} = {score:.1f}")

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top    = [name for name, _ in ranked[:top_n]]
        logger.info(f"트렌딩 Top {top_n}: {top}")
        return top

    except Exception as e:
        logger.warning(f"데이터랩 API 오류: {e}")
        return []
