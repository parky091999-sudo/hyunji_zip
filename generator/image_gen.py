"""
상품 이미지를 Gemini(gemini-3.1-flash-image)로 클리닝 → imgBB 업로드
  - 흰색 스튜디오 배경 + 원본의 모든 글자/치수/설명 제거 (1장만)
실패 시 [] 반환 → 호출부에서 원본 이미지 유지

설계 변경 (2026-06-11):
  003/013/014/015처럼 원본에 치수·설명·중국어 텍스트가 박혀있는 경우 깔끔하게
  보이지 않아 단일 흰배경 클린샷 1장으로 통일. 라이프스타일 컷은 원본 외형 왜곡
  소지가 있어 제외.
"""
import base64
import io
import logging
import os
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
IMGBB_API_KEY  = os.getenv("IMGBB_API_KEY", "")
logger = logging.getLogger("image_gen")

_PROMPTS = [
    (
        "이 이미지에서 오직 핵심 제품 하나만 추출해서 깨끗한 흰색 스튜디오 배경의 전문 제품 사진으로 만들어줘. "
        "다음은 반드시 완전히 제거해야 해 — 한 글자도 남기지 마: "
        "한국어/중국어/일본어/영어 글자, 치수 표기(예: 200w, 20cm, 1.5m), "
        "사이즈 라벨, 설명 문구, 가격표, 화살표, 비교표, 인포그래픽, 워터마크, "
        "로고에 포함된 글자, 제품 위/주변에 적힌 모든 텍스트. "
        "제품의 형태·색상·재질은 원본과 동일하게 유지하고, 배경은 순백, "
        "바닥에 자연스러운 옅은 그림자만 살짝 추가. 결과는 깔끔한 제품 컷 한 장."
    ),
]


def _download_image(url: str) -> bytes | None:
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200 and len(r.content) > 3000:
            return r.content
    except Exception as e:
        logger.warning(f"이미지 다운로드 실패: {e}")
    return None


def _to_clean_jpeg(img_bytes: bytes) -> bytes:
    """Gemini 출력 바이트를 표준 JPEG으로 강제 재인코딩.

    Threads API가 imgBB의 비표준 컨테이너(WebP/PNG with alpha 등) fetch에
    실패하는 문제(2207052/2207083) 회피용. PIL로 RGB 변환 후 quality=92 JPEG.
    """
    from PIL import Image
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=92, optimize=True)
    return buf.getvalue()


def _upload_imgbb(img_bytes: bytes) -> str | None:
    try:
        b64 = base64.b64encode(img_bytes).decode()
        r = requests.post(
            "https://api.imgbb.com/1/upload",
            data={
                "key": IMGBB_API_KEY,
                "image": b64,
                # 명시적 .jpg 확장자 — Threads가 Content-Type/URL 모두 jpg로 인식
                "name": f"kkulpick_{int(time.time())}",
            },
            timeout=30,
        )
        if r.status_code == 200:
            d = r.json()["data"]
            # url = 원본 직접 URL (확장자 보존). display_url은 변환 거치는 경우 있어 회피.
            return d.get("url") or d.get("display_url")
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
            logger.info(f"  이미지 {i+1}/{len(_PROMPTS)} 생성 중...")
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
                    # Gemini 출력은 컨테이너 형식이 들쭉날쭉(WebP/PNG with alpha 등) — Threads가
                    # imgBB의 비표준 형식 fetch에 실패해 carousel 0/N으로 폴백되는 버그 회피.
                    try:
                        img_bytes = _to_clean_jpeg(img_bytes)
                    except Exception as e:
                        logger.warning(f"  JPEG 재인코딩 실패, 원본 업로드 시도: {e}")
                    url = _upload_imgbb(img_bytes)
                    if url:
                        results.append(url)
                        logger.info(f"  업로드 완료 ({i+1}): {url[:55]}...")
                    break
        except Exception as e:
            logger.warning(f"  이미지 {i+1} 생성 실패: {e}")

    logger.info(f"이미지 생성 결과: {len(results)}장 성공 / {len(_PROMPTS)}장 시도")
    return results
