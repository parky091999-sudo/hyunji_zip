"""
콘텐츠 생성기
- 글1: Groq AI로 상품별 맞춤 생성 (스토리텔링 + 해시태그)
- 글2: 코드 기반 유도 — URL 직접 노출 없음 ("프로필 링크에서 [CODE] 검색")
- COUPANG_PARTNERS_ACTIVE=True 시 [광고] + 공정위 고지문 자동 추가
- ★ 수정: 쿠팡 상세페이지에서 이미지 3~4장 수집 → carousel 포스팅용
"""
import random
import os
import sys
import logging

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import COUPANG_PARTNERS_ACTIVE, GROQ_API_KEY

logger = logging.getLogger(__name__)

_AD_DISCLOSURE = "이 게시물은 쿠팡파트너스 활동의 일환으로 수수료를 받을 수 있습니다"


# ── 글1: Groq AI 생성 ────────────────────────────────────────────────────────

_POST1_SYSTEM = """
너는 Threads에서 팔로워가 많은 생활용품 큐레이터야.
"써보니까 좋더라" 하면서 진짜 쓸만한 물건만 콕 집어주는 사람.
계정 컨셉: "보다가 이게 뭐야 싶은 것들"을 발견해서 소개하는 계정.

출력 형식 (반드시 이 순서, 각 블록은 빈 줄로 구분):
[훅 1줄 — 스크롤 멈추게 하는 강력한 첫 문장]
[본문 2~3줄 — 근거·사용법·상황]
[포인트 2줄 — ✔ 로 시작하는 구체적 활용팁]
[해시태그 한 줄, 4~5개]

본문 작성 규칙:
1. 첫 줄(훅)은 무조건 강하게. 다음 중 하나의 느낌으로:
   - 공감 후벼파기: "겨울만 되면 ○○ 때문에 스트레스인 사람 주목"
   - 발견의 놀라움: "이거 왜 이제 알았지 싶은 물건"
   - 후회 자극: "진작 알았으면 돈 굳었을 텐데"
   - 호기심: "이거 본 사람들 다 장바구니行"
2. 추측형 절대 금지. "~같다", "~할 듯", "~보이더라" 쓰지 마.
   대신 단정·경험·근거형으로: "~하더라", "리뷰 보니까 ~래", "써본 사람들이 ~라고 함"
3. 상품의 실제 특징·성분·기능을 구체적으로. 막연한 효능 설명 금지.
4. 사회적 증거를 자연스럽게 녹여: "리뷰 수천 개", "재구매율 높은", "품절됐다 재입고된" 등
   (단, 정확한 수치를 모르면 지어내지 말고 "리뷰 좋은", "후기 많은" 정도로)
5. ✔ 포인트는 실제 사용 상황을 구체적으로 (언제/어디서/어떻게 쓰는지)
6. 반말, 친근하게. 과한 광고티 금지. 가격은 절대 언급하지 마.
7. 이모지는 본문에 1~2개까지만 자연스럽게.

해시태그 규칙:
- 첫 태그는 항상 #생활꿀템
- 나머지는 상품 카테고리에 맞게: #주방템 #살림템 #뷰티꿀템 #자취템 #육아템 #캠핑템 등
- 구체적인 상품 키워드 태그도 1개 포함 (예: #수분크림 #텀블러)

반드시 한국어로만 작성. 영어·중국어·일본어·베트남어 등 다른 언어 절대 사용 금지.
텍스트만 출력. 따옴표, 메타 설명, "다음은~" 같은 안내 문구 넣지 마.
""".strip()

_CODE_LINE = "제품 정보는 프로필 링크에서 [{code}] 검색 👆"


def _generate_post1_ai(product: dict, product_code: str) -> str | None:
    if not GROQ_API_KEY:
        return None
    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)

        name = product.get("name", "")
        category_hint = product.get("category_hint", "")
        brand = product.get("brand", "")
        yt = product.get("youtube_source", {})
        rating = product.get("rating", "")
        review_count = product.get("review_count", "")

        user_msg = f"상품명: {name}"
        if brand:
            user_msg += f"\n브랜드: {brand}"
        if category_hint:
            user_msg += f"\n카테고리: {category_hint}"
        if rating:
            user_msg += f"\n별점: {rating}"
        if review_count:
            user_msg += f"\n리뷰 수: {review_count}"
        if yt.get("title"):
            user_msg += f"\n참고 유튜브 제목: {yt['title'][:60]}"
        user_msg += "\n\n위 상품을 소개하는 Threads 게시글을 써줘. 첫 줄은 스크롤을 멈추게 하는 강력한 훅으로 시작해."

        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": _POST1_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=320,
            temperature=0.9,
        )
        body_and_tags = resp.choices[0].message.content.strip().strip('"\'""''')
        if not body_and_tags:
            return None
        return f"{body_and_tags}\n\n{_CODE_LINE.format(code=product_code)}"
    except Exception as e:
        logger.warning(f"AI 글1 생성 실패: {e}")
        return None


# ── 글1: 폴백 템플릿 ──────────────────────────────────────────────────────────

def _post1_fallback(name: str, product_code: str) -> str:
    short = name[:28] + ("..." if len(name) > 28 else "")
    variations = [
        f"이거 왜 이제 알았지 싶은 물건 발견함\n후기 보니까 한 번 쓰면 못 돌아간다더라\n{short}\n\n✔ 생각날 때마다 바로바로 쓰기 좋고\n✔ 하나 사두면 두고두고 쓰는 템\n\n#생활꿀템 #살림템 #아이디어상품 #꿀템추천",
        f"이거 본 사람들 다 장바구니로 직행한 거\n괜히 후기 많은 게 아니더라\n{short}\n\n✔ 막상 써보면 없을 때가 더 불편함\n✔ 자취·신혼 살림에 딱\n\n#생활꿀템 #자취템 #살림템 #주방꿀템 #필수템",
        f"진작 알았으면 좋았을 텐데 싶은 거\n리뷰 평점 보고 바로 믿고 사는 물건\n{short}\n\n✔ 사용법 간단해서 누구나 OK\n✔ 선물용으로도 반응 좋음\n\n#생활꿀템 #아이디어상품 #꿀템 #추천템 #살림꿀템",
    ]
    body_and_tags = random.choice(variations)
    return f"{body_and_tags}\n\n{_CODE_LINE.format(code=product_code)}"


# ── 쿠팡 상세 이미지 수집 ────────────────────────────────────────────────────

def _collect_detail_images(product: dict) -> list[str]:
    """
    쿠팡 상세페이지에서 이미지 3~4장 수집
    - 실패 시 대표 이미지 1장으로 폴백
    """
    product_url = product.get("product_url", "")
    fallback_image = product.get("image_url", "")

    if not product_url:
        return [fallback_image] if fallback_image else []

    try:
        from scraper.coupang_images import fetch_product_images
        images = fetch_product_images(product_url, max_images=4)
        if images:
            logger.info(f"  상세 이미지 {len(images)}장 수집 성공")
            return images
    except Exception as e:
        logger.warning(f"  상세 이미지 수집 실패, 대표 이미지로 폴백: {e}")

    # 폴백: 대표 이미지 1장
    if fallback_image:
        logger.info("  대표 이미지 1장으로 폴백")
        return [fallback_image]
    return []


# ── 메인 생성 함수 ─────────────────────────────────────────────────────────────

def generate_post(product: dict) -> dict:
    from generator.registry import assign_code

    name = product.get("name", "")
    product_url = product.get("product_url", "")
    image_url = product.get("image_url", "")

    # 상품 코드 할당
    product_code = assign_code(product_url, name, image_url)
    if not product_code:
        logger.info(f"  차단된 상품 스킵: {name[:40]}")
        return {}

    # ★ 쿠팡 상세 이미지 3~4장 수집 (carousel용)
    logger.info(f"  상세 이미지 수집 중: {name[:30]}")
    detail_images = _collect_detail_images(product)
    logger.info(f"  → {len(detail_images)}장 준비됨")

    # 글1 생성
    post_text_1 = _generate_post1_ai(product, product_code)
    if post_text_1:
        style = "ai"
    else:
        post_text_1 = _post1_fallback(name, product_code)
        style = "fallback"

    if COUPANG_PARTNERS_ACTIVE:
        post_text_1 = f"[광고]\n{post_text_1}\n\n{_AD_DISCLOSURE}"

    logger.info(f"생성 완료 [{style}][{product_code}]: {name[:30]}")
    return {
        "post_text_1": post_text_1,
        "post_text_2": "",
        "image_url": image_url,           # 기존 호환용 (단일 이미지)
        "detail_images": detail_images,   # ★ carousel용 3~4장
        "product": product,
        "style": style,
        "product_code": product_code,
    }


def generate_posts_batch(products: list[dict]) -> list[dict]:
    results = []
    for product in products:
        try:
            result = generate_post(product)
            if result:
                results.append(result)
        except Exception as e:
            logger.error(f"콘텐츠 생성 실패: {e}")
    return results
