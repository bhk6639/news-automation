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
)
from config.keywords import KEYWORDS, WEIGHTS, ALIASES, BUCKET_CAPS

# 가점 tier 순회 순서. strong을 먼저 둬야 같은 canon이 묶였을 때 높은 가중치로 카운트된다.
_POS_TIERS = ("strong", "medium", "weak")

# 별칭 → 대표값 역매핑. 별칭에 없는 키워드는 자기 자신이 대표.
_ALIAS2CANON = {alias: canon for canon, group in ALIASES.items() for alias in group}


def _canon(word: str) -> str:
    return _ALIAS2CANON.get(word, word)


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

    score = round(sum(buckets.values()) + neg, 2)
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

    passed = [it for it in items if it["score"] >= PYTHON_SCORE_THRESHOLD]
    dropped = [it for it in items if it["score"] < PYTHON_SCORE_THRESHOLD]

    return passed[:TOP_N_FOR_EXTRACT], dropped[:DROPPED_KEEP]


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