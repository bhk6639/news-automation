# 클로드 루틴 프롬프트 — 화요일 B (파이프라인 분석 검토)

화요일 새벽 실행. `tuesday_prep.py`가 최근 7일치 JSON을 집계해 둔 결과를 읽고, 누락과 키워드와 노이즈를 리뷰해 슬랙으로 보고한다. 노션은 건드리지 않는다.

- **입력**: `data/tuesday_prep.json` (curl 1회)
- **출력**: 슬랙 Incoming Webhook 한 건
- **중단 가드**: fetch 실패 / `window.empty == true` / `generated_at` 날짜가 오늘(KST)이 아님


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
추정/환각 절대 금지. 집계(prep.json)에 없는 수치 생성 금지.
재작성 루프 금지. 초안 = 최종본.
자동 개선 금지. 리뷰만 하고 제안은 "제안"으로만. 변경은 사용자 확인 후.
노션 미관여. 이 루틴은 GitHub JSON 분석 + 슬랙 보고 전용.

원격(컴퓨터 꺼짐) 실행 전제.
- 집계는 GitHub Actions(tuesday-review 워크플로)가 prep.py를 돌려 data/tuesday_prep.json을 커밋한다.
- 이 루틴은 그 파일을 fetch해서 판단하고 슬랙으로 보고한다. (데일리 루틴이 latest.json fetch → 노션 기록하는 구조와 동일)

---

## 0. prep.json 가져오기

저장소 raw에서 집계 결과를 가져온다:

    curl -s "https://raw.githubusercontent.com/YOUR_GITHUB_USERNAME/news-automation/main/data/tuesday_prep.json"

**중단 조건 (하나라도 해당 시 분석 중단, 슬랙으로 사유 한 줄 보고 후 종료):**
- (a) fetch 실패 또는 JSON 아님
  → 슬랙: "⚠️ 화요일 루틴 중단: tuesday_prep.json fetch 실패"
- (b) `window.empty == true`
  → 슬랙: "⚠️ 화요일 루틴 중단: 최근 7일 범위에 JSON 없음"
- (c) `generated_at` 날짜가 오늘(KST)이 아님 (집계가 오늘 안 돌았거나 CDN 캐싱 지연)
  → 슬랙: "⚠️ 화요일 루틴 중단: prep.json이 오늘 갱신 안 됨. generated_at={값} / 오늘(KST)={오늘}"

⚠️ raw 파일은 커밋 후 CDN 캐싱으로 10분+ 지연될 수 있다. tuesday-review 워크플로 트리거 시각보다 충분히 뒤(권장 30분+)에 이 루틴을 돌릴 것.

**데이터 희소 경고:**
`window.missing_dates`가 절반 이상이면 표본 부족. 키워드/추세 판단은 단정하지 말고 "표본 부족, 참고용"으로 표기.

---

## 1. 검토 (LLM 판단 — 이 루틴의 핵심)

prep.json의 집계를 근거로 아래 5가지를 직접 판단한다.
집계는 기계가 했으니 여기서는 "문제인가 아닌가"만 본다.

### 1) 누락 검토
`dropped_candidates` (탈락 기사, 점수순)에서:
- 반도체 핵심 뉴스인데 점수가 낮아 탈락한 게 있는가
- 제목/요약은 반도체인데 `title_hits`/`summary_hits`가 빈약 → 키워드 미스 의심
- 단순 시황/주가/ETF성이라 정당하게 탈락한 것과 구분

### 2) 키워드 점검
- `dead_keywords` (최근 7일 한 번도 안 걸린 현재 키워드): 진짜 안 중요해서인지, 표현이 어긋나서인지. 표본 부족이면 "판단 보류".
  - 스냅샷과 usage는 **둘 다 canon(대표값) 축**이다. 여기 뜨는 항목은 국문이든 영문이든 **어느 표면형으로도 한 번도 안 걸린 개념**을 뜻한다. 별칭 때문에 죽은 것처럼 보이는 유령은 없다. (하닉/hynix는 canon "하이닉스"로 접혀 애초에 목록에 안 뜬다.)
  - ⚠️ 그래도 dead = 삭제가 아니다. 아래를 구분할 것.
    - **세트 묶음**(노드, DRAM세대, 단수): canon 하나가 표면형 수십 개를 대표한다. 이게 dead면 "그 세트 전체가 7일간 0회"라는 뜻이다. 개별 표면형을 지우지 말고 세트 단위로만 판단.
    - **드물지만 중요한 차세대 개념**(CFET, FeFET, STT-MRAM, 4F2, IGZO 등): 몇 주 무매칭이 정상이다. 빈도가 아니라 중요도로 판단. 남긴다.
    - **정리 후보**: 흔한 개념인데 7일 내내 0회인 것. 표현이 어긋났을 가능성이 높은 쪽이다.
  - 옛 JSON(스냅샷이 canon으로 안 접힌 구간)이 윈도우에 섞이면 별칭이 dead로 잡힌다. 그 구간 결과는 참고만.
- `keyword_usage` 편중: "반도체" 같은 범용어에만 쏠려 변별력이 떨어지는지
- 같은 대상인데 canon이 갈라진 게 보이면(예: 국문형과 영문형이 각각 집계) ALIASES 누락이다. 제안 항목에 올린다.

### 3) 노이즈 점검
- `negative_usage`: 네거티브 키워드가 얼마나 작동했는가
- `passed_with_negative`: 선정됐는데 네거티브가 붙은 기사 — 노이즈가 통과했는지
- `dropped_candidates`에서 노이즈가 잘 걸러졌는지도 확인

### 4) 추출 실패 패턴
`extract_failed`의 `by_reason` / `by_source`:
- 특정 소스가 반복 실패하는가 (예: 같은 매체 fetch_fail 다수 → 차단 가능성)
- 사유 분포(fetch_fail / no_body / exception)가 한쪽으로 쏠리는지

### 5) stats 추세
`stats_trend` / `stats_avg`:
- `after_score_filter`(통과 건수), `extracted_success`(추출 성공)의 흐름
- 급감/급증 같은 이상 신호가 있는지

---

## 2. 슬랙 보고

검토 결과를 슬랙 Incoming Webhook으로 POST한다.
(슬랙 MCP는 본인 발신 푸시가 안 와서 외부 POST 방식 사용 — 데일리 알림과 동일)

webhook URL (이 프롬프트 전용 하드코딩, 공개 저장소엔 절대 넣지 말 것):

    YOUR_SLACK_WEBHOOK_URL

POST 형식:

    curl -s -X POST -H "Content-Type: application/json" \
      -d '{"text": "<메시지>"}' \
      "YOUR_SLACK_WEBHOOK_URL"

**메시지 본문 (간결하게, 슬랙에서 읽기 좋게):**

```
📋 화요일 보강 리뷰 — {오늘 YYYY-MM-DD}
윈도우: {window_start} ~ {window_end} (파일 {N}개 / 결측 {M}일)

1. 누락: {발견 또는 "이상 없음"}
2. 키워드: {…}
3. 노이즈: {…}
4. 추출 실패: {…}
5. 추세: {…}

제안(확인 후 적용):
- {없으면 "없음"}
```

원칙:
- 발견 없으면 억지로 채우지 말 것. "이상 없음".
- 제안은 제안일 뿐. settings.py / keywords.py 변경은 사용자 승인 후 적용.
- 표본 부족 시 단정 금지.
- 메시지가 너무 길면 항목당 1~2줄로 압축. 상세는 생략 가능.

---

## 원칙 요약
- 집계 = GitHub Actions의 prep.py, 판단 = 이 루틴. 역할 섞지 않기.
- 자동 개선 금지. 리뷰 후 슬랙 보고, 변경은 사용자 확인 후.
- 노션 건드리지 않음. 출력은 슬랙뿐.
- 실행 로그(tuesday_log.json)는 prep.py가 이미 기록 — 따로 안 건드림.
````

---

## 설계 메모

- **자동 개선 금지**가 이 루틴의 핵심 원칙이다. 리뷰하고 제안만 한다. `settings.py`와 `keywords.py` 변경은 사람이 확인한 뒤 적용한다.
- `dead_keywords`의 신뢰도는 `save.keywords_snapshot`이 canon으로 접어 저장하느냐에 달려 있다. 접지 않으면 `keyword_usage`(canon 집계)와 축이 어긋나, canon이 아닌 별칭은 실제로 아무리 많이 걸려도 영원히 dead로 찍힌다. 접기 전에는 스냅샷 381개 중 156개(41%)가 이런 유령이었고, 접은 뒤 목록이 321개에서 194개로 줄면서 남은 항목이 전부 실제 미사용 개념이 됐다.
- 그래도 dead가 곧 삭제는 아니다. 세트 묶음(`노드`, `DRAM세대`, `단수`)은 canon 하나가 표면형 수십 개를 대표하므로 세트 단위로 판단해야 하고, 차세대 개념(CFET, FeFET, 4F2 등)은 몇 주 무매칭이 정상이다. 프롬프트 2단계에 이 구분이 명시돼 있다.
- prep 커밋 직후에 이 루틴을 돌리면 CDN 캐싱 때문에 옛 파일을 읽는다. 30분 이상 간격을 둔다.
