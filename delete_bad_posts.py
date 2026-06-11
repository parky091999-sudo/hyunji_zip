"""
잘못 포스팅된 게시글 직접 삭제
- 17942040570220581: 013 중복 (DZX4TaQFPyK)
- 18091527815013962: 012 외국어 포함 (DZXzGTTFm6d)
- 17947994988192533: 011 중복 (DZVaPOnFA8M)
"""
import json, os, requests, sys
sys.path.append(os.path.dirname(__file__))
from config import THREADS_ACCESS_TOKEN

GRAPH_BASE = "https://graph.threads.net/v1.0"
FEED_FILE = os.path.join(os.path.dirname(__file__), "data", "feed_posts.json")

# 삭제할 (numeric_id, url_code, reason) 목록
DELETE_TARGETS = [
    ("17942040570220581", "DZX4TaQFPyK", "013 중복본 (사진 없음)"),
    ("18091527815013962", "DZXzGTTFm6d", "012 외국어 포함"),
    ("17947994988192533", "DZVaPOnFA8M", "011 중복본 (사진 1장)"),
]

# feed_posts.json에서 제거할 URL codes
REMOVE_FROM_FEED_CODES = {"DZXzGTTFm6d"}  # 012만 feed에서 제거

def api_delete(post_id):
    r = requests.delete(
        f"{GRAPH_BASE}/{post_id}",
        params={"access_token": THREADS_ACCESS_TOKEN},
        timeout=30,
    )
    return r.json()

def main():
    print("=== Threads 잘못된 포스팅 삭제 ===\n")

    deleted_url_codes = set()
    for numeric_id, url_code, reason in DELETE_TARGETS:
        print(f"삭제 중: {reason}")
        print(f"  ID: {numeric_id} | URL code: {url_code}")
        result = api_delete(numeric_id)
        if result.get("success") or result.get("deleted"):
            print(f"  [OK] 삭제 완료\n")
            deleted_url_codes.add(url_code)
        else:
            print(f"  [FAIL] 실패: {result}\n")

    # feed_posts.json에서 012 제거
    if deleted_url_codes & REMOVE_FROM_FEED_CODES:
        with open(FEED_FILE, "r", encoding="utf-8") as f:
            feed = json.load(f)

        new_feed = []
        for p in feed:
            url = p.get("threads_url") or ""
            code = url.split("/post/")[-1] if "/post/" in url else ""
            if code in (deleted_url_codes & REMOVE_FROM_FEED_CODES):
                print(f"feed에서 제거: [{p.get('product_code')}] {p.get('product_name','')}")
            else:
                new_feed.append(p)

        with open(FEED_FILE, "w", encoding="utf-8") as f:
            json.dump(new_feed, f, ensure_ascii=False, indent=2)
        print("\nfeed_posts.json 업데이트 완료")

    print("\n=== 완료 ===")

if __name__ == "__main__":
    main()
