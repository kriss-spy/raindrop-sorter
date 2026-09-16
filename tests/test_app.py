"""Orchestration tests for the deployed Modal entry points."""

import re
from unittest.mock import patch

import app as app_module
import pytest
from src.reindex_lease import (
    REINDEX_LEASE_KEY,
    acquire_item_lease,
    acquire_reindex_lease,
    is_reindex_active,
    release_reindex_lease,
)
from src.state_machine import tag_pending_vision


class FakeRaindropClient:
    def __init__(self, items):
        self.items = items
        self.updates = []
        self.page_requests = []

    def get_unsorted_collection(self):
        return {"_id": -1, "title": "Unsorted"}

    def get_all_raindrops(self, collection_id):
        assert collection_id == -1
        return self.items

    def get_raindrops(self, collection_id, page=0, perpage=50, search=None):
        assert collection_id == -1
        self.page_requests.append(
            {"page": page, "perpage": perpage, "search": search}
        )
        items = self.items
        if search == "#sorter-pending-resolution":
            items = [
                item
                for item in items
                if "sorter-pending-resolution" in item.get("tags", [])
            ]
        elif search:
            excluded_tags = set(re.findall(r'-#"([^"]+)"', search))
            required_tags = set(re.findall(r'(?<!-)#"([^"]+)"', search))
            items = [
                item
                for item in items
                if required_tags.issubset(item.get("tags", []))
                and excluded_tags.isdisjoint(item.get("tags", []))
            ]
        start = page * perpage
        batch = items[start : start + perpage]
        return batch, start + perpage < len(items)

    def get_raindrop(self, raindrop_id):
        return next(item for item in self.items if item["_id"] == raindrop_id)

    def get_tags(self, collection_id):
        assert collection_id == -1
        counts = {}
        for item in self.items:
            for tag in item.get("tags", []):
                counts[tag] = counts.get(tag, 0) + 1
        return [{"_id": tag, "count": count} for tag, count in counts.items()]

    def update_raindrop(self, raindrop_id, collection_id=None, tags=None):
        self.updates.append((raindrop_id, collection_id, tags))
        return {"item": {"_id": raindrop_id}}


class FakeCoordination:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def put(self, key, value, *, skip_if_exists=False):
        if skip_if_exists and key in self.values:
            return False
        self.values[key] = value
        return True

    def pop(self, key, default=None):
        return self.values.pop(key, default)

    def keys(self):
        return list(self.values)


@pytest.fixture(autouse=True)
def local_coordination_store():
    with patch.object(app_module, "coordination", FakeCoordination()):
        yield


def test_watcher_dispatches_resolver_after_tagging_new_bookmarks():
    client = FakeRaindropClient([{"_id": 123, "tags": []}])

    with (
        patch("src.raindrop_client.RaindropClient", return_value=client),
        patch.object(app_module.resolver, "spawn") as spawn_resolver,
    ):
        result = app_module.watcher.local()

    assert result["processed"] == 1
    spawn_resolver.assert_called_once_with()


def test_watcher_does_not_use_raindrop_api_during_reindex():
    with (
        patch("src.reindex_lease.time.time", return_value=100),
        patch.object(
            app_module,
            "coordination",
            FakeCoordination({"reindex_lease_expires_at": 200}),
            create=True,
        ),
        patch("src.raindrop_client.RaindropClient") as client,
    ):
        result = app_module.watcher.local()

    assert result == {"status": "reindex_active", "processed": 0}
    client.assert_not_called()


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
    assert result["skipped"] == 0
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
    assert result["skipped"] == 0
    assert client.updates == []
    spawn_resolver.assert_not_called()


def test_watcher_tags_only_one_bounded_unprocessed_batch():
    client = FakeRaindropClient(
        [{"_id": item_id, "tags": []} for item_id in range(30)]
        + [{"_id": 100, "tags": ["sorter-pending-resolution"]}]
    )

    with (
        patch("src.raindrop_client.RaindropClient", return_value=client),
        patch.object(app_module.resolver, "spawn") as spawn_resolver,
    ):
        result = app_module.watcher.local()

    assert result == {
        "status": "ok",
        "processed": 25,
        "skipped": 0,
        "total": 25,
        "has_more": True,
    }
    assert len(client.updates) == 25
    assert client.page_requests == [
        {
            "page": 0,
            "perpage": 25,
            "search": '-#"sorter-pending-resolution"',
        }
    ]
    spawn_resolver.assert_called_once_with()


def test_pending_vision_transition_clears_pending_resolution():
    tags = tag_pending_vision(
        {"_id": 123, "tags": ["sorter-pending-resolution"]}
    )

    assert "sorter-pending-resolution" not in tags
    assert any(tag.startswith("sorter-pending-vision:") for tag in tags)


def test_reindex_reserves_api_budget_and_releases_it_after_completion():
    coordination = FakeCoordination()

    def rebuild(client, embedder, db_path):
        assert is_reindex_active(coordination)
        return {"status": "ok", "processed": 3}

    with (
        patch("src.reindex_lease.time.time", return_value=100),
        patch.object(app_module, "coordination", coordination),
        patch("src.raindrop_client.RaindropClient"),
        patch("src.embeddings.Embedder"),
        patch("src.reindex.rebuild_index", side_effect=rebuild),
    ):
        result = app_module.reindex_worker.local()

    assert result["status"] == "ok"
    assert result["processed"] == 3
    assert result["timings_seconds"]["model_init"] >= 0
    assert result["timings_seconds"]["total"] >= 0
    assert coordination.values == {}


def test_serialized_reindex_refreshes_a_preempted_workers_pause_signal():
    coordination = FakeCoordination({"reindex_lease_expires_at": 200})

    with (
        patch("src.reindex_lease.time.time", return_value=100),
        patch.object(app_module, "coordination", coordination),
        patch("src.raindrop_client.RaindropClient") as client,
        patch("src.embeddings.Embedder"),
        patch("src.reindex.rebuild_index", return_value={"status": "ok"}),
    ):
        result = app_module.reindex_worker.local()

    assert result["status"] == "ok"
    client.assert_called_once_with()


def test_expired_reindex_pause_signal_is_replaced_by_serialized_worker():
    coordination = FakeCoordination()

    with patch(
        "src.reindex_lease.time.time",
        side_effect=[100, 100, 100, 1000, 1000, 1000],
    ):
        first_owner = acquire_reindex_lease(coordination, 10)
        second_owner = acquire_reindex_lease(coordination, 10)

    assert first_owner is not None
    assert second_owner is not None
    assert second_owner != first_owner
    assert list(coordination.values) == [REINDEX_LEASE_KEY]

    release_reindex_lease(coordination, "not-the-owner")
    assert REINDEX_LEASE_KEY in coordination.values

    release_reindex_lease(coordination, second_owner)
    assert coordination.values == {}


def test_reindex_failure_reports_timing_and_request_metrics():
    with (
        patch("src.raindrop_client.RaindropClient") as client_class,
        patch("src.embeddings.Embedder", side_effect=RuntimeError("model failed")),
    ):
        client_class.return_value.request_count = 0
        client_class.return_value.rate_limit_wait_seconds = 0.0
        result = app_module.reindex_worker.local()

    assert result["status"] == "error"
    assert result["error"] == "model failed"
    assert result["timings_seconds"]["model_init"] >= 0
    assert result["timings_seconds"]["total"] >= 0
    assert result["raindrop_requests"] == 0
    assert result["rate_limit_wait_seconds"] == 0.0


def test_resolver_does_not_use_raindrop_api_during_reindex():
    with (
        patch("src.reindex_lease.time.time", return_value=100),
        patch.object(
            app_module,
            "coordination",
            FakeCoordination({"reindex_lease_expires_at": 200}),
        ),
        patch("src.raindrop_client.RaindropClient") as client,
    ):
        result = app_module.resolver.local()

    assert result == {"status": "reindex_active"}
    client.assert_not_called()


def test_resolver_processes_one_bounded_pending_batch():
    client = FakeRaindropClient(
        [
            {"_id": item_id, "tags": ["sorter-pending-resolution"]}
            for item_id in range(30)
        ]
    )

    with (
        patch("src.raindrop_client.RaindropClient", return_value=client),
        patch("src.embeddings.Embedder"),
        patch.object(
            app_module,
            "_load_state",
            return_value=({"folder": [1.0]}, {}, {}, {"folder": 42}, {}),
        ),
        patch(
            "src.resolver.resolve_bookmark",
            return_value=(42, ["ai:sorted:2026-09-16"], "centroid"),
        ),
        patch.object(app_module.resolver, "spawn") as spawn_resolver,
    ):
        result = app_module.resolver.local()

    assert result["status"] == "ok"
    assert result["total"] == 25
    assert result["has_more"] is True
    assert len(client.updates) == 25
    assert client.page_requests == [
        {
            "page": 0,
            "perpage": 25,
            "search": "#sorter-pending-resolution",
        }
    ]
    spawn_resolver.assert_called_once_with()


def test_resolver_skips_model_initialization_when_no_work_is_pending():
    client = FakeRaindropClient([])

    with (
        patch("src.raindrop_client.RaindropClient", return_value=client),
        patch("src.embeddings.Embedder") as embedder,
        patch.object(app_module, "_load_state") as load_state,
    ):
        result = app_module.resolver.local()

    assert result["status"] == "ok"
    assert result["total"] == 0
    embedder.assert_not_called()
    load_state.assert_not_called()


def test_resolver_leaves_vision_dispatch_to_the_bounded_cron():
    client = FakeRaindropClient(
        [
            {
                "_id": 123,
                "cover": "https://example.test/cover.jpg",
                "tags": ["sorter-pending-resolution"],
            }
        ]
    )

    with (
        patch("src.raindrop_client.RaindropClient", return_value=client),
        patch("src.embeddings.Embedder"),
        patch.object(
            app_module,
            "_load_state",
            return_value=({"folder": [1.0]}, {}, {}, {"folder": 42}, {}),
        ),
        patch(
            "src.resolver.resolve_bookmark",
            return_value=(None, ["sorter-pending-resolution"], "low_confidence"),
        ),
        patch.object(app_module.vision_worker, "spawn") as spawn_vision_worker,
    ):
        result = app_module.resolver.local()

    assert result["vision"] == 1
    assert any(
        tag.startswith("sorter-pending-vision:")
        for tag in client.updates[0][2]
    )
    spawn_vision_worker.assert_not_called()


def test_vision_worker_transitions_state_without_dispatching_resolver():
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
    spawn_resolver.assert_not_called()


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


def test_vision_worker_releases_its_dispatch_lease():
    client = FakeRaindropClient(
        [
            {
                "_id": 123,
                "cover": "https://example.test/cover.jpg",
                "tags": ["sorter-pending-vision:2026-09-16"],
            }
        ]
    )
    coordination = FakeCoordination()
    lease_owner = acquire_item_lease(
        coordination,
        app_module.VISION_DISPATCH_LEASE_PREFIX,
        123,
        100,
    )
    assert lease_owner is not None

    with (
        patch.object(app_module, "coordination", coordination),
        patch("src.raindrop_client.RaindropClient", return_value=client),
        patch("src.vision_worker.run_vision_on_bookmark", return_value=[]),
    ):
        result = app_module.vision_worker.local(123, lease_owner)

    assert result["status"] == "ok"
    assert coordination.values == {}


def test_vision_worker_does_not_use_raindrop_api_during_reindex():
    with (
        patch("src.reindex_lease.time.time", return_value=100),
        patch.object(
            app_module,
            "coordination",
            FakeCoordination({"reindex_lease_expires_at": 200}),
        ),
        patch("src.raindrop_client.RaindropClient") as client,
    ):
        result = app_module.vision_worker.local(123)

    assert result == {"status": "reindex_active", "bookmark_id": 123}
    client.assert_not_called()


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
        patch.object(app_module.resolver, "spawn") as spawn_resolver,
    ):
        result = app_module.vision_cron.local()

    assert result == {
        "status": "ok",
        "dispatched": 2,
        "skipped_inflight": 0,
        "total": 2,
        "has_more": False,
    }
    assert [call.args[0] for call in spawn_vision_worker.call_args_list] == [123, 456]
    assert all(call.args[1] for call in spawn_vision_worker.call_args_list)
    spawn_resolver.assert_called_once_with()
    assert client.updates == []


def test_vision_cron_dispatches_only_one_bounded_batch():
    client = FakeRaindropClient(
        [
            {
                "_id": item_id,
                "cover": f"https://example.test/{item_id}.jpg",
                "tags": ["sorter-pending-vision:2026-09-16"],
            }
            for item_id in range(30)
        ]
    )

    with (
        patch("src.raindrop_client.RaindropClient", return_value=client),
        patch.object(app_module.vision_worker, "spawn") as spawn_vision_worker,
        patch.object(app_module.resolver, "spawn") as spawn_resolver,
    ):
        result = app_module.vision_cron.local()

    assert result == {
        "status": "ok",
        "dispatched": 25,
        "skipped_inflight": 0,
        "total": 25,
        "has_more": True,
    }
    assert spawn_vision_worker.call_count == 25
    spawn_resolver.assert_called_once_with()
    assert client.page_requests == [
        {
            "page": 0,
            "perpage": 25,
            "search": '#"sorter-pending-vision:2026-09-16"',
        }
    ]


def test_vision_cron_does_not_redispatch_an_inflight_batch():
    client = FakeRaindropClient(
        [
            {
                "_id": 123,
                "cover": "https://example.test/first.jpg",
                "tags": ["sorter-pending-vision:2026-09-16"],
            },
            {
                "_id": 456,
                "cover": "https://example.test/second.jpg",
                "tags": ["sorter-pending-vision:2026-09-16"],
            },
        ]
    )
    coordination = FakeCoordination()

    with (
        patch("src.raindrop_client.RaindropClient", return_value=client),
        patch.object(app_module, "coordination", coordination),
        patch.object(app_module.vision_worker, "spawn") as spawn_vision_worker,
        patch.object(app_module.resolver, "spawn") as spawn_resolver,
    ):
        first = app_module.vision_cron.local()
        second = app_module.vision_cron.local()

    assert first["dispatched"] == 2
    assert first["skipped_inflight"] == 0
    assert second["dispatched"] == 0
    assert second["skipped_inflight"] == 2
    assert spawn_vision_worker.call_count == 2
    assert spawn_resolver.call_count == 2


def test_vision_cron_does_not_use_raindrop_api_during_reindex():
    with (
        patch("src.reindex_lease.time.time", return_value=100),
        patch.object(
            app_module,
            "coordination",
            FakeCoordination({"reindex_lease_expires_at": 200}),
        ),
        patch("src.raindrop_client.RaindropClient") as client,
    ):
        result = app_module.vision_cron.local()

    assert result == {"status": "reindex_active", "dispatched": 0}
    client.assert_not_called()
