"""
쓰레드 피드 페이지 생성기
실행: python generate_feed_page.py
출력: docs/feed.html  → GitHub Pages 호스팅용
데이터: data/feed_posts.json
"""
import json
import os
import sys
from datetime import datetime

sys.path.append(os.path.dirname(__file__))
from config import COUPANG_PARTNERS_ACTIVE

FEED_PATH   = os.path.join(os.path.dirname(__file__), "data", "feed_posts.json")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "docs", "feed.html")


def load_posts() -> list[dict]:
    if not os.path.exists(FEED_PATH):
        return []
    with open(FEED_PATH, encoding="utf-8") as f:
        return json.load(f)


def _fmt_date(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%m/%d %H:%M")
    except Exception:
        return ts[:10]


def _status_badge(status: str) -> str:
    if status == "posted":
        return '<span class="status posted">게시됨</span>'
    return '<span class="status generated">생성됨</span>'


def _load_removed_codes() -> set[str]:
    """registry에서 removed=True 표시된 product_code 집합 반환."""
    reg_path = os.path.join(os.path.dirname(__file__), "data", "product_registry.json")
    if not os.path.exists(reg_path):
        return set()
    try:
        reg = json.load(open(reg_path, encoding="utf-8"))
        return {
            (p.get("code") or "").zfill(3)
            for p in reg.get("products", {}).values()
            if p.get("removed") and p.get("code")
        }
    except Exception:
        return set()


def build_cards(posts: list[dict]) -> str:
    if not posts:
        return '<div class="empty">아직 게시된 포스팅이 없습니다<br><span class="empty-sub">파이프라인이 실행되면 여기에 표시됩니다</span></div>'

    removed = _load_removed_codes()
    html = ""
    for p in posts:
        code     = p.get("product_code", "?")
        if code in removed:
            continue
        name     = p.get("product_name", "")
        img      = p.get("product_image", "")
        url      = p.get("product_url", "#")
        text     = p.get("post_text", "").replace("\n", "<br>")
        ts       = _fmt_date(p.get("timestamp", ""))
        status   = p.get("status", "generated")
        threads_url = p.get("threads_url")

        img_html = (
            f'<img src="{img}" alt="{name}" loading="lazy">'
            if img else ""
        )
        threads_link = (
            f'<a class="threads-link" href="{threads_url}" target="_blank" rel="noopener">Threads 원본 →</a>'
            if threads_url else ""
        )
        product_link = (
            f'<a class="product-link" href="{url}" target="_blank" rel="noopener">쿠팡 상품 →</a>'
            if url != "#" else ""
        )

        html += f"""
  <article class="post-card">
    <div class="card-meta">
      <span class="code-badge">[{code}]</span>
      {_status_badge(status)}
      <span class="ts">{ts}</span>
    </div>
    <div class="card-inner">
      <div class="avatar-col">
        <div class="avatar">🍯</div>
        <div class="thread-line"></div>
      </div>
      <div class="card-body">
        <div class="user-row">
          <span class="username">kkul.pick</span>
        </div>
        <div class="post-text">{text}</div>
        {f'<div class="img-wrap">{img_html}</div>' if img_html else ''}
        <div class="card-links">
          {threads_link}
          {product_link}
        </div>
      </div>
    </div>
  </article>"""
    return html


def build_html(posts: list[dict]) -> str:
    cards = build_cards(posts)
    n_posted    = sum(1 for p in posts if p.get("status") == "posted")
    n_generated = sum(1 for p in posts if p.get("status") == "generated")
    total       = len(posts)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    if COUPANG_PARTNERS_ACTIVE:
        disclosure = "이 포스팅은 쿠팡파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
    else:
        disclosure = "이 페이지에 포함된 링크는 향후 쿠팡파트너스 활동의 일환으로 수수료가 발생할 수 있습니다."

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>피드</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg:      #0d0d0d;
    --surface: #181818;
    --surface2: #222;
    --border:  #2c2c2c;
    --accent:  #FF6B35;
    --accent2: #FFD166;
    --text:    #f0f0f0;
    --text2:   #777;
    --green:   #50DC78;
    --radius:  16px;
  }}
  body {{
    font-family: -apple-system, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
  }}

  /* ── 헤더 ── */
  header {{
    background: rgba(13,13,13,0.95);
    backdrop-filter: blur(20px);
    border-bottom: 1px solid var(--border);
    padding: 16px;
    position: sticky; top: 0; z-index: 100;
    max-width: 640px;
    margin: 0 auto;
  }}
  .header-row {{
    display: flex;
    align-items: center;
    justify-content: space-between;
  }}
  .logo {{
    font-size: 1.5rem;
    font-weight: 900;
    letter-spacing: -0.5px;
  }}
  .logo .accent {{ color: var(--accent); }}
  .logo .sub {{ font-size: 0.8rem; color: var(--text2); font-weight: 400; margin-left: 6px; }}
  .nav-btn {{
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 10px;
    color: var(--text2);
    font-size: 0.72rem;
    font-weight: 600;
    padding: 7px 12px;
    cursor: pointer;
    text-decoration: none;
    transition: all .15s;
    white-space: nowrap;
  }}
  .nav-btn:hover {{ border-color: var(--accent); color: var(--accent); }}

  /* ── 스탯 바 ── */
  .stat-bar {{
    max-width: 640px;
    margin: 0 auto;
    padding: 12px 16px 0;
    display: flex;
    gap: 12px;
    align-items: center;
  }}
  .stat-chip {{
    font-size: 0.72rem;
    padding: 4px 10px;
    border-radius: 20px;
    font-weight: 600;
  }}
  .stat-chip.total   {{ background: var(--surface2); color: var(--text2); }}
  .stat-chip.posted  {{ background: rgba(80,220,120,0.1); color: var(--green); border: 1px solid rgba(80,220,120,0.2); }}
  .stat-chip.pending {{ background: rgba(255,209,102,0.1); color: var(--accent2); border: 1px solid rgba(255,209,102,0.2); }}
  .stat-updated {{ margin-left: auto; font-size: 0.65rem; color: #444; }}

  /* ── 피드 ── */
  .feed {{
    max-width: 640px;
    margin: 0 auto;
    padding: 16px 16px 48px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }}

  /* ── 포스트 카드 ── */
  .post-card {{
    padding: 14px 0 10px;
    border-bottom: 1px solid #1c1c1c;
  }}
  .card-meta {{
    display: flex;
    align-items: center;
    gap: 7px;
    margin-bottom: 10px;
    padding-left: 4px;
  }}
  .code-badge {{
    font-size: 0.68rem;
    font-weight: 700;
    background: rgba(255,107,53,0.12);
    color: var(--accent);
    padding: 2px 8px;
    border-radius: 20px;
    border: 1px solid rgba(255,107,53,0.2);
  }}
  .status {{
    font-size: 0.65rem;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 20px;
    letter-spacing: 0.04em;
  }}
  .status.posted    {{ background: rgba(80,220,120,0.1);  color: var(--green);  border: 1px solid rgba(80,220,120,0.2); }}
  .status.generated {{ background: rgba(255,209,102,0.1); color: var(--accent2); border: 1px solid rgba(255,209,102,0.2); }}
  .ts {{ margin-left: auto; font-size: 0.65rem; color: #444; }}

  .card-inner {{
    display: flex;
    gap: 12px;
  }}
  .avatar-col {{
    display: flex;
    flex-direction: column;
    align-items: center;
    flex-shrink: 0;
  }}
  .avatar {{
    width: 40px; height: 40px;
    border-radius: 50%;
    background: linear-gradient(135deg, #f8c93a, #f5a623);
    display: flex; align-items: center; justify-content: center;
    font-size: 18px;
    flex-shrink: 0;
  }}
  .thread-line {{
    width: 2px;
    background: #1e1e1e;
    flex: 1;
    min-height: 12px;
    margin-top: 6px;
  }}
  .card-body {{ flex: 1; min-width: 0; }}
  .user-row {{
    display: flex; align-items: center; gap: 6px;
    margin-bottom: 7px;
  }}
  .username {{ font-size: 0.88rem; font-weight: 700; }}
  .post-text {{
    font-size: 0.9rem;
    line-height: 1.6;
    color: #d8d8d8;
    margin-bottom: 10px;
    white-space: pre-wrap;
    word-break: break-word;
  }}
  .img-wrap {{
    border-radius: 12px;
    overflow: hidden;
    margin-bottom: 10px;
    max-height: 280px;
  }}
  .img-wrap img {{
    width: 100%;
    height: 240px;
    object-fit: cover;
    display: block;
  }}
  .card-links {{
    display: flex; gap: 8px; flex-wrap: wrap;
  }}
  .threads-link, .product-link {{
    font-size: 0.72rem;
    font-weight: 600;
    padding: 5px 12px;
    border-radius: 8px;
    text-decoration: none;
    transition: opacity .15s;
  }}
  .threads-link {{
    background: rgba(255,107,53,0.1);
    color: var(--accent);
    border: 1px solid rgba(255,107,53,0.2);
  }}
  .product-link {{
    background: var(--surface2);
    color: var(--text2);
    border: 1px solid var(--border);
  }}
  .threads-link:hover, .product-link:hover {{ opacity: 0.7; }}

  .empty {{
    text-align: center;
    padding: 60px 20px;
    color: var(--text2);
    font-size: 0.9rem;
    line-height: 2;
  }}
  .empty-sub {{ font-size: 0.78rem; color: #444; }}

  /* ── 푸터 ── */
  footer {{
    max-width: 640px;
    margin: 0 auto;
    padding: 0 16px 48px;
  }}
  .disclosure-box {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 12px 16px;
    margin-bottom: 12px;
  }}
  .disclosure-title {{
    font-size: 0.66rem; font-weight: 700;
    color: #555; letter-spacing: 0.06em;
    text-transform: uppercase; margin-bottom: 4px;
  }}
  .disclosure-text {{ font-size: 0.69rem; color: var(--text2); line-height: 1.6; }}
  .footer-copy {{ font-size: 0.64rem; color: #333; text-align: center; }}
</style>
</head>
<body>

<header>
  <div class="header-row">
    <div class="logo"></div>
    <a class="nav-btn" href="index.html">상품 목록 →</a>
  </div>
</header>

<div class="stat-bar">
  <span class="stat-chip total">전체 {total}개</span>
  <span class="stat-chip posted">게시됨 {n_posted}</span>
  <span class="stat-chip pending">생성됨 {n_generated}</span>
  <span class="stat-updated">업데이트: {generated_at}</span>
</div>

<div class="feed">
{cards}
</div>

<footer>
  <div class="disclosure-box">
    <div class="disclosure-title">안내</div>
    <div class="disclosure-text">{disclosure}</div>
  </div>
  <div class="footer-copy"></div>
</footer>

</body>
</html>"""


def main():
    posts = load_posts()
    html  = build_html(posts)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"피드 페이지 생성: {OUTPUT_PATH}")
    print(f"포스팅 {len(posts)}개")


if __name__ == "__main__":
    main()
