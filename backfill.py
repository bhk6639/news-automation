"""
누락일 백필 (일회성/수동). 정기 파이프라인(src.main)과 동일 단계를 과거 24시간 구간에 대해 실행.

사용: python backfill.py 2026-10-04
  → KST 2026-10-03 03:00 ~ 2026-10-04 03:00 구간 기사로 data/2026-10-04.json 생성
     (정기 실행이 KST 03:00에 돌았다면 만들었을 파일과 같은 구간/파일명)

정기 파이프라인과 다른 점:
- Google News 쿼리: 'when:1d' 대신 'after:/before:' 날짜 연산자로 과거 구간 조회
  (100건 cap 완화를 위해 구간에 걸친 날짜별로 쿼리 분할)
- 시간 필터: now 기준이 아니라 지정 구간 [end-24h, end)
- resolve 전에 시간 필터 선적용 (구간 밖 기사 decode 낭비 방지)
- latest.json은 건드리지 않음 (데일리 루틴 입력 보호). payload에 backfill 메타 추가
- 직접 RSS 피드(SemiEngineering 등)는 최근 N건만 제공 → 오래된 구간일수록 누락 가능
"""

import sys
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import config.sources as sources_mod
from config.settings import TIME_WINDOW_HOURS, DATA_DIR
from src import collect as collect_mod
from src.resolve import resolve_items
from src.filter import dedupe_by_url, score_and_filter
from src.extract import extract_items
from src.save import item_to_json, dropped_to_json, keywords_snapshot

KST = timezone(timedelta(hours=9))
WHEN_TOKEN = quote(" when:1d")


def window_for(date_str: str) -> tuple[datetime, datetime]:
    end = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=3, tzinfo=KST)
    return end - timedelta(hours=TIME_WINDOW_HOURS), end


def backfill_sources(field: str, start: datetime, end: datetime) -> list[dict]:
    """Google News 소스를 구간 날짜별 after/before 쿼리로 분할. 직접피드는 그대로."""
    out = []
    # Google 날짜 경계 시간대가 불명확하므로 UTC/KST 날짜를 모두 덮도록 앞뒤 하루 여유
    d0 = (start.astimezone(timezone.utc).date()) - timedelta(days=1)
    d1 = end.astimezone(KST).date()
    for src in sources_mod.SOURCES[field]:
        if WHEN_TOKEN not in src["url"]:
            out.append(src)
            continue
        d = d0
        while d <= d1:
            s = deepcopy(src)
            ops = quote(f" after:{d.isoformat()} before:{(d + timedelta(days=1)).isoformat()}")
            s["url"] = src["url"].replace(WHEN_TOKEN, ops)
            out.append(s)
            d += timedelta(days=1)
    return out


def in_window(items: list[dict], start: datetime, end: datetime) -> list[dict]:
    return [it for it in items if it["published"] and start <= it["published"] < end]


def run(date_str: str, field: str = "반도체") -> Path:
    start, end = window_for(date_str)
    print(f"=== 백필 {date_str}: {start.isoformat()} ~ {end.isoformat()} ===")

    srcs = backfill_sources(field, start, end)
    sources_mod.SOURCES = {**sources_mod.SOURCES, field: srcs}
    collect_mod.SOURCES = sources_mod.SOURCES
    print(f"[0] 소스 {len(srcs)}개 (Google News 날짜 분할 포함)")

    collected = collect_mod.collect_field(field)
    print(f"[1] RSS 수집 {len(collected)}건")

    # 날짜 분할 쿼리끼리 겹치는 원본 링크 제거 + 구간 선필터 (resolve 비용 절감)
    seen, pre = set(), []
    for it in in_window(collected, start, end):
        if it["link"] not in seen:
            seen.add(it["link"])
            pre.append(it)
    print(f"    구간 내 고유 {len(pre)}건")

    resolved = resolve_items(pre)
    print(f"[2] URL resolve {len(resolved)}건")

    timed = in_window(resolved, start, end)
    print(f"[3] 시간 필터 {len(timed)}건")

    deduped = dedupe_by_url(timed)
    print(f"[4] 중복 제거 {len(deduped)}건")

    passed, dropped = score_and_filter(deduped, field)
    print(f"[5] 통과 {len(passed)}건, 탈락 {len(dropped)}건")

    extracted, failed = extract_items(passed)
    print(f"[6] 본문 성공 {len(extracted)}건, 실패 {len(failed)}건")

    stats = {
        "collected_total": len(collected),
        "after_resolve": len(resolved),
        "after_time_filter": len(timed),
        "after_dedup": len(deduped),
        "after_score_filter": len(passed),
        "extracted_success": len(extracted),
        "extracted_failed": len(failed),
    }
    payload = {
        "generated_at": end.isoformat(),  # 정기 실행 시각 기준 (소비처 날짜 판정 호환)
        "field": field,
        "field_date": date_str,
        "backfill": {
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "run_at": datetime.now(KST).isoformat(),
        },
        "stats": stats,
        "keywords_snapshot": keywords_snapshot(field),
        "items": [item_to_json(it) for it in extracted],
        "dropped_below_threshold": [dropped_to_json(it) for it in dropped],
        "extract_failed": failed,
    }
    path = Path(DATA_DIR) / f"{date_str}.json"
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[7] 저장 {path}")
    return path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python backfill.py YYYY-MM-DD [field]")
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "반도체")
