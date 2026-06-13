# 현지의 zip 파이프라인 운영 문서

> 집 PC / 직장 PC / 핸드폰 어디서든 이 파일을 Claude에게 붙여넣으면 작업 맥락 공유 가능

---

## 현재 상태 (2026-06-05 기준)

| 항목 | 상태 |
|------|------|
| Threads 계정 | `@hyunji_ssi` (display: 현지, 1인 가구 일상 컨셉) |
| 단축 링크 | http://bit.ly/hyunji_zip → GitHub Pages |
| Threads 포스팅 방식 | **공식 API** (봇탐지 없음) |
| 자동 포스팅 | 매일 오전 8:05 KST (0~55분 랜덤 딜레이) |
| 수동 포스팅 | 매일 낮 12:05 KST (수동 큐에 상품 있을 때만) |
| 사전 선정 | 매일 오전 9:00 KST (다음날 후보 3개 미리 선정) |
| 벤치마크 스캔 | 매주 일요일 23:00 KST (29개 계정 전체 스캔) |
| 관리 페이지 | https://parky091999-sudo.github.io/hyunji_zip/admin.html |
| 상품 페이지 | https://parky091999-sudo.github.io/hyunji_zip/ |

---

## 시스템 개요

```
[전날 09:00 KST] 사전선정 (preselect.py)
  YouTube / 네이버 / 프리셋 → 후보 3개 생성 → pending_post.json 저장

[당일 08:05 KST] 자동 포스팅 (auto_post.py)
  pending_post.json → 승인/기본 후보 선택 → Threads 포스팅
  → docs/index.html, docs/feed.html 업데이트

[당일 12:05 KST] 수동 포스팅 (manual_post.py)
  manual_queue.json 첫 번째 → Threads 포스팅 (큐 없으면 스킵)

[일요일 23:00 KST] 주간 벤치마크 스캔 (full_benchmark_scan.py)
  29개 계정 전체 스캔 → 최대 50개 후보 → manual_candidates.json

[관리 페이지] admin.html
  - 내일 포스팅 후보 승인/반려
  - 수동 큐 순서 관리
  - 벤치마크 후보 선택 → 큐 추가
  - 포스팅 이력 확인
```

---

## 페이지 URL

| 페이지 | URL |
|--------|-----|
| 상품 목록 | https://parky091999-sudo.github.io/hyunji_zip/ |
| 피드 기록 | https://parky091999-sudo.github.io/hyunji_zip/feed.html |

---

## Threads API 정보

| 항목 | 값 |
|------|-----|
| 계정 | @hyunji_ssi (2026-06-13 @kkul_pick711에서 변경) |
| User ID | 26569579222744382 (변경 없음, 핸들만 변경) |
| Meta 앱 이름 | kkul_pick (앱 이름은 그대로, 토큰 영향 없음) |
| Meta 앱 ID | 787758504303097 |
| 토큰 만료 | 2026-07-30 (60일, 만료 전 갱신 필요) |

**토큰 갱신 방법 (60일마다):**
1. Meta Developer → 이용 사례 → Threads API → 설정 → 액세스 토큰 생성하기
2. 브라우저 주소창:
```
https://graph.threads.net/access_token?grant_type=th_exchange_token&client_id=787758504303097&client_secret=앱시크릿&access_token=새단기토큰
```
3. 새 장기 토큰을 GitHub Secret `THREADS_ACCESS_TOKEN` 에 업데이트
4. 로컬 `.env` 파일도 업데이트

---

## GitHub Secrets 현재 등록 목록

Settings → Secrets and variables → Actions

| Secret 이름 | 설명 |
|------------|------|
| `ANTHROPIC_API_KEY` | Claude AI |
| `GROQ_API_KEY` | Groq AI (무료) |
| `NAVER_CLIENT_ID` | 네이버 쇼핑 API |
| `NAVER_CLIENT_SECRET` | 네이버 쇼핑 API |
| `YOUTUBE_API_KEY` | YouTube Data API v3 |
| `THREADS_ACCESS_TOKEN` | Threads 공식 API 장기 토큰 (60일) |
| `THREADS_USER_ID` | 26569579222744382 |

---

## 파일 구조

```
coupang_pipeline/
├── main.py                  ← 파이프라인 진입점 (python main.py)
├── add_product.py           ← 상품 수동 등록 CLI (python add_product.py "상품명")
├── config.py                ← 설정 (품질 필터, 포스팅 수 등)
├── generate_page.py         ← 상품 페이지 생성 (docs/index.html)
├── generate_feed_page.py    ← 피드 페이지 생성 (docs/feed.html)
├── scraper/
│   ├── naver_shopping.py    ← 네이버 쇼핑 API 스크래퍼
│   ├── youtube_trending.py  ← YouTube 트렌딩 → 상품 탐지
│   └── threads_benchmark.py ← 벤치마킹 계정 스캔 → 상품 추출
├── generator/
│   ├── content.py           ← Groq AI 게시글 생성
│   └── registry.py          ← 상품 코드 레지스트리 관리
├── poster/
│   ├── threads.py           ← Threads 공식 API 포스터
│   └── comment_replier.py   ← 댓글 자동 대댓글 (API 기반)
├── data/
│   ├── product_registry.json  ← 등록 상품 + 차단 목록
│   ├── feed_posts.json        ← 포스팅 기록
│   ├── posted_ids.json        ← 중복 포스팅 방지
│   ├── priority_queue.json    ← 우선순위 큐 (수동/벤치마크 상품 대기열)
│   ├── benchmark_accounts.json← 벤치마킹 Threads 계정 목록 (29개)
│   └── profile_pic.png        ← Threads 프로필 사진
├── docs/
│   ├── index.html            ← 상품 페이지 (GitHub Pages)
│   └── feed.html             ← 피드 페이지 (GitHub Pages)
├── .github/workflows/
│   └── daily.yml             ← GitHub Actions 자동화
└── PIPELINE.md               ← 이 파일
```

---

## 수동 조작

### 파이프라인 1회 실행 (포스팅 포함)
```bash
python main.py              # 랜덤 딜레이 포함 (운영용)
python main.py --no-delay   # 즉시 실행 (테스트용)
```

### GitHub Actions 수동 테스트 실행
Actions → Daily Pipeline → Run workflow → **"랜덤 딜레이 건너뛰기" 체크** → Run workflow

### 페이지만 재생성 (포스팅 없이)
```bash
python generate_page.py
python generate_feed_page.py
```

### Threads API 연결 테스트
```bash
python poster/threads.py
```

---

## 상품 관리

### 우선순위 큐 (상품 수동 등록)

**상품명으로 등록:**
```bash
python add_product.py "전동 두피 마사지기"
```
**쿠팡 URL로 등록:**
```bash
python add_product.py --url "https://www.coupang.com/vp/products/..."
```
**큐 조회/삭제:**
```bash
python add_product.py --list        # 현재 큐 목록
python add_product.py --remove 2    # 2번 항목 삭제
python add_product.py --clear       # 전체 삭제
```

**우선순위 정책:**
- `priority=1` (수동): 항상 최우선 포스팅
- `priority=2` (벤치마크): 70% 확률로 우선 사용
- `priority=3` (자동): 큐 비어있거나 30% 확률 시

**벤치마킹 수동 실행:**
```bash
python scraper/threads_benchmark.py
```
→ 29개 계정 중 4개 랜덤 선택 → 게시글 분석 → 상품 추출 → 큐에 priority=2로 추가

### 상품 차단 (재진입 방지)
`data/product_registry.json` → `blocked_item_ids` 배열에 itemId 추가

### 품질 필터 설정
`config.py`:
```python
MAX_PRODUCTS_PER_RUN = 1    # 하루 포스팅 개수
MIN_REVIEW_COUNT = 100      # 최소 리뷰수
MIN_RATING = 4.5            # 최소 별점
```

### 쿠팡파트너스 수익화 전환
`config.py` → `COUPANG_PARTNERS_ACTIVE = True`

---

## 트러블슈팅

### GitHub Actions 실패 시
1. Actions 탭 → 실패 워크플로 → 로그 확인
2. API 키 만료가 대부분 → Secrets 재확인
3. 수동 실행: Actions → Daily Pipeline → Run workflow

### 포스팅이 안 될 때
1. Threads 토큰 만료 확인 (60일) → 위 갱신 방법 참고
2. `python poster/threads.py` 로 연결 테스트
3. Meta Developer에서 앱 상태 확인

### 상품 0개 수집 시
1. 네이버 API 쿼터 확인 (25,000건/일)
2. YouTube API 쿼터 확인 (10,000 units/일)
3. Actions → Run workflow 로 수동 실행

---

## 다른 기기에서 작업 이어가기

**직장 PC / 핸드폰 Claude에서:**
1. 이 PIPELINE.md 내용을 Claude에게 붙여넣기
2. "이어서 작업하자" 라고 말하면 맥락 공유 완료

**직장 PC에서 로컬 실행하려면:**
```bash
git clone https://github.com/parky091999-sudo/hyunji_zip.git
cd hyunji_zip
pip install -r requirements.txt
# .env 파일 새로 만들고 환경변수 입력
```

---

## 남은 작업 목록

- [ ] Threads 프로필 사진 업로드 (data/profile_pic.png 파일)
- [ ] Threads 소개글 설정: `매일 꿀템 하나씩 추천\n제품 정보는 아래 링크를 클릭하세요 👇`
- [ ] Threads 링크 설정: `https://parky091999-sudo.github.io/hyunji_zip/`
- [ ] Meta Developer 앱 시크릿 재설정 (채팅에 노출됨)
- [ ] 쿠팡파트너스 가입 후 `COUPANG_PARTNERS_ACTIVE = True` 전환
- [ ] 60일 후 (2026-07-30) Threads 토큰 갱신

---

## 2026-06-01 작업 이력 (2차)

- `add_product.py` 추가: 상품명/URL → 우선순위 큐(priority=1) 수동 등록 CLI
- `scraper/threads_benchmark.py` 추가: 벤치마킹 계정 29개 랜덤 스캔 → priority=2 큐 추가
- `data/benchmark_accounts.json` 추가: 검증된 쿠팡파트너스 Threads 계정 29개 목록
- `data/priority_queue.json` 추가: 우선순위 큐 저장소
- `main.py` 수정: 우선순위 큐 로직 추가 (P1→P2→자동, 큐<3개 시 벤치마킹 자동 보충)

---

## 2026-06-01 작업 이력

- `daily.yml` 시크릿 수정: `THREADS_USERNAME/PASSWORD` → `THREADS_ACCESS_TOKEN/USER_ID`
- cron `0 0 * * *` → `5 0 * * *` (정각 부하 회피, 09:05 KST)
- 테스트용 딜레이 스킵 옵션 추가: `--no-delay` 플래그, Actions `skip_delay` 체크박스
- `poster/threads.py`: permalink 조회 전 5초 대기 (색인 미완료 대응)
- `main.py`: 포스팅 후 `feed_posts.json`에 `threads_url` 업데이트 로직 추가
- `generator/content.py`: 한국어 전용 생성 지시 추가 (다국어 혼입 방지)
- 2026-06-01 테스트런 성공 확인 (상품코드 002, 포스팅 완료)
