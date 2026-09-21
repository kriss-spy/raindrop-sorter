"""Tests for the weekly re-index and learning loop."""

import os
import shutil
import tempfile
import json

import numpy as np
import pytest

from bootstrap import bootstrap as bootstrap_index, crawl_all_bookmarks
from src.reindex import (
    atomic_swap_new_db,
    build_folder_hierarchy,
    build_folder_map,
    detect_manual_corrections,
    disable_overmatched_rules,
    rebuild_index,
)
from src.state_machine import cleanup_transient_tags
from src.tag_rules import load_tag_rules
from src.visual_learning import VisualLearningConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeRaindropClient:
    """In-memory Raindrop client for testing re-index logic."""

    def __init__(
        self,
        collections: list[dict],
        bookmarks: list[dict],
        unsorted_items: list[dict] | None = None,
        groups: list[dict] | None = None,
    ):
        self._collections = collections
        self._bookmarks = {bm["_id"]: bm for bm in bookmarks}
        self._updated: list[tuple[int, dict]] = []
        self._unsorted_items = unsorted_items or []
        self._groups = groups or []
        self.collection_reads: list[int] = []

    def get_collections(self):
        return self._collections

    def get_collection_groups(self):
        return self._groups

    def get_all_raindrops(self, collection_id):
        self.collection_reads.append(collection_id)
        if collection_id == 0:
            return [*self._bookmarks.values(), *self._unsorted_items]
        if collection_id == -1:
            return self._unsorted_items
        return [bm for bm in self._bookmarks.values() if bm.get("_collection_id") == collection_id]

    def update_raindrop(self, raindrop_id, collection_id=None, tags=None):
        bm = self._bookmarks.get(raindrop_id, {})
        if collection_id is not None:
            bm["_collection_id"] = collection_id
        if tags is not None:
            bm["tags"] = tags
        self._updated.append((raindrop_id, {"collection_id": collection_id, "tags": tags}))
        return {"item": {"_id": raindrop_id}}


class FakeEmbedder:
    """Deterministic embedder for testing."""

    def __init__(self, dim: int = 2):
        self.dim = dim
        self.batch_sizes: list[int] = []

    def embed(self, texts: list[str]) -> np.ndarray:
        self.batch_sizes.append(len(texts))
        rng = np.random.default_rng(42)
        return rng.random((len(texts), self.dim)).astype(np.float32)

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


# ---------------------------------------------------------------------------
# Folder mapping
# ---------------------------------------------------------------------------

def test_build_folder_map():
    collections = [
        {"_id": 1, "title": "Art", "parent": {}},
        {"_id": 2, "title": "Vocaloid", "parent": {"$id": 1}},
        {"_id": 3, "title": "Touhou", "parent": {"$id": 1}},
    ]
    folder_map = build_folder_map(collections)
    assert folder_map == {
        "Art": 1,
        "Art/Vocaloid": 2,
        "Art/Touhou": 3,
    }


def test_build_folder_map_uses_ui_group_to_distinguish_duplicate_root_names():
    collections = [
        {"_id": 1, "title": "VOCALOID", "parent": None},
        {"_id": 2, "title": "VOCALOID", "parent": None},
        {"_id": 3, "title": "VOCALOID", "parent": None},
    ]
    groups = [
        {"title": "Art", "collections": [1]},
        {"title": "Music", "collections": [2]},
        {"title": "Video", "collections": [3]},
    ]

    assert build_folder_map(collections, groups) == {
        "Art/VOCALOID": 1,
        "Music/VOCALOID": 2,
        "Video/VOCALOID": 3,
    }


def test_build_folder_map_does_not_repeat_equivalent_group_and_root_names():
    collections = [
        {"_id": 10, "title": "GAMES", "parent": None},
        {"_id": 11, "title": "BA", "parent": {"$id": 10}},
    ]
    groups = [{"title": "Games", "collections": [10]}]

    assert build_folder_map(collections, groups) == {
        "GAMES": 10,
        "GAMES/BA": 11,
    }


def test_build_folder_map_rejects_duplicate_canonical_paths():
    collections = [
        {"_id": 1, "title": "VOCALOID", "parent": None},
        {"_id": 2, "title": "VOCALOID", "parent": None},
    ]

    with pytest.raises(
        ValueError,
        match=r"Duplicate canonical collection path 'VOCALOID'.*1.*2.*groups",
    ):
        build_folder_map(collections)


def test_build_folder_map_rejects_root_listed_in_multiple_groups():
    collections = [{"_id": 1, "title": "VOCALOID", "parent": None}]
    groups = [
        {"title": "Art", "collections": [1]},
        {"title": "Music", "collections": [1]},
    ]

    with pytest.raises(
        ValueError,
        match=r"collection ID 1.*multiple groups.*Art.*Music",
    ):
        build_folder_map(collections, groups)


def test_build_folder_hierarchy():
    collections = [
        {"_id": 1, "title": "Art", "parent": {}},
        {"_id": 2, "title": "Vocaloid", "parent": {"$id": 1}},
        {"_id": 3, "title": "Touhou", "parent": {"$id": 1}},
    ]
    hierarchy = build_folder_hierarchy(collections)
    assert hierarchy == {"Art": ["Art/Vocaloid", "Art/Touhou"]}


def test_build_folder_hierarchy_uses_group_aware_collection_paths_only():
    collections = [
        {"_id": 1, "title": "VOCALOID", "parent": None},
        {"_id": 2, "title": "Miku", "parent": {"$id": 1}},
    ]
    groups = [{"title": "Art", "collections": [1]}]

    assert build_folder_hierarchy(collections, groups) == {
        "Art/VOCALOID": ["Art/VOCALOID/Miku"],
    }


# ---------------------------------------------------------------------------
# Manual correction detection
# ---------------------------------------------------------------------------

def test_detect_manual_corrections_bumps_mismatch():
    live_bookmarks = [
        {"_id": 1, "folder_path": "Art/Touhou", "tags": ["miku"]},
    ]
    previous_metadata = {
        "1": {"last_seen_folder": "Art/Vocaloid"},
    }
    rules = {"miku": "Art/Vocaloid"}
    mismatches = {}

    updated = detect_manual_corrections(live_bookmarks, previous_metadata, rules, mismatches)
    assert updated["miku"] == 1


def test_detect_manual_corrections_ignores_unchanged():
    live_bookmarks = [
        {"_id": 1, "folder_path": "Art/Vocaloid", "tags": ["miku"]},
    ]
    previous_metadata = {
        "1": {"last_seen_folder": "Art/Vocaloid"},
    }
    rules = {"miku": "Art/Vocaloid"}
    mismatches = {}

    updated = detect_manual_corrections(live_bookmarks, previous_metadata, rules, mismatches)
    assert updated == {}


def test_detect_manual_corrections_normalizes_wd14_tags():
    live_bookmarks = [
        {"_id": 1, "folder_path": "Art/Touhou", "tags": ["ai:wdtag-miku"]},
    ]
    previous_metadata = {
        "1": {"last_seen_folder": "Art/Vocaloid"},
    }
    rules = {"miku": "Art/Vocaloid"}
    mismatches = {}

    updated = detect_manual_corrections(live_bookmarks, previous_metadata, rules, mismatches)
    assert updated["miku"] == 1


def test_detect_manual_corrections_handles_group_specific_rule_candidates():
    live_bookmarks = [
        {"_id": 1, "folder_path": "Music/VOCALOID", "tags": ["vocaloid"]},
    ]
    previous_metadata = {
        "1": {"last_seen_folder": "Art/VOCALOID"},
    }
    rules = {"vocaloid": ["Art/VOCALOID", "Music/VOCALOID"]}

    updated = detect_manual_corrections(live_bookmarks, previous_metadata, rules, {})

    assert updated["vocaloid"] == 1


# ---------------------------------------------------------------------------
# Rule disablement
# ---------------------------------------------------------------------------

def test_disable_overmatched_rules():
    rules = {"a": "Folder/A", "b": "Folder/B", "c": "Folder/C"}
    mismatches = {"a": 2, "b": 3, "c": 4}

    kept_rules, kept_mismatches = disable_overmatched_rules(rules, mismatches, max_mismatches=3)

    assert kept_rules == {"a": "Folder/A", "b": "Folder/B"}
    assert kept_mismatches == {"a": 2, "b": 3}


# ---------------------------------------------------------------------------
# Atomic swap
# ---------------------------------------------------------------------------

def test_atomic_swap_new_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        current = os.path.join(tmpdir, "chroma_db")
        new_path = os.path.join(tmpdir, "chroma_db_new")

        os.makedirs(current)
        os.makedirs(new_path)
        with open(os.path.join(current, "old.txt"), "w") as f:
            f.write("old")
        with open(os.path.join(new_path, "new.txt"), "w") as f:
            f.write("new")

        atomic_swap_new_db(new_path, current)

        assert os.path.isfile(os.path.join(current, "new.txt"))
        assert not os.path.exists(new_path)
        assert not os.path.exists(os.path.join(tmpdir, "chroma_db_old"))


# ---------------------------------------------------------------------------
# Full re-index flow
# ---------------------------------------------------------------------------

def test_rebuild_index_without_bookmarks_reports_crawl_metrics():
    with tempfile.TemporaryDirectory() as tmpdir:
        client = FakeRaindropClient([], [])
        result = rebuild_index(
            client,
            FakeEmbedder(dim=8),
            db_path=os.path.join(tmpdir, "chroma_db"),
        )

    assert result["status"] == "no_bookmarks"
    assert result["timings_seconds"]["crawl"] >= 0
    assert result["timings_seconds"]["total"] >= 0
    assert result["raindrop_requests"] == 0
    assert result["rate_limit_wait_seconds"] == 0.0


def test_rebuild_index_persists_group_aware_collection_routes():
    collections = [
        {"_id": 1, "title": "VOCALOID", "parent": None},
        {"_id": 2, "title": "VOCALOID", "parent": None},
    ]
    groups = [
        {"title": "Art", "collections": [1]},
        {"title": "Music", "collections": [2]},
    ]
    bookmarks = [
        {"_id": 101, "title": "Miku image", "collection": {"$id": 1}, "tags": []},
        {"_id": 102, "title": "Miku song", "collection": {"$id": 2}, "tags": []},
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "chroma_db")
        rebuild_index(
            FakeRaindropClient(collections, bookmarks, groups=groups),
            FakeEmbedder(dim=8),
            db_path=db_path,
        )
        with open(os.path.join(db_path, "folder_id_map.json"), encoding="utf-8") as f:
            folder_map = json.load(f)

    assert folder_map == {"Art/VOCALOID": 1, "Music/VOCALOID": 2}


def test_bootstrap_crawl_assigns_group_aware_folder_paths():
    collections = [
        {"_id": 1, "title": "VOCALOID", "parent": None},
        {"_id": 2, "title": "VOCALOID", "parent": None},
    ]
    bookmarks = [
        {"_id": 101, "_collection_id": 1, "tags": []},
        {"_id": 102, "_collection_id": 2, "tags": []},
    ]
    client = FakeRaindropClient(
        collections,
        bookmarks,
        groups=[
            {"title": "Art", "collections": [1]},
            {"title": "Music", "collections": [2]},
        ],
    )

    crawled, _collections, groups = crawl_all_bookmarks(client)

    assert groups == client._groups
    assert {item["folder_path"] for item in crawled} == {
        "Art/VOCALOID",
        "Music/VOCALOID",
    }


def test_bootstrap_persists_bounded_visual_rules(tmp_path, monkeypatch):
    collections = [
        {"_id": 1, "title": "TOUHOU", "parent": None},
        {"_id": 2, "title": "BA", "parent": None},
    ]
    bookmarks = [
        {"_id": 101, "_collection_id": 1, "title": "Reimu", "cover": "1.jpg", "tags": []},
        {"_id": 102, "_collection_id": 1, "title": "Reimu 2", "cover": "2.jpg", "tags": []},
        {"_id": 103, "_collection_id": 2, "title": "Hina", "cover": "3.jpg", "tags": []},
    ]
    client = FakeRaindropClient(
        collections,
        bookmarks,
        groups=[{"title": "Art", "collections": [1, 2]}],
    )
    detected = {
        101: ["hakurei_reimu"],
        102: ["hakurei_reimu"],
        103: ["hina_(blue_archive)"],
    }
    monkeypatch.setattr("bootstrap.Embedder", lambda: FakeEmbedder(dim=8))

    bootstrap_index(
        client,
        db_path=str(tmp_path),
        visual_analyzer=lambda bookmark: detected[bookmark["_id"]],
        visual_learning_config=VisualLearningConfig(
            max_samples=3,
            min_tag_support=2,
            min_tag_purity=0.9,
            stability_patience=10,
            min_folder_rounds=1,
        ),
    )

    rules, _mismatches = load_tag_rules(str(tmp_path))
    assert rules["hakurei_reimu"] == "Art/TOUHOU"
    metrics = json.loads((tmp_path / "visual_learning.json").read_text())
    assert metrics["samples_analyzed"] == 3
    assert metrics["rules_learned"] == 1
    assert metrics["stop_reason"] == "sample_budget"
    import chromadb

    indexed = chromadb.PersistentClient(path=str(tmp_path)).get_collection("bookmarks")
    stored = indexed.get(ids=["101"], include=["metadatas"])
    assert "ai:wdtag-hakurei_reimu" in stored["metadatas"][0]["tags"]


def test_rebuild_index_creates_db_and_state():
    collections = [
        {"_id": 1, "title": "Art", "parent": None},
        {"_id": 2, "title": "Vocaloid", "parent": {"$id": 1}},
    ]
    bookmarks = [
        {
            "_id": 101,
            "title": "Miku art",
            "domain": "example.com",
            "tags": ["miku", "vocaloid", "music"],
            "excerpt": "",
            "folder_path": "Art/Vocaloid",
            "_collection_id": 2,
        },
        {
            "_id": 102,
            "title": "Miku music",
            "domain": "example.com",
            "tags": ["miku", "vocaloid", "music"],
            "excerpt": "",
            "folder_path": "Art/Vocaloid",
            "_collection_id": 2,
        },
        {
            "_id": 103,
            "title": "Miku again",
            "domain": "example.com",
            "tags": ["miku", "art"],
            "excerpt": "",
            "folder_path": "Art/Vocaloid",
            "_collection_id": 2,
        },
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "chroma_db")
        client = FakeRaindropClient(collections, bookmarks)
        embedder = FakeEmbedder(dim=8)

        result = rebuild_index(client, embedder, db_path=db_path)

        assert result["status"] == "ok"
        assert result["processed"] == 3
        assert result["rules"] == 1  # miku rule extracted
        assert os.path.isfile(os.path.join(db_path, "centroids.json"))
        assert os.path.isfile(os.path.join(db_path, "tag_rules.json"))
        assert os.path.isfile(os.path.join(db_path, "series_rules.json"))
        assert os.path.isfile(os.path.join(db_path, "folder_id_map.json"))
        assert set(result["timings_seconds"]) == {
            "crawl",
            "prepare",
            "embed",
            "index",
            "total",
        }
        assert result["raindrop_requests"] == 0
        assert result["rate_limit_wait_seconds"] == 0.0
        assert client.collection_reads == [0]


def test_rebuild_index_embeds_large_libraries_in_bounded_chunks():
    collections = [{"_id": 1, "title": "Archive", "parent": None}]
    bookmarks = [
        {
            "_id": bookmark_id,
            "title": f"Bookmark {bookmark_id}",
            "collection": {"$id": 1},
            "tags": [],
        }
        for bookmark_id in range(600)
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        embedder = FakeEmbedder(dim=8)
        result = rebuild_index(
            FakeRaindropClient(collections, bookmarks),
            embedder,
            db_path=os.path.join(tmpdir, "chroma_db"),
        )

    assert result["status"] == "ok"
    assert sum(embedder.batch_sizes) == 600
    assert len(embedder.batch_sizes) > 1
    assert max(embedder.batch_sizes) <= 256


def test_rebuild_index_detects_manual_corrections_and_disables_rule():
    collections = [
        {"_id": 1, "title": "Art", "parent": {}},
        {"_id": 2, "title": "Vocaloid", "parent": {"$id": 1}},
        {"_id": 3, "title": "Touhou", "parent": {"$id": 1}},
    ]
    bookmarks = [
        {
            "_id": 101,
            "title": "Miku moved",
            "domain": "example.com",
            "tags": ["miku"],
            "excerpt": "",
            "folder_path": "Art/Touhou",
            "_collection_id": 3,
        },
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "chroma_db")
        os.makedirs(db_path)

        # Seed old metadata and rules via a real ChromaDB collection
        import chromadb
        import json
        from src.centroids import save_centroids
        from src.tag_rules import save_tag_rules

        chroma_client = chromadb.PersistentClient(path=db_path)
        collection = chroma_client.get_or_create_collection(name="bookmarks")
        collection.add(
            ids=["101"],
            embeddings=[[0.0] * 8],
            metadatas=[{"last_seen_folder": "Art/Vocaloid"}],
        )
        del chroma_client, collection
        import gc
        gc.collect()

        save_tag_rules({"miku": "Art/Vocaloid"}, {"miku": 3}, db_path)
        save_centroids({"Art": np.zeros(8)}, db_path)
        with open(os.path.join(db_path, "folder_id_map.json"), "w") as f:
            json.dump({"Art": 1, "Art/Vocaloid": 2, "Art/Touhou": 3}, f)

        client = FakeRaindropClient(collections, bookmarks)
        embedder = FakeEmbedder(dim=8)

        result = rebuild_index(client, embedder, db_path=db_path)

        assert result["status"] == "ok"
        assert result["disabled_rules"] == 1  # miku rule disabled after 4th mismatch


def test_rebuild_index_strips_reviewed_tags_from_unsorted():
    collections = [
        {"_id": -1, "title": "Unsorted", "parent": {}},
        {"_id": 1, "title": "Art", "parent": {}},
    ]
    unsorted_items = [
        {
            "_id": 201,
            "title": "Reviewed item",
            "domain": "example.com",
            "tags": ["sorter-reviewed:2024-01-01", "miku"],
            "excerpt": "",
            "folder_path": "Unsorted",
            "_collection_id": -1,
        },
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "chroma_db")
        client = FakeRaindropClient(collections, [], unsorted_items=unsorted_items)
        embedder = FakeEmbedder(dim=8)

        result = rebuild_index(client, embedder, db_path=db_path)

        assert result["status"] == "ok"
        assert result["retried"] == 1
        assert any(
            call[0] == 201 and "sorter-reviewed" not in (call[1].get("tags") or [])
            for call in client._updated
        )


# ---------------------------------------------------------------------------
# Transient tag cleanup
# ---------------------------------------------------------------------------

def test_cleanup_transient_tags():
    tags = ["miku", "ai:wdtag-hatsune_miku", "ai:sauce-123", "sorter-reviewed:2024-01-01"]
    cleaned = cleanup_transient_tags(tags)
    assert cleaned == ["miku", "sorter-reviewed:2024-01-01"]
