"""
RSS 수집 모듈.
config/sources.py의 SOURCES에서 분야별 RSS를 읽어와 entry 리스트 반환.
"""

import re
import html
import feedparser
from datetime import datetime, timezone
from config.sources import SOURCES


def parse_published(entry) -> datetime | None:
    """RSS entry의 발행일을 datetime으로 변환."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    return None


def clean_summary(text: str) -> str:
    """HTML 태그 + 엔티티 + 연속 공백 제거."""
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


def html_to_text(html_str: str) -> str:
    """RSS content:encoded(HTML)를 문단 보존하며 평문으로. 본문 후보용."""
    if not html_str:
        return ""
    # 블록 종료 태그를 줄바꿈으로 치환해 문단 구조 유지
    text = re.sub(r'(?i)</p>|<br\s*/?>|</div>|</li>|</h[1-6]>', '\n', html_str)
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n\n', text)
    return text.strip()


def extract_rss_content(entry) -> str:
    """RSS 항목이 본문 전체(content:encoded)를 주면 평문으로 반환. 없으면 ''."""
    if entry.get("content"):
        return html_to_text(entry["content"][0].get("value", ""))
    return ""


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
                "summary": clean_summary(entry.get("summary", "")),
                "rss_body": extract_rss_content(entry),  # 본문 전체 제공 피드용 (없으면 '')
                "source_name": entry.get("source", {}).get("title", "")
                               if hasattr(entry, "source") else "",
                "rss_source": src["name"],
            })
    return results


if __name__ == "__main__":
    items = collect_field("반도체")
    print(f"총 {len(items)}건 수집")
    print("---")
    for i, item in enumerate(items[:5]):
        print(f"[{i+1}] {item['title']}")
        print(f"    source: {item['source_name']}")
        print(f"    published: {item['published']}")
        print(f"    summary: {item['summary'][:80]}")
        print()