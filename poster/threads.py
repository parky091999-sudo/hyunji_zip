"""
Threads 공식 API 포스터
Meta Graph API (graph.threads.net) 사용 — Playwright 브라우저 자동화 불필요
- IP 제한 없음 (GitHub Actions에서 직접 실행 가능)
- 봇 탐지 없음 (공식 API)
- 무료 (기본 포스팅 한도: 하루 250개)
"""
import asyncio
import os
import sys
import logging
import requests
import time

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import THREADS_ACCESS_TOKEN, THREADS_USER_ID

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.threads.net/v1.0"


def _api(method: str, path: str, **kwargs) -> dict:
    """Threads Graph API 공통 호출"""
    url = f"{GRAPH_BASE}{path}"
    resp = requests.request(method, url, timeout=30, **kwargs)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Threads API 오류: {data['error']}")
    return data


def create_text_container(text: str) -> str:
    """텍스트 전용 미디어 컨테이너 생성 → container_id 반환"""
    data = _api(
        "POST",
        f"/{THREADS_USER_ID}/threads",
        params={
            "media_type": "TEXT",
            "text": text,
            "access_token": THREADS_ACCESS_TOKEN,
        },
    )
    return data["id"]


def create_image_container(text: str, image_url: str) -> str:
    """이미지 + 텍스트 미디어 컨테이너 생성 → container_id 반환"""
    data = _api(
        "POST",
        f"/{THREADS_USER_ID}/threads",
        params={
            "media_type": "IMAGE",
            "text": text,
            "image_url": image_url,
            "access_token": THREADS_ACCESS_TOKEN,
        },
    )
    return data["id"]


def publish_container(container_id: str) -> str:
    """컨테이너를 실제 게시 → Threads 포스트 ID 반환"""
    data = _api(
        "POST",
        f"/{THREADS_USER_ID}/threads_publish",
        params={
            "creation_id": container_id,
            "access_token": THREADS_ACCESS_TOKEN,
        },
    )
    return data["id"]


def get_post_url(post_id: str) -> str | None:
    """포스트 ID로 permalink(URL) 조회"""
    try:
        data = _api(
            "GET",
            f"/{post_id}",
            params={
                "fields": "permalink",
                "access_token": THREADS_ACCESS_TOKEN,
            },
        )
        return data.get("permalink")
    except Exception as e:
        logger.warning(f"permalink 조회 실패: {e}")
        return None


def post_thread_api(post_text: str, image_url: str | None = None) -> dict | None:
    """
    Threads API로 게시글 작성
    반환: {"post_id": str, "post_url": str | None} (성공 시) / None (실패 시)
    """
    logger.info("Threads API 게시 시작...")

    if not THREADS_ACCESS_TOKEN or not THREADS_USER_ID:
        raise RuntimeError(
            "THREADS_ACCESS_TOKEN 또는 THREADS_USER_ID 환경변수가 없습니다.\n"
            "GitHub Secrets에 추가하거나 .env 파일에 설정하세요."
        )

    # 이미지 URL은 공개 URL 그대로 사용 (쿠팡/네이버 CDN은 이미 공개)
    public_image_url = image_url if (image_url and image_url.startswith("http")) else None

    # 1단계: 미디어 컨테이너 생성
    if public_image_url:
        logger.info(f"  이미지 컨테이너 생성: {public_image_url[:60]}...")
        container_id = create_image_container(post_text, public_image_url)
    else:
        logger.info("  텍스트 컨테이너 생성...")
        container_id = create_text_container(post_text)

    logger.info(f"  컨테이너 ID: {container_id}")

    # 2단계: 게시 전 대기 (Meta 권장: 30초)
    logger.info("  게시 대기 중 (30초)...")
    time.sleep(30)

    # 3단계: 게시
    post_id = publish_container(container_id)
    logger.info(f"  게시 완료 (post_id: {post_id})")

    # 4단계: URL 조회
    post_url = get_post_url(post_id)
    if post_url:
        logger.info(f"  게시 URL: {post_url}")

    return {"post_id": post_id, "post_url": post_url}


async def post_all_products(contents: list[dict]) -> tuple[list[str], list[dict]]:
    """
    여러 상품을 Threads API로 포스팅
    반환: (포스팅된 product_url 목록, story 게시글 정보 목록[{post_id, post_url}])
    """
    posted_urls: list[str] = []
    story_post_infos: list[dict] = []

    for i, content in enumerate(contents, 1):
        post_text = content["post_text_1"]
        image_url = content.get("image_url") or content["product"].get("image_url")
        name = content["product"].get("name", "")[:40]
        product_url = content["product"].get("product_url", "")

        logger.info(f"[{i}/{len(contents)}] 포스팅: {name}")
        try:
            result = post_thread_api(post_text, image_url)
            if result:
                story_post_infos.append(result)
            posted_urls.append(product_url)
            logger.info(f"  [{i}] 완료")

            if i < len(contents):
                logger.info("다음 상품까지 90초 대기...")
                await asyncio.sleep(90)

        except Exception as e:
            logger.error(f"[{i}] 포스팅 실패: {e}")

    return posted_urls, story_post_infos


async def post_product(content: dict):
    """단일 상품 포스팅 (하위 호환용)"""
    await post_all_products([content])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # 연결 테스트
    if not THREADS_ACCESS_TOKEN:
        print("❌ THREADS_ACCESS_TOKEN 없음 — .env 파일에 추가하세요")
    else:
        try:
            data = _api(
                "GET",
                f"/{THREADS_USER_ID}",
                params={"fields": "id,username", "access_token": THREADS_ACCESS_TOKEN},
            )
            print(f"✅ 연결 성공: @{data.get('username')} (id: {data.get('id')})")
        except Exception as e:
            print(f"❌ 연결 실패: {e}")
