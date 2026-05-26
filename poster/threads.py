"""
쓰레드(Threads) 자동 포스터
- Playwright로 실제 브라우저를 조작해 로그인 → 게시 → 댓글 작성
- 쓰레드는 공식 API가 없어 브라우저 자동화 방식 사용
"""
import asyncio
import os
import sys
import logging
import requests
import tempfile
from pathlib import Path
from playwright.async_api import async_playwright, Page, BrowserContext

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import THREADS_USERNAME, THREADS_PASSWORD

logger = logging.getLogger(__name__)

THREADS_URL = "https://www.threads.com"
LOGIN_URL = "https://www.threads.com/login"


async def _human_type(page: Page, selector: str, text: str, delay: int = 80):
    """사람처럼 천천히 타이핑 (봇 탐지 우회)"""
    await page.click(selector)
    await page.type(selector, text, delay=delay)


COOKIE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "threads_cookies.json")


async def login(context: BrowserContext) -> Page:
    """쿠키로 로그인 (threads_login.py로 먼저 쿠키 저장 필요)"""
    import json as _json

    if not os.path.exists(COOKIE_PATH):
        raise RuntimeError(
            "쿠키 파일 없음. 먼저 실행하세요:\n"
            "  python poster/threads_login.py"
        )

    with open(COOKIE_PATH) as f:
        cookies = _json.load(f)

    await context.add_cookies(cookies)
    logger.info(f"쿠키 로드: {len(cookies)}개")

    page = await context.new_page()
    await page.goto(THREADS_URL, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    logger.info(f"접속 URL: {page.url}")

    if "login" in page.url:
        raise RuntimeError("세션 만료 - poster/threads_login.py 재실행 필요")

    logger.info("로그인 성공 (쿠키)")
    return page


async def _download_image(image_url: str) -> str | None:
    """이미지 URL을 임시 파일로 다운로드, 경로 반환"""
    if not image_url:
        return None
    try:
        resp = requests.get(image_url, timeout=10)
        resp.raise_for_status()
        suffix = ".jpg" if "jpg" in image_url.lower() else ".png"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(resp.content)
        tmp.close()
        return tmp.name
    except Exception as e:
        logger.warning(f"이미지 다운로드 실패: {e}")
        return None


async def post_thread(page: Page, post_text: str, image_url: str | None = None) -> str | None:
    """
    쓰레드에 게시글 작성
    반환: 게시된 포스트 URL (성공 시)
    """
    logger.info("게시글 작성 시작...")

    # 게시글 작성 페이지로 직접 이동
    await page.goto(f"{THREADS_URL}/intent/post", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    # 혹시 홈으로 리다이렉트됐으면 버튼 클릭 시도
    if "/intent/post" not in page.url:
        logger.info("리다이렉트 감지 - 버튼 클릭 시도")
        await page.goto(THREADS_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
        compose_selectors = [
            "a[href='/intent/post']",
            "[aria-label='새 스레드']",
            "[aria-label='New thread']",
            "[aria-label='Create']",
        ]
        for sel in compose_selectors:
            try:
                btn = await page.query_selector(sel)
                if btn:
                    await btn.click()
                    break
            except Exception:
                continue
        await page.wait_for_timeout(2000)

    # 텍스트 입력 영역 (모달 안 contenteditable)
    typed = False
    for sel in ["[contenteditable='true']", "div[role='textbox']", "div[contenteditable]"]:
        el = await page.query_selector(sel)
        if el:
            try:
                await el.click()
                await page.wait_for_timeout(300)
                await page.keyboard.type(post_text, delay=50)
                typed = True
                logger.info(f"텍스트 입력 완료 ({sel})")
                break
            except Exception as e:
                logger.warning(f"텍스트 입력 실패 ({sel}): {e}")

    if not typed:
        logger.error("텍스트 입력 가능한 요소 없음 - 포스팅 중단")
        return None

    await page.wait_for_timeout(1000)

    # 이미지 첨부
    if image_url:
        image_path = await _download_image(image_url)
        if image_path:
            try:
                # 이미지 업로드 버튼
                file_input = await page.query_selector("input[type='file']")
                if file_input:
                    await file_input.set_input_files(image_path)
                    await page.wait_for_timeout(3000)
                else:
                    # 미디어 첨부 아이콘 클릭 후 파일 선택
                    media_btns = [
                        "[aria-label='이미지 추가']",
                        "[aria-label='Add image']",
                        "button:has-text('사진')",
                    ]
                    for mb in media_btns:
                        try:
                            async with page.expect_file_chooser() as fc_info:
                                await page.click(mb)
                            fc = await fc_info.value
                            await fc.set_files(image_path)
                            break
                        except Exception:
                            continue
                    await page.wait_for_timeout(3000)
            except Exception as e:
                logger.warning(f"이미지 첨부 실패: {e}")
            finally:
                try:
                    os.unlink(image_path)
                except Exception:
                    pass

    # 게시 버튼 클릭 - 모달 안의 버튼을 정확히 타겟
    # 배경 피드에도 "게시" 버튼이 있어서 :has-text 쓰면 첫 번째(배경) 버튼이 선택됨
    # get_by_role + exact=True + .last 로 모달의 게시 버튼만 클릭
    clicked = False
    try:
        post_btn = page.get_by_role("button", name="게시", exact=True)
        count = await post_btn.count()
        if count > 0:
            await post_btn.last.click()
            clicked = True
            logger.info(f"게시 버튼 클릭 (발견 {count}개 중 마지막)")
    except Exception as e:
        logger.warning(f"get_by_role 게시 버튼 실패: {e}")

    if not clicked:
        try:
            post_btn = page.get_by_role("button", name="Post", exact=True)
            count = await post_btn.count()
            if count > 0:
                await post_btn.last.click()
                clicked = True
                logger.info("Post 버튼 클릭")
        except Exception as e:
            logger.warning(f"Post 버튼 실패: {e}")

    if not clicked:
        logger.error("게시 버튼을 찾지 못했습니다")
        return None

    # 게시 완료 토스트 대기 후 URL 추출
    post_url = None
    try:
        # "게시되었습니다" 토스트의 "보기" 버튼 클릭 → 포스트 URL 이동
        view_btn = page.get_by_role("button", name="보기", exact=True)
        await view_btn.wait_for(timeout=5000)
        await view_btn.click()
        await page.wait_for_timeout(3000)
        if "/post/" in page.url:
            post_url = page.url
            logger.info(f"포스트 URL: {post_url}")
        else:
            logger.info(f"게시 후 URL: {page.url}")
    except Exception:
        # 토스트 없으면 프로필에서 최신 포스트 URL 추출
        try:
            await page.goto(f"{THREADS_URL}/@{THREADS_USERNAME}", timeout=20000)
            await page.wait_for_timeout(2000)
            link = await page.query_selector("a[href*='/post/']")
            if link:
                href = await link.get_attribute("href")
                post_url = f"{THREADS_URL}{href}"
                logger.info(f"프로필에서 URL 추출: {post_url}")
        except Exception as e2:
            logger.warning(f"URL 추출 실패: {e2}")

    logger.info("게시글 업로드 완료")
    return post_url


async def add_comment(page: Page, post_url: str | None, comment_text: str):
    """게시글에 댓글 추가"""
    if not post_url:
        logger.warning("포스트 URL 없음 - 최신 게시글에 댓글 시도")
        # 프로필 → 최신 게시글로 이동
        await page.goto(f"{THREADS_URL}/@{THREADS_USERNAME}", timeout=30000)
        await page.wait_for_timeout(2000)
        first_post = await page.query_selector("a[href*='/post/']")
        if first_post:
            href = await first_post.get_attribute("href")
            post_url = f"{THREADS_URL}{href}"
        else:
            logger.error("댓글 달 게시글을 찾지 못했습니다")
            return

    await page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    # 포스트 페이지의 댓글 입력창
    # 포스트 페이지에서 div[role='textbox']는 하단 답글 입력창을 가리킴
    reply_el = await page.query_selector("div[role='textbox']")
    if not reply_el:
        reply_el = await page.query_selector("[contenteditable='true']")

    if not reply_el:
        logger.warning("댓글 입력창을 찾지 못했습니다")
        return

    await reply_el.click()
    await page.wait_for_timeout(500)

    # 줄바꿈은 Shift+Enter, 마지막 줄 입력 후 Enter로 제출
    # (Threads 댓글창에서 Enter = 즉시 제출, Shift+Enter = 줄바꿈)
    lines = comment_text.split("\n")
    for i, line in enumerate(lines):
        if line:
            await page.keyboard.type(line, delay=30)
        if i < len(lines) - 1:
            await page.keyboard.press("Shift+Enter")
            await page.wait_for_timeout(100)

    await page.wait_for_timeout(1000)

    # Enter 키로 댓글 제출 (버튼 클릭보다 안정적)
    await page.keyboard.press("Enter")
    logger.info("댓글 Enter 제출")

    await page.wait_for_timeout(3000)
    logger.info("댓글 작성 완료")


async def post_all_products(contents: list[dict]) -> list[str]:
    """
    여러 상품을 하나의 브라우저 세션으로 포스팅 (로그인 1회)
    상품당 2개 게시글: 글1(자연스러운 추천) → 글2(링크)
    반환: 성공적으로 포스팅된 상품의 product_url 목록
    """
    posted_urls: list[str] = []

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

        try:
            page = await login(context)

            for i, content in enumerate(contents, 1):
                post_text_1 = content["post_text_1"]
                post_text_2 = content.get("post_text_2", "")
                image_url = content.get("image_url") or content["product"].get("image_url")
                name = content["product"].get("name", "")[:40]
                product_url = content["product"].get("product_url", "")

                logger.info(f"[{i}/{len(contents)}] 포스팅: {name}")
                try:
                    # 글1: 자연스러운 추천 (이미지 포함)
                    await post_thread(page, post_text_1, image_url)
                    logger.info(f"  글1 완료")

                    # 글2: 링크 (이미지 없음, 짧은 간격 후)
                    if post_text_2:
                        await asyncio.sleep(8)
                        await post_thread(page, post_text_2, None)
                        logger.info(f"  글2(링크) 완료")

                    logger.info(f"[{i}/{len(contents)}] 완료")
                    posted_urls.append(product_url)

                    if i < len(contents):
                        logger.info("다음 상품까지 60초 대기...")
                        await asyncio.sleep(60)
                except Exception as e:
                    logger.error(f"[{i}] 포스팅 실패: {e}")

        finally:
            await browser.close()

    return posted_urls


async def post_product(content: dict):
    """단일 상품 포스팅 (하위 호환용)"""
    await post_all_products([content])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # 테스트용
    test_content = {
        "post_text": "🔥 역대최저가 떴다!\n갤럭시 버즈3 Pro 46% 할인\n12만원 아낄 수 있는 기회!\n#쿠팡핫딜 #역대최저가 #갤럭시버즈",
        "comment_text": "🛒 구매 링크\n👇 46% 할인 (139,000원)\nhttps://www.coupang.com/test",
        "product": {
            "name": "삼성 갤럭시 버즈3 Pro",
            "image_url": None,
        },
    }
    asyncio.run(post_product(test_content))
