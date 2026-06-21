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
INTERVAL_HOURS = 6  # 하루 2번(09시/21시 KST) — 같은 슬롯 중복 방지용 6시간 게이트

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
    if not kst_gate_sync(8.0, 22.0, label="casual"):
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

    # 잘림 안전망: 100자 미만이거나 문장 미완성으로 끝나면 게시 차단
    body = post_text.strip()
    if len(body) < 100:
        logger.warning(f"일상글 너무 짧음({len(body)}자) — 잘림 의심으로 게시 차단")
        return
    # 끝 이모지 제거 후 마지막 의미 문자 확인 (이모지 장식 뒤 '?' 등 정상 종결 오탐 방지)
    _EMOJI_TAIL_RE = re.compile(
        r'[\U00010000-\U0010FFFF\U0001F000-\U0001FAFF☀-➿⌚-⏿▪-➿]+$'
    )
    body_no_emoji = _EMOJI_TAIL_RE.sub("", body).rstrip("#가-힣 \n").rstrip()
    last_char = body_no_emoji[-1:] if body_no_emoji else ""
    if last_char and last_char not in "다요임어야겠네봄않함봐!?~)♥.…":
        logger.warning(f"일상글 문장 미완성('...{body[-15:]}') — 잘림 의심으로 게시 차단")
        return

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
