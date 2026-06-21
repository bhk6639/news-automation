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
SCORE_REF = 20.0   # raw 20 → 10점. 며칠 분포 보고 조정하는 튜닝 노브
NEG_FLOOR = -6     # 음수(감점) 합 하한. 한 기사가 무한정 깎이지 않게

# 선별 개수
TOP_N_FOR_EXTRACT = 10
MIN_BODY_LENGTH = 300

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
BODY_TRUNCATE = 1000  # 루틴 토큰 절약용 본문 최대 길이
