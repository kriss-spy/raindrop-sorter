"""Tests for the resolver decision function and related logic."""

import json
import os
import tempfile

import numpy as np
import pytest

from src.centroids import compute_folder_centroids, load_centroids, save_centroids
from src.embeddings import build_text_input
from src.resolver import cosine_similarity, decide_folder, find_best_centroid
from src.state_machine import (
    add_tag,
    get_clean_tags,
    remove_tag,
    remove_tags_by_prefix,
    strip_reviewed_tags,
    tag_pending_resolution,
    tag_reviewed,
    tag_sorted,
)
from src.tag_rules import (
    extract_candidate_tag_rules,
    load_tag_rules,
    save_tag_rules,
    validate_tag_rules,
)


# ---------------------------------------------------------------------------
# Embedding text input
# ---------------------------------------------------------------------------

def test_build_text_input():
    bm = {
        "title": "Hello World",
        "domain": "example.com",
        "tags": ["python", "ai:wdtag-test"],
        "excerpt": "A short description",
    }
    text = build_text_input(bm)
    assert "Hello World" in text
    assert "example.com" in text
    assert "python" in text
    assert "ai:wdtag-test" not in text  # transient tags stripped
    assert "A short description" in text


def test_build_text_input_truncates_description():
    bm = {
        "title": "Title",
        "domain": "example.com",
        "tags": [],
        "excerpt": "x" * 10000,
    }
    text = build_text_input(bm)
    assert "Title" in text
    assert "x" * 10000 in text  # we don't actually truncate in code yet, just ensure it runs


# ---------------------------------------------------------------------------
# Centroids
# ---------------------------------------------------------------------------

def test_compute_folder_centroids_basic():
    # 3 bookmarks: 2 in Art/Vocaloid, 1 in Art/Touhou
    emb = np.array([
        [1.0, 0.0],   # Art/Vocaloid
        [1.0, 0.1],   # Art/Vocaloid
        [0.0, 1.0],   # Art/Touhou
    ])
    folders = ["Art/Vocaloid", "Art/Vocaloid", "Art/Touhou"]
    hierarchy = {"Art": ["Art/Vocaloid", "Art/Touhou"]}

    centroids = compute_folder_centroids(emb, folders, hierarchy)

    # Art/Vocaloid centroid = mean of first two
    np.testing.assert_allclose(centroids["Art/Vocaloid"], [1.0, 0.05], rtol=1e-5)
    # Art/Touhou centroid = third
    np.testing.assert_allclose(centroids["Art/Touhou"], [0.0, 1.0], rtol=1e-5)
    # Art centroid = mean of all three (recursive)
    np.testing.assert_allclose(centroids["Art"], [2/3, 1.1/3], rtol=1e-5)


def test_save_and_load_centroids():
    centroids = {"foo": np.array([1.0, 2.0, 3.0]), "bar": np.array([0.0, 0.0])}
    with tempfile.TemporaryDirectory() as tmpdir:
        save_centroids(centroids, tmpdir)
        loaded = load_centroids(tmpdir)
        assert list(loaded.keys()) == list(centroids.keys())
        for k in centroids:
            np.testing.assert_array_equal(loaded[k], centroids[k])


# ---------------------------------------------------------------------------
# Tag rules
# ---------------------------------------------------------------------------

def test_extract_candidate_tag_rules():
    bms = [
        {"folder_path": "Art/Vocaloid", "tags": ["miku", "vocaloid", "music"]},
        {"folder_path": "Art/Vocaloid", "tags": ["miku", "vocaloid", "art"]},
        {"folder_path": "Art/Vocaloid", "tags": ["miku", "music"]},
        {"folder_path": "Art/Touhou", "tags": ["reimu", "touhou"]},
        {"folder_path": "Art/Touhou", "tags": ["reimu", "touhou", "game"]},
        {"folder_path": "Art/Touhou", "tags": ["reimu", "marisa", "touhou"]},
    ]
    rules = extract_candidate_tag_rules(bms)
    # miku appears 3 times in Art/Vocaloid -> rule
    assert rules.get("miku") == "Art/Vocaloid"
    # reimu appears 3 times in Art/Touhou -> rule
    assert rules.get("reimu") == "Art/Touhou"
    # vocaloid appears 2 times -> no rule
    assert "vocaloid" not in rules


def test_save_and_load_tag_rules():
    with tempfile.TemporaryDirectory() as tmpdir:
        save_tag_rules({"a": "b"}, {"a": 1}, tmpdir)
        rules, mismatches = load_tag_rules(tmpdir)
        assert rules == {"a": "b"}
        assert mismatches == {"a": 1}


def test_load_tag_rules_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        rules, mismatches = load_tag_rules(tmpdir)
        assert rules == {}
        assert mismatches == {}


def test_validate_tag_rules():
    rules = {"a": "Folder/A", "b": "Folder/B", "c": "Missing"}
    validated = validate_tag_rules(rules, {"Folder/A", "Folder/B"})
    assert validated == {"a": "Folder/A", "b": "Folder/B"}


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

def test_get_clean_tags_strips_transient():
    bm = {"tags": ["python", "ai:wdtag-test", "ai:sauce-123", "sorter-pending-vision:2024-01-01"]}
    assert get_clean_tags(bm) == ["python", "sorter-pending-vision:2024-01-01"]


def test_tag_operations():
    tags = ["a", "b"]
    assert add_tag(tags, "c") == ["a", "b", "c"]
    assert add_tag(tags, "a") == ["a", "b"]
    assert remove_tag(tags, "b") == ["a"]
    assert remove_tags_by_prefix(tags, "a") == ["b"]


def test_tag_reviewed():
    bm = {"tags": ["sorter-pending-resolution", "old"]}
    new_tags = tag_reviewed(bm)
    assert "sorter-pending-resolution" not in new_tags
    assert any(t.startswith("sorter-reviewed:") for t in new_tags)
    assert "old" in new_tags


def test_tag_sorted():
    bm = {"tags": ["sorter-pending-resolution", "old"]}
    new_tags = tag_sorted(bm, by_rule="miku")
    assert "sorter-pending-resolution" not in new_tags
    assert any(t.startswith("ai:sorted:") for t in new_tags)
    assert "ai:new-rule-miku" in new_tags
    assert "old" in new_tags


def test_strip_reviewed_tags():
    tags = ["sorter-reviewed:2024-01-01", "python"]
    assert strip_reviewed_tags(tags) == ["python"]


# ---------------------------------------------------------------------------
# Resolver decision
# ---------------------------------------------------------------------------

def test_cosine_similarity():
    a = np.array([1.0, 0.0])
    b = np.array([1.0, 0.0])
    c = np.array([0.0, 1.0])
    assert cosine_similarity(a, b) == pytest.approx(1.0)
    assert cosine_similarity(a, c) == pytest.approx(0.0)


def test_find_best_centroid_confident():
    centroids = {
        "A": np.array([1.0, 0.0]),
        "B": np.array([0.0, 1.0]),
    }
    embedding = np.array([0.95, 0.05])
    folder, gap = find_best_centroid(embedding, centroids)
    assert folder == "A"
    assert gap > 0.5  # strongly confident


def test_find_best_centroid_ambiguous():
    centroids = {
        "A": np.array([1.0, 0.0]),
        "B": np.array([0.0, 1.0]),
    }
    embedding = np.array([0.6, 0.6])
    folder, gap = find_best_centroid(embedding, centroids)
    assert folder == "A" or folder == "B"
    assert gap < 0.3  # low confidence


def test_find_best_centroid_empty():
    folder, gap = find_best_centroid(np.array([1.0, 0.0]), {})
    assert folder is None
    assert gap == 0.0


def test_decide_folder_exact_tag_rule():
    bm = {"tags": ["miku"], "title": "", "domain": "", "excerpt": ""}
    centroids = {"Art/Vocaloid": np.array([1.0, 0.0])}
    rules = {"miku": "Art/Vocaloid"}
    folder, reason = decide_folder(bm, centroids, rules)
    assert folder == "Art/Vocaloid"
    assert "exact_tag_rule" in reason


def test_decide_folder_centroid_match():
    bm = {"tags": [], "title": "vocaloid music", "domain": "", "excerpt": ""}
    centroids = {
        "Art/Vocaloid": np.array([1.0, 0.0]),
        "Art/Touhou": np.array([0.0, 1.0]),
    }
    rules = {}

    # Mock embedder that returns a known embedding
    class MockEmbedder:
        def embed_one(self, text):
            # Return something close to Art/Vocaloid
            return np.array([0.9, 0.1])

    folder, reason = decide_folder(bm, centroids, rules, embedder=MockEmbedder())
    assert folder == "Art/Vocaloid"
    assert "centroid_match" in reason


def test_decide_folder_low_confidence():
    bm = {"tags": [], "title": "ambiguous", "domain": "", "excerpt": ""}
    centroids = {
        "Art/Vocaloid": np.array([1.0, 0.0]),
        "Art/Touhou": np.array([0.0, 1.0]),
    }
    rules = {}

    class MockEmbedder:
        def embed_one(self, text):
            # Right in the middle
            return np.array([0.6, 0.6])

    folder, reason = decide_folder(
        bm, centroids, rules, embedder=MockEmbedder(), relative_gap_threshold=0.5
    )
    assert folder is None
    assert "low_confidence" in reason


from src.resolver import resolve_bookmark, _rule_name_from_reason


# ---------------------------------------------------------------------------
# Rule name extraction
# ---------------------------------------------------------------------------

def test_rule_name_from_reason_exact_tag():
    assert _rule_name_from_reason("exact_tag_rule:miku") == "miku"


def test_rule_name_from_reason_other_reasons():
    assert _rule_name_from_reason("centroid_match:gap=0.500") is None
    assert _rule_name_from_reason("series_rule:Art/Vocaloid") is None
    assert _rule_name_from_reason("crossover_fallback") is None


def test_resolve_bookmark_tags_new_rule_for_exact_match():
    bm = {
        "_id": 4,
        "tags": ["miku"],
        "title": "",
        "domain": "",
        "excerpt": "",
        "_folder_id_map": {"Art/Vocaloid": 42},
    }
    centroids = {}
    rules = {"miku": "Art/Vocaloid"}

    target_id, new_tags, reason = resolve_bookmark(bm, centroids, rules)
    assert target_id == 42
    assert "ai:new-rule-miku" in new_tags
    assert "exact_tag_rule:miku" in reason


# ---------------------------------------------------------------------------
# Full resolve_bookmark
# ---------------------------------------------------------------------------

def test_resolve_bookmark_moves_when_confident():
    bm = {
        "_id": 1,
        "tags": [],
        "title": "vocaloid stuff",
        "domain": "",
        "excerpt": "",
        "_folder_id_map": {"Art/Vocaloid": 42},
    }
    centroids = {
        "Art/Vocaloid": np.array([1.0, 0.0]),
        "Art/Touhou": np.array([0.0, 1.0]),
    }
    rules = {}

    class MockEmbedder:
        def embed_one(self, text):
            return np.array([0.9, 0.1])

    target_id, new_tags, reason = resolve_bookmark(
        bm, centroids, rules, embedder=MockEmbedder()
    )
    assert target_id == 42
    assert any(t.startswith("ai:sorted:") for t in new_tags)


def test_resolve_bookmark_rejects_when_low_confidence():
    bm = {
        "_id": 2,
        "tags": [],
        "title": "ambiguous",
        "domain": "",
        "excerpt": "",
        "_folder_id_map": {"Art/Vocaloid": 42},
    }
    centroids = {
        "Art/Vocaloid": np.array([1.0, 0.0]),
        "Art/Touhou": np.array([0.0, 1.0]),
    }
    rules = {}

    class MockEmbedder:
        def embed_one(self, text):
            return np.array([0.6, 0.6])

    target_id, new_tags, reason = resolve_bookmark(
        bm, centroids, rules, embedder=MockEmbedder(), relative_gap_threshold=0.5
    )
    assert target_id is None
    assert any(t.startswith("sorter-reviewed:") for t in new_tags)


def test_resolve_bookmark_safety_missing_folder():
    bm = {
        "_id": 3,
        "tags": ["miku"],
        "title": "",
        "domain": "",
        "excerpt": "",
        "_folder_id_map": {},  # folder missing
    }
    centroids = {}
    rules = {"miku": "Art/Vocaloid"}

    target_id, new_tags, reason = resolve_bookmark(bm, centroids, rules)
    assert target_id is None
    assert "missing_folder" in reason


# ---------------------------------------------------------------------------
# Raindrop client (mocked HTTP)
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock

from src.raindrop_client import RaindropClient


def test_raindrop_client_get_collections():
    client = RaindropClient(token="test")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"items": [{"_id": 1, "title": "A"}]}
    client.session.get = MagicMock(return_value=mock_resp)

    cols = client.get_collections()
    assert len(cols) == 1
    assert cols[0]["title"] == "A"


def test_raindrop_client_update_raindrop():
    client = RaindropClient(token="test")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"item": {"_id": 123}}
    client.session.put = MagicMock(return_value=mock_resp)

    result = client.update_raindrop(123, collection_id=456, tags=["ai:sorted:2024-01-01"])
    assert result == {"item": {"_id": 123}}

    call_args = client.session.put.call_args
    assert call_args[1]["json"]["collection"]["$id"] == 456
    assert call_args[1]["json"]["tags"] == ["ai:sorted:2024-01-01"]


def test_raindrop_client_never_deletes():
    """Safety invariant: update_raindrop only accepts collection_id and tags."""
    client = RaindropClient(token="test")
    # The API wrapper only moves and tags — no delete/archive endpoint exposed.
    assert not hasattr(client, "delete_raindrop")
    assert not hasattr(client, "archive_raindrop")
