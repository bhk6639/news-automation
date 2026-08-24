# 클로드 루틴 프롬프트 — 화요일 A (주간 브리핑, 요약 보완)

화요일 새벽 실행. `weekly_prep.py`가 노션에서 긁어 커밋해 둔 페이지 목록을 읽어, 요약이 빈 페이지를 채우고 그 주 주간 브리핑을 쓴다.

- **입력**: `data/weekly_prep.json` (fetch 1회)
- **출력**: 노션 (`notion-update-page`로 요약 보완, `notion-create-pages`로 주간 브리핑) + 슬랙 한 줄
- **중단 가드**: fetch 실패 / 응답 잘림 / `empty == true` / `generated_at` 날짜가 오늘(KST)이 아님


## 사용 전 치환할 값

이 문서의 프롬프트는 비밀값이 플레이스홀더로 치환되어 있다. 클로드 루틴에 넣기 전에 자신의 값으로 바꾼다.

| 플레이스홀더 | 바꿀 값 | 찾는 곳 |
|---|---|---|
| `YOUR_GITHUB_USERNAME` | GitHub 사용자명 | 저장소 URL |
| `YOUR_NOTION_DATA_SOURCE_ID` | 노션 데이터 소스 ID | 노션 MCP로 대상 DB 조회 시 응답에 포함 |
| `YOUR_NOTION_DATABASE_ID` | 노션 데이터베이스 ID | 노션 DB URL의 32자리 문자열 |
| `YOUR_NOTION_TOKEN` | 노션 Integration Token | notion.so/my-integrations |
| `YOUR_SLACK_WEBHOOK_URL` | 슬랙 Incoming Webhook URL | 슬랙 앱 설정 |

**치환한 프롬프트는 클로드 루틴 설정에만 넣고 저장소에 커밋하지 않는다.** 로컬 파일로 두더라도 git 추적에서 제외한다.

---

## 프롬프트 전문

아래 블록 전체를 그대로 클로드 루틴에 넣는다.

````markdown
추정/환각 절대 금지. 노션/본문에 없는 내용 생성 금지.
재작성 루프 금지. 초안 = 최종본.
정 안되면 비워두기. 억지로 채우지 않기.

이 루틴은 원격 클로드 루틴으로 실행된다(컴퓨터가 꺼져 있어도 작동).
로컬 파일 접근 불가. 입력은 GitHub에 커밋된 weekly_prep.json을 curl/fetch로 읽고,
출력은 노션 MCP(읽기/쓰기)와 슬랙 Incoming Webhook으로만 한다.

기간 내 페이지 조회는 파이썬(weekly_prep.py, 화요일 03:30 KST 실행 후 커밋)이 이미
필터+페이지네이션으로 빠짐없이 수행해 weekly_prep.json에 담아 둔다.
→ 이 프롬프트는 notion-search/notion-fetch로 DB를 다시 열거하지 않는다. prep.json만 신뢰.

---

## 0. prep 입력 fetch + 중단 가드

다음 URL을 fetch:
https://raw.githubusercontent.com/YOUR_GITHUB_USERNAME/news-automation/main/data/weekly_prep.json

중단 가드 (아래 중 하나라도 해당하면 노션 무변경, 슬랙 한 줄 보고 후 즉시 종료):
- fetch 실패 / 응답 잘림 / JSON 파싱 실패
- empty 가 true (기간 내 대상 페이지 없음)
- generated_at 의 날짜가 오늘(KST)이 아님 (= prep이 이번 주 것이 아님. CDN 캐싱 지연 등)

가드 통과 시: window.window_start ~ window.window_end 를 조회 기간으로 확정.
pages[] 가 전체 대상이며, 이후 노션 재조회 금지.
각 page 객체 필드: page_id, page_url, headline, date, link, summary, summary_empty, categories

---

## 1. 요약 없는 페이지 보완

pages 중 summary_empty == true 인 페이지만 대상.
없으면 → "요약 없는 기사 없음" 메모 후 2단계로.

각 대상 페이지의 link 로 web_fetch 시도.

**성공 시 (본문 확인 가능):**
- 헤드라인(headline): "M/D 제목" 형식이면 보존. 비었거나 날짜 없으면 본문 날짜 확인 후 "M/D 원제목"으로. 날짜 확인 불가 → prep의 date 기준
- 날짜(date): 본문 발행일 확인되면 업데이트, 불가 시 기존값 보존
- 요약: 본문 기반 2문장, 각 80자 이내. 본문에 없는 내용 금지. 직접 인용 금지
- 카테고리: 기존값(categories) 보존. 비었으면 본문 기반 선택 (다중 가능): 메모리 / 파운드리 / 장비소재 / 설계 / 글로벌. 애매하면 비움
- 분야: ["반도체"] (비었으면 채우기)

notion-update-page (page_id 대상)로 업데이트. 성공 목록에 page_url + 헤드라인 기록.
업데이트한 페이지의 요약/카테고리는 2단계 브리핑 판단에 반영.

**실패 시 (본문 확인 불가, web_fetch 차단/오류 — 예: biz.chosun.com·chosun.com 403):**
곧바로 실패 처리하지 말고 **웹 검색으로 보완을 먼저 시도**한다(심화요약 루틴과 동일 패턴).
- headline·핵심 키워드(회사·수치·사건)로 검색해, 같은 사건을 다룬 접근 가능한 다른 출처의 **실제 내용**을 읽고 그 근거로만 요약한다. 추정·환각 절대 금지 — 검색 결과에 실제로 있는 사실만.
- **보완 성공**: 본문 성공과 동일 처리(요약 2문장·카테고리·분야·헤드라인 업데이트)하되, 요약 끝에 ` (원문 차단 — 웹검색 보완)` 표기. notion-update-page로 기록하고 성공 목록에 넣음. 2단계 브리핑 판단에도 반영.
- **보완도 불가**: 실패 목록에 헤드라인만 기록. 노션 건드리지 않음.

---

## 2. 주간 브리핑 작성

확보한 전체 페이지(원래 요약 있던 것 + 1단계 보완 성공한 것) 기준.
요약 텍스트를 근거로 그 주 중요했던 뉴스를 직접 판단해 선정.

- 선정 기준: 본인 판단 (산업 영향도, 사용자 관심사 반영). 사용자 관심사 = 공정·양산, 특히 박막공정(증착·ALD·CVD 등). 같은 조건이면 공정/양산/기술 기사를 시황·주가성보다 우선.
- 건수: 고정 안 함. 중요한 만큼만 (보통 5~8건)
- 정렬: 중요도순 (카테고리 묶음 X)
- 각 항목: 헤드라인(노션 페이지 링크 = page_url) + 한 문장 핵심
- 요약 없어 판단 불가한 페이지는 브리핑 대상에서 제외

---

## 3. 결과 페이지 생성

notion-create-pages, parent: data_source_id = YOUR_NOTION_DATA_SOURCE_ID

⚠️ 날짜 필드 포맷: `date:날짜:start`(날짜 문자열) + `date:날짜:is_datetime` 키에 숫자 0 (문자열 "0" 아님). 1단계 notion-update-page 날짜 업데이트도 동일.
⚠️ multi_select(분야/카테고리)는 문자열로 감싼 JSON 배열로 전달 (예: "[\"반도체\"]").

페이지 필드:
- 헤드라인: "시작일M/D ~ 어제M/D 주간 브리핑" (앞 0 없음. 예: "5/20 ~ 5/26 주간 브리핑")
- 날짜(date): window.window_end (어제 날짜)
- 분야: ["반도체"]
- 카테고리: ["주간 브리핑"]
- 요약: 비움

content:

## 주간 브리핑
1. [헤드라인](page_url) — 핵심 한 문장
2. ...
(중요도순)

## 뉴스 정리 보완
실행 시각: YYYY-MM-DD HH:MM (KST)
요약 업데이트 성공 N건 (웹검색 보완 N건) / 실패 N건

### 성공
- [헤드라인](page_url)
...

### 실패
- 헤드라인 (링크 없이)
...

---

## 4. 완료 슬랙 알림

주간 브리핑 페이지 생성 성공 후, 슬랙 Incoming Webhook으로 한 줄 POST:

curl -X POST -H 'Content-type: application/json' \
  --data '{"text":"✅ 주간 브리핑 작성 완료 (시작일M/D ~ 어제M/D) / 전체 N건, 요약 보완 성공 N건·실패 N건, 브리핑 N건 선정"}' \
  YOUR_SLACK_WEBHOOK_URL

(채널: #노션-알림. webhook URL은 이 파일에 직접 채워 둘 것. 공개 저장소 반입 금지 — 이 프롬프트 파일은 git 미추적 유지.)
중단 가드로 종료한 경우는 ## 0 의 한 줄 보고만 보내고 이 단계는 생략.

---

## 5. 결과 보고 (4줄)

1. 조회 기간: M/D ~ M/D / 전체 N건
2. 요약 보완 성공 N건 (웹검색 보완 N건) / 실패 N건
3. 주간 브리핑 N건 선정
4. 특이사항 (없으면 "없음")
````

---

## 설계 메모

- 이 프롬프트는 `notion-search`나 `notion-fetch`로 DB를 다시 열거하지 않는다. MCP `notion-fetch`는 데이터소스 조회 시 스키마만 반환하고 행을 주지 않으며, `notion-search`는 시맨틱 검색에 25건 한계라 누락이 생긴다. 기간 내 전체 페이지 조회는 `weekly_prep.py`가 REST 필터와 페이지네이션으로 이미 끝내 둔다.
- 1단계에서 `web_fetch`가 403으로 막히면 바로 실패 처리하지 않고 **웹 검색 보완**을 먼저 시도한다. 심화요약 루틴과 같은 패턴이다. 보완으로 쓴 요약에는 표기를 남긴다.
- 조회 시작일은 가장 최근 주간 브리핑 페이지 날짜 + 1일이다. 그래서 한 주를 건너뛰어도 다음 실행이 빈 구간을 자동으로 메운다.
