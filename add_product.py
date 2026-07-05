"""
직접 상품 등록 CLI

[우선순위 큐] — 즉시 포스팅 대기열 (사용 후 삭제)
  python add_product.py "전동 두피 마사지기"
  python add_product.py --url "https://www.coupang.com/vp/products/..."
  python add_product.py --list
  python add_product.py --remove 2
  python add_product.py --clear

[프리셋 리스트] — 자동 수집 실패 시 순환 폴백 (삭제 안 됨)
  python add_product.py --preset "전동 두피 마사지기"
  python add_product.py --preset --url "https://www.coupang.com/vp/products/..."
  python add_product.py --preset --list
  python add_product.py --preset --remove 2
  python add_product.py --preset --clear
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(__file__))
from config import DATA_DIR, NAVER_CLIENT_ID, NAVER_CLIENT_SECRET

QUEUE_PATH = os.path.join(DATA_DIR, "priority_queue.json")


def load_queue() -> list:
    if not os.path.exists(QUEUE_PATH):
        return []
    with open(QUEUE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_queue(queue: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


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
        lp = int(item.get("lprice", 0) or 0)
        return {
            "name":        name,
            "price":       f"{lp:,}원" if lp else "",
            "image_url":   item.get("image", ""),
            "product_url": item.get("link", ""),
            "brand":       (item.get("brand") or item.get("maker") or "").strip(),
            "source":      "manual",
        }
    except Exception as e:
        print(f"  네이버 검색 오류: {e}")
        return None


def _is_duplicate(queue: list, url: str, name: str = "") -> bool:
    if url and any(item.get("product", {}).get("product_url", "") == url for item in queue):
        return True
    if name:
        saturated_kw = {"그라인더", "후추", "소금", "식기세척기", "식세기", "선풍기", "손풍기", "건조기", "휴지통", "쓰레기통", "마스크", "티스푼"}
        if any(sk in name for sk in saturated_kw):
            print(f"  ⚠️  [주의] 과포화 상품 키워드({[sk for sk in saturated_kw if sk in name]})가 포함되어 있습니다.")
        if any(name == item.get("product", {}).get("name", "") for item in queue):
            return True
    return False


def add_by_name(name: str):
    print(f"네이버 쇼핑 검색 중: '{name}'")
    product = _search_naver(name)
    if not product:
        product = {"name": name, "product_url": "", "source": "manual"}
        print("  → 검색 결과 없음 — 상품명만으로 등록")
    else:
        print(f"  → {product['name'][:55]}  |  {product.get('price', '')}")
    _enqueue(product)


def add_by_url(url: str):
    # 쿠팡 URL에서 상품명 힌트 추출
    name_hint = ""
    m = re.search(r"/products/\d+--([^/?#]+)", url)
    if m:
        name_hint = m.group(1).replace("-", " ").strip()

    if name_hint and NAVER_CLIENT_ID:
        print(f"URL 힌트로 네이버 검색: '{name_hint}'")
        product = _search_naver(name_hint)
        if product:
            product["product_url"] = url
            print(f"  → 매칭: {product['name'][:55]}")
        else:
            product = {"name": name_hint, "product_url": url, "source": "manual"}
    else:
        # URL만 있을 때 — 상품명은 URL 끝 부분에서 추출
        fallback_name = url.rstrip("/").split("/")[-1][:50] or "수동 등록 상품"
        product = {"name": fallback_name, "product_url": url, "source": "manual"}

    _enqueue(product)


def _enqueue(product: dict):
    queue = load_queue()
    if _is_duplicate(queue, product.get("product_url", ""), product.get("name", "")):
        print(f"  ⚠️  이미 큐에 있는 상품입니다.")
        return
    if not product.get("short_name") and product.get("name"):
        try:
            from generator.content import _fallback_short_name
            product["short_name"] = _fallback_short_name(product["name"])
        except Exception:
            pass
    entry = {
        "priority":  1,
        "source":    "manual",
        "added_at":  datetime.now().isoformat(),
        "product":   product,
    }
    queue.append(entry)
    save_queue(queue)
    print(f"  ✅ 큐에 추가 (priority=1 / 수동): {product.get('name', '')[:55]}")
    p1 = sum(1 for x in queue if x.get("priority") == 1)
    p2 = sum(1 for x in queue if x.get("priority") == 2)
    print(f"     현재 큐: 수동={p1}개  벤치마크={p2}개  합계={len(queue)}개")


def print_queue():
    queue = load_queue()
    if not queue:
        print("우선순위 큐가 비어 있습니다.")
        return
    queue_sorted = sorted(queue, key=lambda x: (x.get("priority", 99), x.get("added_at", "")))
    print(f"우선순위 큐 ({len(queue_sorted)}개):")
    print(f"  {'#':<4} {'P':<3} {'출처':<12} {'상품명':<45} {'등록일'}")
    print("  " + "-" * 80)
    for i, entry in enumerate(queue_sorted, 1):
        p     = entry.get("priority", "?")
        src   = entry.get("source", "?")[:10]
        name  = entry.get("product", {}).get("name", "?")[:43]
        added = entry.get("added_at", "")[:10]
        print(f"  {i:<4} {p:<3} {src:<12} {name:<45} {added}")


def remove_item(index: int):
    queue = load_queue()
    queue_sorted = sorted(queue, key=lambda x: (x.get("priority", 99), x.get("added_at", "")))
    if index < 1 or index > len(queue_sorted):
        print(f"  ❌ 잘못된 번호: {index} (1~{len(queue_sorted)} 범위)")
        return
    removed = queue_sorted.pop(index - 1)
    save_queue(queue_sorted)
    print(f"  ✅ 삭제: [{index}] {removed.get('product', {}).get('name', '')[:50]}")


def _preset_build_product(name: str | None, url: str | None) -> dict | None:
    if url:
        name_hint = ""
        m = re.search(r"/products/\d+--([^/?#]+)", url)
        if m:
            name_hint = m.group(1).replace("-", " ").strip()
        if name_hint and NAVER_CLIENT_ID:
            product = _search_naver(name_hint)
            if product:
                product["product_url"] = url
            else:
                product = {"name": name_hint, "product_url": url, "source": "manual"}
        else:
            product = {"name": name or url.rstrip("/").split("/")[-1][:50], "product_url": url, "source": "manual"}
    elif name:
        product = _search_naver(name)
        if not product:
            product = {"name": name, "product_url": "", "source": "manual"}
    else:
        return None
    return product


def handle_preset(args):
    from scraper.preset import add_product, remove_product, list_products

    if args.clear:
        from scraper.preset import _save
        _save([])
        print("프리셋 리스트를 초기화했습니다.")
        return

    if args.list:
        items = list_products()
        if not items:
            print("프리셋 리스트가 비어 있습니다.")
            return
        print(f"프리셋 리스트 ({len(items)}개) — 자동 수집 실패 시 순환 폴백:")
        print(f"  {'#':<4} {'상품명':<50} {'마지막사용':<12} {'등록일'}")
        print("  " + "-" * 85)
        for i, p in enumerate(items, 1):
            name     = p.get("name", "?")[:48]
            last     = p.get("last_used", "")[:10] or "미사용"
            added    = p.get("added_at", "")[:10]
            print(f"  {i:<4} {name:<50} {last:<12} {added}")
        return

    if args.remove is not None:
        items = list_products()
        if remove_product(args.remove):
            print(f"  삭제 완료: [{args.remove}]번 항목")
        else:
            print(f"  잘못된 번호: {args.remove} (1~{len(items)} 범위)")
        return

    product = _preset_build_product(args.name, args.url)
    if not product:
        print("상품명 또는 --url 을 입력하세요.")
        return

    print(f"  → {product.get('name', '')[:55]}  |  {product.get('price', '')}")
    if add_product(product):
        items = list_products()
        print(f"  프리셋에 추가 완료 (현재 {len(items)}개)")
    else:
        print("  이미 프리셋에 등록된 상품입니다.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="상품 등록 CLI (우선순위 큐 / 프리셋 리스트)",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("name",     nargs="?",            help="등록할 상품명")
    parser.add_argument("--url",                          help="쿠팡 상품 URL")
    parser.add_argument("--list",   action="store_true",  help="목록 조회")
    parser.add_argument("--remove", type=int, metavar="N",help="N번 항목 삭제")
    parser.add_argument("--clear",  action="store_true",  help="전체 삭제")
    parser.add_argument("--preset", action="store_true",  help="프리셋 리스트 대상 (없으면 우선순위 큐)")
    args = parser.parse_args()

    if args.preset:
        handle_preset(args)
    elif args.clear:
        save_queue([])
        print("큐를 초기화했습니다.")
    elif args.list:
        print_queue()
    elif args.remove is not None:
        remove_item(args.remove)
    elif args.url:
        add_by_url(args.url)
    elif args.name:
        add_by_name(args.name)
    else:
        parser.print_help()
