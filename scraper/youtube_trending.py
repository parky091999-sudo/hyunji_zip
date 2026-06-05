"""
YouTube 트렌딩 상품 탐지기
- YouTube Data API v3로 한국 바이럴 생활용품 영상 검색
- Groq AI로 영상 제목/설명에서 상품명 추출
- 네이버 쇼핑 API로 쿠팡 상품 매칭
- 무료 쿼터: 10,000 units/day (검색 100 units/회 → 하루 100회)
"""
import logging
import random
import sys
import os
from datetime import datetime, timedelta, timezone

import requests

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import YOUTUBE_API_KEY, GROQ_API_KEY

logger = logging.getLogger(__name__)

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEO_URL  = "https://www.googleapis.com/youtube/v3/videos"

# 바이럴 생활용품 영상이 많이 올라오는 키워드
SEARCH_KEYWORDS = [
    "이거 없으면 후회 생활용품",
    "이게 된다고 신기한 물건",
    "생활꿀템 추천",
    "주방 신기한 물건",
    "처음 보는 신기한 제품",
    "SNS 유행 생활용품",
    "신박한 주방용품",
    "신기한 생활용품 추천",
    "살림템 추천",
    "아이디어 생활용품",
    "자취 필수템 추천",
    "집에서 꼭 필요한 물건",
    "주방 가전 추천",
    "요즘 핫한 생활용품",
    "알리 신기한 물건",
]

# 한 번에 사용할 키워드 수 (쿼터: 6개 × 100 = 600 units/실행)
KEYWORDS_PER_RUN = 6
# 최근 며칠 내 영상만 (30일로 확장)
PUBLISHED_DAYS = 30


def _search_videos(keyword: str, max_results: int = 15) -> list[dict]:
    """YouTube에서 최근 영상 검색 — 조회수 순"""
    if not YOUTUBE_API_KEY:
        return []

    published_after = (
        datetime.now(timezone.utc) - timedelta(days=PUBLISHED_DAYS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "part": "snippet",
        "q": keyword,
        "type": "video",
        "regionCode": "KR",
        "relevanceLanguage": "ko",
        "order": "viewCount",
        "publishedAfter": published_after,
        "maxResults": max_results,
        "key": YOUTUBE_API_KEY,
    }
    try:
        resp = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json().get("items", [])
    except Exception as e:
        logger.warning(f"YouTube 검색 실패 ({keyword}): {e}")
        return []


def _get_view_counts(video_ids: list[str]) -> dict[str, int]:
    """영상 조회수 일괄 조회 (1 unit/영상 — 매우 저렴)"""
    if not video_ids or not YOUTUBE_API_KEY:
        return {}
    params = {
        "part": "statistics",
        "id": ",".join(video_ids),
        "key": YOUTUBE_API_KEY,
    }
    try:
        resp = requests.get(YOUTUBE_VIDEO_URL, params=params, timeout=10)
        resp.raise_for_status()
        return {
            item["id"]: int(item["statistics"].get("viewCount", 0))
            for item in resp.json().get("items", [])
        }
    except Exception as e:
        logger.warning(f"조회수 조회 실패: {e}")
        return {}


def _extract_product_name(title: str, description: str) -> str | None:
    """Groq으로 영상 제목/설명에서 소개 상품명 추출"""
    if not GROQ_API_KEY:
        return None
    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)

        prompt = (
            "다음은 한국 유튜브 영상의 제목과 설명이야.\n"
            "영상에서 소개하는 주요 상품명을 딱 하나만 추출해줘.\n\n"
            "규칙:\n"
            "- 상품 카테고리 X, 구체적 상품명 O (예: '식세기' O, '주방용품' X)\n"
            "- 브랜드명 포함 가능\n"
            "- 상품명만 출력. 설명 없이.\n"
            "- 상품이 없거나 판단 불가면 '없음' 출력\n\n"
            f"제목: {title}\n"
            f"설명: {description[:300]}"
        )

        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=30,
            temperature=0.1,
        )
        result = resp.choices[0].message.content.strip().strip('"\'')
        if not result or result == "없음":
            return None
        return result
    except Exception as e:
        logger.warning(f"상품명 추출 실패: {e}")
        return None


def _find_naver_product(product_name: str) -> dict | None:
    """추출된 상품명으로 네이버 쇼핑 검색 → 쿠팡 상품 우선 반환"""
    try:
        from scraper.naver_shopping import _fetch_items, _to_product
        items = _fetch_items(product_name, display=20)
        coupang_hit = None
        any_hit = None
        for item in items:
            p = _to_product(item, category_hint="생활")
            if not p:
                continue
            if any_hit is None:
                any_hit = p
            is_cp = (
                "쿠팡" in p.get("mall_name", "")
                or "coupang" in p.get("product_url", "").lower()
            )
            if is_cp and coupang_hit is None:
                coupang_hit = p
            if coupang_hit:
                break
        return coupang_hit  # 쿠팡 링크만 허용 (비쿠팡은 네이버 보안확인 팝업 뜸)
    except Exception as e:
        logger.warning(f"네이버 상품 검색 실패 ({product_name}): {e}")
        return None


def scrape_trending_products(max_items: int = 5) -> list[dict]:
    """
    YouTube 트렌딩 영상 → 상품명 추출 → 네이버 쇼핑 매칭
    반환: 네이버 쇼핑 상품 포맷 (naver_shopping.scrape_deals와 동일 구조)
    """
    if not YOUTUBE_API_KEY:
        logger.error("YOUTUBE_API_KEY 미설정 — .env에 추가 필요")
        return []

    seen_names: set[str] = set()
    results: list[dict] = []

    keywords = random.sample(SEARCH_KEYWORDS, min(KEYWORDS_PER_RUN, len(SEARCH_KEYWORDS)))

    for keyword in keywords:
        if len(results) >= max_items:
            break

        logger.info(f"[YouTube] 검색: '{keyword}'")
        videos = _search_videos(keyword, max_results=15)
        if not videos:
            continue

        # 조회수 기준 재정렬
        video_ids = [v["id"]["videoId"] for v in videos if "videoId" in v.get("id", {})]
        view_counts = _get_view_counts(video_ids)
        videos_sorted = sorted(
            videos,
            key=lambda v: view_counts.get(v.get("id", {}).get("videoId", ""), 0),
            reverse=True,
        )

        for video in videos_sorted:
            if len(results) >= max_items:
                break

            snippet     = video.get("snippet", {})
            title       = snippet.get("title", "")
            description = snippet.get("description", "")
            video_id    = video.get("id", {}).get("videoId", "")
            views       = view_counts.get(video_id, 0)

            logger.info(f"  영상 ({views:,}회): {title[:55]}")

            product_name = _extract_product_name(title, description)
            if not product_name:
                logger.info("  → 상품명 없음, 스킵")
                continue

            key = product_name[:5]
            if key in seen_names:
                logger.info(f"  → 중복: {product_name}")
                continue
            seen_names.add(key)

            logger.info(f"  → 추출 상품명: {product_name}")

            product = _find_naver_product(product_name)
            if product:
                product["youtube_source"] = {
                    "title": title,
                    "video_id": video_id,
                    "views": views,
                    "keyword": keyword,
                }
                logger.info(f"  → 매칭: {product['name'][:40]} | {product['price']}")
                results.append(product)
            else:
                logger.warning(f"  → 네이버 쇼핑 매칭 실패: {product_name}")

    logger.info(f"[YouTube] 최종 수집: {len(results)}개")
    return results
