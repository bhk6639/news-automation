"""
RSS 수집 모듈.
config/sources.py의 SOURCES에서 분야별 RSS를 읽어와 entry 리스트 반환.
"""

import feedparser
from datetime import datetime, timezone
from config.sources import SOURCES


def parse_published(entry) -> datetime | None:
    """RSS entry의 발행일을 datetime으로 변환."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    return None


def collect_field(field: str) -> list[dict]:
    """
    분야별 RSS 수집.
    return: [{title, link, published(datetime), summary, source_name, rss_source}, ...]
    """
    if field not in SOURCES:
        raise ValueError(f"Unknown field: {field}")

    results = []
    for src in SOURCES[field]:
        feed = feedparser.parse(src["url"])
        for entry in feed.entries:
            results.append({
                "title": entry.get("title", "").strip(),
                "link": entry.get("link", "").strip(),
                "published": parse_published(entry),
                "summary": entry.get("summary", "").strip(),
                "source_name": entry.get("source", {}).get("title", "")
                               if hasattr(entry, "source") else "",
                "rss_source": src["name"],
            })
    return results


if __name__ == "__main__":
    # 단독 실행 테스트
    items = collect_field("반도체")
    print(f"총 {len(items)}건 수집")
    print("---")
    for i, item in enumerate(items[:5]):
        print(f"[{i+1}] {item['title']}")
        print(f"    source: {item['source_name']}")
        print(f"    published: {item['published']}")
        print(f"    link: {item['link'][:80]}...")
        print()