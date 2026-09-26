"""Browser-level behavior for the loopback live-library workspace."""

import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from src.journal_web import create_server
from src.run_journal import SQLiteRunJournal

playwright = pytest.importorskip("playwright.sync_api")


class FakeBrowserLibraryClient:
    def __init__(self):
        self.searches = []
        self.sorts = []

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
        self.searches.append(search)
        self.sorts.append(sort)
        if search:
            if page == 0:
                return [{"_id": 301, "title": "Search page one"}], True
            return [{"_id": 302, "title": "Search page two"}], False
        if collection_id == 10:
            time.sleep(0.35)
            return [{"_id": 100, "title": "Stale root item"}], False
        if collection_id == 11:
            return [{"_id": 110, "title": "Current child item"}], False
        if collection_id == -1 and page == 0:
            return [
                {"_id": 201, "title": "Unsorted one"},
                {"_id": 202, "title": "Unsorted two"},
            ], True
        if collection_id == -1 and page == 1:
            return [{"_id": 203, "title": "Unsorted three"}], False
        return [], False


@pytest.fixture
def live_library_dashboard(tmp_path):
    path = tmp_path / "journal.sqlite"
    SQLiteRunJournal(path)
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


def test_live_library_selection_pagination_and_restoration(live_library_dashboard):
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        page.goto(live_library_dashboard.url)

        root_row = page.locator(".collection-row").filter(
            has=page.locator('.collection-select[title="Root"]')
        )
        root_row.locator(".collection-toggle").click()

        page.locator('.collection-select[title="Root"]').click()
        page.locator('.collection-select[title="Root/Child"]').click()
        page.get_by_text("Current child item", exact=True).wait_for()
        assert page.get_by_text("Stale root item", exact=True).count() == 0
        assert page.locator("#outcome").is_hidden()
        assert page.locator("#phase").is_hidden()
        assert page.locator("#scope").is_hidden()
        assert page.locator(".view-switch").is_hidden()
        assert page.locator("#search").get_attribute("placeholder") == "Search this collection with Raindrop syntax"
        assert parse_qs(urlparse(page.url).query)["collection"] == ["11"]

        page.reload()
        page.locator('.collection-select[title="Root/Child"].active').wait_for()
        page.get_by_text("Current child item", exact=True).wait_for()
        assert root_row.locator(".collection-toggle").text_content().strip() == "▾"

        unsorted_row = page.locator(".collection-row").filter(
            has=page.locator('.collection-select[title="Unsorted"]')
        )
        assert unsorted_row.locator(".collection-count").text_content() == "3"
        page.locator('.collection-select[title="Unsorted"]').click()
        page.get_by_text("Unsorted two", exact=True).wait_for()
        assert page.locator(".live-bookmark").count() == 2
        page.locator("#library-load-more").click()
        page.get_by_text("Unsorted three", exact=True).wait_for()
        assert page.locator(".live-bookmark").count() == 3

        browser.close()


def test_live_library_search_pagination_url_restore_and_journal_mode(live_library_dashboard):
    expression = '#tag "exact phrase" / 日本語'
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        page.goto(live_library_dashboard.url)

        page.locator('.collection-select[title="Root"]').click()
        page.locator("#search").fill(expression)
        page.locator("#library-sort").select_option("-title")
        page.get_by_text("Search page one", exact=True).wait_for()
        assert live_library_dashboard.client.searches[-1] == expression
        assert live_library_dashboard.client.sorts[-1] == "-title"
        query = parse_qs(urlparse(page.url).query)
        assert query["collection"] == ["10"]
        assert query["q"] == [expression]
        assert query["sort"] == ["-title"]

        page.locator("#library-load-more").click()
        page.get_by_text("Search page two", exact=True).wait_for()
        assert parse_qs(urlparse(page.url).query)["page"] == ["1"]
        assert page.locator(".live-bookmark").count() == 2

        page.reload()
        page.get_by_text("Search page two", exact=True).wait_for()
        assert page.locator(".live-bookmark").count() == 2
        assert page.locator("#search").input_value() == expression
        assert page.locator("#library-sort").input_value() == "-title"

        page.locator("#journal-select").click()
        page.locator("#outcome").wait_for(state="visible")
        assert "collection" not in parse_qs(urlparse(page.url).query)
        page.reload()
        page.locator("#outcome").wait_for(state="visible")
        assert page.locator("#journal-select").get_attribute("class").endswith("active")

        browser.close()


def test_direct_live_url_surfaces_collection_tree_failure_in_results(live_library_dashboard):
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

        page.goto(f"{live_library_dashboard.url}/?collection=10")

        guidance = "Raindrop is rate-limiting requests. Wait about a minute, then retry."
        page.locator("#attempts").get_by_text(guidance, exact=True).wait_for()
        assert page.locator("#count").text_content() == "Unavailable"

        browser.close()
