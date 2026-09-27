"""Append-only SQLite journal for local sorter attempts."""

from __future__ import annotations

import json
import hashlib
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from src.routing import RouteDecision, TextEvidence, VisualEvidence
from src.state_machine import is_remote_lifecycle_tag


SCHEMA_VERSION = 2
AUTOMATIC_ATTEMPT_LEASE_SECONDS = 60 * 60
MUTATING_ATTEMPT_MODES = (
    "apply",
    "manual-review",
    "legacy-tag-migration",
    "manual-delete",
)
_MUTATING_ATTEMPT_MODES_SQL = ", ".join(
    repr(mode) for mode in MUTATING_ATTEMPT_MODES
)
_LATEST_ATTEMPTS_CTE = """
    WITH latest_attempts AS (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY bookmark_id
            ORDER BY started_at DESC, attempt_id DESC
        ) AS bookmark_rank
        FROM attempts
    )
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _evidence_destinations(
    evidence_items: list[dict[str, Any]],
    *,
    include_visual_winner: bool = False,
) -> list[str]:
    destinations: list[str] = []
    for evidence in evidence_items:
        values = [evidence.get("destination"), *(evidence.get("candidates") or [])]
        if include_visual_winner:
            values.append(evidence.get("winner"))
        for value in values:
            destination = str(value or "").strip()
            if destination and destination not in destinations:
                destinations.append(destination)
    return destinations


def _review_ai_group(decision: dict[str, Any]) -> tuple[str | None, str | None]:
    """Choose a review bucket from text first, then the visual work winner."""
    text_destinations = _evidence_destinations(decision.get("text_evidence", []))
    visual_destinations = _evidence_destinations(
        decision.get("visual_evidence", []),
        include_visual_winner=True,
    )
    if text_destinations:
        if len(text_destinations) > 1:
            visual_set = set(visual_destinations)
            corroborated = next(
                (item for item in text_destinations if item in visual_set),
                None,
            )
            if corroborated:
                return corroborated, "text+visual"
        return text_destinations[0], "text"
    if visual_destinations:
        return visual_destinations[0], "visual"
    return None, None


@dataclass(frozen=True)
class AttemptHandle:
    attempt_id: str
    bookmark_id: int


class RunJournal(Protocol):
    """Runtime journal interface used by the local runner."""

    def start_attempt(
        self,
        bookmark: dict[str, Any],
        *,
        mode: str,
        pinned_index_version: str | None = None,
        runner_version: str | None = None,
        initial_event: tuple[str, dict[str, Any]] | None = None,
    ) -> AttemptHandle: ...

    def record_event(
        self,
        attempt: AttemptHandle,
        phase: str,
        payload: dict[str, Any] | None = None,
        *,
        duration_ms: float | None = None,
    ) -> None: ...

    def record_decision(
        self, attempt: AttemptHandle, decision: RouteDecision
    ) -> None: ...

    def record_action(self, attempt: AttemptHandle, **kwargs: Any) -> None: ...

    def complete(self, attempt: AttemptHandle, *, phase: str = "applied") -> None: ...

    def fail(self, attempt: AttemptHandle, error: BaseException) -> None: ...

    def terminal_bookmark_ids(self) -> set[int]: ...

    def automatic_processing_exclusions(self) -> set[int]: ...

    def claim_automatic(
        self,
        bookmark: dict[str, Any],
        *,
        pinned_index_version: str | None = None,
        runner_version: str | None = None,
    ) -> AttemptHandle | None: ...

    def claim_rerun(
        self,
        bookmark: dict[str, Any],
        *,
        expected_attempt_id: str,
        pinned_index_version: str | None = None,
        runner_version: str | None = None,
    ) -> AttemptHandle | None: ...

    def renew_automatic_claim(self, attempt: AttemptHandle) -> bool: ...


class SQLiteRunJournal:
    """Durable local implementation of the revised ``RunJournal`` seam."""

    def __init__(self, path: str | Path, *, read_only: bool = False):
        self.path = Path(path)
        self.read_only = read_only
        if read_only:
            if not self.path.is_file():
                raise FileNotFoundError(f"journal does not exist: {self.path}")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self.read_only:
            connection = sqlite3.connect(
                f"file:{self.path.resolve()}?mode=ro", uri=True
            )
        else:
            connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            if not self.read_only:
                connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id TEXT PRIMARY KEY,
                    bookmark_id INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    current_phase TEXT NOT NULL,
                    outcome TEXT,
                    destination TEXT,
                    pinned_index_version TEXT,
                    runner_version TEXT,
                    mode TEXT NOT NULL,
                    claim_heartbeat_at TEXT,
                    bookmark_snapshot_json TEXT NOT NULL,
                    decision_json TEXT,
                    error_json TEXT
                );
                CREATE INDEX IF NOT EXISTS attempts_bookmark_started
                    ON attempts(bookmark_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS attempts_phase
                    ON attempts(current_phase);
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
                    sequence INTEGER NOT NULL,
                    phase TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    duration_ms REAL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(attempt_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS evidence (
                    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
                    source_kind TEXT NOT NULL,
                    destination TEXT,
                    status TEXT,
                    strength TEXT,
                    explanation TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS actions (
                    action_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
                    action_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    destination TEXT,
                    request_count INTEGER NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    latency_ms REAL,
                    error_classification TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS index_versions (
                    manifest_hash TEXT PRIMARY KEY,
                    activated_at TEXT NOT NULL,
                    manifest_json TEXT NOT NULL
                );
                """
            )
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO metadata(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                ("schema_version", str(SCHEMA_VERSION)),
            )
            attempt_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(attempts)").fetchall()
            }
            if "claim_heartbeat_at" not in attempt_columns:
                connection.execute(
                    "ALTER TABLE attempts ADD COLUMN claim_heartbeat_at TEXT"
                )

    def start_attempt(
        self,
        bookmark: dict[str, Any],
        *,
        mode: str,
        pinned_index_version: str | None = None,
        runner_version: str | None = None,
        initial_event: tuple[str, dict[str, Any]] | None = None,
    ) -> AttemptHandle:
        attempt = AttemptHandle(str(uuid.uuid4()), int(bookmark["_id"]))
        snapshot = _bookmark_snapshot(bookmark)
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO attempts(
                    attempt_id, bookmark_id, started_at, current_phase,
                    pinned_index_version, runner_version, mode,
                    bookmark_snapshot_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt.attempt_id,
                    attempt.bookmark_id,
                    now,
                    "discovered",
                    pinned_index_version,
                    runner_version,
                    mode,
                    _json(snapshot),
                ),
            )
            self._append_event(connection, attempt.attempt_id, "discovered", snapshot)
            if initial_event is not None:
                phase, payload = initial_event
                self._append_event(connection, attempt.attempt_id, phase, payload)
                connection.execute(
                    "UPDATE attempts SET current_phase = ? WHERE attempt_id = ?",
                    (phase, attempt.attempt_id),
                )
        return attempt

    def record_event(
        self,
        attempt: AttemptHandle,
        phase: str,
        payload: dict[str, Any] | None = None,
        *,
        duration_ms: float | None = None,
    ) -> None:
        with self._connect() as connection:
            self._append_event(
                connection,
                attempt.attempt_id,
                phase,
                payload or {},
                duration_ms=duration_ms,
            )
            connection.execute(
                "UPDATE attempts SET current_phase = ? WHERE attempt_id = ?",
                (phase, attempt.attempt_id),
            )

    def record_decision(
        self,
        attempt: AttemptHandle,
        decision: RouteDecision,
    ) -> None:
        phase = f"decided_{decision.outcome.value}"
        with self._connect() as connection:
            self._append_event(
                connection,
                attempt.attempt_id,
                phase,
                decision.to_dict(),
            )
            for evidence in (*decision.text_evidence, *decision.visual_evidence):
                self._insert_evidence(connection, attempt.attempt_id, evidence)
            connection.execute(
                """
                UPDATE attempts
                SET current_phase = ?, outcome = ?, destination = ?, decision_json = ?
                WHERE attempt_id = ?
                """,
                (
                    phase,
                    decision.outcome.value,
                    decision.destination,
                    _json(decision.to_dict()),
                    attempt.attempt_id,
                ),
            )

    def record_action(
        self,
        attempt: AttemptHandle,
        *,
        action_kind: str,
        status: str,
        destination: str | None,
        payload: dict[str, Any] | None = None,
        request_count: int = 0,
        retry_count: int = 0,
        latency_ms: float | None = None,
        error_classification: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO actions(
                    attempt_id, action_kind, status, destination, request_count,
                    retry_count, latency_ms, error_classification, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt.attempt_id,
                    action_kind,
                    status,
                    destination,
                    request_count,
                    retry_count,
                    latency_ms,
                    error_classification,
                    _json(payload or {}),
                ),
            )

    def complete(self, attempt: AttemptHandle, *, phase: str = "applied") -> None:
        now = _utc_now()
        with self._connect() as connection:
            self._append_event(connection, attempt.attempt_id, phase, {})
            connection.execute(
                "UPDATE attempts SET current_phase = ?, ended_at = ? WHERE attempt_id = ?",
                (phase, now, attempt.attempt_id),
            )

    def fail(self, attempt: AttemptHandle, error: BaseException) -> None:
        payload = {"type": type(error).__name__, "message": str(error)}
        now = _utc_now()
        with self._connect() as connection:
            self._append_event(connection, attempt.attempt_id, "failed", payload)
            connection.execute(
                """
                UPDATE attempts
                SET current_phase = 'failed', ended_at = ?, error_json = ?
                WHERE attempt_id = ?
                """,
                (now, _json(payload), attempt.attempt_id),
            )

    def explain(self, bookmark_id: int) -> dict[str, Any] | None:
        """Return the latest complete trace for one bookmark."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM attempts
                WHERE bookmark_id = ?
                ORDER BY started_at DESC, attempt_id DESC LIMIT 1
                """,
                (bookmark_id,),
            ).fetchone()
            return self._trace(connection, row)

    def explain_attempt(self, attempt_id: str) -> dict[str, Any] | None:
        """Return one exact attempt trace, including historical attempts."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
            return self._trace(connection, row)

    def recent_manual_destinations(self) -> list[dict[str, str]]:
        """Return successful review destinations ordered by latest manual use."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT destination AS path, MAX(started_at) AS last_assigned_at
                FROM attempts
                WHERE mode = 'manual-review'
                  AND outcome = 'confirmed'
                  AND current_phase = 'applied'
                  AND destination IS NOT NULL
                GROUP BY destination
                ORDER BY last_assigned_at DESC, destination COLLATE NOCASE
                """
            ).fetchall()
        return [
            {
                "path": str(row["path"]),
                "last_assigned_at": str(row["last_assigned_at"]),
            }
            for row in rows
        ]

    def recent(
        self,
        *,
        limit: int = 20,
        before: tuple[str, str] | None = None,
        snapshot: tuple[str, str] | None = None,
        outcome: str | None = None,
        phase: str | None = None,
        query: str | None = None,
        labels: tuple[str, ...] = (),
        title: str | None = None,
        link: str | None = None,
        processed_on: str | None = None,
        utc_offset_minutes: int = 0,
        bookmark_ids: set[int] | None = None,
        latest_per_bookmark: bool = False,
        mode: str | tuple[str, ...] | None = None,
        status_mode: str | None = None,
        exclude_phase: str | None = None,
    ) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        requested_date = None
        if processed_on:
            try:
                requested_date = date.fromisoformat(processed_on)
            except ValueError as error:
                raise ValueError("processed_on must use YYYY-MM-DD") from error
        if not -14 * 60 <= utc_offset_minutes <= 14 * 60:
            raise ValueError("utc_offset_minutes must be between -840 and 840")
        if bookmark_ids == set():
            return []
        with self._connect() as connection:
            clauses: list[str] = []
            parameters: list[Any] = []
            if outcome:
                clauses.append("outcome = ?")
                parameters.append(outcome)
            if phase:
                clauses.append("current_phase = ?")
                parameters.append(phase)
            if exclude_phase:
                clauses.append("current_phase != ?")
                parameters.append(exclude_phase)
            if status_mode:
                clauses.append("mode = ?")
                parameters.append(status_mode)
            if before is not None:
                before_started_at, before_attempt_id = before
                clauses.append(
                    "(started_at < ? OR (started_at = ? AND attempt_id < ?))"
                )
                parameters.extend(
                    [before_started_at, before_started_at, before_attempt_id]
                )
            source = "attempts"
            cte_parameters: list[Any] = []
            if latest_per_bookmark:
                source = "latest_attempts"
                clauses.insert(0, "bookmark_rank = 1")
                cte_clauses: list[str] = []
                if mode:
                    modes = (mode,) if isinstance(mode, str) else mode
                    placeholders = ", ".join("?" for _mode in modes)
                    cte_clauses.append(f"mode IN ({placeholders})")
                    cte_parameters.extend(modes)
                if snapshot is not None:
                    snapshot_started_at, snapshot_attempt_id = snapshot
                    cte_clauses.append(
                        "(started_at < ? OR (started_at = ? AND attempt_id <= ?))"
                    )
                    cte_parameters.extend(
                        [snapshot_started_at, snapshot_started_at, snapshot_attempt_id]
                    )
                if bookmark_ids is not None:
                    placeholders = ", ".join("?" for _id in bookmark_ids)
                    cte_clauses.append(f"bookmark_id IN ({placeholders})")
                    cte_parameters.extend(sorted(bookmark_ids))
                cte_where = (
                    f"WHERE {' AND '.join(cte_clauses)}" if cte_clauses else ""
                )
                latest_cte = f"""
                    WITH latest_attempts AS (
                        SELECT *, ROW_NUMBER() OVER (
                            PARTITION BY bookmark_id
                            ORDER BY started_at DESC, attempt_id DESC
                        ) AS bookmark_rank
                        FROM attempts {cte_where}
                    )
                """
            else:
                latest_cte = ""
                if mode:
                    modes = (mode,) if isinstance(mode, str) else mode
                    placeholders = ", ".join("?" for _mode in modes)
                    clauses.append(f"mode IN ({placeholders})")
                    parameters.extend(modes)
                if snapshot is not None:
                    snapshot_started_at, snapshot_attempt_id = snapshot
                    clauses.append(
                        "(started_at < ? OR (started_at = ? AND attempt_id <= ?))"
                    )
                    parameters.extend(
                        [snapshot_started_at, snapshot_started_at, snapshot_attempt_id]
                    )
                if bookmark_ids is not None:
                    placeholders = ", ".join("?" for _id in bookmark_ids)
                    clauses.append(f"bookmark_id IN ({placeholders})")
                    parameters.extend(sorted(bookmark_ids))
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            needs_python_filter = bool(
                query or labels or title or link or processed_on
            )
            sql_limit = "" if needs_python_filter else "LIMIT ?"
            if not needs_python_filter:
                parameters.append(limit)
            rows = connection.execute(
                f"""
                {latest_cte}
                SELECT attempt_id, bookmark_id, started_at, ended_at, current_phase,
                       outcome, destination, mode, bookmark_snapshot_json, decision_json
                FROM {source} {where} ORDER BY started_at DESC, attempt_id DESC
                {sql_limit}
                """,
                [*cte_parameters, *parameters],
            ).fetchall()

        needle = (query or "").strip().casefold()
        title_needle = (title or "").strip().casefold()
        link_needle = (link or "").strip().casefold()
        required_labels = {
            value.strip().casefold() for value in labels if value.strip()
        }
        local_timezone = timezone(timedelta(minutes=utc_offset_minutes))
        results = []
        for row in rows:
            decoded = _decode_row(row)
            snapshot = decoded.pop("bookmark_snapshot", {})
            decision = decoded.pop("decision", {}) or {}
            visual_labels = {
                str(label).casefold()
                for evidence in decision.get("visual_evidence", [])
                for label in evidence.get("labels", [])
            }
            ai_group, ai_group_source = _review_ai_group(decision)
            decoded.update(
                title=snapshot.get("title") or f"Bookmark {decoded['bookmark_id']}",
                link=snapshot.get("link"),
                excerpt=snapshot.get("excerpt"),
                collection_id=(snapshot.get("collection") or {}).get("$id"),
                summary=decision.get("summary"),
                visual_labels=sorted(visual_labels),
                ai_group=ai_group,
                ai_group_source=ai_group_source,
                duration_ms=_duration_ms(decoded["started_at"], decoded["ended_at"]),
            )
            if bookmark_ids is not None and decoded["bookmark_id"] not in bookmark_ids:
                continue
            if required_labels and not required_labels.issubset(visual_labels):
                continue
            if title_needle and title_needle not in str(decoded["title"]).casefold():
                continue
            if link_needle and link_needle not in str(decoded.get("link") or "").casefold():
                continue
            if requested_date is not None:
                processed_at = datetime.fromisoformat(
                    decoded["ended_at"] or decoded["started_at"]
                )
                if processed_at.astimezone(local_timezone).date() != requested_date:
                    continue
            if needle and not any(
                needle in str(decoded.get(key) or "").casefold()
                for key in ("bookmark_id", "title", "destination", "summary", "current_phase")
            ):
                continue
            results.append(decoded)
            if len(results) == limit:
                break
        return results

    def newest_cursor(self) -> tuple[str, str] | None:
        """Return an upper bound that freezes one journal browsing snapshot."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT started_at, attempt_id FROM attempts
                ORDER BY started_at DESC, attempt_id DESC LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return str(row["started_at"]), str(row["attempt_id"])

    def overview(self, *, bookmark_ids: set[int] | None = None) -> dict[str, Any]:
        """Return compact aggregate data for operator dashboards."""
        if bookmark_ids is not None:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT bookmark_id, started_at, current_phase, outcome
                    FROM attempts ORDER BY started_at DESC, attempt_id DESC
                    """
                ).fetchall()
            attempts = [row for row in rows if int(row["bookmark_id"]) in bookmark_ids]
            latest_by_bookmark: dict[int, sqlite3.Row] = {}
            for row in attempts:
                latest_by_bookmark.setdefault(int(row["bookmark_id"]), row)
            latest = list(latest_by_bookmark.values())

            def counts(items: list[sqlite3.Row], key: str) -> dict[str, int]:
                result: dict[str, int] = {}
                for item in items:
                    value = str(item[key])
                    result[value] = result.get(value, 0) + 1
                return dict(sorted(result.items()))

            def outcome_counts(items: list[sqlite3.Row]) -> dict[str, int]:
                result: dict[str, int] = {}
                for item in items:
                    outcome = (
                        "failed"
                        if item["current_phase"] == "failed"
                        else str(item["outcome"] or "pending")
                    )
                    result[outcome] = result.get(outcome, 0) + 1
                return dict(sorted(result.items()))

            return {
                "total_attempts": len(attempts),
                "total_bookmarks": len(latest),
                "latest_at": max(
                    (str(row["started_at"]) for row in attempts), default=None
                ),
                "phases": counts(latest, "current_phase"),
                "outcomes": outcome_counts(latest),
                "attempt_phases": counts(attempts, "current_phase"),
                "attempt_outcomes": outcome_counts(attempts),
            }
        with self._connect() as connection:
            total, total_bookmarks, latest_at = connection.execute(
                "SELECT COUNT(*), COUNT(DISTINCT bookmark_id), MAX(started_at) FROM attempts"
            ).fetchone()
            rows = connection.execute(
                f"""
                {_LATEST_ATTEMPTS_CTE}
                SELECT display_outcome AS outcome, COUNT(*) AS count
                FROM (
                    SELECT CASE WHEN current_phase = 'failed' THEN 'failed'
                                ELSE COALESCE(outcome, 'pending')
                           END AS display_outcome
                    FROM latest_attempts WHERE bookmark_rank = 1
                )
                GROUP BY display_outcome ORDER BY display_outcome
                """
            ).fetchall()
            attempt_outcome_rows = connection.execute(
                """
                SELECT display_outcome AS outcome, COUNT(*) AS count
                FROM (
                    SELECT CASE WHEN current_phase = 'failed' THEN 'failed'
                                ELSE COALESCE(outcome, 'pending')
                           END AS display_outcome
                    FROM attempts
                )
                GROUP BY display_outcome ORDER BY display_outcome
                """
            ).fetchall()
            attempt_phase_rows = connection.execute(
                """
                SELECT current_phase, COUNT(*) AS count
                FROM attempts GROUP BY current_phase ORDER BY current_phase
                """
            ).fetchall()
        return {
            "total_attempts": int(total),
            "total_bookmarks": int(total_bookmarks),
            "latest_at": latest_at,
            "phases": self.status(),
            "outcomes": {str(row["outcome"]): int(row["count"]) for row in rows},
            "attempt_phases": {
                str(row["current_phase"]): int(row["count"])
                for row in attempt_phase_rows
            },
            "attempt_outcomes": {
                str(row["outcome"]): int(row["count"])
                for row in attempt_outcome_rows
            },
        }

    def has_bookmark(self, bookmark_id: int) -> bool:
        """Return whether any journal attempt exists for a bookmark."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM attempts WHERE bookmark_id = ? LIMIT 1",
                (bookmark_id,),
            ).fetchone()
        return row is not None

    def state_matches(
        self,
        bookmark_id: int,
        *,
        phase: str,
        outcome: str | None,
        destination: str | None = None,
    ) -> bool:
        """Return whether latest database state matches the legacy state exactly."""
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT current_phase, outcome, destination FROM attempts
                WHERE bookmark_id = ?
                  AND mode IN ({_MUTATING_ATTEMPT_MODES_SQL})
                ORDER BY started_at DESC, attempt_id DESC
                LIMIT 1
                """,
                (bookmark_id,),
            ).fetchone()
        return (
            row is not None
            and row["current_phase"] == phase
            and row["outcome"] == outcome
            and row["destination"] == destination
        )

    def terminal_bookmark_ids(self) -> set[int]:
        """Return bookmarks whose latest database-backed mutation is complete."""
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                WITH mutating_attempts AS (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY bookmark_id
                        ORDER BY started_at DESC, attempt_id DESC
                    ) AS bookmark_rank
                    FROM attempts
                    WHERE mode IN ({_MUTATING_ATTEMPT_MODES_SQL})
                )
                SELECT bookmark_id FROM mutating_attempts
                WHERE bookmark_rank = 1 AND current_phase = 'applied'
                """
            ).fetchall()
        return {int(row["bookmark_id"]) for row in rows}

    def automatic_processing_exclusions(self) -> set[int]:
        """Exclude completed/manual work and fresh in-flight automatic attempts."""
        active_after = (
            datetime.now(timezone.utc)
            - timedelta(seconds=AUTOMATIC_ATTEMPT_LEASE_SECONDS)
        ).isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                WITH mutating_attempts AS (
                    SELECT attempts.*,
                           COALESCE(claim_heartbeat_at, started_at) AS last_activity_at,
                           ROW_NUMBER() OVER (
                        PARTITION BY bookmark_id
                        ORDER BY started_at DESC, attempt_id DESC
                    ) AS bookmark_rank
                    FROM attempts
                    WHERE mode IN ({_MUTATING_ATTEMPT_MODES_SQL})
                )
                SELECT bookmark_id FROM mutating_attempts
                WHERE bookmark_rank = 1
                  AND (
                      current_phase = 'applied'
                      OR mode = 'manual-review'
                      OR (
                          mode = 'apply'
                          AND current_phase != 'failed'
                          AND last_activity_at >= ?
                      )
                  )
                """,
                (active_after,),
            ).fetchall()
        return {int(row["bookmark_id"]) for row in rows}

    def claim_automatic(
        self,
        bookmark: dict[str, Any],
        *,
        pinned_index_version: str | None = None,
        runner_version: str | None = None,
    ) -> AttemptHandle | None:
        """Atomically claim a bookmark unless newer state already owns it."""
        bookmark_id = int(bookmark["_id"])
        attempt = AttemptHandle(str(uuid.uuid4()), bookmark_id)
        snapshot = _bookmark_snapshot(bookmark)
        now = _utc_now()
        active_after = (
            datetime.now(timezone.utc)
            - timedelta(seconds=AUTOMATIC_ATTEMPT_LEASE_SECONDS)
        ).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute(
                f"""
                SELECT current_phase, mode, started_at,
                       COALESCE(claim_heartbeat_at, started_at) AS last_activity_at
                FROM attempts
                WHERE bookmark_id = ?
                  AND mode IN ({_MUTATING_ATTEMPT_MODES_SQL})
                ORDER BY started_at DESC, attempt_id DESC
                LIMIT 1
                """,
                (bookmark_id,),
            ).fetchone()
            if latest is not None and (
                latest["current_phase"] == "applied"
                or latest["mode"] == "manual-review"
                or (
                    latest["mode"] == "apply"
                    and latest["current_phase"] != "failed"
                    and latest["last_activity_at"] >= active_after
                )
            ):
                return None
            connection.execute(
                """
                INSERT INTO attempts(
                    attempt_id, bookmark_id, started_at, current_phase,
                    pinned_index_version, runner_version, mode, claim_heartbeat_at,
                    bookmark_snapshot_json
                ) VALUES (?, ?, ?, ?, ?, ?, 'apply', ?, ?)
                """,
                (
                    attempt.attempt_id,
                    bookmark_id,
                    now,
                    "discovered",
                    pinned_index_version,
                    runner_version,
                    now,
                    _json(snapshot),
                ),
            )
            self._append_event(connection, attempt.attempt_id, "discovered", snapshot)
        return attempt

    def claim_rerun(
        self,
        bookmark: dict[str, Any],
        *,
        expected_attempt_id: str,
        pinned_index_version: str | None = None,
        runner_version: str | None = None,
    ) -> AttemptHandle | None:
        """Claim a rerun only while its selected journal state is still latest."""
        bookmark_id = int(bookmark["_id"])
        attempt = AttemptHandle(str(uuid.uuid4()), bookmark_id)
        snapshot = _bookmark_snapshot(bookmark)
        now = _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute(
                f"""
                SELECT attempt_id FROM attempts
                WHERE bookmark_id = ?
                  AND mode IN ({_MUTATING_ATTEMPT_MODES_SQL})
                ORDER BY started_at DESC, attempt_id DESC
                LIMIT 1
                """,
                (bookmark_id,),
            ).fetchone()
            if latest is None or latest["attempt_id"] != expected_attempt_id:
                return None
            connection.execute(
                """
                INSERT INTO attempts(
                    attempt_id, bookmark_id, started_at, current_phase,
                    pinned_index_version, runner_version, mode, claim_heartbeat_at,
                    bookmark_snapshot_json
                ) VALUES (?, ?, ?, ?, ?, ?, 'apply', ?, ?)
                """,
                (
                    attempt.attempt_id,
                    bookmark_id,
                    now,
                    "discovered",
                    pinned_index_version,
                    runner_version,
                    now,
                    _json(snapshot),
                ),
            )
            self._append_event(connection, attempt.attempt_id, "discovered", snapshot)
        return attempt

    def renew_automatic_claim(self, attempt: AttemptHandle) -> bool:
        """Refresh an active automatic claim without changing its lifecycle phase."""
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE attempts SET claim_heartbeat_at = ?
                WHERE attempt_id = ? AND bookmark_id = ?
                  AND mode = 'apply'
                  AND current_phase NOT IN ('applied', 'failed')
                  AND attempt_id = (
                      SELECT attempt_id FROM attempts
                      WHERE bookmark_id = ?
                        AND mode IN ({_MUTATING_ATTEMPT_MODES_SQL})
                      ORDER BY started_at DESC, attempt_id DESC
                      LIMIT 1
                  )
                """,
                (
                    _utc_now(),
                    attempt.attempt_id,
                    attempt.bookmark_id,
                    attempt.bookmark_id,
                ),
            )
            if cursor.rowcount == 1:
                return True
            latest = connection.execute(
                f"""
                SELECT attempt_id, current_phase FROM attempts
                WHERE bookmark_id = ?
                  AND mode IN ({_MUTATING_ATTEMPT_MODES_SQL})
                ORDER BY started_at DESC, attempt_id DESC
                LIMIT 1
                """,
                (attempt.bookmark_id,),
            ).fetchone()
        return (
            latest is not None
            and latest["attempt_id"] == attempt.attempt_id
            and latest["current_phase"] in ("applied", "failed")
        )

    def import_legacy_state(
        self,
        bookmark: dict[str, Any],
        *,
        outcome: str | None,
        phase: str,
        destination: str | None = None,
    ) -> bool:
        """Persist one idempotent journal state before removing legacy tags."""
        bookmark_id = int(bookmark["_id"])
        now = _utc_now()
        decision = (
            {
                "bookmark_id": bookmark_id,
                "outcome": outcome,
                "destination": destination,
                "text_evidence": [],
                "visual_evidence": [],
                "summary": "Imported from legacy Raindrop lifecycle tags.",
            }
            if outcome is not None
            else None
        )
        with self._connect() as connection:
            latest = connection.execute(
                f"""
                SELECT current_phase, outcome, destination FROM attempts
                WHERE bookmark_id = ?
                  AND mode IN ({_MUTATING_ATTEMPT_MODES_SQL})
                ORDER BY started_at DESC, attempt_id DESC
                LIMIT 1
                """,
                (bookmark_id,),
            ).fetchone()
            if (
                latest is not None
                and latest["current_phase"] == phase
                and latest["outcome"] == outcome
                and latest["destination"] == destination
            ):
                return False
            attempt_id = f"legacy-tag-migration:{bookmark_id}:{uuid.uuid4()}"
            connection.execute(
                """
                INSERT INTO attempts(
                    attempt_id, bookmark_id, started_at, ended_at, current_phase,
                    outcome, destination, runner_version, mode,
                    bookmark_snapshot_json, decision_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    bookmark_id,
                    now,
                    now if phase == "applied" else None,
                    phase,
                    outcome,
                    destination,
                    "legacy-tag-migration-v1",
                    "legacy-tag-migration",
                    _json(_bookmark_snapshot(bookmark)),
                    _json(decision) if decision is not None else None,
                ),
            )
            self._append_event(
                connection,
                attempt_id,
                phase,
                {
                    "source": "raindrop_lifecycle_tags",
                    "tags": [
                        str(tag) for tag in bookmark.get("tags", [])
                        if is_remote_lifecycle_tag(tag)
                    ],
                },
            )
        return True

    def status(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                {_LATEST_ATTEMPTS_CTE}
                SELECT current_phase, COUNT(*) AS count
                FROM latest_attempts WHERE bookmark_rank = 1
                GROUP BY current_phase ORDER BY current_phase
                """
            ).fetchall()
        return {str(row["current_phase"]): int(row["count"]) for row in rows}

    def bookmark_ids(self) -> set[int]:
        """Return every Raindrop represented by the Run Journal."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT bookmark_id FROM attempts"
            ).fetchall()
        return {int(row["bookmark_id"]) for row in rows}

    @staticmethod
    def _trace(
        connection: sqlite3.Connection, row: sqlite3.Row | None
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        attempt_id = row["attempt_id"]
        events = connection.execute(
            "SELECT * FROM events WHERE attempt_id = ? ORDER BY sequence",
            (attempt_id,),
        ).fetchall()
        evidence = connection.execute(
            "SELECT * FROM evidence WHERE attempt_id = ? ORDER BY evidence_id",
            (attempt_id,),
        ).fetchall()
        actions = connection.execute(
            "SELECT * FROM actions WHERE attempt_id = ? ORDER BY action_id",
            (attempt_id,),
        ).fetchall()
        return {
            "attempt": _decode_row(row),
            "events": [_decode_row(item) for item in events],
            "evidence": [_decode_row(item) for item in evidence],
            "actions": [_decode_row(item) for item in actions],
        }

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        attempt_id: str,
        phase: str,
        payload: dict[str, Any],
        *,
        duration_ms: float | None = None,
    ) -> None:
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO events(
                attempt_id, sequence, phase, recorded_at, duration_ms, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (attempt_id, sequence, phase, _utc_now(), duration_ms, _json(payload)),
        )

    @staticmethod
    def _insert_evidence(
        connection: sqlite3.Connection,
        attempt_id: str,
        evidence: TextEvidence | VisualEvidence,
    ) -> None:
        if isinstance(evidence, TextEvidence):
            source_kind = evidence.kind
            status = "matched" if evidence.destination else "no_match"
            strength = evidence.strength
        else:
            source_kind = evidence.method
            status = evidence.status
            strength = None
        connection.execute(
            """
            INSERT INTO evidence(
                attempt_id, source_kind, destination, status, strength,
                explanation, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                source_kind,
                evidence.destination,
                status,
                strength,
                evidence.explanation,
                _json(evidence.to_dict()),
            ),
        )


def _bookmark_snapshot(bookmark: dict[str, Any]) -> dict[str, Any]:
    """Keep a bounded, non-secret snapshot useful for later explanation."""
    snapshot = {
        key: bookmark.get(key)
        for key in (
            "_id",
            "title",
            "excerpt",
            "link",
            "collection",
            "tags",
            "type",
        )
        if key in bookmark
    }
    cover = bookmark.get("cover")
    if cover:
        snapshot["cover_fingerprint"] = hashlib.sha256(
            str(cover).encode("utf-8")
        ).hexdigest()
    return snapshot


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _duration_ms(started_at: str, ended_at: str | None) -> float | None:
    if ended_at is None:
        return None
    return round(
        (datetime.fromisoformat(ended_at) - datetime.fromisoformat(started_at)).total_seconds()
        * 1000,
        1,
    )


def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    for key in tuple(result):
        if key.endswith("_json") and result[key] is not None:
            result[key.removesuffix("_json")] = json.loads(result.pop(key))
    return result
