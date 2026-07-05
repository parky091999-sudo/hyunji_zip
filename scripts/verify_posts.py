"""
Threads 게시 검증 + 포스팅 무결성 재점검.

1. feed_posts.json ↔ Threads API 매칭 (살아있는 글, 누락 글, 댓글 누락)
2. 무결성 체크: short_name 이상, post_text 잘림 감지 → registry 자동 수정
3. 운영 체크: 오늘 포스팅 여부 / 이미지 누락 / 페이지 미반영 / AI 이미지 경고
"""
import io
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import DATA_DIR
from poster.threads import _api, fetch_my_posts, THREADS_ACCESS_TOKEN, THREADS_USER_ID

FEED_POSTS_PATH    = os.path.join(DATA_DIR, "feed_posts.json")
REPLIED_PATH       = os.path.join(DATA_DIR, "replied_comments.json")
REGISTRY_PATH      = os.path.join(DATA_DIR, "product_registry.json")
INDEX_HTML_PATH    = os.path.join(ROOT, "docs", "index.html")

KST = timezone(timedelta(hours=9))
_AI_IMAGE_DOMAINS  = ("i.ibb.co", "ibb.co", "imgbb.com")

_FOOTER_RE = re.compile(r'\n\n제품 정보는 프로필 링크에서 \[\d{3}\] 검색 👆\s*$')
_SENTENCE_END_RE = re.compile(r'[다요임어야겠네봄않함봐!?~\).♥]$')


def _shortcode(url: str) -> str:
    return url.rstrip("/").split("/post/")[-1] if url and "/post/" in url else ""


def _is_truncated(text: str) -> bool:
    """post_text 잘림 휴리스틱: 푸터 제거 후 마지막 단락이 문장으로 끝나는지."""
    body = _FOOTER_RE.sub("", text or "").strip()
    if not body:
        return False
    last_para = body.split('\n\n')[-1].strip()
    last_line = last_para.split('\n')[-1].strip()
    # 해시태그·체크마크·URL 종결 패턴(spec=숫자 등)으로 끝나면 완성된 것
    if last_line.startswith('#') or last_line.startswith('✔') or last_line.startswith('•'):
        return False
    if re.search(r'(spec|itemId|vendorItemId|pageKey|ctag|lptag)=\d+\s*$', last_line):
        return False
    return not bool(_SENTENCE_END_RE.search(last_line))


def _fallback_short_name(name: str) -> str:
    """규칙 기반 short_name 생성 (AI 없이)"""
    cleaned = re.sub(r"[\(\[].*?[\)\]]", " ", name or "")
    cleaned = re.sub(r"\d+_\([^\)]+\)", " ", cleaned)
    cleaned = re.sub(r"[\(\)\[\]\{\}/\\,~·+]", " ", cleaned)
    tokens = [t for t in cleaned.split() if t and not re.match(r"^[A-Z0-9\-]+\d", t)]
    tokens = [t for t in tokens if not re.fullmatch(r"(\d+[가-힣]?|\d+개|\d+ml|\d+g|\d+L)", t, re.I)]
    result = " ".join(tokens[:4]).strip()
    while len(result) > 30 and len(result.split()) > 1:
        result = " ".join(result.split()[:-1]).strip()
    return result


# ─────────────────────────────────────────────────────────────
# 섹션 1: 무결성 체크 + registry 자동 수정
# ─────────────────────────────────────────────────────────────

def run_integrity_check(feed: list[dict]) -> bool:
    """
    1. product_registry의 short_name 이상값 자동 수정
    2. feed_posts의 post_text 잘림 경고
    반환: registry 수정 여부
    """
    print("\n" + "=" * 70, flush=True)
    print("무결성 재점검", flush=True)
    print("=" * 70, flush=True)

    # ── 1. registry short_name 체크 ──────────────────────────────────────
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        reg = json.load(f)

    fixes = []
    for v in reg["products"].values():
        if not v.get("posted") or v.get("removed"):
            continue
        code = v["code"]
        short_name = v.get("short_name", "")
        name = v.get("name", "")

        if len(short_name) < 2 or short_name[-1] in ("의", "와", "과", "에", "로", "+", "-", "_", "/"):
            new_sn = _fallback_short_name(name)
            v["short_name"] = new_sn
            fixes.append(f"  [{code}] short_name 수정: {short_name!r} → {new_sn!r}")

    if fixes:
        with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=2)
        print(f"\n[short_name 자동 수정] {len(fixes)}건:", flush=True)
        for msg in fixes:
            print(msg, flush=True)
    else:
        print("\n[short_name] 이상 없음", flush=True)

    # ── 2. post_text 잘림 체크 ────────────────────────────────────────────
    truncated = []
    for p in feed:
        if p.get("status") != "posted":
            continue
        text = p.get("post_text", "")
        if text and _is_truncated(text):
            code = p.get("product_code", "?")
            preview = text.replace('\n', ' ')[-50:]
            truncated.append(f"  [{code}] ...{preview}")

    if truncated:
        print(f"\n[post_text 잘림 의심] {len(truncated)}건:", flush=True)
        for msg in truncated:
            print(msg, flush=True)
        print("  → 앱에서 직접 수정 필요 (Threads API 편집 미지원)", flush=True)
    else:
        print("[post_text] 잘림 이상 없음", flush=True)

    return bool(fixes)


# ─────────────────────────────────────────────────────────────
# 섹션 2: Threads API ↔ feed 매칭 검증
# ─────────────────────────────────────────────────────────────

def run_threads_verify(feed: list[dict]) -> None:
    if not THREADS_ACCESS_TOKEN or not THREADS_USER_ID:
        print("THREADS_ACCESS_TOKEN/USER_ID 없음 — Threads 검증 생략", flush=True)
        return

    print("\n" + "=" * 70, flush=True)
    print("Threads 실제 게시 검증", flush=True)
    print("=" * 70, flush=True)

    my_posts = fetch_my_posts(limit=100)
    print(f"\nThreads API: {len(my_posts)}개 게시글 반환", flush=True)

    api_by_sc = {}
    for p in my_posts:
        sc = _shortcode(p.get("permalink", ""))
        if sc:
            api_by_sc[sc] = p

    posted = [p for p in feed if p.get("status") == "posted"]
    print(f"feed_posts(status=posted): {len(posted)}건", flush=True)

    feed_by_sc = {}
    feed_no_url = []
    for f in posted:
        sc = _shortcode(f.get("threads_url", ""))
        if sc:
            feed_by_sc[sc] = f
        else:
            feed_no_url.append(f)

    matched  = set(feed_by_sc) & set(api_by_sc)
    feed_only = set(feed_by_sc) - set(api_by_sc)
    api_only  = set(api_by_sc) - set(feed_by_sc)

    print(f"\n[매칭] feed↔API 매칭: {len(matched)}건", flush=True)
    print(f"[누락] feed에 있고 API에 없음: {len(feed_only)}건", flush=True)
    print(f"[추가] API에만 있고 feed에 없음: {len(api_only)}건", flush=True)
    print(f"[URL없음] threads_url 비어있음: {len(feed_no_url)}건", flush=True)

    if feed_only:
        print("\n--- 누락 글 (feed엔 있는데 Threads엔 없음) ---", flush=True)
        for sc in sorted(feed_only):
            f = feed_by_sc[sc]
            print(f"  [{f.get('product_code','?'):>4}] {sc}  {f.get('timestamp','')[:16]}  {f.get('product_name','')[:35]}", flush=True)

    if api_only:
        print("\n--- 추가 글 (Threads엔 있는데 feed엔 없음) ---", flush=True)
        for sc in sorted(api_only):
            p = api_by_sc[sc]
            text = (p.get('text') or '')[:60].replace('\n', ' ')
            print(f"  {sc}  {text}", flush=True)

    # 댓글 검증
    print("\n" + "=" * 70, flush=True)
    print("댓글(reply) 검증", flush=True)
    print("=" * 70, flush=True)

    if os.path.exists(REPLIED_PATH):
        replied = json.load(open(REPLIED_PATH, encoding="utf-8"))
        replied_set = set(replied) if isinstance(replied, list) else set(replied.keys())
        print(f"replied_comments: {len(replied_set)}개 기록", flush=True)
    else:
        replied_set = set()
        print("replied_comments.json 없음", flush=True)

    targets = [
        f for f in posted
        if f.get("product_code") and f.get("product_code") != "preview"
        and f.get("threads_url")
    ]
    print(f"댓글 대상(코드+URL 있음): {len(targets)}건", flush=True)

    no_comment = []
    for f in targets:
        sc = _shortcode(f.get("threads_url", ""))
        if not sc:
            continue
        api_id = api_by_sc.get(sc, {}).get("id", "")
        if api_id and api_id not in replied_set:
            no_comment.append((f, sc, api_id))

    print(f"\n댓글 누락(replied 기록 없음): {len(no_comment)}건", flush=True)
    for f, sc, api_id in no_comment:
        print(f"  [{f.get('product_code','?'):>4}] {sc}  api_id={api_id}  {f.get('product_name','')[:30]}", flush=True)

    # 최근 20개 reply 수
    print("\n" + "=" * 70, flush=True)
    print("최근 글 reply 수 (살아있는 글 최신 20개)", flush=True)
    print("=" * 70, flush=True)
    for sc in sorted(matched, key=lambda s: feed_by_sc[s].get('timestamp', ''), reverse=True)[:20]:
        f = feed_by_sc[sc]
        api_id = api_by_sc[sc].get("id", "")
        try:
            data = _api("GET", f"/{api_id}/replies", params={
                "fields": "id,text",
                "access_token": THREADS_ACCESS_TOKEN,
            })
            replies = data.get("data", [])
            sample = (replies[0].get("text") or "")[:40].replace('\n', ' ') if replies else ""
            print(f"  [{f.get('product_code','?'):>4}] {sc}  reply수={len(replies)}  샘플: {sample}", flush=True)
        except Exception as e:
            print(f"  [{f.get('product_code','?'):>4}] {sc}  조회실패: {e}", flush=True)


# ─────────────────────────────────────────────────────────────
# 섹션 3: 운영 체크 (포스팅 누락 / 이미지 / 페이지 반영 / AI 이미지)
# ─────────────────────────────────────────────────────────────

def run_operational_check(feed: list[dict]) -> None:
    """
    1. 오늘 상품 포스팅 여부 (08:05 KST auto_post 실행 확인)
    2. registry 이미지 누락 (posted=true & image_url 비어있는 상품)
    3. 파트너스 페이지 미반영 (registry posted 코드 vs index.html data-code 불일치)
    4. AI 생성 이미지 사용 경고 (실제 상품과 다를 수 있음 — 수동 확인 필요)
    """
    print("\n" + "=" * 70, flush=True)
    print("운영 체크", flush=True)
    print("=" * 70, flush=True)

    today_kst = datetime.now(KST).strftime("%Y-%m-%d")

    # ── 1. 오늘 상품 포스팅 여부 ────────────────────────────────────────────
    product_posts_today = [
        p for p in feed
        if p.get("status") == "posted"
        and p.get("product_code") not in ("", "preview")
        and p.get("post_type") not in ("casual",)
        and p.get("timestamp", "")[:10] == today_kst
    ]
    if product_posts_today:
        print(f"\n[오늘 포스팅] {len(product_posts_today)}건 완료", flush=True)
        for p in product_posts_today:
            print(f"  [{p['product_code']}] {p.get('product_name','')[:30]}  {p['timestamp'][11:16]}", flush=True)
    else:
        print(f"\n[오늘 포스팅] 경고 — {today_kst} 상품 포스팅 없음 (auto_post 미실행 또는 실패 의심)", flush=True)

    # ── 2. registry 이미지 누락 ──────────────────────────────────────────────
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        reg = json.load(f)

    no_image = [
        v for v in reg["products"].values()
        if v.get("posted") and not v.get("removed") and not v.get("image_url", "")
    ]
    if no_image:
        print(f"\n[이미지 누락] {len(no_image)}건 — 파트너스 페이지에 이미지 없이 노출됨:", flush=True)
        for v in no_image:
            print(f"  [{v['code']}] {v.get('name','')[:40]}", flush=True)
        print("  → add_product.py 재실행 또는 image_url 수동 입력 필요", flush=True)
    else:
        print("\n[이미지 누락] 이상 없음", flush=True)

    # ── 2b. 미검증 이미지 (이름 검색으로 보충 — 실제 상품과 다를 수 있음) ──────
    unverified = [
        v for v in reg["products"].values()
        if v.get("posted") and not v.get("removed")
        and v.get("image_url") and v.get("image_verified") is False
    ]
    if unverified:
        print(f"\n[이미지 미검증] {len(unverified)}건 — 상품명 검색으로 보충된 이미지, 실제 상품 일치 확인 필요:", flush=True)
        for v in unverified:
            print(f"  [{v['code']}] {v.get('name','')[:40]}", flush=True)
            print(f"         {v.get('image_url','')[:80]}", flush=True)
        print("  → 확인 후 image_verified: true 업데이트 또는 올바른 이미지로 교체 필요", flush=True)
    else:
        print("\n[이미지 검증] 미검증 이미지 없음", flush=True)

    # ── 3. 파트너스 페이지 미반영 ────────────────────────────────────────────
    registry_codes = {
        v["code"] for v in reg["products"].values()
        if v.get("posted") and not v.get("removed")
    }
    if os.path.exists(INDEX_HTML_PATH):
        with open(INDEX_HTML_PATH, encoding="utf-8") as f:
            html = f.read()
        html_codes = set(re.findall(r'data-code="(\d{3})"', html))
        missing_from_html = registry_codes - html_codes
        extra_in_html     = html_codes - registry_codes
        if missing_from_html:
            print(f"\n[페이지 미반영] {len(missing_from_html)}개 코드 index.html에 없음:", flush=True)
            for c in sorted(missing_from_html):
                v = next((x for x in reg["products"].values() if x["code"] == c), {})
                print(f"  [{c}] {v.get('name','')[:40]}", flush=True)
            print("  → python generate_page.py 실행 필요", flush=True)
        else:
            print("\n[페이지 반영] 이상 없음", flush=True)
        if extra_in_html:
            print(f"\n[페이지 초과] index.html에만 있고 registry에 없는 코드: {sorted(extra_in_html)}", flush=True)
    else:
        print("\n[페이지 미반영] index.html 없음 — generate_page.py 실행 필요", flush=True)

    # ── 4. AI 생성 이미지 사용 경고 ─────────────────────────────────────────
    ai_image_posts = []
    for p in feed:
        if p.get("status") != "posted" or p.get("product_code") in ("", "preview"):
            continue
        detail_imgs = p.get("detail_images") or []
        ai_imgs = [u for u in detail_imgs if any(d in u for d in _AI_IMAGE_DOMAINS)]
        if ai_imgs:
            ai_image_posts.append((p.get("product_code", "?"), p.get("product_name", "")[:30], ai_imgs))

    if ai_image_posts:
        print(f"\n[AI 이미지 경고] {len(ai_image_posts)}개 포스팅에 AI 생성 이미지 사용 — 실제 상품과 다를 수 있음, 수동 확인 필요:", flush=True)
        for code, name, imgs in ai_image_posts:
            print(f"  [{code}] {name}", flush=True)
            for u in imgs:
                print(f"         {u[:80]}", flush=True)
    else:
        print("\n[AI 이미지] 경고 대상 없음", flush=True)


def main() -> None:
    feed = json.load(open(FEED_POSTS_PATH, encoding="utf-8"))

    registry_fixed = run_integrity_check(feed)
    run_operational_check(feed)
    run_threads_verify(feed)

    # CI에서 수정된 경우 exit code 2로 알림 (commit 필요)
    if registry_fixed:
        sys.exit(2)


if __name__ == "__main__":
    main()
