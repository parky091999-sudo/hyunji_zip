"""
AI 이미지 생성
- Gemini로 프롬프트 생성 → pollinations.ai 다운로드 → imgBB 영구 업로드
- imgBB 업로드 성공한 URL만 반환 (pollinations URL을 Threads에 직접 넘기지 않음)
- 실패 시 [] 반환 → 호출부에서 원본 이미지 유지
"""
import base64
import logging
import os
import sys
import time
from urllib.parse import quote

import requests

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
from config import GOOGLE_API_KEY

IMGBB_API_KEY = os.getenv("IMGBB_API_KEY", "")

logger = logging.getLogger("image_gen")

# 카테고리별 영문 폴백 프롬프트 (Gemini 실패 시 사용, 영문만 사용해야 pollinations 정확도 높음)
CATEGORY_PROMPTS = {
    "뷰티": [
        "Korean LED facial mask skincare device, soft pink pastel studio lighting, cosmetic product photography, clean white background, 4k",
        "woman using face beauty device at home, Korean beauty aesthetic, warm natural light, lifestyle photography",
        "skincare beauty gadget flat lay, rose gold tones, minimal elegant composition, editorial style",
        "anti-aging LED mask beauty product, modern bathroom setting, glowing skin concept, professional photo",
    ],
    "주방": [
        "modern kitchen appliance product photography, bright clean white background, professional studio lighting, 4k",
        "cooking lifestyle scene, Korean home kitchen aesthetic, warm natural light, food styling",
        "kitchen gadget flat lay, marble surface, minimalist composition, editorial food photography",
        "home cooking product in use, cozy kitchen setting, soft warm tones, lifestyle photo",
    ],
    "생활": [
        "home lifestyle product photography, cozy interior, warm natural lighting, clean background, 4k",
        "smart home device in modern living room, Scandinavian interior aesthetic, soft focus",
        "household product flat lay, white linen background, minimal editorial composition",
        "home product lifestyle shot, cozy domestic scene, warm golden hour light",
    ],
    "디지털/가전": [
        "tech gadget product photography, minimalist white studio background, sharp focus, 4k",
        "electronic device lifestyle shot, modern desk setup, clean aesthetic, professional lighting",
        "smart device flat lay, dark matte surface, dramatic studio lighting, editorial",
        "technology product in use, modern home office, natural daylight, lifestyle photography",
    ],
    "인테리어": [
        "cozy interior decor product, Scandinavian home aesthetic, warm mood lighting, lifestyle photography",
        "home decoration flat lay, minimal white background, editorial composition, 4k",
        "interior design product in room setting, warm ambient light, lifestyle shot",
        "decorative home item, elegant modern interior, soft natural daylight",
    ],
    "기타": [
        "lifestyle product photography, clean white background, professional studio lighting, 4k",
        "product flat lay composition, minimal editorial style, warm neutral tones",
        "product in use lifestyle photo, natural light, Korean aesthetic, modern setting",
        "commercial product photography, sharp focus, elegant background, professional",
    ],
}


def _make_prompts(product: dict, post_text: str) -> list[str]:
    category = product.get("category_hint", product.get("category", "기타"))

    if GOOGLE_API_KEY:
        try:
            import google.generativeai as genai
            genai.configure(api_key=GOOGLE_API_KEY)
            model = genai.GenerativeModel("gemini-2.0-flash")
            res = model.generate_content(
                f"""Write 4 English image prompts for AI image generation for this Korean shopping product.
Product: {product.get('name', '')}
Category: {category}

Rules:
- English ONLY (no Korean characters)
- Each prompt on one line, no numbering
- Professional commercial product photography style
- Include the product context (in use, flat lay, lifestyle, etc.)
- Include: Korean lifestyle aesthetic, studio quality, 4k
- Output exactly 4 prompts separated by newlines""",
                generation_config=genai.types.GenerationConfig(temperature=0.7),
            )
            lines = [l.strip() for l in res.text.strip().split("\n") if l.strip()][:4]
            if len(lines) >= 3:
                return lines
        except Exception as e:
            logger.warning(f"Gemini 프롬프트 생성 실패: {e}")

    return CATEGORY_PROMPTS.get(category, CATEGORY_PROMPTS["기타"])


def _fetch_image(url: str, timeout: int = 60) -> bytes | None:
    """pollinations.ai에서 이미지 바이트 다운로드 (1회 재시도)"""
    for attempt in range(2):
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code == 200 and len(r.content) > 5000:
                ct = r.headers.get("content-type", "")
                # content-type이 image거나, 바이트 시그니처로 이미지 확인
                if ct.startswith("image") or r.content[:3] in (b'\xff\xd8\xff', b'\x89PN', b'GIF', b'RIFF'):
                    return r.content
                logger.warning(f"  비이미지 응답 (attempt {attempt+1}): ct={ct}, size={len(r.content)}")
            elif r.status_code != 200:
                logger.warning(f"  HTTP {r.status_code} (attempt {attempt+1})")
        except requests.Timeout:
            logger.warning(f"  타임아웃 {timeout}s (attempt {attempt+1})")
        except Exception as e:
            logger.warning(f"  다운로드 오류 (attempt {attempt+1}): {e}")

        if attempt == 0:
            time.sleep(10)
    return None


def _upload_imgbb(img_bytes: bytes) -> str | None:
    """imgBB에 이미지 업로드 → URL 반환"""
    try:
        b64 = base64.b64encode(img_bytes).decode()
        r = requests.post(
            "https://api.imgbb.com/1/upload",
            data={"key": IMGBB_API_KEY, "image": b64},
            timeout=30,
        )
        if r.status_code == 200:
            return r.json()["data"]["url"]
        logger.warning(f"  imgBB 오류: {r.status_code}")
    except Exception as e:
        logger.warning(f"  imgBB 업로드 실패: {e}")
    return None


def generate_and_upload_images(product: dict, post_text: str = "") -> list[str]:
    """
    AI 이미지 생성 → imgBB 업로드 → 영구 URL 목록 반환.
    IMGBB_API_KEY 없거나 전체 실패 시 [] 반환 (호출부가 원본 이미지 사용).
    """
    if not IMGBB_API_KEY:
        logger.info("IMGBB_API_KEY 없음 → AI 이미지 건너뜀")
        return []

    prompts = _make_prompts(product, post_text)
    result  = []

    for i, prompt in enumerate(prompts[:4]):
        encoded  = quote(prompt)
        seed     = (abs(hash(prompt)) + i * 7919) % 99999
        poll_url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?width=1080&height=1080&nologo=true&seed={seed}&model=flux-realism"
        )
        logger.info(f"  이미지 {i+1}/4 생성 중...")

        img_bytes = _fetch_image(poll_url)
        if not img_bytes:
            logger.warning(f"  이미지 {i+1} 다운로드 실패 — 건너뜀")
            continue

        url = _upload_imgbb(img_bytes)
        if url:
            result.append(url)
            logger.info(f"  imgBB 업로드 완료 ({i+1}): {url[:55]}...")
        else:
            logger.warning(f"  이미지 {i+1} imgBB 업로드 실패 — 건너뜀")

    logger.info(f"AI 이미지 생성 결과: {len(result)}장 성공 / {len(prompts[:4])}장 시도")
    return result
