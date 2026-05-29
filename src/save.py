"""
JSON 저장. 날짜 파일명 + latest.json 복사.
"""

import json
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta
from config.settings import DATA_DIR, BODY_TRUNCATE
from config.keywords import KEYWORDS


KST = timezone(timedelta(hours=9))


def item_to_json(item: dict) -> dict:
    """item dict를 JSON 직렬화 가능한 형태로 정리."""
    published = item.get("published")
    return {
        "title": item["title"],
        "date": published.astimezone(KST).strftime("%Y-%m-%d") if published else None,
        "source": item.get("source_name", ""),
        "url": item["url"],
        "summary": item.get("summary", ""),
        "body": item.get("body", "")[:BODY_TRUNCATE],
        "score": item["score"],
        "score_detail": item["score_detail"],
    }


def dropped_to_json(item: dict) -> dict:
    """탈락 항목은 body 제외, 메타만."""
    return {
        "title": item["title"],
        "url": item.get("url", item.get("link", "")),
        "source": item.get("source_name", ""),
        "score": item["score"],
        "score_detail": item["score_detail"],
    }


def save(field: str, items: list[dict], dropped: list[dict],
         failed: list[dict], stats: dict) -> Path:
    """
    JSON 저장. data/YYYY-MM-DD.json + data/latest.json.
    return: 저장된 날짜 파일 경로.
    """
    now_kst = datetime.now(KST)
    date_str = now_kst.strftime("%Y-%m-%d")

    payload = {
        "generated_at": now_kst.isoformat(),
        "field": field,
        "field_date": date_str,
        "stats": stats,
        "keywords_snapshot": {k: sorted(v) for k, v in KEYWORDS[field].items()},
        "items": [item_to_json(it) for it in items],
        "dropped_below_threshold": [dropped_to_json(it) for it in dropped],
        "extract_failed": failed,
    }

    data_dir = Path(DATA_DIR)
    data_dir.mkdir(exist_ok=True)

    dated_path = data_dir / f"{date_str}.json"
    latest_path = data_dir / "latest.json"

    with open(dated_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    shutil.copy(dated_path, latest_path)

    return dated_path


if __name__ == "__main__":
    from src.collect import collect_field
    from src.resolve import resolve_items
    from src.filter import filter_by_time, dedupe_by_url, score_and_filter
    from src.extract import extract_items

    collected = collect_field("반도체")
    resolved = resolve_items(collected)
    timed = filter_by_time(resolved)
    deduped = dedupe_by_url(timed)
    passed, dropped = score_and_filter(deduped, "반도체")
    extracted, failed = extract_items(passed)

    stats = {
        "collected_total": len(collected),
        "after_resolve": len(resolved),
        "after_time_filter": len(timed),
        "after_dedup": len(deduped),
        "after_score_filter": len(passed),
        "extracted_success": len(extracted),
        "extracted_failed": len(failed),
    }

    path = save("반도체", extracted, dropped, failed, stats)
    print(f"저장 완료: {path}")
    print(f"items: {len(extracted)}, dropped: {len(dropped)}, failed: {len(failed)}")
