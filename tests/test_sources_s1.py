"""S1 offline tests for source discovery (RSS + single-link fetch).

No network: a fake fetcher serves fixed strings so robots.txt handling, parsing,
bounds, and no-bypass behavior are all verified deterministically.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shorts_pipeline.sources import (
    DiscoveredCandidate,
    RobotsChecker,
    RssSourceProvider,
    SingleLinkFetchProvider,
    SourceError,
)
from shorts_pipeline.sources.base import FetchResult

RSS_2_0 = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Ruliweb</title>
<item><title>테스트 글 1</title>
<link>https://bbs.ruliweb.com/community/board/300143/read/1</link>
<description>요약 &lt;b&gt;본문&lt;/b&gt; 일부</description>
<pubDate>Wed, 04 Jun 2026 09:00:00 +0900</pubDate></item>
<item><title>테스트 글 2</title>
<link>https://bbs.ruliweb.com/community/board/300143/read/2</link>
<description>두번째 요약</description></item>
<item><title>나쁜 링크</title><link>ftp://example/1</link><description>스킵됨</description></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<title>Feed</title>
<entry><title>아톰 글</title>
<link rel="alternate" href="https://example.com/a"/>
<summary>아톰 요약</summary>
<updated>2026-06-04T09:00:00Z</updated></entry>
</feed>"""

PAGE_HTML = (
    "<html><head><title>페이지 제목</title>"
    "<meta name='description' content='메타 설명 발췌'></head>"
    "<body><p>본문 텍스트</p></body></html>"
)


def fetch_returning(status: int, text: str):
    return lambda url: FetchResult(url=url, status_code=status, text=text)


# --- DiscoveredCandidate model ---------------------------------------------


def test_candidate_rejects_non_http_url() -> None:
    with pytest.raises(ValidationError):
        DiscoveredCandidate(title="t", url="ftp://x/1", source="rss")


def test_candidate_excerpt_is_length_bounded() -> None:
    with pytest.raises(ValidationError):
        DiscoveredCandidate(title="t", url="https://x/1", source="rss", excerpt="x" * 501)


# --- RSS / Atom -------------------------------------------------------------


def test_rss_parses_and_skips_non_http_links() -> None:
    provider = RssSourceProvider(fetcher=fetch_returning(200, RSS_2_0))
    items = provider.discover("https://bbs.ruliweb.com/community/board/300143/rss")
    assert [c.title for c in items] == ["테스트 글 1", "테스트 글 2"]  # ftp item skipped
    assert items[0].url.endswith("/read/1")
    assert "본문" in items[0].excerpt and "<b>" not in items[0].excerpt  # html stripped
    assert items[0].source == "rss"


def test_atom_feed_parses() -> None:
    provider = RssSourceProvider(fetcher=fetch_returning(200, ATOM))
    items = provider.discover("https://example.com/feed")
    assert len(items) == 1
    assert items[0].title == "아톰 글" and items[0].url == "https://example.com/a"


def test_rss_non_200_raises() -> None:
    provider = RssSourceProvider(fetcher=fetch_returning(403, ""))
    with pytest.raises(SourceError):
        provider.discover("https://example.com/feed")


def test_rss_requires_feed_url() -> None:
    provider = RssSourceProvider(fetcher=fetch_returning(200, RSS_2_0))
    with pytest.raises(SourceError):
        provider.discover("")


# --- Single-link fetch ------------------------------------------------------


def _single_link_fetcher(robots_body: str, robots_status: int, page_status: int, page_text: str):
    def _fetch(url: str) -> FetchResult:
        if url.endswith("/robots.txt"):
            return FetchResult(url=url, status_code=robots_status, text=robots_body)
        return FetchResult(url=url, status_code=page_status, text=page_text)

    return _fetch


def test_single_link_allowed_returns_title_and_excerpt() -> None:
    fetcher = _single_link_fetcher("User-agent: *\nAllow: /", 200, 200, PAGE_HTML)
    provider = SingleLinkFetchProvider(fetcher=fetcher)
    items = provider.discover("https://example.com/post/1")
    assert len(items) == 1
    assert items[0].title == "페이지 제목"
    assert items[0].excerpt == "메타 설명 발췌"
    assert items[0].source == "link"


def test_single_link_respects_robots_disallow() -> None:
    fetcher = _single_link_fetcher("User-agent: *\nDisallow: /", 200, 200, PAGE_HTML)
    provider = SingleLinkFetchProvider(fetcher=fetcher)
    with pytest.raises(SourceError):
        provider.discover("https://example.com/post/1")


def test_single_link_does_not_bypass_block() -> None:
    # A 403 (login/Cloudflare wall) must fail, never be worked around.
    fetcher = _single_link_fetcher("User-agent: *\nAllow: /", 200, 403, "")
    provider = SingleLinkFetchProvider(fetcher=fetcher)
    with pytest.raises(SourceError):
        provider.discover("https://example.com/post/1")


def test_single_link_rejects_non_http() -> None:
    provider = SingleLinkFetchProvider(fetcher=fetch_returning(200, PAGE_HTML))
    with pytest.raises(SourceError):
        provider.discover("ftp://example.com/x")


def test_robots_checker_denies_when_robots_unavailable() -> None:
    # robots.txt returns 500 -> conservative deny (do not fetch).
    checker = RobotsChecker(fetcher=fetch_returning(500, ""))
    assert checker.allowed("https://example.com/post/1") is False
