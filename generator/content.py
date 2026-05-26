"""
콘텐츠 생성기
- 포스팅 구조: 2개 세트 (글1: 자연스러운 추천 / 글2: 링크)
- 스타일: 반말, 개인 경험 위주, 짧고 자연스럽게
- 준수 사항:
    - 확정적 가격/순위 표현 금지 ("역대최저가", "최저가보장" 등)
    - 할인율 0%일 때 할인 언급 금지
    - COUPANG_PARTNERS_ACTIVE=True 시 [광고] + 공정위 고지문 자동 추가
"""
import random
import os
import sys
import logging

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import COUPANG_PARTNERS_ACTIVE

logger = logging.getLogger(__name__)


# ── 카테고리별 해시태그 ─────────────────────────────────────────────────────
_HASHTAGS = {
    "뷰티": [
        "#스킨케어추천 #뷰티템 #화장품추천",
        "#스킨케어 #뷰티추천 #피부관리",
        "#뷰티템 #스킨케어루틴 #화장품",
        "#뷰티 #피부관리 #스킨케어추천",
    ],
    "생활": [
        "#살림템 #생활용품 #주부템",
        "#생활꿀템 #살림 #집꾸미기",
        "#주방용품 #살림템 #생활용품추천",
        "#생활용품 #꿀템 #살림살이",
    ],
    "식품": [
        "#먹스타그램 #간식추천 #쇼핑추천",
        "#식품추천 #맛있는거 #간식",
        "#건강식품 #먹방 #간식템",
        "#간식 #음식추천 #먹스타그램",
    ],
    "패션": [
        "#패션템 #옷추천 #데일리룩",
        "#패션추천 #오오티디 #스타일",
        "#데일리패션 #옷스타그램 #패션",
        "#패션 #옷추천 #스타일링",
    ],
    "default": [
        "#쇼핑추천 #핫템 #꿀템",
        "#득템 #쇼핑 #추천템",
        "#꿀템 #핫딜 #추천",
        "",  # 해시태그 없는 버전도 포함
    ],
}


def _get_hashtags(category_hint: str) -> str:
    pool = _HASHTAGS.get(category_hint, _HASHTAGS["default"])
    return random.choice(pool)


def _parse_price(price_str: str) -> int:
    try:
        return int("".join(filter(str.isdigit, price_str)))
    except Exception:
        return 0


def _saved_str(original_price: str, price: str) -> str:
    orig = _parse_price(original_price)
    cur = _parse_price(price)
    if orig > cur > 0:
        return f"{orig - cur:,}원"
    return ""


# ── 글1: 자연스러운 추천 (링크 없음) ──────────────────────────────────────

def _post1_friend(name: str, price: str, discount_rate: int) -> str:
    short = name[:28] + ("..." if len(name) > 28 else "")
    variations = [
        f"야 이거 봐\n\n{short}\n{price}인데 진짜 괜찮더라\n\n나쁘지 않지 않음?",
        f"이거 어때\n\n{short}\n{price}에 파는데\n요즘 이 가격 보기 쉽지 않더라",
        f"오늘 이거 발견했는데\n\n{short}\n{price}\n솔직히 이 가격이면 살만하지 않음?",
    ]
    if discount_rate > 0:
        variations += [
            f"야 이거 {discount_rate}% 할인 중이야\n\n{short}\n{price}\n\n한번 봐봐",
        ]
    return random.choice(variations)


def _post1_observation(name: str, price: str, discount_rate: int) -> str:
    short = name[:28] + ("..." if len(name) > 28 else "")
    variations = [
        f"쇼핑하다가 발견함\n\n{short}\n{price} ← 이 가격 실화?",
        f"아 이거 괜찮은데\n\n{short}\n지금 {price}임\n필요한 사람 참고해",
        f"오늘의 발견\n\n{short}\n{price}\n\n사야 하나 고민 중",
    ]
    if discount_rate > 0:
        variations.append(
            f"오늘 이거 봤는데\n\n{short}\n{price} ({discount_rate}% 할인)\n\n사야 하나 고민 중"
        )
    return random.choice(variations)


def _post1_short(name: str, price: str, discount_rate: int) -> str:
    short = name[:24] + ("..." if len(name) > 24 else "")
    variations = [
        f"{short}\n\n{price}\n\n이 가격 맞음?",
        f"가격 보고 두 번 봤음\n\n{short}\n{price}",
        f"오늘 발견한 거\n\n{short}\n{price}",
    ]
    if discount_rate > 0:
        variations.append(f"{short}\n\n{price} ({discount_rate}% 할인)\n\n이 가격 맞음?")
    return random.choice(variations)


def _post1_empathy(name: str, price: str, discount_rate: int) -> str:
    short = name[:28] + ("..." if len(name) > 28 else "")
    variations = [
        f"요즘 물가 미쳤는데\n\n{short}\n{price}면 그나마 숨통 트이지 않음?",
        f"은근 필요한데 맨날 미뤘던 거\n\n{short}\n지금 {price}임\n이 참에 사볼까 고민 중",
        f"이거 써본 사람 있어?\n\n{short}\n{price}인데 리뷰가 괜찮던데",
    ]
    if discount_rate > 0:
        variations.append(
            f"요즘 물가 미쳤는데\n\n{short} {price}면 그나마 숨통 트이지 않음\n{discount_rate}% 할인 중이래"
        )
    return random.choice(variations)


_POST1_FUNCS = [_post1_friend, _post1_observation, _post1_short, _post1_empathy]
_STYLE_NAMES = ["friend", "observation", "short", "empathy"]


# ── 글2: 링크 게시글 ───────────────────────────────────────────────────────

# 공정위 고지문 (쿠팡파트너스 활성화 시에만 사용)
_AD_DISCLOSURE = "이 게시물은 쿠팡파트너스 활동의 일환으로 수수료를 받을 수 있습니다"

def _post2_link(name: str, price: str, product_url: str, discount_rate: int) -> str:
    """링크 포함 두 번째 게시글"""
    if not product_url:
        return ""

    short = name[:24] + ("..." if len(name) > 24 else "")

    hooks = [
        f"구매 링크 남겨둘게\n\n{short}\n{price}",
        f"링크 여기야\n\n{short}\n{price}",
        f"사고 싶으면 여기\n\n{short}\n{price}",
    ]
    if discount_rate > 0:
        hooks.append(f"링크 여기야\n\n{short}\n{price} ({discount_rate}% 할인)")

    hook = random.choice(hooks)

    if COUPANG_PARTNERS_ACTIVE:
        return f"[광고]\n{hook}\n\n{product_url}\n\n{_AD_DISCLOSURE}"
    else:
        return f"{hook}\n\n{product_url}"


# ── 메인 생성 함수 ─────────────────────────────────────────────────────────

def generate_post(product: dict) -> dict:
    name = product.get("name", "")
    price = product.get("price", "")
    original_price = product.get("original_price", price)
    discount_rate = product.get("discount_rate", 0)
    product_url = product.get("product_url", "")
    category_hint = product.get("category_hint", "default")
    image_url = product.get("image_url", "")

    fn = random.choice(_POST1_FUNCS)
    style_name = _STYLE_NAMES[_POST1_FUNCS.index(fn)]

    body1 = fn(name, price, discount_rate)
    tags = _get_hashtags(category_hint)
    post_text_1 = f"{body1}\n\n{tags}".strip() if tags else body1

    post_text_2 = _post2_link(name, price, product_url, discount_rate)

    logger.info(f"생성 완료 [{style_name}]: {name[:30]}")
    return {
        "post_text_1": post_text_1,
        "post_text_2": post_text_2,
        "image_url": image_url,
        "product": product,
        "style": style_name,
    }


def generate_posts_batch(products: list[dict]) -> list[dict]:
    results = []
    for product in products:
        try:
            results.append(generate_post(product))
        except Exception as e:
            logger.error(f"콘텐츠 생성 실패: {e}")
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test = {
        "name": "비렌다 크림 촉촉한 수분크림 50ml",
        "price": "31,800원",
        "original_price": "",
        "discount_rate": 0,
        "product_url": "https://link.coupang.com/test",
        "category_hint": "뷰티",
        "image_url": "",
    }
    print("=== 글1 (자연스러운 추천) ===")
    for fn, name in zip(_POST1_FUNCS, _STYLE_NAMES):
        print(f"── [{name}] ──")
        body = fn(test["name"], test["price"], test["discount_rate"])
        tags = _get_hashtags(test["category_hint"])
        print(body + (f"\n\n{tags}" if tags else ""))
        print()
    print("=== 글2 (링크) ===")
    print(_post2_link(test["name"], test["price"], test["product_url"], test["discount_rate"]))
