"""
전역 설정값. 튜닝은 여기서.
"""

# 시간 필터
TIME_WINDOW_HOURS = 24

# 점수 필터
# 임계는 버킷 합산(정규화 전, raw) 기준. 버킷 cap 도입으로 raw 스케일이 바뀌었으나
# "강한 키워드 1개 이상" 수준을 거르는 의도는 동일해 4 유지 (필요 시 dropped 분포 보고 튜닝).
PYTHON_SCORE_THRESHOLD = 4
TITLE_WEIGHT = 1.5
BODY_WEIGHT = 1.0

# 버킷 스코어링 (filter.py score_item / save.py 정규화)
# 정규화는 배치 최댓값 나눗셈 → 고정 기준(SCORE_REF)으로 전환.
# 이유: 배치 최댓값 정규화는 한 건만 튀면 나머지를 전부 눌러(예: 4.71 동률) 변별력을 죽인다.
# score_norm = min(10, max(0, score_raw) / SCORE_REF * 10)
SCORE_REF = 28.0   # raw 28 → 10점. critical(+5)·tech 배수(1.6) 도입으로 스케일↑ 반영(6/25). 분포 보고 조정하는 튜닝 노브
NEG_FLOOR = -6     # 음수(감점) 합 하한. 한 기사가 무한정 깎이지 않게

# 선별 개수
TOP_N_FOR_EXTRACT = 15
MIN_BODY_LENGTH = 300

# 영문 쿼터 (filter.py score_and_filter)
# 영문 헤드라인은 키워드를 적게 때려 점수가 낮음 → 컷(THRESHOLD)에서 늘 탈락.
# 본문 추출용 top-N에 영문 피드 자리를 ENGLISH_QUOTA개 예약해 컷을 우회시킨다.
# 이렇게 latest.json까지 살아남아야 본문을 읽는 클로드 루틴이 최종 판단할 수 있다.
# (실제 노션 상위 5 보장은 데일리 프롬프트의 '영문 쿼터' 규칙이 담당)
ENGLISH_FEEDS = {"GoogleNews_EN", "SemiEngineering", "BlocksAndFiles", "EETimes"}
ENGLISH_QUOTA = 3

# tech 쿼터 (filter.py score_and_filter) — 6/25
# 시장 뉴스가 product/entity로 top-N을 채워 공정/기술 기사가 밀리는 문제 방어.
# 영문 쿼터와 동일 패턴: top-N에 'tech 주도'(tech 버킷 최상위) 기사 자리를 TECH_QUOTA개 예약.
# 영문 쿼터를 보존하면서, tech도 영문도 아닌 최저점 기사를 밀어내 자리를 만든다.
TECH_QUOTA = 2

# 제목 중복제거 (filter.py) — 6/25
# 같은 사건을 여러 매체가 거의 동일 제목으로 재배포한 완전복사본만 제거.
# 정규화(끝 ' - 매체명' 제거) 후 글자 trigram Jaccard >= 이 값이면 중복으로 보고 최고점 1건만 남김.
# 보수적으로 높게(0.85) — 패러프레이즈(다른 표현 같은 사건)는 LLM 루틴이 top-5 선별 때 거름.
TITLE_DEDUP_SIM = 0.85

# dropped 저장 개수
DROPPED_KEEP = 20

# 본문 추출
EXTRACT_TIMEOUT = 10
EXTRACT_RETRY = 1
EXTRACT_SLEEP = 1.0

# 병렬 처리 (지금은 OFF, 섹터 늘릴 때 ON)
PARALLEL_EXTRACT = False
PARALLEL_WORKERS = 4

# JSON 저장
DATA_DIR = "data"
# 본문 최대 길이 (루틴 토큰 절약). 언어별 분리 — 한글은 짧게, 영문은 길게.
# 한글 기사는 첫 문단에 핵심이 몰려 600자면 2문장 요약·카테고리 판단에 충분.
# 영문(쿼터로 진입)은 LLM이 본문으로 관련성·요약을 판단해야 하므로 1000자 유지.
BODY_TRUNCATE = 1000      # 영문/기본 본문 최대 길이
BODY_TRUNCATE_KO = 600    # 한글 본문 최대 길이
