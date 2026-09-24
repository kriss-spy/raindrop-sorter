"""Append-only SQLite journal for local sorter attempts."""

from __future__ import annotations

import json
import hashlib
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from src.routing import RouteDecision, RouteEvidence


SCHEMA_VERSION = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


class SQLiteRunJournal:
    """Durable local implementation of the revised ``RunJournal`` seam."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
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
            connection.execute(
                "INSERT OR IGNORE INTO metadata(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )

    def start_attempt(
        self,
        bookmark: dict[str, Any],
        *,
        mode: str,
        pinned_index_version: str | None = None,
        runner_version: str | None = None,
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
                ORDER BY started_at DESC LIMIT 1
                """,
                (bookmark_id,),
            ).fetchone()
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

    def recent(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT attempt_id, bookmark_id, started_at, ended_at, current_phase,
                       outcome, destination, mode
                FROM attempts ORDER BY started_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def status(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                WITH latest AS (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY bookmark_id
                        ORDER BY started_at DESC, attempt_id DESC
                    ) AS rank
                    FROM attempts
                )
                SELECT current_phase, COUNT(*) AS count
                FROM latest WHERE rank = 1
                GROUP BY current_phase ORDER BY current_phase
                """
            ).fetchall()
        return {str(row["current_phase"]): int(row["count"]) for row in rows}

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
        evidence: RouteEvidence,
    ) -> None:
        connection.execute(
            """
            INSERT INTO evidence(
                attempt_id, source_kind, destination, status, strength,
                explanation, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                evidence.kind.value,
                evidence.destination,
                evidence.status,
                evidence.strength,
                evidence.explanation,
                _json(evidence.details),
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


def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    for key in tuple(result):
        if key.endswith("_json") and result[key] is not None:
            result[key.removesuffix("_json")] = json.loads(result.pop(key))
    return result
