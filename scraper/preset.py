"""
미리 등록한 상품 목록에서 다음 포스팅 대상 선택
- preset_products.json 은 소진되지 않고 순환 (pop 하지 않음)
- 아직 포스팅 안 된 상품 우선, 전부 포스팅됐으면 가장 오래된 것부터 재사용
"""
import json
import logging
import os
import sys
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import DATA_DIR

logger = logging.getLogger(__name__)

PRESET_PATH = os.path.join(DATA_DIR, "preset_products.json")


def _load() -> list[dict]:
    if not os.path.exists(PRESET_PATH):
        return []
    with open(PRESET_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save(products: list[dict]):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PRESET_PATH, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)


def _product_key(url: str) -> str:
    return (url or "")[:80]


def get_next_preset_product(posted_ids: set[str]) -> dict | None:
    """
    preset_products.json 에서 포스팅할 상품 1개 선택.
    우선순위:
    1. 아직 한 번도 포스팅 안 된 상품
    2. 모두 포스팅됐으면 last_used 가 가장 오래된 상품 (순환)
    """
    products = _load()
    if not products:
        return None

    unposted = [
        p for p in products
        if _product_key(p.get("product_url", "")) not in posted_ids
    ]

    if unposted:
        chosen = unposted[0]
        logger.info(f"[프리셋] 미포스팅 상품 선택: {chosen.get('name', '')[:40]}")
    else:
        # 전부 포스팅됨 → last_used 가장 오래된 것 재사용
        chosen = min(products, key=lambda p: p.get("last_used", ""))
        logger.info(f"[프리셋] 순환 재사용: {chosen.get('name', '')[:40]}")

    # last_used 갱신
    for p in products:
        if p.get("product_url") == chosen.get("product_url"):
            p["last_used"] = datetime.now().isoformat()
            break
    _save(products)

    return {
        "name":         chosen.get("name", ""),
        "product_url":  chosen.get("product_url", ""),
        "image_url":    chosen.get("image_url", ""),
        "brand":        chosen.get("brand", ""),
        "price":        chosen.get("price", ""),
        "source":       "preset",
        "category_hint": chosen.get("category_hint", "생활"),
    }


def add_product(product: dict):
    """preset 리스트에 상품 추가 (중복 URL 무시)"""
    products = _load()
    url_key = _product_key(product.get("product_url", ""))
    if any(_product_key(p.get("product_url", "")) == url_key for p in products):
        return False  # 중복
    products.append({
        **product,
        "added_at":  datetime.now().isoformat(),
        "last_used": "",
    })
    _save(products)
    return True


def remove_product(index: int) -> bool:
    """1-based 인덱스로 삭제"""
    products = _load()
    if index < 1 or index > len(products):
        return False
    products.pop(index - 1)
    _save(products)
    return True


def list_products() -> list[dict]:
    return _load()
