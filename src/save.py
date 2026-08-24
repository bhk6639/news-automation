"""
JSON 저장. 날짜 파일명 + latest.json 복사.
"""

import json
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta
from config.settings import (
    DATA_DIR,
    BODY_TRUNCATE,
    BODY_TRUNCATE_KO,
    ENGLISH_FEEDS,
    SCORE_REF,
)
from config.keywords import KEYWORDS, ALIASES


KST = timezone(timedelta(hours=9))

# critical 포함 필수 — 빠지면 차세대 공정/메모리 키워드(EUV·노드·단수·CXL 등)가
# 스냅샷에서 통째로 사라져, 소비처의 죽은 키워드 탐지가 그 tier를 영영 못 본다.
_POS_TIERS = ("critical", "strong", "medium", "weak")
_SNAP_TIERS = _POS_TIERS + ("neg_strong", "neg_weak")

# 별칭 → 대표값(canon) 역매핑. filter._ALIAS2CANON과 같은 규칙.
_ALIAS2CANON = {alias: canon for canon, group in ALIASES.items() for alias in group}


def keywords_snapshot(field: str) -> dict:
    """버킷 구조를 평탄한 tier별 목록으로 펼치되 canon(대표값)으로 접어 저장.

    canon으로 접는 이유:
      score_detail의 hits는 canon으로 기록된다(filter.score_item). 그래서 소비처가
      집계하는 keyword_usage도 canon 단위다. 스냅샷만 표면형으로 두면 canon이 아닌
      별칭(하닉/hynix/D램/176단 …)은 실제로 아무리 많이 걸려도 usage와 매칭되지 않아
      영원히 '죽은 키워드'로 보인다. 두 축을 canon으로 맞춰야 dead 판정이 성립한다.

    tuesday_prep 등 평탄 스냅샷을 읽는 소비처 호환.
    (옛 JSON에는 critical 키가 없으므로 소비처는 .get 접근을 유지할 것)
    """
    snap = {t: set() for t in _SNAP_TIERS}
    for bucket, sub in KEYWORDS[field].items():
        if bucket == "negative":
            for cat, words in sub.items():
                snap[cat] |= {_ALIAS2CANON.get(w, w) for w in words}
        else:
            for tier in _POS_TIERS:
                snap[tier] |= {_ALIAS2CANON.get(w, w) for w in sub.get(tier, ())}
    return {k: sorted(v) for k, v in snap.items()}


def item_to_json(item: dict) -> dict:
    """item dict를 JSON 직렬화 가능한 형태로 정리.
    score는 고정 기준(SCORE_REF) 0~10 정규화. 배치 최댓값 의존 폐기."""
    published = item.get("published")
    raw_score = item["score"]
    normalized = min(10.0, max(0.0, raw_score) / SCORE_REF * 10) if SCORE_REF > 0 else 0
    # 본문 길이: 영문 피드는 1000자, 한글은 600자 (루틴 토큰 절약)
    limit = BODY_TRUNCATE if item.get("rss_source") in ENGLISH_FEEDS else BODY_TRUNCATE_KO
    return {
        "title": item["title"],
        "date": published.astimezone(KST).strftime("%Y-%m-%d") if published else None,
        "source": item.get("source_name", ""),
        "url": item["url"],
        "summary": item.get("summary", ""),
        "body": item.get("body", "")[:limit],
        "score": round(normalized, 2),
        "score_raw": raw_score,
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
        "keywords_snapshot": keywords_snapshot(field),
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
