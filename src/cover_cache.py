"""Persistent projection of current Raindrop cover metadata for the dashboard."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cover_url(bookmark: dict[str, Any]) -> str | None:
    """Prefer a normal X media CDN URL over its generated preview endpoint."""
    cover = str(bookmark.get("cover") or "")
    if urlparse(cover).netloc.casefold() == "jf.x.com":
        for media_item in bookmark.get("media") or []:
            if not isinstance(media_item, dict):
                continue
            candidate = str(media_item.get("link") or "")
            if (
                str(media_item.get("type") or "").casefold() == "image"
                and urlparse(candidate).netloc.casefold() == "pbs.twimg.com"
            ):
                return candidate
    return cover or None


class SQLiteCoverCache:
    """Store current cover observations separately from immutable journal history."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS bookmark_covers (
                    bookmark_id INTEGER PRIMARY KEY,
                    cover_url TEXT,
                    cover_fingerprint TEXT,
                    observed_at TEXT NOT NULL
                )
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def record(self, bookmark: dict[str, Any]) -> None:
        self.record_many([bookmark])

    def record_many(self, bookmarks: list[dict[str, Any]]) -> None:
        observations = []
        now = _utc_now()
        for bookmark in bookmarks:
            cover = _cover_url(bookmark)
            fingerprint = (
                hashlib.sha256(cover.encode("utf-8")).hexdigest() if cover else None
            )
            observations.append((int(bookmark["_id"]), cover, fingerprint, now))
        if not observations:
            return
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO bookmark_covers(
                    bookmark_id, cover_url, cover_fingerprint, observed_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(bookmark_id) DO UPDATE SET
                    cover_url = excluded.cover_url,
                    cover_fingerprint = excluded.cover_fingerprint,
                    observed_at = excluded.observed_at
                """,
                observations,
            )

    def record_unavailable(self, bookmark_ids: set[int]) -> None:
        if not bookmark_ids:
            return
        now = _utc_now()
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO bookmark_covers(
                    bookmark_id, cover_url, cover_fingerprint, observed_at
                ) VALUES (?, NULL, NULL, ?)
                ON CONFLICT(bookmark_id) DO UPDATE SET
                    cover_url = NULL,
                    cover_fingerprint = NULL,
                    observed_at = excluded.observed_at
                """,
                [(bookmark_id, now) for bookmark_id in bookmark_ids],
            )

    def unobserved(self, bookmark_ids: set[int]) -> set[int]:
        with self._connect() as connection:
            observed = {
                int(row["bookmark_id"])
                for row in connection.execute("SELECT bookmark_id FROM bookmark_covers")
            }
        return bookmark_ids - observed

    def get(self, bookmark_id: int) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT cover_url FROM bookmark_covers WHERE bookmark_id = ?",
                (bookmark_id,),
            ).fetchone()
        return str(row["cover_url"]) if row is not None and row["cover_url"] else None

    def attach(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not items:
            return items
        bookmark_ids = {int(item["bookmark_id"]) for item in items}
        placeholders = ", ".join("?" for _bookmark_id in bookmark_ids)
        with self._connect() as connection:
            covers = {
                int(row["bookmark_id"]): row["cover_url"]
                for row in connection.execute(
                    f"SELECT bookmark_id, cover_url FROM bookmark_covers "
                    f"WHERE bookmark_id IN ({placeholders})",
                    tuple(bookmark_ids),
                )
            }
        return [
            {**item, "cover": covers.get(int(item["bookmark_id"]))}
            for item in items
        ]
