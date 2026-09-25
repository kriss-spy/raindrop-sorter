import json
import threading
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from src.journal_web import create_server
from src.routing import RouteDecision, RouteOutcome, TextEvidence
from src.run_journal import SQLiteRunJournal


@pytest.fixture
def dashboard(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = SQLiteRunJournal(path)
    older = journal.start_attempt(
        {"_id": 1864496693, "title": "Earlier Pixiv check"}, mode="dry-run"
    )
    journal.complete(older, phase="dry_run_completed")
    attempt = journal.start_attempt(
        {"_id": 1864496693, "title": "Pixiv illustration", "link": "https://example.test/art"},
        mode="dry-run",
    )
    journal.record_decision(
        attempt,
            RouteDecision(
                bookmark_id=1864496693,
                outcome=RouteOutcome.REVIEW,
                destination=None,
                text_evidence=(TextEvidence(
                    kind="no_match",
                    destination=None,
                    strength=None,
                    explanation="No personal-interest text match was found.",
                ),),
                visual_evidence=(),
                summary="Kept in Unsorted because no destination met the routing policy.",
            ),
    )
    journal.complete(attempt, phase="dry_run_completed")

    server = create_server(path, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", attempt.attempt_id
    server.shutdown()
    server.server_close()
    thread.join()


def _json(url):
    with urlopen(url) as response:
        return json.load(response)


def test_dashboard_serves_browser_app_and_overview(dashboard):
    base_url, _ = dashboard
    with urlopen(base_url) as response:
        page = response.read().decode()
    assert "Raindrop Journal" in page
    assert "Search bookmarks" in page
    assert "bookmark-preview" in page
    assert "Latest status" in page

    overview = _json(f"{base_url}/api/overview")
    assert overview["total_attempts"] == 2
    assert overview["total_bookmarks"] == 1
    assert overview["outcomes"] == {"review": 1}
    assert overview["attempt_outcomes"] == {"pending": 1, "review": 1}


def test_dashboard_filters_attempts_and_returns_exact_trace(dashboard):
    base_url, attempt_id = dashboard
    attempts = _json(f"{base_url}/api/attempts?outcome=review&q=pixiv")
    assert attempts["items"][0]["bookmark_id"] == 1864496693
    assert _json(f"{base_url}/api/attempts?outcome=confirmed")["items"] == []

    trace = _json(f"{base_url}/api/attempts/{attempt_id}")
    assert trace["attempt"]["attempt_id"] == attempt_id
    assert trace["evidence"][0]["source_kind"] == "no_match"


def test_dashboard_can_hide_older_attempts_for_each_bookmark(dashboard):
    base_url, _ = dashboard
    latest = _json(f"{base_url}/api/attempts?latest=1")
    history = _json(f"{base_url}/api/attempts?latest=0")
    assert latest["count"] == 1
    assert latest["items"][0]["title"] == "Pixiv illustration"
    assert history["count"] == 2


def test_dashboard_reports_bad_limits_and_missing_attempts(dashboard):
    base_url, _ = dashboard
    with pytest.raises(HTTPError) as bad_limit:
        urlopen(f"{base_url}/api/attempts?limit=zero")
    assert bad_limit.value.code == 400

    with pytest.raises(HTTPError) as missing:
        urlopen(f"{base_url}/api/attempts/missing")
    assert missing.value.code == 404


def test_dashboard_refuses_to_create_a_missing_journal(tmp_path):
    missing = tmp_path / "missing" / "journal.sqlite"
    with pytest.raises(FileNotFoundError, match="journal does not exist"):
        create_server(missing, host="127.0.0.1", port=0)
    assert not missing.exists()


def test_dashboard_proxies_live_bookmark_preview(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = SQLiteRunJournal(path)
    journal.start_attempt({"_id": 1864496693}, mode="dry-run")
    calls = []

    def load_preview(bookmark_id):
        calls.append(bookmark_id)
        return b"preview-bytes", "image/webp"

    server = create_server(
        path, host="127.0.0.1", port=0, preview_loader=load_preview
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(
            f"http://127.0.0.1:{server.server_port}/api/bookmarks/1864496693/preview"
        ) as response:
            assert response.headers["Content-Type"] == "image/webp"
            assert response.read() == b"preview-bytes"
        assert calls == [1864496693]

        with pytest.raises(HTTPError) as unknown:
            urlopen(
                f"http://127.0.0.1:{server.server_port}/api/bookmarks/999/preview"
            )
        assert unknown.value.code == 404
        assert calls == [1864496693]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_dashboard_rejects_non_loopback_preview_binding(tmp_path):
    path = tmp_path / "journal.sqlite"
    SQLiteRunJournal(path)
    with pytest.raises(ValueError, match="loopback"):
        create_server(
            path,
            host="0.0.0.0",
            port=0,
            preview_loader=lambda bookmark_id: None,
        )
