"""
콘텐츠 생성기
- 글1: 짧은 훅 캡션 2~3줄 (2026-07-13 전환 — 설명은 사진/영상+첫 댓글이 대체)
- 코드 유도: 본문 말미 "[CODE] 정보는 댓글에 👇" 1줄 (중복게시 마커 겸용)
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

# (구 장문 리뷰형 _POST1_SYSTEM 프롬프트는 2026-07-13 짧은 포맷 전환으로 제거 — git 이력 참조)

# 2026-07-13 사용자 판단 요청 → 결론: 완전 삭제 대신 초경량 1줄로 교체.
#   근거: ①직링크·공정위는 첫 댓글에 있음(전환 동선 유지) ②[코드]가 중복게시
#   차단 마커·관리도구(fix_post_code)에 쓰여 완전 제거는 위험 ③"프로필 링크에서
#   검색"(2단계)보다 "댓글 👇"(1클릭)이 동선 짧음.
_CODE_LINE = "[{code}] 정보는 댓글에 👇"

# 코드 푸터 제거용 — 구(프로필 링크 검색)·신(댓글 유도) 포맷 모두 매칭
_CODE_FOOTER_RE = re.compile(
    r"\n\n(?:제품 정보는 프로필 링크에서 \[(?:\d{3}|CODE)\] 검색 👆"
    r"|\[(?:\d{3}|CODE)\] 정보는 댓글에 👇)\s*$"
)


def _strip_code_footer(text: str) -> str:
    return _CODE_FOOTER_RE.sub("", text or "")

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
# 완결로 인정하는 종결(반말 페르소나 어미 포함): ~더라(라)/~더라고(고)/~거든(든)/~는데·좋은데(데)/
# ~간대(대)/~했나(나)/~하냐(냐)/~그렇군(군)/~좋아(아) 등. 없으면 looks_truncated가 정상 글을 오탐함.
_SENTENCE_END_RE = re.compile(r'[다요임음어아야겠네봄않함봐걸래지자중듯라고든데대나냐군!?~\).♥]$')

# 연결어미·조사에서 끊긴 '미완성 꼬리' — 짧은 캡션이 여기서 끝나면 잘림으로 간주.
# (2026-07-16: "…흘리고 들어" 1줄 파편 게시 사고 대응.)
# ⚠️정상 반말 어미(~더라고/~다고/~좋은데/~거든) 오차단을 피하려 '고'·'는데'는 제외하고,
#   거의 항상 연결/서술을 요구하는 고신뢰 꼬리만 잡는다. 1줄 파편은 2~3줄 강제가 별도로 막음.
_DANGLING_TAIL_RE = re.compile(
    r"(?:"
    r"들어|들어와|나와|"                              # 동사 연결 파편
    r"[가-힣]*(?:아서|어서|여서|라서)|"                 # …서 연결
    r"[가-힣]*(?:다가|려고|으려고|면서|으면서)|"          # 연결어미
    r"[가-힣]*(?:으로|에게|한테|부터)|"                 # 서술 필요 조사
    r"[가-힣]*(?:을|를|의)"                           # 목적·속격 조사
    r")\s*$"
)

# 끝에 붙은 이모지·장식 — 완결 판정 전에 떼어낸다(이모지로 끝나는 정상 캡션 오탐 방지)
_TRAIL_EMOJI_RE = re.compile(
    r'[\U0001F000-\U0010FFFF☀-➿←-⇿⬀-⯿️‍⭐✅❤]+\s*$'
)


def looks_truncated(text: str) -> bool:
    body = _strip_code_footer(text or "").strip()
    if not body:
        return False
    # 길이 게이트: 짧은 포맷(훅 2~3줄, 2026-07-13 전환) 기준 — 한 줄도 안 되면 잘림 의심.
    # ⚠️구 리뷰형(400~600자)의 200자 게이트는 짧은 포맷과 충돌해 폐기
    #   (유지 시 ensure_not_truncated가 모든 정상 짧은 글을 잘림 오판 → 게시 전멸).
    if len(body) < 15:
        return True
    last_para = body.split('\n\n')[-1].strip()
    last_line = last_para.split('\n')[-1].strip()
    if last_line.startswith(('#', '✔', '•', '👉', '👆')):
        return False
    if re.search(r'(spec|itemId|vendorItemId|pageKey|ctag|lptag)=\d+\s*$', last_line):
        return False
    # 끝 이모지 제외 후 완결 판정 (이모지로 끝나는 정상 캡션의 오탐 방지)
    core = _TRAIL_EMOJI_RE.sub("", last_line).strip()
    if not core:
        return False  # 이모지만 남는 끝줄은 의도된 마무리
    if _DANGLING_TAIL_RE.search(core):   # 연결어미/조사에서 끊긴 미완성
        return True
    return not bool(_SENTENCE_END_RE.search(core))


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


_DIARY_COUNTER_PATH = os.path.join(DATA_DIR, "diary_counter.json")


def renumber_diary(text: str) -> tuple[str, int | None]:
    """[현지의 자취일기 #N] 태그를 순차 카운터 번호로 교체하되 카운터를 '소비하지 않는다'.
    (모델이 프롬프트 예시 #12를 보고 아무 번호나 지어내 발행 순서가 #24→#47→#17…
    뒤죽박죽이던 문제 교정 — 2026-07-12.)
    반환한 번호는 실제 게시 성공 후 commit_diary_number(n)로 확정해야 한다. 이렇게
    분리해야 게이트 차단·발행 실패로 안 올라간 글이 번호만 먹어 발행 시리즈가 띄엄띄엄
    어긋나는 것을 막는다(2026-07-16). 이미 발행된 최대 번호가 #47이라 카운터는 48부터 시작.
    반환: (교체된 본문, 사용할 번호 또는 None)"""
    import json as _json
    if not _DIARY_RE.search(text):
        return text, None
    try:
        n = int(_json.load(open(_DIARY_COUNTER_PATH, encoding="utf-8")).get("next", 48))
    except Exception:
        n = 48
    text = _DIARY_RE.sub("@@DIARY@@", text, count=1)
    text = _DIARY_RE.sub("", text)  # 두 번 이상 쓴 경우 나머지 제거
    text = text.replace("@@DIARY@@", f"[현지의 자취일기 #{n}]")
    return text, n


def commit_diary_number(n: int) -> None:
    """게시 성공 후에만 자취일기 카운터를 다음 번호로 확정 (renumber_diary와 짝)."""
    import json as _json
    try:
        _json.dump({"next": n + 1}, open(_DIARY_COUNTER_PATH, "w", encoding="utf-8"))
    except Exception:
        pass


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


_VARIETY_ONLY = "\n\n[필수] 첫 문장을 금지 목록과 완전히 다른 새로운 패턴으로 시작해."

_KOREAN_ONLY = (
    "\n\n[필수] 한국어로만 출력. 태국어·중국어·일본어·베트남어·아랍어 등 어떤 외국어도 절대 사용 금지. "
    "영어 단어도 쓰지 마라 — 한글에 영어를 붙이거나(예: '끝인거imore라고', '더efficient하게') 영어 단어를 섞지 말고 "
    "전부 한국어로 풀어써라. 브랜드·제품명도 한글로 표기. "
    "(단 LED·UV·USB·TV 처럼 일상적으로 굳어진 약어만 예외) 한글과 이모지 위주로만 작성."
)


def _generate_post1_ai(product: dict, product_code: str) -> str | None:
    """사진 상품글 — 2026-07-13부터 짧은 훅 포맷(사진 매체) 위임. 시그니처는 호환 유지."""
    return _generate_short_post(product, product_code, media="photo")


# ── 짧은 상품글 (사진·영상 공용, Threads 포맷) ───────────────────────────────
# 2026-07-13 사용자 지시: 사진·영상 모두 리뷰형 장문 금지 — 후킹 첫줄 포함 2~3줄.
# "스레드는 긴 글 안 읽는다" — 설명은 매체(사진 캐러셀/영상)+첫 댓글이 대체,
# 캡션은 스크롤을 멈추는 미끼 역할만 한다.

_SHORT_MEDIA = {
    "video": {
        "intro": "지금 물건 쓰는 모습이 담긴 짧은 영상을 올리면서 소개글을 붙여.\n상품 설명은 영상이 다 하니까, 글은 스크롤을 멈추고 영상을 재생하게 만드는 미끼야.",
        "hook_goal": "'어? 뭐지' 하고 영상을 누르게 만드는 단 한 줄",
        "second": "영상을 보라고 등 떠미는 말, 또는 짧은 감탄 한 줄",
        "user_ask": "이 상품 영상에 붙일 2~3줄 소개글을 써줘.",
        "fallback": [
            "이거 쓰는 영상 보고 바로 홀렸음\n궁금하면 끝까지 봐봐",
            "요즘 내 살림 최애가 뭐냐면\n영상 보면 바로 알걸",
            "이 영상 보고 안 사고 버틸 수 있나\n나는 실패했음",
        ],
    },
    "photo": {
        "intro": "지금 요즘 잘 쓰는 물건 사진 몇 장을 올리면서 소개글을 붙여.\n자세한 정보는 사진이랑 첫 댓글이 보여주니까, 글은 스크롤을 멈추게 만드는 미끼야.",
        "hook_goal": "'어? 뭐지' 하고 사진을 넘겨보게 만드는 단 한 줄",
        "second": "사진이나 댓글을 확인하게 만드는 말, 또는 짧은 감탄 한 줄",
        "user_ask": "이 상품 사진들에 붙일 2~3줄 소개글을 써줘.",
        "fallback": [
            "이거 왜 이제 알았지 싶은 물건 발견함\n사진 보면 무슨 말인지 알걸",
            "장바구니에 넣고 고민만 삼일 하다 삼\n결론: 더 빨리 살걸 그랬음",
            "요즘 집에서 제일 손 많이 가는 애가 이거임\n궁금하면 댓글 봐봐",
        ],
    },
}

_SHORT_POST_SYSTEM_TMPL = """
너는 Threads(@hyunji_ssi)에서 1인 가구 일상을 적는 20대 여자 '현지'야.
{intro}

━━━ 형식 (가장 중요) ━━━
- 반드시 2~3줄(1줄로 끝내지 마). 한 줄 40자 이내. 그 이상 절대 금지.
- 1줄째 = 훅: {hook_goal}.
  (공감 상황·놀라움·궁금증 중 하나 — 매번 완전히 다른 표현으로. 예시 복사 금지)
- 2~3줄째: {second}.
- ★반드시 완성된 문장으로 끝내. 연결어미(…흘리고/…들어와서/…하는데)나 조사(…을/…를/…으로)에서
  문장을 끊지 마 — 중간에 잘린 것처럼 보이면 안 됨.
- 해시태그 금지. 기능 나열 금지. 리뷰 인용 금지.
- 이모지 0~1개.

━━━ 말투 규칙 ━━━
편안한 반말 — 친구한테 카톡 보내듯. 허용 어미: ~하더라 / ~더라고 / ~거든 / ~했음 / ~임
절대 금지: "~냐?"류 공격조 / "~이다"·"~된다" 뉴스체 / 존댓말 / "~같다" 추측 / 반말↔존댓말 혼용
가격 언급 금지. 상품명 직접 언급 금지 — 상황·효과로만 표현해.
반드시 한국어만. 텍스트만 출력(따옴표·메타설명·안내문구 금지).

━━━ 좋은 예 (그대로 복사 금지) ━━━
설거지하다 허리 나갈 뻔한 사람 이거 꼭 봐
나 이거 보고 바로 주문했잖아
""".strip()

# 존댓말·높임 혼입 탐지 — 현지 페르소나는 반말 고정 (Groq 폴백이 특히 자주 어김)
_HONORIFIC_RE = re.compile(
    r"(?:세요|셔요|습니다|입니다|합니다|이에요|예요|에요|해요|드려요|드릴게요|보세요|하세요|"
    r"보시면|하시면|주시면|드시면|보실|하실)"
)


def _short_caption_gate(cand: str) -> str | None:
    """짧은 캡션 게이트 — 2~3줄·줄당 50자·해시태그 제거·존댓말 차단·완성문장·기존 품질 게이트."""
    cand = (cand or "").strip().strip("\"'“”‘’")
    if not cand or _has_foreign_chars(cand) or _has_bad_english(cand) or _is_dup_hook(cand):
        return None
    if _HONORIFIC_RE.search(cand):
        return None
    lines = [l for l in (x.strip() for x in cand.split("\n")) if l]
    lines = [l for l in lines if not l.startswith("#")]
    # 2~3줄 강제 — 1줄짜리는 대개 잘린 파편("…흘리고 들어" 사고, 2026-07-16). 줄당 50자.
    if not (2 <= len(lines) <= 3) or any(len(l) > 50 for l in lines):
        return None
    # 마지막 줄 완결성 — looks_truncated와 같은 판정(연결어미/조사 종결 or 비종결 = 미완성).
    # 끝 이모지는 제외하고 본다. 미완성이면 탈락 → 재생성 유도(최종 폴백은 완성문장).
    last = _TRAIL_EMOJI_RE.sub("", lines[-1]).strip()
    if last and (_DANGLING_TAIL_RE.search(last) or not _SENTENCE_END_RE.search(last)):
        return None
    return "\n".join(lines)


def _generate_short_post(product: dict, product_code: str, media: str = "photo") -> str:
    """사진·영상 공용 짧은 본문 — 훅 2~3줄 + 코드 라인. 전부 실패 시 고정 훅 폴백."""
    m = _SHORT_MEDIA.get(media, _SHORT_MEDIA["photo"])
    system = _SHORT_POST_SYSTEM_TMPL.format(
        intro=m["intro"], hook_goal=m["hook_goal"], second=m["second"])
    name = product.get("name", "")
    user_msg = f"상품명: {name}\n\n{m['user_ask']}"
    banned = _recent_first_lines()
    if banned:
        user_msg += "\n\n[중요] 아래 최근 첫 문장들과 같거나 비슷하게 시작 금지:\n"
        user_msg += "\n".join(f"- {b}" for b in banned)

    if GOOGLE_API_KEY:
        try:
            from google import genai
            client = genai.Client(api_key=GOOGLE_API_KEY)
            for attempt in range(3):
                extra = (_KOREAN_ONLY + _VARIETY_ONLY) if attempt > 0 else ""
                resp = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=user_msg + extra,
                    config=genai.types.GenerateContentConfig(
                        system_instruction=system,
                        max_output_tokens=300,
                        temperature=0.95,
                    ),
                )
                body = _short_caption_gate(resp.text)
                if body:
                    logger.info(f"  [Gemini] 짧은 캡션({media}) 생성 완료")
                    return f"{body}\n\n{_CODE_LINE.format(code=product_code)}"
                logger.warning(f"짧은 캡션 게이트 탈락 → 재시도 {attempt + 1}/3")
        except Exception as e:
            logger.warning(f"Gemini 짧은 캡션 실패: {e}")
    if GROQ_API_KEY:
        try:
            import httpx, urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            from groq import Groq
            client = Groq(api_key=GROQ_API_KEY, http_client=httpx.Client(verify=False))
            for attempt in range(3):
                extra = (_KOREAN_ONLY + _VARIETY_ONLY) if attempt > 0 else ""
                resp = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user_msg + extra}],
                    max_tokens=300,
                    temperature=0.9 if attempt == 0 else 0.6,
                )
                body = _short_caption_gate(resp.choices[0].message.content)
                if body:
                    logger.info(f"  [Groq 폴백] 짧은 캡션({media}) 생성 완료")
                    return f"{body}\n\n{_CODE_LINE.format(code=product_code)}"
                logger.warning(f"짧은 캡션(Groq) 게이트 탈락 → 재시도 {attempt + 1}/3")
        except Exception as e:
            logger.warning(f"Groq 짧은 캡션 실패: {e}")
    logger.warning(f"짧은 캡션({media}) AI 생성 전부 실패 — 고정 훅 폴백")
    return f"{random.choice(m['fallback'])}\n\n{_CODE_LINE.format(code=product_code)}"


def generate_video_post_text(product: dict, product_code: str) -> str:
    """영상 게시용 짧은 본문 (osmu publish_video_product.py가 호출)."""
    return _generate_short_post(product, product_code, media="video")


# ── 글1: 폴백 템플릿 ──────────────────────────────────────────────────────────

def _post1_fallback(name: str, product_code: str) -> str:
    """짧은 포맷 고정 훅 폴백 (fix_post_code 등 외부 호환용, 2026-07-13 단축)."""
    return f"{random.choice(_SHORT_MEDIA['photo']['fallback'])}\n\n{_CODE_LINE.format(code=product_code)}"


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
        post_text_1 = _strip_code_footer(post_text_1)
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
    m = re.search(r"\[(\d{3})\]", text or "")
    code = product_code or (m.group(1) if m else "")
    regen = _generate_post1_ai(product, code or "CODE")
    # regen은 _short_caption_gate(2~3줄·외국어·존댓말·중복 차단)를 이미 통과한 결과라
    # looks_truncated로 재검열하지 않는다 — 정상 짧은 캡션의 자연스러운 종결(…거/…네/명사/이모지)을
    # '잘림'으로 오판해 유효한 본문까지 버리고 게시가 통째로 skip되던 문제(2026-07-16) 방지.
    # (실측: Gemini가 새 캡션을 정상 생성했는데도 looks_truncated 재검열에 걸려 [060] skip.)
    if regen and not _has_foreign_chars(regen):
        if not code:
            regen = _strip_code_footer(regen)
        return regen
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

    m = re.search(r"\[(\d{3})\]", text)
    code = product_code or (m.group(1) if m else "")
    logger.warning("정제 실패 → 본문 재생성")
    regen = _generate_post1_ai(product, code or "CODE")
    if regen and not _has_foreign_chars(regen) and not _has_bad_english(regen):
        if not code:
            regen = _strip_code_footer(regen)
        return regen

    logger.warning("재생성 실패 → 안전 템플릿 사용")
    fb = _post1_fallback(product.get("name", ""), code or "CODE")
    if not code:
        fb = _strip_code_footer(fb)
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
너는 서울 어딘가에서 혼자 사는 20대 여자 '현지'야. Threads(@hyunji_ssi)에 1인 가구 일상과 살림을 짧게 기록해.
광고 계정 아니라 진짜 일반인 톤. 오늘은 상품 얘기 없이 팔로워랑 소통하는 일상 글을 써.

★★가장 중요 — 짧게, 훅킹 있게:
- 스레드는 길면 아무도 안 읽어. 전체 2~3줄(최대 4줄)로 딱 끊어. 한 호흡에 훅 읽히게. 절대 늘여쓰지 마.
- 첫 줄이 승부다 — 스크롤을 멈추게 하는 강한 훅으로 시작해. 공감(나도 그래)·의외·솔직고백·궁금증 중 하나로 확 잡아.
  "오늘은~", "요즘~", "다들 그거 알지?" 같은 밋밋하고 뻔한 도입은 금지.
- 배경설명·부연 늘어놓지 마. 핵심 장면 딱 하나만 남기고 나머지는 다 버려.

글 유형별 (전부 2~3줄):
- account_intro: "나 이런 사람이야 / 이 계정 이런 곳이야"를 한두 줄로 솔직하게.
- daily_life: 오늘 겪은 공감 장면 딱 한 컷. 읽자마자 "나도 그래!" 나오게.
- tip: 살림·생활 꿀팁 딱 1개, 바로 써먹게 한 줄로.
- question: 진짜 궁금한 걸 친구한테 묻듯 짧게. 반드시 물음표로 끝. 추천·광고 톤 절대 금지.
  (실측: 다들 당연시하는 생활매너·습관에 의문 던지고 내 원칙 짧게 밝힌 저녁 글이 크게 터진 적 있음 —
   단 "국룰 아니었음?" 같은 특정 표현 반복·도배는 금방 식상해지니 금지, 매번 완전히 다른 소재로.)
- F: 의견 갈리는 가벼운 주제(연애/직장/소비/라이프스타일)를 한 줄 툭 던지고 "다들 어때?"로 끝.
  한쪽을 세게 주장하지 말고 살짝 의문만. 정치/젠더/혐오 절대 금지.

끝맺음 (조회수·노출의 핵심):
- Threads는 '답글' 많은 글을 더 널리 노출해. 모든 글은 읽는 사람이 자기 경험·의견을 답글로 달고 싶어지는
  '진짜 궁금한 한 줄'로 끝내라. 독백으로 닫지 마.
- 단 '댓글 달아줘'·'좋아요 눌러줘' 같은 뻔한 구걸(engagement bait)은 절대 금지(메타가 노출 강등).
  글과 자연스럽게 이어지는 구체적인 질문이어야 함.

자취일기 시리즈 (가끔만, 대략 3~4번에 1번꼴):
- 가끔 첫 줄을 [현지의 자취일기 #12]로 시작해 다음 편이 궁금하게 만들어. 번호는 아무거나 써도 시스템이
  자동 교정하니 신경 쓰지 마. 자취하며 겪은 짧은 에피소드 한 장면 + 끝에 질문. 이것도 2~3줄로 짧게.

규칙:
- 반말, 친근, 위트. 진짜 사람이 툭 던진 것처럼.
- 이모지 0~1개만.
- 해시태그 절대 금지. 상품·링크 절대 금지. 한국어만. 텍스트만 출력(메타설명 금지).
""".strip()

# 짧은 포맷 폴백 (2~3줄, 훅+질문) — 2026-07-16 단축
_CASUAL_FALLBACKS = [
    "설거지 하루만 미뤄도 싱크대가 지옥됨\n이거 나만 그래…? 다들 며칠에 한 번 몰아서 해?",
    "혼자 사는데 제일 쓸데없이 자주 사는 거\n나는 그릇이야ㅋㅋ 다들 이런 거 하나씩 있지 않아?",
    "정리 끝내고 딱 3일 뒤면 원상복구 되는 거\n이 저주 다들 어떻게 끊어…?",
    "자취하면 집에 손님 자주 불러? 거의 안 불러?\n난 내 공간 보여주는 게 좀 어색하더라ㅋㅋ",
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
                # 자취일기 번호는 여기서 매기지 않는다 — 게시 성공 후 renumber_diary+commit(caller).
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
        return _fix_linebreaks(text)
    except Exception as e:
        logger.warning(f"일상글 생성 실패: {e}")
        return random.choice(_CASUAL_FALLBACKS)
