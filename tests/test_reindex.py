"""Tests for the weekly re-index and learning loop."""

import os
import shutil
import tempfile

import numpy as np
import pytest

from src.reindex import (
    atomic_swap_new_db,
    build_folder_hierarchy,
    build_folder_map,
    detect_manual_corrections,
    disable_overmatched_rules,
    rebuild_index,
)
from src.state_machine import cleanup_transient_tags


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
    ):
        self._collections = collections
        self._bookmarks = {bm["_id"]: bm for bm in bookmarks}
        self._updated: list[tuple[int, dict]] = []
        self._unsorted_items = unsorted_items or []

    def get_collections(self):
        return self._collections

    def get_all_raindrops(self, collection_id):
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

    def embed(self, texts: list[str]) -> np.ndarray:
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


def test_build_folder_hierarchy():
    collections = [
        {"_id": 1, "title": "Art", "parent": {}},
        {"_id": 2, "title": "Vocaloid", "parent": {"$id": 1}},
        {"_id": 3, "title": "Touhou", "parent": {"$id": 1}},
    ]
    hierarchy = build_folder_hierarchy(collections)
    assert hierarchy == {"Art": ["Art/Vocaloid", "Art/Touhou"]}


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

def test_rebuild_index_creates_db_and_state():
    collections = [
        {"_id": 1, "title": "Art", "parent": {}},
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
        assert os.path.isfile(os.path.join(db_path, "folder_id_map.json"))


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
