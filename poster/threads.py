"""
Threads 공식 API 포스터
Meta Graph API (graph.threads.net) 사용 — Playwright 브라우저 자동화 불필요
- IP 제한 없음 (GitHub Actions에서 직접 실행 가능)
- 봇 탐지 없음 (공식 API)
- 무료 (기본 포스팅 한도: 하루 250개)
- ★ 수정: 이미지 3~4장 carousel 포스팅 지원
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
    """텍스트 전용 미디어 컨테이너 생성"""
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
    """단일 이미지 + 텍스트 컨테이너 생성"""
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


def create_carousel_item(image_url: str) -> str | None:
    """
    carousel용 개별 이미지 아이템 컨테이너 생성
    반환: item container_id (실패 시 None)
    """
    try:
        data = _api(
            "POST",
            f"/{THREADS_USER_ID}/threads",
            params={
                "media_type": "IMAGE",
                "image_url": image_url,
                "is_carousel_item": "true",
                "access_token": THREADS_ACCESS_TOKEN,
            },
        )
        item_id = data.get("id", "")
        logger.info(f"    carousel 아이템 등록: {item_id} | {image_url[:50]}")
        return item_id
    except Exception as e:
        logger.warning(f"    carousel 아이템 실패 ({image_url[:40]}): {e}")
        return None


def create_carousel_container(text: str, child_ids: list[str]) -> str:
    """
    carousel 메인 컨테이너 생성
    child_ids: 개별 이미지 아이템 ID 리스트 (2~20개)
    """
    data = _api(
        "POST",
        f"/{THREADS_USER_ID}/threads",
        params={
            "media_type": "CAROUSEL",
            "text": text,
            "children": ",".join(child_ids),
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


def find_recent_post_by_marker(marker: str, limit: int = 25) -> dict | None:
    """최근 내 게시글에서 marker(예: '[013] 검색') 포함 글 탐색 — 중복 게시 차단용.
    발견 시 {post_id, post_url} 반환, 없거나 조회 실패 시 None (게시 진행)."""
    if not marker or not THREADS_ACCESS_TOKEN:
        return None
    try:
        data = _api(
            "GET",
            f"/{THREADS_USER_ID}/threads",
            params={
                "fields": "id,text,permalink",
                "limit": limit,
                "access_token": THREADS_ACCESS_TOKEN,
            },
        )
        for p in data.get("data", []):
            if marker in (p.get("text") or ""):
                return {"post_id": p.get("id", ""), "post_url": p.get("permalink")}
    except Exception as e:
        logger.warning(f"최근 게시글 조회 실패(가드 생략): {e}")
    return None


def post_thread_api(
    post_text: str,
    image_url: str | None = None,
    detail_images: list[str] | None = None,
    fallback_image_url: str | None = None,
) -> dict | None:
    """
    Threads API로 게시글 작성

    ★ 이미지 처리 우선순위:
    1. detail_images가 2장 이상 → carousel 포스팅 (3~4장)
    2. detail_images가 1장 또는 image_url만 있음 → 단일 이미지 포스팅
    3. 이미지 없음 → 텍스트만 포스팅

    반환: {"post_id": str, "post_url": str | None}
    """
    logger.info("Threads API 게시 시작...")

    if not THREADS_ACCESS_TOKEN or not THREADS_USER_ID:
        raise RuntimeError(
            "THREADS_ACCESS_TOKEN 또는 THREADS_USER_ID 환경변수가 없습니다."
        )

    # 사용할 이미지 목록 결정
    images_to_use: list[str] = []
    if detail_images and len(detail_images) >= 1:
        images_to_use = [img for img in detail_images if img and img.startswith("http")]
    if not images_to_use and image_url and image_url.startswith("http"):
        images_to_use = [image_url]

    # ── 케이스 1: 이미지 2장 이상 → carousel ─────────────────────────────────
    if len(images_to_use) >= 2:
        logger.info(f"  carousel 포스팅: {len(images_to_use)}장")
        container_id = _create_carousel_post(
            post_text, images_to_use[:4], fallback_image_url or image_url
        )

    # ── 케이스 2: 이미지 1장 → 단일 이미지 ──────────────────────────────────
    elif len(images_to_use) == 1:
        logger.info(f"  단일 이미지 포스팅: {images_to_use[0][:50]}")
        try:
            container_id = create_image_container(post_text, images_to_use[0])
        except Exception as e:
            fb = fallback_image_url or image_url
            if fb and fb != images_to_use[0]:
                logger.warning(f"  이미지 컨테이너 실패 → 원본 이미지로 재시도: {e}")
                container_id = create_image_container(post_text, fb)
            else:
                raise

    # ── 케이스 3: 이미지 없음 → 텍스트만 ────────────────────────────────────
    else:
        logger.info("  텍스트 전용 포스팅")
        container_id = create_text_container(post_text)

    logger.info(f"  컨테이너 ID: {container_id}")

    # 게시 전 대기 (Meta 권장: 30초)
    logger.info("  게시 대기 중 (30초)...")
    time.sleep(30)

    # 게시
    post_id = publish_container(container_id)
    logger.info(f"  게시 완료 (post_id: {post_id})")

    # URL 조회
    time.sleep(5)
    post_url = get_post_url(post_id)
    if post_url:
        logger.info(f"  게시 URL: {post_url}")

    return {"post_id": post_id, "post_url": post_url}


def _create_carousel_post(
    text: str, image_urls: list[str], fallback_image_url: str | None = None
) -> str:
    """
    carousel 컨테이너 생성 전체 플로우
    1. 각 이미지 아이템 컨테이너 생성
    2. carousel 컨테이너 생성
    실패한 이미지는 건너뜀 — 최소 2장 있어야 carousel 가능
    """
    child_ids: list[str] = []

    for img_url in image_urls:
        item_id = create_carousel_item(img_url)
        if item_id:
            child_ids.append(item_id)
        time.sleep(2)  # 아이템 생성 간 대기

    # carousel은 최소 2장 필요
    if len(child_ids) < 2:
        logger.warning(f"  carousel 아이템 {len(child_ids)}개만 성공 → 단일 이미지로 폴백")
        # 폴백 우선순위: 성공한 AI 이미지 → 원본 상품 이미지 → 텍스트
        candidates = []
        if child_ids:
            candidates.append(image_urls[0])
        if fallback_image_url and fallback_image_url.startswith("http"):
            candidates.append(fallback_image_url)
        for cand in candidates:
            try:
                return create_image_container(text, cand)
            except Exception as e:
                logger.warning(f"  단일 이미지 폴백 실패({cand[:40]}): {e}")
        logger.warning("  모든 이미지 실패 → 텍스트 전용 게시")
        return create_text_container(text)

    # carousel 컨테이너 생성
    carousel_id = create_carousel_container(text, child_ids)
    logger.info(f"  carousel 컨테이너: {carousel_id} ({len(child_ids)}장)")
    return carousel_id


async def post_all_products(contents: list[dict]) -> tuple[list[str], list[dict]]:
    """
    여러 상품을 Threads API로 포스팅
    반환: (포스팅된 product_url 목록, 게시글 정보 목록[{post_id, post_url}])
    """
    posted_urls: list[str] = []
    story_post_infos: list[dict] = []

    for i, content in enumerate(contents, 1):
        post_text = content["post_text_1"]
        # ★ detail_images 우선 사용, 없으면 image_url 폴백
        detail_images = content.get("detail_images") or []
        image_url = content.get("image_url") or content["product"].get("image_url")
        name = content["product"].get("name", "")[:40]
        product_url = content["product"].get("product_url", "")

        logger.info(f"[{i}/{len(contents)}] 포스팅: {name}")
        logger.info(f"  이미지: {len(detail_images)}장 (상세) + 대표 1장 폴백")

        try:
            result = post_thread_api(
                post_text=post_text,
                image_url=image_url,
                detail_images=detail_images,
            )
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
