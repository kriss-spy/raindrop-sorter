"""Migrate remote lifecycle state and remove all sorter-owned Raindrop tags."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from src.run_journal import SQLiteRunJournal
from src.state_machine import (
    EDGE_CASE_PREFIX,
    NEEDS_REVIEW_PREFIX,
    PENDING_RESOLUTION,
    PENDING_VISION_PREFIX,
    REVIEWED_PREFIX,
    UNREVIEWED,
    VISION_ATTEMPTED,
    is_remote_lifecycle_tag,
    is_remote_sorter_tag,
    without_remote_sorter_tags,
)

ACTIVE_LIBRARY_SCOPE = 0
TRASH_SCOPE = -99


def migrate_remote_sorter_tags(
    client: Any,
    journal: SQLiteRunJournal,
    *,
    apply: bool = False,
    batch_size: int = 100,
    collection_scopes: Iterable[int] = (ACTIVE_LIBRARY_SCOPE, TRASH_SCOPE),
    destination_paths: dict[int, str] | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Persist legacy state, then remove every sorter-owned remote tag."""
    bookmarks = _discover_tagged_bookmarks(
        client,
        collection_scopes,
        limit=batch_size,
    )
    plans = []
    for bookmark_id in sorted(bookmarks):
        bookmark = bookmarks[bookmark_id]
        legacy_state_tags = [
            str(tag) for tag in bookmark.get("tags", [])
            if is_remote_lifecycle_tag(tag)
        ]
        phase, outcome = _optional_legacy_state(legacy_state_tags)
        collection_id = (bookmark.get("collection") or {}).get("$id")
        destination = (
            (destination_paths or {}).get(int(collection_id))
            if collection_id is not None
            else None
        )
        requires_import = bool(legacy_state_tags) and not journal.state_matches(
            bookmark_id,
            phase=phase,
            outcome=outcome,
            destination=destination,
        )
        plans.append({
            "bookmark_id": bookmark_id,
            "source_tags": [
                str(tag) for tag in bookmark.get("tags", [])
                if is_remote_sorter_tag(tag)
            ],
            "phase": phase,
            "outcome": outcome,
            "destination": destination,
            "cleaned_tags": without_remote_sorter_tags(bookmark.get("tags", [])),
            "requires_import": requires_import,
        })
    would_import = sum(bool(item["requires_import"]) for item in plans)
    state_import_bookmarks = sum(item["phase"] is not None for item in plans)
    result: dict[str, Any] = {
        "status": "ok",
        "mode": "sorter_tag_migration",
        "applied": apply,
        "batch_limit": batch_size,
        "discovered": len(bookmarks),
        "would_import": would_import,
        "would_clean": len(bookmarks),
        "state_import_bookmarks": state_import_bookmarks,
        "extraction_only_bookmarks": len(bookmarks) - state_import_bookmarks,
        "imported": 0,
        "already_journaled": state_import_bookmarks - would_import,
        "cleaned": 0,
        "failed": 0,
        "errors": [],
    }
    if not apply:
        result["items"] = plans
        return result

    paths = destination_paths or {}
    for index, plan in enumerate(plans, start=1):
        bookmark_id = int(plan["bookmark_id"])
        try:
            bookmark = client.get_raindrop(bookmark_id)
            live_sorter_tags = [
                str(tag) for tag in bookmark.get("tags", [])
                if is_remote_sorter_tag(tag)
            ]
            if not live_sorter_tags:
                continue
            live_legacy_state_tags = [
                tag for tag in live_sorter_tags if is_remote_lifecycle_tag(tag)
            ]
            if live_legacy_state_tags:
                phase, outcome = _legacy_state(live_legacy_state_tags)
                collection_id = (bookmark.get("collection") or {}).get("$id")
                destination = (
                    paths.get(int(collection_id))
                    if collection_id is not None
                    else None
                )
                if not journal.state_matches(
                    bookmark_id,
                    phase=phase,
                    outcome=outcome,
                    destination=destination,
                ):
                    imported = journal.import_legacy_state(
                        bookmark,
                        outcome=outcome,
                        phase=phase,
                        destination=destination,
                    )
                    result["imported"] += int(imported)
                    if not imported and not journal.state_matches(
                        bookmark_id,
                        phase=phase,
                        outcome=outcome,
                        destination=destination,
                    ):
                        raise RuntimeError("legacy state was not persisted")
            client.update_raindrop(
                bookmark_id,
                tags=without_remote_sorter_tags(bookmark.get("tags", [])),
            )
            result["cleaned"] += 1
        except Exception as error:
            result["failed"] += 1
            result["errors"].append({
                "bookmark_id": bookmark_id,
                "type": type(error).__name__,
                "message": str(error),
            })
        if progress is not None and (index % 25 == 0 or index == len(bookmarks)):
            progress({
                "processed": index,
                "total": len(bookmarks),
                "cleaned": result["cleaned"],
                "failed": result["failed"],
            })
    remaining = _discover_tagged_bookmarks(client, collection_scopes, limit=batch_size)
    result["remaining"] = len(remaining)
    result["remaining_bookmark_ids"] = sorted(remaining)
    if result["failed"] or remaining:
        result["status"] = "partial"
    return result


def _discover_tagged_bookmarks(
    client: Any,
    collection_scopes: Iterable[int],
    *,
    limit: int,
) -> dict[int, dict[str, Any]]:
    bookmarks: dict[int, dict[str, Any]] = {}
    for collection_id in collection_scopes:
        sorter_tags = sorted(
            str(tag["_id"])
            for tag in client.get_tags(collection_id)
            if is_remote_sorter_tag(tag.get("_id", ""))
        )
        for tag in sorter_tags:
            page = 0
            while True:
                items, has_more = client.get_raindrops(
                    collection_id,
                    page=page,
                    perpage=50,
                    search=f'#"{tag}"',
                )
                for item in items:
                    bookmarks[int(item["_id"])] = item
                    if len(bookmarks) >= limit:
                        return bookmarks
                if not has_more:
                    break
                page += 1
    return bookmarks


def _optional_legacy_state(tags: list[str]) -> tuple[str | None, str | None]:
    return _legacy_state(tags) if tags else (None, None)


# Backward-compatible import for callers using the original migration name.
migrate_remote_lifecycle = migrate_remote_sorter_tags


def _legacy_state(tags: list[str]) -> tuple[str, str | None]:
    values = [str(tag) for tag in tags]
    if any(tag.startswith(f"{PENDING_VISION_PREFIX}:") for tag in values):
        return "visual_queued", None
    if PENDING_RESOLUTION in values:
        return "pending_resolution", None
    if UNREVIEWED in values:
        return "queued_in_journal", None
    if any(tag.startswith(f"{EDGE_CASE_PREFIX}:") for tag in values):
        return "applied", "conflict"
    if any(tag.startswith(f"{NEEDS_REVIEW_PREFIX}:") for tag in values):
        return "applied", "provisional"
    if any(tag.startswith(f"{REVIEWED_PREFIX}:") for tag in values):
        return "applied", "review"
    if VISION_ATTEMPTED in values:
        return "visual_completed", None
    return "applied", "confirmed"
