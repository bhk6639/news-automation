#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
measure_tech_density.py  —  읽기 전용 진단 스크립트 (파이프라인 비침습)

목적
----
"한 기사(제목+요약)에 tech 키워드가 실제로 몇 개나 등장하는가?"를 실측한다.
가설 검증: tech는 stack이 안 되고(보통 1~2개), 비즈니스 차원(entity+product+event)은
한 헤드라인에서 같이 쌓인다 → 깊이가 넓이에 구조적으로 진다.

특징
----
- config/keywords.py, config/sources.py 를 "그대로" 로드 → 키워드 항상 동기화.
- 채점 로직(filter.py)은 import 하지 않고, 문서화된 매칭 규칙만 재현:
    · 제목+요약을 대상으로
    · 버킷별로 "등장 여부"만 카운트(중복 X)
    · ALIASES로 별칭 1회 접음(예: 본딩/하이브리드본딩 → 1개)
  → 이 스크립트는 '점수'가 아니라 '몇 종류가 등장했나(개수)'를 센다.
- 어떤 파일도 쓰지 않는다. 네트워크는 피드 GET만. 코드 수정 없음.

사용
----
  # 레포 루트에서 (config/ 가 보이는 곳)
  python measure_tech_density.py                # SOURCES의 when:1d 그대로
  python measure_tech_density.py --days 7       # 구글뉴스 윈도를 7일로 넓혀 표본↑
  python measure_tech_density.py --repo /path/to/news-automation
  python measure_tech_density.py --examples 8   # 카운트별 예시 헤드라인 출력
  python measure_tech_density.py --selftest     # 네트워크 없이 샘플 헤드라인으로 동작확인

의존성: feedparser  (pip install feedparser)
"""

from __future__ import annotations
import argparse
import html
import importlib.util
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from functools import lru_cache

# ----------------------------------------------------------------------------
# config 로드 (파일 경로로 직접 로드 → 패키지/__init__ 유무와 무관)
# ----------------------------------------------------------------------------
def _load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def load_config(repo: str):
    kw_path = os.path.join(repo, "config", "keywords.py")
    src_path = os.path.join(repo, "config", "sources.py")
    if not os.path.exists(kw_path):
        sys.exit(f"[!] {kw_path} 없음. --repo 로 레포 루트를 지정하거나 루트에서 실행하세요.")
    kw = _load_module(kw_path, "_kwcfg")
    sources = None
    if os.path.exists(src_path):
        sources = _load_module(src_path, "_srccfg")
    return kw, sources


# ----------------------------------------------------------------------------
# 매칭기: 문서화된 규칙 재현 (등장 여부 + 별칭 1회 접기)
# ----------------------------------------------------------------------------
BUCKETS_TECH = ["tech"]
BUCKETS_BIZ = ["entity", "product", "event"]  # '넓이' = 비즈니스 차원
TIERS = ("critical", "strong", "medium", "weak")


def build_bucket_terms(KEYWORDS, field: str):
    """분야(field)의 각 버킷에 대해 {버킷: [(rep, [surface_forms...])]} 생성.
    surface form 은 소문자 비교용으로 보관."""
    spec = KEYWORDS[field]
    out = {}
    for bucket, conf in spec.items():
        if bucket == "negative":
            continue
        kws = set()
        for tier in TIERS:
            kws |= set(conf.get(tier, set()) or set())
        out[bucket] = kws
    return out


def build_alias_map(ALIASES):
    """surface(lower) -> 대표값. 같은 그룹은 한 대표값으로 접힘."""
    m = {}
    for rep, members in ALIASES.items():
        for s in members:
            m[s.lower()] = rep
    return m


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def clean(text: str) -> str:
    if not text:
        return ""
    text = _TAG.sub(" ", text)
    return _WS.sub(" ", text).strip()


# --- collect.py 의 본문 추출 로직을 그대로 복제 (rss_body 길이를 동일 기준으로 측정) ---
def html_to_text(html_str: str) -> str:
    """RSS content:encoded(HTML)를 문단 보존하며 평문으로. (collect.html_to_text 복제)"""
    if not html_str:
        return ""
    text = re.sub(r"(?i)</p>|<br\s*/?>|</div>|</li>|</h[1-6]>", "\n", html_str)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def extract_rss_content(entry) -> str:
    """RSS 항목이 본문 전체(content:encoded)를 주면 평문 반환. 없으면 ''. (collect 복제)"""
    if entry.get("content"):
        return html_to_text(entry["content"][0].get("value", ""))
    return ""


@lru_cache(maxsize=None)
def _kw_pattern(word: str) -> "re.Pattern":
    """filter.py 의 _kw_pattern 을 그대로 복제 — 단어 경계 + 대소문자 무시.
    왼쪽: 앞에 ASCII 영숫자 오면 차단('physics'의 'sic' 막음).
    오른쪽: 뒤에 ASCII 글자만 차단(숫자는 허용 → 'HBM'→'HBM3' 매칭).
    한쪽 끝이 한글이면 그쪽 경계 없음."""
    if re.fullmatch(r"1[a-d]", word):  # DRAM 세대코드: 뒤 컨텍스트 필수 (filter.py와 동일)
        return re.compile(r"(?<![A-Za-z0-9])" + word + r"\s*(?:나노|nm|디램|D램|DRAM)", re.IGNORECASE)
    left = r"(?<![A-Za-z0-9])" if word[0].isascii() and word[0].isalnum() else ""
    right = r"(?![A-Za-z])" if word[-1].isascii() and word[-1].isalnum() else ""
    return re.compile(left + re.escape(word) + right, re.IGNORECASE)


def matched_reps(text: str, surface_set, alias_map) -> set:
    """text 안에 등장한 키워드들을 대표값(별칭 접기)으로 환원한 집합.
    filter._kw_pattern 과 동일한 경계 규칙으로 매칭(부분문자열 허수 제거)."""
    reps = set()
    for kw in surface_set:
        if _kw_pattern(kw).search(text):
            reps.add(alias_map.get(kw.lower(), kw))
    return reps


# ----------------------------------------------------------------------------
# 피드 수집
# ----------------------------------------------------------------------------
def widen_google(url: str, days: int) -> str:
    if days and days != 1 and "news.google.com" in url:
        return re.sub(r"when:1d", f"when:{days}d", url)
    return url


def iter_entries(SOURCES, field: str, days: int):
    import feedparser
    feeds = SOURCES.get(field, [])
    for f in feeds:
        url = widen_google(f["url"], days)
        try:
            d = feedparser.parse(url)
        except Exception as e:
            print(f"  [skip] {f['name']}: {e}", file=sys.stderr)
            continue
        n = 0
        for e in d.entries:
            title = clean(e.get("title", ""))
            summary = clean(e.get("summary", "") or e.get("description", ""))
            yield f["name"], title, summary
            n += 1
        print(f"  [{f['name']:18}] {n} entries", file=sys.stderr)


# ----------------------------------------------------------------------------
# 집계 + 리포트
# ----------------------------------------------------------------------------
def histo(counter: Counter, maxk: int = 6) -> str:
    total = sum(counter.values()) or 1
    lines = []
    for k in range(0, maxk + 1):
        label = f"{k}+" if k == maxk else f"{k}"
        c = counter[k] if k < maxk else sum(v for kk, v in counter.items() if kk >= maxk)
        bar = "█" * round(40 * c / total)
        lines.append(f"   {label:>3}개 | {bar:<40} {c:4d}  ({100*c/total:4.1f}%)")
    return "\n".join(lines)


def run(items, KEYWORDS, ALIASES, field: str, examples: int):
    bucket_terms = build_bucket_terms(KEYWORDS, field)
    alias_map = build_alias_map(ALIASES)

    tech_surface = set().union(*[bucket_terms[b] for b in BUCKETS_TECH if b in bucket_terms])
    biz_surface = {b: bucket_terms[b] for b in BUCKETS_BIZ if b in bucket_terms}

    tech_hist = Counter()
    biz_hist = Counter()
    n_articles = 0
    n_with_tech = 0
    n_biz_ge_tech = 0
    ex_by_techcount = defaultdict(list)
    seen = set()  # 제목 중복 제거(구글뉴스 중복 방지)

    for src, title, summary in items:
        key = title.strip().lower()
        if not title or key in seen:
            continue
        seen.add(key)
        n_articles += 1
        tl = (title + " " + summary).lower()

        tech_reps = matched_reps(tl, tech_surface, alias_map)
        biz_reps = set()
        for b, surf in biz_surface.items():
            biz_reps |= matched_reps(tl, surf, alias_map)

        tc, bc = len(tech_reps), len(biz_reps)
        tech_hist[tc] += 1
        biz_hist[bc] += 1
        if tc > 0:
            n_with_tech += 1
        if bc >= tc:
            n_biz_ge_tech += 1
        if len(ex_by_techcount[tc]) < examples:
            ex_by_techcount[tc].append((tc, bc, src, title, sorted(tech_reps)))

    if n_articles == 0:
        print("\n[!] 수집된 기사가 0건. 네트워크/윈도(--days)를 확인하세요.")
        return

    mean_tech = sum(k * v for k, v in tech_hist.items()) / n_articles
    mean_biz = sum(k * v for k, v in biz_hist.items()) / n_articles
    multi_tech = sum(v for k, v in tech_hist.items() if k >= 2)

    print("\n" + "=" * 64)
    print(f"  분야: {field}   |   분석 기사 수: {n_articles}")
    print("=" * 64)

    print(f"\n[1] 기사당 tech 키워드 '종류' 개수 분포 (별칭 1회 접음)")
    print(histo(tech_hist))
    print(f"   평균 {mean_tech:.2f}개 / 기사")

    print(f"\n[2] 기사당 비즈니스(entity+product+event) 종류 개수 분포")
    print(histo(biz_hist))
    print(f"   평균 {mean_biz:.2f}개 / 기사")

    print(f"\n[3] 핵심 지표")
    print(f"   - tech 키워드가 1개라도 있는 기사 : {n_with_tech}/{n_articles} "
          f"({100*n_with_tech/n_articles:.1f}%)")
    print(f"   - tech 키워드 2개 이상인 기사     : {multi_tech}/{n_articles} "
          f"({100*multi_tech/n_articles:.1f}%)   <- stack 가능성")
    print(f"   - 비즈니스 종류 >= tech 종류 인 기사: {n_biz_ge_tech}/{n_articles} "
          f"({100*n_biz_ge_tech/n_articles:.1f}%)   <- 넓이가 깊이를 누르는 비율")
    print(f"   - 평균 비교: tech {mean_tech:.2f}  vs  biz {mean_biz:.2f}")

    if examples:
        print(f"\n[4] tech 키워드 개수별 예시 헤드라인")
        for k in sorted(ex_by_techcount):
            print(f"\n  --- tech {k}개 ---")
            for tc, bc, src, title, reps in ex_by_techcount[k]:
                hit = ", ".join(reps) if reps else "-"
                print(f"   (tech={tc}, biz={bc}) [{src}] {title[:70]}")
                print(f"        tech hits: {hit}")


# ----------------------------------------------------------------------------
# 피드별 rss_body(content:encoded) 보유율 / 길이 분포
# ----------------------------------------------------------------------------
def _dist_buckets(lengths):
    """길이 리스트를 구간별 카운트로."""
    edges = [(0, 0), (1, 300), (301, 1000), (1001, 3000), (3001, 10**9)]
    labels = ["0(없음)", "1~300", "301~1000", "1001~3000", "3000+"]
    cnt = [0] * len(edges)
    for L in lengths:
        for i, (lo, hi) in enumerate(edges):
            if lo <= L <= hi:
                cnt[i] += 1
                break
    return labels, cnt


def report_rss_body(SOURCES, field, days):
    import feedparser
    feeds = SOURCES.get(field, [])
    print("\n" + "=" * 86)
    print(f"  피드별 rss_body(content:encoded) 보유율 / 길이 분포   (field={field}, days={days})")
    print("=" * 86)
    hdr = (f"  {'feed':18}{'entries':>8}{'body有':>8}{'보유%':>7}"
           f"{'body중앙':>10}{'body평균':>10}{'body최대':>10}{'summary중앙':>12}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    all_blens = []
    for f in feeds:
        url = widen_google(f["url"], days)
        try:
            d = feedparser.parse(url)
        except Exception as e:
            print(f"  {f['name']:18} parse 실패: {e}")
            continue
        blens, slens = [], []
        for e in d.entries:
            body = extract_rss_content(e)
            summ = clean(e.get("summary", "") or e.get("description", ""))
            slens.append(len(summ))
            if body:
                blens.append(len(body))
        n = len(d.entries)
        have = len(blens)
        pct = (100 * have / n) if n else 0
        bmed = int(statistics.median(blens)) if blens else 0
        bmean = int(statistics.mean(blens)) if blens else 0
        bmax = max(blens) if blens else 0
        smed = int(statistics.median(slens)) if slens else 0
        print(f"  {f['name']:18}{n:8d}{have:8d}{pct:6.0f}%"
              f"{bmed:10d}{bmean:10d}{bmax:10d}{smed:12d}")
        all_blens += blens

    print("\n  [body 길이 분포 — 전체 피드 합산, 본문 있는 기사만]")
    if all_blens:
        labels, cnt = _dist_buckets(all_blens)
        tot = sum(cnt) or 1
        for lab, c in zip(labels, cnt):
            bar = "█" * round(40 * c / tot)
            print(f"     {lab:>9} | {bar:<40} {c:4d}  ({100*c/tot:4.1f}%)")
    else:
        print("     (본문 있는 기사 0건)")

    print("\n  해석")
    print("   - body有 0% 피드 = content:encoded 미제공 → 본문 채점 불가(구글뉴스가 여기 해당).")
    print("   - body有 높은 피드 = 본문이 이미 rss_body에 들어와 있음(지금은 채점에서 버려짐).")
    print("   - summary중앙 = 현재 채점이 실제로 보는 텍스트 길이(제목 제외, 요약만).")


# ----------------------------------------------------------------------------
# 실제 filter.score_item 으로 전체 채점 → top-N 구성 (랭킹 검증)
# ----------------------------------------------------------------------------
def run_rank(items, repo, field, topn):
    """순수 점수 순위 + 실제 score_and_filter(threshold·영문쿼터·tech쿼터) 결과를 비교 출력.
    resolve(URL 디코딩)는 생략 — 채점은 title/summary만 보므로 불필요."""
    sys.path.insert(0, os.path.abspath(repo))
    try:
        from src.filter import score_item, score_and_filter, _is_tech_led
        from config.settings import SCORE_REF, TOP_N_FOR_EXTRACT
    except Exception as e:
        print(f"[!] 실제 filter 임포트 실패: {e}\n    레포 루트에서 실행했는지 확인.")
        return

    def nrm(s):
        return round(min(10, max(0, s) / SCORE_REF * 10), 2)

    # items 구성 (dedup + rss_source/url 부여)
    seen = set()
    pool = []
    for src, title, summary in items:
        k = title.strip().lower()
        if not title or k in seen:
            continue
        seen.add(k)
        pool.append({"title": title, "summary": summary,
                     "rss_source": src, "url": f"x://{len(pool)}/{k[:24]}"})

    # (1) 순수 점수 순위 (쿼터 적용 전, 참고용)
    tmp = []
    for it in pool:
        d = score_item({"title": it["title"], "summary": it["summary"]}, field)
        b = d["buckets"]
        topb = max(b, key=b.get) if b and max(b.values()) > 0 else "-"
        tmp.append((d["score"], topb, it))
    tmp.sort(key=lambda x: -x[0])
    pure_top_urls = {t[2]["url"] for t in tmp[:TOP_N_FOR_EXTRACT]}

    print("\n" + "=" * 80)
    print(f"  (1) 순수 점수 top-{topn} — 쿼터 적용 전   field={field}")
    print("=" * 80)
    for i, (raw, topb, it) in enumerate(tmp[:topn], 1):
        mk = " ◀tech" if topb == "tech" else ""
        print(f"  {i:2}. {nrm(raw):5} (raw {raw:6}) [{topb:7}]{mk:7} {it['rss_source']:14} {it['title'][:40]}")

    # (2) 실제 score_and_filter — threshold + 영문쿼터 + tech쿼터
    sel, _ = score_and_filter(pool, field)
    print("\n" + "=" * 80)
    print(f"  (2) ★실제 추출 top-{len(sel)} — threshold + 영문쿼터 + tech쿼터 적용 (노션까지 갈 후보)")
    print("=" * 80)
    for i, it in enumerate(sel, 1):
        b = it["score_detail"]["buckets"]
        topb = max(b, key=b.get) if b and max(b.values()) > 0 else "-"
        tech_mk = "◀tech" if _is_tech_led(it) else "     "
        q_mk = "  ☆쿼터진입" if it["url"] not in pure_top_urls else ""
        print(f"  {i:2}. {nrm(it['score']):5} [{topb:7}] {tech_mk} {it['rss_source']:14} {it['title'][:36]}{q_mk}")
    techn = sum(1 for it in sel if _is_tech_led(it))
    print(f"\n  실제 추출 {len(sel)}건 중 tech 주도: {techn}/{len(sel)}   (☆=쿼터로 끌어올려진 기사)")


# ----------------------------------------------------------------------------
# 셀프테스트 (네트워크 없이 동작 확인용 샘플)
# ----------------------------------------------------------------------------
SELFTEST_ITEMS = [
    ("sample", "SK하이닉스, HBM4 엔비디아 공급 위해 양산 투자 확대", ""),
    ("sample", "삼성전자 TSMC 2나노 파운드리 수주 경쟁", ""),
    ("sample", "하이브리드 본딩으로 HBM 16단 적층 수율 개선", ""),
    ("sample", "마이크론, 1c D램 양산 돌입", ""),
    ("sample", "ASML 하이NA EUV 노광장비 출하", "high-NA EUV lithography 본격화"),
    ("sample", "삼성 갤럭시 신제품 공개", ""),  # 비반도체(negative 영역)
    ("sample", "TSMC CoWoS 첨단 패키징 증설", ""),
    ("sample", "차세대 트랜지스터 nanosheet CFET backside power 로드맵", ""),
]


def main():
    ap = argparse.ArgumentParser(description="tech 키워드 밀도 측정 (읽기 전용)")
    ap.add_argument("--repo", default=".", help="레포 루트 (config/ 가 있는 경로)")
    ap.add_argument("--field", default="반도체", help="SOURCES/KEYWORDS 분야 키")
    ap.add_argument("--days", type=int, default=1, help="구글뉴스 when:Nd 윈도(표본 확대용)")
    ap.add_argument("--examples", type=int, default=5, help="개수별 예시 헤드라인 수 (0=끔)")
    ap.add_argument("--selftest", action="store_true", help="네트워크 없이 샘플로 동작 확인")
    ap.add_argument("--bodystats", action="store_true",
                    help="피드별 rss_body 보유율/길이 분포만 출력")
    ap.add_argument("--eetimes", action="store_true",
                    help="측정에만 EE Times 피드를 임시로 추가 (config/sources.py 는 수정 안 함)")
    ap.add_argument("--rank", action="store_true",
                    help="실제 filter.score_item 으로 전체 채점→top-N 구성 출력(랭킹 검증)")
    ap.add_argument("--topn", type=int, default=15, help="--rank 출력 개수")
    args = ap.parse_args()

    kw, sources = load_config(args.repo)
    KEYWORDS = kw.KEYWORDS
    ALIASES = getattr(kw, "ALIASES", {})

    # 측정 전용 임시 추가 피드 (파일 미수정, 메모리에만 append).
    if args.eetimes and sources is not None:
        sources.SOURCES.setdefault(args.field, []).append(
            {"name": "EETimes", "url": "https://www.eetimes.com/feed/", "type": "rss"})

    if args.bodystats:
        if sources is None:
            sys.exit("[!] config/sources.py 를 못 찾음. --repo 로 레포 루트를 지정하세요.")
        print(f"[*] 피드 수집 중 (field={args.field}, days={args.days}) ...", file=sys.stderr)
        report_rss_body(sources.SOURCES, args.field, args.days)
        return

    if args.rank:
        if sources is None:
            sys.exit("[!] config/sources.py 를 못 찾음. --repo 로 레포 루트를 지정하세요.")
        print(f"[*] 피드 수집 중 (field={args.field}, days={args.days}) ...", file=sys.stderr)
        items = list(iter_entries(sources.SOURCES, args.field, args.days))
        run_rank(items, args.repo, args.field, args.topn)
        return

    if args.selftest:
        print("[selftest] 내장 샘플 8건으로 매칭 동작 확인")
        run(iter(SELFTEST_ITEMS), KEYWORDS, ALIASES, args.field, args.examples)
        return

    if sources is None:
        sys.exit("[!] config/sources.py 를 못 찾음. --selftest 로 동작만 확인하거나 경로 확인.")
    print(f"[*] 피드 수집 중 (field={args.field}, days={args.days}) ...", file=sys.stderr)
    items = list(iter_entries(sources.SOURCES, args.field, args.days))
    run(iter(items), KEYWORDS, ALIASES, args.field, args.examples)


if __name__ == "__main__":
    main()
