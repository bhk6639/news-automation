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
        # 나중에 매체 RSS 추가 가능
    ],
}