"""Conservative source-availability checks for bookmarks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

import requests

from src.routing import RouteDecision, RouteOutcome, TextEvidence


class SourceHealthStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class SourceHealthResult:
    status: SourceHealthStatus
    source: str
    reason: str
    http_status: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def unavailable_source_decision(
    bookmark: dict[str, Any],
    health: SourceHealthResult,
) -> RouteDecision:
    """Build the shared terminal routing decision for an inaccessible source."""
    return RouteDecision(
        bookmark_id=int(bookmark["_id"]),
        outcome=RouteOutcome.ERROR,
        destination=None,
        text_evidence=(TextEvidence(
            kind="source_unavailable",
            destination=None,
            strength=None,
            matched_value=str(bookmark.get("link") or ""),
            source=health.source,
            explanation=health.reason,
        ),),
        visual_evidence=(),
        summary="Source is permanently inaccessible; ignore this Raindrop.",
    )


def twitter_status_url(value: str | None) -> str | None:
    """Return an X/Twitter status URL, excluding unrelated profile/pages."""
    if not value:
        return None
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    host = (parsed.hostname or "").casefold()
    if host not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 3 or parts[1].casefold() != "status" or not parts[2].isdigit():
        return None
    return value


def twitter_source_needs_check(bookmark: dict[str, Any]) -> bool:
    """Limit network probes to statuses whose Raindrop metadata is missing."""
    link = twitter_status_url(str(bookmark.get("link") or ""))
    if link is None:
        return False
    title = str(bookmark.get("title") or "").strip()
    return not title or title == link or title.casefold() in {"x", "twitter"}


class TwitterSourceHealthChecker:
    """Ask Twitter's public embed endpoint whether a status remains accessible."""

    endpoint = "https://publish.twitter.com/oembed"
    terminal_statuses = frozenset({401, 403, 404, 410})

    def __init__(
        self,
        *,
        get: Callable[..., Any] = requests.get,
        timeout: float = 8.0,
    ):
        self.get = get
        self.timeout = timeout

    def check(self, bookmark: dict[str, Any]) -> SourceHealthResult:
        link = twitter_status_url(str(bookmark.get("link") or ""))
        if link is None or not twitter_source_needs_check(bookmark):
            return SourceHealthResult(
                SourceHealthStatus.NOT_APPLICABLE,
                source="twitter_oembed",
                reason="Bookmark does not need an X/Twitter source probe.",
            )
        try:
            response = self.get(
                self.endpoint,
                params={"url": link},
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            return SourceHealthResult(
                SourceHealthStatus.UNKNOWN,
                source="twitter_oembed",
                reason=f"Source check failed transiently: {type(error).__name__}",
            )
        status_code = int(response.status_code)
        if status_code == 200:
            status = SourceHealthStatus.AVAILABLE
            reason = "Twitter embed metadata is available."
        elif status_code in self.terminal_statuses:
            status = SourceHealthStatus.UNAVAILABLE
            reason = f"Twitter returned HTTP {status_code}; the post is inaccessible."
        else:
            status = SourceHealthStatus.UNKNOWN
            reason = f"Twitter returned HTTP {status_code}; availability is inconclusive."
        return SourceHealthResult(
            status,
            source="twitter_oembed",
            reason=reason,
            http_status=status_code,
        )
