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
)
from config.keywords import KEYWORDS, WEIGHTS, ALIASES

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
    제목 + summary 기반 키워드 점수 계산.
    return: {score, title_hits, summary_hits, negative_hits}
    """
    kw = KEYWORDS[field]
    title = item["title"]
    summary = item["summary"]

    title_hits = []
    summary_hits = []
    negative_hits = []
    score = 0.0

    # 별칭(엔티티) 중복 카운트 방지: 대표값 기준으로 위치별 1회만 가산.
    # 예) '하이닉스'(제목) + '하닉'(제목) → 같은 엔티티라 제목에서 1회만.
    counted_title = set()
    counted_summary = set()
    counted_negative = set()

    for category, words in kw.items():
        weight = WEIGHTS[category]
        for word in words:
            in_title = kw_in(word, title)
            in_summary = kw_in(word, summary)
            canon = _canon(word)

            if category.startswith("negative"):
                # 감점: 제목/summary 어디든 등장하면 엔티티당 1회만 감점
                if (in_title or in_summary) and canon not in counted_negative:
                    score += weight  # weight는 음수
                    negative_hits.append(canon)
                    counted_negative.add(canon)
            else:
                # 가점: 제목 등장 1.5배, summary 등장 1배. 엔티티당 위치별 1회.
                if in_title and canon not in counted_title:
                    score += weight * TITLE_WEIGHT
                    title_hits.append(canon)
                    counted_title.add(canon)
                if in_summary and canon not in counted_summary:
                    score += weight * BODY_WEIGHT
                    summary_hits.append(canon)
                    counted_summary.add(canon)

    return {
        "score": round(score, 2),
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
        print(f"[{i+1}] score={it['score']} | {it['title']}")
        print(f"    title_hits: {it['score_detail']['title_hits']}")
        print(f"    summary_hits: {it['score_detail']['summary_hits']}")
        print(f"    negative_hits: {it['score_detail']['negative_hits']}")
        print()

    print("--- 탈락 5개 (점수 낮은 순) ---")
    for it in dropped[:5]:
        print(f"score={it['score']} | {it['title']}")
        print(f"  hits: {it['score_detail']}")