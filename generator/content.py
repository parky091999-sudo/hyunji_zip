"""
콘텐츠 생성기
- 글1: Groq AI로 상품별 맞춤 생성 (스토리텔링 + 해시태그)
- 글2: 코드 기반 유도 — URL 직접 노출 없음 ("프로필 링크에서 [CODE] 검색")
- COUPANG_PARTNERS_ACTIVE=True 시 [광고] + 공정위 고지문 자동 추가
- ★ 수정: 쿠팡 상세페이지에서 이미지 3~4장 수집 → carousel 포스팅용
"""
import random
import re
import os
import sys
import logging

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import COUPANG_PARTNERS_ACTIVE, GROQ_API_KEY, GOOGLE_API_KEY

logger = logging.getLogger(__name__)

_AD_DISCLOSURE = "이 게시물은 쿠팡파트너스 활동의 일환으로 수수료를 받을 수 있습니다"


# ── 글1: Groq AI 생성 ────────────────────────────────────────────────────────

_POST1_SYSTEM = """
너는 Threads에서 직접 써보고 찍은 꿀템 올리는 취향 좋은 20대야.
친구한테 카카오톡으로 "야 이거 진짜 괜찮더라" 하고 보내는 느낌으로 써줘.

━━━ 말투 규칙 (가장 중요) ━━━
전체 글을 처음부터 끝까지 완전히 같은 말투로 써.
허용 어미: ~하더라 / ~래 / ~더라고 / ~했음 / ~임 / ~거든 / ~는 거 알아?
절대 금지:
  - ~같다 / ~할 것 같아 / ~보이더라 (추측형)
  - ~이다 / ~된다 / ~있다 / ~않다 (건조한 종결어미)
  - ~있어요 / ~합니다 (존댓말)
  - 문장을 "~지?" 로 끝내기 (의문형으로 마무리 금지)
  - "~노?" 로 끝내기 (일베식 말투, 절대 금지)
  - 한 글 안에서 말투를 바꾸는 것 (예: ~하더라 쓰다가 ~이다 로 전환 금지)

━━━ 이야기 흐름 ━━━
반드시 이 순서로 자연스럽게 이어지게 써:
① 훅 (1줄): "이거 나 얘기인데" 싶은 공감 or 놀라움
② 왜 필요한지 (1~2줄): 어떤 상황에서, 어떤 사람에게 딱인지
③ 이 상품이 특별한 이유 (1~2줄): 구체적인 기능·소재·특징. "좋다"는 말 금지, 실제로 무엇이 어떻게 다른지
④ 리뷰 근거 (1줄): 후기 기반으로 신뢰 주기
⑤ ✔ 팁 2줄: 언제 / 어디서 / 어떻게 쓰면 좋은지 구체적 상황
⑥ 빈 줄 후 해시태그

각 문장은 앞 문장과 반드시 연결되게. "그래서", "근데", "덕분에", "게다가" 같은 연결어를 자연스럽게 써.
읽는 사람이 "맞아맞아 → 오 진짜? → 그렇구나 → 나도 필요하다" 흐름으로 읽혀야 함.

━━━ 나쁜 예 / 좋은 예 ━━━
나쁜 예 (말투 섞임, 연결 없음):
"식기세척기 있어도 허리아픈사람 이물건알면 속쓰리지?
방문설치가 포함되어 있어서 설치에 대한 고민을 덜 수 있다.
리뷰 수천개 보니까 만족도 매우 높은 제품이라고 하더라."

좋은 예 (말투 통일, 이야기처럼 연결됨):
"설거지 할 때마다 허리 나가는 느낌 받는 사람 여기 봐봐
이거 그냥 그릇 넣고 버튼 누르면 끝이래
게다가 방문설치 포함이라 사자마자 당일에 바로 쓸 수 있더라고
리뷰 보니까 산 사람들이 진짜 하나같이 왜 이제 샀냐고 하더라"

━━━ 기타 규칙 ━━━
- 이모지 1~2개만, 본문에 자연스럽게
- 해시태그 첫 번째는 항상 #생활꿀템, 총 4~5개
- 가격 언급 금지
- 글 전체 400~600자
- 반드시 한국어만. 외국어(태국어·중국어·일본어 등) 절대 금지
- 텍스트만 출력. 따옴표·메타설명·안내문구 넣지 마
""".strip()

_CODE_LINE = "제품 정보는 프로필 링크에서 [{code}] 검색 👆"

# 외국어 탐지 — 명시적 \u 이스케이프로 인코딩 이슈 완전 차단
# 허용: 한글(U+AC00-U+D7A3, U+1100-U+11FF, U+3130-U+318F), ASCII(0x00-0x7F), 이모지 등
_FOREIGN_RE = re.compile(
    "[一-鿿"     # CJK 통합 한자 (중국어 간체/번체)
    "㐀-䶿"     # CJK 확장 A
    "぀-ゟ"     # 일본어 히라가나
    "゠-ヿ"     # 일본어 가타카나
    "ㇰ-ㇿ"     # 가타카나 음성 확장
    "฀-๿"     # 태국어 (Thai)
    "ᨠ-᪯"     # Tai Tham (타이 탐)
    "ᥐ-᥿"     # Tai Le
    "ꪀ-꫟"     # Tai Viet
    "؀-ۿ"     # 아랍어
    "ݐ-ݿ"     # 아랍어 보조
    "Ѐ-ӿ"     # 키릴 (러시아어)
    "Ͱ-Ͽ"     # 그리스어 (Greek — ης 등)
    "Ā-ɏ"     # 라틴 확장 A/B (베트남어 등)
    "ɐ-ʯ"     # IPA 확장
    "Ḁ-ỿ"     # 라틴 확장 추가 (베트남어 성조)
    "]"
)


def _has_foreign_chars(text: str) -> bool:
    return bool(_FOREIGN_RE.search(text))


def _fix_linebreaks(text: str) -> str:
    """줄바꿈 정리: 해시태그 앞 빈 줄 보장, 연속 빈 줄 제거"""
    lines = text.split("\n")
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if result and result[-1] != "":
                result.append("")
        else:
            # 해시태그 줄 앞에 빈 줄 보장
            if stripped.startswith("#") and result and result[-1] != "":
                result.append("")
            result.append(stripped)
    # 앞뒤 빈 줄 제거
    while result and result[0] == "":
        result.pop(0)
    while result and result[-1] == "":
        result.pop()
    return "\n".join(result)


def _build_user_msg(product: dict) -> str:
    name         = product.get("name", "")
    brand        = product.get("brand", "")
    category     = product.get("category_hint", "")
    rating       = product.get("rating", "")
    review_count = product.get("review_count", "")
    yt_title     = (product.get("youtube_source") or {}).get("title", "")
    msg = f"상품명: {name}"
    if brand:        msg += f"\n브랜드: {brand}"
    if category:     msg += f"\n카테고리: {category}"
    if rating:       msg += f"\n별점: {rating}"
    if review_count: msg += f"\n리뷰 수: {review_count}"
    if yt_title:     msg += f"\n참고 유튜브 제목: {yt_title[:60]}"
    msg += "\n\n위 상품을 소개하는 Threads 게시글을 써줘. 첫 줄은 스크롤을 멈추게 하는 강력한 훅으로 시작해."
    return msg

_KOREAN_ONLY = "\n\n[필수] 한국어로만 출력. 태국어·중국어·일본어·베트남어·아랍어 등 어떤 외국어도 절대 사용 금지. 한글+영문+이모지만 허용."


def _generate_with_gemini(product: dict, product_code: str) -> str | None:
    try:
        import google.generativeai as genai
        genai.configure(api_key=GOOGLE_API_KEY)
        model = genai.GenerativeModel(
            "gemini-2.5-flash",
            system_instruction=_POST1_SYSTEM,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=450,
                temperature=0.9,
            ),
        )
        user_msg = _build_user_msg(product)
        body_and_tags = None
        for attempt in range(3):
            extra = _KOREAN_ONLY if attempt > 0 else ""
            resp = model.generate_content(user_msg + extra)
            candidate = resp.text.strip().strip("\"'""''") if resp.text else ""
            if not candidate:
                continue
            if _has_foreign_chars(candidate):
                logger.warning(f"Gemini 외국어 감지 → 재시도 {attempt + 1}/3")
                continue
            body_and_tags = candidate
            break
        if not body_and_tags:
            logger.warning("Gemini 3회 재시도 후 외국어 포함 → Groq 폴백")
            return None
        body_and_tags = _fix_linebreaks(body_and_tags)
        return f"{body_and_tags}\n\n{_CODE_LINE.format(code=product_code)}"
    except Exception as e:
        logger.warning(f"Gemini 생성 실패: {e}")
        return None


def _generate_with_groq(product: dict, product_code: str) -> str | None:
    try:
        import httpx, urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY, http_client=httpx.Client(verify=False))
        user_msg = _build_user_msg(product)
        body_and_tags = None
        for attempt in range(3):
            temp = 0.9 if attempt == 0 else 0.6
            extra = _KOREAN_ONLY if attempt > 0 else ""
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": _POST1_SYSTEM},
                    {"role": "user", "content": user_msg + extra},
                ],
                max_tokens=420,
                temperature=temp,
            )
            candidate = resp.choices[0].message.content.strip().strip("\"'""''")
            if not candidate:
                continue
            if _has_foreign_chars(candidate):
                logger.warning(f"Groq 외국어 감지 → 재시도 {attempt + 1}/3")
                continue
            body_and_tags = candidate
            break
        if not body_and_tags:
            logger.warning("Groq 3회 재시도 후 외국어 포함 → 폴백 사용")
            return None
        body_and_tags = _fix_linebreaks(body_and_tags)
        return f"{body_and_tags}\n\n{_CODE_LINE.format(code=product_code)}"
    except Exception as e:
        logger.warning(f"Groq 생성 실패: {e}")
        return None


def _generate_post1_ai(product: dict, product_code: str) -> str | None:
    if GOOGLE_API_KEY:
        result = _generate_with_gemini(product, product_code)
        if result:
            logger.info("  [Gemini 2.0 Flash] 본문 생성 완료")
            return result
    if GROQ_API_KEY:
        result = _generate_with_groq(product, product_code)
        if result:
            logger.info("  [Groq 폴백] 본문 생성 완료")
            return result
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

def generate_post(product: dict, assign_code_now: bool = True) -> dict:
    """
    assign_code_now=True (기본): 포스팅 시점에 호출 — 코드 즉시 부여
    assign_code_now=False:       preselect용 — 코드 없이 텍스트만 생성, 포스팅 시점에 코드 부여
    """
    from generator.registry import assign_code

    name = product.get("name", "")
    product_url = product.get("product_url", "")
    image_url = product.get("image_url", "")

    if assign_code_now:
        product_code = assign_code(product_url, name, image_url)
        if not product_code:
            logger.info(f"  차단된 상품 스킵: {name[:40]}")
            return {}
    else:
        # 코드 없이 생성 — 나중에 포스팅 시점에 assign_code() 호출
        product_code = ""

    # ★ 쿠팡 상세 이미지 3~4장 수집 (carousel용)
    logger.info(f"  상세 이미지 수집 중: {name[:30]}")
    detail_images = _collect_detail_images(product)
    logger.info(f"  → {len(detail_images)}장 준비됨")

    # 글1 생성 (코드 있으면 코드 라인 포함, 없으면 나중에 추가)
    if product_code:
        post_text_1 = _generate_post1_ai(product, product_code)
        if post_text_1:
            style = "ai"
        else:
            post_text_1 = _post1_fallback(name, product_code)
            style = "fallback"
    else:
        # 코드 없이 본문만 생성 (_CODE_LINE 제외)
        post_text_1 = _generate_post1_ai(product, "CODE")
        if post_text_1:
            # CODE 플레이스홀더 제거 (포스팅 시점에 실제 코드로 교체)
            post_text_1 = re.sub(r'\n\n제품 정보는 프로필 링크에서 \[CODE\] 검색 👆', '', post_text_1)
            style = "ai"
        else:
            body = _post1_fallback(name, "CODE")
            post_text_1 = re.sub(r'\n\n제품 정보는 프로필 링크에서 \[CODE\] 검색 👆', '', body)
            style = "fallback"

    if COUPANG_PARTNERS_ACTIVE:
        post_text_1 = f"[광고]\n{post_text_1}\n\n{_AD_DISCLOSURE}"

    logger.info(f"생성 완료 [{style}]{('['+product_code+']') if product_code else '[코드미정]'}: {name[:30]}")
    return {
        "post_text_1": post_text_1,
        "post_text_2": "",
        "image_url": image_url,
        "detail_images": detail_images,
        "product": product,
        "style": style,
        "product_code": product_code,
    }


def polish_post(text: str, product: dict) -> str | None:
    """사용자가 편집한 포스팅 텍스트를 AI로 다듬기 (auto_post.py에서 호출)"""
    if not GROQ_API_KEY or not text:
        return None
    name = product.get("name", "")
    prompt = (
        f"아래는 쿠팡 상품 추천 SNS 포스팅 초안입니다.\n\n"
        f"상품명: {name}\n\n"
        f"초안:\n{text}\n\n"
        "위 초안을 바탕으로 자연스러운 한국어 SNS 포스팅으로 다듬어 주세요.\n"
        "규칙:\n"
        "- 초안의 구조·내용·방향을 최대한 유지\n"
        "- 외국어(영어 제외) 단어가 있으면 한국어로 교체\n"
        "- 어색한 표현만 자연스럽게 수정\n"
        "- 이모지·해시태그·코드 라인 그대로 유지\n"
        "- 다듬은 텍스트만 출력, 설명 금지"
    )
    try:
        import httpx, urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY, http_client=httpx.Client(verify=False))
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=450,
            temperature=0.4,
        )
        result = resp.choices[0].message.content.strip()
        if _has_foreign_chars(result):
            logger.warning("polish_post: 외국어 여전히 포함 → 원본 사용")
            return None
        return _fix_linebreaks(result)
    except Exception as e:
        logger.warning(f"polish_post 실패: {e}")
        return None


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


# ── 일상/일반 포스트 생성 ──────────────────────────────────────────────────────

_CASUAL_POST_TYPES = [
    "account_intro",   # 계정 소개 / 내가 어떤 사람인지
    "daily_life",      # 일상 공감글
    "tip",             # 상품 없는 생활 꿀팁
    "question",        # 팔로워에게 질문하는 참여 유도 글
]

_CASUAL_SYSTEM = """
너는 Threads SNS에서 생활용품 꿀템을 추천하는 계정(@kkul_pick711)을 운영하는 20~30대야.
오늘은 상품 소개가 아니라, 팔로워들과 자연스럽게 소통하는 일상 글을 써야 해.

글 유형별 지침:
- account_intro: "나는 이런 사람이야" / "이 계정은 이런 곳이야" 형식으로, 어떤 기준으로 꿀템을 고르는지, 왜 이 계정을 시작했는지 등을 자연스럽고 솔직하게.
- daily_life: 오늘 겪은 작은 공감 가는 일상 순간, 생활 속 불편함이나 소소한 발견 등. 사람들이 "나도 그래!" 하고 공감할 수 있게.
- tip: 상품 없이도 살림·생활에 도움 되는 꿀팁 1~2개. 실용적이고 즉시 써먹을 수 있는 것.
- question: 팔로워들에게 의견을 묻는 가벼운 질문. "여러분은 어떻게 해요?", "이거 써본 사람?" 같은 참여 유도.

출력 형식 (각 블록 사이에 빈 줄 1개):

[훅 — 첫 문장, 멈추게 하는 강렬한 시작]

[본문 3~5줄 — 자연스럽고 친근하게, 재치 있게]

규칙:
- 반말, 친근하게. 위트 있게. 진짜 사람이 쓴 것 같아야 해.
- 이모지 1~2개, 자연스럽게.
- 해시태그 절대 쓰지 마.
- 상품 홍보·링크 절대 금지.
- 한국어로만 작성. 외국어 절대 금지.
- 텍스트만 출력. 메타 설명 금지.
""".strip()

_CASUAL_FALLBACKS = [
    "오늘도 쓸데없이 쇼핑몰 들어갔다가 30분 날렸어\n근데 이상하게 그 시간이 행복함 ✨\n가끔은 그냥 구경만 해도 힐링되는 거 나만 그런 거 아니지?",
    "살림하면서 제일 뿌듯할 때가\n없던 공간이 딱 정리됐을 때인데\n근데 그게 또 2~3일 지나면 원상복구 됨 ㅋㅋ\n이 계절의 저주 언제 끝나냐",
    "이 계정 시작한 이유가 사실\n나 혼자만 쓰기 아까운 거 발견할 때마다 어딘가에 기록하고 싶어서야\n꿀템 찾는 거 취미인 사람들 여기 다 모여라 🙌",
]


def generate_general_post(post_type: str | None = None) -> str | None:
    """일상/일반 포스트 생성 (상품 없음)"""
    chosen_type = post_type or random.choice(_CASUAL_POST_TYPES)
    user_msg = (
        f"글 유형: {chosen_type}\n\n"
        "위 유형에 맞는 Threads 일상 게시글을 써줘. "
        "진짜 사람이 쓴 것처럼 자연스럽고 재치 있게."
    )

    if GOOGLE_API_KEY:
        try:
            import google.generativeai as genai
            genai.configure(api_key=GOOGLE_API_KEY)
            model = genai.GenerativeModel(
                "gemini-2.5-flash",
                system_instruction=_CASUAL_SYSTEM,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=300,
                    temperature=0.95,
                ),
            )
            resp = model.generate_content(user_msg)
            text = resp.text.strip().strip("\"'""''") if resp.text else ""
            if text and not _has_foreign_chars(text):
                logger.info("  [Gemini 2.0 Flash] 일상글 생성 완료")
                return _fix_linebreaks(text)
            logger.warning("Gemini 일상글 외국어 포함 또는 빈 응답 → Groq 폴백")
        except Exception as e:
            logger.warning(f"Gemini 일상글 생성 실패: {e}")

    if not GROQ_API_KEY:
        return random.choice(_CASUAL_FALLBACKS)

    try:
        import httpx, urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY, http_client=httpx.Client(verify=False))
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": _CASUAL_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=300,
            temperature=0.95,
        )
        text = resp.choices[0].message.content.strip().strip("\"'""''")
        if not text or _has_foreign_chars(text):
            logger.warning("일상글 AI 생성 실패 또는 외국어 포함 → 폴백")
            return random.choice(_CASUAL_FALLBACKS)
        logger.info("  [Groq 폴백] 일상글 생성 완료")
        return _fix_linebreaks(text)
    except Exception as e:
        logger.warning(f"일상글 생성 실패: {e}")
        return random.choice(_CASUAL_FALLBACKS)
