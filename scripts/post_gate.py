"""
KST 시간 게이트 — GitHub Actions 크론 지연(실측 7~12시간) 방어선.

크론이 언제 도착하든 도착 시점의 KST 기준으로:
- 허용창 안이면 즉시 통과
- 창 시작 전이면 시작 시각까지 대기 (max_wait_h 이내일 때만)
- 그 외(새벽 등)는 이번 실행 생략 → 다음 크론에 위임

schedule 이벤트에만 적용. workflow_dispatch(수동 실행)·로컬은 사람 의도이므로 무조건 통과.
"""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
logger = logging.getLogger("post_gate")


def _decide(window_start: float, window_end: float, max_wait_h: float,
            label: str, now: datetime | None):
    """(통과여부, 대기초) 반환"""
    if os.getenv("GITHUB_EVENT_NAME", "") != "schedule":
        return True, 0.0
    now = now or datetime.now(KST)
    h = now.hour + now.minute / 60
    if window_start <= h < window_end:
        return True, 0.0
    if h < window_start:
        wait_h = window_start - h
        if 0 < wait_h <= max_wait_h:
            logger.info(f"[{label}] KST {now:%H:%M} 도착 — {int(window_start):02d}:00까지 {wait_h*60:.0f}분 대기 후 게시")
            return True, wait_h * 3600
        logger.info(f"[{label}] KST {now:%H:%M} 도착 — 창 시작까지 {wait_h:.1f}h(상한 {max_wait_h}h 초과) → 생략")
        return False, 0.0
    logger.info(f"[{label}] KST {now:%H:%M} 도착 — 허용창 {int(window_start)}~{int(window_end)}시 밖 → 생략")
    return False, 0.0


async def kst_gate(window_start: float, window_end: float, max_wait_h: float = 0.0,
                   label: str = "", now: datetime | None = None) -> bool:
    ok, wait = _decide(window_start, window_end, max_wait_h, label, now)
    if ok and wait:
        await asyncio.sleep(wait)
    return ok


def kst_gate_sync(window_start: float, window_end: float, max_wait_h: float = 0.0,
                  label: str = "", now: datetime | None = None) -> bool:
    ok, wait = _decide(window_start, window_end, max_wait_h, label, now)
    if ok and wait:
        time.sleep(wait)
    return ok


def photo_posted_within(days: int = 2, label: str = "") -> bool:
    """최근 N일 내 사진 상품글 발행 여부 — 격일(2일 1회) 빈도 게이트용.

    2026-07-13 사용자 지시: 영상 쿠파스가 2일 1회 페이스라 사진 쿠파스도 2일 1회로.
    feed_posts.json에서 type=video(영상)·post_type=casual(일상글)을 제외한
    가장 최근 posted 항목의 timestamp로 판정. 수동 큐(manual_post)는 사람 의도라
    게이트 없이 나가되, 그 발행도 여기 기록돼 다음 자동 발행을 뒤로 민다.
    """
    import json
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        feed = json.load(open(os.path.join(root, "data", "feed_posts.json"), encoding="utf-8"))
    except Exception:
        return False  # 판독 불가 시 게시 허용(안전측: 기존 동작 유지)
    latest = None
    for p in feed:
        if p.get("type") == "video" or p.get("post_type") == "casual":
            continue
        if p.get("status") != "posted":
            continue
        ts = p.get("timestamp", "")
        if ts and (latest is None or ts > latest):
            latest = ts
    if not latest:
        return False
    try:
        last_dt = datetime.fromisoformat(latest)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=KST)
    except ValueError:
        return False
    # 2026-07-19: 시간차가 아니라 달력 날짜 차이로 판정 — 매일 1건(days=1) 정책에서
    # 어제 지연 도착(예: 15시 발행) 때문에 오늘 13시 창이 24h 미경과로 밀리는 드리프트 방지.
    day_gap = (datetime.now(KST).date() - last_dt.date()).days
    if day_gap < days:
        logger.info(f"[{label}] 최근 사진 상품글 {latest[:16]} — 빈도 게이트({days}일) 미경과 "
                    f"(날짜차 {day_gap}d) → 생략")
        return True
    return False


def refresh_shared_feed(label: str = "") -> None:
    """공유 상태(feed_posts.json)를 원격 최신으로 당김 — 발행 '직전' 재판정용 (best-effort).

    2026-07-17 실사고: 저녁 사진 워크플로가 게이트 통과 후 생성하는 몇 분 사이에
    osmu 영상이 먼저 발행돼 같은 날 사진+영상이 겹침(판정 시점의 체크아웃이 스테일).
    발행 직전 git pull 후 coupang_posted_today()를 한 번 더 호출해 레이스 창을 좁힌다.
    """
    import subprocess
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        subprocess.run(["git", "pull", "--rebase", "--autostash", "-q"],
                       cwd=root, timeout=60, check=False,
                       capture_output=True)
    except Exception as e:
        logger.info(f"[{label}] 공유 피드 pull 실패(무시하고 로컬 판정): {e}")


def coupang_posted_today(label: str = "") -> bool:
    """오늘(KST) 이미 '사진' 쿠파스 상품글이 나갔는지 — '하루 사진 1건 상한'.

    2026-07-19 정책 전환: 상품글 1건 + 영상 1건을 매일 병행하므로 영상(type=video)은
    여기서 세지 않는다(영상 하루 1건 상한은 osmu stock_publisher 게이트가 관리).
    사진(hyunji auto/evening/manual)끼리의 같은 날 중복만 막는다.
    """
    import json
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        feed = json.load(open(os.path.join(root, "data", "feed_posts.json"), encoding="utf-8"))
    except Exception:
        return False  # 판독 불가 시 게시 허용(안전측)
    today = datetime.now(KST).strftime("%Y-%m-%d")
    for p in feed:
        if p.get("status") != "posted" or p.get("post_type") == "casual" \
                or p.get("type") == "video":
            continue
        if p.get("timestamp", "")[:10] == today:
            tag = p.get("product_code") or p.get("type", "") or "상품글"
            logger.info(f"[{label}] 오늘 이미 쿠파스 발행({tag}) → 하루 1개 상한 도달, 생략")
            return True
    return False
