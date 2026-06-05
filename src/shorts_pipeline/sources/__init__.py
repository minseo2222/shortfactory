"""Opt-in source discovery providers (legal, no-bypass).

Each provider turns one allowed input (an official-API result, a published RSS
feed, or a single user-pasted public URL) into bounded ``DiscoveredCandidate``
metadata. No mass/automatic crawling, no login/CAPTCHA/rate-limit bypass, and
only title/url/score/source/excerpt is ever retained - never full bodies,
comments, raw HTML, screenshots, or PII.
"""

from shorts_pipeline.sources.base import (
    DiscoveredCandidate,
    FetchResult,
    SourceError,
    SourceProvider,
)
from shorts_pipeline.sources.rss import RssSourceProvider
from shorts_pipeline.sources.single_link import RobotsChecker, SingleLinkFetchProvider
from shorts_pipeline.sources.youtube import YouTubeSourceProvider, youtube_enabled

__all__ = [
    "DiscoveredCandidate",
    "FetchResult",
    "SourceError",
    "SourceProvider",
    "RssSourceProvider",
    "SingleLinkFetchProvider",
    "RobotsChecker",
    "YouTubeSourceProvider",
    "youtube_enabled",
]
