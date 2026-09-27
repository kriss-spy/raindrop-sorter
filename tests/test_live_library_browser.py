"""Browser-level behavior for the collection-backed destination filter."""

import threading
from types import SimpleNamespace

import pytest

from src.journal_web import create_server
from src.routing import RouteDecision, RouteOutcome, VisualEvidence
from src.run_journal import SQLiteRunJournal

playwright = pytest.importorskip("playwright.sync_api")


class FakeBrowserLibraryClient:
    def __init__(self):
        self.raindrop_fetches = []

    def get_collections(self):
        return [
            {"_id": 10, "title": "Root", "count": 1},
            {"_id": 11, "title": "Child", "count": 1, "parent": {"$id": 10}},
        ]

    def get_collection_groups(self):
        return [{"title": "Library", "sort": 0, "collections": [10]}]

    def get_collection(self, collection_id):
        return {"_id": collection_id, "title": "", "count": 0}

    def get_collection_count(self, collection_id):
        return {0: 5, -1: 3, -99: 1}[collection_id]

    def get_raindrops(self, collection_id, page=0, perpage=50, search=None, sort=None):
        self.raindrop_fetches.append((collection_id, page, search, sort))
        if collection_id == 10:
            return [{"_id": 100}], False
        if collection_id == 11:
            return [{"_id": 110}], False
        return [], False


def _record_attempt(journal, bookmark_id, title, destination, *, labels=()):
    attempt = journal.start_attempt(
        {
            "_id": bookmark_id,
            "title": title,
            "link": f"https://x.com/example/status/{bookmark_id}",
        },
        mode="dry-run",
    )
    journal.record_decision(
        attempt,
        RouteDecision(
            bookmark_id=bookmark_id,
            outcome=RouteOutcome.REVIEW,
            destination=destination,
            text_evidence=(),
            visual_evidence=(
                VisualEvidence(
                    status="inconclusive",
                    destination=None,
                    method="visual_labels",
                    explanation="Labels retained for review.",
                    labels=tuple(labels),
                ),
            ),
            summary=f"Review in {destination}.",
        ),
    )
    journal.complete(attempt, phase="dry_run_completed")


@pytest.fixture
def destination_filter_dashboard(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = SQLiteRunJournal(path)
    # Decisions deliberately disagree with Raindrop's live membership. The tree
    # must filter by current location, not by the recorded routing decision.
    _record_attempt(journal, 100, "Root result", "Library/Root/Child", labels=("halo",))
    _record_attempt(
        journal,
        110,
        "Child result",
        "Library/Root",
        labels=("halo", "blue_hair"),
    )
    client = FakeBrowserLibraryClient()
    server = create_server(
        path,
        host="127.0.0.1",
        port=0,
        raindrop_client=client,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield SimpleNamespace(
        url=f"http://127.0.0.1:{server.server_port}",
        client=client,
    )
    server.shutdown()
    server.server_close()
    thread.join()


def test_collection_tree_filters_journal_by_exact_destination(destination_filter_dashboard):
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        page.goto(destination_filter_dashboard.url)

        root_row = page.locator(".collection-row").filter(
            has=page.locator('.collection-select[title="Library/Root"]')
        )
        root_row.locator(".collection-toggle").click()
        page.locator('.collection-select[title="Library/Root/Child"]').click()

        page.get_by_text("Child result", exact=True).wait_for()
        assert page.get_by_text("Root result", exact=True).count() == 0
        assert page.locator("#search").input_value() == "location:Library/Root/Child"
        assert page.locator("#location-filter").text_content() == "Library/Root/Child"
        assert page.locator("#tree-filter-state").text_content() == "Library/Root/Child"
        assert page.locator("#filter-count").text_content() == "1"
        assert destination_filter_dashboard.client.raindrop_fetches == [
            (11, 0, None, None)
        ]

        # Selecting the active destination again clears the filter.
        page.locator('.collection-select[title="Library/Root/Child"]').click()
        page.get_by_text("Root result", exact=True).wait_for()
        assert page.locator("#search").input_value() == ""
        assert page.locator("#location-filter").text_content() == "Any location"

        browser.close()


def test_query_and_filter_controls_stay_in_sync(destination_filter_dashboard):
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        page.goto(destination_filter_dashboard.url)

        page.locator("#filter-toggle").click()
        page.locator("#outcome").select_option("review")
        page.locator("#mode").select_option("dry-run")
        assert page.locator("#search").input_value() == "outcome:review mode:dry-run"

        query = (
            'outcome:review mode:dry-run location:"Library/Root/Child" '
            'label:halo label:blue_hair title:Child link:x.com scope:history'
        )
        page.locator("#search").fill(query)
        page.get_by_text("Child result", exact=True).wait_for()

        assert page.locator("#outcome").input_value() == "review"
        assert page.locator("#mode").input_value() == "dry-run"
        assert page.locator("#scope").input_value() == "history"
        assert page.locator("#visual-labels").input_value() == "halo, blue_hair"
        assert page.locator("#title-filter").input_value() == "Child"
        assert page.locator("#link-filter").input_value() == "x.com"
        assert page.locator("#location-filter").text_content() == "Library/Root/Child"
        root_row = page.locator(".collection-row").filter(
            has=page.locator('.collection-select[title="Library/Root"]')
        )
        root_row.locator(".collection-toggle").click()
        assert page.locator('.collection-select[title="Library/Root/Child"]').get_attribute(
            "aria-pressed"
        ) == "true"

        browser.close()


def test_collection_tree_failure_does_not_replace_journal_results(destination_filter_dashboard):
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        page.route(
            "**/api/library/tree",
            lambda route: route.fulfill(
                status=429,
                content_type="application/json",
                body='{"error":"Raindrop is rate-limiting requests. Wait about a minute, then retry."}',
            ),
        )

        page.goto(destination_filter_dashboard.url)

        guidance = "Raindrop is rate-limiting requests. Wait about a minute, then retry."
        page.locator("#collection-tree").get_by_text(guidance, exact=True).wait_for()
        page.get_by_text("Root result", exact=True).wait_for()
        assert page.locator("#count").text_content() == "2 shown"

        browser.close()


def test_detail_drawer_discards_stale_async_render_and_resets_scroll(
    destination_filter_dashboard,
):
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        page.goto(destination_filter_dashboard.url)

        attempts = page.locator("[data-attempt-id]")
        first_id = attempts.nth(0).get_attribute("data-attempt-id")
        second_id = attempts.nth(1).get_attribute("data-attempt-id")
        second_title = attempts.nth(1).locator(".attempt-title").inner_text()
        page.evaluate(
            """
            () => {
              const originalFetch = window.fetch;
              collectionTreeGroups = [];
              artCollectionsPromise = null;
              let delayed = false;
              window.fetch = (input, init) => {
                if (!delayed && String(input).includes('/api/review/collections')) {
                  delayed = true;
                  return new Promise(resolve => setTimeout(
                    () => resolve(originalFetch(input, init)), 300
                  ));
                }
                return originalFetch(input, init);
              };
            }
            """
        )

        page.evaluate("attemptId => openAttempt(attemptId)", first_id)
        page.locator("#detail .resolution").wait_for()
        page.evaluate("attemptId => openAttempt(attemptId)", second_id)
        page.locator("#detail .detail-title").filter(has_text=second_title).wait_for()
        page.wait_for_timeout(450)

        assert page.locator("#detail > .resolution").count() == 1
        assert page.locator("#detail > .section").count() == 3
        page.locator("#detail").evaluate("element => { element.scrollTop = 100; }")
        page.evaluate("attemptId => openAttempt(attemptId)", first_id)
        page.locator("#detail .detail-title").wait_for()
        assert page.locator("#detail").evaluate("element => element.scrollTop") == 0

        browser.close()


def test_detail_drawer_uses_loaded_tree_when_collection_endpoint_fails(
    destination_filter_dashboard,
):
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        collection_requests = []

        def fail_collections(route):
            collection_requests.append(route.request.url)
            route.fulfill(
                status=504,
                content_type="application/json",
                body='{"error":"upstream collection timeout"}',
            )

        page.route("**/api/review/collections", fail_collections)
        page.goto(destination_filter_dashboard.url)
        page.locator("#collection-tree .collection-select").first.wait_for()
        page.evaluate(
            """
            () => {
              const group = collectionTreeGroups.find(item => item.title === 'Library');
              group.title = 'Art';
            }
            """
        )
        attempt_id = page.locator("[data-attempt-id]").first.get_attribute(
            "data-attempt-id"
        )
        page.evaluate("id => openAttempt(id)", attempt_id)

        page.locator("#detail .collection-search").wait_for()
        assert page.locator("#detail .resolution-error").text_content() == ""
        assert collection_requests == []

        browser.close()
