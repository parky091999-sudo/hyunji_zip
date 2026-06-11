"""
상품 페이지 생성기
실행: python generate_page.py
출력: docs/index.html  → GitHub Pages 호스팅용
"""
import json
import os
import sys

sys.path.append(os.path.dirname(__file__))
from generator.registry import get_all
from config import COUPANG_PARTNERS_ACTIVE

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "docs", "index.html")
_FB_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "firebase_config.json")


def load_firebase_config() -> str:
    """firebase_config.json을 읽어 JSON 문자열로 반환. 없으면 'null' 반환."""
    try:
        with open(_FB_CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        if cfg.get("apiKey", "").startswith("여기에"):
            return "null"
        return json.dumps(cfg, ensure_ascii=False)
    except FileNotFoundError:
        return "null"

_TICKER_MSG = "이 페이지의 링크는 쿠팡파트너스 활동의 일환으로, 구매 시 일정액의 수수료를 제공받을 수 있습니다"

CATEGORIES = ["전체", "식품", "뷰티", "주방", "생활", "디지털/가전", "인테리어", "기타"]


def build_cards(products: list[dict]) -> str:
    if not products:
        return '<div class="empty">아직 등록된 상품이 없습니다</div>'

    sorted_products = sorted(products, key=lambda x: int(x["code"]), reverse=True)

    html = ""
    for p in sorted_products:
        code         = p["code"]
        name         = p.get("name", "")
        display_name = p.get("short_name") or name
        url          = p.get("url") or "#"
        img          = p.get("image_url", "")
        category     = p.get("category", "")

        img_tag = (
            f'<img src="{img}" alt="{display_name}" loading="lazy" '
            f'onerror="this.parentElement.classList.add(\'no-img\')">'
            if img else ""
        )
        target = 'target="_blank" rel="noopener noreferrer"' if url != "#" else ""

        html += f"""
    <a class="card" data-code="{code}" data-name="{name.lower()}" data-category="{category}"
       href="{url}" {target} onclick="recordClick('{code}')">
      {img_tag}
      <div class="card-body">
        <div class="badge-row">
          <span class="badge">[{code}]</span>
        </div>
        <p class="name">{display_name}</p>
      </div>
    </a>"""
    return html


def build_html(products: list[dict]) -> str:
    cards    = build_cards(products)
    count    = len(products)
    firebase_config_json = load_firebase_config()
    products_json = json.dumps(
        [
            {
                "code":          p["code"],
                "name":          p.get("short_name") or p.get("name", ""),
                "url":           p.get("url", ""),
                "image_url":     p.get("image_url", ""),
                "category":      p.get("category", ""),
                "registered_at": p.get("registered_at", ""),
            }
            for p in products
        ],
        ensure_ascii=False,
    )

    if COUPANG_PARTNERS_ACTIVE:
        footer_disclosure = "이 포스팅은 쿠팡파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
    else:
        footer_disclosure = "이 페이지에 포함된 링크는 향후 쿠팡파트너스 활동의 일환으로 수수료가 발생할 수 있습니다."

    ticker_repeated = ("  ·  " + _TICKER_MSG) * 6

    cat_pills = "".join(
        f'<button class="cat-pill{" active" if c == "전체" else ""}" data-cat="{c}" onclick="filterCat(this)">{c}</button>'
        for c in CATEGORIES
    )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>꿀픽 | 진짜 쓸만한 것들만 모았어요</title>
<script src="https://www.gstatic.com/firebasejs/10.12.2/firebase-app-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore-compat.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  :root {{
    --bg: #0d0d0d;
    --surface: #181818;
    --surface2: #222;
    --border: #2c2c2c;
    --accent: #FF6B35;
    --accent2: #FFD166;
    --text: #f0f0f0;
    --text2: #777;
    --radius: 16px;
    --ticker-bg: linear-gradient(90deg, #1a0a00, #2a1000, #1a0a00);
    --ticker-border: rgba(255,107,53,0.3);
    --ticker-color: rgba(255,209,102,0.9);
    --header-bg: rgba(13,13,13,0.9);
  }}

  body.light {{
    --bg: #f5f5f5;
    --surface: #ffffff;
    --surface2: #efefef;
    --border: #dedede;
    --text: #111111;
    --text2: #888888;
    --ticker-bg: linear-gradient(90deg, #fff3ed, #fff0e6, #fff3ed);
    --ticker-border: rgba(255,107,53,0.2);
    --ticker-color: rgba(180,80,20,0.9);
    --header-bg: rgba(245,245,245,0.95);
  }}

  body {{
    font-family: -apple-system, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    transition: background .2s, color .2s;
  }}

  /* ── 티커 ── */
  .ticker-wrap {{
    background: var(--ticker-bg);
    border-bottom: 1px solid var(--ticker-border);
    overflow: hidden;
    padding: 7px 0;
    position: sticky;
    top: 0;
    z-index: 200;
  }}
  .ticker-track {{
    display: flex;
    width: max-content;
    animation: ticker 30s linear infinite;
  }}
  .ticker-track:hover {{ animation-play-state: paused; }}
  .ticker-text {{
    font-size: 0.72rem;
    color: var(--ticker-color);
    white-space: nowrap;
    padding-right: 40px;
    letter-spacing: 0.02em;
  }}
  @keyframes ticker {{
    0%   {{ transform: translateX(0); }}
    100% {{ transform: translateX(-50%); }}
  }}

  /* ── 헤더 ── */
  header {{
    background: var(--header-bg);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border-bottom: 1px solid var(--border);
    padding: 12px 16px 12px;
    text-align: center;
    position: sticky;
    top: 33px;
    z-index: 100;
  }}
  .header-top {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 10px;
  }}
  /* 워드마크 — 한글 '꿀픽' 단독, 미세 그라데이션 + 그림자 */
  .logo {{
    font-size: 1.65rem;
    font-weight: 800;
    letter-spacing: -1.5px;
    flex: 1;
    text-align: center;
    background: linear-gradient(135deg, var(--accent) 0%, #FFB454 65%, var(--accent2) 100%);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
    color: transparent;
    text-shadow: 0 1px 0 rgba(255,107,53,0.06);
    padding: 0 4px;
    line-height: 1;
  }}
  .logo::after {{
    content: '';
    display: block;
    width: 22px;
    height: 2px;
    margin: 6px auto 0;
    border-radius: 2px;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    opacity: 0.7;
  }}
  .tagline {{
    font-size: 0.73rem;
    color: var(--text2);
    margin-bottom: 10px;
    letter-spacing: 0.02em;
  }}
  .header-btns {{
    display: flex;
    gap: 6px;
    flex-shrink: 0;
  }}
  .icon-btn {{
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 10px;
    color: var(--text2);
    font-size: 0.72rem;
    font-weight: 600;
    padding: 6px 10px;
    cursor: pointer;
    transition: all .15s;
    display: flex;
    align-items: center;
    gap: 4px;
    white-space: nowrap;
    text-decoration: none;
  }}
  .icon-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
  .icon-btn svg {{ width: 13px; height: 13px; fill: currentColor; }}

  .search-wrap {{
    margin: 0 auto;
    max-width: 400px;
    position: relative;
  }}
  .search-wrap::before {{
    content: '🔍';
    position: absolute;
    left: 13px;
    top: 50%;
    transform: translateY(-50%);
    font-size: 13px;
    pointer-events: none;
  }}
  #search {{
    width: 100%;
    padding: 9px 14px 9px 36px;
    background: var(--surface2);
    border: 1.5px solid var(--border);
    border-radius: 24px;
    color: var(--text);
    font-size: 0.84rem;
    outline: none;
    transition: border-color .2s;
  }}
  #search:focus {{ border-color: var(--accent); }}
  #search::placeholder {{ color: var(--text2); }}

  /* ── 카테고리 필터 ── */
  .cat-wrap {{
    max-width: 640px;
    margin: 12px auto 0;
    padding: 0 14px;
    display: flex;
    gap: 6px;
    flex-wrap: nowrap;          /* 한 줄 고정 */
    overflow-x: auto;           /* 옆으로 스와이프 */
    scrollbar-width: none;
    -webkit-overflow-scrolling: touch;
  }}
  .cat-wrap::-webkit-scrollbar {{ display: none; }}
  .cat-pill {{
    font-size: 0.72rem;
    font-weight: 600;
    padding: 5px 13px;
    border-radius: 20px;
    border: 1.5px solid var(--border);
    background: var(--surface2);
    color: var(--text2);
    cursor: pointer;
    transition: all .18s ease;
    white-space: nowrap;
  }}
  .cat-pill:hover {{ border-color: var(--accent); color: var(--accent); transform: translateY(-1px); }}
  .cat-pill.active {{
    background: linear-gradient(135deg, var(--accent), #FF8552);
    border-color: var(--accent);
    color: #fff;
    box-shadow: 0 2px 8px rgba(255,107,53,0.25);
  }}

  /* ── 컨트롤 바 ── */
  .control-bar {{
    max-width: 640px;
    margin: 12px auto 0;
    padding: 0 14px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }}
  .count-label {{ font-size: 0.74rem; color: var(--text2); flex-shrink: 0; }}

  .sort-tabs {{
    display: flex;
    gap: 4px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 3px;
  }}
  .sort-tab {{
    font-size: 0.7rem;
    font-weight: 600;
    color: var(--text2);
    padding: 4px 10px;
    border-radius: 16px;
    cursor: pointer;
    transition: all .15s;
    border: none;
    background: transparent;
  }}
  .sort-tab.active {{ background: var(--accent); color: #fff; }}

  .view-toggle {{
    display: flex;
    gap: 4px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 3px;
  }}
  .view-btn {{
    width: 28px;
    height: 24px;
    border: none;
    background: transparent;
    border-radius: 14px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all .15s;
    color: var(--text2);
  }}
  .view-btn.active {{ background: var(--surface); color: var(--accent); border: 1px solid var(--border); }}
  .view-btn svg {{ width: 14px; height: 14px; fill: currentColor; }}

  /* ── 추천 섹션 ── */
  .featured-section {{
    padding: 14px 14px 0;
    max-width: 640px;
    margin: 0 auto;
  }}
  .featured-title {{
    font-size: 0.75rem;
    font-weight: 800;
    color: var(--text2);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 5px;
  }}
  .carousel-outer {{
    position: relative;
  }}
  .carousel-wrap {{
    overflow-x: auto;
    scrollbar-width: none;
    -ms-overflow-style: none;
  }}
  .carousel-wrap::-webkit-scrollbar {{ display: none; }}
  .carousel-row {{
    display: flex;
    gap: 10px;
    padding-bottom: 4px;
    padding-left: 2px;
    padding-right: 2px;
  }}
  .arrow-btn {{
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    z-index: 10;
    background: var(--surface);
    border: 1.5px solid var(--border);
    border-radius: 50%;
    width: 30px;
    height: 30px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    color: var(--text2);
    font-size: 1.1rem;
    font-weight: 700;
    transition: all .15s;
    line-height: 1;
    padding: 0;
  }}
  .arrow-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
  .arrow-btn.left  {{ left: -4px; }}
  .arrow-btn.right {{ right: -4px; }}

  .c-card {{
    flex: 0 0 130px;
    background: var(--surface);
    border: 1.5px solid var(--border);
    border-radius: 14px;
    overflow: hidden;
    text-decoration: none;
    display: block;
    transition: border-color .15s, transform .15s;
  }}
  .c-card:hover {{ border-color: var(--accent); transform: translateY(-2px); }}
  .c-card.rank-best {{ border-color: #50DC78; }}
  .c-card.rank-hot  {{ border-color: var(--accent); }}
  .c-card img {{
    width: 100%;
    aspect-ratio: 1/1;
    object-fit: cover;
    display: block;
    background: var(--surface2);
  }}
  .c-card-body {{ padding: 7px 8px 9px; }}
  .c-badge {{
    font-size: 0.58rem;
    font-weight: 800;
    padding: 2px 6px;
    border-radius: 6px;
    display: inline-block;
    margin-bottom: 4px;
    letter-spacing: 0.03em;
  }}
  .c-badge.best {{ background: rgba(80,220,120,0.2); color: #50DC78; border: 1px solid rgba(80,220,120,0.3); }}
  .c-badge.hot  {{ background: rgba(255,107,53,0.2); color: var(--accent); border: 1px solid rgba(255,107,53,0.3); }}
  .c-badge.new  {{ background: rgba(255,209,102,0.2); color: var(--accent2); border: 1px solid rgba(255,209,102,0.3); }}
  .c-overlay-badge {{
    position: absolute; top: 4px; left: 4px;
    font-size: 0.58rem; font-weight: 800;
    padding: 2px 6px; border-radius: 5px; line-height: 1.3;
  }}
  .c-overlay-badge.hot {{ background: rgba(255,107,53,.92); color: #fff; }}
  .c-overlay-badge.new {{ background: rgba(255,209,102,.95); color: #5a3e00; }}
  /* 카테고리 보기: Best/추천 배너 절반 이하 축소 */
  #featured-section.compact {{ padding-top: 8px; }}
  #featured-section.compact .featured-title {{ margin-bottom: 5px; font-size: 0.68rem; }}
  #featured-section.compact .c-card {{ flex: 0 0 84px; border-radius: 10px; }}
  #featured-section.compact .c-card-body {{ padding: 4px 5px 5px; }}
  #featured-section.compact .c-name {{ -webkit-line-clamp: 1; font-size: 0.62rem; }}
  #featured-section.compact .arrow-btn {{ display: none; }}
  .c-name {{
    font-size: 0.7rem;
    font-weight: 600;
    line-height: 1.35;
    color: var(--text);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }}

  /* ── 그리드 ── */
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(158px, 1fr));
    gap: 12px;
    padding: 12px 14px 28px;
    max-width: 640px;
    margin: 0 auto;
    transition: all .2s;
  }}
  .grid.list-view {{ grid-template-columns: 1fr; gap: 8px; }}
  .grid.list-view .card {{ flex-direction: row; height: 76px; position: relative; }}
  .grid.list-view .card img {{ width: 76px; height: 76px; aspect-ratio: 1/1; flex-shrink: 0; border-radius: var(--radius) 0 0 var(--radius); }}
  /* 리스트뷰: 상품명만 가운데, 코드/HOT 뱃지는 좌측 상단(이미지 우측 위) */
  .grid.list-view .card-body {{ padding: 8px 14px 8px 14px; justify-content: center; align-items: center; text-align: center; gap: 0; }}
  .grid.list-view .badge-row {{
    position: absolute;
    top: 4px;
    left: 84px;
    margin: 0;
    gap: 4px;
    z-index: 2;
  }}
  .grid.list-view .name {{
    -webkit-line-clamp: 2;
    margin: 0;
    font-size: 0.82rem;
    font-weight: 600;
    flex: initial;
    text-align: center;
    padding-top: 10px; /* 상단 뱃지 영역 회피 */
  }}

  /* ── 카드 ── */
  .card {{
    background: var(--surface);
    border-radius: var(--radius);
    overflow: hidden;
    border: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    text-decoration: none;
    color: inherit;
    transition: transform .2s ease, border-color .2s, box-shadow .2s;
  }}
  .card:hover {{ transform: translateY(-3px); border-color: #3a3a3a; box-shadow: 0 10px 28px rgba(0,0,0,0.45); }}
  body.light .card:hover {{ box-shadow: 0 10px 28px rgba(0,0,0,0.12); border-color: #ccc; }}
  .grid.list-view .card:hover {{ transform: translateX(3px); }}
  .card img {{ width: 100%; aspect-ratio: 1/1; object-fit: cover; background: var(--surface2); display: block; }}
  .card.no-img img {{ display: none; }}
  .card-body {{ padding: 10px 10px 12px; display: flex; flex-direction: column; flex: 1; }}
  .badge-row {{ display: flex; align-items: center; gap: 5px; margin-bottom: 7px; flex-wrap: wrap; }}
  .badge {{
    display: inline-block;
    background: rgba(255,107,53,0.12);
    color: var(--accent);
    font-size: 0.67rem;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 20px;
    border: 1px solid rgba(255,107,53,0.25);
    flex-shrink: 0;
  }}
  .badge-new  {{ display: inline-block; background: rgba(255,209,102,0.12); color: var(--accent2); font-size: 0.62rem; font-weight: 800; padding: 2px 6px; border-radius: 20px; border: 1px solid rgba(255,209,102,0.25); letter-spacing: 0.04em; flex-shrink: 0; }}
  .badge-hot  {{ display: inline-block; background: rgba(255,107,53,0.12); color: #FF6B6B; font-size: 0.62rem; font-weight: 800; padding: 2px 6px; border-radius: 20px; border: 1px solid rgba(255,59,59,0.25); letter-spacing: 0.04em; flex-shrink: 0; }}
  .badge-best {{ display: inline-block; background: rgba(80,220,120,0.12); color: #50DC78; font-size: 0.62rem; font-weight: 800; padding: 2px 6px; border-radius: 20px; border: 1px solid rgba(80,220,120,0.25); letter-spacing: 0.04em; flex-shrink: 0; }}
  .name {{ font-size: 0.82rem; font-weight: 600; line-height: 1.45; color: #c0c0c0; flex: 1; text-align: center; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }}
  body.light .name {{ color: #333; }}

  .empty, #no-result {{ text-align: center; padding: 60px 20px; color: var(--text2); font-size: 0.88rem; grid-column: 1 / -1; }}
  #no-result {{ display: none; }}

  /* ── 푸터 ── */
  footer {{ max-width: 640px; margin: 0 auto; padding: 0 14px 48px; }}
  .disclosure-box {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 13px 16px; margin-bottom: 14px; }}
  .disclosure-title {{ font-size: 0.68rem; font-weight: 700; color: #555; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 5px; }}
  .disclosure-text {{ font-size: 0.7rem; color: var(--text2); line-height: 1.65; }}
  .footer-copy {{ font-size: 0.65rem; color: #333; text-align: center; }}

  /* ── QR 모달 ── */
  .modal-overlay {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.75); backdrop-filter: blur(8px); z-index: 500; align-items: center; justify-content: center; }}
  .modal-overlay.open {{ display: flex; }}
  .modal-box {{ background: var(--surface); border: 1px solid var(--border); border-radius: 20px; padding: 28px 24px 22px; max-width: 300px; width: 90%; text-align: center; }}
  .modal-title {{ font-size: 1rem; font-weight: 700; margin-bottom: 18px; color: var(--text); }}
  #qr-canvas {{ display: flex; justify-content: center; margin-bottom: 14px; }}
  #qr-canvas canvas, #qr-canvas img {{ border-radius: 10px; border: 6px solid #fff; }}
  .modal-url {{ font-size: 0.65rem; color: var(--text2); word-break: break-all; margin-bottom: 16px; line-height: 1.5; }}
  .modal-close {{ background: var(--surface2); border: 1px solid var(--border); border-radius: 10px; color: var(--text2); font-size: 0.82rem; font-weight: 600; padding: 8px 20px; cursor: pointer; transition: all .15s; }}
  .modal-close:hover {{ border-color: #555; color: var(--text); }}

  /* ── 토스트 ── */
  .toast {{ position: fixed; bottom: 32px; left: 50%; transform: translateX(-50%) translateY(20px); background: #222; border: 1px solid #444; border-radius: 24px; padding: 10px 20px; font-size: 0.82rem; color: var(--text); opacity: 0; transition: all .3s; z-index: 600; white-space: nowrap; pointer-events: none; }}
  .toast.show {{ opacity: 1; transform: translateX(-50%) translateY(0); }}
</style>
</head>
<body>

<div class="ticker-wrap">
  <div class="ticker-track">
    <span class="ticker-text">📢 {ticker_repeated}</span>
    <span class="ticker-text">📢 {ticker_repeated}</span>
  </div>
</div>

<header>
  <div class="header-top">
    <div style="width:50px"></div>
    <div class="logo">꿀픽</div>
    <div class="header-btns">
      <button class="icon-btn" id="theme-btn" onclick="toggleTheme()" title="다크/라이트">☀️</button>
      <button class="icon-btn" onclick="showQR()" title="QR코드">
        <svg viewBox="0 0 24 24"><path d="M3 3h7v7H3V3zm2 2v3h3V5H5zm9-2h7v7h-7V3zm2 2v3h3V5h-3zM3 14h7v7H3v-7zm2 2v3h3v-3H5zm11 0h2v2h-2v-2zm2 2h2v2h-2v-2zm-4 0h2v2h-2v-2zm4-4h2v2h-2v-2zm-4 4h2v2h-2v-2zm4 4h2v2h-2v-2zm-2-2h2v2h-2v-2z"/></svg>
        QR
      </button>
      <button class="icon-btn" onclick="sharePage()" title="공유">
        <svg viewBox="0 0 24 24"><path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92s2.92-1.31 2.92-2.92-1.31-2.92-2.92-2.92z"/></svg>
        공유
      </button>
    </div>
  </div>
  <div class="search-wrap">
    <input type="search" id="search" placeholder="코드(예: 027) 또는 상품명 검색" autocomplete="off" inputmode="search">
  </div>
</header>

<div class="cat-wrap" id="cat-wrap">
  {cat_pills}
</div>

<div class="featured-section" id="featured-section">
  <div class="featured-title" id="title-best">🏆 Best 10</div>
  <div class="carousel-outer">
    <button class="arrow-btn left" onclick="scrollCarousel('best10',-1)">‹</button>
    <div class="carousel-wrap" id="wrap-best10">
      <div class="carousel-row" id="row-best10"><div style="color:var(--text2);font-size:0.75rem;padding:14px 4px">집계 중...</div></div>
    </div>
    <button class="arrow-btn right" onclick="scrollCarousel('best10',1)">›</button>
  </div>
  <div class="featured-title" id="title-hot" style="margin-top:14px">🔥 추천 상품</div>
  <div class="carousel-wrap" id="wrap-hot" style="padding:0 2px">
    <div class="carousel-row" id="row-hot"><div style="color:var(--text2);font-size:0.75rem;padding:14px 4px">집계 중...</div></div>
  </div>
</div>

<div class="control-bar">
  <span class="count-label" id="count-label">상품 {count}개</span>
  <div class="sort-tabs">
    <button class="sort-tab active" id="tab-newest" onclick="setSort('newest')">최신순</button>
    <button class="sort-tab" id="tab-popular" onclick="setSort('popular')">인기순</button>
  </div>
  <div class="view-toggle">
    <button class="view-btn active" id="btn-grid" onclick="setView('grid')" title="카드형">
      <svg viewBox="0 0 16 16"><rect x="1" y="1" width="6" height="6" rx="1"/><rect x="9" y="1" width="6" height="6" rx="1"/><rect x="1" y="9" width="6" height="6" rx="1"/><rect x="9" y="9" width="6" height="6" rx="1"/></svg>
    </button>
    <button class="view-btn" id="btn-list" onclick="setView('list')" title="리스트형">
      <svg viewBox="0 0 16 16"><rect x="1" y="2" width="14" height="3" rx="1"/><rect x="1" y="7" width="14" height="3" rx="1"/><rect x="1" y="12" width="14" height="3" rx="1"/></svg>
    </button>
  </div>
</div>

<div class="grid" id="grid">
{cards}
  <div id="no-result">검색 결과가 없습니다</div>
</div>

<footer>
  <div class="disclosure-box">
    <div class="disclosure-title">안내</div>
    <div class="disclosure-text">
      {footer_disclosure}<br>
      상품 가격 및 재고는 실시간으로 변동될 수 있으며, 쿠팡 페이지에서 최종 확인 후 구매해 주세요.
    </div>
  </div>
  <div class="footer-copy">© 꿀픽</div>
</footer>

<div id="qr-modal" class="modal-overlay" onclick="hideQR()">
  <div class="modal-box" onclick="event.stopPropagation()">
    <div class="modal-title">📱 QR코드로 공유</div>
    <div id="qr-canvas"></div>
    <div class="modal-url" id="qr-url-text"></div>
    <button class="modal-close" onclick="hideQR()">닫기</button>
  </div>
</div>

<div class="toast" id="toast">링크가 복사됐어요 ✓</div>

<script>
  /* ── 상품 데이터 ── */
  const PRODUCTS_DATA = {products_json};

  /* ── 카테고리 자동 추론 ── */
  function inferCategory(name) {{
    const n = name.toLowerCase();
    if (/메론|멜론|과일|사과|딸기|포도|감귤|고기|한우|삼겹|식품|간식|과자|젤리|견과|쌀|김치|반찬|즉석|밀키트|음료|주스|차류|원두|해산물|생선|간재미|오징어|새우|소스|양념|장아찌|육포|빵|떡|꿀\b/.test(n)) return '식품';
    if (/크림|샴푸|세럼|마스크팩|화장품|뷰티|헤어|두피|클렌징|세안|렌즈|로션|에센스|토너|선크림/.test(n)) return '뷰티';
    if (/도마|식기세척기|주방|냄비|프라이팬|에어프라이어|정수기|조리|커피|그릇|칼|가위|집게/.test(n)) return '주방';
    if (/휴지통|청소기|세탁|수납|정리함|쓰레기|걸레|진공|빨래|청소/.test(n)) return '생활';
    if (/이어폰|블루투스|충전기|스마트워치|가전|전자|스피커|노트북|태블릿|키보드/.test(n)) return '디지털/가전';
    if (/조명|무드등|디퓨저|인테리어|선반|수납장|커튼|러그/.test(n)) return '인테리어';
    return '기타';
  }}

  function getCardCategory(card) {{
    const stored = (card.dataset.category || '').trim();
    return stored || inferCategory(card.dataset.name || '');
  }}

  /* ── Firebase 클릭 트래킹 ── */
  const _FB_CONFIG = {firebase_config_json};
  let _db = null;
  let _clicks = {{}};   // {{ code: {{ total, hot7 }} }}
  const THEME_KEY = 'kkul_theme';
  const VIEW_KEY  = 'kkul_view';

  if (_FB_CONFIG) {{
    try {{
      firebase.initializeApp(_FB_CONFIG);
      _db = firebase.firestore();
    }} catch(e) {{
      console.warn('[꿀픽] Firebase init error:', e);
    }}
  }}

  async function _loadClickStats() {{
    if (!_db) return;
    try {{
      const snap = await _db.collection("products").get();
      const now = Date.now();
      const last7 = [];
      for (let i = 0; i < 7; i++) {{
        const d = new Date(now - i * 86400000);
        last7.push(d.toISOString().slice(0,10).replace(/-/g,''));
      }}
      _clicks = {{}};
      snap.forEach(ds => {{
        const data = ds.data();
        _clicks[ds.id] = {{
          total: data.total || 0,
          hot7:  last7.reduce((s, day) => s + (data.days?.[day] || 0), 0),
        }};
      }});
      applyBadges();
      buildCarousel();
      if (currentSort === 'popular') setSort('popular');
    }} catch(e) {{
      console.warn('[꿀픽] Firebase load error:', e);
    }}
  }}

  /* 운영자 클릭 제외: ?owner=1 로 켜고 ?owner=0 으로 끔 (admin 접속 기기는 자동 ON) */
  const _params = new URLSearchParams(location.search);
  if (_params.get('owner') === '1') {{ localStorage.setItem('kkul_owner', '1'); }}
  if (_params.get('owner') === '0') {{ localStorage.removeItem('kkul_owner'); }}
  const _isOwner = localStorage.getItem('kkul_owner') === '1';

  function recordClick(code) {{
    if (_isOwner) return;        // 내 클릭은 집계 제외
    if (!_clicks[code]) _clicks[code] = {{ total: 0, hot7: 0 }};
    _clicks[code].total++;
    _clicks[code].hot7++;
    applyBadges();
    if (!_db) return;
    const today = new Date().toISOString().slice(0,10).replace(/-/g,'');
    const ref = _db.collection("products").doc(code);
    ref.update({{
      total: firebase.firestore.FieldValue.increment(1),
      [`days.${{today}}`]: firebase.firestore.FieldValue.increment(1),
    }}).catch(() => {{
      ref.set({{ total: 1, days: {{ [today]: 1 }} }})
         .catch(e => console.warn('[꿀픽] write error:', e));
    }});
  }}

  /* ── 뱃지 계산 ──
     BEST : 누적 클릭 상위 10 (최소 3클릭)
     HOT  : 최근 7일 클릭 상위 2 (BEST 제외)
     NEW  : registered_at 기준 48시간 이내
  */
  function pCat(p) {{ return (p.category || '').trim() || inferCategory((p.name || '').toLowerCase()); }}

  function computeBadges(pool, minClicks) {{
    pool = pool || PRODUCTS_DATA;
    const now = Date.now();
    const MS_48H  = 48 * 3600000;
    const MIN_CLICKS = (minClicks !== undefined) ? minClicks : 3;

    // BEST: 누적 클릭 상위 10
    const withTotal = pool
      .map(p => ({{ code: p.code, total: _clicks[p.code]?.total || 0 }}))
      .filter(x => x.total >= MIN_CLICKS)
      .sort((a, b) => b.total - a.total);
    const bestCodes = new Set(withTotal.slice(0, 10).map(x => x.code));

    // HOT: 7일 클릭 상위 2 (BEST 제외)
    const withHot = pool
      .filter(p => !bestCodes.has(p.code))
      .map(p => ({{ code: p.code, hot7: _clicks[p.code]?.hot7 || 0 }}))
      .filter(x => x.hot7 > 0)
      .sort((a, b) => b.hot7 - a.hot7);
    const hotCodes = new Set(withHot.slice(0, 2).map(x => x.code));

    // NEW: registered_at 기준 48시간 이내
    const newCodes = new Set();
    for (const p of pool) {{
      if (!p.registered_at) continue;
      const reg = new Date(p.registered_at).getTime();
      if (!isNaN(reg) && now - reg < MS_48H) newCodes.add(p.code);
    }}

    return {{ bestCodes, hotCodes, newCodes }};
  }}

  function applyBadges() {{
    const {{ bestCodes, hotCodes, newCodes }} = computeBadges();
    document.querySelectorAll('.card').forEach(card => {{
      const code = card.dataset.code;
      const row  = card.querySelector('.badge-row');
      row.querySelectorAll('.badge-hot, .badge-best, .badge-new').forEach(b => b.remove());
      if (bestCodes.has(code)) {{
        row.insertAdjacentHTML('beforeend', '<span class="badge-best">BEST</span>');
      }} else if (hotCodes.has(code)) {{
        row.insertAdjacentHTML('beforeend', '<span class="badge-hot">HOT 🔥</span>');
      }}
      if (newCodes.has(code)) {{
        row.insertAdjacentHTML('beforeend', '<span class="badge-new">NEW</span>');
      }}
    }});
  }}

  applyBadges();   // NEW 뱃지는 즉시 표시 (Firebase 없이도)
  _loadClickStats(); // BEST/HOT은 Firebase 로드 후 표시

  /* ── 카테고리 필터 ── */
  let currentCat = '전체';

  function filterCat(btn) {{
    currentCat = btn.dataset.cat;
    document.querySelectorAll('.cat-pill').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    // 카테고리 모드: Best/추천도 해당 카테고리 기준으로 재계산 + 배너 축소
    document.getElementById('featured-section').classList.toggle('compact', currentCat !== '전체');
    buildCarousel();
    filterAndCount();
  }}

  /* ── 검색 + 카테고리 통합 필터 ── */
  const searchInput = document.getElementById('search');
  const allCards    = Array.from(document.querySelectorAll('.card'));
  const noResult    = document.getElementById('no-result');
  const countLabel  = document.getElementById('count-label');

  function filterAndCount() {{
    const q = searchInput.value.trim().replace(/[\\[\\]]/g, '').toLowerCase();
    let visible = 0;
    allCards.forEach(c => {{
      const matchSearch   = !q || c.dataset.code.startsWith(q) || c.dataset.name.includes(q);
      const cardCat       = getCardCategory(c);
      const matchCat      = currentCat === '전체' || cardCat === currentCat;
      const show          = matchSearch && matchCat;
      c.style.display     = show ? '' : 'none';
      if (show) visible++;
    }});
    noResult.style.display = visible === 0 ? 'block' : 'none';
    const suffix = q || currentCat !== '전체' ? `${{visible}}개 검색됨` : `상품 ${{allCards.length}}개`;
    countLabel.textContent = suffix;
  }}

  searchInput.addEventListener('input', filterAndCount);

  const hash = location.hash.replace('#', '').replace(/[\\[\\]]/g, '');
  if (hash) {{
    searchInput.value = hash;
    filterAndCount();
    const target = document.querySelector(`.card[data-code="${{hash.padStart(3,'0')}}"]`);
    if (target) target.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
  }}

  /* ── 추천 캐러셀 (Best10 + HOT 2) ── */
  function buildCarousel() {{
    if (!PRODUCTS_DATA.length) return;
    const inCat = currentCat !== '전체';
    const pool  = inCat ? PRODUCTS_DATA.filter(p => pCat(p) === currentCat) : PRODUCTS_DATA;
    // 카테고리 모드: 풀이 작으니 최소 클릭 1로 완화
    const {{ bestCodes, hotCodes, newCodes }} = computeBadges(pool, inCat ? 1 : 3);
    const tB = document.getElementById('title-best');
    const tH = document.getElementById('title-hot');
    if (tB) tB.textContent = inCat ? `🏆 ${{currentCat}} Best` : '🏆 Best 10';
    if (tH) tH.textContent = inCat ? `🔥 ${{currentCat}} 추천` : '🔥 추천 상품';

    // ── Best 10 ──
    const rowBest = document.getElementById('row-best10');
    if (rowBest) {{
      const bestItems = [...pool]
        .filter(p => bestCodes.has(p.code))
        .sort((a, b) => (_clicks[b.code]?.total || 0) - (_clicks[a.code]?.total || 0))
        .slice(0, 10);
      if (!bestItems.length) {{
        rowBest.innerHTML = '<div style="color:var(--text2);font-size:0.75rem;padding:16px 4px">아직 집계된 클릭이 없습니다</div>';
      }} else {{
        rowBest.innerHTML = bestItems.map((p, i) => {{
          const imgTag = p.image_url ? `<img src="${{p.image_url}}" alt="${{p.name}}" loading="lazy">` : '';
          return `
            <a class="c-card rank-best" href="${{p.url || '#'}}"
               ${{p.url ? 'target="_blank" rel="noopener noreferrer"' : ''}}
               onclick="recordClick('${{p.code}}')">
              <div style="position:relative">
                ${{imgTag}}
                <span style="position:absolute;top:4px;left:4px;background:rgba(0,0,0,.72);color:#FFD166;font-size:.6rem;font-weight:800;padding:2px 5px;border-radius:5px;line-height:1.3">#${{i+1}}</span>
              </div>
              <div class="c-card-body">
                <div class="c-name">${{p.name}}</div>
              </div>
            </a>`;
        }}).join('');
      }}
    }}

    // ── HOT 추천 2 ──
    const rowHot = document.getElementById('row-hot');
    if (rowHot) {{
      const hotItems = [...pool]
        .filter(p => hotCodes.has(p.code))
        .sort((a, b) => (_clicks[b.code]?.hot7 || 0) - (_clicks[a.code]?.hot7 || 0));
      // 부족하면 NEW로 채움
      const newFill = [...pool]
        .filter(p => newCodes.has(p.code) && !hotCodes.has(p.code) && !bestCodes.has(p.code));
      const combined = [...hotItems, ...newFill].slice(0, 2);
      if (!combined.length) {{
        rowHot.innerHTML = '<div style="color:var(--text2);font-size:0.75rem;padding:16px 4px">추천 상품 집계 중...</div>';
      }} else {{
        rowHot.innerHTML = combined.map(p => {{
          const isHot = hotCodes.has(p.code);
          const badgeClass = isHot ? 'hot' : 'new';
          const badgeText  = isHot ? 'HOT 🔥' : 'NEW';
          const rankClass  = isHot ? 'rank-hot' : '';
          const imgTag = p.image_url ? `<img src="${{p.image_url}}" alt="${{p.name}}" loading="lazy">` : '';
          const overlay = `<span class="c-overlay-badge ${{badgeClass}}">${{badgeText}}</span>`;
          return `
            <a class="c-card ${{rankClass}}" href="${{p.url || '#'}}"
               ${{p.url ? 'target="_blank" rel="noopener noreferrer"' : ''}}
               onclick="recordClick('${{p.code}}')">
              <div style="position:relative">${{imgTag}}${{imgTag ? overlay : ''}}</div>
              <div class="c-card-body">
                ${{imgTag ? '' : overlay}}
                <div class="c-name">${{p.name}}</div>
              </div>
            </a>`;
        }}).join('');
      }}
    }}
  }}

  function scrollCarousel(id, dir) {{
    const wrap = document.getElementById('wrap-' + id);
    if (wrap) wrap.scrollBy({{ left: dir * 145, behavior: 'smooth' }});
  }}

  /* ── 정렬 ── */
  let currentSort = 'newest';

  function setSort(mode) {{
    currentSort = mode;
    document.getElementById('tab-newest').classList.toggle('active', mode === 'newest');
    document.getElementById('tab-popular').classList.toggle('active', mode === 'popular');
    const grid = document.getElementById('grid');
    const noEl = document.getElementById('no-result');
    const cards = allCards.slice();
    if (mode === 'newest') {{
      cards.sort((a, b) => parseInt(b.dataset.code) - parseInt(a.dataset.code));
    }} else {{
      cards.sort((a, b) => {{
        const ca = _clicks[a.dataset.code]?.total || 0;
        const cb = _clicks[b.dataset.code]?.total || 0;
        return cb !== ca ? cb - ca : parseInt(b.dataset.code) - parseInt(a.dataset.code);
      }});
    }}
    cards.forEach(c => grid.insertBefore(c, noEl));
    filterAndCount();
  }}

  /* ── 뷰 모드 ── */
  let currentView = 'grid';

  function setView(mode) {{
    currentView = mode;
    document.getElementById('btn-grid').classList.toggle('active', mode === 'grid');
    document.getElementById('btn-list').classList.toggle('active', mode === 'list');
    document.getElementById('grid').classList.toggle('list-view', mode === 'list');
    localStorage.setItem(VIEW_KEY, mode);
  }}

  const savedView = localStorage.getItem(VIEW_KEY);
  if (savedView && savedView !== 'grid') setView(savedView);

  /* ── 다크/라이트 모드 ── */
  function applyTheme(theme) {{
    document.body.classList.toggle('light', theme === 'light');
    document.getElementById('theme-btn').textContent = theme === 'light' ? '🌙' : '☀️';
  }}

  function toggleTheme() {{
    const next = document.body.classList.contains('light') ? 'dark' : 'light';
    localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
  }}

  applyTheme(localStorage.getItem(THEME_KEY) || 'dark');

  /* ── QR ── */
  let qrGenerated = false;
  function showQR() {{
    const modal = document.getElementById('qr-modal');
    const url = window.location.href;
    document.getElementById('qr-url-text').textContent = url;
    if (!qrGenerated) {{
      new QRCode(document.getElementById('qr-canvas'), {{ text: url, width: 200, height: 200, colorDark: '#000', colorLight: '#fff', correctLevel: QRCode.CorrectLevel.H }});
      qrGenerated = true;
    }}
    modal.classList.add('open');
  }}
  function hideQR() {{ document.getElementById('qr-modal').classList.remove('open'); }}

  /* ── 공유 ── */
  function sharePage() {{
    const url = window.location.href;
    if (navigator.share) {{
      navigator.share({{ title: '꿀픽', text: '매일 하나씩, 진짜 쓸만한 것들만', url }}).catch(() => {{}});
    }} else {{
      navigator.clipboard.writeText(url).then(showToast).catch(() => {{ prompt('링크를 복사하세요:', url); }});
    }}
  }}

  function showToast() {{
    const t = document.getElementById('toast');
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 2200);
  }}
</script>

</body>
</html>"""


def main():
    products = get_all()
    html = build_html(products)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"생성 완료: {OUTPUT_PATH}")
    print(f"상품 {len(products)}개 포함")
    if products:
        codes = sorted([p['code'] for p in products], key=lambda x: int(x), reverse=True)
        print("코드 목록 (최신순):", ", ".join(f"[{c}]" for c in codes))


if __name__ == "__main__":
    main()
