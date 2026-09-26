"""Populate the cover projection for bookmarks represented in the Run Journal."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from src.cover_cache import SQLiteCoverCache
from src.run_journal import SQLiteRunJournal


def migrate_cover_cache(
    source: Any,
    journal: SQLiteRunJournal,
    cover_cache: SQLiteCoverCache,
    *,
    collection_scopes: Iterable[int] = (0, -99),
    progress: Callable[[dict[str, int]], None] | None = None,
) -> dict[str, int | str]:
    """Cache covers for journal bookmarks using Raindrop's paged list response."""
    pending = cover_cache.unobserved(journal.bookmark_ids())
    initial_count = len(pending)
    if not pending:
        return {
            "status": "ok",
            "journal_bookmarks": 0,
            "scanned": 0,
            "cached": 0,
            "without_cover": 0,
        }

    scanned = 0
    cached = 0
    without_cover = 0
    pages = 0
    for collection_id in collection_scopes:
        page = 0
        while True:
            items, has_more = source.get_raindrops(
                collection_id,
                page=page,
                perpage=50,
            )
            scanned += len(items)
            pages += 1
            matches = [item for item in items if int(item["_id"]) in pending]
            if matches:
                cover_cache.record_many(matches)
                matched_ids = {int(item["_id"]) for item in matches}
                pending.difference_update(matched_ids)
                cached += sum(bool(item.get("cover")) for item in matches)
                without_cover += sum(not item.get("cover") for item in matches)
                if not pending:
                    return {
                        "status": "ok",
                        "journal_bookmarks": initial_count,
                        "scanned": scanned,
                        "cached": cached,
                        "without_cover": without_cover,
                    }
            if progress is not None and (pages % 25 == 0 or not has_more):
                progress({
                    "pages": pages,
                    "scanned": scanned,
                    "cached": cached,
                    "remaining": len(pending),
                })
            if not has_more:
                break
            page += 1

    cover_cache.record_unavailable(pending)
    return {
        "status": "ok",
        "journal_bookmarks": initial_count,
        "scanned": scanned,
        "cached": cached,
        "without_cover": without_cover + len(pending),
    }
