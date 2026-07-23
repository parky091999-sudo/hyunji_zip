"""registry.posted=True 상품을 posted_ids에 백필 (중복 발행 1차 가드 보강).

배경(2026-07-23): [066] 소파베드가 registry엔 posted=True인데 posted_ids에 키가
없어, evening_post가 후보로 재선정 → 마커 가드(find_recent_post_by_marker)가
막아 라이브 중복은 없었으나 1차 가드(posted_ids)가 뚫린 상태였음. 초기·수동 발행분이
posted_ids에 안 들어간 잔재. posted_ids는 '이미 발행' allowlist라 known-posted 키를
추가하는 것은 항상 dedup을 강화(약화 불가) → 안전.

키 형식은 auto_post._product_key 와 동일하게 product_url[:80].
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA = os.path.join(ROOT, "data")
REG = os.path.join(DATA, "product_registry.json")
PID = os.path.join(DATA, "posted_ids.json")

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def main() -> int:
    reg = json.load(open(REG, encoding="utf-8"))
    products = reg.get("products", {})
    ids = set(json.load(open(PID, encoding="utf-8")))
    before = len(ids)
    added = []
    for url, v in products.items():
        if not v.get("posted"):
            continue
        key = (v.get("url") or url or "")[:80]
        if key and key not in ids:
            ids.add(key)
            added.append((v.get("code", "?"), v.get("short_name") or v.get("name", "")[:20]))
    if added:
        json.dump(sorted(ids), open(PID, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"posted_ids: {before} → {len(ids)} (+{len(added)})")
    for code, name in added:
        print(f"  + [{code}] {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
