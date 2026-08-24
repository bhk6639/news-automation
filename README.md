# news-automation

반도체 뉴스를 매일 자동으로 수집, 선별, 요약해서 노션 데이터베이스에 정리하는 파이프라인.

Python이 담당하는 **기계적인 전처리**(수집, 중복 제거, 키워드 점수, 본문 추출, 집계)와 클로드 루틴이 담당하는 **판단 작업**(중요도 재평가, 요약, 카테고리 분류, 노션 기록)을 분리한 구조다. 무거운 크롤링과 반복 집계는 GitHub Actions가 처리하고, 클로드는 정제된 JSON 하나만 읽는다.

---

## 목차

1. [자동화 경로 4개](#자동화-경로-4개)
2. [스케줄](#스케줄)
3. [폴더 구조](#폴더-구조)
4. [데일리 파이프라인 7단계](#데일리-파이프라인-7단계)
5. [점수 체계](#점수-체계)
6. [쿼터와 중복 제거](#쿼터와-중복-제거)
7. [본문 확보 전략](#본문-확보-전략)
8. [출력 JSON 스키마](#출력-json-스키마)
9. [화요일 보강 루틴](#화요일-보강-루틴)
10. [온디맨드 심화요약](#온디맨드-심화요약)
11. [노션 데이터베이스 스키마](#노션-데이터베이스-스키마)
12. [클로드 루틴 프롬프트](#클로드-루틴-프롬프트)
13. [설치 및 로컬 실행](#설치-및-로컬-실행)
14. [GitHub Actions 설정](#github-actions-설정)
15. [진단 도구](#진단-도구)
16. [튜닝 포인트](#튜닝-포인트)
17. [트러블슈팅](#트러블슈팅)
18. [보안 주의사항](#보안-주의사항)

---

## 자동화 경로 4개

이 저장소는 독립적인 자동화 경로 네 개를 굴린다. 셋은 외부 스케줄러가 깨우고, 하나는 사용자가 버튼으로 깨운다.

### 1. 데일리 파이프라인

```
[외부 스케줄러]
     |  repository_dispatch: daily-news
     v
[Actions: daily.yml] -- python -m src.main 반도체
     |
     |  RSS 8개 수집 -> resolve -> 시간 필터 -> URL 중복 제거
     |  -> 버킷 점수 -> 제목 중복 제거 -> 쿼터 -> 본문 추출
     |
     v  data/YYYY-MM-DD.json + data/latest.json 커밋
[raw.githubusercontent]
     |
     |  curl 1회
     v
[클로드 루틴 - 데일리]
     신선도 검증 -> LLM 재점수 -> 상위 5건 -> 요약/카테고리
     -> 브리핑 작성 -> 노션 create-pages 2회
     v
[노션: 통합 뉴스 DB]
```

### 2. 노션 점검

```
[외부 스케줄러]
     |  repository_dispatch: notion-check
     v
[Actions: notion_check.yml] -- python src/check_notion.py
     |
     |  어제자 "데일리 브리핑" 페이지가 노션에 있는지 REST로 확인
     v
[없거나 API 실패] -> 슬랙 Incoming Webhook 경고
```

### 3. 화요일 보강 (루틴 A + B)

```
[외부 스케줄러]
     |  repository_dispatch: tuesday-review
     v
[Actions: tuesday.yml]
     |-- python tuesday_prep.py   (루틴 B용 집계: 최근 7일 JSON)
     |-- python weekly_prep.py    (루틴 A용 조회: 노션 REST, continue-on-error)
     v  data/tuesday_prep.json + data/weekly_prep.json + 로그 커밋
[raw.githubusercontent]
     |
     +--> [클로드 루틴 A] weekly_prep.json -> 요약 보완 + 주간 브리핑 -> 노션 + 슬랙
     +--> [클로드 루틴 B] tuesday_prep.json -> 키워드/노이즈 리뷰 -> 슬랙
```

### 4. 온디맨드 심화요약

```
[노션 DB에서 "심화요약요청" 체크]
     |
     |  노션 버튼 "URL 열기" (GET)
     v
[Cloudflare Worker]  GET을 POST로 변환 + 디바운스
     |
     |  클로드 루틴 API 트리거로 POST
     v
[클로드 루틴 - 심화요약]
     노션 REST로 체크된 행 조회 -> 원문 web_fetch -> 한줄핵심 + 상세요약
     -> notion-update-page (기록 + 체크 해제) -> 슬랙 알림
```

핵심 설계 의도는 넷이다.

- **크롤링과 판단의 분리.** 파이썬은 판단하지 않고 클로드는 크롤링하지 않는다. 기계적 집계는 전부 파이썬으로 내려 LLM 토큰을 판단에만 쓴다.
- **원격 실행 전제.** 모든 클로드 루틴은 컴퓨터가 꺼져 있어도 도는 원격 예약 루틴이다. 그래서 로컬 파일에 접근할 수 없고, 입력은 항상 GitHub에 커밋된 JSON을 fetch하는 방식이다.
- **조용한 실패 방지.** 각 루틴 첫 단계에 중단 가드가 있다. fetch 실패, 응답 잘림, `generated_at` 날짜 불일치 중 하나라도 걸리면 노션에 아무것도 쓰지 않고 종료한다.
- **토큰 절약.** 본문을 언어별로 잘라 저장하고, 재조회와 재작성 루프를 프롬프트에서 명시적으로 금지한다. 루틴 1회 토큰은 대략 60K 수준이다.

---

## 스케줄

GitHub Actions의 `schedule` 크론은 쓰지 않는다. 부하에 따라 수십 분 지연되거나 건너뛰기 때문이다. 외부 스케줄러(cron-job.org)가 `repository_dispatch`로 정확한 시각에 깨운다.

| 시각 (KST) | 주체 | 동작 |
|---|---|---|
| 매일 03:00 | 외부 스케줄러 | `daily-news` dispatch -> daily.yml |
| 매일 새벽 | 클로드 루틴 (데스크탑 예약) | latest.json fetch -> 노션 기록 |
| 매일 06:30 | 외부 스케줄러 | `notion-check` dispatch -> notion_check.yml |
| 화요일 03:30 | 외부 스케줄러 | `tuesday-review` dispatch -> tuesday.yml |
| 화요일 04:00~04:30 | 클로드 루틴 A/B | prep.json fetch -> 노션/슬랙 |
| 수시 | 사용자 (노션 버튼) | Cloudflare Worker -> 심화요약 루틴 |

화요일 루틴을 prep 커밋 직후에 돌리면 안 된다. `raw.githubusercontent`는 CDN 캐싱으로 커밋 후 10분 이상 지연될 수 있어, 30분 이상 간격을 둔다.

---

## 폴더 구조

```
news-automation/
├── .github/
│   └── workflows/
│       ├── daily.yml           # daily-news    : 데일리 파이프라인 + data/ 커밋
│       ├── notion_check.yml    # notion-check  : 노션 기록 누락 감시 + 슬랙 알림
│       └── tuesday.yml         # tuesday-review: 루틴 A/B prep 생성 + 커밋
├── config/
│   ├── settings.py             # 전역 설정값 (임계값, 쿼터, 타임아웃, 길이 제한)
│   ├── sources.py              # RSS 소스 8개
│   └── keywords.py             # 버킷 키워드 + WEIGHTS + BUCKET_CAPS + BUCKET_WEIGHTS + ALIASES
├── src/
│   ├── main.py                 # 진입점, 7단계 순차 실행
│   ├── collect.py              # RSS 수집 + summary 정제 + content:encoded 본문 추출
│   ├── resolve.py              # Google News 링크 디코딩 + BLOCKED_HOSTS 드롭
│   ├── filter.py               # 시간 필터, URL 중복, 버킷 점수, 제목 중복, 쿼터
│   ├── extract.py              # 본문 확보 (RSS 본문 우선 -> trafilatura 재크롤)
│   ├── save.py                 # JSON 직렬화 + 고정 기준 정규화
│   └── check_notion.py         # 노션 기록 검증 + 슬랙 알림
├── data/
│   ├── latest.json             # 데일리 루틴이 읽는 최신 결과
│   ├── YYYY-MM-DD.json         # 날짜별 영구 아카이브
│   ├── tuesday_prep.json       # 루틴 B 집계 결과
│   ├── tuesday_log.json        # 루틴 B 실행 로그 (append)
│   ├── weekly_prep.json        # 루틴 A 노션 조회 결과
│   └── weekly_log.json         # 루틴 A 실행 로그 (append)
├── docs/
│   ├── prompt-daily.md             # 클로드 루틴 프롬프트 - 데일리
│   ├── prompt-tuesday-a-weekly.md  # 클로드 루틴 프롬프트 - 화요일 A (주간 브리핑)
│   ├── prompt-tuesday-b-review.md  # 클로드 루틴 프롬프트 - 화요일 B (분석 검토)
│   └── prompt-deep-summary.md      # 클로드 루틴 프롬프트 - 온디맨드 심화요약
├── workers/
│   └── deep-summary-worker.js  # Cloudflare Worker (노션 버튼 GET -> 루틴 POST 릴레이)
├── tuesday_prep.py             # 루틴 B 기계적 집계 (최근 7일 JSON 분석)
├── weekly_prep.py              # 루틴 A 기계적 조회 (노션 REST 페이지네이션)
├── measure_tech_density.py     # 읽기 전용 진단 스크립트
├── requirements.txt
└── README.md
```

---

## 데일리 파이프라인 7단계

`src/main.py`가 순차 실행한다.

### 1. RSS 수집 (`src/collect.py`)

`config/sources.py`의 `SOURCES`를 읽어 8개 피드를 `feedparser`로 파싱한다.

| 이름 | 종류 | 역할 |
|---|---|---|
| GoogleNews_반도체 | Google News (ko) | 광범위 catch-all. 쿼리는 순수 `반도체` 한 단어 |
| GoogleNews_기술 | Google News (ko) | 기술어 부스터. EUV, 노광, 식각, 증착, CMP, HBM, D램, 낸드, CXL, 하이브리드본딩, GAA, 첨단패키징 |
| GoogleNews_EN | Google News (en/US) | 영문 속보. semiconductor, HBM, DRAM, foundry, TSMC, memory chip |
| SemiEngineering | 직접 RSS | 해외 제조, 계측, 수율 심층 (영문) |
| BlocksAndFiles | 직접 RSS | 해외 메모리, 스토리지 전문 (영문) |
| THELEC_반도체 | 직접 RSS | 국내 반도체 섹션 전용 |
| KIPOST | 직접 RSS | 국내 소부장 전문 (전체 피드를 키워드로 거름) |
| EETimes | 직접 RSS | 해외 소자, EDA, 공정 (영문) |

Google News 쿼리를 두 개로 쪼갠 이유가 있다. 단일 피드는 100건 상한이 걸려 있어서, `반도체` 하나로만 긁으면 정치나 지역 기사가 상한을 채워 실제 반도체 뉴스를 밀어낸다. 기술어 부스터는 별도 100건 상한을 받아 고가치 공정 기사를 따로 건진다. 이때 `반도체장비`, `반도체소재`, `소부장` 같은 단어를 부스터 쿼리에 넣으면 안 된다. `반도체`로 퍼져 정치 기사를 다시 끌어온다는 게 실측으로 확인됐다.

수집 항목의 필드는 이렇다.

```python
{"title", "link", "published", "summary", "rss_body", "source_name", "rss_source"}
```

`rss_body`는 `content:encoded`로 본문 전체를 주는 피드(SemiEngineering 등)에서 뽑은 평문이다. 없으면 빈 문자열이다. `source_name`은 Google News의 실제 매체명을 우선 쓰고, 직접 피드는 피드명으로 폴백한다.

### 2. URL resolve (`src/resolve.py`)

Google News RSS 링크는 리다이렉트 URL이라 `googlenewsdecoder`로 실제 언론사 URL로 바꾼다.

- 디코딩 실패, 결과가 여전히 구글 도메인이면 버린다.
- `BLOCKED_HOSTS`(현재 `msn.com`)에 걸리면 버린다. 아그리게이터라 본문 추출이 항상 실패하고, 원문은 원매체로 따로 들어오기 때문에 잃는 게 없다.
- 직접 RSS 피드의 URL은 디코딩 없이 통과하되 `BLOCKED_HOSTS` 검사는 받는다.

파이프라인에서 가장 느린 단계다. 항목당 1초 간격을 둔다.

### 3. 시간 필터 (`src/filter.py`)

`published`가 `TIME_WINDOW_HOURS`(24) 이내인 것만 남긴다. `published`가 없으면 버린다.

### 4. URL 중복 제거 (`src/filter.py`)

resolve된 최종 URL의 SHA1 해시로 중복을 판정한다.

### 5. 점수와 선별 (`src/filter.py`)

버킷 기반으로 채점한 뒤 정렬, 제목 중복 제거, 임계값 컷, 쿼터 보정을 거쳐 상위 `TOP_N_FOR_EXTRACT`(15)건을 고른다. 자세한 내용은 [점수 체계](#점수-체계)와 [쿼터와 중복 제거](#쿼터와-중복-제거)를 본다.

### 6. 본문 확보 (`src/extract.py`)

RSS 본문 우선, 없으면 `trafilatura` 재크롤. 자세한 내용은 [본문 확보 전략](#본문-확보-전략)을 본다.

### 7. JSON 저장 (`src/save.py`)

`data/YYYY-MM-DD.json`으로 저장하고 `data/latest.json`으로 복사한다. 날짜는 KST 기준이다.

---

## 점수 체계

키워드를 **의미 버킷 + 버킷별 상한 + 버킷 배수** 구조로 채점한다. 평면 가중치 방식에서 넘어온 이유는, 한 차원(예: 회사명)만 도배한 기사가 여러 차원을 건드린 기사를 점수로 이기는 문제 때문이었다.

### 버킷

| 버킷 | 뜻 | cap | 배수 | 의도 |
|---|---|---|---|---|
| `entity` | 누가 (기업, 주체) | 5 | 1.0 | 회사명 나열로 점수를 끌어올리지 못하게 |
| `product` | 무엇을 (상품) | 5 | 1.0 | 제품명 나열이 회사명보다 높을 이유가 없어 5로 낮춤 |
| `tech` | 어떻게 (기술, 공정) | 10 | **1.3** | 기술 기사가 단독으로 상위에 오를 수 있게 |
| `event` | 무슨 일 (사건, 액션) | 5 | 1.0 | |
| `domain` | 분야 배경어 | 2 | 1.0 | 변별력 없는 범용어는 바닥값만 |
| `negative` | 감점 (버킷 밖) | 상한 없음 | 하한 `NEG_FLOOR` = -6 | |

`tech`의 cap이 가장 높고 배수까지 받는다. 같은 cap이라도 기술 기사가 시장 뉴스를 넘어서게 만드는 장치다. 배수를 1.6까지 올려봤으나 과해서 1.3으로 낮췄다.

### tier 가중치

```python
WEIGHTS = {"critical": 5, "strong": 3, "medium": 2, "weak": 1,
           "neg_strong": -3, "neg_weak": -2}
```

`critical`(+5)은 나중에 신설한 최상위 tier다. 배치 의도는 이렇다.

- **critical (+5)** — 차세대 메모리 공정과 노드. DRAM 세대와 구조(1a~1d, 4F2, 수직D램, BCAT, VCT, 새들핀, 매립게이트, IGZO, 셀 커패시턴스 타깃), NAND 단수(128단~1000단, 셀온페리, 채널홀), HBM 단수(8단~24단), 차세대메모리(CXL, PIM, MRAM, FeRAM, STT-MRAM, SOT-MRAM, FeFET), 노드(0.7나노~3나노), EUV, high-NA
- **strong (+3)** — 로직 트랜지스터(GAA, CFET, forksheet, RibbonFET, PowerVia, 후면전력), 노광과 패터닝(노광, 펠리클, 다중패터닝), 식각과 고종횡비, HKMG, HBM 적층기법(MR-MUF, 하이브리드본딩), 그리고 **박막공정 전반**(박막, 증착, ALD, CVD, PVD, PECVD, 선택적증착, AS-ALD, 컴포멀리티, 몰리브덴, Ru, TiN). 사건 쪽에서는 양산과 램프업
- **medium (+2)** — 일반 단위공정(이온주입, CMP, 에피, 습식식각), 계측과 검사, 소재, 패키징 브랜드(CoWoS, SoIC, Foveros, 팬아웃, 유리기판), 신뢰성과 결함(번인, seam, void, 웨이퍼보우)
- **weak (+1)** — 배경 기업명, 배경어

범용어(전공정, 후공정, 패키징, 첨단공정, 미세화)는 tech에서 빼서 domain으로 내렸다. 너무 범용이라 tech 배수를 받으면 안 되기 때문이다.

### 계산

위치 가중치는 제목 `TITLE_WEIGHT`(1.5), summary `BODY_WEIGHT`(1.0)다. 이름과 달리 `BODY_WEIGHT`는 **summary에 곱한다.** 본문은 파이썬 점수에 쓰이지 않는다. 제목과 summary만 채점한다.

```
버킷별 raw   = Σ(tier가중치 × 위치가중치)     # canon 기준 위치별 1회
버킷별 capped = min(버킷 raw, cap)
score_raw    = Σ(capped × BUCKET_WEIGHTS) + max(neg, NEG_FLOOR)
score        = min(10, max(0, score_raw) / SCORE_REF × 10)     # SCORE_REF = 28.0
```

정규화 기준이 고정값(`SCORE_REF`)인 이유가 있다. 예전에는 배치 최댓값으로 나눴는데, 한 건만 점수가 튀면 나머지가 전부 눌려 4.71 같은 값에 동률로 몰렸다. 변별력이 죽는다. 고정 기준으로 바꾸면서 날짜 간 점수 비교도 가능해졌다.

### ALIASES

같은 개념의 국문, 영문, 별칭을 하나로 접어 1회만 카운트한다. `하이닉스`/`하닉`/`hynix`, `DRAM`/`D램`/`디램`, `HBM`/`HBM3E`/`HBM4` 같은 묶음이다.

세트 묶음도 있다. `노드`(0.7나노~3나노 전체), `DRAM세대`(1a~1d), `단수`(NAND와 HBM 적층 단수 전체)를 각각 한 canon으로 묶어, 한 기사에 2나노와 3나노가 같이 나와도 +1만 받는다.

같은 버킷 안에서 tier는 `critical` -> `strong` -> `medium` -> `weak` 순으로 순회한다. 그래서 `{본딩(medium), 하이브리드본딩(strong)}` 묶음은 "하이브리드본딩"이 언급되면 +3, 일반 "본딩"만 있으면 +2로 자동 분리된다.

### 키워드 매칭 규칙

`filter._kw_pattern`이 정규식으로 경계를 잡는다.

- 대소문자 무시. 영문 `Foundry`와 `foundry`를 같이 잡는다.
- 왼쪽 경계: 앞에 ASCII 영숫자가 오면 차단. `anode`의 `node`, `21c`의 `1c`를 막는다.
- 오른쪽 경계: 뒤에 ASCII **글자**만 차단하고 **숫자는 허용**한다. `fab`이 `fabric`에 안 걸리면서 `HBM`이 `HBM3E`를, `GDDR`이 `GDDR7`을 잡는다.
- 한쪽 끝이 한글이면 그쪽 경계는 없다. `SK하이닉스가`의 `하이닉스`, `DDR5메모리`의 `메모리`가 잡힌다.
- **DRAM 세대코드 특례**: `1a`~`1d`는 단독이면 `1 billion`, `1D`, `1A` 등과 오매칭된다. 그래서 뒤에 `나노`, `nm`, `D램`, `DRAM` 컨텍스트가 올 때만 매칭한다. `1c D램`, `1cnm`은 잡히고 `1b 달러`는 안 잡힌다.

---

## 쿼터와 중복 제거

`score_and_filter`가 점수 부여 이후 아래 순서로 처리한다.

```
채점 -> 점수 내림차순 정렬 -> 제목 중복 제거 -> 임계값 컷(4)
-> top-15 자르기 -> 영문 쿼터(3) -> tech 쿼터(2) -> dropped 수집(20건)
```

### 제목 중복 제거

같은 사건을 여러 매체가 거의 동일한 제목으로 재배포한 **완전복사본만** 제거한다.

제목을 정규화(끝의 ` - 매체명` 제거, 기호와 공백 제거, 소문자화)한 뒤 글자 trigram Jaccard 유사도가 `TITLE_DEDUP_SIM`(0.85) 이상이면 중복으로 보고 최고점 1건만 남긴다. 점수 정렬 직후에 돌기 때문에 대표로 남는 건 항상 최고점이다.

임계값을 일부러 높게 잡았다. 한글 패러프레이즈("1나노 벽 깼다" vs "0.7나노 시대 개막")는 어휘 유사도가 0.1~0.3 수준이라 임계를 못 넘고 통과한다. 이건 의도한 것이다. 의미 기반 클러스터링은 임베딩이 필요해 무겁고, 본문을 읽는 클로드 루틴이 상위 5건 선별할 때 어차피 걸러낸다.

### 영문 쿼터 (`ENGLISH_QUOTA` = 3)

영문 뉴스가 노션에 전혀 안 뜨던 문제를 해결한 장치다. 원인은 수집이나 소스가 아니라 **점수 단계**였다.

채점은 제목과 summary만 본다. 그런데 구글뉴스는 summary가 사실상 제목 반복이라, 영문 기사는 헤드라인 한 줄로만 채점된다. 한글 헤드라인은 키워드를 여러 개 때리지만(예: 하이닉스 + HBM = raw 12) 영문은 보통 하나만 때려서(예: Intel weak = 2.5) 컷(4)을 못 넘고 늘 탈락했다. 버킷 cap이 원인이 아니다. 키워드를 더 넣어도 한 버킷만 때리면 못 넘는다.

해결은 점수 룰을 그대로 두고 쿼터로 강제 진입시키는 것이다. 2단 구조다.

1. **파이썬** — top-15에 영문 피드(`ENGLISH_FEEDS`) 자리 3개를 예약한다. 컷을 우회해 점수 높은 영문 후보를 끌어올리고(점수 > 0 조건), 그만큼 점수 낮은 한글 기사를 뺀다. 영문 후보가 부족하면 있는 만큼만.
2. **데일리 프롬프트** — items에 영문 기사(제목에 한글이 하나도 없음)가 있으면 최종 상위 5건에 1건을 보장한다.

둘 다 있어야 실제로 노션에 뜬다. 파이썬 쿼터는 후보 진입까지만 책임지고, 최종 노출은 프롬프트가 책임진다.

**딥테크 우선슬롯**: 영문 쿼터 3자리를 채울 때 `DEEPTECH_FEEDS`(SemiEngineering, EETimes)를 `GoogleNews_EN`보다 먼저 배정한다. 안정 정렬이라 그룹 내부는 점수순이 유지된다. 딥테크 매체는 낚시성 제목이 많아 점수가 낮지만 신호는 높은데, 시황 영문에 밀려 탈락하던 문제를 막는다.

### tech 쿼터 (`TECH_QUOTA` = 2)

시장 뉴스가 회사명과 제품명으로 `product`, `entity` cap을 채워 top-N을 먹고, 공정 기사가 밀리는 문제를 막는다.

top-15에 **tech 주도** 기사 자리 2개를 보장한다. tech 주도의 판정은 `_is_tech_led` 함수가 하며, `score_detail.buckets`에서 tech가 최댓값인 기사를 말한다.

자리를 만들 때는 **tech도 영문도 아닌** 기사 중 최저점부터 밀어낸다. 영문 쿼터를 보존하기 위한 순서다. EETimes와 SemiEngineering은 영문이면서 tech라 두 쿼터를 동시에 채운다.

### dropped 수집

`dropped_below_threshold`에는 **선정되지 않았고 동시에 점수가 임계값 미만인** 기사만 상위 `DROPPED_KEEP`(20)건까지 담는다. 임계값은 넘었지만 top-15에 못 든 기사는 두 목록 어디에도 안 들어간다.

---

## 본문 확보 전략

`extract.get_body`가 세 갈래로 처리한다.

```
1. rss_body가 있고 길이 >= MIN_BODY_LENGTH(300)  ->  재크롤 없이 그대로 사용   사유 "ok(rss)"
2. 아니면 trafilatura로 기사 URL 재크롤          ->  성공 시 사용             사유 "ok"
3. 재크롤 실패했는데 짧은 rss_body가 있으면       ->  그거라도 사용            사유 "ok(rss-short)"
4. 전부 실패                                    ->  extract_failed로         사유 fetch_fail / no_body / exception
```

**`MIN_BODY_LENGTH`는 더 이상 드롭 기준이 아니다.** 지금은 "RSS 본문을 재크롤 없이 쓸지" 판단하는 용도로만 쓴다. 본문 길이로 기사를 버리지 않고, 본문이 아예 없을 때만 버린다.

이렇게 바꾼 이유는 두 가지다. SemiEngineering처럼 재크롤을 차단하지만 RSS로 전문을 주는 매체를 살리기 위해서고, 짧은 기사라도 제목과 링크만 있는 것보다는 나아서다.

`trafilatura` 호출은 `favor_precision=True`, 댓글과 표 제외로 설정한다. 추출 후 저작권 고지, 무단 전재 문구, 기자 서명 이후를 잘라낸다. 실패 시 1회 재시도하고 항목 간 1초 대기한다.

`PARALLEL_EXTRACT`를 `True`로 바꾸면 `ThreadPoolExecutor` 4워커로 병렬 처리한다. 분야를 늘릴 때 켠다.

추출에 실패한 기사도 버리지 않고 `extract_failed`에 담는다. 클로드 루틴이 제목과 링크만으로 별도 페이지를 만들어, 나중에 사람이 직접 확인할 수 있게 한다.

---

## 출력 JSON 스키마

`data/latest.json` 구조다.

```json
{
  "generated_at": "2026-08-24T03:14:22.123456+09:00",
  "field": "반도체",
  "field_date": "2026-08-24",
  "stats": {
    "collected_total": 210,
    "after_resolve": 168,
    "after_time_filter": 132,
    "after_dedup": 121,
    "after_score_filter": 15,
    "extracted_success": 13,
    "extracted_failed": 2
  },
  "keywords_snapshot": {
    "strong": ["..."], "medium": ["..."], "weak": ["..."],
    "neg_strong": ["..."], "neg_weak": ["..."]
  },
  "items": [
    {
      "title": "기사 제목 - 매체명",
      "date": "2026-08-24",
      "source": "매체명",
      "url": "https://...",
      "summary": "RSS summary 정제본",
      "body": "본문. 영문 1000자 / 한글 600자",
      "score": 7.32,
      "score_raw": 20.5,
      "score_detail": {
        "buckets": {"entity": 4.5, "product": 5, "tech": 6.5, "event": 0, "domain": 2},
        "bucket_hits": {"entity": ["하이닉스"], "tech": ["ALD", "박막"]},
        "title_hits": ["하이닉스", "HBM"],
        "summary_hits": ["HBM"],
        "negative_hits": []
      }
    }
  ],
  "dropped_below_threshold": [
    {"title": "...", "url": "...", "source": "...", "score": 2.5, "score_detail": {}}
  ],
  "extract_failed": [
    {"title": "...", "url": "...", "source": "...", "score": 8.4, "reason": "fetch_fail"}
  ]
}
```

필드별 용도는 이렇다.

- `items` — 본문 확보까지 성공한 기사. 클로드 데일리 루틴의 주 입력이다.
- `extract_failed` — 본문 확보 실패 기사. 제목과 링크만으로 노션에 기록한다.
- `dropped_below_threshold` — 임계값 미달 기사. 키워드 튜닝 참고용이며 데일리 루틴은 무시하고 화요일 루틴 B가 읽는다.
- `keywords_snapshot` — 실행 시점의 키워드 사전을 평탄한 tier별 목록으로 펼친 것. 화요일 루틴 B의 죽은 키워드 탐지에 쓰인다.
- `generated_at` — 모든 루틴의 신선도 검증 기준. 이 값의 날짜가 오늘(KST)이 아니면 루틴이 작업을 중단한다.

`score_detail`의 `buckets`와 `bucket_hits`는 버킷 구조 도입 때 추가됐다. `title_hits`, `summary_hits`, `negative_hits`는 `tuesday_prep.py`가 이 키로 읽기 때문에 레거시 호환용으로 유지한다. 두 계열이 공존하므로 옛 JSON과 새 JSON을 모두 읽을 수 있다.

---

## 화요일 보강 루틴

일주일에 한 번, 데일리가 놓친 것을 메우고 파이프라인 자체를 점검한다. A와 B가 같은 워크플로에서 준비되고 각각 다른 클로드 루틴이 소비한다.

`tuesday.yml`에서 `weekly_prep` 스텝은 `continue-on-error: true`로 격리되어 있다. A의 노션 조회가 실패해도 B의 커밋을 막지 않기 위해서다. 커밋은 `git add -A data/`로 A와 B의 prep을 일괄 처리한다.

### 루틴 A — 주간 브리핑과 요약 보완

**`weekly_prep.py`(파이썬)**: 노션 DB를 REST API로 조회한다.

- 시작일 = 가장 최근 "주간 브리핑" 페이지의 날짜 + 1일. 없으면 어제 기준 7일 윈도우(어제 - 6).
- 종료일 = 어제(KST).
- 카테고리 "데일리 브리핑"과 "주간 브리핑"은 제외한다.
- `has_more`가 끝날 때까지 페이지네이션으로 전부 가져온다.
- 결과는 `data/weekly_prep.json` (window, empty, pages[], total, summary_empty_count) + `data/weekly_log.json` append.

읽기를 파이썬으로 분리한 이유가 있다. 노션 MCP의 `notion-fetch`는 데이터소스를 조회하면 스키마만 반환하고 행을 주지 않아 날짜와 카테고리 필터 쿼리가 불가능하다. `notion-search`는 시맨틱 검색에 25건 한계라 누락이 생긴다. "기간 내 전체 페이지 빠짐없이 읽기"는 REST의 필터 쿼리로만 확실하다.

**클로드 루틴 A**: `weekly_prep.json`을 fetch해서 판단한다.

1. `summary_empty == true`인 페이지의 `link`를 `web_fetch`로 읽어 요약을 보완한다. 403 차단(biz.chosun.com 등)이면 곧바로 실패 처리하지 않고 **웹 검색으로 보완**을 먼저 시도하고, 성공하면 요약 끝에 `(원문 차단 — 웹검색 보완)`을 표기한다.
2. 확보한 전체 페이지를 근거로 그 주 중요 뉴스 5~8건을 중요도순으로 골라 주간 브리핑 페이지를 만든다.
3. 완료 슬랙 알림 한 줄.

### 루틴 B — 파이프라인 분석 검토

**`tuesday_prep.py`(파이썬)**: `data/`의 최근 7일 날짜 JSON을 읽어 집계한다. 순수 집계만 하고 판단은 전혀 하지 않는다.

| 집계 항목 | 내용 |
|---|---|
| `stats_trend` / `stats_avg` | 날짜별 수집량, 통과 건수, 추출 성공/실패 추세와 평균 |
| `dropped_candidates` | 탈락 기사 상위 25건. URL 기준 중복 제거, 같은 기사가 여러 날 나오면 최고점만 |
| `keyword_usage` | 키워드별 히트 수 (선정 + 탈락 기사 전체) |
| `dead_keywords` | 최근 7일 한 번도 안 걸린 현재 키워드 |
| `negative_usage` | 감점 키워드별 히트 수 |
| `passed_with_negative` | 선정됐는데 감점 키워드가 붙은 기사 (노이즈 통과 의심) |
| `extract_failed` | 사유별, 소스별 실패 집계. `too_short(41자)`는 `too_short`로 정규화 |
| `selected_source_distribution` | 선정 기사의 매체 분포 상위 15 (편향 확인) |

**클로드 루틴 B**: `tuesday_prep.json`을 fetch해서 누락, 키워드, 노이즈, 추출 실패, 추세 5가지를 리뷰하고 슬랙으로 보고한다. 노션은 건드리지 않는다.

`dead_keywords`가 의미를 가지려면 스냅샷과 usage가 같은 축이어야 한다. `score_detail`의 hits는 canon으로 기록되므로 `keyword_usage`도 canon 단위인데, `keywords_snapshot`을 표면형으로 저장하면 canon이 아닌 별칭(하닉, hynix, D램, 176단)은 실제로 아무리 많이 걸려도 매칭이 안 돼 영원히 dead로 찍힌다. 그래서 `save.keywords_snapshot`이 저장 시점에 canon으로 접는다.

접은 뒤에도 dead가 곧 삭제는 아니다. 세트 묶음(`노드`, `DRAM세대`, `단수`)은 canon 하나가 표면형 수십 개를 대표하므로 세트 단위로 판단해야 하고, 차세대 개념(CFET, FeFET, 4F2, IGZO)은 몇 주 무매칭이 정상이다. 정리 후보로 올릴 것은 흔한 개념인데 7일 내내 0회인 것, 즉 표현이 어긋났을 가능성이 높은 쪽이다.

원칙은 **자동 개선 금지**다. 리뷰 후 슬랙으로 제안만 하고, `settings.py`나 `keywords.py` 변경은 사람이 확인한 뒤 적용한다.

---

## 온디맨드 심화요약

데일리 자동수집과 별개로, 노션에서 고른 기사의 본문을 더 깊게 읽어 추가 요약을 다는 기능이다. 사용자가 원할 때 버튼 한 번으로 실행된다.

### 왜 Worker 릴레이인가

무료 플랜 노션은 버튼의 "Send webhook"(외부 POST)이 유료 전용이다. "URL 열기"(GET)만 쓸 수 있다. Cloudflare Worker가 그 GET을 받아 클로드 루틴의 API 트리거 POST로 변환한다.

Worker는 두 가지를 더 한다. `?key=` 파라미터를 `BUTTON_KEY` 시크릿과 대조해 아무나 워커 주소를 눌러 루틴을 깨우는 걸 막고, Cloudflare 엣지 캐시를 마커로 써서 30초 디바운스를 건다. 브라우저나 노션이 같은 URL을 짧은 시간에 두 번 요청해도 트리거는 한 번만 나간다.

Worker 코드는 `workers/deep-summary-worker.js`에 있다. 비밀값은 전부 환경변수(`TRIGGER_URL`, `TRIGGER_SECRET`, `BUTTON_KEY`, `DEBOUNCE_SECONDS`)로 빼두어 코드 자체에는 아무 비밀도 없다. 배포 절차는 파일 상단 주석에 적혀 있다.

### 루틴 동작

1. 노션 REST `POST /v1/databases/{id}/query`에 `심화요약요청 = true` 필터로 체크된 행을 조회한다. 결정론적이라 내용이 적은 페이지도 누락되지 않는다.
2. 각 행의 `링크`를 `web_fetch`로 읽는다. 403 차단이면 웹 검색으로 보완하고 한줄핵심에 `(원문 차단 — 웹 검색 보완)`을 표기한다.
3. 한줄핵심(180자 이내)과 상세 심화요약(8~12문장)을 만든다.
4. `notion-update-page`로 `심화요약핵심` 속성에 한 줄, 페이지 본문에 `🔎 심화요약 (M/D)` 섹션으로 상세를 붙이고, `심화요약요청` 체크를 해제한다.
5. 슬랙 알림. 실패하면 PushNotification으로 폴백한다.

체크 해제를 각 행 기록 직후에 하는 게 중요하다. 재실행 루프를 막는다.

### 환경 제약

이 API 트리거 루틴은 데일리나 화요일 루틴과 환경이 다르다. 프록시 허용목록 방식이라 클라우드 환경 설정의 "허용된 도메인"에 `api.notion.com`과 `hooks.slack.com`을 등록해야 `curl`이 동작한다. 환경 변경은 새 세션부터 적용된다.

무료 플랜에서는 MCP의 `query_data_sources`(SQL)와 `query_database_view`가 Business 전용이라 쓸 수 없다. 검색 기반 조회는 내용이 빈약한 페이지를 누락시켜 폐기했고, REST 필터로 확정했다.

커밋된 JSON의 `body`를 본문 소스로 쓰자는 안은 기각했다. `body`는 이미 truncate(한글 600자, 영문 1000자)된 데다 데일리 루틴이 바로 그걸로 요약을 만들었기 때문에, 심화요약이 조금도 더 깊어지지 않는다.

### DB 스키마 추가

`심화요약요청`(checkbox), `심화요약핵심`(rich_text) 두 속성이 필요하다. 데일리와 화요일 자동화는 이 필드를 쓰지 않는다.

---

## 노션 데이터베이스 스키마

루틴이 기록하는 DB(이름: 통합 뉴스 DB)의 속성 구성이다.

| 속성명 | 타입 | 내용 |
|---|---|---|
| 헤드라인 | title | `M/D 헤드라인` 형식. 데일리 브리핑은 `M/D 반도체 데일리 브리핑`. 주간 브리핑은 `시작M/D ~ 어제M/D 주간 브리핑` |
| 날짜 | date | 발행일 기준 YYYY-MM-DD. `is_datetime: 0` |
| 분야 | multi_select | 현재는 `반도체` 하나 |
| 카테고리 | multi_select | 메모리, 파운드리, 장비소재, 설계, 글로벌, 데일리 브리핑, 주간 브리핑, 심화요약, 기술 심화 |
| 요약 | rich_text | 뉴스는 2문장. 데일리 브리핑은 3~4문장 + 빈 줄 + `인사이트: ` 한 문장 |
| 링크 | url | 원문 URL |
| 적합도 1~5 | number | 사용자가 직접 입력하는 피드백. 자동화는 건드리지 않는다 |
| 심화요약요청 | checkbox | 심화요약 트리거. 처리 후 자동 해제 |
| 심화요약핵심 | rich_text | 심화요약 한 줄 핵심 |

### create-pages 속성 형식

```json
{
  "헤드라인": "8/24 SK하이닉스, HBM4 양산 준비 완료",
  "date:날짜:start": "2026-08-24",
  "date:날짜:is_datetime": 0,
  "분야": "[\"반도체\"]",
  "카테고리": "[\"메모리\",\"파운드리\"]",
  "요약": "두 문장 요약.",
  "링크": "https://..."
}
```

여기서 반복적으로 거부당했던 지점이 셋이다.

**multi_select는 JSON 배열을 문자열로 직렬화한 형태만 받는다.** 값이 하나여도 배열이다.

- 맞음: `"[\"메모리\",\"글로벌\"]"`
- 틀림: `"메모리,글로벌"` (쉼표 구분 문자열, 거부됨)
- 틀림: `["메모리","글로벌"]` (실제 배열, 거부됨)

**날짜는 확장키를 쓴다.** `date:날짜:start`에 날짜 문자열, `date:날짜:is_datetime`에 **숫자 0**을 넣는다. 문자열 `"0"`이 아니다.

**카테고리 값은 정확히 일치해야 한다.** 정의된 옵션 외의 값, 오타 한 글자, 띄어쓰기 차이도 전부 거부된다.

링크 속성명은 `링크` 그대로 쓴다. `userDefined` 같은 접두사를 붙이지 않는다.

### 읽기는 REST로

`notion-search`는 쓰지 않는다. 시맨틱 검색에 25건 한계라 누락이 생긴다. MCP `notion-fetch`도 데이터소스의 행을 열거하지 못하고 스키마만 반환한다. **필터 기반 DB 행 읽기는 파이썬 Notion REST API**(`POST /v1/databases/{id}/query`, 필터 + 페이지네이션)로 한다. MCP는 단건 fetch와 쓰기에만 쓴다.

---

## 클로드 루틴 프롬프트

프롬프트 전문은 `docs/`에 있다.

| 파일 | 루틴 | 입력 | 출력 |
|---|---|---|---|
| [`docs/prompt-daily.md`](docs/prompt-daily.md) | 데일리 | `data/latest.json` | 노션 (뉴스 + 추출실패 + 브리핑) |
| [`docs/prompt-tuesday-a-weekly.md`](docs/prompt-tuesday-a-weekly.md) | 화요일 A | `data/weekly_prep.json` | 노션 (요약 보완 + 주간 브리핑) + 슬랙 |
| [`docs/prompt-tuesday-b-review.md`](docs/prompt-tuesday-b-review.md) | 화요일 B | `data/tuesday_prep.json` | 슬랙 |
| [`docs/prompt-deep-summary.md`](docs/prompt-deep-summary.md) | 심화요약 | 노션 REST (체크된 행) | 노션 (속성 + 본문) + 슬랙 |

모두 클로드 데스크탑의 원격 예약 루틴으로 실행된다. 컴퓨터가 꺼져 있어도 돌고, GitHub Actions도 아니다. 로컬 파일에 접근할 수 없어서 데이터는 항상 `raw.githubusercontent`에서 `curl`로 가져온 커밋된 JSON만 쓴다.

### 프롬프트 설계에서 반복되는 패턴

운영하면서 실제로 사고가 났던 지점과 그 대응이다.

**중단 가드.** 모든 루틴 첫 단계에 있다. fetch 실패, 응답 잘림, `generated_at` 날짜 불일치. 파이프라인이 실패해서 어제 JSON이 그대로 남아 있는 날, 루틴이 그걸로 페이지를 또 만드는 사고가 있었다. 갱신 실패 시 아무것도 안 쓰고 중단하는 편이, 잘못된 페이지를 만든 뒤 사람이 지우는 것보다 낫다.

**요약본 반환 감지.** curl 결과가 길면 중간에서 요약되어 전달되는 경우가 있다. 요약본으로 작업하면 존재하지 않는 기사를 지어낸다. `items` 개수와 `stats.extracted_success`를 대조해 잡아낸다.

**환각 차단.** "JSON에 명시된 값만 사용", "JSON에 없는 기사 생성 금지", "추정으로 채우기 금지"를 반복 명시한다. URL은 특히 `items[].url` 그대로 쓰도록 항목마다 못박았다. 요약을 만들다 링크를 그럴듯한 다른 URL로 바꿔 쓰는 경우가 있었다.

**루프 차단.** "초안 = 최종본", "재채점 금지", "생성 후 재조회 금지". 초안을 스스로 다듬으려 하면 토큰과 시간이 배로 든다.

**호출 횟수 절감.** 데일리는 선정 뉴스와 추출 실패를 한 번의 `create-pages`로 묶고, 브리핑만 2회차로 분리한다. 브리핑 본문에 1회차 페이지 링크가 들어가야 해서 순서상 분리가 불가피하다.

**사용자 우선순위 반영.** 데일리와 화요일 A 프롬프트 모두 "같은 조건이면 공정과 양산 기사(특히 박막공정 — 증착, ALD, CVD, PVD)를 시황이나 주가성 기사보다 위로" 규칙을 담고 있다. 파이썬의 tech 배수와 tech 쿼터가 같은 방향으로 작동해, 파이프라인 전 구간이 한 방향을 본다.

### 프롬프트를 쓰려면 치환할 값

| 플레이스홀더 | 바꿀 값 |
|---|---|
| `YOUR_GITHUB_USERNAME` | 자신의 GitHub 사용자명 (raw fetch URL) |
| `YOUR_NOTION_DATA_SOURCE_ID` | 노션 데이터 소스 ID |
| `YOUR_NOTION_DATABASE_ID` | 노션 데이터베이스 ID |
| `YOUR_NOTION_TOKEN` | 노션 Integration Token |
| `YOUR_SLACK_WEBHOOK_URL` | 슬랙 Incoming Webhook URL |

치환한 프롬프트는 클로드 루틴 설정에만 넣고 저장소에 커밋하지 않는다.

---

## 설치 및 로컬 실행

Python 3.13 기준이다.

```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/news-automation.git
cd news-automation

python -m venv .venv
source .venv/bin/activate        # 윈도우는 .venv\Scripts\activate

pip install -r requirements.txt
```

의존성은 다섯 개다.

```
feedparser          # RSS 파싱
requests            # 노션, 슬랙 API 호출
googlenewsdecoder   # Google News 리다이렉트 링크 디코딩
trafilatura         # 본문 추출
lxml                # trafilatura 백엔드
```

전체 파이프라인 실행:

```bash
python -m src.main 반도체
```

각 모듈은 단독 실행도 지원한다. 단계별 디버깅용이다.

```bash
python -m src.collect     # RSS 수집만, 상위 5건 출력
python -m src.resolve     # 수집 + resolve, 성공 건수
python -m src.filter      # 점수까지, 상위 10건의 buckets/bucket_hits 출력
python -m src.extract     # 본문 확보까지, 상위 3건 본문 앞부분
python -m src.save        # 전체 실행 후 JSON 저장
```

`python -m src.filter`가 특히 유용하다. 버킷별 점수와 어떤 canon이 걸렸는지를 그대로 찍어주기 때문에, 키워드를 고친 효과를 즉시 확인할 수 있다.

화요일 prep 스크립트는 저장소 루트에서 실행한다.

```bash
python tuesday_prep.py              # 오늘(KST) 기준 최근 7일
python tuesday_prep.py --days 14    # 윈도우 확장

# weekly_prep는 노션 인증이 필요
export NOTION_TOKEN=...
export NOTION_DATABASE_ID=...
python weekly_prep.py
```

로컬 실행 결과도 `data/`에 저장되므로, 테스트 후 커밋 전에 `git status`를 확인한다.

---

## GitHub Actions 설정

### 워크플로 3개

| 파일 | `event_type` | 하는 일 | Secrets |
|---|---|---|---|
| `daily.yml` | `daily-news` | 파이프라인 실행 후 `data/` 커밋 | 없음 |
| `notion_check.yml` | `notion-check` | 어제 브리핑 존재 확인, 없으면 슬랙 | NOTION_TOKEN, NOTION_DATABASE_ID, SLACK_WEBHOOK_URL |
| `tuesday.yml` | `tuesday-review` | `tuesday_prep.py` + `weekly_prep.py` 후 커밋 | NOTION_TOKEN, NOTION_DATABASE_ID |

`daily.yml`은 시크릿이 필요 없다. 크롤링만 하고 노션을 건드리지 않기 때문이다. 노션 기록은 클로드 루틴이 자기 MCP 커넥터로 처리한다.

`data/`를 커밋하는 워크플로(`daily.yml`, `tuesday.yml`)에는 `permissions: contents: write`가 필요하다.

### 외부 스케줄러로 트리거하기

Personal Access Token(scope: `repo`)을 발급받고 스케줄러에서 아래 요청을 보낸다. **세 워크플로 모두 같은 엔드포인트를 치며, 구분은 요청 본문의 `event_type`이 한다.**

```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer YOUR_GITHUB_PAT" \
  https://api.github.com/repos/YOUR_GITHUB_USERNAME/news-automation/dispatches \
  -d '{"event_type":"daily-news"}'
```

`event_type`을 `notion-check`, `tuesday-review`로 바꿔 나머지 두 잡을 만든다.

주의할 점이 있다. `repository_dispatch`는 **정확히 일치하는 `types`를 선언한 워크플로가 있을 때만** 실행된다. 없으면 GitHub은 POST를 정상 접수하고 `204 No Content`를 돌려준다. 스케줄러 로그에는 성공으로 찍히는데 Actions에는 아무 실행도 안 생긴다. 조용히 실패하는 유형이라, `event_type` 오타는 몇 달 모르고 지나갈 수 있다. 새 잡을 만들면 Actions 탭에서 실제 실행이 생겼는지 반드시 확인한다.

> 이 curl 명령의 토큰은 절대 저장소에 커밋하지 않는다. 스케줄러 서비스의 시크릿 저장소나 환경변수에 넣는다.

### 필요한 Secrets

저장소 Settings > Secrets and variables > Actions에서 등록한다.

| 이름 | 발급처 |
|---|---|
| `NOTION_TOKEN` | notion.so/my-integrations에서 Internal Integration Secret 발급 후 대상 DB에 연결 권한 부여 |
| `NOTION_DATABASE_ID` | 노션 DB URL의 32자리 문자열 |
| `SLACK_WEBHOOK_URL` | 슬랙 앱의 Incoming Webhook URL |

슬랙은 MCP 대신 Incoming Webhook을 쓴다. 본인 계정 발신은 푸시 알림이 안 오기 때문이다.

---

## 진단 도구

`measure_tech_density.py`는 읽기 전용 진단 스크립트다. 파이프라인에 전혀 개입하지 않고 파일도 쓰지 않는다.

측정하는 것은 "한 기사(제목 + 요약)에 tech 키워드가 실제로 몇 종류나 등장하는가"다. 검증하려던 가설은 이렇다. tech 키워드는 stack이 안 되고(보통 1~2개) 비즈니스 차원(entity + product + event)은 한 헤드라인에서 같이 쌓이므로, 깊이가 넓이에 구조적으로 진다.

`config/keywords.py`와 `config/sources.py`를 그대로 로드하므로 키워드가 항상 동기화된다. 다만 `filter.py`를 import하지는 않고 문서화된 매칭 규칙만 재현한다. 그래서 이 스크립트가 세는 것은 점수가 아니라 **몇 종류가 등장했나(개수)**다.

```bash
python measure_tech_density.py                # SOURCES의 when:1d 그대로
python measure_tech_density.py --days 7       # 구글뉴스 윈도우를 7일로 넓혀 표본 확대
python measure_tech_density.py --examples 8   # 카운트별 예시 헤드라인 출력
python measure_tech_density.py --rank         # 실제 랭킹 확인
python measure_tech_density.py --bodystats    # rss_body 통계
python measure_tech_density.py --selftest     # 네트워크 없이 샘플 헤드라인으로 동작 확인
```

`feedparser`만 있으면 돈다. 키워드 tier 조정이나 버킷 배수 변경을 고민할 때, 감이 아니라 실측으로 판단하기 위한 도구다.

---

## 튜닝 포인트

대부분의 조정은 `config/` 세 파일에서 끝난다. **`settings.py`와 `keywords.py` 변경은 항상 사람이 확인한 뒤 적용한다.**

### config/settings.py 주요 노브

| 설정 | 현재값 | 역할 |
|---|---|---|
| `TIME_WINDOW_HOURS` | 24 | 수집 시간 범위 |
| `PYTHON_SCORE_THRESHOLD` | 4 | 정규화 전 raw 버킷합 기준 컷 |
| `TITLE_WEIGHT` / `BODY_WEIGHT` | 1.5 / 1.0 | 제목 / summary 위치 가중치 |
| `SCORE_REF` | 28.0 | 정규화 고정 기준. raw 28이 10점 |
| `NEG_FLOOR` | -6 | 감점 합 하한 |
| `TOP_N_FOR_EXTRACT` | 15 | 본문 확보 대상 개수 |
| `MIN_BODY_LENGTH` | 300 | RSS 본문을 재크롤 없이 쓸지 판단하는 기준 (드롭 기준 아님) |
| `ENGLISH_QUOTA` | 3 | top-N에 예약하는 영문 자리 |
| `TECH_QUOTA` | 2 | top-N에 예약하는 tech 주도 자리 |
| `TITLE_DEDUP_SIM` | 0.85 | 제목 trigram Jaccard 중복 임계 |
| `BODY_TRUNCATE` / `BODY_TRUNCATE_KO` | 1000 / 600 | 본문 최대 길이 (영문 / 한글) |
| `DROPPED_KEEP` | 20 | JSON에 남길 탈락 항목 수 |
| `PARALLEL_EXTRACT` | False | 분야 늘릴 때 True |
| `BLOCKED_HOSTS` | `{"msn.com"}` | resolve 단계에서 드롭할 호스트 |

증상별 대응은 이렇다.

- **수집량이 너무 적다** — `TIME_WINDOW_HOURS`를 늘리거나 `PYTHON_SCORE_THRESHOLD`를 낮춘다. `stats`의 `after_time_filter`와 `after_score_filter` 중 어디서 줄었는지 먼저 본다.
- **잡음 기사가 통과한다** — `negative`의 `neg_weak`에 키워드를 추가한다. `tuesday_prep.json`의 `passed_with_negative`가 바로 이 진단용이다.
- **기술 기사가 안 뜬다** — `BUCKET_WEIGHTS["tech"]`를 올리거나 `TECH_QUOTA`를 늘린다. 1.6은 과했고 1.3이 현재 균형점이다.
- **영문이 안 뜬다** — `ENGLISH_QUOTA`를 늘린다. 파이썬 쿼터만 늘리면 후보만 늘고 노션 노출은 안 늘어난다. 데일리 프롬프트의 영문 쿼터 규칙도 같이 고쳐야 한다.
- **본문 확보 실패가 많다** — `extract_failed`의 `reason` 분포를 본다. `fetch_fail`이 특정 매체에 몰리면 차단이니 `BLOCKED_HOSTS` 후보다.
- **루틴 토큰이 부족하다** — `TOP_N_FOR_EXTRACT`나 `BODY_TRUNCATE_KO`를 줄인다.
- **비슷한 기사가 여러 건 뜬다** — `TITLE_DEDUP_SIM`을 낮춘다. 다만 낮추면 다른 사건까지 묶일 위험이 있어 조심스럽게 움직인다.

### config/keywords.py

키워드 사전을 수정하면 즉시 점수 체계가 바뀐다. `keywords_snapshot`이 JSON에 함께 저장되므로 과거 결과와 비교할 때 어떤 사전으로 채점했는지 추적할 수 있다.

새 키워드를 추가할 때는 어느 버킷에 넣을지가 tier보다 중요하다. 버킷이 cap과 배수를 결정하기 때문이다. 별칭 관계가 있으면 `ALIASES`에도 반드시 등록한다. 안 그러면 같은 개념이 중복 카운트되어 cap을 혼자 채운다.

### config/sources.py

`SOURCES` 딕셔너리에 새 분야를 추가하면 `python -m src.main 새분야`로 실행할 수 있다. 단, 해당 분야의 키워드 사전을 `config/keywords.py`에도 함께 추가해야 한다.

새 RSS를 추가하기 전에는 신선도를 확인한다. 죽은 피드를 여럿 겪었다.

```bash
python -c "import feedparser as f; d=f.parse('https://example.com/feed/'); print(len(d.entries)); [print(e.get('published'), e.title[:50]) for e in d.entries[:5]]"
```

영문 피드를 추가하면 `settings.ENGLISH_FEEDS`에도 등록해야 쿼터와 truncate(1000자) 처리를 받는다. 딥테크 매체면 `DEEPTECH_FEEDS`에도 넣는다.

---

## 트러블슈팅

| 증상 | 원인 | 확인 및 조치 |
|---|---|---|
| 루틴이 "latest.json이 오늘 갱신 안 됨"으로 중단 | 파이프라인이 안 돌았거나 커밋 실패 | Actions 탭에서 daily.yml 실행 이력 확인. 외부 스케줄러가 dispatch를 보냈는지 확인 |
| 루틴이 "JSON 요약본만 반환됨"으로 중단 | curl 결과가 원본이 아니라 요약되어 전달됨 | `items` 개수가 `stats.extracted_success`와 같아야 한다 |
| 스케줄러는 성공인데 Actions에 실행이 없음 | `event_type`이 어느 워크플로의 `types`와도 안 맞음 | 오타 확인. GitHub은 204를 돌려주므로 스케줄러 쪽에서는 성공으로 보인다 |
| 화요일 루틴이 "prep.json이 오늘 갱신 안 됨"으로 중단 | CDN 캐싱 지연 | tuesday.yml 트리거 시각과 루틴 실행 시각 사이를 30분 이상 벌린다 |
| `after_resolve`가 `collected_total`보다 크게 적음 | Google News 디코딩 실패 | `googlenewsdecoder`를 최신 버전으로. 구글이 인코딩을 바꾸면 이 패키지가 먼저 깨진다 |
| `extracted_failed`가 대부분 | 언론사가 크롤링 차단 | `by_reason`이 `fetch_fail`이면 차단, `no_body`면 JS 렌더링. 반복되면 `BLOCKED_HOSTS` 후보 |
| 특정 매체 기사가 전혀 안 들어옴 | 피드가 죽었거나 스테일 | 위의 feedparser 원라이너로 신선도 확인. TrendForce와 KEDGlobal이 이 경우였다 |
| 노션 create-pages가 계속 거부됨 | multi_select 형식 오류 | 배열을 문자열로 감쌌는지, 카테고리 값이 정의된 옵션과 정확히 일치하는지 확인 |
| 노션 날짜가 시간까지 들어감 | `is_datetime`을 문자열로 보냄 | 숫자 `0`이어야 한다. `"0"`은 안 된다 |
| 같은 날짜 페이지가 두 번 생김 | 루틴이 두 번 실행됨 | 루틴 스케줄 중복 확인. `generated_at` 검증이 작동하는지 확인 |
| 슬랙 알림이 안 옴 | Secrets 미등록 또는 웹훅 만료 | 워크플로 실행 로그에서 KeyError 확인 |
| 심화요약 루틴에서 curl이 막힘 | 프록시 허용목록 미등록 | 클라우드 환경 설정에 `api.notion.com`과 `hooks.slack.com` 추가. 새 세션부터 적용 |
| 심화요약이 같은 기사를 반복 처리 | 체크 해제 실패 | 각 행 기록 직후 `심화요약요청`을 false로 내리는지 확인 |

### 알아두면 좋은 것

- 파이썬 `requests`를 막는 사이트는 클로드의 fetch도 막힌다(예: biz.chosun.com). 광범위 스크래핑은 토큰 비용과 중복 문제로 기각했다. 본문 확보는 trafilatura 재크롤과 RSS 본문 폴백으로만 한다.
- `latest.json`은 CDN 캐싱으로 커밋 후 10분 이상 지연될 수 있다. 항상 `items` 수를 `stats`와 대조해 검증한다.
- LLM은 Sonnet 4.6을 쓴다. Haiku는 환각과 날짜 오류로 부적합했다.

---

## 보안 주의사항

이 저장소는 공개되어 있다. 아래 값들은 절대 커밋하지 않는다.

- 노션 Integration Token (`NOTION_TOKEN`)
- 노션 데이터베이스 ID 및 데이터 소스 ID
- 슬랙 Incoming Webhook URL
- GitHub Personal Access Token
- Cloudflare Worker의 `TRIGGER_URL`, `TRIGGER_SECRET`, `BUTTON_KEY`

모두 GitHub Secrets, Cloudflare Worker의 Secret 변수, 또는 외부 스케줄러의 시크릿 저장소에 넣고, 코드에서는 `os.environ`, `${{ secrets.NAME }}`, `env.NAME`으로만 참조한다. `src/check_notion.py`와 `weekly_prep.py`는 모든 값을 환경변수로 읽고, `workers/deep-summary-worker.js`는 전부 `env`로 읽는다. `.gitignore`에 `.env`가 포함되어 있다.

`docs/`의 프롬프트 4개는 노션 ID, 토큰, 슬랙 웹훅이 전부 플레이스홀더로 치환되어 있다. 자신의 값으로 채운 프롬프트는 클로드 루틴 설정에만 넣고, 로컬 파일로 두더라도 git 추적에서 제외한다.

실수로 커밋했다면 파일만 수정하는 것으로는 부족하다. git 히스토리에 남기 때문이다. **해당 토큰을 즉시 폐기하고 새로 발급받는다.** 노션 토큰은 notion.so/my-integrations, 슬랙 웹훅은 슬랙 앱 설정, GitHub PAT는 Settings > Developer settings에서 각각 폐기할 수 있다.
