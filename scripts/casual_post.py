"""
일상/일반 포스트 — 3일에 한 번 자동 포스팅
상품 링크 없이 계정 소개·일상 공감·생활 팁·질문글 등을 올려 팔로워 유입 유도
"""
import json
import logging
import os
import random
import re
import sys
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import DATA_DIR, LOG_DIR, THREADS_ACCESS_TOKEN

TRACKER_PATH = os.path.join(DATA_DIR, "last_casual_post.json")
FEED_POSTS_PATH = os.path.join(DATA_DIR, "feed_posts.json")
INTERVAL_HOURS = 5  # 하루 2번(오전/저녁) — 같은 슬롯 중복 방지 게이트.
# 6→5 하향(2026-07-13): 오전 글이 지연으로 13시대에 나가면 저녁 19시 글과 간격이
# 6시간 미만이라 저녁 슬롯이 차단되던 문제 해소(저녁 크론 3개끼리는 간격<5h라 여전히 차단됨).

KST = timezone(timedelta(hours=9))

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "casual_post.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("casual_post")


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _should_post() -> bool:
    tracker = _load_json(TRACKER_PATH, {})
    last_posted = tracker.get("last_posted_at")
    if not last_posted:
        return True
    last_dt = datetime.fromisoformat(last_posted)
    elapsed = datetime.now(KST) - last_dt.replace(tzinfo=KST) if last_dt.tzinfo is None else datetime.now(KST) - last_dt
    return elapsed.total_seconds() / 3600 >= INTERVAL_HOURS


def _pick_post_type() -> str | None:
    """KST 시간대 기반 일상글 타입 선택.
    저녁(18시 이후) → question 2/3, F(이슈/논란) 1/3 (댓글 골든타임).
    그 외 → 랜덤 (None 반환, generate_general_post가 알아서 선택)."""
    hour = datetime.now(KST).hour
    if hour >= 18:
        return random.choice(["question", "question", "F"])
    return None


def run():
    logger.info("=" * 50)
    logger.info(f"일상글 포스팅 체크: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    logger.info("=" * 50)

    from scripts.post_gate import kst_gate_sync
    # 저녁 슬롯(SCHEDULE_CRON으로 판별)은 19~22시 창 + 이르면 19시까지 대기 —
    # 유진 실측 최고 성과 시간대(질문·국룰형 20~22시) 정렬 (2026-07-13)
    _EVENING_CRONS = {"17 8 * * *", "17 10 * * *", "17 12 * * *"}
    if os.getenv("SCHEDULE_CRON", "") in _EVENING_CRONS:
        # 상한 22.5(2026-07-14): 21:42 도착 런이 의존성 설치 22분 소요로 22:04 판정
        # → 4분 차이 생략된 실측 보완. 22시대 초반 게시도 골든타임 범위.
        if not kst_gate_sync(19.0, 22.5, max_wait_h=2.0, label="casual-evening"):
            return
    elif not kst_gate_sync(8.0, 22.0, label="casual"):
        return

    if not _should_post():
        tracker = _load_json(TRACKER_PATH, {})
        logger.info(f"아직 {INTERVAL_HOURS}시간 미경과 (마지막: {tracker.get('last_posted_at', '없음')}) — 건너뜀")
        return

    if not THREADS_ACCESS_TOKEN:
        logger.warning("THREADS_ACCESS_TOKEN 미설정 — 건너뜀")
        return

    trending = []
    try:
        from scraper.trending_news import get_trending_topics
        trending = get_trending_topics()
    except Exception as e:
        logger.warning(f"트렌딩 수집 실패: {e}")

    forced_type = _pick_post_type()
    logger.info(f"{INTERVAL_HOURS}시간 경과 — 일상글 생성 시작 (타입: {forced_type or 'random'})")
    from generator.content import generate_general_post
    post_text = generate_general_post(post_type=forced_type, trending=trending)

    if not post_text:
        logger.warning("일상글 생성 실패 — 종료")
        return

    # 잘림 안전망: 사실상 빈/잘린 응답이거나 문장 미완성으로 끝나면 게시 차단.
    # 임계 100→20 하향(2026-07-16): 스레드 일상글은 짧을수록 잘 읽혀 2~3줄 훅 포맷을
    # 허용해야 함 — 100자 하한이 오히려 긴 글을 강제했다. 진짜 잘림은 아래 문장완결 검사가 잡는다.
    body = post_text.strip()
    if len(body) < 20:
        logger.warning(f"일상글 너무 짧음({len(body)}자) — 잘림 의심으로 게시 차단")
        return
    # 끝 이모지 제거 후 마지막 의미 문자 확인 (이모지 장식 뒤 '?' 등 정상 종결 오탐 방지)
    _EMOJI_TAIL_RE = re.compile(
        r'[\U00010000-\U0010FFFF\U0001F000-\U0001FAFF☀-➿⌚-⏿▪-➿]+$'
    )
    body_no_emoji = _EMOJI_TAIL_RE.sub("", body).rstrip("#가-힣 \n").rstrip()
    last_char = body_no_emoji[-1:] if body_no_emoji else ""
    # ㅋㅎㅠㅜ 추가(2026-07-16): 짧은 반말 일상글은 'ㅋㅋ/ㅎㅎ/ㅠㅠ'로 끝나는 게 자연스러운데
    # 기존 집합엔 없어 정상 글이 '미완성'으로 오탐 차단됐다.
    if last_char and last_char not in "다요임어야겠네봄않함봐!?~)♥.…ㅋㅎㅠㅜ":
        logger.warning(f"일상글 문장 미완성('...{body[-15:]}') — 잘림 의심으로 게시 차단")
        return

    # 자취일기 시리즈 번호는 '게시 성공 후'에만 카운터를 소비 — 게이트 차단·발행 실패로
    # 안 올라간 글이 번호만 먹어 발행 시리즈가 띄엄띄엄 어긋나던 문제(2026-07-16) 방지.
    from generator.content import renumber_diary, commit_diary_number
    post_text, diary_n = renumber_diary(post_text)

    logger.info(f"생성된 글:\n{post_text}")

    from poster.threads import post_thread_api
    from poster.comment_replier import add_recent_post

    try:
        result = post_thread_api(post_text=post_text, image_url=None, detail_images=None)
    except Exception as e:
        logger.error(f"포스팅 실패: {e}")
        result = None

    now_str = datetime.now(KST).isoformat()
    status = "posted" if result else "failed"

    if result:
        post_url = result.get("post_url")
        post_id = result.get("post_id")
        if diary_n is not None:
            commit_diary_number(diary_n)  # 발행 성공 시에만 다음 번호로 확정
        _save_json(TRACKER_PATH, {"last_posted_at": now_str})
        if post_url and post_id:
            add_recent_post(post_url, post_id, "story")
        logger.info(f"일상글 포스팅 완료: {post_url or '(URL 없음)'}")
    else:
        logger.warning("일상글 포스팅 실패")

    # feed_posts 기록
    feed = _load_json(FEED_POSTS_PATH, [])
    feed.insert(0, {
        "timestamp":    now_str,
        "product_code": "",
        "product_name": "[일상글]",
        "post_text":    post_text,
        "threads_url":  result.get("post_url") if result else None,
        "status":       status,
        "post_type":    "casual",
    })
    _save_json(FEED_POSTS_PATH, feed[:200])


if __name__ == "__main__":
    run()
