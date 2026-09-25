"""Canonical bookmark modality inference shared by routing policies."""

import re
from typing import Any
from urllib.parse import urlparse

VISUAL_ART_DOMAINS = {
    "pixiv.net",
    "www.pixiv.net",
}


def bookmark_modality(bookmark: dict[str, Any]) -> str | None:
    """Infer the UI group used for modality-specific collection routes."""
    domain = str(bookmark.get("domain", "")).casefold()
    link = str(bookmark.get("link", "")).casefold()
    link_host = str(urlparse(link).hostname or "").casefold()
    media_types = {
        str(item.get("type", "")).casefold()
        for item in bookmark.get("media") or []
        if isinstance(item, dict)
    }
    if domain in {"x.com", "twitter.com", "www.x.com", "www.twitter.com"}:
        if "video" in media_types:
            return "video"
        if "image" in media_types or bookmark.get("cover"):
            return "art"

    if any(
        host in VISUAL_ART_DOMAINS or host.endswith(".pixiv.net")
        for host in (domain, link_host)
    ) and (
        "image" in media_types or bookmark.get("cover")
    ):
        return "art"

    bookmark_type = str(bookmark.get("type", "")).casefold()
    if bookmark_type == "image":
        return "art"
    if bookmark_type == "audio":
        return "music"
    if bookmark_type == "video":
        return "video"

    if domain in {"youtube.com", "www.youtube.com", "youtu.be", "vimeo.com"}:
        return "video"
    if domain in {"open.spotify.com", "soundcloud.com", "bandcamp.com"}:
        return "music"
    if domain in {"x.com", "twitter.com", "www.x.com", "www.twitter.com"}:
        if bookmark.get("media"):
            return "art"
    if re.search(r"\.(?:mp3|flac|wav|m4a|ogg)(?:$|[?#])", link):
        return "music"
    if re.search(r"\.(?:mp4|webm|mov|mkv)(?:$|[?#])", link):
        return "video"
    if re.search(r"\.(?:png|jpe?g|gif|webp|avif)(?:$|[?#])", link):
        return "art"
    return None
