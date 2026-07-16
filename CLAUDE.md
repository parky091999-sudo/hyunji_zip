# coupang_pipeline 프로젝트 컨텍스트

## 프로젝트 개요
쿠팡 파트너스 상품을 자동/수동으로 Threads에 포스팅하는 파이프라인.
GitHub Actions로 자동화, GitHub Pages로 상품 페이지 제공.

**저장소:** https://github.com/parky091999-sudo/hyunji_zip (2026-06-13 coupang-pipeline에서 rename)  
**Threads 계정:** @hyunji_ssi (display name: 현지)  
**컨셉:** 1인 가구 자취생 "현지"의 일상 + 가끔 좋은 거 공유 (광고 톤 X)  
**프로필 링크:** https://bit.ly/hyunji_zip → GitHub Pages 리다이렉트  
**상품 페이지:** GitHub Pages (docs/index.html)  
**관리 페이지:** docs/admin.html (PAT: localStorage `kkul_pat`)

---

## 현재 포스팅 현황 (2026-06-11 기준)
[001]~[015] 포스팅 완료. [014]는 단종(쿠팡 링크 dead)으로 페이지에서 숨김
처리(`removed: true` 플래그). next_code = 16.

> **중요:** 쿠팡 파트너스(link.coupang.com 또는 coupang.com) 상품만 포스팅.
> Naver Smartstore, 네이버 쇼핑 등 비쿠팡 상품은 절대 포스팅하지 않음.

## ★2026-07-13 짧은 포맷 대전환 + 격일 빈도 (사용자 지시)
- **본문 = 후킹 첫줄 포함 2~3줄** (사진·영상 공통, `content._generate_short_post`). 리뷰형 장문(400~600자+해시태그) 폐기 — "스레드는 긴 글 안 읽음", 설명은 사진 캐러셀/영상+첫 댓글이 대체.
- **코드 라인**: "제품 정보는 프로필 링크에서 [N] 검색 👆" → **"[N] 정보는 댓글에 👇"** (직링크·공정위는 첫 댓글에 있고, [N]은 중복게시 마커 겸용이라 완전 삭제 대신 경량화).
- **사진 쿠파스 격일(2일 1회)**: `post_gate.photo_posted_within(days=2)` — auto/evening에 배선(영상 쿠파스 2일 1회 페이스와 균형). manual 큐는 사람 의도라 게이트 없음(발행은 기록돼 다음 자동을 뒤로 밈).
- **게이트 주의**: `looks_truncated` 200자 게이트는 짧은 포맷과 충돌해 15자로 하향 — 되돌리면 게시 전멸함.
- **공정위**: 첫 댓글 두 분기(직링크/랜딩폴백) 모두 수수료 고지 포함.

## ★2026-07-16 미발행 버그 수정 + 일상글 숏폼화 (사용자 지시)
- **상품글 미발행 근인 = pending 날짜 드리프트**: `preselect`가 `for_date=내일`로 저장하는데, 크론 지연(7~12h)으로 실제 게시가 다음날 낮에 실행돼 `_pick_from_pending`(today/yesterday만 허용)과 **매일 불일치** → 실시간 폴백 → 저품질(중국셀러식) 상품 → 본문 게이트 실패 → 미게시. 마지막 상품글이 07-11/07-12(video)에서 멈췄던 원인. **수정: `_pick_from_pending`을 `for_date >= 어제`면 수용(미래날짜 포함, posted_ids가 재게시 차단)으로 완화 — auto_post.py·evening_post.py 양쪽.**
- **일상글 숏폼화**: `_CASUAL_SYSTEM`을 "본문 3~5줄"에서 **2~3줄(최대 4줄) 훅+질문**으로 재작성("스레드는 길면 안 읽음"). `casual_post.py` 길이하한 **100자→20자**(100자 하한이 오히려 장문 강제했음). 종결 허용집합에 **ㅋㅎㅠㅜ 추가**(반말 종결 오탐 차단 해소).
- **자취일기 시리즈 순서 교정**: 번호를 **생성 시점이 아니라 게시 성공 후에만** 소비하도록 분리(`renumber_diary`+`commit_diary_number`). 기존 `_seq_diary_number`는 생성 시 카운터를 먹어, 게이트 차단·발행 실패한 글이 번호만 소모 → 발행 시리즈가 띄엄띄엄 어긋났음.
- **⚠️인스타(릴스)는 이 레포가 아님**: 영상 릴스+스레드 동시게시는 `osmu_pipeline`인데 **GitHub 워크플로가 전혀 없어 집 PC 수동 실행만 가능**. 07-12 이후 안 돌린 게 인스타 미발행 원인 — 클라우드 자동화하려면 별도 워크플로 신설 필요(ffmpeg·TTS·더우인 소싱 등 무거움).

## 포스팅 시간 (post_gate.py 게이트 적용)
- 자동: KST 11~23시 창 (점심 골든)
- 수동: KST 19~23:30시 창 (저녁 골든)
- 일상: KST 8~22시, 댓글: KST 7~24시
- 새벽 게시 물리적으로 차단됨. `workflow_dispatch`는 면제(테스트는 낮에).

## 필터 (014/015 재발 방지)
- `scraper/naver_shopping.is_chinese_seller_style()`: 한국어 단어(2자+) 반복 +
  영문 대문자 브랜드(2자+) 없음 → 차단. naver_shopping과 process_benchmark_urls
  양쪽에 적용.

---

## 핵심 파일 구조

```
scripts/
  auto_post.py       — 매일 08:05 KST 자동 포스팅
  preselect.py       — 매일 09:00 KST 내일 후보 3개 선정 (코드 선점 안 함)
  manual_post.py     — 수동 포스팅 (admin.html에서 트리거)
  fix_post_code.py   — 잘못된 코드 게시글 수정
  remove_post.py     — 비쿠팡 게시글 삭제 전용
  process_benchmark_urls.py — inpock 컬렉션 스캔 (쿠팡 URL만 수집)

generator/
  registry.py        — 상품 코드 관리. mark_posted() 호출 시에만 페이지 노출
  content.py         — 포스팅 텍스트 생성. assign_code_now=False면 코드 미부여

data/
  product_registry.json   — 등록 상품 목록 (posted=True만 페이지 표시)
  feed_posts.json         — 포스팅 이력
  pending_post.json       — 내일 자동포스팅 후보
  manual_queue.json       — 수동 포스팅 큐
  manual_candidates.json  — 벤치마크 스캔 후보 목록
  collection_sources.json — inpock 컬렉션 URL 영구 저장 (16개)
  posted_ids.json         — 중복 방지용 포스팅된 상품 키 목록

docs/
  admin.html   — 관리 페이지 (GitHub Contents API로 data/ 읽기/쓰기)
  index.html   — 상품 페이지
  feed.html    — 피드 페이지
```

---

## GitHub Actions 워크플로우

| 워크플로우 | 트리거 | 역할 |
|-----------|--------|------|
| daily.yml | 매일 23:05 UTC (08:05 KST) | 자동 포스팅 |
| daily_preselect.yml | 매일 00:00 UTC (09:00 KST) | 내일 후보 선정 |
| daily_manual_post.yml | 매일 03:05 UTC (12:05 KST) | 수동 큐 포스팅 |
| process_benchmark_urls.yml | workflow_dispatch | inpock 스캔 |
| fix_post_code.yml | workflow_dispatch | 코드 수정 (OLD_POST_ID/OLD_CODE/NEW_CODE) |
| remove_post.yml | workflow_dispatch | 게시글 삭제 (POST_ID) |
| rebuild_pages.yml | workflow_dispatch | 페이지만 재생성 |

---

## 중요 설계 결정사항

### 코드 선점 방지
`preselect.py`는 `assign_code_now=False`로 실행 → 코드 없이 텍스트만 생성.
실제 코드는 `auto_post.py` / `manual_post.py`에서 포스팅 직전에 부여.
`mark_posted(code)` 호출 후에만 상품 페이지에 노출됨.

### 비쿠팡 필터
`process_benchmark_urls.py`의 `_is_coupang_url()`로 최종 필터링.
`coupang.com`을 포함하지 않는 URL은 candidates에서 제외.

### 수동 관리 탭 (admin.html)
- 좌측: 포스팅 큐 (manual_queue.json)
- 우측: 벤치마크 후보 50개 스크롤 (manual_candidates.json)
- 하단: 선택된 상품 미리보기 + 본문 편집

---

## gh CLI 경로 (이 PC)
`/c/Program Files/GitHub CLI/gh.exe` (PATH 미등록 — 절대경로 사용)

---

## 알려진 이슈 / TODO
- YouTube API 키: 회사 PC 차단됨, 집 PC에서 등록 필요
- Threads Access Token: 만료 시 Meta Developer에서 재발급 필요
- inpock Playwright 스크래핑: 실제 수집량 확인 필요 (Coupang URL이 적은 inpock 계정들)
