import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

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


def _post_json(url, payload, headers=None):
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urlopen(request) as response:
        return json.load(response)


def test_dashboard_serves_browser_app_and_overview(dashboard):
    base_url, _ = dashboard
    with urlopen(base_url) as response:
        page = response.read().decode()
        assert "img-src 'self' blob:" in response.headers["Content-Security-Policy"]
    assert "Raindrop Journal" in page
    assert "Search bookmarks" in page
    assert "bookmark-preview" in page
    assert "Latest status" in page
    assert "Search Art collections" in page
    assert "Move & confirm" in page
    assert 'id="detail-toggle"' in page
    assert 'id="detail-close"' in page
    assert 'id="detail-panel" aria-hidden="true" inert' in page
    assert 'class="attempt-grid"' in page
    assert "attemptTraceCache" in page
    assert "detailSelectionRevision === reviewSelectionRevision" in page
    assert "attempt-footer" in page
    assert "year:'2-digit', month:'2-digit', day:'2-digit'" in page
    assert "startedAt.dateTime = attempt.started_at" in page
    assert "text-overflow:ellipsis" not in page
    assert ".attempt{min-height:" not in page
    assert "overflow:hidden" in page

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
            assert response.headers["Cache-Control"] == "private, max-age=300"
            assert response.read() == b"preview-bytes"
        with urlopen(
            f"http://127.0.0.1:{server.server_port}/api/bookmarks/1864496693/preview"
        ) as response:
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


def test_dashboard_exposes_art_picker_and_resolves_attempt(tmp_path):
    class FakeClient:
        def __init__(self):
            self.updates = []

        def get_collections(self):
            return [
                {"_id": 10, "title": "TOUHOU", "parent": None},
                {"_id": 20, "title": "Music", "parent": None},
            ]

        def get_collection_groups(self):
            return [
                {"title": "Art", "collections": [10]},
                {"title": "Music", "collections": [20]},
            ]

        def get_raindrop(self, bookmark_id):
            return {"_id": bookmark_id, "title": "Conflict", "tags": []}

        def update_raindrop(self, bookmark_id, collection_id=None, tags=None):
            self.updates.append((bookmark_id, collection_id, tags))
            return {"result": True}

    path = tmp_path / "journal.sqlite"
    journal = SQLiteRunJournal(path)
    attempt = journal.start_attempt({"_id": 123, "title": "Conflict"}, mode="dry-run")
    journal.record_decision(
        attempt,
        RouteDecision(
            bookmark_id=123,
            outcome=RouteOutcome.PROVISIONAL,
            destination="Art/TOUHOU",
            text_evidence=(TextEvidence(
                kind="personal_interest_text",
                destination="Art/TOUHOU",
                strength="strong",
                explanation="Matched Reimu.",
            ),),
            visual_evidence=(),
            summary="Provisional text route.",
        ),
    )
    journal.complete(attempt, phase="dry_run_completed")
    client = FakeClient()
    server = create_server(path, host="127.0.0.1", port=0, raindrop_client=client)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        collections = _json(f"{base_url}/api/review/collections")
        assert collections["items"] == [
            {"collection_id": 10, "path": "Art/TOUHOU"}
        ]
        with pytest.raises(HTTPError) as cross_origin:
            _post_json(
                f"{base_url}/api/attempts/{attempt.attempt_id}/resolve",
                {"collection_id": 10, "selection_source": "text"},
                headers={"Origin": "https://attacker.example"},
            )
        assert cross_origin.value.code == 400
        assert client.updates == []
        resolved = _post_json(
            f"{base_url}/api/attempts/{attempt.attempt_id}/resolve",
            {"collection_id": 10, "selection_source": "text"},
        )
        assert resolved["outcome"] == "confirmed"
        assert resolved["selection_source"] == "text"
        assert client.updates[0][0:2] == (123, 10)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
