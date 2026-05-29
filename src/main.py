"""
진입점. 분야 받아서 전체 파이프라인 실행.
GitHub Actions에서 호출.
"""

import sys
from src.collect import collect_field
from src.resolve import resolve_items
from src.filter import filter_by_time, dedupe_by_url, score_and_filter
from src.extract import extract_items
from src.save import save


def run(field: str = "반도체") -> None:
    print(f"=== 파이프라인 시작: {field} ===")

    print("[1] RSS 수집")
    collected = collect_field(field)
    print(f"    {len(collected)}건")

    print("[2] URL resolve")
    resolved = resolve_items(collected)
    print(f"    {len(resolved)}건")

    print("[3] 시간 필터")
    timed = filter_by_time(resolved)
    print(f"    {len(timed)}건")

    print("[4] 중복 제거")
    deduped = dedupe_by_url(timed)
    print(f"    {len(deduped)}건")

    print("[5] 점수 매기기")
    passed, dropped = score_and_filter(deduped, field)
    print(f"    통과 {len(passed)}건, 탈락 {len(dropped)}건")

    print("[6] 본문 추출")
    extracted, failed = extract_items(passed)
    print(f"    성공 {len(extracted)}건, 실패 {len(failed)}건")

    print("[7] JSON 저장")
    stats = {
        "collected_total": len(collected),
        "after_resolve": len(resolved),
        "after_time_filter": len(timed),
        "after_dedup": len(deduped),
        "after_score_filter": len(passed),
        "extracted_success": len(extracted),
        "extracted_failed": len(failed),
    }
    path = save(field, extracted, dropped, failed, stats)
    print(f"    {path}")

    print(f"=== 완료 ===")


if __name__ == "__main__":
    field = sys.argv[1] if len(sys.argv) > 1 else "반도체"
    run(field)