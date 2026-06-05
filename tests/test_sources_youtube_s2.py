"""S2 offline tests for the YouTube Data API source provider.

No network: a fake fetcher returns a fixed API JSON payload. Verifies KR
most-popular URL building, normalization, the opt-in key gate, transient
retry, and that the API key never leaks into candidate output.
"""

from __future__ import annotations

import json

import pytest

from shorts_pipeline.sources.base import FetchResult, SourceError
from shorts_pipeline.sources.youtube import (
    YouTubeSourceProvider,
    build_request_url,
    youtube_enabled,
)

_YT_PAYLOAD = json.dumps(
    {
        "items": [
            {
                "id": "abc123",
                "snippet": {"title": "인기 영상 1", "channelTitle": "채널A"},
                "statistics": {"viewCount": "15000"},
            },
            {
                "id": "def456",
                "snippet": {"title": "인기 영상 2", "channelTitle": "채널B"},
                "statistics": {"viewCount": "not-a-number"},
            },
            {"id": "noTitle", "snippet": {}, "statistics": {}},  # skipped: no title
        ]
    }
)


def _ok_fetcher(text: str):
    return lambda url: FetchResult(url=url, status_code=200, text=text)


def test_build_url_targets_kr_most_popular() -> None:
    url = build_request_url("KEY", region_code="KR")
    assert "chart=mostPopular" in url
    assert "regionCode=KR" in url
    assert "part=snippet%2Cstatistics" in url


def test_youtube_normalizes_and_skips_bad_items() -> None:
    provider = YouTubeSourceProvider(api_key="fake-key", fetcher=_ok_fetcher(_YT_PAYLOAD))
    items = provider.discover()
    assert [c.title for c in items] == ["인기 영상 1", "인기 영상 2"]  # no-title item skipped
    assert items[0].url == "https://www.youtube.com/watch?v=abc123"
    assert items[0].score == 15000
    assert items[1].score is None  # unparseable viewCount -> None, not a crash
    assert all(c.source == "youtube" for c in items)


def test_youtube_requires_key(monkeypatch) -> None:
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    provider = YouTubeSourceProvider(fetcher=_ok_fetcher(_YT_PAYLOAD))
    with pytest.raises(SourceError):
        provider.discover()


def test_youtube_enabled_reflects_env(monkeypatch) -> None:
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    assert youtube_enabled() is False
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    assert youtube_enabled() is True


def test_youtube_retries_transient_then_succeeds() -> None:
    calls = {"n": 0}

    def flaky(url: str) -> FetchResult:
        calls["n"] += 1
        if calls["n"] == 1:
            return FetchResult(url=url, status_code=503, text="")
        return FetchResult(url=url, status_code=200, text=_YT_PAYLOAD)

    provider = YouTubeSourceProvider(api_key="fake-key", fetcher=flaky)
    items = provider.discover()
    assert calls["n"] == 2
    assert len(items) == 2


def test_youtube_key_never_leaks_into_output() -> None:
    provider = YouTubeSourceProvider(api_key="SECRET-KEY-XYZ", fetcher=_ok_fetcher(_YT_PAYLOAD))
    items = provider.discover()
    assert "SECRET-KEY-XYZ" not in repr([c.model_dump() for c in items])
