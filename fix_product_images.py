#!/usr/bin/env python
"""
제품 이미지 수정: 015, 013 제품의 threads_image_url 제거
(제품 페이지에서 threads_image_url이 없으면 image_url 사용)
"""
import json

# Read product_registry
with open('data/product_registry.json', 'r', encoding='utf-8') as f:
    registry = json.load(f)

# 013, 015 제품의 threads_image_url 제거
changed = []
for url, p in registry['products'].items():
    code = p.get('code')
    if code in ['013', '015']:
        name = p.get('name', '')[:40]
        has_threads_img = 'threads_image_url' in p

        # threads_image_url 제거 (있으면)
        if has_threads_img:
            del p['threads_image_url']
            changed.append(f"[{code}] {name}")

        print(f"[{code}] {name}")
        print(f"  image_url: {p.get('image_url', '')[:50]}")
        print(f"  removed threads_image_url: {has_threads_img}")
        print()

# Save
if changed:
    with open('data/product_registry.json', 'w', encoding='utf-8') as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)
    print(f"✓ 수정 완료: {len(changed)}개 제품")
    for item in changed:
        print(f"  - {item}")
else:
    print("변경 사항 없음")
