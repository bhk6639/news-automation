"""
Google News RSS 리다이렉트 링크를 실제 언론사 URL로 변환.
"""

from googlenewsdecoder import gnewsdecoder
from urllib.parse import urlparse

from config.settings import BLOCKED_HOSTS


def _is_blocked_host(url: str) -> bool:
    """아그리게이터/JS렌더로 본문이 늘 비는 호스트인지 (BLOCKED_HOSTS)."""
    host = urlparse(url).netloc.lower()
    return any(host == b or host.endswith("." + b) for b in BLOCKED_HOSTS)


def resolve_url(url: str) -> str | None:
    """Google News 링크를 디코딩해서 최종 URL 반환. 실패하면 None."""
    if not url:
        return None

    if "news.google.com" not in url:
        return None if _is_blocked_host(url) else url

    try:
        decoded = gnewsdecoder(url, interval=1)
        if decoded.get("status"):
            final_url = decoded["decoded_url"]
            if "google.com" in urlparse(final_url).netloc:
                return None
            if _is_blocked_host(final_url):
                return None
            return final_url
        return None
    except Exception as e:
        print(f"  resolve 실패: {e}")
        return None


def resolve_items(items: list[dict]) -> list[dict]:
    resolved = []
    for i, item in enumerate(items):
        final = resolve_url(item["link"])
        if final:
            item["url"] = final
            item["original_link"] = item["link"]
            resolved.append(item)
        if (i + 1) % 20 == 0:
            print(f"  resolve 진행: {i+1}/{len(items)} (성공 {len(resolved)})")
    return resolved


if __name__ == "__main__":
    from src.collect import collect_field

    items = collect_field("반도체")
    print(f"수집: {len(items)}건")
    print("resolve 시작...")
    resolved = resolve_items(items)
    print(f"resolve 성공: {len(resolved)}건")
    print("---")
    for item in resolved[:5]:
        print(f"제목: {item['title']}")
        print(f"  최종 URL: {item['url'][:100]}")
        print()