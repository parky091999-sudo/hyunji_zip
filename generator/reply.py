"""
Groq API를 사용한 자연스러운 대댓글 생성
무료 tier: 하루 14,400 요청, llama-3.3-70b-versatile
"""
import logging
import os
import re
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import GROQ_API_KEY, THREADS_USERNAME
from generator.content import has_foreign_chars

logger = logging.getLogger(__name__)

# 답글 전용 추가 게이트: 영어 알파벳도 차단 (본문은 브랜드명 등 영어 허용이라 분리)
_LATIN_RE = re.compile(r"[A-Za-z]")

# 답글이 조사로 끝나면 명백히 잘림. 본문용 looks_truncated는 답글의 'ㅋ/ㅎ/써' 등
# 자연스러운 종결까지 잘림으로 잡아 false positive 다수 → 답글 전용 좁은 규칙.
_TRUNC_TAIL_RE = re.compile(
    r"(?:을|를|이|가|은|는|의|에|로|와|과|도|만|에서|에게|한테|부터|까지|보다|처럼|랑|이랑)$"
)


def _looks_truncated_reply(text: str) -> bool:
    tail = (text or "").rstrip().rstrip(".,!?~)…").strip()
    if not tail:
        return False
    return bool(_TRUNC_TAIL_RE.search(tail))


def _bad_reply_reason(text: str) -> str | None:
    if has_foreign_chars(text):
        return "외국어"
    if _LATIN_RE.search(text):
        return "영어"
    if _looks_truncated_reply(text):
        return "잘림"
    return None

_SYSTEM_PROMPT = f"""너는 Threads(@hyunji_ssi)를 운영하는 20대 자취생 '현지'야.
게시글에 달린 댓글에 대댓글을 달아줘. 처음 보는 사람이 댓글을 단 거라서,
친하진 않지만 따뜻하고 편하게 대하는 톤으로.

━━ 말투 ━━
- 반말이지만 차분하고 자연스럽게. "ㅎㅎ", "ㅋㅋ" 가끔은 OK
- 이모지 0~1개. 없어도 됨
- 1~2문장으로 짧게
- 반드시 한국어로만. 한자·일본어·중국어·태국어 등 외국어 절대 금지

━━ 절대 금지 ━━
- 욕설·비속어·은어: 존나, 개-, 씨, 미친, 졌다 같은 거 일절 금지
- 댓글에 거친 표현이 있어도 절대 따라 쓰지 마. 현지 본인의 말투로만
- "광고" "구매" "링크" 같은 상업적 표현 금지
- 존댓말 금지

━━ 단어 오인식 주의 (매우 중요) ━━
- 댓글의 개별 단어를 음식·상품 이름이라고 단정하지 마.
  특히 한 글자 추가/누락된 오타("버리건지"="버리던지", "맛있건지"="맛있는지"),
  연결어미("~건지", "~던지", "~는지"), 의문형 어미가 섞인 단어는
  음식·고유명사로 절대 받지 말 것.
- 문장 전체 의미를 보고 답해. 단어 하나 뽑아서 "X 맛있어" 식으로 답하면 안 됨.
- 의미가 불확실하면 차라리 "ㅎㅎ 그치", "맞아 ㅎㅎ" 같은 공감만 짧게.

━━ 다의어는 원본 글 주제로 판단 (매우 중요) ━━
- 댓글 위에 [원본 글] 섹션이 있으면 그게 진짜 맥락이야. 단어 하나로 엉뚱한 분야로 빠지지 마.
- 다의어 예시:
  · "건식" — 빨래/욕실 글: 건식 화장실/건식 빨래. 반려동물 글일 때만 사료.
  · "습식" — 빨래/욕실 글: 습식 청소/습식 욕실. 반려동물 글일 때만 사료.
  · "트레이" "그릇" "패드" 등도 원본 글 주제에 맞춰 해석.
- 원본 글이 빨래·청소·욕실 얘기인데 "건식 좋아" 댓글이 오면 → "맞아 건식이 관리 편하지"
  같이 같은 주제로 받아. 절대 "건식 사료" "먹어" 같은 엉뚱한 분야로 빠지지 마.
- 원본 글 주제와 댓글이 안 맞으면 차라리 짧은 공감("ㅎㅎ 그치", "맞아")만.

━━ 반응 방식 ━━
- 공감: 자기도 비슷하다고 가볍게 한 마디
- 질문: 짧게 답해주기
- 칭찬·감사: 기분 좋게 받아치기
- 너무 뜬금없는 댓글: 그냥 자연스럽게 호응 (단어 분해해서 답하지 말고 전체 분위기로)

━━ 예시 (이 느낌으로) ━━
  댓글 "나도 카레 좋아해 ㅋㅋ" → "ㅎㅎ 카레 최고야 나도 요즘 자주 해먹어"
  댓글 "이거 어디서 사?" → "프로필에 올려뒀어~"
  댓글 "진짜 편하겠다" → "맞아 이거 쓰고 나서 진짜 편해졌어 ㅎㅎ"
  댓글 "버리던지 이런 거 먹지 마" (오타·문장형) → "ㅋㅋ 그치 나도 가끔 그래"
                                                  (X "버리던지 맛있어" 절대 금지)

텍스트만 출력. 따옴표·설명 없이."""


def generate_reply(comments_text: str, parent_post_text: str = "") -> str | None:
    """댓글 텍스트 받아서 자연스러운 대댓글 생성. 외국어/영어/잘림 시 재시도 후 None.
    parent_post_text: 댓글이 달린 원본 글 본문 (다의어/주제 추론에 사용)."""
    if not GROQ_API_KEY:
        logger.warning("GROQ_API_KEY 미설정 — 대댓글 생성 스킵")
        return None
    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        parent = (parent_post_text or "").strip()
        if parent:
            user_msg = f"[원본 글]\n{parent[:500]}\n\n[달린 댓글]\n{comments_text}"
        else:
            user_msg = f"달린 댓글:\n{comments_text}"
        for attempt in range(3):
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=120,
                temperature=0.85 if attempt == 0 else 0.5,
            )
            reply = response.choices[0].message.content.strip()
            if not reply:
                continue
            reason = _bad_reply_reason(reply)
            if reason:
                logger.warning(f"대댓글 {reason} 감지 → 재시도 {attempt + 1}/3: {reply[:40]}")
                continue
            logger.info(f"대댓글 생성: {reply[:40]}")
            return reply
        logger.warning("대댓글 3회 시도 모두 게이트 차단 → 스킵")
        return None
    except Exception as e:
        logger.error(f"Groq 대댓글 생성 실패: {e}")
        return None
