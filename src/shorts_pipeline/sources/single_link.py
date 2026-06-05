"""Single user-pasted link provider (one polite, robots-respecting fetch).

This is the lawful fill-in for sites without an official API or feed: the user
pastes ONE public page URL and we fetch it exactly once, after checking
robots.txt. We never bypass a login/CAPTCHA/Cloudflare wall, never rotate
agents, and never crawl beyond that single URL. Only a title and a short
excerpt are kept.
"""

from __future__ import annotations

import re
import urllib.robotparser
from urllib.parse import urljoin, urlparse

from shorts_pipeline.sources.base import (
    MAX_EXCERPT_LEN,
    MAX_TITLE_LEN,
    USER_AGENT,
    DiscoveredCandidate,
    SourceError,
    bound_text,
    strip_html,
    urllib_fetch,
)

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_RE = re.compile(
    r"""<meta[^>]+(?:name|property)=["'](?:description|og:description)["']"""
    r"""[^>]+content=["'](.*?)["']""",
    re.IGNORECASE | re.DOTALL,
)


def extract_title(html_text: str) -> str:
    match = _TITLE_RE.search(html_text or "")
    return strip_html(match.group(1)) if match else ""


def extract_excerpt(html_text: str) -> str:
    match = _META_RE.search(html_text or "")
    if match:
        return strip_html(match.group(1))
    return ""


class RobotsChecker:
    """Checks robots.txt before a single fetch (fail-closed on restriction)."""

    def __init__(self, fetcher=urllib_fetch) -> None:
        self._fetcher = fetcher

    def allowed(self, url: str, user_agent: str = USER_AGENT) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        robots_url = urljoin(f"{parsed.scheme}://{parsed.netloc}", "/robots.txt")
        try:
            result = self._fetcher(robots_url)
        except SourceError:
            return False  # cannot verify -> do not fetch
        if result.status_code == 404:
            return True  # no robots.txt published -> allowed
        if result.status_code != 200 or not result.text:
            return False  # restricted/unavailable -> conservative deny
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(result.text.splitlines())
        return parser.can_fetch(user_agent, url)


class SingleLinkFetchProvider:
    """Fetch ONE user-supplied public URL, once, respecting robots.txt."""

    name = "link"

    def __init__(self, fetcher=urllib_fetch, robots_checker: RobotsChecker | None = None) -> None:
        self._fetcher = fetcher
        self._robots = robots_checker if robots_checker is not None else RobotsChecker(fetcher)

    def discover(self, query: str = "") -> list[DiscoveredCandidate]:
        url = (query or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise SourceError("http(s) 링크를 입력하세요.")
        if not self._robots.allowed(url):
            raise SourceError("robots.txt가 자동 접근을 허용하지 않습니다. 우회하지 않습니다.")

        result = self._fetcher(url)
        if result.status_code in {401, 403}:
            raise SourceError(
                "페이지가 접근을 차단했습니다(로그인/Cloudflare 등). 우회하지 않습니다."
            )
        if result.status_code != 200 or not result.text:
            raise SourceError(f"페이지를 가져오지 못했습니다 (HTTP {result.status_code}).")

        title = extract_title(result.text) or url
        return [
            DiscoveredCandidate(
                title=bound_text(title, MAX_TITLE_LEN),
                url=result.url or url,
                source="link",
                excerpt=bound_text(extract_excerpt(result.text), MAX_EXCERPT_LEN),
            )
        ]
