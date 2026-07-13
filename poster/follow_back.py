# -*- coding: utf-8 -*-
"""신규 팔로워 자동 반응 (팔로우백) — 맞팔 + 최근글 좋아요 + 게시글 특성 댓글.

engager.py 패턴 재사용: 쿠키 세션 로그인 · 랜덤 딜레이 · 하루 상한 · 처리기록(중복 방지).
리포스트는 제외(2026-07-13 사용자 지시 — 계정 정체성·탐지 위험). '반하리' 같은 봇 시그널
문구는 쓰지 않고, 상대 최근 게시글 특성 댓글(Groq) 또는 일반 인사를 남긴다.

⚠️ 봇 탐지에 가장 민감한 동작이라 집 PC(작업 스케줄러)에서 저빈도로만 실행. 데이터센터
   IP(GitHub Actions)에서는 돌리지 않는다.

실행:
  python -m poster.follow_back --dry     # 감지·댓글생성만 (실제 팔로우/좋아요/게시 안 함) — 먼저 이걸로 검증
  python -m poster.follow_back --show    # 브라우저 띄워 눈으로 확인(headless 끔)
  python -m poster.follow_back           # 실동작(작업 스케줄러가 호출)
"""
import argparse
import asyncio
import json
import logging
import os
import random
import sys
from datetime import datetime, timedelta

from playwright.async_api import Page

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import DATA_DIR
from poster.engager import _extract_post_text, _generate_comment, _is_quality_comment

logger = logging.getLogger("follow_back")

PROCESSED_PATH = os.path.join(DATA_DIR, "followed_back.json")
COOKIE_PATH = os.path.join(DATA_DIR, "threads_cookies.json")
THREADS_URL = "https://www.threads.com"

MAX_PER_RUN = 12          # 1회 최대 처리 팔로워 (저빈도)
MIN_DELAY_SEC = 150       # 유저 사이 2.5~5분 (자연스러운 간격)
MAX_DELAY_SEC = 300
ACTION_GAP = (2.0, 6.0)   # 한 유저 내 팔로우→좋아요→댓글 사이 초
HISTORY_DAYS = 90

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# 게시글이 없어 특성 댓글을 못 만들 때 쓰는 일반 인사 (반복 티 안 나게 로테이션)
GREETINGS = [
    "팔로우 감사해요 반가워요~",
    "안녕하세요 반가워요 자주 소통해요~",
    "팔로우 감사합니다 잘 보고 갈게요~",
    "반가워요~ 앞으로 자주 소통해요",
    "안녕하세요 팔로우 감사해요 :)",
]


def _load_processed() -> set:
    if not os.path.exists(PROCESSED_PATH):
        return set()
    try:
        data = json.load(open(PROCESSED_PATH, encoding="utf-8"))
    except Exception:
        return set()
    cutoff = datetime.now() - timedelta(days=HISTORY_DAYS)
    return {k for k, v in data.items() if datetime.fromisoformat(v) > cutoff}


def _save_processed(users: dict):
    existing = {}
    if os.path.exists(PROCESSED_PATH):
        try:
            existing = json.load(open(PROCESSED_PATH, encoding="utf-8"))
        except Exception:
            existing = {}
    existing.update(users)
    cutoff = datetime.now() - timedelta(days=HISTORY_DAYS)
    cleaned = {k: v for k, v in existing.items() if datetime.fromisoformat(v) > cutoff}
    os.makedirs(DATA_DIR, exist_ok=True)
    json.dump(cleaned, open(PROCESSED_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


async def _sleep(a, b, dry=False):
    await asyncio.sleep(0.3 if dry else random.uniform(a, b))


async def detect_new_followers(page: Page, limit: int = 40) -> list:
    """활동(알림) 페이지에서 '회원님을 팔로우' 알림의 @username 목록 추출.

    Threads DOM은 자주 바뀌므로 팔로우 알림 행을 텍스트로 식별한다:
    링크(/@user)를 담은 알림 항목의 텍스트에 '팔로우'가 있고 '좋아요/답글/언급'이 없으면 채택.
    ⚠️ 셀렉터는 실제 페이지에 맞춰 튜닝 필요 — --dry로 먼저 검증.
    """
    users, seen = [], set()
    for url in (f"{THREADS_URL}/activity/follows", f"{THREADS_URL}/activity"):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(3500)
            if "/login" in page.url or page.url.rstrip("/") == THREADS_URL:
                logger.warning(f"활동 페이지 접근 불가(→ {page.url}) — 쿠키 세션 부족. "
                               "poster/threads_login.py 로 재로그인 후 다시 시도하세요")
                continue
            anchors = await page.query_selector_all("a[href^='/@']")
            for a in anchors:
                href = await a.get_attribute("href") or ""
                if "/post/" in href:
                    continue
                uname = href.strip("/").lstrip("@").split("/")[0]
                if not uname or uname in seen:
                    continue
                # 알림 행 텍스트로 '팔로우' 여부 판별 (조상 컨테이너 텍스트)
                try:
                    row_text = await a.evaluate(
                        "el => (el.closest('div[role=\"row\"]') || el.parentElement?.parentElement "
                        "|| el.parentElement || el).innerText")
                except Exception:
                    row_text = ""
                rt = row_text or ""
                is_follow = ("팔로우" in rt or "follow" in rt.lower())
                is_other = any(k in rt for k in ("좋아요", "답글", "언급", "님이 회원님의", "리포스트"))
                if is_follow and not is_other:
                    seen.add(uname)
                    users.append(uname)
                if len(users) >= limit:
                    break
            if users:
                logger.info(f"활동 페이지({url.split('/')[-1]}) — 팔로우 알림 {len(users)}명 감지")
                break
        except Exception as e:
            logger.warning(f"활동 페이지 파싱 실패 ({url}): {e}")
    return users


async def _click_by_text(page: Page, texts: tuple) -> bool:
    """보이는 버튼 중 텍스트가 정확히 일치하는 것 클릭."""
    for sel in ("div[role='button']", "button"):
        for el in await page.query_selector_all(sel):
            try:
                t = (await el.inner_text()).strip()
            except Exception:
                continue
            if t in texts:
                await el.click()
                return True
    return False


async def _follow_user(page: Page, username: str, dry: bool) -> bool:
    """프로필 방문 → 팔로우 버튼 클릭(이미 맞팔이면 스킵)."""
    await page.goto(f"{THREADS_URL}/@{username}", wait_until="domcontentloaded", timeout=25000)
    await page.wait_for_timeout(2500)
    # 이미 팔로잉이면 버튼 텍스트가 '팔로잉'/'맞팔로우 중' → 건너뜀
    has_follow = False
    for sel in ("div[role='button']", "button"):
        for el in await page.query_selector_all(sel):
            try:
                t = (await el.inner_text()).strip()
            except Exception:
                continue
            if t in ("팔로우", "맞팔로우", "Follow", "Follow back"):
                has_follow = True
    if not has_follow:
        logger.info(f"  @{username}: 팔로우 버튼 없음(이미 맞팔이거나 구조 상이) — 스킵")
        return False
    if dry:
        logger.info(f"  [dry] @{username} 맞팔로우 예정")
        return True
    ok = await _click_by_text(page, ("팔로우", "맞팔로우", "Follow", "Follow back"))
    await page.wait_for_timeout(1500)
    logger.info(f"  @{username} 맞팔로우 {'완료' if ok else '실패'}")
    return ok


async def _like_recent(page: Page, dry: bool) -> bool:
    """현재 프로필의 최근 게시글 좋아요(첫 하트 버튼)."""
    like = await page.query_selector("svg[aria-label='좋아요'], svg[aria-label='Like']")
    if not like:
        logger.info("  좋아요 버튼 못찾음 — 스킵")
        return False
    if dry:
        logger.info("  [dry] 최근글 좋아요 예정")
        return True
    try:
        target = await like.evaluate_handle(
            "el => el.closest('div[role=\"button\"],button,a') || el")
        await target.as_element().click()
        await page.wait_for_timeout(1200)
        logger.info("  최근글 좋아요 완료")
        return True
    except Exception as e:
        logger.info(f"  좋아요 실패: {e}")
        return False


async def _comment_recent(page: Page, username: str, dry: bool) -> bool:
    """프로필 최근 게시글 방문 → 특성 댓글(Groq) 또는 일반 인사."""
    link = await page.query_selector("a[href*='/post/']")
    if not link:
        logger.info(f"  @{username}: 게시글 없음 — 댓글 생략")
        return False
    href = await link.get_attribute("href") or ""
    post_url = f"{THREADS_URL}{href}" if href.startswith("/") else href
    await page.goto(post_url, wait_until="domcontentloaded", timeout=25000)
    await page.wait_for_timeout(2000)

    post_text = await _extract_post_text(page)
    comment = _generate_comment(post_text) if post_text else None
    if comment and not _is_quality_comment(comment):
        comment = _generate_comment(post_text, retry=True)
    if not comment:
        comment = random.choice(GREETINGS)

    if dry:
        logger.info(f"  [dry] @{username} 댓글 예정: {comment}")
        return True

    box = await page.query_selector("div[role='textbox'], [contenteditable='true']")
    if not box:
        logger.info("  댓글창 없음 — 스킵")
        return False
    await box.click()
    await page.wait_for_timeout(500)
    await page.keyboard.type(comment, delay=45)
    await page.wait_for_timeout(700)
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(1800)
    logger.info(f"  댓글 완료: {comment}")
    return True


async def run_follow_back(page: Page, max_users: int, actions: tuple, dry: bool):
    processed = _load_processed()
    followers = await detect_new_followers(page)
    logger.info(f"감지 {len(followers)}명 · 처리기록 {len(processed)}명 · 최대 {max_users}명 처리")
    new, count = {}, 0
    for uname in followers:
        if count >= max_users:
            break
        if uname in processed:
            continue
        logger.info(f"[{count + 1}] @{uname}")
        followed = await _follow_user(page, uname, dry)
        if not followed:
            continue  # 이미 맞팔/버튼없음 → 기록도 남기지 않음(다음에 재시도 가능)
        if "like" in actions:
            await _sleep(*ACTION_GAP, dry=dry)
            await _like_recent(page, dry)
        if "comment" in actions:
            await _sleep(*ACTION_GAP, dry=dry)
            await _comment_recent(page, uname, dry)
        new[uname] = datetime.now().isoformat()
        processed.add(uname)
        count += 1
        if count < max_users:
            await _sleep(MIN_DELAY_SEC, MAX_DELAY_SEC, dry=dry)
    if new and not dry:
        _save_processed(new)
    logger.info(f"완료: {count}명 처리 (dry={dry})")


async def run_session(max_users=MAX_PER_RUN, actions=("follow", "like", "comment"),
                      dry=False, headless=True):
    from playwright.async_api import async_playwright
    if not os.path.exists(COOKIE_PATH):
        logger.warning("쿠키 없음 — poster/threads_login.py 로 먼저 로그인하세요")
        return
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(user_agent=UA,
                                             viewport={"width": 1280, "height": 800},
                                             locale="ko-KR")
        try:
            context_cookies = json.load(open(COOKIE_PATH))
            await context.add_cookies(context_cookies)
            page = await context.new_page()
            await page.goto(THREADS_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            if "login" in page.url:
                logger.warning("세션 만료 — threads_login.py 로 재로그인 필요")
                return
            await run_follow_back(page, max_users, actions, dry)
        finally:
            await browser.close()


def main():
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(os.path.join(log_dir, "follow_back.log"), encoding="utf-8")])
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="감지·댓글생성만 (실제 액션 없음)")
    ap.add_argument("--max", type=int, default=MAX_PER_RUN)
    ap.add_argument("--show", action="store_true", help="브라우저 표시(headless 끔)")
    a = ap.parse_args()
    asyncio.run(run_session(max_users=a.max, dry=a.dry, headless=not a.show))


if __name__ == "__main__":
    main()
