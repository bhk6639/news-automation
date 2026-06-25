"""
시간 필터 → 중복 제거 → 점수 매기기.
"""

import re
import hashlib
from functools import lru_cache
from datetime import datetime, timezone, timedelta
from config.settings import (
    TIME_WINDOW_HOURS,
    PYTHON_SCORE_THRESHOLD,
    TITLE_WEIGHT,
    BODY_WEIGHT,
    TOP_N_FOR_EXTRACT,
    DROPPED_KEEP,
    NEG_FLOOR,
    ENGLISH_FEEDS,
    ENGLISH_QUOTA,
    TECH_QUOTA,
    TITLE_DEDUP_SIM,
)
from config.keywords import KEYWORDS, WEIGHTS, ALIASES, BUCKET_CAPS, BUCKET_WEIGHTS

# 가점 tier 순회 순서. 높은 tier를 먼저 둬야 같은 canon이 묶였을 때 높은 가중치로 카운트된다.
_POS_TIERS = ("critical", "strong", "medium", "weak")

# 별칭 → 대표값 역매핑. 별칭에 없는 키워드는 자기 자신이 대표.
_ALIAS2CANON = {alias: canon for canon, group in ALIASES.items() for alias in group}


def _canon(word: str) -> str:
    return _ALIAS2CANON.get(word, word)


def _is_english_feed(item: dict) -> bool:
    """영문 피드(GoogleNews_EN/SemiEngineering/BlocksAndFiles/EETimes) 출처인지."""
    return item.get("rss_source") in ENGLISH_FEEDS


def _is_tech_led(item: dict) -> bool:
    """tech 버킷이 최상위(가중치 적용 전 capped 점수 기준)인 '공정/기술 주도' 기사인지."""
    b = item.get("score_detail", {}).get("buckets", {})
    if not b:
        return False
    mx = max(b.values())
    return mx > 0 and b.get("tech", 0) == mx


def _norm_title(t: str) -> str:
    """제목 정규화: 끝 ' - 매체명' 제거 + 기호/공백 제거 + 소문자."""
    t = re.sub(r'\s*[-–—|]\s*[^-–—|]+$', '', t)   # 끝 ' - 매체명'
    return re.sub(r'[^\w가-힣]+', '', t).lower()


def _title_trigrams(t: str) -> set:
    n = _norm_title(t)
    return {n[i:i + 3] for i in range(len(n) - 2)} if len(n) >= 3 else {n}


def dedupe_by_title(items: list[dict], threshold: float = TITLE_DEDUP_SIM) -> list[dict]:
    """점수 내림차순 가정. 정규화 제목 trigram Jaccard >= threshold면 거의 동일한
    재배포 복사본 → 최고점 1건만 남긴다. (패러프레이즈는 임계 미달로 통과 → LLM이 선별)."""
    kept = []
    reps = []
    for it in items:
        tg = _title_trigrams(it["title"])
        if any(len(tg & rt) and len(tg & rt) / len(tg | rt) >= threshold for rt in reps):
            continue
        kept.append(it)
        reps.append(tg)
    return kept


def filter_by_time(items: list[dict]) -> list[dict]:
    """published가 TIME_WINDOW_HOURS 이내인 것만."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=TIME_WINDOW_HOURS)
    return [it for it in items if it["published"] and it["published"] >= cutoff]


def dedupe_by_url(items: list[dict]) -> list[dict]:
    """최종 URL 해시로 중복 제거."""
    seen = set()
    unique = []
    for it in items:
        h = hashlib.sha1(it["url"].encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            unique.append(it)
    return unique


@lru_cache(maxsize=None)
def _kw_pattern(word: str) -> "re.Pattern":
    """
    키워드 매칭용 정규식.
    - 대소문자 무시 (IGNORECASE): 영문 'Foundry'/'foundry' 케이스 차이 흡수.
    경계 규칙 (키워드의 해당 끝 글자가 ASCII 영숫자일 때만 적용):
    - 왼쪽: 앞에 ASCII 영숫자(글자+숫자) 오면 차단. 'anode'의 'node', '21c'의 '1c' 막음.
    - 오른쪽: 뒤에 ASCII '글자'만 차단, '숫자'는 허용. 두 목적 동시 달성:
      * subword 차단: 'fab'은 'fabric'/'prefab' 안 걸림, 'node'는 'nodes' 안 걸림.
      * 버전접미사 복구: 'HBM'→'HBM3'/'HBM3E', 'GDDR'→'GDDR7', 'LPDDR'→'LPDDR5X' 매칭.
    - 한쪽 끝이 한글이면 그쪽 경계 없음 → 'SK하이닉스가'의 '하이닉스', 'DDR5메모리'의 '메모리' 매칭.
    - 'HBM4'는 뒤에 글자 'E' 오면 차단 → 'HBM4E' 안 걸림(별도 키워드).
    """
    # DRAM 세대코드(1a~1d)는 단독이면 '1 billion(1b)'·'1D'·'1A' 등과 오매칭 →
    # 뒤에 나노/nm/D램/DRAM 컨텍스트가 와야 매칭(공정 기사만 잡음). 예: '1c D램'·'1cnm'.
    if re.fullmatch(r'1[a-d]', word):
        return re.compile(r'(?<![A-Za-z0-9])' + word + r'\s*(?:나노|nm|디램|D램|DRAM)', re.IGNORECASE)
    left = r'(?<![A-Za-z0-9])' if word[0].isascii() and word[0].isalnum() else ''
    right = r'(?![A-Za-z])' if word[-1].isascii() and word[-1].isalnum() else ''
    return re.compile(left + re.escape(word) + right, re.IGNORECASE)


def kw_in(word: str, text: str) -> bool:
    """키워드가 텍스트에 등장하는지 (경계+대소문자 규칙 적용)."""
    if not text:
        return False
    return _kw_pattern(word).search(text) is not None


def score_item(item: dict, field: str) -> dict:
    """
    제목 + summary 기반 버킷 점수 계산.
    버킷별로 Σ(tier가중치 × 위치가중치)를 cap으로 자른 뒤 합산 + 음수(하한 NEG_FLOOR).
    정규화(0~10)는 save.py에서 SCORE_REF로 수행 — 여기 score는 정규화 전 raw.

    return: {
        score,            # 버킷 합 + 음수 (정규화 전 raw)
        buckets,          # {버킷: capped 점수}
        bucket_hits,      # {버킷: [canon...]}
        title_hits,       # 레거시 호환: 제목 등장 canon 전체(버킷 무관)
        summary_hits,     # 레거시 호환: summary 등장 canon 전체
        negative_hits,    # 감점 canon
    }
    """
    cfg = KEYWORDS[field]
    title = item["title"]
    summary = item["summary"]

    buckets = {}
    bucket_hits = {}
    # 레거시 flat hits (tuesday_prep 등 기존 소비처 호환). 위치별 전체 canon.
    title_hits = []
    summary_hits = []
    seen_title = set()
    seen_summary = set()

    for bucket, sub in cfg.items():
        if bucket == "negative":
            continue
        cap = sub.get("cap", BUCKET_CAPS.get(bucket, 99))
        raw = 0.0
        counted_title = set()    # 같은 버킷·위치 내 canon 1회
        counted_summary = set()
        for tier in _POS_TIERS:
            weight = WEIGHTS[tier]
            for word in sub.get(tier, ()):
                canon = _canon(word)
                if canon not in counted_title and kw_in(word, title):
                    raw += weight * TITLE_WEIGHT
                    counted_title.add(canon)
                if canon not in counted_summary and kw_in(word, summary):
                    raw += weight * BODY_WEIGHT
                    counted_summary.add(canon)
        buckets[bucket] = round(min(raw, cap), 2)
        bucket_hits[bucket] = sorted(counted_title | counted_summary)
        for canon in counted_title:
            if canon not in seen_title:
                title_hits.append(canon)
                seen_title.add(canon)
        for canon in counted_summary:
            if canon not in seen_summary:
                summary_hits.append(canon)
                seen_summary.add(canon)

    # 음수: 버킷 밖, 상한 없이 하한(NEG_FLOOR)만. 엔티티당 1회.
    neg = 0.0
    negative_hits = []
    counted_negative = set()
    for cat, words in cfg.get("negative", {}).items():
        weight = WEIGHTS[cat]
        for word in words:
            canon = _canon(word)
            if canon not in counted_negative and (kw_in(word, title) or kw_in(word, summary)):
                neg += weight  # weight는 음수
                negative_hits.append(canon)
                counted_negative.add(canon)
    neg = max(neg, NEG_FLOOR)

    # 버킷별 가중치 적용 — tech를 비즈니스 버킷보다 무겁게 (BUCKET_WEIGHTS).
    # buckets 딕트는 표시·호환용으로 capped 원값 유지, 합산에만 가중치를 곱한다.
    score = round(
        sum(v * BUCKET_WEIGHTS.get(b, 1.0) for b, v in buckets.items()) + neg, 2
    )
    return {
        "score": score,
        "buckets": buckets,
        "bucket_hits": bucket_hits,
        "title_hits": title_hits,
        "summary_hits": summary_hits,
        "negative_hits": negative_hits,
    }


def score_and_filter(items: list[dict], field: str) -> tuple[list[dict], list[dict]]:
    """
    각 item에 점수 부여 후 정렬.
    return: (선정된 상위 N개, 컷오프 못 넘은 dropped)

    영문 쿼터: 본문 추출용 top-N에 영문 피드 자리를 ENGLISH_QUOTA개 보장한다.
    영문은 헤드라인이 키워드를 적게 때려 점수가 낮아 컷에서 늘 탈락하므로,
    이 자리만은 컷(THRESHOLD)을 우회해 점수 높은 영문 후보를 끌어올린다.
    부족한 자리는 점수 낮은 한글 기사를 빼서 만든다(후보 부족 시 그만큼만).
    """
    for it in items:
        detail = score_item(it, field)
        it["score"] = detail["score"]
        it["score_detail"] = {
            "buckets": detail["buckets"],
            "bucket_hits": detail["bucket_hits"],
            "title_hits": detail["title_hits"],
            "summary_hits": detail["summary_hits"],
            "negative_hits": detail["negative_hits"],
        }

    # 점수 내림차순 정렬
    items.sort(key=lambda x: x["score"], reverse=True)

    # 제목 거의 동일한 재배포 복사본 제거 (최고점 1건만; 정렬 후라 최고점이 대표로 남음)
    items = dedupe_by_title(items)

    passed = [it for it in items if it["score"] >= PYTHON_SCORE_THRESHOLD]
    selected = passed[:TOP_N_FOR_EXTRACT]

    # ── 영문 쿼터 ──────────────────────────────────────────────
    eng_in = [it for it in selected if _is_english_feed(it)]
    need = ENGLISH_QUOTA - len(eng_in)
    if need > 0:
        sel_urls = {it["url"] for it in selected}
        # 아직 안 뽑힌 영문 후보(컷 미만 포함), 점수>0, 이미 점수순 정렬됨
        eng_pool = [
            it for it in items
            if _is_english_feed(it) and it["url"] not in sel_urls and it["score"] > 0
        ]
        promote = eng_pool[:need]
        if promote:
            # 영문 자리만큼 점수 낮은 한글(비영문) 기사를 뺀다
            korean = [it for it in selected if not _is_english_feed(it)]
            drop_n = min(len(promote), len(korean))
            demote_urls = {it["url"] for it in korean[-drop_n:]} if drop_n else set()
            selected = [it for it in selected if it["url"] not in demote_urls] + promote
            selected.sort(key=lambda x: x["score"], reverse=True)
            selected = selected[:TOP_N_FOR_EXTRACT]

    # ── tech 쿼터 ──────────────────────────────────────────────
    # top-N에 'tech 주도' 기사 자리를 TECH_QUOTA개 보장. 시장 뉴스가 product/entity로
    # 자리를 채워 공정 기사가 밀리는 걸 방어. 영문 쿼터는 보존(영문도 tech도 아닌 최저점만 밀어냄).
    tech_in = [it for it in selected if _is_tech_led(it)]
    need = TECH_QUOTA - len(tech_in)
    if need > 0:
        sel_urls = {it["url"] for it in selected}
        tech_pool = [
            it for it in items
            if _is_tech_led(it) and it["url"] not in sel_urls and it["score"] > 0
        ]
        promote = tech_pool[:need]
        # tech도 영문도 아닌 기사(점수순 정렬 상태)에서 최저점부터 밀어내 영문 쿼터 보존
        demotable = [
            it for it in selected
            if not _is_tech_led(it) and not _is_english_feed(it)
        ]
        if promote and demotable:
            drop_n = min(len(promote), len(demotable))
            demote_urls = {it["url"] for it in demotable[-drop_n:]}
            selected = [it for it in selected if it["url"] not in demote_urls] + promote[:drop_n]
            selected.sort(key=lambda x: x["score"], reverse=True)
            selected = selected[:TOP_N_FOR_EXTRACT]

    sel_urls = {it["url"] for it in selected}
    dropped = [
        it for it in items
        if it["url"] not in sel_urls and it["score"] < PYTHON_SCORE_THRESHOLD
    ]

    return selected, dropped[:DROPPED_KEEP]


if __name__ == "__main__":
    from src.collect import collect_field
    from src.resolve import resolve_items

    print("=== 수집 ===")
    items = collect_field("반도체")
    print(f"{len(items)}건")

    print("=== resolve ===")
    items = resolve_items(items)
    print(f"{len(items)}건")

    print("=== 시간 필터 ===")
    items = filter_by_time(items)
    print(f"{len(items)}건")

    print("=== 중복 제거 ===")
    items = dedupe_by_url(items)
    print(f"{len(items)}건")

    print("=== 점수 매기기 ===")
    passed, dropped = score_and_filter(items, "반도체")
    print(f"통과: {len(passed)}건, 탈락: {len(dropped)}건")

    print("\n--- 상위 10개 ---")
    for i, it in enumerate(passed[:10]):
        d = it["score_detail"]
        print(f"[{i+1}] raw={it['score']} | {it['title']}")
        print(f"    buckets: {d['buckets']}")
        print(f"    bucket_hits: {d['bucket_hits']}")
        print(f"    negative_hits: {d['negative_hits']}")
        print()

    print("--- 탈락 5개 (점수 낮은 순) ---")
    for it in dropped[:5]:
        print(f"raw={it['score']} | {it['title']}")
        print(f"  buckets: {it['score_detail']['buckets']}")
