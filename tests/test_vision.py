"""Tests for vision worker, WD14 tagger, and resolver series logic."""

import io
import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.resolver import decide_folder, resolve_bookmark, _normalized_tags
from src.state_machine import (
    has_vision_tags,
    is_pending_vision,
    tag_after_vision,
    tag_reviewed,
)
from src.tag_rules import (
    load_series_rules,
    save_series_rules,
    validate_series_rules,
)
from src.vision_worker import download_cover, run_vision_on_bookmark
from src.wd14_tagger import normalize_tag, WD14Tagger


# ---------------------------------------------------------------------------
# WD14 tag normalization
# ---------------------------------------------------------------------------

def test_normalize_tag_basic():
    assert normalize_tag("Hatsune Miku") == "hatsune_miku"
    assert normalize_tag("1girl") == "1girl"
    assert normalize_tag("VOCALOID") == "vocaloid"


def test_normalize_tag_idempotent():
    assert normalize_tag("hatsune_miku") == "hatsune_miku"


# ---------------------------------------------------------------------------
# WD14Tagger prediction (mocked ONNX)
# ---------------------------------------------------------------------------

def test_wd14_tagger_predict():
    """Mock ONNX session and verify tag thresholding."""
    tagger = WD14Tagger(model_dir="/tmp/fake_wd14", threshold=0.5)

    # Mock internals
    mock_session = MagicMock()
    mock_session.get_inputs.return_value = [MagicMock(name="input")]
    # Simulate 3 tags with probs [0.9, 0.3, 0.6]
    mock_session.run.return_value = [np.array([[0.9, 0.3, 0.6]])]
    tagger._session = mock_session
    tagger._tags = ["hatsune_miku", "1girl", "vocaloid"]

    # Create a tiny RGB image
    from PIL import Image
    img = Image.new("RGB", (448, 448), color=(255, 0, 0))

    tags = tagger.predict(img)
    assert "hatsune_miku" in tags
    assert "vocaloid" in tags
    assert "1girl" not in tags  # below threshold


def test_wd14_tagger_predict_bytes():
    """Predict from raw image bytes."""
    tagger = WD14Tagger(model_dir="/tmp/fake_wd14", threshold=0.0)

    mock_session = MagicMock()
    mock_session.get_inputs.return_value = [MagicMock(name="input")]
    mock_session.run.return_value = [np.array([[0.5]])]
    tagger._session = mock_session
    tagger._tags = ["test_tag"]

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (448, 448)).save(buf, format="PNG")

    tags = tagger.predict(buf.getvalue())
    assert tags == ["test_tag"]


# ---------------------------------------------------------------------------
# Cover download
# ---------------------------------------------------------------------------

@patch("src.vision_worker.requests.get")
def test_download_cover_success(mock_get):
    mock_get.return_value = MagicMock(content=b"fake_image", raise_for_status=lambda: None)
    result = download_cover("http://example.com/cover.jpg")
    assert result == b"fake_image"


@patch("src.vision_worker.requests.get")
def test_download_cover_failure(mock_get):
    mock_get.side_effect = Exception("timeout")
    result = download_cover("http://example.com/cover.jpg")
    assert result is None


# ---------------------------------------------------------------------------
# Vision worker bookmark processing
# ---------------------------------------------------------------------------

def test_run_vision_on_bookmark_no_cover():
    bm = {"cover": ""}
    assert run_vision_on_bookmark(bm) == []


def test_run_vision_on_bookmark_with_cover():
    bm = {"cover": "http://example.com/cover.jpg"}

    mock_tagger = MagicMock()
    mock_tagger.predict.return_value = ["hatsune_miku", "vocaloid"]

    with patch("src.vision_worker.download_cover", return_value=b"img"):
        tags = run_vision_on_bookmark(bm, tagger=mock_tagger)

    assert "ai:wdtag-hatsune_miku" in tags
    assert "ai:wdtag-vocaloid" in tags
    mock_tagger.predict.assert_called_once_with(b"img")


def test_run_vision_on_bookmark_dead_url():
    bm = {"cover": "http://example.com/dead.jpg"}
    with patch("src.vision_worker.download_cover", return_value=None):
        tags = run_vision_on_bookmark(bm)
    assert tags == []


# ---------------------------------------------------------------------------
# Resolver: normalized tags
# ---------------------------------------------------------------------------

def test_normalized_tags():
    assert _normalized_tags(["ai:wdtag-hatsune_miku", "user_tag"]) == [
        "hatsune_miku",
        "user_tag",
    ]
    assert _normalized_tags(["plain_tag"]) == ["plain_tag"]
    assert _normalized_tags([]) == []


# ---------------------------------------------------------------------------
# Resolver: exact tag rules with vision tags
# ---------------------------------------------------------------------------

def test_decide_folder_vision_tag_exact_rule():
    bm = {
        "tags": ["ai:wdtag-hatsune_miku"],
        "title": "",
        "domain": "",
        "excerpt": "",
    }
    centroids = {"Art/Vocaloid": np.array([1.0, 0.0])}
    rules = {"hatsune_miku": "Art/Vocaloid/Hatsune Miku"}
    folder, reason = decide_folder(bm, centroids, rules)
    assert folder == "Art/Vocaloid/Hatsune Miku"
    assert "exact_tag_rule" in reason


# ---------------------------------------------------------------------------
# Resolver: series rules
# ---------------------------------------------------------------------------

def test_decide_folder_series_rule():
    bm = {
        "tags": ["ai:wdtag-vocaloid", "ai:wdtag-hatsune_miku"],
        "title": "",
        "domain": "",
        "excerpt": "",
    }
    centroids = {"Art/Vocaloid": np.array([1.0, 0.0])}
    rules = {}
    series_rules = {"vocaloid": "Art/Vocaloid"}
    folder, reason = decide_folder(bm, centroids, rules, series_rules=series_rules)
    assert folder == "Art/Vocaloid"
    assert "series_rule" in reason


def test_decide_folder_crossover_fallback():
    bm = {
        "tags": ["ai:wdtag-vocaloid", "ai:wdtag-touhou"],
        "title": "",
        "domain": "",
        "excerpt": "",
    }
    centroids = {}
    rules = {}
    series_rules = {
        "vocaloid": "Art/Vocaloid",
        "touhou": "Art/Touhou",
    }
    folder, reason = decide_folder(
        bm, centroids, rules, series_rules=series_rules, crossover_folder="Art/ANIME"
    )
    assert folder == "Art/ANIME"
    assert reason == "crossover_fallback"


def test_decide_folder_no_series_rules():
    bm = {
        "tags": ["ai:wdtag-vocaloid"],
        "title": "",
        "domain": "",
        "excerpt": "",
    }
    centroids = {"Art/Vocaloid": np.array([1.0, 0.0])}
    rules = {}
    # No series rules -> falls through to centroid matching
    class MockEmbedder:
        def embed_one(self, text):
            return np.array([0.9, 0.1])

    folder, reason = decide_folder(
        bm, centroids, rules, embedder=MockEmbedder(), series_rules={}
    )
    assert folder == "Art/Vocaloid"
    assert "centroid_match" in reason


# ---------------------------------------------------------------------------
# Resolver: priority order (exact > series > crossover > centroid)
# ---------------------------------------------------------------------------

def test_decide_folder_priority_exact_over_series():
    bm = {
        "tags": ["ai:wdtag-hatsune_miku", "ai:wdtag-vocaloid"],
        "title": "",
        "domain": "",
        "excerpt": "",
    }
    centroids = {}
    rules = {"hatsune_miku": "Art/Vocaloid/Hatsune Miku"}
    series_rules = {"vocaloid": "Art/Vocaloid"}
    folder, reason = decide_folder(bm, centroids, rules, series_rules=series_rules)
    assert folder == "Art/Vocaloid/Hatsune Miku"
    assert "exact_tag_rule" in reason


# ---------------------------------------------------------------------------
# Full resolve_bookmark with vision tags
# ---------------------------------------------------------------------------

def test_resolve_bookmark_vision_to_series():
    bm = {
        "_id": 1,
        "tags": ["ai:wdtag-touhou", "ai:wdtag-hakurei_reimu"],
        "title": "",
        "domain": "",
        "excerpt": "",
        "_folder_id_map": {"Art/Touhou": 42},
    }
    centroids = {}
    rules = {}
    series_rules = {"touhou": "Art/Touhou"}

    target_id, new_tags, reason = resolve_bookmark(
        bm, centroids, rules, series_rules=series_rules
    )
    assert target_id == 42
    assert "series_rule" in reason
    assert any(t.startswith("ai:sorted:") for t in new_tags)


def test_resolve_bookmark_crossover_to_anime():
    bm = {
        "_id": 2,
        "tags": ["ai:wdtag-vocaloid", "ai:wdtag-touhou"],
        "title": "",
        "domain": "",
        "excerpt": "",
        "_folder_id_map": {"Art/ANIME": 99},
    }
    centroids = {}
    rules = {}
    series_rules = {
        "vocaloid": "Art/Vocaloid",
        "touhou": "Art/Touhou",
    }

    target_id, new_tags, reason = resolve_bookmark(
        bm, centroids, rules, series_rules=series_rules, crossover_folder="Art/ANIME"
    )
    assert target_id == 99
    assert reason == "crossover_fallback"


# ---------------------------------------------------------------------------
# State machine: vision helpers
# ---------------------------------------------------------------------------

def test_has_vision_tags():
    assert has_vision_tags({"tags": ["ai:wdtag-test"]}) is True
    assert has_vision_tags({"tags": ["user_tag"]}) is False
    assert has_vision_tags({"tags": []}) is False


def test_is_pending_vision():
    assert is_pending_vision({"tags": ["sorter-pending-vision:2024-01-01"]}) is True
    assert is_pending_vision({"tags": ["sorter-pending-resolution"]}) is False


def test_tag_after_vision_preserves_wd14_tags():
    bm = {"tags": ["sorter-pending-vision:2024-01-01", "ai:wdtag-hatsune_miku", "user"], "title":"", "domain":"", "excerpt":""}
    new_tags = tag_after_vision(bm)
    assert "ai:wdtag-hatsune_miku" in new_tags
    assert "user" in new_tags
    assert "sorter-pending-resolution" in new_tags
    assert not any(t.startswith("sorter-pending-vision") for t in new_tags)


def test_tag_reviewed_preserves_wd14_tags():
    bm = {"tags": ["sorter-pending-resolution", "ai:wdtag-hatsune_miku", "user"], "title":"", "domain":"", "excerpt":""}
    new_tags = tag_reviewed(bm)
    assert "ai:wdtag-hatsune_miku" in new_tags
    assert "user" in new_tags
    assert any(t.startswith("sorter-reviewed:") for t in new_tags)
    assert "sorter-pending-resolution" not in new_tags


# ---------------------------------------------------------------------------
# Series rules persistence
# ---------------------------------------------------------------------------

def test_save_and_load_series_rules():
    with tempfile.TemporaryDirectory() as tmpdir:
        save_series_rules({"vocaloid": "Art/Vocaloid"}, tmpdir)
        loaded = load_series_rules(tmpdir)
        assert loaded == {"vocaloid": "Art/Vocaloid"}


def test_load_series_rules_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        loaded = load_series_rules(tmpdir)
        assert loaded == {}


def test_validate_series_rules():
    rules = {"vocaloid": "Art/Vocaloid", "missing": "Art/Missing"}
    validated = validate_series_rules(rules, {"Art/Vocaloid"})
    assert validated == {"vocaloid": "Art/Vocaloid"}
