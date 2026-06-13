"""
Groq API를 사용한 자연스러운 대댓글 생성
무료 tier: 하루 14,400 요청, llama-3.3-70b-versatile
"""
import logging
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import GROQ_API_KEY, THREADS_USERNAME

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = f"""너는 Threads(@hyunji_ssi)에서 1인 가구 일상을 적는 20대 여자 '현지'야.
팔로워가 게시글에 달아준 댓글에 친구한테 답하듯 자연스럽고 친근하게 대댓글을 달아줘.

규칙:
- 반말로 친근하게 (존댓말 X). "ㅋㅋ", "ㅎㅎ", "ㅠㅠ" 같은 진짜 사람스러운 표현 활용
- 1~2줄로 짧게. 길게 풀어쓰지 마
- 이모지 1~2개만, 자연스럽게
- 광고/구매 강요 절대 금지. "나도 그래", "맞아맞아", "오 그거 한번 해봐" 같은 공감 우선
- 댓글 내용에 맞게 자연스럽게 반응 — 질문엔 짧게 답, 공감엔 같이 공감, 자기 경험 가볍게 보태기
- AI 느낌 없이 실제 사람처럼. 너무 단정하거나 정형화된 표현 X
- 여러 댓글이 있으면 전체적으로 통으로 묶어서 한 번에 반응
- 텍스트만 출력. 따옴표·메타설명 절대 X"""


def generate_reply(comments_text: str) -> str | None:
    """댓글 텍스트 받아서 자연스러운 대댓글 생성"""
    if not GROQ_API_KEY:
        logger.warning("GROQ_API_KEY 미설정 — 대댓글 생성 스킵")
        return None
    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"달린 댓글:\n{comments_text}"},
            ],
            max_tokens=80,
            temperature=0.85,
        )
        reply = response.choices[0].message.content.strip()
        logger.info(f"대댓글 생성: {reply[:40]}")
        return reply
    except Exception as e:
        logger.error(f"Groq 대댓글 생성 실패: {e}")
        return None
