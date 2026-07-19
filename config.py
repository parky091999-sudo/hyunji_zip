from dotenv import load_dotenv
import os
from datetime import date, datetime, timezone, timedelta

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
THREADS_USERNAME = os.getenv("THREADS_USERNAME")
THREADS_PASSWORD = os.getenv("THREADS_PASSWORD")

# Threads 공식 API (Meta Graph API)
# Meta Developer → 앱 → Threads API → 사용자 액세스 토큰
THREADS_ACCESS_TOKEN = os.getenv("THREADS_ACCESS_TOKEN", "")
THREADS_USER_ID = os.getenv("THREADS_USER_ID", "")  # 숫자 ID (조회 방법: poster/threads.py 실행)

# 네이버 개발자센터 - 검색 API (쇼핑)
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")

# Groq API - 폴백용 (무료, 하루 14,400 요청)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Google Gemini API - 본문 생성 메인 모델 (무료 2.0 Flash)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# YouTube Data API v3 - 트렌딩 상품 탐지 (무료, 하루 10,000 units)
# Google Cloud Console → YouTube Data API v3 활성화 → API 키 발급
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

# imgBB 이미지 호스팅 API (선택) - AI 생성 이미지 영구 업로드용
# 무료 발급: https://api.imgbb.com/
# 없으면 pollinations.ai URL 직접 사용 (API 키 불필요)
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY", "")

# 상품 품질 필터
REQUIRE_BRAND = False     # 별점/리뷰수 필터가 더 강력 — 브랜드 필터는 오탈락 많아 비활성화
CHECK_RATING = False      # GitHub Actions IP를 쿠팡이 차단해 별점 확인 불가 → 비활성화
MIN_REVIEW_COUNT = 100    # 최소 리뷰 수
MIN_RATING = 4.5          # 최소 별점

# 쿠팡파트너스 수익화 활성화 여부
# False: 링크만 게시, 광고 고지 없음 (수익 발생 전)
# True:  [광고] 표시 + 공정위 고지문 자동 추가 (파트너스 가입 후 True로 변경)
COUPANG_PARTNERS_ACTIVE = True

# 스케줄 시간 (24시간 기준)
SCHEDULE_TIMES = ["09:00", "13:00", "19:00"]

# 한 번 실행 시 포스팅할 최대 상품 수
MAX_PRODUCTS_PER_RUN = 1

# 쿠팡 스크래핑 대상 URL
COUPANG_URLS = {
    "rocket_deals": "https://www.coupang.com/np/campaigns/82",   # 로켓배송 특가
    "homepage": "https://www.coupang.com",                        # 메인 홈
}

# 데이터 저장 경로
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")

# ── 수익화 전환 & 발행 비율 페이즈 (2026-07-13 사용자 지시) ─────────────────
# 실업급여 수급 종료 → 쿠팡 파트너스 전환 예정일. 이 날짜(KST) 기준으로 상품글
# 발행 빈도가 자동 전환된다. 일상글(casual_post)은 양 페이즈 모두 매일 유지 —
# 성장기·수익화기 어느 쪽에도 도달/팔로워 유입에 유익하므로 줄이지 않는다.
#
#   growth   (~09/20): 수익 0(무태그)·계정 성장기 → 상품글 저빈도.  목표 일상 ~70 : 쿠파스 ~30
#   monetize (09/21~): 파트너스 수익화 → 상품글 증편.               목표 일상 ~50 : 쿠파스 ~50
#
# 2026-07-19 정책: 상품글(사진) 1건 + 영상 1건을 매일 병행 (사용자 지시).
# coupang_posted_today는 사진끼리만, 영상 상한은 osmu stock_publisher가 관리.
MONETIZATION_DATE = date(2026, 7, 31)  # 2026-07-19 사용자 정정: 광고 수익화 9/21→7/31 (osmu MONETIZE_FROM과 동기화)
KST = timezone(timedelta(hours=9))

PHOTO_GATE_DAYS = {"growth": 1, "monetize": 1}   # 사진 상품글 최소 발행 간격(일)
VIDEO_GATE_DAYS = {"growth": 1, "monetize": 1}   # 영상 상품글 최소 간격 — osmu가 동일 값 참조(동기화 유지)


def current_phase(today: date | None = None) -> str:
    """오늘(KST)이 수익화 전환일 전이면 'growth', 이후면 'monetize'."""
    today = today or datetime.now(KST).date()
    return "monetize" if today >= MONETIZATION_DATE else "growth"


def photo_gate_days(today: date | None = None) -> int:
    """현재 페이즈의 사진 상품글 최소 발행 간격(일)."""
    return PHOTO_GATE_DAYS[current_phase(today)]
