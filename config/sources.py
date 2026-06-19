"""
분야별 RSS 소스 리스트.
"""

from urllib.parse import quote


def google_news_rss(query: str) -> str:
    """Google News RSS 검색 URL 생성. when:1d = 최근 24시간."""
    q = quote(f"{query} when:1d")
    return f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"


SOURCES = {
    "반도체": [
        {
            "name": "GoogleNews_반도체",
            "url": google_news_rss("반도체 OR HBM OR 파운드리 OR 메모리반도체"),
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
            # 국내 반도체 섹션 전용 피드 (디스플레이/배터리 등 비반도체 유입 차단).
            "name": "THELEC_반도체",
            "url": "https://www.thelec.kr/rss/S1N2.xml",
            "type": "rss",
        },
        {
            # 해외/메모리 시장·HBM·DRAM (영문). 이 피드는 본문 전체를 직접 제공하나
            # 파이프라인 일관성을 위해 기사 URL 재크롤링 경로를 그대로 사용.
            "name": "TrendForce",
            "url": "https://www.trendforce.com/news/feed/",
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
    ],
}