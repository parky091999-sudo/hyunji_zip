"""
벤치마킹 계정 스크래퍼
매 실행마다 benchmark_accounts.json에서 ACCOUNTS_PER_RUN개 랜덤 선택
→ Threads 프로필 페이지 파싱 → Groq로 상품명 추출 → 네이버 쇼핑 매칭
→ priority_queue.json에 추가 (priority=2)

제약: Threads 공식 API는 타 계정 게시글 조회 미지원
      → 프로필 웹페이지(Next.js __NEXT_DATA__ JSON) 파싱으로 대체
      실패 시 로그만 남기고 건너뜀 (graceful skip)
"""
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import DATA_DIR, GROQ_API_KEY, NAVER_CLIENT_ID, NAVER_CLIENT_SECRET

logger = logging.getLogger(__name__)

ACCOUNTS_PATH = os.path.join(DATA_DIR, "benchmark_accounts.json")
QUEUE_PATH    = os.path.join(DATA_DIR, "priority_queue.json")

ACCOUNTS_PER_RUN       = 4  # 매 실행마다 랜덤 선택 계정 수
MAX_POSTS_PER_ACCOUNT  = 5  # 계정당 최대 게시글 수
MAX_PRODUCTS_TO_ADD    = 3  # 이번 실행에서 큐에 추가할 최대 상품 수
REQUEST_DELAY_SEC      = 2  # 계정 간 요청 간격 (레이트 리밋 방지)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.threads.net/",
}


# ── 파일 I/O ────────────────────────────────────────────────────────────────

def _load_accounts() -> list:
    if not os.path.exists(ACCOUNTS_PATH):
        return []
    with open(ACCOUNTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _load_queue() -> list:
    if not os.path.exists(QUEUE_PATH):
        return []
    with open(QUEUE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_queue(queue: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


# ── Threads 프로필 파싱 ──────────────────────────────────────────────────────

def _fetch_posts(username: str) -> list[str]:
    """
    Threads 프로필 페이지에서 게시글 텍스트 추출.
    Next.js __NEXT_DATA__ JSON 파싱 → 텍스트 필드 재귀 탐색.
    실패 시 빈 리스트 반환.
    """
    url = f"https://www.threads.net/@{username}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        if resp.status_code != 200:
            logger.debug(f"  @{username}: HTTP {resp.status_code}")
            return []
        html = resp.text

        # ① __NEXT_DATA__ JSON 블록 파싱 (Next.js SSR 데이터)
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m:
            try:
                data  = json.loads(m.group(1))
                texts = _walk_for_texts(data)
                if texts:
                    return texts[:MAX_POSTS_PER_ACCOUNT]
            except (json.JSONDecodeError, ValueError):
                pass

        # ② og:description (프로필 설명이라도 활용)
        og = re.findall(r'<meta\s+property="og:description"\s+content="([^"]{10,})"', html)
        if og:
            return og[:1]

        logger.info(f"  @{username}: 게시글 파싱 실패 (Threads JS 렌더링 필요)")
        return []
    except requests.RequestException as e:
        logger.warning(f"  @{username}: 요청 오류 — {e}")
        return []


def _walk_for_texts(obj, depth: int = 0) -> list[str]:
    """JSON 트리를 재귀 탐색해 게시글 텍스트 필드 수집"""
    if depth > 15:
        return []
    texts: list[str] = []
    TEXT_KEYS = {"text_post_app_text", "caption", "text", "body", "content"}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in TEXT_KEYS and isinstance(v, str) and len(v) > 10:
                texts.append(v)
            else:
                texts.extend(_walk_for_texts(v, depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            texts.extend(_walk_for_texts(item, depth + 1))
    return texts


# ── AI 상품명 추출 ────────────────────────────────────────────────────────────

def _extract_product_names(texts: list[str], account: str) -> list[str]:
    """Groq LLM으로 게시글 텍스트에서 상품명 추출"""
    if not GROQ_API_KEY or not texts:
        return []
    combined = "\n\n---\n\n".join(texts[:MAX_POSTS_PER_ACCOUNT])
    prompt = (
        f"다음은 한국 쿠팡 추천 SNS 계정(@{account})의 게시글 텍스트입니다.\n\n"
        f"{combined}\n\n"
        "위 텍스트에서 언급된 실제 상품명을 최대 3개 추출하세요.\n"
        "규칙:\n"
        "- 상품명만 한 줄에 하나씩 출력\n"
        "- 설명, 번호, 기호 없이 상품명만\n"
        "- 상품이 없거나 모르면 아무것도 출력하지 마세요"
    )
    try:
        import httpx
        resp = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization":  f"Bearer {GROQ_API_KEY}",
                "Content-Type":   "application/json",
            },
            json={
                "model":       "llama-3.3-70b-versatile",
                "messages":    [{"role": "user", "content": prompt}],
                "max_tokens":  200,
                "temperature": 0.1,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        names = [
            line.strip() for line in content.splitlines()
            if line.strip() and len(line.strip()) > 2
        ]
        return names[:3]
    except Exception as e:
        logger.warning(f"  Groq 상품명 추출 오류: {e}")
        return []


# ── 네이버 쇼핑 매칭 ─────────────────────────────────────────────────────────

def _search_naver(query: str) -> dict | None:
    if not NAVER_CLIENT_ID:
        return None
    headers = {
        "X-Naver-Client-Id":     NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {"query": query, "display": 5, "sort": "sim"}
    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/shop.json",
            headers=headers, params=params, timeout=10,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            return None
        item = items[0]
        name = re.sub(r"<[^>]+>", "", item.get("title", query)).strip()
        lp   = int(item.get("lprice", 0) or 0)
        return {
            "name":        name,
            "price":       f"{lp:,}원" if lp else "",
            "image_url":   item.get("image", ""),
            "product_url": item.get("link", ""),
            "brand":       (item.get("brand") or item.get("maker") or "").strip(),
            "source":      "benchmark",
        }
    except Exception as e:
        logger.warning(f"  네이버 검색 오류 ({query}): {e}")
        return None


# ── 메인 진입점 ───────────────────────────────────────────────────────────────

def run_benchmark() -> int:
    """
    벤치마킹 실행.
    반환값: 이번 실행에서 큐에 추가된 상품 수
    """
    accounts = [a for a in _load_accounts() if a.get("active", True)]
    if not accounts:
        logger.warning("벤치마킹 계정 목록이 비어 있습니다.")
        return 0

    selected = random.sample(accounts, min(ACCOUNTS_PER_RUN, len(accounts)))
    logger.info(
        f"벤치마킹 계정 {len(selected)}개 선택: "
        f"{[a['username'] for a in selected]}"
    )

    queue       = _load_queue()
    added_count = 0

    # 큐에 이미 있는 URL 집합 (중복 방지)
    queued_urls: set[str] = {
        item.get("product", {}).get("product_url", "")
        for item in queue
        if item.get("product", {}).get("product_url")
    }

    for account in selected:
        if added_count >= MAX_PRODUCTS_TO_ADD:
            break

        username = account["username"]
        logger.info(f"  계정 스캔: @{username}")

        posts = _fetch_posts(username)
        if not posts:
            time.sleep(REQUEST_DELAY_SEC)
            continue
        logger.info(f"    게시글 {len(posts)}개 파싱 완료")

        product_names = _extract_product_names(posts, username)
        if not product_names:
            logger.info(f"    상품명 추출 없음 — 건너뜀")
            time.sleep(REQUEST_DELAY_SEC)
            continue

        for pname in product_names:
            if added_count >= MAX_PRODUCTS_TO_ADD:
                break
            product = _search_naver(pname)
            if not product:
                continue
            url = product.get("product_url", "")
            if url in queued_urls:
                logger.info(f"    이미 큐에 있음: {product['name'][:35]}")
                continue

            entry = {
                "priority":           2,
                "source":             "benchmark",
                "benchmark_account":  username,
                "added_at":           datetime.now().isoformat(),
                "product":            product,
            }
            queue.append(entry)
            queued_urls.add(url)
            added_count += 1
            logger.info(f"    ✅ 큐 추가 (priority=2): {product['name'][:45]}")

        time.sleep(REQUEST_DELAY_SEC)

    if added_count > 0:
        _save_queue(queue)

    logger.info(f"벤치마킹 완료: {added_count}개 상품 큐에 추가")
    return added_count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    n = run_benchmark()
    print(f"\n벤치마킹 결과: {n}개 상품 추가됨")
