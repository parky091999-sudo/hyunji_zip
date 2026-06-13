from dotenv import load_dotenv
import os

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
