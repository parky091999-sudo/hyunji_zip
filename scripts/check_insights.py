"""
포스팅 인사이트(조회수/좋아요/댓글/리포스트) 조회 — 일회성.
Threads Insights API: GET /{post_id}/insights?metric=...
"""
import io
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import DATA_DIR
from poster.threads import _api, fetch_my_posts, THREADS_ACCESS_TOKEN, THREADS_USER_ID

FEED_POSTS_PATH = os.path.join(DATA_DIR, "feed_posts.json")
KST = timezone(timedelta(hours=9))

METRICS = "views,likes,replies,reposts,quotes"


def shortcode(url: str) -> str:
    return url.rstrip("/").split("/post/")[-1] if url and "/post/" in url else ""


def fetch_insights(media_id: str) -> dict:
    data = _api(
        "GET",
        f"/{media_id}/insights",
        params={"metric": METRICS, "access_token": THREADS_ACCESS_TOKEN},
    )
    out = {}
    for item in data.get("data", []):
        name = item.get("name")
        if "values" in item and item["values"]:
            out[name] = item["values"][0].get("value", 0)
        elif "total_value" in item:
            out[name] = item["total_value"].get("value", 0)
    return out


def main():
    if not THREADS_ACCESS_TOKEN or not THREADS_USER_ID:
        print("THREADS_ACCESS_TOKEN/USER_ID 없음", flush=True)
        sys.exit(1)

    feed = json.load(open(FEED_POSTS_PATH, encoding="utf-8"))
    api_posts = fetch_my_posts(limit=100)
    api_by_sc = {shortcode(p.get("permalink", "")): p for p in api_posts if shortcode(p.get("permalink", ""))}

    posted = [p for p in feed if p.get("status") == "posted" and p.get("threads_url")]
    print(f"feed_posts: {len(posted)}건 / Threads API: {len(api_by_sc)}건\n", flush=True)

    rows = []
    for p in posted:
        sc = shortcode(p["threads_url"])
        api_id = api_by_sc.get(sc, {}).get("id", "")
        if not api_id:
            rows.append({"ts": p.get("timestamp", "")[:16], "code": p.get("product_code") or "-",
                         "type": p.get("post_type", "?"), "sc": sc, "name": (p.get("product_name") or "")[:24],
                         "views": None, "likes": None, "replies": None, "reposts": None, "quotes": None,
                         "err": "API 매칭 없음"})
            continue
        try:
            m = fetch_insights(api_id)
            rows.append({"ts": p.get("timestamp", "")[:16], "code": p.get("product_code") or "-",
                         "type": p.get("post_type", "?"), "sc": sc, "name": (p.get("product_name") or "")[:24],
                         **m, "err": ""})
        except Exception as e:
            rows.append({"ts": p.get("timestamp", "")[:16], "code": p.get("product_code") or "-",
                         "type": p.get("post_type", "?"), "sc": sc, "name": (p.get("product_name") or "")[:24],
                         "views": None, "likes": None, "replies": None, "reposts": None, "quotes": None,
                         "err": str(e)[:60]})

    rows.sort(key=lambda r: r["ts"], reverse=True)

    print(f"{'timestamp':<17} {'code':>4} {'type':<13} {'views':>6} {'likes':>5} {'rep':>4} {'rpst':>4} {'quot':>4}  name", flush=True)
    print("-" * 110, flush=True)
    tot_v = tot_l = tot_r = 0
    n_ok = 0
    for r in rows:
        v = r.get("views"); l = r.get("likes"); rp = r.get("replies"); rpst = r.get("reposts"); q = r.get("quotes")
        if v is not None:
            tot_v += v or 0; tot_l += l or 0; tot_r += rp or 0; n_ok += 1
        fmt = lambda x: "-" if x is None else str(x)
        line = f"{r['ts']:<17} {r['code']:>4} {r['type']:<13} {fmt(v):>6} {fmt(l):>5} {fmt(rp):>4} {fmt(rpst):>4} {fmt(q):>4}  {r['name']}"
        if r.get("err"):
            line += f"  [err: {r['err']}]"
        print(line, flush=True)

    print("-" * 110, flush=True)
    print(f"합계({n_ok}건): views={tot_v} / likes={tot_l} / replies={tot_r}", flush=True)
    if n_ok:
        print(f"평균: views={tot_v/n_ok:.1f} / likes={tot_l/n_ok:.2f} / replies={tot_r/n_ok:.2f}", flush=True)

    # 상위 5 — engagement 기준
    print("\n=== views TOP 5 ===", flush=True)
    top_v = sorted([r for r in rows if r.get("views") is not None], key=lambda r: r["views"] or 0, reverse=True)[:5]
    for r in top_v:
        print(f"  [{r['code']}] views={r['views']} likes={r['likes']} replies={r['replies']}  {r['name']}  ({r['ts']})", flush=True)

    print("\n=== likes TOP 5 ===", flush=True)
    top_l = sorted([r for r in rows if r.get("likes") is not None], key=lambda r: r["likes"] or 0, reverse=True)[:5]
    for r in top_l:
        print(f"  [{r['code']}] likes={r['likes']} views={r['views']} replies={r['replies']}  {r['name']}  ({r['ts']})", flush=True)


if __name__ == "__main__":
    main()
