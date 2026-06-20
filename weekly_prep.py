# -*- coding: utf-8 -*-
"""
화요일 보강 루틴 A - 기계적 조회 단계 (파이썬 담당)

노션 "통합 뉴스 DB"를 필터 쿼리로 읽어, 클로드 원격 루틴이 주간 브리핑 작성과
요약 보완을 판단할 수 있도록 기간 내 페이지 전체를 data/weekly_prep.json으로 커밋한다.

배경:
- Notion MCP의 notion-fetch는 데이터소스 조회 시 스키마만 반환하고 행(페이지)을 주지 않아
  날짜/카테고리 필터 쿼리가 불가능하다. (notion-search는 시맨틱 + 25건 한계라 누락 발생)
- 따라서 "읽기"는 파이썬 Notion REST API(/databases/{id}/query)로 수행한다.
  (이 방식은 src/check_notion.py에서 이미 검증됨: 필터 쿼리로 results 반환)
- "쓰기/판단"(요약 보완 update, 주간 브리핑 create, 본문 web_fetch)은
  클로드 원격 루틴이 MCP로 담당한다.

원칙:
- 판단/요약 생성 없음. 순수 조회만. (LLM 판단은 클로드 루틴 담당)
- 페이지네이션으로 누락 없이 전체 조회. (A 프롬프트의 "빠짐없이" 요구 충족)
- 노션 응답 스키마 변화에 방어적 (속성 누락 허용).

출력:
- data/weekly_prep.json : 클로드 원격 루틴이 raw.githubusercontent에서 fetch해 읽는 결과
- data/weekly_log.json  : 실행 로그 누적 (append)

실행:
    python weekly_prep.py
환경변수(GitHub Secrets):
    NOTION_TOKEN, NOTION_DATABASE_ID
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta, timezone

import requests

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]

KST = timezone(timedelta(hours=9))

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
PREP_PATH = os.path.join(DATA_DIR, "weekly_prep.json")
LOG_PATH = os.path.join(DATA_DIR, "weekly_log.json")

API = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

# 노션 DB 속성 이름 (CLAUDE.md 스키마 기준)
TITLE_PROP = "헤드라인"
DATE_PROP = "날짜"
CAT_PROP = "카테고리"
LINK_PROP = "링크"
SUMMARY_PROP = "요약"

# 이전 주간 브리핑이 없을 때 기본 윈도우 (어제 포함 7일 = 어제-6)
DEFAULT_WINDOW_DAYS = 7

EXCLUDE_CATEGORIES = ["데일리 브리핑", "주간 브리핑"]


# ---------- 속성 추출 헬퍼 (스키마 방어적) ----------

def _props(page):
    return page.get("properties", {}) if isinstance(page, dict) else {}


def get_title(page):
    arr = _props(page).get(TITLE_PROP, {}).get("title", []) or []
    return "".join(t.get("plain_text", "") for t in arr).strip()


def get_date(page):
    d = _props(page).get(DATE_PROP, {}).get("date")
    if not d:
        return None
    start = d.get("start")
    # "2026-06-05" 또는 "2026-06-05T..." -> 날짜부만
    return start[:10] if start else None


def get_link(page):
    return _props(page).get(LINK_PROP, {}).get("url")


def get_summary(page):
    arr = _props(page).get(SUMMARY_PROP, {}).get("rich_text", []) or []
    return "".join(t.get("plain_text", "") for t in arr).strip()


def get_categories(page):
    arr = _props(page).get(CAT_PROP, {}).get("multi_select", []) or []
    return [o.get("name") for o in arr if o.get("name")]


# ---------- 노션 쿼리 ----------

def query_all(payload):
    """페이지네이션으로 results 전체 수집 (has_more 끝까지)."""
    results = []
    cursor = None
    while True:
        body = dict(payload)
        if cursor:
            body["start_cursor"] = cursor
        res = requests.post(API, headers=HEADERS, json=body, timeout=30)
        res.raise_for_status()
        data = res.json()
        results.extend(data.get("results", []))
        if data.get("has_more"):
            cursor = data.get("next_cursor")
            if not cursor:
                break
        else:
            break
    return results


def find_start_date(end_date, window_days=DEFAULT_WINDOW_DAYS):
    """가장 최근 '주간 브리핑' 페이지 날짜 + 1일.
    없으면 어제 기준 window_days 윈도우 시작(기본 어제-6).
    반환: (start_iso, prev_briefing_date or None)
    """
    payload = {
        "filter": {"property": TITLE_PROP, "title": {"contains": "주간 브리핑"}},
        "sorts": [{"property": DATE_PROP, "direction": "descending"}],
        "page_size": 1,
    }
    res = requests.post(API, headers=HEADERS, json=payload, timeout=30)
    res.raise_for_status()
    results = res.json().get("results", [])
    if results:
        prev = get_date(results[0])
        if prev:
            start = datetime.strptime(prev, "%Y-%m-%d").date() + timedelta(days=1)
            return start.isoformat(), prev
    start = end_date - timedelta(days=window_days - 1)
    return start.isoformat(), None


def fetch_window(start_iso, end_iso):
    """기간 내 페이지 전체 조회 (데일리/주간 브리핑 제외, 날짜 오름차순)."""
    and_filters = [
        {"property": DATE_PROP, "date": {"on_or_after": start_iso}},
        {"property": DATE_PROP, "date": {"on_or_before": end_iso}},
    ]
    for cat in EXCLUDE_CATEGORIES:
        and_filters.append(
            {"property": CAT_PROP, "multi_select": {"does_not_contain": cat}}
        )
    payload = {
        "filter": {"and": and_filters},
        "sorts": [{"property": DATE_PROP, "direction": "ascending"}],
        "page_size": 100,
    }
    return query_all(payload)


def build_pages(raw):
    pages = []
    for p in raw:
        summ = get_summary(p)
        pages.append({
            "page_id": p.get("id"),
            "page_url": p.get("url"),
            "headline": get_title(p),
            "date": get_date(p) or "",
            "link": get_link(p),
            "summary": summ,
            "summary_empty": (summ == ""),
            "categories": get_categories(p),
        })
    return pages


# ---------- 로그 ----------

def write_log(entry):
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


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=DEFAULT_WINDOW_DAYS,
                    help="이전 브리핑 없을 때 윈도우 일수 (기본 7)")
    args = ap.parse_args()

    now_kst = datetime.now(KST)
    today = now_kst.date()
    end_date = today - timedelta(days=1)  # 어제(KST)
    end_iso = end_date.isoformat()

    start_iso, prev_briefing = find_start_date(end_date, window_days=args.days)

    window = {
        "today": today.isoformat(),
        "window_start": start_iso,
        "window_end": end_iso,
        "prev_briefing_date": prev_briefing,
    }

    # 시작일이 어제보다 늦으면(직전 브리핑이 어제) 새 뉴스 없음 -> empty
    if start_iso > end_iso:
        prep = {
            "generated_at": now_kst.isoformat(),
            "window": window,
            "empty": True,
            "reason": "window_start > window_end (직전 브리핑 이후 신규 기간 없음)",
            "pages": [],
            "total": 0,
            "summary_empty_count": 0,
        }
    else:
        raw = fetch_window(start_iso, end_iso)
        pages = build_pages(raw)
        empty_cnt = sum(1 for p in pages if p["summary_empty"])
        prep = {
            "generated_at": now_kst.isoformat(),
            "window": window,
            "empty": (len(pages) == 0),
            "pages": pages,
            "total": len(pages),
            "summary_empty_count": empty_cnt,
        }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PREP_PATH, "w", encoding="utf-8") as f:
        json.dump(prep, f, ensure_ascii=False, indent=2)

    write_log({
        "ran_at": now_kst.isoformat(),
        "window_start": start_iso,
        "window_end": end_iso,
        "prev_briefing_date": prev_briefing,
        "total": prep.get("total", 0),
        "summary_empty_count": prep.get("summary_empty_count", 0),
        "empty": prep.get("empty"),
    })

    print(f"조회 완료: {start_iso} ~ {end_iso}")
    print(f"  직전 주간 브리핑: {prev_briefing or '없음(기본 7일 윈도우)'}")
    print(f"  전체 {prep.get('total', 0)}건 / 요약 빈 페이지 {prep.get('summary_empty_count', 0)}건")
    print(f"  -> {PREP_PATH}")


if __name__ == "__main__":
    main()
