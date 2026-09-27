import json
import threading
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from src.cover_cache import SQLiteCoverCache
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
        {
            "_id": 1864496693,
            "title": "Pixiv illustration",
            "link": "https://example.test/art",
            "cover": "https://rdl.ink/pixiv.webp",
        },
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

    cover_cache = SQLiteCoverCache(tmp_path / "cover-cache.sqlite")
    cover_cache.record({"_id": 1864496693, "cover": "https://rdl.ink/pixiv.webp"})
    server = create_server(
        path,
        host="127.0.0.1",
        port=0,
        cover_cache=cover_cache,
    )
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
        assert "img-src 'self' blob: https:" in response.headers["Content-Security-Policy"]
    assert "Raindrop Sorter" in page
    assert "Raindrop Journal" not in page
    assert 'class="stats"' not in page
    assert 'aria-label="Refresh dashboard"' in page
    assert 'aria-label="Show attempt details"' in page
    assert 'aria-label="Image card layout"' in page
    assert 'aria-label="Table layout"' in page
    assert 'aria-label="Assign selected Raindrops"' in page
    assert 'aria-label="Delete selected records"' in page
    assert 'role="combobox"' in page
    assert 'placeholder="Search Art, Goods, Image, Post, or Video destinations…"' in page
    assert 'role="listbox"' in page
    assert "renderBatchDestinationResults" in page
    assert "function syncBatchControls()" in page
    assert "renderBatchDestinationResults();\n  syncBatchControls();" in page
    assert "closeBatchDestinationResults();\n  syncBatchControls();" in page
    assert "batchDestinationCollections" in page
    assert "batchDestinationWantsOpen" in page
    assert "option.tabIndex = -1" in page
    assert "aria-activedescendant" in page
    assert '<select class="control" id="batch-destination"' not in page
    assert 'aria-label="Process all Unsorted Raindrops"' in page
    assert 'aria-label="Stop processing Unsorted Raindrops"' in page
    assert "https://app.raindrop.io/my/0/item/" in page
    assert "encodeURIComponent(bookmarkId)}/edit" in page
    assert "setInterval(refreshSorterStatus, 1000)" in page
    assert "/api/attempts/resolve-batch" in page
    assert "/api/attempts/delete-batch" in page
    assert "/api/sorter/${action}" in page
    assert "Process every actionable Raindrop in Unsorted now?" in page
    assert "Start the automatic sorter?" in page
    assert "This does not delete anything from Raindrop.io." in page
    assert "updateOutcomeOptions" in page
    assert "All outcomes ·" in page
    assert "Search or use filters" in page
    assert 'id="filter-toggle"' in page
    assert 'id="filter-panel"' in page
    assert 'id="mode"' in page
    assert 'id="visual-labels"' in page
    assert 'id="title-filter"' in page
    assert 'id="link-filter"' in page
    assert 'id="date-filter" type="date"' in page
    assert "function parseFilterQuery(" in page
    assert "function syncQueryFromFilterControls(" in page
    assert "label:" in page
    assert "bookmark-preview" in page
    assert "MAX_CONCURRENT_PREVIEW_FETCHES = 2" in page
    assert "fetchPreviewBlob(bookmarkId)" in page
    assert "image.dataset.bookmarkId" in page
    assert "image.dataset.coverUrl" in page
    assert "image.referrerPolicy = 'no-referrer'" in page
    assert "image.onerror = () => loadFallbackPreview(image)" in page
    assert "image.dataset.fallbackStarted" in page
    assert "previewImage(attempt.bookmark_id, attempt.title, 'attempt-cover', attempt.cover)" in page
    assert "const attemptElementCache = new Map()" in page
    assert "function reconcileChildren(" in page
    assert "attemptList.replaceChildren()" not in page
    assert "function clearDataCaches()" in page
    assert "function clearPreviewCache()" in page
    assert (
        "clearDataCaches();\n    if (batchMessageGeneration === messageGeneration)"
        in page
    )
    assert "Latest status" in page
    assert "Search Art, Goods, Image, Post, or Video collections" in page
    assert "Move & confirm" in page
    assert 'id="detail-toggle"' in page
    assert 'id="detail-close"' in page
    assert 'id="detail-panel" aria-hidden="true" inert' in page
    assert 'class="attempt-grid"' in page
    assert "attemptTraceCache" in page
    assert "detailSelectionRevision === assignmentRevision" in page
    assert "attempt-footer" in page
    assert "year:'2-digit', month:'2-digit', day:'2-digit'" in page
    assert "startedAt.dateTime = attempt.started_at" in page
    assert "text-overflow:ellipsis" not in page
    assert ".attempt{min-height:" not in page
    assert "align-items:stretch" in page
    assert "overflow:hidden" in page
    assert ".attempt.selected" in page
    assert "selectionAnchorAttemptId" in page
    assert "handleAttemptActivation" in page
    assert "event.shiftKey" in page
    assert "event.ctrlKey || event.metaKey" in page
    assert ".attempt-cover,.table-cover{pointer-events:none}" in page
    assert 'aria-label="Current Raindrop location filter"' in page
    assert 'id="collection-tree"' in page
    assert "/api/library/tree" in page
    assert "sorter-library-expanded-collections" in page
    assert "function renderCollectionTree()" in page
    assert "function collectionFilterPath(group, node)" in page
    assert "`${groupTitle}/${path}`" in page
    assert "function selectLocationCollection" in page
    assert "selectLiveCollection" not in page
    assert 'id="journal-select"' not in page

    overview = _json(f"{base_url}/api/overview")
    assert overview["total_attempts"] == 2
    assert overview["total_bookmarks"] == 1
    assert overview["outcomes"] == {"review": 1}
    assert overview["attempt_outcomes"] == {"pending": 1, "review": 1}

    health = _json(f"{base_url}/api/health")
    assert health == {
        "status": "ok",
        "journal": True,
        "image_previews": False,
        "review_actions": False,
        "sorter": {
            "available": False,
            "state": "unavailable",
            "automatic": False,
            "error": "RAINDROP_TOKEN is required for sorter controls",
        },
    }
    with pytest.raises(HTTPError) as not_ready:
        urlopen(f"{base_url}/api/ready")
    assert not_ready.value.code == 503


def test_dashboard_filters_attempts_and_returns_exact_trace(dashboard):
    base_url, attempt_id = dashboard
    attempts = _json(f"{base_url}/api/attempts?outcome=review&q=pixiv")
    assert attempts["items"][0]["bookmark_id"] == 1864496693
    assert attempts["items"][0]["cover"] == "https://rdl.ink/pixiv.webp"
    assert _json(f"{base_url}/api/attempts?outcome=confirmed")["items"] == []
    processed_on = attempts["items"][0]["started_at"][:10]
    structured = _json(
        f"{base_url}/api/attempts?mode=dry-run&title=illustration"
        f"&link=example.test&processed_on={processed_on}&utc_offset_minutes=0"
    )
    assert structured["items"][0]["bookmark_id"] == 1864496693

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

    first_page = _json(f"{base_url}/api/attempts?latest=0&limit=1")
    second_page = _json(f"{base_url}/api/attempts?" + urlencode({
        "latest": 0,
        "limit": 1,
        "before_started_at": first_page["next_before_started_at"],
        "before_attempt_id": first_page["next_before_attempt_id"],
        "snapshot_started_at": first_page["snapshot_started_at"],
        "snapshot_attempt_id": first_page["snapshot_attempt_id"],
    }))
    assert first_page["count"] == 1
    assert first_page["has_more"] is True
    assert first_page["snapshot_started_at"]
    assert first_page["snapshot_attempt_id"]
    assert first_page["items"][0]["title"] == "Pixiv illustration"
    assert second_page["count"] == 1
    assert second_page["has_more"] is False
    assert second_page["items"][0]["title"] == "Earlier Pixiv check"


def test_dashboard_reports_bad_limits_and_missing_attempts(dashboard):
    base_url, _ = dashboard
    with pytest.raises(HTTPError) as bad_limit:
        urlopen(f"{base_url}/api/attempts?limit=zero")
    assert bad_limit.value.code == 400
    with pytest.raises(HTTPError) as incomplete_cursor:
        urlopen(f"{base_url}/api/attempts?before_attempt_id=missing-start")
    assert incomplete_cursor.value.code == 400

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


def test_dashboard_exposes_live_collection_tree_and_bookmark_pages(tmp_path):
    class FakeClient:
        def get_collections(self):
            return [
                {"_id": 10, "title": "Art", "count": 2},
                {"_id": 11, "title": "Miku", "count": 1, "parent": {"$id": 10}},
            ]

        def get_collection_groups(self):
            return [{"title": "Creative", "sort": 0, "collections": [10]}]

        def get_collection(self, collection_id):
            return {"_id": collection_id, "title": {0: "All", -1: "Unsorted", -99: "Trash"}[collection_id], "count": 3}

        def get_collection_count(self, collection_id):
            return 3

        def get_raindrops(self, collection_id, page=0, perpage=50, search=None, sort=None):
            assert (collection_id, page, perpage, search, sort) == (
                11,
                1,
                25,
                '#tag "exact phrase" / 日本語',
                "title",
            )
            return [{"_id": 501, "title": "Live item", "collection": {"$id": 11}}], True

        def get_raindrop(self, bookmark_id):
            return {"_id": bookmark_id, "title": str(bookmark_id), "tags": []}

        def update_raindrop(self, bookmark_id, collection_id=None, tags=None):
            return {"result": True}

    path = tmp_path / "journal.sqlite"
    SQLiteRunJournal(path)
    server = create_server(
        path,
        host="127.0.0.1",
        port=0,
        raindrop_client=FakeClient(),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        tree = _json(f"{base_url}/api/library/tree")
        assert tree["groups"][1]["collections"][0]["children"][0]["path"] == "Art/Miku"

        page = _json(
            f"{base_url}/api/library/bookmarks?collection_id=11&page=1&per_page=25"
            "&q=%23tag%20%22exact%20phrase%22%20%2F%20%E6%97%A5%E6%9C%AC%E8%AA%9E"
            "&sort=title"
        )
        assert page["items"][0]["title"] == "Live item"
        assert page["next_page"] == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_live_library_endpoint_rejects_invalid_page_requests(tmp_path):
    class FakeClient:
        def get_collections(self):
            return []

        def get_collection_groups(self):
            return []

        def get_collection(self, collection_id):
            return {"_id": collection_id, "count": 0}

        def get_raindrops(self, collection_id, page=0, perpage=50, search=None):
            return [], False

    path = tmp_path / "journal.sqlite"
    SQLiteRunJournal(path)
    server = create_server(path, host="127.0.0.1", port=0, raindrop_client=FakeClient())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        with pytest.raises(HTTPError) as missing_collection:
            urlopen(f"{base_url}/api/library/bookmarks")
        assert missing_collection.value.code == 400

        with pytest.raises(HTTPError) as bad_page_size:
            urlopen(f"{base_url}/api/library/bookmarks?collection_id=-1&per_page=101")
        assert bad_page_size.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_live_library_endpoint_translates_upstream_tree_failure(tmp_path):
    class FailingClient:
        def get_collections(self):
            raise TimeoutError("token and upstream details stay behind the boundary")

        def get_collection_groups(self):
            return []

    path = tmp_path / "journal.sqlite"
    SQLiteRunJournal(path)
    server = create_server(path, host="127.0.0.1", port=0, raindrop_client=FailingClient())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HTTPError) as upstream:
            urlopen(f"http://127.0.0.1:{server.server_port}/api/library/tree")
        assert upstream.value.code == 502
        assert json.load(upstream.value) == {
            "error": "could not load live collection tree: TimeoutError"
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_live_library_endpoint_gives_rate_limit_guidance(tmp_path):
    class RateLimitedClient:
        def get_raindrops(self, collection_id, page=0, perpage=50, search=None):
            error = RuntimeError("upstream details stay private")
            error.response = SimpleNamespace(status_code=429)
            raise error

    path = tmp_path / "journal.sqlite"
    SQLiteRunJournal(path)
    server = create_server(
        path,
        host="127.0.0.1",
        port=0,
        raindrop_client=RateLimitedClient(),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HTTPError) as upstream:
            urlopen(
                f"http://127.0.0.1:{server.server_port}/api/library/bookmarks"
                "?collection_id=0"
            )
        assert upstream.value.code == 429
        assert json.load(upstream.value) == {
            "error": "Raindrop is rate-limiting requests. Wait about a minute, then retry."
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_dashboard_exposes_assignment_picker_and_resolves_attempt(tmp_path):
    class FakeClient:
        def __init__(self):
            self.updates = []
            self.membership_reads = 0

        def get_collections(self):
            return [
                {"_id": 10, "title": "TOUHOU", "parent": None},
                {"_id": 20, "title": "Music", "parent": None},
                {"_id": 30, "title": "REFERENCE", "parent": None},
                {"_id": 40, "title": "CLIPS", "parent": None},
                {"_id": 50, "title": "CURSOR", "parent": None},
                {"_id": 60, "title": "NEWS", "parent": None},
            ]

        def get_collection_groups(self):
            return [
                {"title": "Art", "collections": [10]},
                {"title": "Music", "collections": [20]},
                {"title": "Image", "collections": [30]},
                {"title": "Video", "collections": [40]},
                {"title": "Goods", "collections": [50]},
                {"title": "Post", "collections": [60]},
            ]

        def get_raindrop(self, bookmark_id):
            return {"_id": bookmark_id, "title": "Conflict", "tags": []}

        def get_raindrops(
            self, collection_id, page=0, perpage=50, search=None, sort=None
        ):
            self.membership_reads += 1
            return [], False

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
            {"collection_id": 10, "path": "Art/TOUHOU"},
            {"collection_id": 50, "path": "Goods/CURSOR"},
            {"collection_id": 30, "path": "Image/REFERENCE"},
            {"collection_id": 60, "path": "Post/NEWS"},
            {"collection_id": 40, "path": "Video/CLIPS"},
        ]
        with pytest.raises(HTTPError) as cross_origin:
            _post_json(
                f"{base_url}/api/attempts/{attempt.attempt_id}/resolve",
                {"collection_id": 10, "selection_source": "text"},
                headers={"Origin": "https://attacker.example"},
            )
        assert cross_origin.value.code == 400
        assert client.updates == []
        assert _json(
            f"{base_url}/api/attempts?latest=1&collection_id=10"
        )["items"] == []
        resolved = _post_json(
            f"{base_url}/api/attempts/{attempt.attempt_id}/resolve",
            {"collection_id": 10, "selection_source": "text"},
        )
        assert resolved["outcome"] == "confirmed"
        assert resolved["selection_source"] == "text"
        assert client.updates[0][0:2] == (123, 10)
        moved = _json(
            f"{base_url}/api/attempts?latest=1&outcome=confirmed&collection_id=10"
        )
        assert moved["items"][0]["bookmark_id"] == 123
        assert client.membership_reads == 1

        with pytest.raises(HTTPError) as missing_confirmation:
            _post_json(
                f"{base_url}/api/attempts/{resolved['attempt_id']}/resolve",
                {"collection_id": 30, "selection_source": "custom"},
            )
        assert missing_confirmation.value.code == 409
        corrected = _post_json(
            f"{base_url}/api/attempts/{resolved['attempt_id']}/resolve",
            {
                "collection_id": 30,
                "selection_source": "custom",
                "confirmed_correction": True,
            },
        )
        assert corrected["destination"] == "Image/REFERENCE"
        assert client.updates[-1][0:2] == (123, 30)
        first_confirmation = journal.explain_attempt(resolved["attempt_id"])
        assert first_confirmation["attempt"]["destination"] == "Art/TOUHOU"
        assert journal.explain(123)["attempt"]["destination"] == "Image/REFERENCE"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_dashboard_failed_resolution_returns_authoritative_retry_trace(tmp_path):
    class FakeClient:
        def get_collections(self):
            return [{"_id": 10, "title": "TOUHOU", "parent": None}]

        def get_collection_groups(self):
            return [{"title": "Art", "collections": [10]}]

        def get_raindrop(self, bookmark_id):
            return {"_id": bookmark_id, "title": "Conflict", "tags": []}

        def update_raindrop(self, bookmark_id, collection_id=None, tags=None):
            raise RuntimeError("unavailable")

    path = tmp_path / "journal.sqlite"
    journal = SQLiteRunJournal(path)
    attempt = journal.start_attempt({"_id": 123, "title": "Conflict"}, mode="dry-run")
    journal.record_decision(
        attempt,
        RouteDecision(
            bookmark_id=123,
            outcome=RouteOutcome.REVIEW,
            destination=None,
            text_evidence=(),
            visual_evidence=(),
            summary="Needs review.",
        ),
    )
    journal.complete(attempt, phase="dry_run_completed")
    server = create_server(
        path, host="127.0.0.1", port=0, raindrop_client=FakeClient()
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HTTPError) as failed:
            _post_json(
                f"http://127.0.0.1:{server.server_port}"
                f"/api/attempts/{attempt.attempt_id}/resolve",
                {"collection_id": 10, "selection_source": "custom"},
            )

        assert failed.value.code == 502
        payload = json.load(failed.value)
        assert payload["error"] == "Raindrop update failed: RuntimeError"
        assert payload["retry_attempt_id"] != attempt.attempt_id
        assert payload["retry_attempt"]["attempt_id"] == payload["retry_attempt_id"]
        assert payload["retry_attempt"]["mode"] == "manual-review"
        assert payload["retry_attempt"]["current_phase"] == "failed"
        assert payload["retry_attempt"]["title"] == "Conflict"
        assert payload["retry_attempt"]["duration_ms"] is not None
        assert (
            payload["retry_trace"]["attempt"]["attempt_id"]
            == payload["retry_attempt_id"]
        )
        assert payload["retry_trace"]["attempt"]["bookmark_snapshot"]["title"] == (
            "Conflict"
        )
        assert payload["retry_trace"]["events"][-1]["phase"] == "failed"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_dashboard_batch_resolves_selected_attempts(tmp_path):
    class FakeClient:
        def __init__(self):
            self.updates = []
            self.collection_reads = 0
            self.group_reads = 0
            self.http_requests = 0
            self.simulated_network_seconds = 0

        def record_requests(self, count=1):
            self.http_requests += count
            self.simulated_network_seconds += count * 0.75

        def get_collections(self):
            self.collection_reads += 1
            # RaindropClient fetches roots and child collections separately.
            self.record_requests(2)
            return [{"_id": 10, "title": "TOUHOU", "parent": None}]

        def get_collection_groups(self):
            self.group_reads += 1
            self.record_requests()
            return [{"title": "Art", "collections": [10]}]

        def get_raindrop(self, bookmark_id):
            self.record_requests()
            return {"_id": bookmark_id, "title": str(bookmark_id), "tags": []}

        def update_raindrop(self, bookmark_id, collection_id=None, tags=None):
            self.record_requests()
            self.updates.append((bookmark_id, collection_id, tags))
            return {"result": True}

    path = tmp_path / "journal.sqlite"
    journal = SQLiteRunJournal(path)
    attempt_ids = []
    for bookmark_id in (101, 102, 103, 104):
        attempt = journal.start_attempt(
            {"_id": bookmark_id, "title": str(bookmark_id)}, mode="dry-run"
        )
        journal.record_decision(
            attempt,
            RouteDecision(
                bookmark_id=bookmark_id,
                outcome=RouteOutcome.REVIEW,
                destination=None,
                text_evidence=(),
                visual_evidence=(),
                summary="Needs review.",
            ),
        )
        journal.complete(attempt, phase="dry_run_completed")
        attempt_ids.append(attempt.attempt_id)

    client = FakeClient()
    server = create_server(path, host="127.0.0.1", port=0, raindrop_client=client)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = _post_json(
            f"http://127.0.0.1:{server.server_port}/api/attempts/resolve-batch",
            {"attempt_ids": attempt_ids, "collection_id": 10},
        )
        assert result["resolved"] == 4
        assert result["failed"] == 0
        assert [update[:2] for update in client.updates] == [
            (101, 10),
            (102, 10),
            (103, 10),
            (104, 10),
        ]
        assert client.collection_reads == 1
        assert client.group_reads == 1
        assert client.http_requests == 11
        assert client.simulated_network_seconds <= 10
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_dashboard_batch_resolution_reports_partial_failure(tmp_path):
    class FakeClient:
        def get_collections(self):
            return [{"_id": 10, "title": "TOUHOU", "parent": None}]

        def get_collection_groups(self):
            return [{"title": "Art", "collections": [10]}]

        def get_raindrop(self, bookmark_id):
            return {"_id": bookmark_id, "title": str(bookmark_id), "tags": []}

        def update_raindrop(self, bookmark_id, collection_id=None, tags=None):
            if bookmark_id == 102:
                raise RuntimeError("unavailable")
            return {"result": True}

    path = tmp_path / "journal.sqlite"
    journal = SQLiteRunJournal(path)
    attempt_ids = []
    for bookmark_id in (101, 102):
        attempt = journal.start_attempt({"_id": bookmark_id}, mode="dry-run")
        journal.record_decision(
            attempt,
            RouteDecision(
                bookmark_id=bookmark_id,
                outcome=RouteOutcome.REVIEW,
                destination=None,
                text_evidence=(),
                visual_evidence=(),
                summary="Needs review.",
            ),
        )
        journal.complete(attempt, phase="dry_run_completed")
        attempt_ids.append(attempt.attempt_id)

    server = create_server(
        path, host="127.0.0.1", port=0, raindrop_client=FakeClient()
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = _post_json(
            f"http://127.0.0.1:{server.server_port}/api/attempts/resolve-batch",
            {"attempt_ids": attempt_ids, "collection_id": 10},
        )
        assert result["status"] == "partial"
        assert result["resolved"] == 1
        assert result["failed"] == 1
        assert result["errors"][0]["attempt_id"] == attempt_ids[1]
        assert result["errors"][0]["retry_attempt_id"] != attempt_ids[1]
        assert result["errors"][0]["retry_attempt"]["attempt_id"] == result["errors"][0][
            "retry_attempt_id"
        ]
        assert result["errors"][0]["retry_attempt"]["mode"] == "manual-review"
        assert result["errors"][0]["retry_attempt"]["current_phase"] == "failed"
        assert result["errors"][0]["retry_attempt"]["outcome"] is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_dashboard_marks_selected_records_deleted_without_mutating_raindrop(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = SQLiteRunJournal(path)
    attempt_ids = []
    for bookmark_id in (101, 102):
        attempt = journal.start_attempt(
            {"_id": bookmark_id, "title": f"Deleted {bookmark_id}"},
            mode="dry-run",
        )
        journal.record_decision(
            attempt,
            RouteDecision(
                bookmark_id=bookmark_id,
                outcome=RouteOutcome.REVIEW,
                destination=None,
                text_evidence=(),
                visual_evidence=(),
                summary="Needs review.",
            ),
        )
        journal.complete(attempt, phase="dry_run_completed")
        attempt_ids.append(attempt.attempt_id)

    server = create_server(path, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = _post_json(
            f"http://127.0.0.1:{server.server_port}/api/attempts/delete-batch",
            {"attempt_ids": attempt_ids},
        )

        assert result == {"status": "ok", "deleted": 2, "failed": 0, "errors": []}
        assert journal.automatic_processing_exclusions() == {101, 102}
        for bookmark_id, source_attempt_id in zip((101, 102), attempt_ids):
            trace = journal.explain(bookmark_id)
            assert trace["attempt"]["outcome"] == "deleted"
            assert trace["attempt"]["current_phase"] == "applied"
            assert trace["attempt"]["mode"] == "manual-delete"
            assert trace["attempt"]["decision"]["summary"] == (
                "Marked deleted because the Raindrop no longer exists."
            )
            assert trace["actions"][0]["action_kind"] == "mark_raindrop_deleted"
            assert trace["actions"][0]["request_count"] == 0
            assert trace["actions"][0]["payload"]["source_attempt_id"] == (
                source_attempt_id
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_dashboard_exposes_sorter_controls(tmp_path):
    class FakeController:
        def __init__(self):
            self.calls = []

        def status(self):
            return {"available": True, "state": "paused", "automatic": False}

        def process_all(self):
            self.calls.append("process-all")
            return {"available": True, "state": "running", "automatic": False}

        def start_automatic(self):
            self.calls.append("start")
            return {"available": True, "state": "running", "automatic": True}

        def stop_processing_all(self):
            self.calls.append("stop")
            return {"available": True, "state": "stopping", "automatic": False}

        def pause_automatic(self):
            self.calls.append("pause")
            return {"available": True, "state": "paused", "automatic": False}

        def close(self):
            self.calls.append("close")

    path = tmp_path / "journal.sqlite"
    SQLiteRunJournal(path)
    controller = FakeController()
    server = create_server(
        path, host="127.0.0.1", port=0, sorter_controller=controller
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        assert _json(f"{base_url}/api/ready")["status"] == "ready"
        assert _json(f"{base_url}/api/sorter/status")["state"] == "paused"
        assert _post_json(f"{base_url}/api/sorter/process-all", {})["state"] == "running"
        assert _post_json(f"{base_url}/api/sorter/stop", {})["state"] == "stopping"
        assert _post_json(f"{base_url}/api/sorter/start", {})["automatic"] is True
        assert _post_json(f"{base_url}/api/sorter/pause", {})["state"] == "paused"
        assert controller.calls == ["process-all", "stop", "start", "pause"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert controller.calls[-1] == "close"


def test_dashboard_reports_why_sorter_controls_are_unavailable(tmp_path):
    path = tmp_path / "journal.sqlite"
    SQLiteRunJournal(path)
    server = create_server(
        path,
        host="127.0.0.1",
        port=0,
        sorter_unavailable_reason="Local index is incomplete; run bootstrap first.",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status = _json(f"http://127.0.0.1:{server.server_port}/api/sorter/status")
        assert status == {
            "available": False,
            "state": "unavailable",
            "automatic": False,
            "error": "Local index is incomplete; run bootstrap first.",
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_unavailable_sorter_action_reports_the_actual_preflight_error(tmp_path):
    path = tmp_path / "journal.sqlite"
    SQLiteRunJournal(path)
    reason = "Local index is incomplete; run bootstrap first."
    server = create_server(
        path,
        host="127.0.0.1",
        port=0,
        sorter_unavailable_reason=reason,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HTTPError) as unavailable:
            _post_json(f"http://127.0.0.1:{server.server_port}/api/sorter/start", {})
        assert unavailable.value.code == 503
        assert json.load(unavailable.value)["error"] == reason
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
