"""Vision worker: download cover images and run WD14 tagger."""

from typing import Any

import requests

from src.wd14_tagger import WD14Tagger


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
    cover_url = bookmark.get("cover")
    if not cover_url:
        return []

    image_bytes = download_cover(cover_url)
    if image_bytes is None:
        return []

    tagger = tagger or WD14Tagger()
    raw_tags = tagger.predict(image_bytes)
    return [f"ai:wdtag-{tag}" for tag in raw_tags]
