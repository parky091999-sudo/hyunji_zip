"""
잘못된 코드로 올라간 게시글 수정
1. 기존 포스트 삭제 (Threads API)
2. registry 정리 (미포스팅 코드 제거, 번호 재정렬)
3. 같은 상품 올바른 코드로 재포스팅
환경변수: OLD_POST_ID (삭제할 포스트ID), OLD_CODE (예: 008), NEW_CODE (예: 005)
"""
import json
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import DATA_DIR, LOG_DIR

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("fix_post_code")

REGISTRY_PATH   = os.path.join(DATA_DIR, "product_registry.json")
FEED_POSTS_PATH = os.path.join(DATA_DIR, "feed_posts.json")


def _load(path, default):
    if not os.path.exists(path): return default
    with open(path, encoding="utf-8") as f: return json.load(f)

def _save(path, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def delete_threads_post(post_id: str) -> bool:
    """Threads API로 게시글 삭제"""
    import requests, urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    token = os.getenv("THREADS_ACCESS_TOKEN", "")
    if not token:
        logger.error("THREADS_ACCESS_TOKEN 없음")
        return False
    r = requests.delete(
        f"https://graph.threads.net/v1.0/{post_id}",
        params={"access_token": token},
        timeout=10, verify=False,
    )
    if r.status_code == 200:
        logger.info(f"  게시글 삭제 완료: {post_id}")
        return True
    else:
        logger.error(f"  삭제 실패: {r.status_code} {r.text[:200]}")
        return False


def fix_registry(old_code: str, new_code: str) -> dict | None:
    """
    registry에서:
    - 미포스팅 항목(posted 없는 것) 제거
    - old_code → new_code 로 변경
    - next_code 를 실제 포스팅된 최대 코드 + 1 로 재설정
    """
    reg = _load(REGISTRY_PATH, {"next_code": 1, "products": {}})
    products = reg.get("products", {})

    # 미포스팅 항목 제거 + old_code → new_code 변경
    to_delete = []
    target_entry = None
    for key, v in products.items():
        if not v.get("posted", False):
            to_delete.append(key)
        if v["code"] == old_code:
            target_entry = (key, v)

    for key in to_delete:
        logger.info(f"  미포스팅 항목 제거: [{products[key]['code']}] {products[key].get('name','')[:30]}")
        del products[key]

    # old_code 항목이 이미 삭제됐으면 다시 찾기
    if target_entry and target_entry[0] in products:
        products[target_entry[0]]["code"] = new_code
        products[target_entry[0]]["posted"] = True
        logger.info(f"  코드 변경: [{old_code}] → [{new_code}]")

    # next_code 재산정: 포스팅된 코드 중 최대값 + 1
    posted_codes = [int(v["code"]) for v in products.values() if v.get("posted", False)]
    new_next = (max(posted_codes) + 1) if posted_codes else 1
    reg["next_code"] = new_next
    reg["products"] = products
    _save(REGISTRY_PATH, reg)
    logger.info(f"  registry 저장 — next_code={new_next}, 총 {len(products)}개")

    if target_entry:
        return target_entry[1]

    # old_code가 이미 new_code로 변경된 경우 → new_code로 직접 조회
    for v in products.values():
        if v["code"] == new_code:
            logger.info(f"  old_code [{old_code}] 없음 — new_code [{new_code}] 항목으로 재포스팅")
            return v

    return None


def fix_feed(old_code: str, new_code: str):
    """feed_posts.json의 코드 수정"""
    feed = _load(FEED_POSTS_PATH, [])
    for f in feed:
        if f.get("product_code") == old_code:
            f["product_code"] = new_code
            logger.info(f"  feed_posts 코드 수정: {old_code} → {new_code}")
    _save(FEED_POSTS_PATH, feed)


def repost(product_entry: dict, new_code: str, old_post_text: str = ""):
    """수정된 코드로 재포스팅"""
    from generator.content import _generate_post1_ai, _post1_fallback, _AD_DISCLOSURE
    from config import COUPANG_PARTNERS_ACTIVE

    # 기존 post_text에서 코드 라인 교체 (구·신 포맷 모두 대응)
    if old_post_text:
        import re
        post_text = re.sub(
            r'제품 정보는 프로필 링크에서 \[\w+\] 검색 👆|\[\w+\] 정보는 댓글에 👇',
            f'[{new_code}] 정보는 댓글에 👇',
            old_post_text,
        )
        if post_text == old_post_text and f"[{new_code}]" not in post_text:
            post_text += f"\n\n[{new_code}] 정보는 댓글에 👇"
    else:
        name = product_entry.get("name", "")
        post_text = _generate_post1_ai({"name": name}, new_code) or _post1_fallback(name, new_code)
        if COUPANG_PARTNERS_ACTIVE:
            post_text = f"[광고]\n{post_text}\n\n{_AD_DISCLOSURE}"

    image_url = product_entry.get("image_url", "")

    from poster.threads import post_thread_api
    result = post_thread_api(post_text=post_text, image_url=image_url, detail_images=[])

    if result:
        post_url = result.get("post_url", "")
        post_id  = result.get("post_id", "")
        logger.info(f"  재포스팅 완료: {post_url}")

        # feed에 새 포스팅 기록
        from datetime import datetime, timezone, timedelta
        KST = timezone(timedelta(hours=9))
        feed = _load(FEED_POSTS_PATH, [])
        feed.insert(0, {
            "timestamp":     datetime.now(KST).isoformat(),
            "product_code":  new_code,
            "product_name":  product_entry.get("name", ""),
            "product_image": image_url,
            "product_url":   product_entry.get("url", ""),
            "post_text":     post_text,
            "threads_url":   post_url,
            "status":        "posted",
            "post_type":     "repost",
        })
        _save(FEED_POSTS_PATH, feed[:200])
        return True
    else:
        logger.error("  재포스팅 실패")
        return False


def run():
    old_post_id = os.getenv("OLD_POST_ID", "").strip()
    old_code    = os.getenv("OLD_CODE", "").strip().zfill(3)
    new_code    = os.getenv("NEW_CODE", "").strip().zfill(3)

    if not old_code or not new_code:
        logger.error("OLD_CODE, NEW_CODE 환경변수 필요")
        sys.exit(1)

    logger.info(f"코드 수정: [{old_code}] → [{new_code}], post_id={old_post_id or '(삭제 안함)'}")

    # 1. 기존 포스트 삭제
    if old_post_id:
        deleted = delete_threads_post(old_post_id)
        if not deleted:
            logger.warning("삭제 실패했지만 계속 진행")

    # 2. registry + feed 코드 수정
    product_entry = fix_registry(old_code, new_code)
    fix_feed(old_code, new_code)

    # 3. 재포스팅
    if product_entry:
        # feed_posts에서 기존 post_text 찾기
        feed = _load(FEED_POSTS_PATH, [])
        old_text = next((f.get("post_text","") for f in feed if f.get("product_code") == new_code), "")
        repost(product_entry, new_code, old_text)
    else:
        logger.error("재포스팅할 상품 정보 없음")

    # 4. 페이지 재생성
    try:
        import generate_page, generate_feed_page
        generate_page.main()
        generate_feed_page.main()
    except Exception as e:
        logger.error(f"페이지 생성 오류: {e}")

    logger.info("완료")


if __name__ == "__main__":
    run()
