"""Orchestration tests for the deployed Modal entry points."""

from unittest.mock import patch

import app as app_module
from src.state_machine import tag_pending_vision


class FakeRaindropClient:
    def __init__(self, items):
        self.items = items
        self.updates = []

    def get_unsorted_collection(self):
        return {"_id": -1, "title": "Unsorted"}

    def get_all_raindrops(self, collection_id):
        assert collection_id == -1
        return self.items

    def get_raindrop(self, raindrop_id):
        return next(item for item in self.items if item["_id"] == raindrop_id)

    def update_raindrop(self, raindrop_id, collection_id=None, tags=None):
        self.updates.append((raindrop_id, collection_id, tags))
        return {"item": {"_id": raindrop_id}}


def test_watcher_dispatches_resolver_after_tagging_new_bookmarks():
    client = FakeRaindropClient([{"_id": 123, "tags": []}])

    with (
        patch("src.raindrop_client.RaindropClient", return_value=client),
        patch.object(app_module.resolver, "spawn") as spawn_resolver,
    ):
        result = app_module.watcher.local()

    assert result["processed"] == 1
    spawn_resolver.assert_called_once_with()


def test_watcher_redispatches_resolver_for_existing_pending_bookmarks():
    client = FakeRaindropClient(
        [{"_id": 123, "tags": ["sorter-pending-resolution"]}]
    )

    with (
        patch("src.raindrop_client.RaindropClient", return_value=client),
        patch.object(app_module.resolver, "spawn") as spawn_resolver,
    ):
        result = app_module.watcher.local()

    assert result["processed"] == 0
    assert result["skipped"] == 1
    spawn_resolver.assert_called_once_with()


def test_watcher_leaves_pending_vision_bookmarks_for_vision_cron():
    client = FakeRaindropClient(
        [
            {
                "_id": 123,
                "tags": [
                    "sorter-pending-resolution",
                    "sorter-pending-vision:2026-09-15",
                ],
            }
        ]
    )

    with (
        patch("src.raindrop_client.RaindropClient", return_value=client),
        patch.object(app_module.resolver, "spawn") as spawn_resolver,
    ):
        result = app_module.watcher.local()

    assert result["processed"] == 0
    assert result["skipped"] == 1
    assert client.updates == []
    spawn_resolver.assert_not_called()


def test_pending_vision_transition_clears_pending_resolution():
    tags = tag_pending_vision(
        {"_id": 123, "tags": ["sorter-pending-resolution"]}
    )

    assert "sorter-pending-resolution" not in tags
    assert any(tag.startswith("sorter-pending-vision:") for tag in tags)


def test_vision_worker_dispatches_resolver_after_adding_vision_tags():
    client = FakeRaindropClient(
        [
            {
                "_id": 123,
                "cover": "https://example.test/cover.jpg",
                "tags": ["sorter-pending-vision:2026-09-15"],
            }
        ]
    )

    with (
        patch("src.raindrop_client.RaindropClient", return_value=client),
        patch(
            "src.vision_worker.run_vision_on_bookmark",
            return_value=["ai:wdtag-hatsune_miku"],
        ),
        patch.object(app_module.resolver, "spawn") as spawn_resolver,
    ):
        result = app_module.vision_worker.local(123)

    assert result["status"] == "ok"
    spawn_resolver.assert_called_once_with()


def test_vision_worker_skips_bookmark_that_is_no_longer_pending():
    client = FakeRaindropClient(
        [{"_id": 123, "cover": "https://example.test/cover.jpg", "tags": []}]
    )

    with (
        patch("src.raindrop_client.RaindropClient", return_value=client),
        patch("src.vision_worker.run_vision_on_bookmark") as run_vision,
        patch.object(app_module.resolver, "spawn") as spawn_resolver,
    ):
        result = app_module.vision_worker.local(123)

    assert result == {"status": "not_pending", "bookmark_id": 123}
    run_vision.assert_not_called()
    assert client.updates == []
    spawn_resolver.assert_not_called()


def test_vision_cron_dispatches_pending_bookmarks_to_vision_workers():
    client = FakeRaindropClient(
        [
            {
                "_id": 123,
                "cover": "https://example.test/first.jpg",
                "tags": ["sorter-pending-vision:2026-09-15"],
            },
            {
                "_id": 456,
                "cover": "https://example.test/second.jpg",
                "tags": ["sorter-pending-vision:2026-09-15"],
            },
        ]
    )

    with (
        patch("src.raindrop_client.RaindropClient", return_value=client),
        patch.object(app_module.vision_worker, "spawn") as spawn_vision_worker,
    ):
        result = app_module.vision_cron.local()

    assert result == {"status": "ok", "dispatched": 2, "total": 2}
    assert [call.args for call in spawn_vision_worker.call_args_list] == [(123,), (456,)]
    assert client.updates == []
