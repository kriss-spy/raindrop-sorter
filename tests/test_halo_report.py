import json
import sqlite3
from pathlib import Path

from scripts.generate_halo_report import load_halo_records, render_report


def _journal(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE attempts (
                attempt_id TEXT PRIMARY KEY,
                bookmark_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                current_phase TEXT NOT NULL,
                outcome TEXT,
                destination TEXT,
                bookmark_snapshot_json TEXT NOT NULL,
                decision_json TEXT
            );
            CREATE TABLE evidence (
                evidence_id INTEGER PRIMARY KEY,
                attempt_id TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                details_json TEXT NOT NULL
            );
            """
        )


def _attempt(
    connection: sqlite3.Connection,
    *,
    attempt_id: str,
    bookmark_id: int,
    started_at: str,
    labels: list[str],
    title: str,
    link: str | None = None,
) -> None:
    visual = {
        "status": "pass",
        "destination": "Art/GAMES/BA",
        "candidates": ["Art/GAMES/BA"],
        "winner": "Art/GAMES/BA",
        "runner_up": "Art/TOUHOU",
        "similarity": 0.88,
        "runner_up_similarity": 0.72,
        "margin": 0.16,
        "labels": labels,
        "explanation": "Visual evidence.",
    }
    snapshot = {
        "_id": bookmark_id,
        "title": title,
        "excerpt": "excerpt",
        "link": link or f"https://example.test/{bookmark_id}",
    }
    decision = {
        "summary": "Moved provisionally.",
        "text_evidence": [],
        "visual_evidence": [visual],
    }
    connection.execute(
        """
        INSERT INTO attempts VALUES (?, ?, ?, 'applied', 'provisional',
                                     'Art/GAMES/BA', ?, ?)
        """,
        (
            attempt_id,
            bookmark_id,
            started_at,
            json.dumps(snapshot),
            json.dumps(decision),
        ),
    )
    connection.execute(
        "INSERT INTO evidence(attempt_id, source_kind, details_json) VALUES (?, ?, ?)",
        (attempt_id, "wd14+visual_exemplar", json.dumps(visual)),
    )


def test_load_halo_records_uses_only_each_bookmarks_latest_attempt(tmp_path: Path) -> None:
    journal = tmp_path / "journal.sqlite"
    covers = tmp_path / "covers.sqlite"
    _journal(journal)
    with sqlite3.connect(journal) as connection:
        _attempt(
            connection,
            attempt_id="old-halo",
            bookmark_id=1,
            started_at="2026-01-01T00:00:00+00:00",
            labels=["halo"],
            title="Old halo",
        )
        _attempt(
            connection,
            attempt_id="new-no-halo",
            bookmark_id=1,
            started_at="2026-01-02T00:00:00+00:00",
            labels=["1girl"],
            title="New no halo",
        )
        _attempt(
            connection,
            attempt_id="new-halo",
            bookmark_id=2,
            started_at="2026-01-03T00:00:00+00:00",
            labels=["1girl", "halo"],
            title="<Halo & card>",
        )
        _attempt(
            connection,
            attempt_id="a-halo",
            bookmark_id=3,
            started_at="2026-01-04T00:00:00+00:00",
            labels=["halo"],
            title="Same-time halo",
        )
        _attempt(
            connection,
            attempt_id="z-no-halo",
            bookmark_id=3,
            started_at="2026-01-04T00:00:00+00:00",
            labels=["1girl"],
            title="Same-time no halo",
        )
    with sqlite3.connect(covers) as connection:
        connection.execute(
            "CREATE TABLE bookmark_covers(bookmark_id INTEGER PRIMARY KEY, cover_url TEXT)"
        )
        connection.execute(
            "INSERT INTO bookmark_covers VALUES (2, 'https://cdn.test/2.webp')"
        )

    records = load_halo_records(journal, covers)

    assert [record["bookmark_id"] for record in records] == [2]
    assert records[0]["cover"] == "https://cdn.test/2.webp"
    assert records[0]["visual"]["destination"] == "Art/GAMES/BA"


def test_render_report_uses_viewport_aware_image_loading(tmp_path: Path) -> None:
    journal = tmp_path / "journal.sqlite"
    covers = tmp_path / "covers.sqlite"
    _journal(journal)
    with sqlite3.connect(journal) as connection:
        _attempt(
            connection,
            attempt_id="halo",
            bookmark_id=2,
            started_at="2026-01-03T00:00:00+00:00",
            labels=["1girl", "halo"],
            title="<Halo & card>",
        )
    with sqlite3.connect(covers) as connection:
        connection.execute(
            "CREATE TABLE bookmark_covers(bookmark_id INTEGER PRIMARY KEY, cover_url TEXT)"
        )
        connection.execute(
            "INSERT INTO bookmark_covers VALUES (2, 'https://cdn.test/2.webp')"
        )

    page = render_report(load_halo_records(journal, covers))

    assert 'data-src="https://cdn.test/2.webp"' in page
    assert ' src="https://cdn.test/2.webp"' not in page
    assert 'loading="lazy"' in page
    assert 'decoding="async"' in page
    assert 'fetchpriority="low"' in page
    assert "IntersectionObserver" in page
    assert "rootMargin: '900px 0px'" in page
    assert "observer.disconnect()" in page
    assert "observeImages(true)" in page
    assert "&lt;Halo &amp; card&gt;" in page


def test_render_report_rejects_non_http_source_links(tmp_path: Path) -> None:
    journal = tmp_path / "journal.sqlite"
    covers = tmp_path / "covers.sqlite"
    _journal(journal)
    with sqlite3.connect(journal) as connection:
        _attempt(
            connection,
            attempt_id="halo",
            bookmark_id=2,
            started_at="2026-01-03T00:00:00+00:00",
            labels=["halo"],
            title="Unsafe link",
            link="javascript:alert(1)",
        )
    with sqlite3.connect(covers) as connection:
        connection.execute(
            "CREATE TABLE bookmark_covers(bookmark_id INTEGER PRIMARY KEY, cover_url TEXT)"
        )

    page = render_report(load_halo_records(journal, covers))

    assert "javascript:alert(1)" not in page
    assert "No source link" in page
