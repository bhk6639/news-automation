# 클로드 루틴 프롬프트 — 온디맨드 심화요약

노션 버튼으로 수시 실행. 사용자가 `심화요약요청`을 체크한 기사의 원문을 읽어 한줄핵심과 상세 요약을 만들어 노션에 붙인다.

- **트리거**: 노션 버튼(URL 열기) -> Cloudflare Worker -> 클로드 루틴 API 트리거 POST
- **입력**: 노션 REST `POST /v1/databases/{id}/query` + `심화요약요청 = true` 필터
- **출력**: 노션 (`심화요약핵심` 속성 + 페이지 본문 + 체크 해제) + 슬랙
- **중단 가드**: 체크된 행 0건 / 노션 접근 실패


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
# 클로드 루틴 — 온디맨드 심화요약

## 트리거
클로드 데스크탑 예약 루틴, **API 트리거**로 실행.
노션 "심화요약" 버튼 → Cloudflare Worker 릴레이 → 이 루틴의 API 트리거 URL로 POST → 루틴 시작.
POST 본문(payload)에 의존하지 않는다. 루틴은 노션 DB에서 **심화요약요청 = 체크됨** 인 행을 직접 읽어 처리한다.

## 비밀값 (이 파일은 비공개 · git 미추적 — 공개 저장소 금지)
- `NOTION_TOKEN` = `YOUR_NOTION_TOKEN`  (REST 체크박스 필터 조회용)
- `SLACK_WEBHOOK_URL` = `YOUR_SLACK_WEBHOOK_URL` (#노션-알림 채널)
- `NOTION_DATABASE_ID` = `YOUR_NOTION_DATABASE_ID`
- Notion-Version 헤더 = `2022-06-28`

## 환경 제약 (중요 — 6/28 실측 확인. 막힌 길을 다시 시도하지 말 것 = 토큰 낭비)
- 사용자가 루틴 네트워크 허용목록에 **`api.notion.com` 과 `hooks.slack.com` 둘 다 허용**해 둠 → Notion REST `curl`·Slack webhook `curl` **모두 사용 가능**.
- 행 **조회는 REST 체크박스 필터**(결정론적 — 내용 적은 페이지도 누락 0). ⚠️ 무료 플랜이라 MCP `query_data_sources`(SQL)·`query_database_view` 는 여전히 Business 전용이라 불가 — 그쪽은 시도 금지.
- **기록(쓰기)은 `notion-update-page`(MCP)** 로 한다(동작 확인됨). 단건 fetch도 MCP 가능.
- 알림은 **Slack Incoming Webhook**(`curl`). 혹시 실패하면 **PushNotification** 으로 폴백.
- `web_fetch` 는 사용 가능. 단 일부 매체(예: kipost.net, biz.chosun.com)는 403 차단 → 그 경우 **웹 검색으로 보완 요약**.
- 모델: Sonnet 4.6. 재작성/검토 루프 금지 — 초안을 최종본으로.

---

## 단계

### 1. 체크된 행 조회 (Notion REST — 결정론적, 누락 0)
`POST https://api.notion.com/v1/databases/YOUR_NOTION_DATABASE_ID/query`
헤더: `Authorization: Bearer {NOTION_TOKEN}`, `Notion-Version: 2022-06-28`, `Content-Type: application/json`
본문:
```json
{
  "filter": { "property": "심화요약요청", "checkbox": { "equals": true } },
  "page_size": 100
}
```
- `results[]`에서 각 행의 `id`(page_id), `properties.헤드라인`, `properties.링크`(url)를 추출. `has_more`가 true면 `next_cursor`를 `start_cursor`로 넘겨 반복.
- 이 방식은 **체크박스로 직접 거르므로 내용이 적은 페이지도 빠짐없이** 잡힌다(검색 추측 없음 — 이전 누락 원인 제거).
- **폴백**: 혹시 REST 호출이 실패(허용목록 미반영 등 HTTP≠200)하면, 임시로 MCP `notion-search`+`notion-fetch`로 최근 편집 페이지를 훑어 `심화요약요청=true`만 추린다(누락 가능 — 어디까지나 비상용).

**중단 가드**: 체크된 행 0건 → Slack "심화요약 요청 없음" 한 줄 후 종료. 노션 접근 자체가 실패 → Slack 한 줄 보고 후 종료.

### 2. 원문 본문 읽기 (행마다)
각 행의 `링크` URL을 `web_fetch`로 가져와 **본문 전체**를 읽는다.
- 추출 실패(차단·빈 본문 등, 예: biz.chosun.com류)면 그 행은 "실패"로 표시하고 3단계 대신 5단계의 실패 처리로 간다.

### 3. 심화요약 작성 (행마다)
본문을 근거로 직접 인용 없이 본인 말로 재구성한다. 두 가지를 만든다.

(A) **한줄 핵심** — 한 문장(공백 포함 180자 이내). 기사에서 가장 중요한 한 가지.
(B) **상세 심화요약** — 8~12문장. 다음 흐름을 권장:
   - 무슨 일인가(사실 요지)
   - 기술적·산업적 맥락(공정/제품/세대/단수 등 구체값 살리기)
   - 왜 중요한가 / 메모리·파운드리·장비 관점의 함의
   - 남은 쟁점·불확실성 또는 후속 관전 포인트
   분량 제한 없음 — 본문에 있는 구체 수치·고유명사를 충실히 살린다.

### 4. 노션에 기록 (행마다) — `notion-update-page` (MCP)
한 페이지에 대해 **(a) 속성 변경 + (b) 본문 추가**를 모두 한다. 둘 다 `notion-update-page`로 수행(이 환경에서 동작 확인됨).

**(a) 속성**: `심화요약핵심` = `<한줄 핵심>` (rich_text, 2000자 제한 — 한 줄이라 충분), `심화요약요청` = 체크 해제(false).

**(b) 페이지 본문 추가**: 페이지 맨 아래에 아래를 덧붙인다.
- 제목(heading): `🔎 심화요약 (M/D)`  ← `M/D` = 오늘 날짜(KST, 앞 0 없음, 예 `6/28`)
- 본문 단락(들): 상세 심화요약. 길면 문단을 여러 개로 나눠 추가.

- 속성(a)·본문(b) **둘 다** 수행(사용자 선택: 필드 한 줄 + 본문 상세).
- 기존 속성(요약·카테고리·분야·날짜 등)은 건드리지 않는다.

### 5. 본문 못 읽은 행 처리 (web_fetch 403 등)
- 먼저 **웹 검색으로 보완 요약**을 시도한다(제목·핵심 키워드로 검색해 사실 확인). 보완이 되면 일반 성공으로 처리하되 한줄 핵심 끝에 `(원문 차단 — 웹 검색 보완)` 표기.
- 보완도 불가하면: `심화요약핵심` = `⚠️ 본문 추출 실패(차단/오류) — 원문 직접 확인 필요`, `심화요약요청` = false(재실행 루프 방지), 본문 추가 생략, 실패로 집계.

### 6. 결과 알림 (마지막에 한 번) — Slack Incoming Webhook
`SLACK_WEBHOOK_URL` 로 `curl -X POST -H 'Content-type: application/json' -d '{"text":"..."}'`.
형식 예: `심화요약 완료: 성공 N건 / 실패 M건` + (있으면) 실패 기사 제목.
혹시 슬랙 POST가 실패하면 **PushNotification** 으로 같은 내용 폴백.

---

## 처리 순서·견고성
- 행은 하나씩 순서대로 처리(한 행 실패가 다른 행을 막지 않게 try 단위 분리).
- 같은 행을 두 번 처리하지 않도록, 각 행 기록 직후 바로 `심화요약요청`을 false로 내린다.
- 노션 rate limit(약 3 req/s) 고려해 호출 사이 약간 간격.
- 전체 토큰 절약: 본문은 요약 판단에만 쓰고 그대로 옮겨 붙이지 않는다.

## 작성 규칙
- 한국어. 직접 인용 없이 재구성. 재작성/검토 루프 금지.
- 날짜 표기 "M/D"(앞 0 없음).
- 카테고리·분야 등 기존 속성은 건드리지 않는다(심화요약핵심·심화요약요청만 변경 + 본문 추가).
````

---

## 설계 메모

- 트리거 payload에 의존하지 않는다. 루틴이 노션에서 체크된 행을 직접 읽는다. Worker가 두 번 발사되더라도 처리 대상은 같고, 각 행은 기록 직후 체크가 풀려 중복 처리되지 않는다.
- 이 루틴만 환경이 다르다. 프록시 허용목록 방식이라 클라우드 환경 설정의 허용 도메인에 `api.notion.com`과 `hooks.slack.com`을 등록해야 `curl`이 동작한다. 환경 변경은 새 세션부터 적용된다.
- 무료 플랜에서는 MCP `query_data_sources`(SQL)와 `query_database_view`가 Business 전용이라 쓸 수 없다. 검색 기반 조회는 내용이 빈약한 페이지를 누락시켜 폐기했고 REST 필터로 확정했다.
- 커밋된 JSON의 `body`를 본문 소스로 쓰는 안은 기각했다. 이미 truncate된 데다 데일리 루틴이 바로 그걸로 요약을 만들었기 때문에 심화요약이 더 깊어지지 않는다.
