"""RSS/Atom feed provider (no key required).

Reads a *published* feed (e.g. Ruliweb board ``/rss``, Inven news RSS, or any
feed URL the user supplies) and returns bounded candidate metadata. Parsing is
pure; the network fetch goes through an injectable fetcher so tests stay
offline.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from shorts_pipeline.sources.base import (
    MAX_EXCERPT_LEN,
    MAX_ITEMS,
    MAX_TITLE_LEN,
    DiscoveredCandidate,
    FetchResult,
    SourceError,
    bound_text,
    strip_html,
    urllib_fetch,
)

_ATOM = "http://www.w3.org/2005/Atom"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_feed(text: str) -> list[dict[str, str | None]]:
    """Parse RSS 2.0 or Atom feed text into a list of bounded item dicts."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SourceError(f"RSS/Atom 파싱 실패: {exc}") from exc

    items: list[dict[str, str | None]] = []

    # RSS 2.0: <item> anywhere (namespace-agnostic via local name).
    for element in root.iter():
        if _local(element.tag) != "item":
            continue
        fields = {_local(child.tag): child for child in element}
        link = fields.get("link")
        items.append(
            {
                "title": (fields["title"].text if "title" in fields else None),
                "link": (link.text if link is not None else None),
                "summary": (fields["description"].text if "description" in fields else None),
                "published": (fields["pubDate"].text if "pubDate" in fields else None),
            }
        )

    # Atom: <entry> with namespaced link[@href].
    if not items:
        for entry in root.iter(f"{{{_ATOM}}}entry"):
            link_href = None
            for link in entry.findall(f"{{{_ATOM}}}link"):
                if link.get("rel", "alternate") in {"alternate", ""}:
                    link_href = link.get("href")
                    break
            items.append(
                {
                    "title": entry.findtext(f"{{{_ATOM}}}title"),
                    "link": link_href,
                    "summary": entry.findtext(f"{{{_ATOM}}}summary")
                    or entry.findtext(f"{{{_ATOM}}}content"),
                    "published": entry.findtext(f"{{{_ATOM}}}updated")
                    or entry.findtext(f"{{{_ATOM}}}published"),
                }
            )

    return items[:MAX_ITEMS]


class RssSourceProvider:
    """Turn a published RSS/Atom feed URL into bounded candidates."""

    name = "rss"

    def __init__(self, fetcher=urllib_fetch) -> None:
        self._fetcher = fetcher

    def discover(self, query: str = "") -> list[DiscoveredCandidate]:
        feed_url = (query or "").strip()
        if not feed_url:
            raise SourceError("RSS 피드 URL이 필요합니다.")
        result: FetchResult = self._fetcher(feed_url)
        if result.status_code != 200 or not result.text:
            raise SourceError(f"RSS 피드를 가져오지 못했습니다 (HTTP {result.status_code}).")

        candidates: list[DiscoveredCandidate] = []
        for item in parse_feed(result.text):
            link = (item.get("link") or "").strip()
            title = strip_html(item.get("title") or "")
            if not link or not title:
                continue
            try:
                candidates.append(
                    DiscoveredCandidate(
                        title=bound_text(title, MAX_TITLE_LEN),
                        url=link,
                        source="rss",
                        excerpt=bound_text(strip_html(item.get("summary") or ""), MAX_EXCERPT_LEN),
                        published_at=bound_text(item.get("published"), 60) or None,
                    )
                )
            except ValueError:
                # Skip items whose link is not a valid http(s) URL.
                continue
        return candidates
