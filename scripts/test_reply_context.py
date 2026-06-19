"""generate_reply 컨텍스트 회귀 테스트 — 일회성. 결과는 로그로만."""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from generator.reply import generate_reply

LAUNDRY_POST = """빨래는 왜 해도 해도 끝이 없는 걸까? 🧺
분명 주말에 빨래 지옥에서 탈출했다고 생각했는데... 며칠 지나 서랍 위를 보면 또 옷 무덤이 생겨있네?
안 입은 건 아닌데, 그렇다고 바로 또 입을 건 아닌 그런 묘하게 애매한 옷들이 매번 서랍 위를 점령하는 거 나만 그래?"""

CLEANING_POST = """방금 치웠는데 왜 이래...? 🤦‍♀️
퇴근하고 집에 왔는데 거실 바닥에 굴러다니는 머리카락이랑 먼지들 보면서 현타 옴."""

cases = [
    ("빨래글 + '건식이 짱이야'", LAUNDRY_POST, "@user: 건식이 짱이야"),
    ("청소글 + '건식 화장실 추천'", CLEANING_POST, "@user: 건식 화장실 추천"),
    ("빨래글 + '습식이 더 빨라'", LAUNDRY_POST, "@user: 습식이 더 빨라"),
    ("컨텍스트 없음 + '건식이 짱이야'", "", "@user: 건식이 짱이야"),
]

print("=" * 60, flush=True)
for label, parent, comment in cases:
    print(f"\n[{label}]", flush=True)
    for i in range(2):
        r = generate_reply(comment, parent_post_text=parent)
        print(f"  try {i+1}: {r}", flush=True)
print("=" * 60, flush=True)
