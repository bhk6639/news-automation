# -*- coding: utf-8 -*-
"""
화요일 보강 루틴 B - 기계적 집계 단계 (파이썬 담당)

data/ 폴더의 최근 N일(기본 7일) JSON을 읽어 클로드 루틴이 판단할 수 있도록
탈락 후보 / 키워드 사용 / 노이즈 / 추출 실패 / stats 추세를 집계한다.

원칙:
- 판단/개선 없음. 순수 집계만. (LLM 판단은 클로드 루틴 담당)
- JSON 스키마 변화에 방어적 (summary/score_raw/extract_failed.url 등 누락 허용)

출력:
- data/tuesday_prep.json : 클로드 루틴이 읽는 집계 결과
- data/tuesday_log.json  : 실행 로그 누적 (append)

실행:
    python tuesday_prep.py            # 오늘(KST) 기준 최근 7일
    python tuesday_prep.py --days 7   # 윈도우 일수 지정
"""

import os
import json
import glob
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
PREP_PATH = os.path.join(DATA_DIR, "tuesday_prep.json")
LOG_PATH = os.path.join(DATA_DIR, "tuesday_log.json")

# 집계 상한 (토큰 절약)
TOP_DROPPED = 25
TOP_SOURCES = 15


def parse_file_date(path):
    """파일명 2026-06-05.json -> date. latest.json 등은 None."""
    name = os.path.basename(path).replace(".json", "")
    try:
        return datetime.strptime(name, "%Y-%m-%d").date()
    except ValueError:
        return None


def load_window(days):
    """오늘(KST) 기준 최근 days일 범위의 날짜 파일을 로드."""
    today = datetime.now(KST).date()
    start = today - timedelta(days=days - 1)

    loaded = []
    for path in glob.glob(os.path.join(DATA_DIR, "*.json")):
        d = parse_file_date(path)
        if d is None:
            continue
        if start <= d <= today:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    loaded.append((d, json.load(f)))
            except (json.JSONDecodeError, OSError):
                continue

    loaded.sort(key=lambda x: x[0])
    found_dates = [d.isoformat() for d, _ in loaded]
    expected = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    missing = [d for d in expected if d not in found_dates]

    return {
        "today": today.isoformat(),
        "window_start": start.isoformat(),
        "window_end": today.isoformat(),
        "days": days,
        "found_dates": found_dates,
        "missing_dates": missing,
        "data": loaded,
    }


def hits_of(detail, *keys):
    """score_detail에서 title_hits/summary_hits/negative_hits 안전 추출."""
    if not isinstance(detail, dict):
        return []
    out = []
    for k in keys:
        v = detail.get(k)
        if isinstance(v, list):
            out.extend(v)
    return out


def aggregate(win):
    data = win["data"]

    # 1. stats 추세
    stats_trend = []
    for d, doc in data:
        s = doc.get("stats", {})
        stats_trend.append({
            "date": d.isoformat(),
            "collected_total": s.get("collected_total"),
            "after_score_filter": s.get("after_score_filter"),
            "extracted_success": s.get("extracted_success"),
            "extracted_failed": s.get("extracted_failed"),
        })

    def avg(field):
        vals = [r[field] for r in stats_trend if isinstance(r[field], (int, float))]
        return round(sum(vals) / len(vals), 1) if vals else None

    stats_avg = {
        "collected_total": avg("collected_total"),
        "after_score_filter": avg("after_score_filter"),
        "extracted_success": avg("extracted_success"),
        "extracted_failed": avg("extracted_failed"),
    }

    # 2. 탈락 후보 (누락 검토용) - url 기준 dedup, 점수순
    dropped_by_url = {}
    for d, doc in data:
        for art in doc.get("dropped_below_threshold", []):
            url = art.get("url")
            key = url or (art.get("title", "") + art.get("source", ""))
            detail = art.get("score_detail", {})
            rec = {
                "title": art.get("title"),
                "source": art.get("source"),
                "score": art.get("score"),
                "date": d.isoformat(),
                "title_hits": hits_of(detail, "title_hits"),
                "summary_hits": hits_of(detail, "summary_hits"),
                "negative_hits": hits_of(detail, "negative_hits"),
            }
            prev = dropped_by_url.get(key)
            # 같은 기사 여러 날 등장 시 가장 높은 점수만 유지
            if prev is None or (rec["score"] or 0) > (prev["score"] or 0):
                dropped_by_url[key] = rec
    dropped_candidates = sorted(
        dropped_by_url.values(), key=lambda r: (r["score"] or 0), reverse=True
    )[:TOP_DROPPED]

    # 3. 키워드 사용 빈도 (선정기사 + 탈락기사의 title/summary hits)
    kw_counter = Counter()
    neg_counter = Counter()
    for d, doc in data:
        for art in doc.get("items", []) + doc.get("dropped_below_threshold", []):
            detail = art.get("score_detail", {})
            for kw in hits_of(detail, "title_hits", "summary_hits"):
                kw_counter[kw] += 1
            for kw in hits_of(detail, "negative_hits"):
                neg_counter[kw] += 1

    # 현재(최신 파일) 키워드 스냅샷 기준 죽은 키워드 탐지.
    # critical 포함 — 없으면 차세대 공정/메모리 tier가 탐지 대상에서 통째로 빠진다.
    # 옛 JSON(critical 키 없음)은 .get으로 빈 리스트가 되어 그대로 동작한다.
    # ⚠️ save.keywords_snapshot이 canon으로 접어 저장하므로 kw_counter(canon 집계)와
    #    같은 축에서 비교된다. 스냅샷이 표면형이던 옛 JSON은 별칭이 dead로 잡히니
    #    (하닉/hynix/D램 등) 그 구간 결과는 참고만 할 것.
    latest_doc = data[-1][1] if data else {}
    snapshot = latest_doc.get("keywords_snapshot", {})
    snapshot_pos = []
    for tier in ("critical", "strong", "medium", "weak"):
        snapshot_pos.extend(snapshot.get(tier, []))
    dead_keywords = sorted({kw for kw in snapshot_pos if kw_counter.get(kw, 0) == 0})

    keyword_usage = [
        {"keyword": kw, "hits": cnt} for kw, cnt in kw_counter.most_common()
    ]
    negative_usage = [
        {"keyword": kw, "hits": cnt} for kw, cnt in neg_counter.most_common()
    ]

    # 4. 노이즈 점검: 선정(items)됐는데 negative_hits 있는 기사
    passed_with_negative = []
    for d, doc in data:
        for art in doc.get("items", []):
            negs = hits_of(art.get("score_detail", {}), "negative_hits")
            if negs:
                passed_with_negative.append({
                    "title": art.get("title"),
                    "source": art.get("source"),
                    "score": art.get("score"),
                    "date": d.isoformat(),
                    "negative_hits": negs,
                })

    # 5. 추출 실패 패턴 (사유별 / 소스별)
    fail_by_reason = Counter()
    fail_by_source = Counter()
    fail_total = 0
    for d, doc in data:
        for art in doc.get("extract_failed", []):
            fail_total += 1
            fail_by_reason[normalize_reason(art.get("reason"))] += 1
            fail_by_source[art.get("source") or "(unknown)"] += 1

    # 6. 선정 기사 소스 분포 (편향 확인)
    source_counter = Counter()
    for d, doc in data:
        for art in doc.get("items", []):
            source_counter[art.get("source") or "(unknown)"] += 1

    return {
        "stats_trend": stats_trend,
        "stats_avg": stats_avg,
        "dropped_candidates": dropped_candidates,
        "keyword_usage": keyword_usage,
        "dead_keywords": dead_keywords,
        "negative_usage": negative_usage,
        "passed_with_negative": passed_with_negative,
        "extract_failed": {
            "total": fail_total,
            "by_reason": dict(fail_by_reason.most_common()),
            "by_source": dict(fail_by_source.most_common()),
        },
        "selected_source_distribution": dict(source_counter.most_common(TOP_SOURCES)),
    }


def normalize_reason(reason):
    """too_short(41자) -> too_short 처럼 변동 부분 제거해 집계 가능하게."""
    if not reason:
        return "(unknown)"
    return reason.split("(")[0].strip()


def write_log(win):
    entry = {
        "ran_at": datetime.now(KST).isoformat(),
        "window_start": win["window_start"],
        "window_end": win["window_end"],
        "files_used": win["found_dates"],
        "missing_dates": win["missing_dates"],
    }
    log = []
    if os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH, "r", encoding="utf-8") as f:
                log = json.load(f)
            if not isinstance(log, list):
                log = []
        except (json.JSONDecodeError, OSError):
            log = []
    log.append(entry)
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    return entry


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="윈도우 일수 (기본 7)")
    args = ap.parse_args()

    win = load_window(args.days)

    if not win["data"]:
        print(f"[경고] {win['window_start']} ~ {win['window_end']} 범위에 JSON 파일이 없습니다.")
        prep = {
            "generated_at": datetime.now(KST).isoformat(),
            "window": {k: win[k] for k in
                       ("today", "window_start", "window_end", "days",
                        "found_dates", "missing_dates")},
            "empty": True,
        }
    else:
        agg = aggregate(win)
        prep = {
            "generated_at": datetime.now(KST).isoformat(),
            "window": {k: win[k] for k in
                       ("today", "window_start", "window_end", "days",
                        "found_dates", "missing_dates")},
            "empty": False,
            **agg,
        }

    with open(PREP_PATH, "w", encoding="utf-8") as f:
        json.dump(prep, f, ensure_ascii=False, indent=2)

    log_entry = write_log(win)

    # 콘솔 요약
    print(f"집계 완료: {win['window_start']} ~ {win['window_end']}")
    print(f"  사용 파일 {len(win['found_dates'])}개: {', '.join(win['found_dates']) or '없음'}")
    if win["missing_dates"]:
        print(f"  결측일: {', '.join(win['missing_dates'])}")
    if not prep.get("empty"):
        print(f"  탈락 후보 {len(prep['dropped_candidates'])}건 / "
              f"죽은 키워드 {len(prep['dead_keywords'])}개 / "
              f"추출 실패 {prep['extract_failed']['total']}건")
    print(f"  -> {PREP_PATH}")
    print(f"  -> 로그 기록 {log_entry['ran_at']}")


if __name__ == "__main__":
    main()
