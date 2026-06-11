"""
포스팅 정리 스크립트
- 002(채칼), 003(도마), 004(유리창닦이), 005(샴푸) Threads 삭제
- 도마를 [002]로, 샴푸를 [003]으로 재게시
- product_registry.json, feed_posts.json 업데이트
"""
import sys, os, json, time, re
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()
from config import THREADS_ACCESS_TOKEN, THREADS_USER_ID
import requests

GRAPH_BASE = "https://graph.threads.net/v1.0"

# 삭제할 Threads 포스트 ID (API 조회 결과)
DELETE_IDS = {
    "002_채칼":     "18101872288950513",
    "003_도마":     "18078123233650425",
    "004_유리창닦이": "18060337241492475",
    "005_샴푸":     "18070742921681663",
}

def api(method, path, **kwargs):
    url = f"{GRAPH_BASE}{path}"
    resp = requests.request(method, url, timeout=30, **kwargs)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"API 오류: {data['error']}")
    return data


def delete_post(post_id: str, label: str):
    print(f"  삭제 중: {label} (ID: {post_id})")
    try:
        data = api("DELETE", f"/{post_id}", params={"access_token": THREADS_ACCESS_TOKEN})
        print(f"  → 삭제 완료: {data}")
    except Exception as e:
        print(f"  → 삭제 실패: {e}")


def post_with_image(text: str, image_url: str) -> dict | None:
    print(f"  이미지 컨테이너 생성...")
    if image_url:
        container = api("POST", f"/{THREADS_USER_ID}/threads", params={
            "media_type": "IMAGE",
            "text": text,
            "image_url": image_url,
            "access_token": THREADS_ACCESS_TOKEN,
        })
    else:
        container = api("POST", f"/{THREADS_USER_ID}/threads", params={
            "media_type": "TEXT",
            "text": text,
            "access_token": THREADS_ACCESS_TOKEN,
        })
    container_id = container["id"]
    print(f"  컨테이너 ID: {container_id} → 30초 대기...")
    time.sleep(30)
    result = api("POST", f"/{THREADS_USER_ID}/threads_publish", params={
        "creation_id": container_id,
        "access_token": THREADS_ACCESS_TOKEN,
    })
    post_id = result["id"]
    # URL 조회
    try:
        url_data = api("GET", f"/{post_id}", params={"fields": "permalink", "access_token": THREADS_ACCESS_TOKEN})
        post_url = url_data.get("permalink")
    except Exception:
        post_url = None
    print(f"  게시 완료: {post_url}")
    return {"post_id": post_id, "post_url": post_url}


def update_code_in_text(text: str, old_code: str, new_code: str) -> str:
    return re.sub(rf"\[{old_code}\]", f"[{new_code}]", text)


def main():
    data_dir = os.path.join(os.path.dirname(__file__), "data")

    with open(os.path.join(data_dir, "feed_posts.json"), encoding="utf-8") as f:
        feed_posts = json.load(f)

    with open(os.path.join(data_dir, "product_registry.json"), encoding="utf-8") as f:
        registry = json.load(f)

    # 재게시할 포스트 데이터 미리 추출
    post_003 = next((p for p in feed_posts if p["product_code"] == "003"), None)
    post_005 = next((p for p in feed_posts if p["product_code"] == "005"), None)

    # ── 1단계: Threads 삭제 ───────────────────────────────────────────────────
    print("\n[1/4] Threads 포스트 삭제...")
    for label, pid in DELETE_IDS.items():
        delete_post(pid, label)
        time.sleep(3)

    # ── 2단계: 도마 → [002] 재게시 ───────────────────────────────────────────
    print("\n[2/4] 도마 → [002] 재게시...")
    new_003_text = update_code_in_text(post_003["post_text"], "003", "002")
    result_002 = post_with_image(new_003_text, post_003["product_image"])
    time.sleep(5)

    # ── 3단계: 샴푸 → [003] 재게시 ───────────────────────────────────────────
    print("\n[3/4] 샴푸 → [003] 재게시...")
    new_005_text = update_code_in_text(post_005["post_text"], "005", "003")
    result_003 = post_with_image(new_005_text, post_005["product_image"])

    # ── 4단계: 데이터 파일 업데이트 ──────────────────────────────────────────
    print("\n[4/4] 데이터 파일 업데이트...")

    # feed_posts.json 업데이트
    new_feed = []
    for p in feed_posts:
        code = p["product_code"]
        if code in ("002", "004"):
            continue  # 삭제
        elif code == "003":
            p["product_code"] = "002"
            p["post_text"] = new_003_text
            p["threads_url"] = result_002.get("post_url")
        elif code == "005":
            p["product_code"] = "003"
            p["post_text"] = new_005_text
            p["threads_url"] = result_003.get("post_url")
        new_feed.append(p)

    # 코드순(내림차순)으로 정렬
    new_feed.sort(key=lambda x: x["product_code"], reverse=True)

    with open(os.path.join(data_dir, "feed_posts.json"), "w", encoding="utf-8") as f:
        json.dump(new_feed, f, ensure_ascii=False, indent=2)
    print("  feed_posts.json 저장 완료")

    # product_registry.json 업데이트
    products = registry["products"]
    # 002(채칼) 삭제
    del_keys_002 = [k for k, v in products.items() if v["code"] == "002"]
    for k in del_keys_002:
        del products[k]
    # 004(유리창닦이) 삭제
    del_keys_004 = [k for k, v in products.items() if v["code"] == "004"]
    for k in del_keys_004:
        del products[k]
    # 003 → 002
    for v in products.values():
        if v["code"] == "003":
            v["code"] = "002"
    # 005 → 003
    for v in products.values():
        if v["code"] == "005":
            v["code"] = "003"
    # next_code = 4
    registry["next_code"] = 4

    with open(os.path.join(data_dir, "product_registry.json"), "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)
    print("  product_registry.json 저장 완료")

    # recent_posts.json 업데이트 (새 포스트 등록)
    recent_posts_path = os.path.join(data_dir, "recent_posts.json")
    try:
        with open(recent_posts_path, encoding="utf-8") as f:
            recent = json.load(f)
    except Exception:
        recent = []
    from datetime import datetime
    if result_003.get("post_url"):
        recent.append({"url": result_003["post_url"], "post_id": result_003["post_id"], "posted_at": datetime.now().isoformat(), "post_type": "story"})
    with open(recent_posts_path, "w", encoding="utf-8") as f:
        json.dump(recent, f, ensure_ascii=False, indent=2)
    print("  recent_posts.json 저장 완료")

    print("\n완료! 최종 포스트 목록:")
    for p in new_feed:
        print(f"  [{p['product_code']}] {p['product_name'][:40]}")
        print(f"       {p['threads_url']}")


if __name__ == "__main__":
    main()
