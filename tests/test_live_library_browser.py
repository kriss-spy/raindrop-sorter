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


def _record_attempt(
    journal,
    bookmark_id,
    title,
    destination,
    *,
    labels=(),
    outcome=RouteOutcome.REVIEW,
):
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
            outcome=outcome,
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
        outcome=RouteOutcome.PROVISIONAL,
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


def test_location_filter_scopes_outcome_selector_counts(destination_filter_dashboard):
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
        page.locator("#filter-toggle").click()
        page.wait_for_function(
            """
            () => document.querySelector('#outcome option[value=""]')?.textContent
              === 'All outcomes · 1'
            """
        )

        assert page.locator('#outcome option[value="provisional"]').text_content() == (
            "provisional · 1"
        )
        assert page.locator('#outcome option[value="review"]').text_content() == "review · 0"

        browser.close()


def test_unresolved_location_filter_shows_zero_outcome_counts(
    destination_filter_dashboard,
):
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        page.goto(destination_filter_dashboard.url)

        page.locator("#search").fill('location:"Library/Missing"')
        page.locator("#filter-toggle").click()
        page.wait_for_function(
            """
            () => document.querySelector('#outcome option[value=""]')?.textContent
              === 'All outcomes · 0'
            """
        )

        assert page.locator('#outcome option[value="provisional"]').text_content() == (
            "provisional · 0"
        )
        assert page.locator('#outcome option[value="review"]').text_content() == "review · 0"
        assert page.locator("#count").text_content() == "0 shown"

        browser.close()


def test_stale_location_overview_response_does_not_replace_current_counts(
    destination_filter_dashboard,
):
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        page.goto(destination_filter_dashboard.url)

        root_row = page.locator(".collection-row").filter(
            has=page.locator('.collection-select[title="Library/Root"]')
        )
        root_row.locator(".collection-toggle").click()
        page.locator('.collection-select[title="Library/Root/Child"]').wait_for()
        page.evaluate(
            """
            () => {
              const originalFetch = window.fetch.bind(window);
              window.pendingOverviewRequests = [];
              window.fetch = (url, options) => {
                if (String(url).startsWith('/api/overview')) {
                  return new Promise(resolve => {
                    window.pendingOverviewRequests.push({url: String(url), resolve});
                  });
                }
                return originalFetch(url, options);
              };
              window.resolveOverviewRequest = (index, outcome, total) => {
                const outcomes = {[outcome]: total};
                window.pendingOverviewRequests[index].resolve(new Response(JSON.stringify({
                  total_bookmarks: total,
                  total_attempts: total,
                  outcomes,
                  attempt_outcomes: outcomes,
                  phases: {dry_run_completed: total},
                  attempt_phases: {dry_run_completed: total},
                  latest_at: '2026-09-27T00:00:00+00:00',
                }), {status: 200, headers: {'Content-Type': 'application/json'}}));
              };
            }
            """
        )

        page.locator('.collection-select[title="Library/Root"]').click()
        page.wait_for_function("() => window.pendingOverviewRequests.length === 1")
        page.locator('.collection-select[title="Library/Root/Child"]').click()
        page.wait_for_function("() => window.pendingOverviewRequests.length === 2")

        page.evaluate("window.resolveOverviewRequest(1, 'provisional', 1)")
        page.wait_for_function(
            """
            () => document.querySelector('#outcome option[value="provisional"]')?.textContent
              === 'provisional · 1'
            """
        )
        page.evaluate("window.resolveOverviewRequest(0, 'review', 1)")
        page.wait_for_timeout(100)

        assert page.locator('#outcome option[value="provisional"]').text_content() == (
            "provisional · 1"
        )
        assert page.locator('#outcome option[value="review"]').text_content() == "review · 0"

        browser.close()


def test_batch_assignment_clears_successful_cards_before_background_refresh(
    destination_filter_dashboard,
):
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        page.goto(destination_filter_dashboard.url)

        page.locator(".attempt-select").nth(0).check()
        page.locator(".attempt-select").nth(1).check()
        page.evaluate(
            """
            () => {
              const destination = document.querySelector('#batch-destination-search');
              destination.dataset.collectionId = '11';
              destination.value = 'Library/Root/Child';
              syncSelectionUi();

              const originalFetch = window.fetch.bind(window);
              window.fetch = (url, options = {}) => {
                if (String(url) === '/api/attempts/resolve-batch') {
                  return new Promise(resolve => {
                    window.resolveBatchAssignment = () => resolve(new Response(JSON.stringify({
                      status: 'ok', resolved: 2, failed: 0, results: [], errors: [],
                    }), {status: 200, headers: {'Content-Type': 'application/json'}}));
                  });
                }
                if (String(url).startsWith('/api/overview') || String(url).startsWith('/api/attempts?')) {
                  return new Promise(() => {});
                }
                return originalFetch(url, options);
              };
            }
            """
        )

        page.locator("#batch-assign").click()
        page.wait_for_function("() => typeof window.resolveBatchAssignment === 'function'")

        assert page.locator("#batch-bar").is_hidden()
        assert page.locator("[data-attempt-id]").count() == 0

        page.evaluate("window.resolveBatchAssignment()")
        page.wait_for_function(
            "() => document.querySelector('#batch-message').textContent === '2 assigned'"
        )

        assert page.locator("#batch-bar").is_hidden()
        assert page.locator("[data-attempt-id]").count() == 0

        browser.close()


def test_batch_assignment_ignores_refresh_started_before_optimistic_removal(
    destination_filter_dashboard,
):
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        page.goto(destination_filter_dashboard.url)

        page.locator(".attempt-select").nth(0).check()
        page.locator(".attempt-select").nth(1).check()
        page.evaluate(
            """
            () => {
              const destination = document.querySelector('#batch-destination-search');
              destination.dataset.collectionId = '11';
              destination.value = 'Library/Root/Child';
              syncSelectionUi();
              const staleItems = renderedAttempts.map(item => ({...item}));
              const originalFetch = window.fetch.bind(window);
              window.fetch = (url, options = {}) => {
                if (String(url) === '/api/attempts/resolve-batch') {
                  return new Promise(resolve => {
                    window.resolveBatchAssignment = () => resolve(new Response(JSON.stringify({
                      status: 'ok', resolved: 2, failed: 0, results: [], errors: [],
                    }), {status: 200, headers: {'Content-Type': 'application/json'}}));
                  });
                }
                if (String(url).startsWith('/api/attempts?')) {
                  return new Promise(resolve => {
                    if (!window.resolveStaleAttempts) {
                      window.resolveStaleAttempts = () => resolve(new Response(JSON.stringify({
                        items: staleItems, count: staleItems.length,
                      }), {status: 200, headers: {'Content-Type': 'application/json'}}));
                    }
                  });
                }
                return originalFetch(url, options);
              };
              void renderAttempts();
            }
            """
        )
        page.wait_for_function("() => typeof window.resolveStaleAttempts === 'function'")

        page.locator("#batch-assign").click()
        page.wait_for_function("() => typeof window.resolveBatchAssignment === 'function'")
        assert page.locator("[data-attempt-id]").count() == 0

        page.evaluate("window.resolveStaleAttempts()")
        page.wait_for_timeout(100)
        assert page.locator("[data-attempt-id]").count() == 0

        page.evaluate("window.resolveBatchAssignment()")
        page.wait_for_function(
            "() => document.querySelector('#batch-message').textContent === '2 assigned'"
        )
        browser.close()


def test_batch_assignment_ignores_refresh_started_while_request_is_pending(
    destination_filter_dashboard,
):
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        page.goto(destination_filter_dashboard.url)

        page.locator(".attempt-select").nth(0).check()
        page.locator(".attempt-select").nth(1).check()
        page.evaluate(
            """
            () => {
              const destination = document.querySelector('#batch-destination-search');
              destination.dataset.collectionId = '11';
              destination.value = 'Library/Root/Child';
              syncSelectionUi();
              const staleItems = renderedAttempts.map(item => ({...item}));
              const originalFetch = window.fetch.bind(window);
              window.fetch = (url, options = {}) => {
                if (String(url) === '/api/attempts/resolve-batch') {
                  return new Promise(resolve => {
                    window.resolveBatchAssignment = () => resolve(new Response(JSON.stringify({
                      status: 'ok', resolved: 2, failed: 0, results: [], errors: [],
                    }), {status: 200, headers: {'Content-Type': 'application/json'}}));
                  });
                }
                if (String(url).startsWith('/api/attempts?')) {
                  return new Promise(resolve => {
                    if (!window.resolveStaleAttempts) {
                      window.resolveStaleAttempts = () => resolve(new Response(JSON.stringify({
                        items: staleItems, count: staleItems.length,
                      }), {status: 200, headers: {'Content-Type': 'application/json'}}));
                    }
                  });
                }
                return originalFetch(url, options);
              };
            }
            """
        )

        page.locator("#batch-assign").click()
        page.wait_for_function("() => typeof window.resolveBatchAssignment === 'function'")
        page.evaluate("void renderAttempts()")
        page.wait_for_function("() => typeof window.resolveStaleAttempts === 'function'")

        page.evaluate("window.resolveBatchAssignment()")
        page.wait_for_function(
            "() => document.querySelector('#batch-message').textContent === '2 assigned'"
        )
        page.evaluate("window.resolveStaleAttempts()")
        page.wait_for_timeout(100)

        assert page.locator("[data-attempt-id]").count() == 0
        browser.close()


def test_batch_assignment_restores_cards_and_selection_when_request_fails(
    destination_filter_dashboard,
):
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        page.goto(destination_filter_dashboard.url)

        page.locator(".attempt-select").nth(0).check()
        page.locator(".attempt-select").nth(1).check()
        page.evaluate(
            """
            () => {
              const destination = document.querySelector('#batch-destination-search');
              destination.dataset.collectionId = '11';
              destination.value = 'Library/Root/Child';
              syncSelectionUi();
              window.fetch = url => {
                if (String(url) === '/api/attempts/resolve-batch') {
                  return Promise.resolve(new Response(JSON.stringify({error: 'Assignment failed'}), {
                    status: 502, headers: {'Content-Type': 'application/json'},
                  }));
                }
                return new Promise(() => {});
              };
            }
            """
        )

        page.locator("#batch-assign").click()
        page.wait_for_function(
            "() => document.querySelector('#batch-message').textContent === 'Assignment failed'"
        )

        assert page.locator("[data-attempt-id]").count() == 2
        assert page.locator(".attempt-select:checked").count() == 2
        assert page.locator("#batch-bar").is_visible()

        browser.close()


def test_batch_assignment_keeps_only_failed_cards_selected_during_refresh(
    destination_filter_dashboard,
):
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        page.goto(destination_filter_dashboard.url)

        page.locator(".attempt-select").nth(0).check()
        page.locator(".attempt-select").nth(1).check()
        page.evaluate(
            """
            () => {
              const destination = document.querySelector('#batch-destination-search');
              destination.dataset.collectionId = '11';
              destination.value = 'Library/Root/Child';
              syncSelectionUi();
              const attemptIds = [...document.querySelectorAll('[data-attempt-id]')]
                .map(item => item.dataset.attemptId);
              const failedAttempt = renderedAttempts.find(
                item => item.attempt_id === attemptIds[0]
              );
              window.fetch = url => {
                if (String(url) === '/api/attempts/resolve-batch') {
                  return Promise.resolve(new Response(JSON.stringify({
                    status: 'partial', resolved: 1, failed: 1, results: [],
                    errors: [{
                      attempt_id: attemptIds[0], retry_attempt_id: 'retry-attempt',
                      retry_attempt: {
                        ...failedAttempt, attempt_id: 'retry-attempt',
                        mode: 'manual-review', outcome: null, current_phase: 'failed',
                      },
                      error: 'Unavailable', type: 'RuntimeError',
                    }],
                  }), {status: 200, headers: {'Content-Type': 'application/json'}}));
                }
                return new Promise(() => {});
              };
            }
            """
        )

        page.locator("#batch-assign").click()
        page.wait_for_function(
            "() => document.querySelector('#batch-message').textContent === '1 assigned · 1 failed'"
        )

        assert page.locator("[data-attempt-id]").count() == 1
        assert page.locator('[data-attempt-id="retry-attempt"] .attempt-select').is_checked()
        assert page.locator("#selection-count").text_content() == "1 selected"

        browser.close()


def test_detail_assignment_closes_and_removes_card_before_request_finishes(
    destination_filter_dashboard,
):
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        page.goto(destination_filter_dashboard.url)
        page.get_by_text("Root result", exact=True).wait_for()
        page.evaluate(
            """
            () => {
              const originalFetch = window.fetch.bind(window);
              window.fetch = (url, options = {}) => {
                if (String(url) === '/api/review/collections') {
                  return Promise.resolve(new Response(JSON.stringify({
                    items: [{collection_id: 11, path: 'Art/Child'}],
                  }), {status: 200, headers: {'Content-Type': 'application/json'}}));
                }
                if (String(url).endsWith('/resolve')) {
                  return new Promise(resolve => {
                    window.resolveDetailAssignment = () => resolve(new Response(JSON.stringify({
                      attempt_id: 'confirmed-attempt',
                    }), {status: 200, headers: {'Content-Type': 'application/json'}}));
                  });
                }
                if (String(url).startsWith('/api/overview') || String(url).startsWith('/api/attempts?')) {
                  return new Promise(() => {});
                }
                return originalFetch(url, options);
              };
            }
            """
        )

        page.get_by_text("Root result", exact=True).click()
        page.get_by_role("button", name="Art/Child", exact=True).click()
        page.get_by_role("button", name="Move & confirm → Art/Child", exact=True).click()
        page.wait_for_function("() => typeof window.resolveDetailAssignment === 'function'")

        assert page.locator("#detail-panel").get_attribute("aria-hidden") == "true"
        assert page.get_by_text("Root result", exact=True).count() == 0
        assert page.locator("[data-attempt-id]").count() == 1

        page.evaluate("window.resolveDetailAssignment()")
        browser.close()


def test_detail_assignment_restores_card_and_detail_when_request_fails(
    destination_filter_dashboard,
):
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        page.goto(destination_filter_dashboard.url)
        page.get_by_text("Root result", exact=True).wait_for()
        page.evaluate(
            """
            () => {
              const originalFetch = window.fetch.bind(window);
              const submittedAttempt = renderedAttempts.find(
                item => item.title === 'Root result'
              );
              const retryAttempt = {
                ...submittedAttempt,
                attempt_id: 'retry-attempt',
                mode: 'manual-review',
                outcome: null,
                current_phase: 'failed',
                error: {type: 'RuntimeError', message: 'unavailable'},
              };
              window.fetch = (url, options = {}) => {
                if (String(url) === '/api/review/collections') {
                  return Promise.resolve(new Response(JSON.stringify({
                    items: [{collection_id: 11, path: 'Art/Child'}],
                  }), {status: 200, headers: {'Content-Type': 'application/json'}}));
                }
                if (String(url).endsWith('/resolve')) {
                  return Promise.resolve(new Response(JSON.stringify({
                    error: 'Assignment failed',
                    retry_attempt_id: retryAttempt.attempt_id,
                    retry_attempt: retryAttempt,
                    retry_trace: {
                      attempt: {...retryAttempt, bookmark_snapshot: {title: retryAttempt.title}},
                      evidence: [],
                      actions: [],
                      events: [{
                        phase: 'manual_destination_selected',
                        payload: {
                          destination: 'Art/Child',
                          selection_source: 'custom',
                          custom_only: true,
                        },
                      }],
                    },
                  }), {status: 502, headers: {'Content-Type': 'application/json'}}));
                }
                if (String(url).startsWith('/api/attempts?')) return new Promise(() => {});
                return originalFetch(url, options);
              };
            }
            """
        )

        page.get_by_text("Root result", exact=True).click()
        page.get_by_role("button", name="Art/Child", exact=True).click()
        page.get_by_role("button", name="Move & confirm → Art/Child", exact=True).click()
        page.locator("#detail .resolution-error").get_by_text(
            "Assignment failed", exact=True
        ).wait_for()

        assert page.locator("#detail-panel").get_attribute("aria-hidden") == "false"
        assert page.locator("[data-attempt-id]").count() == 2
        assert page.locator('[data-attempt-id="retry-attempt"]').count() == 1
        assert page.get_by_text("Root result", exact=True).count() == 2

        page.evaluate(
            "openAttempt(renderedAttempts.find(item => item.title === 'Child result').attempt_id)"
        )
        assert page.locator('[data-attempt-id="retry-attempt"]').count() == 0
        page.locator("#detail .detail-title").get_by_text(
            "Child result", exact=True
        ).wait_for()

        browser.close()


def test_detail_assignment_failure_does_not_restore_card_after_filter_change(
    destination_filter_dashboard,
):
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        page.goto(destination_filter_dashboard.url)
        page.get_by_text("Root result", exact=True).wait_for()
        page.evaluate(
            """
            () => {
              const originalFetch = window.fetch.bind(window);
              const submittedAttempt = renderedAttempts.find(
                item => item.title === 'Root result'
              );
              const retryAttempt = {
                ...submittedAttempt,
                attempt_id: 'retry-attempt',
                mode: 'manual-review',
                outcome: null,
                current_phase: 'failed',
              };
              window.fetch = (url, options = {}) => {
                if (String(url) === '/api/review/collections') {
                  return Promise.resolve(new Response(JSON.stringify({
                    items: [{collection_id: 11, path: 'Art/Child'}],
                  }), {status: 200, headers: {'Content-Type': 'application/json'}}));
                }
                if (String(url).endsWith('/resolve')) {
                  return new Promise(resolve => {
                    window.rejectDetailAssignment = () => resolve(new Response(JSON.stringify({
                      error: 'Assignment failed',
                      retry_attempt_id: retryAttempt.attempt_id,
                      retry_attempt: retryAttempt,
                      retry_trace: {
                        attempt: {...retryAttempt, bookmark_snapshot: {title: retryAttempt.title}},
                        evidence: [], actions: [], events: [],
                      },
                    }), {status: 502, headers: {'Content-Type': 'application/json'}}));
                  });
                }
                return originalFetch(url, options);
              };
            }
            """
        )

        page.get_by_text("Root result", exact=True).click()
        page.get_by_role("button", name="Art/Child", exact=True).click()
        page.get_by_role("button", name="Move & confirm → Art/Child", exact=True).click()
        page.wait_for_function("() => typeof window.rejectDetailAssignment === 'function'")
        page.locator("#search").fill("title:Child")
        page.get_by_text("Child result", exact=True).wait_for()
        page.evaluate("window.rejectDetailAssignment()")
        page.wait_for_timeout(100)

        assert page.locator("#detail-panel").get_attribute("aria-hidden") == "true"
        assert page.get_by_text("Root result", exact=True).count() == 0
        assert page.locator('[data-attempt-id="retry-attempt"]').count() == 0
        assert page.get_by_text("Child result", exact=True).count() == 1

        browser.close()


def test_detail_assignment_failure_stays_visible_with_active_review_filters(
    destination_filter_dashboard,
):
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        page.goto(destination_filter_dashboard.url)
        page.locator("#search").fill("outcome:review mode:dry-run")
        page.get_by_text("Root result", exact=True).wait_for()
        page.evaluate(
            """
            () => {
              const originalFetch = window.fetch.bind(window);
              const submittedAttempt = renderedAttempts.find(
                item => item.title === 'Root result'
              );
              const retryAttempt = {
                ...submittedAttempt,
                attempt_id: 'retry-attempt',
                mode: 'manual-review',
                outcome: null,
                current_phase: 'failed',
                error: {type: 'RuntimeError', message: 'unavailable'},
              };
              window.fetch = (url, options = {}) => {
                if (String(url) === '/api/review/collections') {
                  return Promise.resolve(new Response(JSON.stringify({
                    items: [{collection_id: 11, path: 'Art/Child'}],
                  }), {status: 200, headers: {'Content-Type': 'application/json'}}));
                }
                if (String(url).endsWith('/resolve')) {
                  window.detailAssignmentFailed = true;
                  return Promise.resolve(new Response(JSON.stringify({
                    error: 'Assignment failed',
                    retry_attempt_id: retryAttempt.attempt_id,
                    retry_attempt: retryAttempt,
                    retry_trace: {
                      attempt: {...retryAttempt, bookmark_snapshot: {title: retryAttempt.title}},
                      evidence: [],
                      actions: [],
                      events: [{
                        phase: 'manual_destination_selected',
                        payload: {
                          destination: 'Art/Child',
                          selection_source: 'custom',
                          custom_only: true,
                        },
                      }],
                    },
                  }), {status: 502, headers: {'Content-Type': 'application/json'}}));
                }
                if (window.detailAssignmentFailed && String(url).startsWith('/api/attempts?')) {
                  return Promise.resolve(new Response(JSON.stringify({items: []}), {
                    status: 200, headers: {'Content-Type': 'application/json'},
                  }));
                }
                return originalFetch(url, options);
              };
            }
            """
        )

        page.get_by_text("Root result", exact=True).click()
        page.get_by_role("button", name="Art/Child", exact=True).click()
        page.get_by_role("button", name="Move & confirm → Art/Child", exact=True).click()
        page.locator("#detail .resolution-error").get_by_text(
            "Assignment failed", exact=True
        ).wait_for()
        page.evaluate("refreshDashboard()")
        page.wait_for_timeout(300)

        assert page.locator("#detail-panel").get_attribute("aria-hidden") == "false"
        assert page.locator('[data-attempt-id="retry-attempt"]').count() == 1
        assert page.locator("#search").input_value() == "outcome:review mode:dry-run"
        assert page.get_by_text("Root result", exact=True).count() == 2

        page.locator("#detail-close").click()
        assert page.locator('[data-attempt-id="retry-attempt"]').count() == 0
        assert page.locator("#detail-panel").get_attribute("aria-hidden") == "true"

        browser.close()


def test_query_change_immediately_dismisses_pinned_retry_detail(
    destination_filter_dashboard,
):
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        page.goto(destination_filter_dashboard.url)
        page.get_by_text("Root result", exact=True).wait_for()
        page.evaluate(
            """
            () => {
              const source = renderedAttempts.find(item => item.title === 'Root result');
              const retryAttempt = {
                ...source,
                attempt_id: 'retry-attempt',
                mode: 'manual-review',
                outcome: null,
                current_phase: 'failed',
              };
              pinnedRetry = {attempt: retryAttempt, query: document.querySelector('#search').value};
              renderedAttempts = [retryAttempt, ...renderedAttempts];
              selectedAttemptId = retryAttempt.attempt_id;
              setDetailOpen(true);
              renderCurrentAttempts();
              const originalFetch = window.fetch.bind(window);
              window.fetch = (url, options = {}) => String(url).startsWith('/api/attempts?')
                ? new Promise(() => {})
                : originalFetch(url, options);
            }
            """
        )

        page.locator("#search").fill("title:Child")

        assert page.locator('[data-attempt-id="retry-attempt"]').count() == 0
        assert page.locator("#detail-panel").get_attribute("aria-hidden") == "true"

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
            'outcome:provisional mode:dry-run location:"Library/Root/Child" '
            'label:halo label:blue_hair title:Child link:x.com scope:history'
        )
        page.locator("#search").fill(query)
        page.get_by_text("Child result", exact=True).wait_for()

        assert page.locator("#outcome").input_value() == "provisional"
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


def test_filter_change_renders_first_page_then_appends_in_order(
    destination_filter_dashboard,
):
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        page.goto(destination_filter_dashboard.url)
        page.get_by_text("Root result", exact=True).wait_for()
        page.evaluate(
            """
            () => {
              const originalFetch = window.fetch.bind(window);
              const attempts = Array.from({length: 27}, (_, index) => ({
                attempt_id: `progressive-${index}`,
                bookmark_id: 1000 + index,
                title: `Progressive ${String(index).padStart(2, '0')}`,
                mode: 'apply',
                outcome: 'confirmed',
                current_phase: 'applied',
                started_at: `2026-09-27T00:${String(59 - index).padStart(2, '0')}:00+00:00`,
                duration_ms: 10,
              }));
              window.progressiveRequests = [];
              window.firstPageFrameObserved = false;
              window.fetch = (url, options = {}) => {
                if (!String(url).startsWith('/api/attempts?')) return originalFetch(url, options);
                const params = new URL(String(url), location.origin).searchParams;
                const beforeAttemptId = params.get('before_attempt_id');
                const snapshotAttemptId = params.get('snapshot_attempt_id');
                const offset = beforeAttemptId
                  ? Number(beforeAttemptId.replace('progressive-', '')) + 1
                  : 0;
                const limit = Number(params.get('limit'));
                window.progressiveRequests.push({beforeAttemptId, snapshotAttemptId, limit});
                if (beforeAttemptId) {
                  window.frameBeforeSecondRequest = window.firstPageFrameObserved;
                }
                const pageItems = attempts.slice(offset, offset + limit);
                const response = new Response(JSON.stringify({
                  items: pageItems,
                  count: Math.min(limit, attempts.length - offset),
                  has_more: offset + limit < attempts.length,
                  next_before_started_at: pageItems.at(-1)?.started_at || null,
                  next_before_attempt_id: pageItems.at(-1)?.attempt_id || null,
                  snapshot_started_at: '2026-09-27T00:59:00+00:00',
                  snapshot_attempt_id: 'progressive-0',
                }), {status: 200, headers: {'Content-Type': 'application/json'}});
                if (offset === 0) {
                  return new Promise(resolve => {
                    window.releaseFirstAttemptPage = () => {
                      requestAnimationFrame(() => { window.firstPageFrameObserved = true; });
                      resolve(response);
                    };
                  });
                }
                return new Promise(resolve => {
                  window.releaseNextAttemptPage = () => resolve(response);
                });
              };
            }
            """
        )

        page.locator("#filter-toggle").click()
        page.locator("#outcome").select_option("confirmed")
        assert page.locator("#count").text_content() == "Loading…"
        assert page.locator("[data-attempt-id]").count() == 0
        page.evaluate("refreshDashboardInBackground()")
        assert page.evaluate("window.progressiveRequests") == [
            {"beforeAttemptId": None, "snapshotAttemptId": None, "limit": 24},
        ]

        page.evaluate("window.releaseFirstAttemptPage()")
        page.wait_for_function("() => document.querySelectorAll('[data-attempt-id]').length === 24")
        page.wait_for_function("() => window.progressiveRequests.length === 2")

        assert page.locator("#count").text_content() == "24+ shown"
        assert page.locator(".attempt-title").all_text_contents() == [
            f"Progressive {index:02d}" for index in range(24)
        ]
        assert page.evaluate("window.progressiveRequests") == [
            {"beforeAttemptId": None, "snapshotAttemptId": None, "limit": 24},
            {
                "beforeAttemptId": "progressive-23",
                "snapshotAttemptId": "progressive-0",
                "limit": 100,
            },
        ]
        assert page.evaluate("window.frameBeforeSecondRequest") is True

        page.evaluate("window.releaseNextAttemptPage()")
        page.wait_for_function("() => document.querySelectorAll('[data-attempt-id]').length === 27")
        page.wait_for_function("() => window.progressiveRequests.length === 3")

        assert page.locator("#count").text_content() == "27 shown"
        assert page.locator(".attempt-title").all_text_contents() == [
            f"Progressive {index:02d}" for index in range(27)
        ]
        assert page.evaluate("window.progressiveRequests[2]") == {
            "beforeAttemptId": None,
            "snapshotAttemptId": None,
            "limit": 24,
        }

        browser.close()


def test_background_progressive_refresh_keeps_current_cards_until_complete(
    destination_filter_dashboard,
):
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        page.goto(destination_filter_dashboard.url)
        page.get_by_text("Root result", exact=True).wait_for()
        page.evaluate(
            """
            () => {
              const originalFetch = window.fetch.bind(window);
              const attempts = Array.from({length: 27}, (_, index) => ({
                attempt_id: `background-${index}`,
                bookmark_id: 2000 + index,
                title: `Background ${String(index).padStart(2, '0')}`,
                mode: 'apply', outcome: 'confirmed', current_phase: 'applied',
                started_at: `2026-09-27T00:${String(59 - index).padStart(2, '0')}:00+00:00`,
                duration_ms: 10,
              }));
              window.fetch = (url, options = {}) => {
                if (!String(url).startsWith('/api/attempts?')) return originalFetch(url, options);
                const params = new URL(String(url), location.origin).searchParams;
                const beforeAttemptId = params.get('before_attempt_id');
                const offset = beforeAttemptId
                  ? Number(beforeAttemptId.replace('background-', '')) + 1
                  : 0;
                const limit = Number(params.get('limit'));
                const pageItems = attempts.slice(offset, offset + limit);
                const response = new Response(JSON.stringify({
                  items: pageItems,
                  count: pageItems.length,
                  has_more: offset + limit < attempts.length,
                  next_before_started_at: pageItems.at(-1)?.started_at || null,
                  next_before_attempt_id: pageItems.at(-1)?.attempt_id || null,
                  snapshot_started_at: attempts[0].started_at,
                  snapshot_attempt_id: attempts[0].attempt_id,
                }), {status: 200, headers: {'Content-Type': 'application/json'}});
                if (offset === 0) return Promise.resolve(response);
                return new Promise(resolve => {
                  window.releaseBackgroundTail = () => resolve(response);
                });
              };
            }
            """
        )

        page.evaluate("void refreshDashboard({progressive:true, clearBeforeLoad:false})")
        page.wait_for_function("() => Boolean(window.releaseBackgroundTail)")

        assert page.get_by_text("Root result", exact=True).count() == 1
        assert page.locator('[data-attempt-id^="background-"]').count() == 0

        page.evaluate("window.releaseBackgroundTail()")
        page.wait_for_function(
            "() => document.querySelectorAll('[data-attempt-id^=\"background-\"]').length === 27"
        )
        assert page.get_by_text("Root result", exact=True).count() == 0

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
