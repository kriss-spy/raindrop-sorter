"""Canonical bookmark modality inference shared by routing policies."""

import re
from typing import Any


def bookmark_modality(bookmark: dict[str, Any]) -> str | None:
    """Infer the UI group used for modality-specific collection routes."""
    domain = str(bookmark.get("domain", "")).casefold()
    link = str(bookmark.get("link", "")).casefold()
    if domain in {"x.com", "twitter.com", "www.x.com", "www.twitter.com"}:
        media = bookmark.get("media") or []
        media_types = {
            str(item.get("type", "")).casefold()
            for item in media
        }
        if "video" in media_types:
            return "video"
        if "image" in media_types or bookmark.get("cover"):
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
