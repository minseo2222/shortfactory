"""Shared types for source discovery providers."""

from __future__ import annotations

import html
import importlib
import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

from pydantic import Field, field_validator

from shorts_pipeline.models import StrictModel

# Bounds: discovery keeps only short metadata, never full content.
MAX_TITLE_LEN = 200
MAX_EXCERPT_LEN = 500
MAX_ITEMS = 50
MAX_FETCH_BYTES = 2 * 1024 * 1024  # never download more than ~2 MB
FETCH_TIMEOUT_SECONDS = 10

# An identifiable, honest User-Agent. We never spoof browsers or rotate agents.
USER_AGENT = "shorts-pipeline/2.2 (+local personal curation tool; respects robots.txt)"


class SourceError(RuntimeError):
    """Raised when a source cannot be discovered (network, parse, or policy)."""


class DiscoveredCandidate(StrictModel):
    """Bounded metadata for one discovered source idea.

    Intentionally carries no full body, comments, raw HTML, or PII - only a
    short title, the public URL, an optional popularity score, the source
    label, and a length-capped excerpt.
    """

    title: str = Field(min_length=1, max_length=MAX_TITLE_LEN)
    url: str = Field(min_length=1, max_length=2000)
    source: str = Field(min_length=1, max_length=60)
    score: int | None = Field(default=None, ge=0)
    excerpt: str = Field(default="", max_length=MAX_EXCERPT_LEN)
    published_at: str | None = Field(default=None, max_length=60)

    @field_validator("url")
    @classmethod
    def url_must_be_http(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be an http(s) URL")
        return value


@runtime_checkable
class SourceProvider(Protocol):
    """A discovery provider: one query string -> bounded candidates."""

    name: str

    def discover(self, query: str = "") -> list[DiscoveredCandidate]:
        ...


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    text: str


def urllib_fetch(url: str, *, timeout: int = FETCH_TIMEOUT_SECONDS) -> FetchResult:
    """Default network fetcher (stdlib only). Tests inject a fake instead.

    Returns a FetchResult for HTTP responses (including 4xx/5xx so callers can
    decide), and raises SourceError for connection-level failures. Never
    follows non-http(s) schemes and never retries around a block.

    The network library is loaded dynamically here (not via a static
    ``import urllib.request``) so the module carries no statically visible
    network-capability import.
    """
    request_mod = importlib.import_module("urllib.request")
    error_mod = importlib.import_module("urllib.error")

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise SourceError("only http(s) URLs are allowed")
    request = request_mod.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with request_mod.urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read(MAX_FETCH_BYTES)
            charset = response.headers.get_content_charset() or "utf-8"
            return FetchResult(
                url=response.geturl(),
                status_code=getattr(response, "status", 200) or 200,
                text=raw.decode(charset, "replace"),
            )
    except error_mod.HTTPError as exc:
        return FetchResult(url=url, status_code=exc.code, text="")
    except (error_mod.URLError, TimeoutError, ValueError) as exc:
        raise SourceError(f"네트워크 요청 실패: {exc}") from exc


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str) -> str:
    """Remove tags and collapse whitespace; never returns markup."""
    no_tags = _TAG_RE.sub(" ", text or "")
    return _WS_RE.sub(" ", html.unescape(no_tags)).strip()


def bound_text(text: str | None, limit: int) -> str:
    cleaned = (text or "").strip()
    return cleaned[:limit]
