"""
본문 추출. trafilatura 사용.
실패하거나 본문이 짧으면 drop.
병렬 처리 옵션 지원 (settings.PARALLEL_EXTRACT).
"""

import re
import time
import trafilatura
from concurrent.futures import ThreadPoolExecutor
from config.settings import (
    EXTRACT_TIMEOUT,
    EXTRACT_RETRY,
    EXTRACT_SLEEP,
    MIN_BODY_LENGTH,
    PARALLEL_EXTRACT,
    PARALLEL_WORKERS,
)


def clean_body(text: str) -> str:
    """본문 뒷부분 노이즈 제거 (저작권 고지, 관련기사 목록 등)."""
    patterns = [
        r'\nCopyright\s*©',
        r'\n저작권자',
        r'\n무단\s*전재',
        r'\n\[.*?기자.*?\]',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            text = text[:m.start()].strip()
    return text


def extract_one(url: str) -> tuple[str | None, str]:
    """
    return: (본문 or None, 실패 사유)
    사유: "ok" | "fetch_fail" | "no_body" | "too_short" | "exception"
    """
    for attempt in range(EXTRACT_RETRY + 1):
        try:
            downloaded = trafilatura.fetch_url(url, no_ssl=True)
            if not downloaded:
                if attempt < EXTRACT_RETRY:
                    time.sleep(EXTRACT_SLEEP)
                    continue
                return None, "fetch_fail"
            body = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=False,
                favor_precision=True,
            )
            if not body:
                return None, "no_body"
            body = clean_body(body)
            if len(body) < MIN_BODY_LENGTH:
                return None, f"too_short({len(body)}자)"
            return body.strip(), "ok"
        except Exception as e:
            if attempt < EXTRACT_RETRY:
                time.sleep(EXTRACT_SLEEP)
                continue
            return None, f"exception: {e}"
    return None, "unknown"


def get_body(item: dict) -> tuple[str | None, str]:
    """
    본문 확보. RSS가 본문 전체(rss_body)를 주면 재크롤링 없이 그걸 사용,
    아니면 기사 URL 재크롤링(extract_one).
    - semiengineering 등 재크롤링 차단 사이트는 RSS 본문으로 살림.
    - thelec/KIPOST 등 요약만 주는 피드는 기존대로 재크롤링.
    return: (본문 or None, 사유). 사유 "ok(rss)" | extract_one 사유
    """
    rss_body = item.get("rss_body", "")
    if rss_body:
        body = clean_body(rss_body)
        if len(body) >= MIN_BODY_LENGTH:
            return body.strip(), "ok(rss)"
    return extract_one(item["url"])


def extract_items_sequential(items: list[dict]) -> tuple[list[dict], list[dict]]:
    results = []
    failures = []
    for i, item in enumerate(items):
        body, reason = get_body(item)
        if body:
            item["body"] = body
            results.append(item)
        else:
            failures.append({
                "title": item["title"],
                "url": item.get("url", ""),
                "source": item.get("source_name", ""),
                "score": item["score"],
                "reason": reason,
            })
        if (i + 1) % 10 == 0:
            print(f"  extract 진행: {i+1}/{len(items)} (성공 {len(results)})")
        time.sleep(EXTRACT_SLEEP)

    if failures:
        print("\n--- 본문 추출 실패 ---")
        for f in failures:
            print(f"[{f['reason']}] {f['title']}")
    return results, failures


def extract_items_parallel(items: list[dict]) -> tuple[list[dict], list[dict]]:
    results = []
    failures = []

    def worker(item):
        body, reason = get_body(item)
        return item, body, reason

    with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as ex:
        for i, (item, body, reason) in enumerate(ex.map(worker, items)):
            if body:
                item["body"] = body
                results.append(item)
            else:
                failures.append({
                    "title": item["title"],
                    "url": item.get("url", ""),
                    "source": item.get("source_name", ""),
                    "score": item["score"],
                    "reason": reason,
                })
            if (i + 1) % 10 == 0:
                print(f"  extract 진행: {i+1}/{len(items)} (성공 {len(results)})")

    if failures:
        print("\n--- 본문 추출 실패 ---")
        for f in failures:
            print(f"[{f['reason']}] {f['title']}")
    return results, failures


def extract_items(items: list[dict]) -> tuple[list[dict], list[dict]]:
    if PARALLEL_EXTRACT:
        return extract_items_parallel(items)
    return extract_items_sequential(items)


if __name__ == "__main__":
    from src.collect import collect_field
    from src.resolve import resolve_items
    from src.filter import filter_by_time, dedupe_by_url, score_and_filter

    items = collect_field("반도체")
    items = resolve_items(items)
    items = filter_by_time(items)
    items = dedupe_by_url(items)
    passed, dropped = score_and_filter(items, "반도체")
    print(f"본문 추출 대상: {len(passed)}건")

    extracted, failed = extract_items(passed)
    print(f"본문 추출 성공: {len(extracted)}건, 실패: {len(failed)}건")

    print("\n--- 상위 3개 본문 앞부분 ---")
    for it in extracted[:3]:
        print(f"제목: {it['title']}")
        print(f"점수: {it['score']}")
        print(f"본문 ({len(it['body'])}자): {it['body'][:200]}...")
        print()
