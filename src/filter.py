"""
시간 필터 → 중복 제거 → 점수 매기기.
"""

import hashlib
from datetime import datetime, timezone, timedelta
from config.settings import (
    TIME_WINDOW_HOURS,
    PYTHON_SCORE_THRESHOLD,
    TITLE_WEIGHT,
    BODY_WEIGHT,
    TOP_N_FOR_EXTRACT,
    DROPPED_KEEP,
)
from config.keywords import KEYWORDS, WEIGHTS


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

    for category, words in kw.items():
        weight = WEIGHTS[category]
        for word in words:
            in_title = word in title
            in_summary = word in summary

            if category.startswith("negative"):
                # 감점: 제목/summary 어디든 등장하면 1회만 감점
                if in_title or in_summary:
                    score += weight  # weight는 음수
                    negative_hits.append(word)
            else:
                # 가점: 제목 등장은 1.5배, summary 등장은 1배 (둘 다면 둘 다 가산)
                if in_title:
                    score += weight * TITLE_WEIGHT
                    title_hits.append(word)
                if in_summary:
                    score += weight * BODY_WEIGHT
                    summary_hits.append(word)

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