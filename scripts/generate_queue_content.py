"""
수동 포스팅 큐 AI 본문 즉시 생성
post_text가 비어있는 manual_queue 항목에 Gemini(기본)/Groq(폴백)로 본문 생성
직접 URL 등록 항목(name="쿠팡 상품 (URL 직접 등록)")은 Coupang 페이지에서
실제 상품명·이미지·가격을 먼저 스크래핑한 후 본문 생성
"""
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone, timedelta

import requests

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import DATA_DIR, LOG_DIR, GROQ_API_KEY, GOOGLE_API_KEY

QUEUE_PATH = os.path.join(DATA_DIR, "manual_queue.json")
KST = timezone(timedelta(hours=9))

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "generate_queue.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("generate_queue_content")

_POST_SYSTEM = """
너는 Threads에서 팔로워가 많은 생활용품 큐레이터야.
"써보니까 좋더라" 하면서 진짜 쓸만한 물건만 콕 집어주는 사람.
계정 컨셉: "보다가 이게 뭐야 싶은 것들"을 발견해서 소개하는 계정.

출력 형식 (반드시 이 순서, 각 블록은 빈 줄로 구분):
[훅 1줄 — 스크롤 멈추게 하는 강력한 첫 문장]
[본문 2~3줄 — 근거·사용법·상황]
[포인트 2줄 — ✔ 로 시작하는 구체적 활용팁]
[해시태그 한 줄, 4~5개]

본문 작성 규칙:
1. 첫 줄(훅)은 무조건 강하게. 공감/발견/후회/호기심 중 하나 느낌으로.
2. 추측형 절대 금지. 단정·경험·근거형으로.
3. 상품의 실제 특징·기능을 구체적으로.
4. 사회적 증거를 자연스럽게 녹여.
5. ✔ 포인트는 실제 사용 상황을 구체적으로.
6. 반말, 친근하게. 가격은 언급하지 마.
7. 이모지는 본문에 1~2개까지만.
해시태그: 첫 태그 #생활꿀템 고정, 나머지 카테고리·키워드 태그.
반드시 한국어로만. 텍스트만 출력.
""".strip()


_PLACEHOLDER_NAME = "쿠팡 상품 (URL 직접 등록)"

_SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _parse_coupang_html(html: str) -> dict:
    """쿠팡 상품 HTML에서 이름·이미지·가격 파싱"""
    # 상품명: og:title (속성 순서 두 가지) → <title>
    name = ""
    for pat in [
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
    ]:
        m = re.search(pat, html)
        if m:
            name = m.group(1).strip()
            break
    if not name:
        m = re.search(r"<title>([^<]+)</title>", html)
        if m:
            name = m.group(1).split("|")[0].split("-")[0].strip()

    # 이미지: og:image
    image_url = ""
    for pat in [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    ]:
        m = re.search(pat, html)
        if m:
            image_url = m.group(1).strip()
            break

    # 가격
    price = ""
    m = re.search(r'"price"\s*:\s*"?([\d]+)"?', html)
    if m:
        p = int(m.group(1))
        if p > 100:
            price = f"{p:,}원"

    return {"name": name, "image_url": image_url, "price": price}


_INVALID_NAMES = {"access denied", "forbidden", "error", "robot check", "robot or human?", "blocked", "429"}


def _is_valid_name(name: str) -> bool:
    return bool(name) and name.lower().strip() not in _INVALID_NAMES and len(name) > 3


def _fetch_coupang_info_playwright(url: str) -> dict:
    """Playwright로 JS 렌더링 후 상품 정보 추출 (단축 URL 등 fallback)"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page(user_agent=_SCRAPE_HEADERS["User-Agent"])
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2000)
            html = page.content()
            final_url = page.url
            browser.close()
        logger.info(f"  Playwright 최종 URL: {final_url[:80]}")
        info = _parse_coupang_html(html)
        if not _is_valid_name(info.get("name", "")):
            logger.warning(f"  Playwright 응답이 오류 페이지: '{info.get('name','')}' — 무효 처리")
            return {}
        return info
    except Exception as e:
        logger.warning(f"  Playwright 스크래핑 실패: {e}")
        return {}


def _fetch_coupang_info(url: str) -> dict:
    """Coupang 상품 URL에서 이름·이미지·가격 추출"""
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # 1차: requests (빠름)
    try:
        resp = requests.get(url, headers=_SCRAPE_HEADERS, timeout=15,
                            verify=False, allow_redirects=True)
        info = _parse_coupang_html(resp.text)
        if _is_valid_name(info.get("name", "")):
            logger.info(f"  스크래핑 완료: {info['name'][:40]} / {info.get('price','')}")
            return info
        logger.info(f"  requests로 상품명 미수집 (최종URL: {resp.url[:70]}) → Playwright 시도")
    except Exception as e:
        logger.warning(f"  requests 실패: {e} → Playwright 시도")

    # 2차: Playwright (JS 렌더링, 단축 URL용)
    info = _fetch_coupang_info_playwright(url)
    if info.get("name"):
        logger.info(f"  Playwright 완료: {info['name'][:40]} / {info.get('price','')}")
    return info


def _build_prompt(product: dict) -> str:
    name  = product.get("name", "")
    brand = product.get("brand", "")
    price = product.get("price", "")
    desc = f"상품명: {name}"
    if brand: desc += f"\n브랜드: {brand}"
    if price: desc += f"\n가격대: {price}"
    return f"{desc}\n\n위 상품에 대한 Threads 포스팅을 작성해줘."


def _generate(product: dict) -> str | None:
    prompt = _build_prompt(product)

    if GOOGLE_API_KEY:
        try:
            import google.generativeai as genai
            genai.configure(api_key=GOOGLE_API_KEY)
            model = genai.GenerativeModel(
                "gemini-2.5-flash",
                system_instruction=_POST_SYSTEM,
                generation_config=genai.types.GenerationConfig(max_output_tokens=500, temperature=0.85),
            )
            resp = model.generate_content(prompt)
            text = resp.text.strip() if resp.text else ""
            if text:
                logger.info("  [Gemini] 생성 완료")
                return text
        except Exception as e:
            logger.warning(f"  Gemini 오류 → Groq 폴백: {e}")

    if GROQ_API_KEY:
        try:
            from groq import Groq
            client = Groq(api_key=GROQ_API_KEY)
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": _POST_SYSTEM}, {"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.85,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"  Groq 생성 오류: {e}")

    return None


def run():
    logger.info("=" * 50)
    logger.info(f"큐 AI 본문 생성: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")

    if not os.path.exists(QUEUE_PATH):
        logger.info("manual_queue.json 없음 — 종료")
        return

    with open(QUEUE_PATH, encoding="utf-8") as f:
        queue = json.load(f)

    pending = [i for i, item in enumerate(queue) if not item.get("post_text", "").strip()]
    logger.info(f"본문 없는 항목: {len(pending)}개")

    if not pending:
        logger.info("생성 대상 없음")
        return

    changed = 0
    for i in pending:
        item = queue[i]
        product = item.get("product") or {}
        name = product.get("name", "")

        # URL 직접 등록 항목 — 실제 상품 정보 먼저 스크래핑
        if name == _PLACEHOLDER_NAME:
            url = product.get("product_url", "")
            if url:
                logger.info(f"  URL 직접 등록 감지 → Coupang 스크래핑: {url[:60]}")
                info = _fetch_coupang_info(url)
                if info.get("name"):
                    product.update(info)
                    queue[i]["product"] = product
                    # 최상위 image_url도 동기화
                    if info.get("image_url") and not queue[i].get("image_url"):
                        queue[i]["image_url"] = info["image_url"]
                    name = product["name"]
                else:
                    logger.warning(f"  상품명 조회 실패 — 본문 생성 건너뜀")
                    continue
            else:
                logger.warning(f"  product_url 없음 — 건너뜀")
                continue

        logger.info(f"  생성 중: {name[:40]}")
        text = _generate(product)
        if text:
            queue[i]["post_text"]      = text
            queue[i]["content_gen_at"] = datetime.now(KST).isoformat()
            changed += 1
            logger.info(f"  ✅ 완료")
        else:
            logger.warning(f"  생성 실패 — 건너뜀")

    if changed:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(QUEUE_PATH, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
        logger.info(f"저장 완료: {changed}개 본문 생성됨")
    else:
        logger.warning("생성된 본문 없음")


if __name__ == "__main__":
    run()
