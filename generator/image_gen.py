"""
AI 이미지 생성
- Gemini로 상품별 이미지 프롬프트 생성
- pollinations.ai로 실제 이미지 URL 반환 (무료, API 키 불필요)
- IMGBB_API_KEY 있으면 영구 CDN URL로 업로드 (선택적 품질 향상)
"""
import base64
import logging
import os
import sys
from urllib.parse import quote

import requests

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
from config import GOOGLE_API_KEY

IMGBB_API_KEY = os.getenv("IMGBB_API_KEY", "")

logger = logging.getLogger("image_gen")

CATEGORY_STYLE = {
    "뷰티":       "Korean beauty aesthetic, soft pastel lighting, cosmetic product photography",
    "주방":       "modern bright kitchen, lifestyle cooking scene, clean background",
    "생활":       "cozy home interior, lifestyle product, warm natural lighting",
    "디지털/가전": "tech product, minimalist studio, white background, sharp focus",
    "인테리어":   "cozy Scandinavian interior, warm mood lighting, home styling",
    "기타":       "lifestyle product photography, clean background, warm tones",
}


def _make_prompts(product: dict, post_text: str) -> list[str]:
    name     = product.get("name", "")
    category = product.get("category_hint", product.get("category", "기타"))
    style    = CATEGORY_STYLE.get(category, CATEGORY_STYLE["기타"])

    if GOOGLE_API_KEY:
        try:
            import google.generativeai as genai
            genai.configure(api_key=GOOGLE_API_KEY)
            model = genai.GenerativeModel("gemini-2.0-flash")
            res = model.generate_content(
                f"""다음 한국 쇼핑 상품의 인스타그램 광고용 AI 이미지 프롬프트 3개를 영어로 작성해줘.
상품명: {name}
카테고리: {category}
본문 참고: {post_text[:200]}

규칙:
- 각 프롬프트 한 줄 (콤마로 태그 구분)
- 실제 상품이 사진에 등장하는 상황 묘사
- professional commercial product photography 스타일
- Korean lifestyle aesthetic 포함
- 번호 없이 줄바꿈으로만 구분, 프롬프트 3개만 출력""",
                generation_config=genai.types.GenerationConfig(temperature=0.7),
            )
            lines = [l.strip() for l in res.text.strip().split("\n") if l.strip()][:3]
            if lines:
                return lines
        except Exception as e:
            logger.warning(f"Gemini 프롬프트 생성 실패: {e}")

    # Fallback
    return [
        f"{name}, {style}, professional commercial photography, 4k",
        f"{name} lifestyle in use, {style}, Korean aesthetic, natural light",
        f"{name} product flat lay, {style}, editorial composition",
    ]


def _pollinations_url(prompt: str, idx: int = 0) -> str:
    encoded = quote(prompt)
    seed    = (abs(hash(prompt)) + idx * 7919) % 99999
    return (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=1080&height=1080&nologo=true&seed={seed}&model=flux-realism"
    )


def _fetch_with_retry(url: str, retries: int = 2, timeout: int = 45) -> bytes | None:
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                return r.content
        except Exception as e:
            if attempt == retries:
                logger.warning(f"  다운로드 실패: {e}")
    return None


def generate_product_image_urls(product: dict, post_text: str = "") -> list[str]:
    """pollinations.ai URL 4개 즉시 반환 (Threads 서버가 직접 다운로드)"""
    prompts = _make_prompts(product, post_text)
    # 3개 프롬프트 × 변형 시드로 4개 URL 생성
    urls = []
    for i, p in enumerate(prompts):
        urls.append(_pollinations_url(p, idx=i))
    if len(urls) < 4 and prompts:
        urls.append(_pollinations_url(prompts[0], idx=99))
    logger.info(f"pollinations.ai 이미지 URL {len(urls)}개 생성")
    return urls[:4]


def generate_and_upload_images(product: dict, post_text: str = "") -> list[str]:
    """
    이미지 생성 후 imgBB 업로드 → 영구 CDN URL 반환.
    IMGBB_API_KEY 없으면 pollinations.ai URL 그대로 반환.
    """
    prompts = _make_prompts(product, post_text)

    if not IMGBB_API_KEY:
        return generate_product_image_urls(product, post_text)

    result = []
    indices = list(range(len(prompts))) + [99]  # 4번째는 첫 프롬프트 변형
    for i, (prompt, idx) in enumerate(zip(prompts + [prompts[0]], indices)):
        if len(result) >= 4:
            break
        poll_url = _pollinations_url(prompt, idx=idx)
        img_bytes = _fetch_with_retry(poll_url)
        if not img_bytes:
            continue
        try:
            b64 = base64.b64encode(img_bytes).decode()
            up = requests.post(
                "https://api.imgbb.com/1/upload",
                data={"key": IMGBB_API_KEY, "image": b64},
                timeout=20,
            )
            if up.status_code == 200:
                img_url = up.json()["data"]["url"]
                result.append(img_url)
                logger.info(f"  imgBB 업로드 완료 ({i+1}): {img_url[:55]}...")
        except Exception as e:
            logger.warning(f"  imgBB 업로드 실패: {e}")

    if not result:
        logger.warning("imgBB 전체 실패 → pollinations.ai URL 사용")
        result = generate_product_image_urls(product, post_text)
    return result
