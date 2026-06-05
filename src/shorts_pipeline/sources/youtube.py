"""YouTube Data API source provider (opt-in, official, key required).

Uses the official ``videos.list?chart=mostPopular&regionCode=KR`` endpoint to
list Korea's currently popular videos (Shorts included) as bounded candidate
metadata. The call is a plain REST GET via the injectable fetcher, so there is
no SDK import and tests stay fully offline. The API key is read from the
environment and never logged or returned.
"""

from __future__ import annotations

import json
import os

from shorts_pipeline.sources.base import (
    MAX_TITLE_LEN,
    DiscoveredCandidate,
    FetchResult,
    SourceError,
    bound_text,
    urllib_fetch,
)

YOUTUBE_API_KEY_ENV = "YOUTUBE_API_KEY"
_API_URL = "https://www.googleapis.com/youtube/v3/videos"
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}
_MAX_RESULTS = 25


def youtube_api_key() -> str | None:
    value = os.environ.get(YOUTUBE_API_KEY_ENV, "").strip()
    return value or None


def youtube_enabled() -> bool:
    return youtube_api_key() is not None


def build_request_url(api_key: str, *, region_code: str = "KR", max_results: int = _MAX_RESULTS) -> str:
    from urllib.parse import urlencode

    params = urlencode(
        {
            "part": "snippet,statistics",
            "chart": "mostPopular",
            "regionCode": region_code,
            "maxResults": max_results,
            "key": api_key,
        }
    )
    return f"{_API_URL}?{params}"


def _fetch_with_retry(fetcher, url: str, *, attempts: int = 2) -> FetchResult:
    last: FetchResult | None = None
    for _ in range(attempts):
        result = fetcher(url)
        if result.status_code not in _TRANSIENT_STATUS:
            return result
        last = result
    return last if last is not None else fetcher(url)


def parse_videos(payload_text: str) -> list[dict[str, object]]:
    try:
        payload = json.loads(payload_text)
    except (ValueError, TypeError) as exc:
        raise SourceError(f"YouTube 응답 파싱 실패: {exc}") from exc
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    parsed: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        snippet = item.get("snippet") or {}
        stats = item.get("statistics") or {}
        video_id = item.get("id")
        title = snippet.get("title")
        if not isinstance(video_id, str) or not isinstance(title, str) or not title:
            continue
        view_count = stats.get("viewCount")
        try:
            score = int(view_count) if view_count is not None else None
        except (ValueError, TypeError):
            score = None
        parsed.append(
            {
                "video_id": video_id,
                "title": title,
                "channel": snippet.get("channelTitle") or "",
                "score": score,
            }
        )
    return parsed


class YouTubeSourceProvider:
    """List KR most-popular videos as candidates (opt-in via API key)."""

    name = "youtube"

    def __init__(self, *, api_key: str | None = None, fetcher=urllib_fetch) -> None:
        self._api_key = api_key
        self._fetcher = fetcher

    def discover(self, query: str = "") -> list[DiscoveredCandidate]:
        api_key = self._api_key or youtube_api_key()
        if not api_key:
            raise SourceError(
                "YouTube API 키가 없습니다. 환경변수 YOUTUBE_API_KEY를 설정하세요."
            )
        region = (query or "KR").strip() or "KR"
        url = build_request_url(api_key, region_code=region)
        result = _fetch_with_retry(self._fetcher, url)
        if result.status_code != 200 or not result.text:
            raise SourceError(f"YouTube API 호출 실패 (HTTP {result.status_code}).")

        candidates: list[DiscoveredCandidate] = []
        for video in parse_videos(result.text):
            channel = video["channel"]
            candidates.append(
                DiscoveredCandidate(
                    title=bound_text(str(video["title"]), MAX_TITLE_LEN),
                    url=f"https://www.youtube.com/watch?v={video['video_id']}",
                    source="youtube",
                    score=video["score"],  # type: ignore[arg-type]
                    excerpt=bound_text(f"채널: {channel}" if channel else "", 500),
                )
            )
        return candidates
