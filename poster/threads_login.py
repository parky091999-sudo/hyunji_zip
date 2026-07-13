"""
쓰레드 수동 로그인 → 쿠키 저장 스크립트
처음 1번만 실행하면 이후 자동 로그인 불필요
"""
import asyncio
import json
import os
from playwright.async_api import async_playwright

COOKIE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "threads_cookies.json")

async def manual_login():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="ko-KR",
        )
        page = await context.new_page()

        print("브라우저가 열립니다. 직접 로그인해주세요.")
        print("로그인 완료(메인 피드 도달) 시 자동으로 쿠키가 저장됩니다. (최대 6분 대기)")

        await page.goto("https://www.threads.com/login")

        # 로그인 완료 자동 감지 — 세션 쿠키(sessionid/ig_did) 확보되면 저장 (input 불필요)
        saved = False
        for _ in range(180):
            await page.wait_for_timeout(2000)
            if "/login" in page.url:
                continue
            cookies = await context.cookies()
            names = {c.get("name") for c in cookies}
            if "sessionid" in names or "ig_did" in names:
                await page.wait_for_timeout(3000)  # 세션 안정화 후 재수집
                cookies = await context.cookies()
                os.makedirs(os.path.dirname(COOKIE_PATH), exist_ok=True)
                with open(COOKIE_PATH, "w") as f:
                    json.dump(cookies, f)
                print(f"쿠키 저장 완료: {COOKIE_PATH} ({len(cookies)}개)")
                saved = True
                break
        if not saved:
            print("로그인 감지 실패(시간 초과) — 스크립트를 다시 실행해주세요")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(manual_login())
