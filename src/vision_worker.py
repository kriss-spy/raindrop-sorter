"""Vision worker: download cover images and run WD14 tagger."""

import re
from typing import Any
from urllib.parse import urlparse

import requests

from src.wd14_tagger import WD14Tagger

FXTWITTER_API_BASE = "https://api.fxtwitter.com/status"
X_STATUS_PATTERN = re.compile(
    r"https?://(?:www\.)?(?:x|twitter)\.com/[^/]+/status/(\d+)",
    re.IGNORECASE,
)


def _is_x_placeholder(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.netloc.casefold() == "abs.twimg.com"
        and parsed.path.endswith("/og/image.png")
    )


def _recover_x_photo_url(bookmark: dict[str, Any], timeout: int = 15) -> str | None:
    match = X_STATUS_PATTERN.search(str(bookmark.get("link", "")))
    if match is None:
        return None
    try:
        response = requests.get(
            f"{FXTWITTER_API_BASE}/{match.group(1)}",
            timeout=timeout,
        )
        response.raise_for_status()
        media = response.json().get("tweet", {}).get("media", {})
        candidates = [*media.get("photos", []), *media.get("all", [])]
        for item in candidates:
            if item.get("type") == "photo" and item.get("url"):
                return str(item["url"])
    except Exception:
        return None
    return None


def resolve_cover_url(bookmark: dict[str, Any]) -> str | None:
    """Return real image media, recovering legacy X placeholder covers."""
    cover_url = str(bookmark.get("cover", "") or "")
    if cover_url and not _is_x_placeholder(cover_url):
        return cover_url

    for media_item in bookmark.get("media") or []:
        media_url = str(media_item.get("link", "") or "")
        if (
            str(media_item.get("type", "")).casefold() == "image"
            and media_url
            and not _is_x_placeholder(media_url)
        ):
            return media_url

    if _is_x_placeholder(cover_url):
        return _recover_x_photo_url(bookmark)
    return None


def download_cover(cover_url: str, timeout: int = 30) -> bytes | None:
    """Download a cover image from a URL.

    Returns None on any network or HTTP error for graceful fallback.
    """
    try:
        resp = requests.get(cover_url, timeout=timeout)
        resp.raise_for_status()
        return resp.content
    except Exception:
        return None


def run_vision_on_bookmark(
    bookmark: dict[str, Any],
    tagger: WD14Tagger | None = None,
) -> list[str]:
    """Download the bookmark's cover image and return WD14 tags.

    Tags are formatted as ``ai:wdtag-<normalized_tag>``.

    Args:
        bookmark: Raindrop bookmark dict; must contain a ``cover`` key.
        tagger: Optional WD14Tagger instance for reuse.

    Returns:
        List of AI extraction tags. Empty if no cover URL or download fails.
    """
    cover_url = resolve_cover_url(bookmark)
    if not cover_url:
        return []

    image_bytes = download_cover(cover_url)
    if image_bytes is None:
        return []

    tagger = tagger or WD14Tagger()
    raw_tags = tagger.predict(image_bytes)
    return [f"ai:wdtag-{tag}" for tag in raw_tags]


def run_character_vision_on_bookmark(
    bookmark: dict[str, Any],
    tagger: WD14Tagger | None = None,
) -> list[str]:
    """Return only WD14 character labels for historical rule learning."""
    cover_url = resolve_cover_url(bookmark)
    if not cover_url:
        return []
    image_bytes = download_cover(cover_url)
    if image_bytes is None:
        return []
    tagger = tagger or WD14Tagger()
    return tagger.predict_characters(image_bytes)
