"""S3 offline tests for the Naver source providers (search + DataLab).

No network: a fake transport returns fixed JSON and records the request so the
auth-header gate, normalization, POST body, and no-credential-leak guarantees
are all verified offline.
"""

from __future__ import annotations

import json

import pytest

from shorts_pipeline.sources.base import FetchResult, SourceError
from shorts_pipeline.sources.naver import (
    NaverDataLabProvider,
    NaverSearchSourceProvider,
    naver_enabled,
)

_SEARCH_JSON = json.dumps(
    {
        "items": [
            {
                "title": "오늘의 <b>화제</b> 뉴스",
                "link": "https://n.news.naver.com/article/1",
                "description": "요약 <b>본문</b> 일부",
                "pubDate": "Thu, 04 Jun 2026 09:00:00 +0900",
            },
            {"title": "", "link": "https://x/2", "description": "no title -> skip"},
        ]
    }
)

_DATALAB_JSON = json.dumps(
    {
        "results": [
            {"title": "키워드A", "data": [{"period": "2026-06-01", "ratio": 12.3},
                                          {"period": "2026-06-04", "ratio": 87.6}]},
            {"title": "키워드B", "data": []},  # no data -> skip
        ]
    }
)


class FakeTransport:
    def __init__(self, response_text: str, status: int = 200) -> None:
        self.response_text = response_text
        self.status = status
        self.calls: list[dict] = []

    def __call__(self, method, url, headers, body=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        return FetchResult(url=url, status_code=self.status, text=self.response_text)


_CREDS = ("client-id", "client-secret")


def test_naver_search_normalizes_and_strips_html() -> None:
    transport = FakeTransport(_SEARCH_JSON)
    provider = NaverSearchSourceProvider(credentials=_CREDS, transport=transport)
    items = provider.discover("숏폼 아이디어")
    assert len(items) == 1  # empty-title item skipped
    assert items[0].title == "오늘의 화제 뉴스" and "<b>" not in items[0].title
    assert items[0].url.endswith("/article/1")
    assert items[0].source == "naver:news"
    # Auth headers were sent; query was URL-encoded.
    sent = transport.calls[0]
    assert sent["headers"]["X-Naver-Client-Id"] == "client-id"
    assert "query=" in sent["url"]


def test_naver_search_requires_credentials(monkeypatch) -> None:
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    provider = NaverSearchSourceProvider(transport=FakeTransport(_SEARCH_JSON))
    with pytest.raises(SourceError):
        provider.discover("숏폼")


def test_naver_search_requires_query() -> None:
    provider = NaverSearchSourceProvider(credentials=_CREDS, transport=FakeTransport(_SEARCH_JSON))
    with pytest.raises(SourceError):
        provider.discover("")


def test_naver_enabled_reflects_env(monkeypatch) -> None:
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    assert naver_enabled() is False
    monkeypatch.setenv("NAVER_CLIENT_ID", "i")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "s")
    assert naver_enabled() is True


def test_datalab_turns_keywords_into_scored_candidates() -> None:
    transport = FakeTransport(_DATALAB_JSON)
    provider = NaverDataLabProvider(
        start_date="2026-05-05", end_date="2026-06-04", credentials=_CREDS, transport=transport
    )
    items = provider.discover("키워드A, 키워드B")
    assert len(items) == 1  # keyword B (no data) skipped
    assert items[0].title == "키워드A"
    assert items[0].score == 88  # latest ratio 87.6 rounded
    assert items[0].source == "naver_trend"
    # POST body carries the date window and keyword groups.
    body = json.loads(transport.calls[0]["body"])
    assert body["startDate"] == "2026-05-05" and body["timeUnit"] == "date"
    assert transport.calls[0]["method"] == "POST"


def test_naver_credentials_never_leak_into_output() -> None:
    transport = FakeTransport(_SEARCH_JSON)
    provider = NaverSearchSourceProvider(
        credentials=("ID-SECRETZ", "PW-SECRETZ"), transport=transport
    )
    items = provider.discover("k")
    assert "SECRETZ" not in repr([c.model_dump() for c in items])
