"""
분야별 RSS 소스 리스트.
"""

from urllib.parse import quote


def google_news_rss(query: str, lang: str = "ko", country: str = "KR") -> str:
    """Google News RSS 검색 URL 생성. when:1d = 최근 24시간.
    lang/country로 언어판 선택 (기본 한국어판, 영문은 en/US)."""
    q = quote(f"{query} when:1d")
    return (
        f"https://news.google.com/rss/search?q={q}"
        f"&hl={lang}&gl={country}&ceid={country}:{lang}"
    )


SOURCES = {
    "반도체": [
        {
            "name": "GoogleNews_반도체",
            "url": google_news_rss("반도체 OR HBM OR 파운드리 OR 메모리반도체"),
            "type": "google_news",
        },
        {
            # 영문 속보 (when:1d라 신선, source 자동 부여). 죽은 직접피드 대안.
            "name": "GoogleNews_EN",
            "url": google_news_rss(
                "semiconductor OR HBM OR DRAM OR foundry OR TSMC OR memory chip",
                lang="en", country="US",
            ),
            "type": "google_news",
        },
        # 자체 RSS 직접 구독 (구글 인덱싱 의존 없이 누락/지연 방지).
        # collect.py가 feedparser로 범용 파싱하므로 type은 표시용.
        # resolve.py는 news.google.com이 아닌 URL은 그대로 통과시킴.
        {
            # 해외/제조·계측·수율 심층 (영문). 기사 재크롤링으로 본문 추출.
            "name": "SemiEngineering",
            "url": "https://semiengineering.com/feed/",
            "type": "rss",
        },
        {
            # 해외/메모리·스토리지 전문 (영문). HBM/DRAM/NAND/CXL 집중.
            # ⚠ 추가 전 freshness 확인:
            #   python -c "import feedparser as f; d=f.parse('https://blocksandfiles.com/feed/'); print(len(d.entries)); [print(e.get('published'),e.title[:50]) for e in d.entries[:5]]"
            "name": "BlocksAndFiles",
            "url": "https://blocksandfiles.com/feed/",
            "type": "rss",
        },
        # KEDGlobal 제거 — S1N1 섹션이 저빈도/스테일(최신 6/08, 3월까지 소급)이라
        # 일간/주간 어느 윈도로도 못 건짐. 활성 섹션코드 찾으면 부활. 영문은 GoogleNews_EN+B&F가 커버.
        {
            # 국내 반도체 섹션 전용 피드 (디스플레이/배터리 등 비반도체 유입 차단).
            "name": "THELEC_반도체",
            "url": "https://www.thelec.kr/rss/S1N2.xml",
            "type": "rss",
        },
        {
            # 국내 소부장 전문. 반도체가 프리미엄(유료)/뉴스룸/아시아로 분산돼 있어
            # 전체 피드를 받아 키워드 점수로 거름. 유료 프리미엄 기사는 본문 추출
            # 실패(MIN_BODY 미달)로 자연 탈락.
            "name": "KIPOST",
            "url": "https://www.kipost.net/rss/allArticle.xml",
            "type": "rss",
        },
        {
            # 해외/소자·EDA·공정 (영문). 기술 비중 보강용 (6/25 추가).
            # content:encoded 본문 제공하나 발췌형(중앙 ~200자, 최대 ~1100자) — SemiEng처럼 풀본문은 아님.
            # 헤드라인에 EUV/lithography 등 tech 용어가 박혀 점수에 유리. 볼륨 작음(~10건).
            # 영문이라 settings.ENGLISH_FEEDS에도 등록해야 쿼터·truncate(1000) 처리됨.
            "name": "EETimes",
            "url": "https://www.eetimes.com/feed/",
            "type": "rss",
        },
        # TrendForce 제거 — news RSS(/feed, /feed_v2 둘 다)가 2026-04-16에 멈춤(죽은 피드).
        # 영문 메모리 뉴스는 GoogleNews_EN + BlocksAndFiles로 대체.
    ],
}
