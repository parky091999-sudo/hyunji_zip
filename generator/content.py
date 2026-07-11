"""
콘텐츠 생성기
- 글1: Groq AI로 상품별 맞춤 생성 (스토리텔링 + 해시태그)
- 글2: 코드 기반 유도 — 본문에 "프로필 링크에서 [CODE] 검색" 안내
- COUPANG_PARTNERS_ACTIVE는 페이지 푸터 disclosure 분기에만 사용 (본문에는 안 붙임 — 첫 댓글에서 처리)
- ★ 수정: 쿠팡 상세페이지에서 이미지 3~4장 수집 → carousel 포스팅용
"""
import random
import re
import os
import sys
import logging

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import COUPANG_PARTNERS_ACTIVE, GROQ_API_KEY, GOOGLE_API_KEY, DATA_DIR

logger = logging.getLogger(__name__)

_AD_DISCLOSURE = "이 게시물은 쿠팡파트너스 활동의 일환으로 수수료를 받습니다"


# ── 글1: Groq AI 생성 ────────────────────────────────────────────────────────

_POST1_SYSTEM = """
너는 Threads(@hyunji_ssi)에서 1인 가구 일상을 적는 20대 여자 '현지'야.
오늘은 평소에 자주 쓰는 물건 하나를 솔직하게 소개하는 글을 쓰는데, 광고 멘트가 아니라
"나 이거 써봤는데 진짜 좋더라, 너도 알면 좋겠어" 하고 친구한테 말하듯이 따뜻하게 공유하는 톤이야.

━━━ 말투 규칙 (가장 중요) ━━━
전체 글을 처음부터 끝까지 완전히 같은 말투로 써.
기본 톤: 편안한 반말 — 친구한테 카톡 보내는 것처럼 자연스럽게.
허용 어미: ~하더라 / ~더라고 / ~거든 / ~했음 / ~임 / ~래 / ~는 거 알아? / ~인 거 알았어
절대 금지:
  - "~냐?" "~더냐?" "~이냐?" 로 끝내기 (건방지고 공격적으로 들림)
  - "~지?" "~잖아?" 로 문장 끝내기 (몰아붙이는 느낌)
  - "~이다" "~된다" "~있다" "~않다" (건조한 뉴스체 종결어미)
  - "~있어요" "~합니다" "~입니다" (존댓말, 반말 글과 섞이면 어색함)
  - "~같다" "~할 것 같아" "~보이더라" (추측·불확실 표현)
  - "~노?" (일베식, 절대 금지)
  - 한 글 안에서 반말↔존댓말 전환 금지

━━━ 이야기 흐름 ━━━
반드시 이 순서로 자연스럽게 이어지게 써:
① 훅 (1줄): 읽는 사람이 자기 얘기처럼 느낄 공감 or 놀라움 — 단, 매번 완전히 다른 표현으로. 이 지침이나 아래 예시의 문장을 그대로 복사하는 것 절대 금지
② 왜 필요한지 (1~2줄): 어떤 상황에서, 어떤 사람에게 딱인지
③ 이 상품이 특별한 이유 (1~2줄): 구체적인 기능·소재·특징. "좋다"는 말 금지, 실제로 무엇이 어떻게 다른지
④ 리뷰 근거 (1줄): 후기 기반으로 신뢰 주기
⑤ ✔ 팁 2줄: 언제 / 어디서 / 어떻게 쓰면 좋은지 구체적 상황
⑥ 빈 줄 후 해시태그

각 문장은 앞 문장과 반드시 연결되게. "그래서", "근데", "덕분에", "게다가" 같은 연결어를 자연스럽게 써.
읽는 사람이 "맞아맞아 → 오 진짜? → 그렇구나 → 나도 필요하다" 흐름으로 읽혀야 함.
★[팔로우 및 프로필 방문 유도]: 글 끝부분(팁 2줄 다음)에 가끔 "내가 쓴 자취 살림 성공템 vs 실패템 리스트 프로필 링크에 표로 깔끔하게 다 정리해뒀어! 팔로우하고 꼭 확인해보고 돈 아껴ㅠㅠ" 처럼 프로필 방문(Bio link)과 팔로우를 유도하는 따뜻한 한 줄을 자연스럽게 덧붙여줘.

━━━ 나쁜 예 / 좋은 예 ━━━
나쁜 예 (건방진/딱딱한 말투):
"식기세척기 있어도 허리아픈사람 이물건알면 속쓰리냐?
방문설치가 포함되어 있다. 리뷰 수천개 만족도 매우 높다.
설치 고민 덜 수 있어요. 추천합니다."

좋은 예 (따뜻하고 자연스러운 반말):
"설거지할 때마다 허리 나가는 느낌 받는 사람 이거 봐봐
그냥 그릇 넣고 버튼 누르면 끝이래
게다가 방문설치 포함이라 사자마자 당일 바로 쓸 수 있더라고
리뷰 보니까 산 사람들이 하나같이 왜 이제 샀냐고 하더라"

━━━ 비살림 카테고리 (디지털/가전/뷰티/의류/테크 등) 처리 ━━━
상품이 자취 살림템이 아니어도 1인 가구 일상 맥락으로 풀어쓸 것. 절대 generic하게
"두고두고 쓰는 템" 같은 만능 문구만 쓰지 마. 그 상품의 구체적 기능·스펙·호환성을
일상 상황에 묶어서 설명해.
나쁜 예 (아이패드 매직키보드): "이거 왜 이제 알았지 / 두고두고 쓰는 템 / #테크템"
   → 매직키보드의 어떤 점도 안 드러남. 휴지통이든 화장품이든 다 통할 문구.
좋은 예 (아이패드 매직키보드 iPad Air M4용):
   "카페에서 노트북 꺼내기 부담스러울 때 아이패드에 키보드만 붙이면 끝
   트랙패드까지 있어서 마우스 없이도 작업 가능하더라
   백라이트 들어와서 어두운 데서도 오타 안 남"
상품명에 모델명·호환 기기·소재·용량이 있으면 반드시 본문에 활용. 그 상품이
다른 상품으로 바꿔도 그대로 통하는 문구는 절대 금지.

━━━ 기타 규칙 ━━━
- 이모지 1~2개만, 본문에 자연스럽게
- 해시태그 총 4~5개, 상품 카테고리에 어울리게 (사용자 메시지의 추천 해시태그 풀에서 조합). 매번 #생활꿀템으로 시작하지 말고 카테고리마다 다르게
- 가격 언급 금지
- 제품명(상품명) 직접 언급 금지 — 기능·소재·효과·상황으로만 표현해
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
    "À-ɏ"     # Latin-1 Supplement + 라틴 확장 A/B
              # (à é ñ ç ü ö 등 발음 부호 — 2026-06-16 'ngày' 누락 사고 보강)
    "ɐ-ʯ"     # IPA 확장
    "Ḁ-ỿ"     # 라틴 확장 추가 (베트남어 성조)
    "]"
)


def _has_foreign_chars(text: str) -> bool:
    return bool(_FOREIGN_RE.search(text))


has_foreign_chars = _has_foreign_chars  # 외부 모듈용 공개 별칭


# ── 영어 혼입 탐지 ──────────────────────────────────────────────────────────
# _FOREIGN_RE는 기본 영어(A-Z)를 막지 않아 "끝인거imore라고", "더efficient하게" 같은
# LLM 글리치나 영어 단어가 본문에 그대로 게시됐다. 일상적으로 굳어진 약어만 허용하고
# 나머지 영어 단어(2자+)는 부적절 영어로 보고 재생성 트리거.
_ENGLISH_WHITELIST = {
    "LED", "UV", "USB", "TV", "PC", "AS", "IH", "DIY", "AI", "OK", "QR", "LCD",
    "OLED", "HDMI", "GPS", "BLE", "IOT", "NFC", "RGB", "SSD", "HDD", "CPU",
    "ML", "KG", "CM", "MM", "MG", "KW", "HZ", "DB", "DC", "AC",
    "ABS", "PE", "PP", "PVC", "PET", "BPA", "SPF", "PA", "CC", "BB",
}
_ENG_WORD_RE = re.compile(r"[A-Za-z]{2,}")


def _has_bad_english(text: str) -> bool:
    """본문에 부적절한 영어(약어 화이트리스트 외 영어 단어, 한글에 끼어든 영어)가 있으면 True.
    해시태그·URL·제품코드 라인은 제외."""
    t = re.sub(r"#\S+|https?://\S+|\[\d+\]", " ", text)
    for w in _ENG_WORD_RE.findall(t):
        if w.upper() not in _ENGLISH_WHITELIST:
            return True
    return False


has_bad_english = _has_bad_english  # 외부 모듈용 공개 별칭


# ── 본문 잘림 감지 ──────────────────────────────────────────────────────────
# 토큰 한도로 마지막 문장이 절단된 상태에서 그대로 게시되는 것을 막는 게이트.
# verify_posts._is_truncated와 같은 휴리스틱(푸터/해시태그/체크마크 제외 후
# 마지막 줄이 종결 어미로 끝나는지)을 게시 *전* 단계에서 적용한다.
_FOOTER_RE = re.compile(r'\n\n제품 정보는 프로필 링크에서 \[(?:\d{3}|CODE)\] 검색 👆\s*$')
_SENTENCE_END_RE = re.compile(r'[다요임어야겠네봄않함봐!?~\).♥]$')


def looks_truncated(text: str) -> bool:
    body = _FOOTER_RE.sub("", text or "").strip()
    if not body:
        return False
    # 길이 게이트: 푸터 제외 본문이 비정상적으로 짧으면(목표 400~600자) 잘림 의심.
    # 어미 종결 통과해도 길이 부족 사례 차단 (2026-06-16 오뚜기 식초 126자 '거임' 잘림 보강).
    if len(body) < 200:
        return True
    last_para = body.split('\n\n')[-1].strip()
    last_line = last_para.split('\n')[-1].strip()
    if last_line.startswith(('#', '✔', '•', '👉', '👆')):
        return False
    if re.search(r'(spec|itemId|vendorItemId|pageKey|ctag|lptag)=\d+\s*$', last_line):
        return False
    return not bool(_SENTENCE_END_RE.search(last_line))


def _recent_first_lines(limit: int = 8) -> list[str]:
    """최근 상품 게시글들의 첫 문장 — 훅 반복 방지용 금지 목록"""
    try:
        import json
        path = os.path.join(DATA_DIR, "feed_posts.json")
        if not os.path.exists(path):
            return []
        feed = json.load(open(path, encoding="utf-8"))
        lines = []
        for p in feed:
            if p.get("post_type") == "casual":
                continue
            txt = (p.get("post_text") or "").strip()
            if txt:
                first = txt.splitlines()[0].strip()
                if first and first not in lines:
                    lines.append(first)
            if len(lines) >= limit:
                break
        return lines
    except Exception:
        return []


def _norm_line(s: str) -> str:
    return re.sub(r"[\s.,!?~…·\-]+", "", s)[:12]


def _is_dup_hook(candidate: str, banned: list[str] | None = None) -> bool:
    """후보 글의 첫 문장이 최근 게시글 첫 문장과 같은 패턴이면 True"""
    if not candidate:
        return False
    first = _norm_line(candidate.strip().splitlines()[0])
    if not first:
        return False
    for b in (banned if banned is not None else _recent_first_lines()):
        bn = _norm_line(b)
        # 완전 일치 또는 도입부 7자 일치 ("이거나얘기인데..." 류 동일 훅 패턴 감지)
        if first == bn or (len(first) >= 7 and len(bn) >= 7 and first[:7] == bn[:7]):
            return True
    return False


_DIARY_RE = re.compile(r"\[현지의 자취일기\s*#\s*\d+\]")


def _seq_diary_number(text: str) -> str:
    """[현지의 자취일기 #N] 번호를 순차 카운터로 교정 (2026-07-12).
    기존엔 프롬프트 예시(#12)를 보고 모델이 번호를 지어내 뒤죽박죽(#24→#47→#17…).
    이미 발행된 최대 번호가 #47이라 카운터는 48부터 시작."""
    import json as _json
    if not _DIARY_RE.search(text):
        return text
    path = os.path.join(DATA_DIR, "diary_counter.json")
    try:
        n = int(_json.load(open(path, encoding="utf-8")).get("next", 48))
    except Exception:
        n = 48
    text = _DIARY_RE.sub("@@DIARY@@", text, count=1)
    text = _DIARY_RE.sub("", text)  # 두 번 이상 쓴 경우 나머지 제거
    text = text.replace("@@DIARY@@", f"[현지의 자취일기 #{n}]")
    try:
        _json.dump({"next": n + 1}, open(path, "w", encoding="utf-8"))
    except Exception:
        pass
    return text


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


_HASHTAG_POOLS = {
    "먹는거":      ["#먹꿀템", "#간식추천", "#맛스타그램", "#푸드템", "#먹스타그램", "#오늘뭐먹지"],
    "뷰티":        ["#뷰티템", "#뷰티꿀템", "#화장품추천", "#피부관리", "#셀프케어"],
    "주방":        ["#주방꿀템", "#주방템", "#자취요리", "#살림템", "#요리템"],
    "생활":        ["#생활꿀템", "#살림꿀템", "#자취템", "#필수템", "#살림템"],
    "디지털/가전": ["#테크템", "#가전추천", "#전자기기", "#IT템", "#테크"],
    "인테리어":    ["#인테리어소품", "#집꾸미기", "#홈데코", "#감성인테리어", "#홈스타일링"],
    "기타":        ["#꿀템", "#아이디어상품", "#추천템", "#꿀템추천", "#잇템"],
}


def _infer_category_kr(name: str) -> str:
    n = (name or "").lower()
    if re.search(r"메론|멜론|과일|고기|한우|삼겹|식품|간식|과자|젤리|견과|쌀|김치|반찬|즉석|밀키트|음료|주스|원두|해산물|생선|간재미|오징어|새우|소스|양념|육포|빵|떡", n): return "먹는거"
    if re.search(r"크림|샴푸|마스크팩|세럼|클렌징|선크림|화장|뷰티|미스트|로션|에센스|두피|스케일러|헤어|앰플|토너|패드", n): return "뷰티"
    if re.search(r"냄비|프라이팬|후라이팬|그라인더|믹서|에어프라이어|주방|식기|텀블러|보관용기|도마|커피머신|컵|믹싱볼|탈수기|밀폐용기|조리도구", n): return "주방"
    if re.search(r"청소|세제|수납|정리|건조기|건조대|빨래|욕실|선반|화장지|물티슈|방향제|탈취|살림|스팀|곰팡이|세탁조|배수구", n): return "생활"
    if re.search(r"충전|케이블|이어폰|스피커|보조배터리|마우스|키보드|모니터|공기청정|선풍기|가습|히터|드라이기|led|전동|무선|손풍기|제습기", n): return "디지털/가전"
    if re.search(r"조명|무드등|쿠션|커튼|러그|액자|인테리어|디퓨저|캔들|화분", n): return "인테리어"
    return "기타"


def _hashtag_pool(product: dict) -> list[str]:
    cat = (product.get("category_hint") or product.get("category") or "").strip()
    if cat not in _HASHTAG_POOLS:
        cat = _infer_category_kr(product.get("name", ""))
    return _HASHTAG_POOLS.get(cat, _HASHTAG_POOLS["기타"])


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
    msg += "\n추천 해시태그 풀(이 중 4~5개 자유 조합, 어울리는 태그 1개 추가 가능): " + " ".join(_hashtag_pool(product))
    msg += "\n\n위 상품을 소개하는 Threads 게시글을 써줘. 첫 줄은 스크롤을 멈추게 하는 강력한 훅으로 시작해."
    banned = _recent_first_lines()
    if banned:
        msg += "\n\n[중요] 아래는 최근 게시글들의 첫 문장이야. 이것들과 같거나 비슷한 첫 문장으로 시작하지 마:\n"
        msg += "\n".join(f"- {b}" for b in banned)
    return msg

_VARIETY_ONLY = "\n\n[필수] 첫 문장을 금지 목록과 완전히 다른 새로운 패턴으로 시작해."

_KOREAN_ONLY = (
    "\n\n[필수] 한국어로만 출력. 태국어·중국어·일본어·베트남어·아랍어 등 어떤 외국어도 절대 사용 금지. "
    "영어 단어도 쓰지 마라 — 한글에 영어를 붙이거나(예: '끝인거imore라고', '더efficient하게') 영어 단어를 섞지 말고 "
    "전부 한국어로 풀어써라. 브랜드·제품명도 한글로 표기. "
    "(단 LED·UV·USB·TV 처럼 일상적으로 굳어진 약어만 예외) 한글과 이모지 위주로만 작성."
)


def _generate_with_gemini(product: dict, product_code: str) -> str | None:
    try:
        from google import genai
        client = genai.Client(api_key=GOOGLE_API_KEY)
        user_msg = _build_user_msg(product)
        body_and_tags = None
        for attempt in range(3):
            extra = (_KOREAN_ONLY + _VARIETY_ONLY) if attempt > 0 else ""
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=user_msg + extra,
                config=genai.types.GenerateContentConfig(
                    system_instruction=_POST1_SYSTEM,
                    max_output_tokens=2000,
                    temperature=0.9,
                ),
            )
            candidate = (resp.text or "").strip().strip("\"'""''")
            if not candidate:
                continue
            if _has_foreign_chars(candidate):
                logger.warning(f"Gemini 외국어 감지 → 재시도 {attempt + 1}/3")
                continue
            if _has_bad_english(candidate):
                logger.warning(f"Gemini 영어 혼입 감지 → 재시도 {attempt + 1}/3")
                continue
            if _is_dup_hook(candidate):
                logger.warning(f"Gemini 첫 문장 반복 감지 → 재시도 {attempt + 1}/3")
                continue
            if looks_truncated(candidate):
                logger.warning(f"Gemini 본문 잘림 감지 → 재시도 {attempt + 1}/3")
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
            extra = (_KOREAN_ONLY + _VARIETY_ONLY) if attempt > 0 else ""
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": _POST1_SYSTEM},
                    {"role": "user", "content": user_msg + extra},
                ],
                max_tokens=1600,
                temperature=temp,
            )
            candidate = resp.choices[0].message.content.strip().strip("\"'""''")
            if not candidate:
                continue
            if _has_foreign_chars(candidate):
                logger.warning(f"Groq 외국어 감지 → 재시도 {attempt + 1}/3")
                continue
            if _has_bad_english(candidate):
                logger.warning(f"Groq 영어 혼입 감지 → 재시도 {attempt + 1}/3")
                continue
            if _is_dup_hook(candidate):
                logger.warning(f"Groq 첫 문장 반복 감지 → 재시도 {attempt + 1}/3")
                continue
            if looks_truncated(candidate):
                logger.warning(f"Groq 본문 잘림 감지 → 재시도 {attempt + 1}/3")
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
    variations = [
        "이거 왜 이제 알았지 싶은 물건 발견함\n후기 보니까 한 번 쓰면 못 돌아간다더라\n\n✔ 생각날 때마다 바로바로 쓰기 좋고\n✔ 하나 사두면 두고두고 쓰는 템\n\n#생활꿀템 #살림템 #아이디어상품 #꿀템추천",
        "이거 본 사람들 다 장바구니로 직행한 거\n괜히 후기 많은 게 아니더라\n\n✔ 막상 써보면 없을 때가 더 불편함\n✔ 자취·신혼 살림에 딱\n\n#생활꿀템 #자취템 #살림템 #주방꿀템 #필수템",
        "진작 알았으면 좋았을 텐데 싶은 거\n리뷰 평점 보고 바로 믿고 사는 물건\n\n✔ 사용법 간단해서 누구나 OK\n✔ 선물용으로도 반응 좋음\n\n#생활꿀템 #아이디어상품 #꿀템 #추천템 #살림꿀템",
    ]
    body_and_tags = random.choice(variations)
    # 카테고리 기반 해시태그로 교체 (#생활꿀템 고정 탈피)
    pool = _hashtag_pool({"name": name})
    tags = " ".join(random.sample(pool, k=min(4, len(pool))))
    body_and_tags = re.sub(r"\n#[^\n]+$", "\n" + tags, body_and_tags)
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

    # 글1 생성 — AI 생성 성공 시에만 게시. fallback 본문은 generic해서
    # 비살림 상품(매직키보드 등)에 부적합 → 사용자 불만 발생 (2026-06-16 [027] 사고).
    # AI 실패 시 빈 dict 반환 → auto/manual_post는 다음 후보로 넘어가거나 skip.
    if product_code:
        post_text_1 = _generate_post1_ai(product, product_code)
        if not post_text_1:
            logger.warning(f"AI 본문 생성 실패 — 게시 skip [{product_code}]: {name[:40]}")
            return {}
        style = "ai"
    else:
        # 코드 없이 본문만 생성 (_CODE_LINE 제외)
        post_text_1 = _generate_post1_ai(product, "CODE")
        if not post_text_1:
            logger.warning(f"AI 본문 생성 실패 — preselect skip: {name[:40]}")
            return {}
        post_text_1 = re.sub(r'\n\n제품 정보는 프로필 링크에서 \[CODE\] 검색 👆', '', post_text_1)
        style = "ai"

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


def ensure_not_truncated(text: str, product: dict, product_code: str = "") -> str:
    """포스팅 직전 본문 게이트 — 비어있음/잘림/외국어 모두 잡아 AI 재생성.
    수동 큐 / pending_post 에 저장된 본문이 토큰 한도로 잘렸거나 외국어가 섞였을 때
    완성된 한국어 문장을 보장한다. 실패 시 빈 문자열 반환 → 호출부에서 게시 skip."""
    is_empty = not (text and text.strip())
    foreign = (not is_empty) and _has_foreign_chars(text)
    truncated = (not is_empty) and looks_truncated(text)
    if not (is_empty or foreign or truncated):
        return text
    reason = "비어있음" if is_empty else ("외국어" if foreign else "잘림")
    logger.warning(f"포스팅 직전 본문 {reason} 감지 → 재생성 시도")
    m = re.search(r"\[(\d{3})\] 검색", text or "")
    code = product_code or (m.group(1) if m else "")
    regen = _generate_post1_ai(product, code or "CODE")
    if regen and not looks_truncated(regen) and not _has_foreign_chars(regen):
        if not code:
            regen = re.sub(r"\n\n제품 정보는 프로필 링크에서 \[CODE\] 검색 👆", "", regen)
        return regen
    # fallback은 generic해서 게시 금지 — 빈 본문 반환, 호출부에서 skip 판단
    logger.warning("본문 재생성 실패 → 빈 본문 반환 (호출부에서 게시 skip)")
    return ""


def ensure_korean(text: str, product: dict, product_code: str = "") -> str:
    """포스팅 직전 최종 언어 게이트.
    외국어 감지 시: 정제(polish) → 재생성 → 안전 템플릿 순으로 한국어 텍스트를 보장.
    (수동 큐처럼 생성 시점 필터를 거치지 않은 텍스트의 마지막 방어선)"""
    if not text or (not _has_foreign_chars(text) and not _has_bad_english(text)):
        return text
    logger.warning("포스팅 직전 외국어/영어 혼입 감지 → 정제 시도")
    fixed = polish_post(text, product)
    if fixed and not _has_foreign_chars(fixed) and not _has_bad_english(fixed):
        return fixed

    m = re.search(r"\[(\d{3})\] 검색", text)
    code = product_code or (m.group(1) if m else "")
    logger.warning("정제 실패 → 본문 재생성")
    regen = _generate_post1_ai(product, code or "CODE")
    if regen and not _has_foreign_chars(regen) and not _has_bad_english(regen):
        if not code:
            regen = re.sub(r"\n\n제품 정보는 프로필 링크에서 \[CODE\] 검색 👆", "", regen)
        return regen

    logger.warning("재생성 실패 → 안전 템플릿 사용")
    fb = _post1_fallback(product.get("name", ""), code or "CODE")
    if not code:
        fb = re.sub(r"\n\n제품 정보는 프로필 링크에서 \[CODE\] 검색 👆", "", fb)
    return fb


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
        "- 외국어 및 영어 단어가 있으면 한국어로 교체 (LED·UV·USB·TV 같이 굳어진 약어만 예외)\n"
        "- 한글에 붙은 영어(예: '끝인거imore라고', '더efficient하게')는 자연스러운 한국어로 바로잡기\n"
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
        if _has_foreign_chars(result) or _has_bad_english(result):
            logger.warning("polish_post: 외국어/영어 여전히 포함 → 원본 사용")
            return None
        return _fix_linebreaks(result)
    except Exception as e:
        logger.warning(f"polish_post 실패: {e}")
        return None


_GENERIC_TOKENS = {
    "욕실", "주방", "거실", "방", "침실", "사무실", "차량",  # 공간 단어만
    "용품", "제품", "상품", "기기", "도구", "세트",          # 일반 카테고리
}


def _short_name_ok(result: str, name: str) -> bool:
    """short_name 검증: 너무 짧거나 일반 단어만이면 reject."""
    if not result or len(result) < 2 or len(result) > 40:
        return False
    tokens = result.split()
    # 한 단어인데 공간/카테고리 단어면 reject (예: "욕실", "주방")
    if len(tokens) == 1 and tokens[0] in _GENERIC_TOKENS:
        return False
    # 한 토큰만 있고 길이 4자 미만이면 잘림 의심 reject (예: "6인", "1L")
    if len(tokens) == 1 and len(tokens[0]) < 4:
        return False
    # 원본 상품명에 한 글자도 안 겹치면 reject (AI 환각)
    if not any(t in name for t in tokens):
        return False
    # 끝 단어가 조사/접속사/어색한 절단 문자면 reject
    if result[-1] in ("의", "와", "과", "에", "로", "+", "-", "_", "/"):
        return False
    return True


def _fallback_short_name(name: str) -> str:
    """AI 실패 시 규칙 기반 폴백: 처음 2~4 의미 단어."""
    # 옵션/출고/배송 태그 및 괄호 제거
    cleaned = re.sub(r"[\(\[].*?[\)\]]", " ", name or "")
    cleaned = re.sub(r"\d+_\([^\)]+\)", " ", cleaned)
    cleaned = re.sub(r"[\(\)\[\]\{\}/\\,~·+]", " ", cleaned)
    tokens = [t for t in cleaned.split() if t and not re.match(r"^[A-Z0-9\-]+\d", t)]
    # 모델번호/숫자만/단순개수 토큰 제외
    tokens = [t for t in tokens if not re.fullmatch(r"(\d+[가-힣]?|\d+개|\d+ml|\d+g|\d+L)", t, re.I)]
    result = " ".join(tokens[:4]).strip()
    while len(result) > 30 and len(result.split()) > 1:
        result = " ".join(result.split()[:-1]).strip()
    return result


def generate_short_name(product: dict) -> str:
    """쿠팡 상품 전체명 → 2~4단어 간결한 표시 이름 (페이지 카드 제목용)"""
    name = product.get("name", "")
    if not name:
        return ""
    prompt = (
        "다음 쿠팡 상품명을 2~4단어의 간결한 한국어 표시 이름으로 줄여줘.\n"
        "브랜드명·모델번호·용량·색상·개수 등 부가정보는 제거하고 핵심 품목명만 남겨.\n"
        "중요: '욕실'/'주방'/'거실' 같은 공간 단어 하나만 응답하면 안 됨. 반드시 핵심 품목어(예: 선반/청소기/그라인더)를 포함해야 함.\n"
        "중요: 한국어 단어를 중간에 자르지 말고 완결된 단어들로 구성해.\n"
        "예시: \"쿠쿠 식기세척기 6인용 CDW-A0611TW 방문설치\" → \"6인용 식기세척기\"\n"
        "예시: \"산리오 헬로키티 미니 물 정수기 디스펜서 2L 핑크\" → \"헬로키티 정수기 디스펜서\"\n"
        "예시: \"데코아르 스마트 자동센서 스테인레스 휴지통 (20L 전용)\" → \"스마트 자동센서 휴지통\"\n"
        "예시: \"스텐 무타공 욕실선반 물빠짐 부착식 삼각 코너선반 화이트 N21\" → \"무타공 욕실선반\"\n\n"
        f"상품명: {name}\n\n"
        "간결한 이름만 출력 (설명 없이):"
    )
    if GOOGLE_API_KEY:
        try:
            from google import genai
            client = genai.Client(api_key=GOOGLE_API_KEY)
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    max_output_tokens=100,
                    temperature=0.2,
                ),
            )
            result = (resp.text or "").strip().strip("\"'")
            if _short_name_ok(result, name):
                return result
            logger.warning(f"generate_short_name Gemini 거절: {result!r} (원본: {name[:30]})")
        except Exception as e:
            logger.warning(f"generate_short_name Gemini 실패: {e}")
    if GROQ_API_KEY:
        try:
            import httpx, urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            from groq import Groq
            client = Groq(api_key=GROQ_API_KEY, http_client=httpx.Client(verify=False))
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.2,
            )
            result = resp.choices[0].message.content.strip().strip("\"'")
            if _short_name_ok(result, name):
                return result
            logger.warning(f"generate_short_name Groq 거절: {result!r} (원본: {name[:30]})")
        except Exception as e:
            logger.warning(f"generate_short_name Groq 실패: {e}")
    # 최종 폴백: 규칙 기반 추출
    fb = _fallback_short_name(name)
    logger.info(f"generate_short_name 폴백 사용: {fb!r}")
    return fb


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
    # 답글(reply)이 Threads 성장의 핵심 → 답글 유도형(question/opinion) 비중을 높게.
    "question",        # 팔로워에게 질문하는 참여 유도 글
    "question",
    "F",               # 의견 갈리는 가벼운 주제 — 댓글·공유 동시 유도(트렌딩 활용)
    "F",
    "daily_life",      # 일상 공감글
    "tip",             # 상품 없는 생활 꿀팁
    "account_intro",   # 계정 소개 / 내가 어떤 사람인지
]

_CASUAL_SYSTEM = """
너는 서울 어딘가에서 혼자 사는 20대 여자 '현지'야. Threads(@hyunji_ssi)에서 1인 가구 일상과 살림 기록을 적고,
가끔 정말 좋아서 자주 쓰는 물건을 공유하는 사람이야. 광고 계정이 아니라 진짜 일반인 톤.
오늘은 상품 얘기 없이 팔로워들과 자연스럽게 소통하는 일상 글을 써야 해.

글 유형별 지침:
- account_intro: "나는 이런 사람이야" / "이 계정은 이런 곳이야" 형식으로, 어떤 기준으로 꿀템을 고르는지, 왜 이 계정을 시작했는지 등을 자연스럽고 솔직하게.
- daily_life: 오늘 겪은 작은 공감 가는 일상 순간, 생활 속 불편함이나 소소한 발견 등. 사람들이 "나도 그래!" 하고 공감할 수 있게. ★끝은 독백으로 닫지 말고 "다들 안 그래?" 처럼 자기 경험 답글 달고 싶은 자연스러운 한 줄로.
- tip: 상품 없이도 살림·생활에 도움 되는 꿀팁 1~2개. 실용적이고 즉시 써먹을 수 있는 것. 계절·날씨와 연결된 생활 상식이면 더 자연스러움. ★끝에 "다들 어떻게 해?" "더 좋은 방법 있어?" 처럼 다른 사람 방법을 묻는 한 줄을 자연스럽게.
- question: 진짜 궁금한 거 다른 사람한테 묻는 글. "나 이거 해보고 싶은데 다들 어떻게 해?" / "이런 경험 다들 한 번씩 있지 않나?" / "솔직히 이런 거 어디서 사?" 같은 톤. 반드시 글 끝에 물음표로 끝내고, 댓글로 자기 경험·의견 적고 싶게 만들어야 함. 광고스럽거나 추천 톤 절대 금지. 진짜 내 일상 고민/궁금증을 친구한테 묻는 것처럼.
- F: 요즘 사람들 의견이 갈리는 가벼운 주제로 글 써줘. 연애/직장/소비/라이프스타일 가치관에서 "이게 맞아? 저게 맞아?" 하고 의견이 나뉠 수 있는 주제. 반드시 어느 한쪽을 강하게 주장하지 말고, 살짝 의문을 던지거나 경험을 공유하는 방식으로. 댓글로 자기 생각 달고 싶게 만들어야 함. 공유하고 싶은 내용으로. 반드시 물음표나 공감 구하는 문장으로 끝낼 것. 정치/젠더/혐오 주제 절대 금지.

출력 형식 (각 블록 사이에 빈 줄 1개):

[훅 — 첫 문장, 멈추게 하는 강렬한 시작]

[본문 3~5줄 — 자연스럽고 친근하게, 재치 있게]

규칙:
- ★[가장 중요] Threads는 '답글' 많은 글을 더 많은 사람에게 노출한다. 모든 글은 읽는 사람이 자기 경험·의견을 답글로 달고 싶어지는 '진짜 궁금한' 한 줄로 끝내라. 단 '댓글 달아줘'·'좋아요 눌러줘' 같은 뻔한 구걸/낚시(engagement bait)는 절대 금지(메타가 강등시킴) — 글과 자연스럽게 이어지는 구체적인 질문/공감 요청이어야 함.
- ★[팔로워 및 소통 유도]: 가끔씩 글 첫 문장에 [현지의 자취일기 #12] 처럼 시리즈 번호를 붙여 다음 편을 팔로우해서 보고 싶게 만들거나, 글 끝에 "다들 어떻게 해? 댓글로 서로 꿀팁 공유해보자!! (나중에 표로 깔끔하게 정리해서 또 공유할게ㅎㅎ)" 처럼 저장(Save)과 참여를 부르는 멘트를 넣어줘.
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
    "이거 나만 이렇게 생각하는 건지 모르겠는데\n자취하면 집에 손님 자주 부르는 편이야, 아니면 거의 안 부르는 편이야?\n솔직히 나는 내 공간 남한테 보여주는 게 좀 어색하더라ㅋㅋ",
]


def generate_general_post(post_type: str | None = None, trending: list[str] | None = None) -> str | None:
    """일상/일반 포스트 생성 (상품 없음)"""
    chosen_type = post_type or random.choice(_CASUAL_POST_TYPES)

    if chosen_type == "F":
        if trending:
            issue_hint = (
                f"오늘 한국 이슈/트렌딩: {', '.join(trending[:5])}\n"
                "정치/젠더/혐오 제외하고 가볍게 논란이 될 수 있는 주제가 있으면 활용해. "
                "없으면 연애/직장/소비/라이프스타일 가치관에서 의견이 갈리는 주제로 써줘."
            )
        else:
            issue_hint = "연애/직장/소비/라이프스타일 중 요즘 사람들 의견이 갈리는 가벼운 주제로 써줘."
        user_msg = f"글 유형: F\n\n{issue_hint}"
    else:
        user_msg = (
            f"글 유형: {chosen_type}\n\n"
            "위 유형에 맞는 Threads 일상 게시글을 써줘. "
            "진짜 사람이 쓴 것처럼 자연스럽고 재치 있게."
        )

    if GOOGLE_API_KEY:
        try:
            from google import genai
            client = genai.Client(api_key=GOOGLE_API_KEY)
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=user_msg,
                config=genai.types.GenerateContentConfig(
                    system_instruction=_CASUAL_SYSTEM,
                    max_output_tokens=3000,
                    temperature=0.95,
                ),
            )
            text = (resp.text or "").strip().strip("\"'""''")
            if text and not _has_foreign_chars(text):
                logger.info("  [Gemini] 일상글 생성 완료")
                return _fix_linebreaks(_seq_diary_number(text))
            logger.warning("Gemini 일상글 외국어 포함 또는 빈 응답 → Groq 폴백")
        except Exception as e:
            logger.warning(f"Gemini 일상글 생성 실패: {e}")

    if not GROQ_API_KEY:
        return random.choice(_CASUAL_FALLBACKS)

    try:
        import httpx, urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        from groq import Groq
        groq_client = Groq(api_key=GROQ_API_KEY, http_client=httpx.Client(verify=False))
        resp = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": _CASUAL_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=800,
            temperature=0.95,
        )
        text = resp.choices[0].message.content.strip().strip("\"'""''")
        if not text or _has_foreign_chars(text):
            logger.warning("일상글 AI 생성 실패 또는 외국어 포함 → 폴백")
            return random.choice(_CASUAL_FALLBACKS)
        logger.info("  [Groq 폴백] 일상글 생성 완료")
        return _fix_linebreaks(_seq_diary_number(text))
    except Exception as e:
        logger.warning(f"일상글 생성 실패: {e}")
        return random.choice(_CASUAL_FALLBACKS)
