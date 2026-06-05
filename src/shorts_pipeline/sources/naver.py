"""Naver official API source providers (opt-in, Client ID/Secret required).

Two providers:
- ``NaverSearchSourceProvider``: keyword -> recent news/blog/cafe items
  (the main discovery path).
- ``NaverDataLabProvider``: keyword(s) -> relative search-trend strength
  (a ranking signal turned into bounded candidates).

Both use a plain authenticated REST call via an injectable transport, so there
is no SDK import and tests stay offline. Credentials come from the environment
and are never logged or returned.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import quote

from shorts_pipeline.sources.base import (
    MAX_EXCERPT_LEN,
    MAX_TITLE_LEN,
    USER_AGENT,
    DiscoveredCandidate,
    FetchResult,
    SourceError,
    bound_text,
    strip_html,
)

NAVER_CLIENT_ID_ENV = "NAVER_CLIENT_ID"
NAVER_CLIENT_SECRET_ENV = "NAVER_CLIENT_SECRET"

_SEARCH_URL = "https://openapi.naver.com/v1/search/{kind}.json"
_DATALAB_URL = "https://openapi.naver.com/v1/datalab/search"
_SEARCH_KINDS = {"news", "blog", "cafearticle"}


def naver_credentials() -> tuple[str, str] | None:
    client_id = os.environ.get(NAVER_CLIENT_ID_ENV, "").strip()
    client_secret = os.environ.get(NAVER_CLIENT_SECRET_ENV, "").strip()
    if client_id and client_secret:
        return client_id, client_secret
    return None


def naver_enabled() -> bool:
    return naver_credentials() is not None


def urllib_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None = None,
    *,
    timeout: int = 10,
) -> FetchResult:
    """Default Naver transport (stdlib). Tests inject a fake instead."""
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read(2 * 1024 * 1024)
            charset = response.headers.get_content_charset() or "utf-8"
            return FetchResult(
                url=response.geturl(),
                status_code=getattr(response, "status", 200) or 200,
                text=raw.decode(charset, "replace"),
            )
    except urllib.error.HTTPError as exc:
        return FetchResult(url=url, status_code=exc.code, text="")
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise SourceError(f"네이버 API 요청 실패: {exc}") from exc


def _auth_headers(credentials: tuple[str, str], *, json_body: bool = False) -> dict[str, str]:
    client_id, client_secret = credentials
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
        "User-Agent": USER_AGENT,
    }
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


class NaverSearchSourceProvider:
    """Keyword -> recent Naver search items as bounded candidates."""

    name = "naver"

    def __init__(self, *, kind: str = "news", credentials=None, transport=urllib_transport) -> None:
        if kind not in _SEARCH_KINDS:
            raise ValueError(f"unsupported search kind: {kind}")
        self._kind = kind
        self._credentials = credentials
        self._transport = transport

    def discover(self, query: str = "") -> list[DiscoveredCandidate]:
        keyword = (query or "").strip()
        if not keyword:
            raise SourceError("검색어가 필요합니다.")
        credentials = self._credentials or naver_credentials()
        if credentials is None:
            raise SourceError(
                "네이버 API 키가 없습니다. NAVER_CLIENT_ID / NAVER_CLIENT_SECRET를 설정하세요."
            )
        url = _SEARCH_URL.format(kind=self._kind) + f"?query={quote(keyword)}&display=20&sort=date"
        result = self._transport("GET", url, _auth_headers(credentials))
        if result.status_code != 200 or not result.text:
            raise SourceError(f"네이버 검색 호출 실패 (HTTP {result.status_code}).")
        return _parse_search_items(result.text, source=f"naver:{self._kind}")


def _parse_search_items(payload_text: str, *, source: str) -> list[DiscoveredCandidate]:
    try:
        payload = json.loads(payload_text)
    except (ValueError, TypeError) as exc:
        raise SourceError(f"네이버 응답 파싱 실패: {exc}") from exc
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    candidates: list[DiscoveredCandidate] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = strip_html(item.get("title") or "")
        link = (item.get("link") or "").strip()
        if not title or not link:
            continue
        try:
            candidates.append(
                DiscoveredCandidate(
                    title=bound_text(title, MAX_TITLE_LEN),
                    url=link,
                    source=source,
                    excerpt=bound_text(strip_html(item.get("description") or ""), MAX_EXCERPT_LEN),
                    published_at=bound_text(item.get("pubDate"), 60) or None,
                )
            )
        except ValueError:
            continue
    return candidates


class NaverDataLabProvider:
    """Keyword(s) -> relative search-trend strength as bounded candidates.

    ``start_date`` / ``end_date`` are ISO ``YYYY-MM-DD`` strings supplied by the
    caller (the UI derives them from the injected clock), so this module stays
    clock-free and offline-testable.
    """

    name = "naver_trend"

    def __init__(self, *, start_date: str, end_date: str, credentials=None, transport=urllib_transport):
        self._start = start_date
        self._end = end_date
        self._credentials = credentials
        self._transport = transport

    def discover(self, query: str = "") -> list[DiscoveredCandidate]:
        keywords = [k.strip() for k in (query or "").split(",") if k.strip()][:5]
        if not keywords:
            raise SourceError("검색어를 1개 이상 입력하세요(쉼표로 구분).")
        credentials = self._credentials or naver_credentials()
        if credentials is None:
            raise SourceError(
                "네이버 API 키가 없습니다. NAVER_CLIENT_ID / NAVER_CLIENT_SECRET를 설정하세요."
            )
        body = json.dumps(
            {
                "startDate": self._start,
                "endDate": self._end,
                "timeUnit": "date",
                "keywordGroups": [{"groupName": k, "keywords": [k]} for k in keywords],
            }
        ).encode("utf-8")
        result = self._transport(
            "POST", _DATALAB_URL, _auth_headers(credentials, json_body=True), body
        )
        if result.status_code != 200 or not result.text:
            raise SourceError(f"네이버 데이터랩 호출 실패 (HTTP {result.status_code}).")
        return _parse_datalab(result.text)


def _parse_datalab(payload_text: str) -> list[DiscoveredCandidate]:
    try:
        payload = json.loads(payload_text)
    except (ValueError, TypeError) as exc:
        raise SourceError(f"데이터랩 응답 파싱 실패: {exc}") from exc
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []
    candidates: list[DiscoveredCandidate] = []
    for group in results:
        if not isinstance(group, dict):
            continue
        keyword = group.get("title")
        data = group.get("data")
        if not isinstance(keyword, str) or not keyword or not isinstance(data, list) or not data:
            continue
        last = data[-1] if isinstance(data[-1], dict) else {}
        ratio = last.get("ratio")
        try:
            score = int(round(float(ratio))) if ratio is not None else None
        except (ValueError, TypeError):
            score = None
        candidates.append(
            DiscoveredCandidate(
                title=bound_text(keyword, MAX_TITLE_LEN),
                url=f"https://search.naver.com/search.naver?query={quote(keyword)}",
                source="naver_trend",
                score=score,
                excerpt="검색어 트렌드 상대 지수(최근값)",
            )
        )
    return candidates
