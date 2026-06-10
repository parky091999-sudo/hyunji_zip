"""
상품 이미지를 Gemini(gemini-3.1-flash-image)로 3가지 스타일 변형 → imgBB 업로드
  1) 흰색 스튜디오 배경 제품 사진
  2) 따뜻한 자연광 라이프스타일 샷
  3) 미니멀 클로즈업
실패 시 [] 반환 → 호출부에서 원본 이미지 유지
"""
import base64
import io
import logging
import os
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
IMGBB_API_KEY  = os.getenv("IMGBB_API_KEY", "")
logger = logging.getLogger("image_gen")

_PROMPTS = [
    "이 상품 사진을 깔끔한 흰색 스튜디오 배경의 전문 제품 사진으로 변환해줘. 상품은 그대로 유지하고 배경만 순백으로 바꿔줘.",
    "이 상품 사진을 따뜻한 자연광이 있는 라이프스타일 사진으로 변환해줘. 상품을 자연스러운 생활 공간에 배치해줘.",
    "이 상품 사진을 미니멀하고 세련된 클로즈업으로 변환해줘. 상품을 화면 가득 채우고 배경은 부드럽게 흐릿하게 처리해줘.",
]


def _download_image(url: str) -> bytes | None:
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200 and len(r.content) > 3000:
            return r.content
    except Exception as e:
        logger.warning(f"이미지 다운로드 실패: {e}")
    return None


def _upload_imgbb(img_bytes: bytes) -> str | None:
    try:
        b64 = base64.b64encode(img_bytes).decode()
        r = requests.post(
            "https://api.imgbb.com/1/upload",
            data={"key": IMGBB_API_KEY, "image": b64},
            timeout=30,
        )
        if r.status_code == 200:
            d = r.json()["data"]
            # display_url = 직접 렌더링 가능한 이미지 URL (Threads가 fetch 가능해야 함)
            return d.get("display_url") or d.get("url")
        logger.warning(f"imgBB 오류: {r.status_code}")
    except Exception as e:
        logger.warning(f"imgBB 업로드 실패: {e}")
    return None


def generate_and_upload_images(product: dict, post_text: str = "") -> list[str]:
    """
    상품 이미지 다운로드 → Gemini로 3종 변형 → imgBB 업로드 → URL 목록 반환.
    키 없거나 전체 실패 시 [] 반환.
    """
    if not GEMINI_API_KEY:
        logger.info("GEMINI_API_KEY 없음 → 이미지 생성 건너뜀")
        return []
    if not IMGBB_API_KEY:
        logger.info("IMGBB_API_KEY 없음 → 이미지 생성 건너뜀")
        return []

    try:
        from google import genai
        from google.genai import types
        from PIL import Image
    except ImportError as e:
        logger.warning(f"패키지 없음: {e}")
        return []

    image_url = product.get("image_url", "")
    if not image_url:
        logger.warning("상품 이미지 URL 없음")
        return []

    logger.info(f"상품 이미지 다운로드: {image_url[:60]}...")
    img_bytes = _download_image(image_url)
    if not img_bytes:
        return []

    try:
        pil_image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception as e:
        logger.warning(f"이미지 열기 실패: {e}")
        return []

    client = genai.Client(api_key=GEMINI_API_KEY)
    results = []

    for i, prompt in enumerate(_PROMPTS):
        try:
            logger.info(f"  이미지 {i+1}/3 생성 중...")
            response = client.models.generate_content(
                model="gemini-3.1-flash-image",
                contents=[prompt, pil_image],
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                ),
            )
            for part in response.parts:
                if getattr(part, "thought", False):
                    continue
                if part.inline_data is not None:
                    raw = part.inline_data.data
                    img_bytes = base64.b64decode(raw) if isinstance(raw, str) else raw
                    url = _upload_imgbb(img_bytes)
                    if url:
                        results.append(url)
                        logger.info(f"  업로드 완료 ({i+1}): {url[:55]}...")
                    break
        except Exception as e:
            logger.warning(f"  이미지 {i+1} 생성 실패: {e}")

    logger.info(f"이미지 생성 결과: {len(results)}장 성공 / 3장 시도")
    return results
