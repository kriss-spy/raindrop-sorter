"""Browser-level behavior for the loopback live-library workspace."""

import threading
import time

import pytest

from src.journal_web import create_server
from src.run_journal import SQLiteRunJournal

playwright = pytest.importorskip("playwright.sync_api")


class FakeBrowserLibraryClient:
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

    def get_raindrops(self, collection_id, page=0, perpage=50, search=None):
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
    server = create_server(
        path,
        host="127.0.0.1",
        port=0,
        raindrop_client=FakeBrowserLibraryClient(),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join()


def test_live_library_selection_pagination_and_restoration(live_library_dashboard):
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(5_000)
        page.goto(live_library_dashboard)

        root_row = page.locator(".collection-row").filter(
            has=page.locator('.collection-select[title="Root"]')
        )
        root_row.locator(".collection-toggle").click()

        page.locator('.collection-select[title="Root"]').click()
        page.locator('.collection-select[title="Root/Child"]').click()
        page.get_by_text("Current child item", exact=True).wait_for()
        assert page.get_by_text("Stale root item", exact=True).count() == 0

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
