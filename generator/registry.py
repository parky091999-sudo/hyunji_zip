"""
상품 코드 레지스트리
- 포스팅할 상품마다 [001], [002]... 순번 부여
- 인포크링크(inpock.co.kr) 상품 목록과 코드 동기화 기준
"""
import json
import os
import re
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import DATA_DIR

REGISTRY_PATH = os.path.join(DATA_DIR, "product_registry.json")


def _extract_item_id(url: str) -> str | None:
    """쿠팡 URL에서 itemId 추출 — ctag가 달라도 같은 상품 감지용"""
    m = re.search(r"itemId=(\d+)", url or "")
    return m.group(1) if m else None


def _load() -> dict:
    if os.path.exists(REGISTRY_PATH):
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"next_code": 1, "products": {}}


def _save(reg: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)


def assign_code(product_url: str, name: str = "", image_url: str = "") -> str:
    """
    상품 URL에 순번 코드 할당.
    이미 등록된 URL이면 기존 코드 반환.
    URL이 달라도 itemId가 같으면 같은 상품으로 판단 (중복 방지).
    """
    reg = _load()
    key = (product_url or "")[:80]

    # 1. URL key 일치
    if key and key in reg["products"]:
        if image_url and not reg["products"][key].get("image_url"):
            reg["products"][key]["image_url"] = image_url
            _save(reg)
        return reg["products"][key]["code"]

    # 2. itemId 일치 — ctag만 다른 동일 상품 감지
    item_id = _extract_item_id(product_url)
    if item_id:
        # 차단 목록 확인 (수동 삭제된 상품 재진입 방지)
        if item_id in reg.get("blocked_item_ids", []):
            return ""  # 빈 문자열 = 차단됨
        for existing in reg["products"].values():
            if _extract_item_id(existing.get("url", "")) == item_id:
                return existing["code"]

    code = str(reg["next_code"]).zfill(3)
    if key:
        reg["products"][key] = {"code": code, "name": name, "url": product_url, "image_url": image_url}
    reg["next_code"] += 1
    _save(reg)
    return code


def mark_posted(code: str):
    """포스팅 성공 시 호출 — 해당 코드 상품을 posted=True 로 표시"""
    reg = _load()
    for v in reg["products"].values():
        if v["code"] == code:
            v["posted"] = True
            break
    _save(reg)


def get_all() -> list[dict]:
    """실제 포스팅된 상품 목록만 반환 — 링크인바이오 페이지 생성용"""
    reg = _load()
    return [
        {
            "code": v["code"],
            "name": v.get("name", ""),
            "url": v.get("url", ""),
            "image_url": v.get("image_url", ""),
        }
        for v in reg["products"].values()
        if v.get("posted", False)
    ]
