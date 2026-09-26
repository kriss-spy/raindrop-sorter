"""Audit unresolved Twitter bookmarks and ignore permanently inaccessible posts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from src.run_journal import SQLiteRunJournal
from src.source_error_lifecycle import record_source_error
from src.source_health import (
    SourceHealthStatus,
    TwitterSourceHealthChecker,
    twitter_source_needs_check,
)


UNRESOLVED_OUTCOMES = ("review", "provisional", "conflict")


def ignore_broken_twitter_sources(
    journal: SQLiteRunJournal,
    *,
    client: Any,
    checker: Any | None = None,
    apply: bool = False,
    scan_limit: int = 10_000,
    workers: int = 8,
) -> dict[str, Any]:
    """Check unresolved X/Twitter statuses and persist terminal errors."""
    checker = checker or TwitterSourceHealthChecker()
    candidates: dict[int, dict[str, Any]] = {}
    for outcome in UNRESOLVED_OUTCOMES:
        for item in journal.recent(
            limit=scan_limit,
            outcome=outcome,
            latest_per_bookmark=True,
            mode=("apply", "manual-review", "legacy-tag-migration"),
            exclude_phase="skipped_stale",
        ):
            bookmark = {
                "_id": int(item["bookmark_id"]),
                "title": (
                    None
                    if item.get("title") == f"Bookmark {item['bookmark_id']}"
                    else item.get("title")
                ),
                "link": item.get("link"),
                "excerpt": item.get("excerpt"),
                "collection": {"$id": item.get("collection_id")},
            }
            if twitter_source_needs_check(bookmark):
                candidates[int(item["bookmark_id"])] = bookmark
    work = []
    reconciliation_failures = []
    skipped_moved = []
    for bookmark_id, snapshot in candidates.items():
        try:
            live = client.get_raindrop(bookmark_id)
        except Exception as error:
            reconciliation_failures.append({
                "bookmark_id": bookmark_id,
                "type": type(error).__name__,
                "message": str(error),
            })
            continue
        current_collection = (live.get("collection") or {}).get("$id")
        if current_collection not in (None, -1):
            skipped_moved.append(bookmark_id)
            continue
        live.setdefault("_id", snapshot["_id"])
        if twitter_source_needs_check(live):
            work.append(live)
    if work:
        with ThreadPoolExecutor(max_workers=min(workers, len(work))) as executor:
            health_results = list(executor.map(checker.check, work))
    else:
        health_results = []
    unavailable = [
        (bookmark, health)
        for bookmark, health in zip(work, health_results)
        if health.status is SourceHealthStatus.UNAVAILABLE
    ]
    ignored = []
    if apply:
        for bookmark, health in unavailable:
            attempt = journal.start_attempt(
                bookmark,
                mode="apply",
                pinned_index_version="native-local-index-v1",
                runner_version="source-health-v1",
            )
            record_source_error(
                journal,
                attempt,
                bookmark,
                health,
                apply=True,
            )
            ignored.append(int(bookmark["_id"]))
    status_counts: dict[str, int] = {}
    for health in health_results:
        status_counts[health.status.value] = status_counts.get(health.status.value, 0) + 1
    return {
        "status": "ok",
        "applied": apply,
        "checked": len(work),
        "would_ignore": len(unavailable),
        "ignored": len(ignored),
        "ignored_bookmark_ids": ignored,
        "skipped_moved": skipped_moved,
        "reconciliation_failures": reconciliation_failures,
        "source_statuses": status_counts,
    }
