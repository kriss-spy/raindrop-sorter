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
    VISION_ATTEMPTED,
    has_completed_vision,
    has_vision_tags,
    is_pending_vision,
    tag_after_vision,
    tag_reviewed,
)
from src.tag_rules import (
    extract_candidate_tag_rules,
    extract_series_rules,
    load_series_rules,
    save_series_rules,
    validate_series_rules,
)
from src.vision_worker import (
    download_cover,
    resolve_cover_url,
    run_visual_embedding_on_bookmark,
    run_character_vision_on_bookmark,
    run_vision_on_bookmark,
)
from src.wd14_tagger import normalize_tag, select_execution_providers, WD14Tagger


# ---------------------------------------------------------------------------
# WD14 tag normalization
# ---------------------------------------------------------------------------


def test_candidate_tag_rules_only_include_art_group():
    bookmarks = [
        {"folder_path": "Art/TOUHOU", "tags": ["touhou"]},
        {"folder_path": "Art/TOUHOU", "tags": ["touhou"]},
        {"folder_path": "Art/TOUHOU", "tags": ["touhou"]},
        {"folder_path": "Video/TOUHOU", "tags": ["video-only"]},
        {"folder_path": "Video/TOUHOU", "tags": ["video-only"]},
        {"folder_path": "Video/TOUHOU", "tags": ["video-only"]},
    ]
    assert extract_candidate_tag_rules(bookmarks) == {"touhou": "Art/TOUHOU"}

def test_normalize_tag_basic():
    assert normalize_tag("Hatsune Miku") == "hatsune_miku"
    assert normalize_tag("1girl") == "1girl"
    assert normalize_tag("VOCALOID") == "vocaloid"


def test_normalize_tag_idempotent():
    assert normalize_tag("hatsune_miku") == "hatsune_miku"


def test_wd14_prefers_cuda_without_enabling_untested_tensorrt():
    assert select_execution_providers([
        "TensorrtExecutionProvider",
        "CUDAExecutionProvider",
        "CPUExecutionProvider",
    ]) == ["CUDAExecutionProvider", "CPUExecutionProvider"]
    assert select_execution_providers(["CPUExecutionProvider"]) == [
        "CPUExecutionProvider"
    ]


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


def test_wd14_tagger_predict_batch_runs_one_model_call_for_many_images():
    tagger = WD14Tagger(model_dir="/tmp/fake_wd14", threshold=0.5)
    mock_session = MagicMock()
    model_input = MagicMock(name="input")
    model_input.shape = ["batch", 448, 448, 3]
    mock_session.get_inputs.return_value = [model_input]
    mock_session.run.return_value = [
        np.array([[0.9, 0.2], [0.1, 0.8]], dtype=np.float32)
    ]
    tagger._session = mock_session
    tagger._tags = ["hatsune_miku", "hakurei_reimu"]

    from PIL import Image

    images = [
        Image.new("RGB", (448, 448), color=(255, 0, 0)),
        Image.new("RGB", (448, 448), color=(0, 0, 255)),
    ]

    assert tagger.predict_batch(images) == [
        ["hatsune_miku"],
        ["hakurei_reimu"],
    ]
    assert mock_session.run.call_count == 1


def test_wd14_tagger_predict_batch_honors_fixed_model_batch_dimension():
    tagger = WD14Tagger(model_dir="/tmp/fake_wd14", threshold=0.5)
    mock_session = MagicMock()
    model_input = MagicMock(name="input")
    model_input.shape = [1, 448, 448, 3]
    mock_session.get_inputs.return_value = [model_input]
    mock_session.run.side_effect = [
        [np.array([[0.9, 0.2]], dtype=np.float32)],
        [np.array([[0.1, 0.8]], dtype=np.float32)],
    ]
    tagger._session = mock_session
    tagger._tags = ["hatsune_miku", "hakurei_reimu"]

    from PIL import Image

    images = [Image.new("RGB", (448, 448)), Image.new("RGB", (448, 448))]

    assert tagger.predict_batch(images) == [
        ["hatsune_miku"],
        ["hakurei_reimu"],
    ]
    assert mock_session.run.call_count == 2


def test_wd14_tagger_predict_characters_excludes_generic_properties():
    tagger = WD14Tagger(model_dir="/tmp/fake_wd14", threshold=0.5)
    mock_session = MagicMock()
    mock_session.get_inputs.return_value = [MagicMock(name="input")]
    mock_session.run.return_value = [np.array([[0.9, 0.8, 0.7]])]
    tagger._session = mock_session
    tagger._tags = ["hakurei_reimu", "1girl", "hina_(blue_archive)"]
    tagger._categories = [4, 0, 4]

    from PIL import Image

    image = Image.new("RGB", (448, 448))

    assert tagger.predict_characters(image) == [
        "hakurei_reimu",
        "hina_(blue_archive)",
    ]


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


@patch("src.vision_worker.requests.get")
def test_resolve_cover_url_recovers_original_x_photo_from_placeholder(mock_get):
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "tweet": {
            "media": {
                "photos": [
                    {
                        "type": "photo",
                        "url": "https://pbs.twimg.com/media/D0uOhKBVAAANP5k.jpg?name=orig",
                    }
                ]
            }
        }
    }
    mock_get.return_value = response
    bookmark = {
        "link": "https://x.com/hibimeganesama/status/1102131260741177345",
        "cover": "https://abs.twimg.com/rweb/ssr/default/v2/og/image.png",
        "media": [
            {
                "type": "image",
                "link": "https://abs.twimg.com/rweb/ssr/default/v2/og/image.png",
            }
        ],
    }

    assert resolve_cover_url(bookmark) == (
        "https://pbs.twimg.com/media/D0uOhKBVAAANP5k.jpg?name=orig"
    )
    mock_get.assert_called_once_with(
        "https://api.fxtwitter.com/status/1102131260741177345",
        timeout=15,
    )


@patch("src.vision_worker.requests.get")
def test_resolve_cover_url_does_not_call_metadata_for_real_cover(mock_get):
    bookmark = {
        "link": "https://x.com/example/status/1",
        "cover": "https://pbs.twimg.com/media/real.jpg",
    }

    assert resolve_cover_url(bookmark) == bookmark["cover"]
    mock_get.assert_not_called()


@patch("src.vision_worker.requests.get")
def test_resolve_cover_url_replaces_generated_x_preview_with_photo(mock_get):
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "tweet": {"media": {"all": [{
            "type": "photo",
            "url": "https://pbs.twimg.com/media/photo.jpg?name=orig",
        }]}}
    }
    mock_get.return_value = response

    assert resolve_cover_url({
        "link": "https://x.com/example/status/123",
        "cover": "https://jf.x.com/images/media-preview/123",
    }) == "https://pbs.twimg.com/media/photo.jpg?name=orig"


@patch("src.vision_worker.requests.get")
def test_resolve_cover_url_replaces_generated_x_preview_with_video_thumbnail(mock_get):
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "tweet": {"media": {"all": [{
            "type": "video",
            "thumbnail_url": "https://pbs.twimg.com/video_thumb/thumb.jpg",
        }]}}
    }
    mock_get.return_value = response

    assert resolve_cover_url({
        "link": "https://x.com/example/status/456",
        "cover": "https://jf.x.com/images/media-preview/456",
    }) == "https://pbs.twimg.com/video_thumb/thumb.jpg"


@patch("src.vision_worker.requests.get")
def test_resolve_cover_url_keeps_generated_x_preview_when_metadata_fails(mock_get):
    mock_get.side_effect = Exception("metadata unavailable")
    generated = "https://jf.x.com/images/media-preview/789"

    assert resolve_cover_url({
        "link": "https://x.com/example/status/789",
        "cover": generated,
    }) == generated


@patch("src.vision_worker.requests.get")
def test_resolve_cover_url_skips_unrecoverable_x_placeholder(mock_get):
    mock_get.side_effect = Exception("metadata unavailable")
    bookmark = {
        "link": "https://x.com/example/status/123",
        "cover": "https://abs.twimg.com/rweb/ssr/default/v2/og/image.png",
    }

    assert resolve_cover_url(bookmark) is None


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


def test_run_vision_on_bookmark_downloads_recovered_cover():
    bookmark = {
        "link": "https://x.com/example/status/1",
        "cover": "https://abs.twimg.com/rweb/ssr/default/v2/og/image.png",
    }
    mock_tagger = MagicMock()
    mock_tagger.predict.return_value = ["nishizumi_miho"]
    recovered = "https://pbs.twimg.com/media/recovered.jpg?name=orig"

    with (
        patch("src.vision_worker.resolve_cover_url", return_value=recovered),
        patch("src.vision_worker.download_cover", return_value=b"img") as download,
    ):
        tags = run_vision_on_bookmark(bookmark, tagger=mock_tagger)

    assert tags == ["ai:wdtag-nishizumi_miho"]
    download.assert_called_once_with(recovered)


def test_run_vision_on_bookmark_dead_url():
    bm = {"cover": "http://example.com/dead.jpg"}
    with patch("src.vision_worker.download_cover", return_value=None):
        tags = run_vision_on_bookmark(bm)
    assert tags == []


def test_run_visual_embedding_on_bookmark_reuses_cover_recovery():
    bookmark = {"cover": "http://example.com/cover.jpg"}
    mock_embedder = MagicMock()
    mock_embedder.embed_image.return_value = np.array([0.25, 0.75], dtype=np.float32)

    with patch("src.vision_worker.download_cover", return_value=b"img"):
        embedding = run_visual_embedding_on_bookmark(bookmark, mock_embedder)

    np.testing.assert_array_equal(embedding, [0.25, 0.75])
    mock_embedder.embed_image.assert_called_once_with(b"img")


def test_run_character_vision_on_bookmark_returns_only_character_labels():
    bookmark = {"cover": "http://example.com/cover.jpg"}
    mock_tagger = MagicMock()
    mock_tagger.predict_characters.return_value = [
        "hakurei_reimu",
        "hina_(blue_archive)",
    ]

    with patch("src.vision_worker.download_cover", return_value=b"img"):
        tags = run_character_vision_on_bookmark(bookmark, tagger=mock_tagger)

    assert tags == ["hakurei_reimu", "hina_(blue_archive)"]
    mock_tagger.predict_characters.assert_called_once_with(b"img")


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


def test_decide_folder_normalizes_human_rule_names_for_wd14_tags():
    bookmark = {
        "tags": ["ai:wdtag-hakurei_reimu"],
        "title": "",
        "domain": "",
        "excerpt": "",
    }

    folder, reason = decide_folder(
        bookmark,
        {},
        {"Hakurei Reimu": "TOUHOU"},
    )

    assert folder == "TOUHOU"
    assert reason == "exact_tag_rule:hakurei_reimu"


def test_decide_folder_uses_series_key_embedded_in_wd14_character_tag():
    bookmark = {
        "type": "image",
        "tags": ["ai:wdtag-hina_(blue_archive)"],
        "title": "",
        "domain": "x.com",
        "excerpt": "",
    }

    folder, reason = decide_folder(
        bookmark,
        {},
        {"blue_archive": "Art/GAMES/BA"},
    )

    assert folder == "Art/GAMES/BA"
    assert reason == "calibrated_tag:blue_archive"


def test_decide_folder_maps_wd14_series_name_to_abbreviated_collection():
    bookmark = {
        "type": "image",
        "tags": ["ai:wdtag-boko_(girls_und_panzer)"],
        "title": "",
        "domain": "x.com",
        "excerpt": "",
    }

    folder, reason = decide_folder(
        bookmark,
        {},
        {},
        series_rules=extract_series_rules(["Art/ANIME/GUP"]),
    )

    assert folder == "Art/ANIME/GUP"
    assert reason == "series_rule:Art/ANIME/GUP"


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


def test_decide_folder_routes_image_x_post_to_art_series_collection():
    bookmark = {
        "type": "image",
        "link": "https://x.com/example/status/1",
        "domain": "x.com",
        "media": [{"link": "https://pbs.twimg.com/media/example.jpg"}],
        "tags": [],
        "title": "#VOCALOID",
        "excerpt": "",
    }

    folder, reason = decide_folder(
        bookmark,
        {},
        {},
        series_rules={
            "vocaloid": [
                "Art/VOCALOID",
                "Music/VOCALOID",
                "Video/VOCALOID",
            ]
        },
    )

    assert folder == "Art/VOCALOID"
    assert reason == "series_rule:Art/VOCALOID"


def test_decide_folder_trusts_x_image_media_over_misleading_video_type():
    bookmark = {
        "type": "video",
        "link": "https://x.com/example/status/1",
        "domain": "x.com",
        "media": [
            {"type": "image", "link": "https://pbs.twimg.com/media/example.jpg"}
        ],
        "tags": [],
        "title": "#VOCALOID",
        "excerpt": "",
    }

    folder, reason = decide_folder(
        bookmark,
        {},
        {},
        series_rules={
            "vocaloid": [
                "Art/VOCALOID",
                "Music/VOCALOID",
                "Video/VOCALOID",
            ]
        },
    )

    assert folder == "Art/VOCALOID"
    assert reason == "series_rule:Art/VOCALOID"


def test_decide_folder_routes_audio_to_music_series_collection():
    bookmark = {
        "type": "audio",
        "link": "https://example.test/miku.mp3",
        "domain": "example.test",
        "tags": ["vocaloid"],
        "title": "Miku song",
        "excerpt": "",
    }

    folder, reason = decide_folder(
        bookmark,
        {},
        {},
        series_rules={
            "vocaloid": [
                "Art/VOCALOID",
                "Music/VOCALOID",
                "Video/VOCALOID",
            ]
        },
    )

    assert folder == "Music/VOCALOID"
    assert reason == "series_rule:Music/VOCALOID"


def test_decide_folder_routes_video_to_video_series_collection():
    bookmark = {
        "type": "video",
        "link": "https://www.youtube.com/watch?v=example",
        "domain": "youtube.com",
        "tags": ["vocaloid"],
        "title": "Miku MV",
        "excerpt": "",
    }

    folder, reason = decide_folder(
        bookmark,
        {},
        {},
        series_rules={
            "vocaloid": [
                "Art/VOCALOID",
                "Music/VOCALOID",
                "Video/VOCALOID",
            ]
        },
    )

    assert folder == "Video/VOCALOID"
    assert reason == "series_rule:Video/VOCALOID"


def test_decide_folder_does_not_route_ambiguous_series_without_modality():
    bookmark = {
        "type": "link",
        "link": "https://example.test/post",
        "domain": "example.test",
        "tags": [],
        "title": "#VOCALOID",
        "excerpt": "",
    }

    folder, reason = decide_folder(
        bookmark,
        {},
        {},
        series_rules={
            "vocaloid": [
                "Art/VOCALOID",
                "Music/VOCALOID",
                "Video/VOCALOID",
            ]
        },
    )

    assert folder is None
    assert reason == "no_centroids"


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


def test_decide_folder_does_not_treat_synonyms_for_one_series_as_crossover():
    bookmark = {
        "tags": ["ai:wdtag-vocaloid", "ai:wdtag-project_sekai"],
        "title": "",
        "domain": "",
        "excerpt": "",
    }

    folder, reason = decide_folder(
        bookmark,
        {},
        {},
        series_rules={"vocaloid": "VOCALOID", "project_sekai": "VOCALOID"},
    )

    assert folder == "VOCALOID"
    assert reason == "series_rule:VOCALOID"


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


def test_decide_folder_matches_explicit_series_hashtag_in_excerpt():
    bookmark = {
        "tags": ["Twitter"],
        "title": "Perspective study",
        "domain": "x.com",
        "excerpt": "Perspective study\n#BlueArchive https://t.co/example",
    }

    folder, reason = decide_folder(
        bookmark,
        {},
        {},
        series_rules={"bluearchive": "GAMES/BA"},
    )

    assert folder == "GAMES/BA"
    assert reason == "series_rule:GAMES/BA"


def test_decide_folder_matches_curated_multilingual_series_alias_in_title():
    bookmark = {
        "tags": ["Twitter"],
        "title": "ヒフミが照れてる",
        "domain": "x.com",
        "cover": "https://example.test/art.jpg",
    }
    series_rules = extract_series_rules(["Art/GAMES/BA"])

    folder, reason = decide_folder(
        bookmark,
        {},
        {},
        series_rules=series_rules,
    )

    assert folder == "Art/GAMES/BA"
    assert reason == "series_rule:Art/GAMES/BA"


def test_decide_folder_ignores_noisy_unconfigured_hashtag_beside_vedal_alias():
    bookmark = {
        "tags": ["Twitter"],
        "title": "I found Vedal!",
        "excerpt": "#heartheartart #minecraft #けいおん",
        "domain": "x.com",
        "cover": "https://example.test/art.jpg",
    }
    series_rules = extract_series_rules(
        ["Art/NEUROVERSE", "Art/ANIME", "Video/GAMES/MINECRAFT"],
    )

    folder, reason = decide_folder(
        bookmark,
        {},
        {},
        series_rules=series_rules,
    )

    assert folder == "Art/NEUROVERSE"
    assert reason == "series_rule:Art/NEUROVERSE"


def test_decide_folder_uses_safe_anime_fallback_after_visual_analysis():
    bookmark = {
        "tags": ["Twitter", "ai:wdtag-1girl", "ai:wdtag-solo"],
        "title": "original character",
        "domain": "x.com",
        "cover": "https://example.test/art.jpg",
    }

    folder, reason = decide_folder(bookmark, {}, {})

    assert folder == "Art/ANIME"
    assert reason == "visual_art_fallback"


def test_decide_folder_does_not_use_anime_fallback_before_visual_analysis():
    bookmark = {
        "tags": ["Twitter"],
        "title": "unclassified image",
        "domain": "x.com",
        "cover": "https://example.test/art.jpg",
    }

    folder, reason = decide_folder(bookmark, {}, {})

    assert folder is None
    assert reason == "no_centroids"


def test_decide_folder_does_not_match_unmarked_series_name_in_prose():
    bookmark = {
        "tags": [],
        "title": "A discussion about BlueArchive",
        "domain": "example.test",
        "excerpt": "",
    }

    folder, reason = decide_folder(
        bookmark,
        {},
        {},
        embedder=MagicMock(embed_one=lambda _text: np.array([1.0, 0.0])),
        series_rules={"bluearchive": "GAMES/BA"},
    )

    assert folder is None
    assert reason == "no_centroids"


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


def test_resolve_bookmark_uses_live_anime_folder_as_default_crossover():
    bookmark = {
        "_id": 3,
        "tags": ["ai:wdtag-vocaloid", "ai:wdtag-touhou"],
        "title": "",
        "domain": "",
        "excerpt": "",
        "_folder_id_map": {"Art/ANIME": 99},
    }

    target_id, _new_tags, reason = resolve_bookmark(
        bookmark,
        {},
        {},
        series_rules={"vocaloid": "MIKU", "touhou": "TOUHOU"},
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


def test_completed_vision_does_not_require_detected_tags():
    assert has_completed_vision({"tags": [VISION_ATTEMPTED]}) is True
    assert has_completed_vision({"tags": ["ai:wdtag-test"]}) is True
    assert has_completed_vision({"tags": ["user_tag"]}) is False


def test_is_pending_vision():
    assert is_pending_vision({"tags": ["sorter-pending-vision:2024-01-01"]}) is True
    assert is_pending_vision({"tags": ["sorter-pending-resolution"]}) is False


def test_tag_after_vision_preserves_wd14_tags():
    bm = {"tags": ["sorter-pending-vision:2024-01-01", "ai:wdtag-hatsune_miku", "user"], "title":"", "domain":"", "excerpt":""}
    new_tags = tag_after_vision(bm)
    assert "ai:wdtag-hatsune_miku" in new_tags
    assert "user" in new_tags
    assert "sorter-pending-resolution" in new_tags
    assert VISION_ATTEMPTED in new_tags
    assert not any(t.startswith("sorter-pending-vision") for t in new_tags)


def test_tag_after_vision_records_an_attempt_when_no_tags_were_detected():
    bookmark = {"tags": ["sorter-pending-vision:2026-09-17"]}

    new_tags = tag_after_vision(bookmark)

    assert VISION_ATTEMPTED in new_tags
    assert "sorter-pending-resolution" in new_tags


def test_tag_reviewed_preserves_wd14_tags():
    bm = {"tags": ["sorter-pending-resolution", "ai:wdtag-hatsune_miku", "user"], "title":"", "domain":"", "excerpt":""}
    new_tags = tag_reviewed(bm)
    assert "ai:wdtag-hatsune_miku" in new_tags
    assert "user" in new_tags
    assert any(t.startswith("sorter-reviewed:") for t in new_tags)
    assert "sorter-pending-resolution" not in new_tags
    assert VISION_ATTEMPTED not in tag_reviewed(
        {"tags": [VISION_ATTEMPTED, "sorter-pending-resolution"]}
    )


# ---------------------------------------------------------------------------
# Series rules persistence
# ---------------------------------------------------------------------------

def test_save_and_load_series_rules():
    with tempfile.TemporaryDirectory() as tmpdir:
        save_series_rules({"vocaloid": "Art/Vocaloid"}, tmpdir)
        loaded = load_series_rules(tmpdir)
        assert loaded == {"vocaloid": "Art/Vocaloid"}


def test_extract_series_rules_from_unique_folder_names():
    rules = extract_series_rules(
        ["ANIME", "Art/Vocaloid", "Art/Touhou", "Archive/Touhou"]
    )

    assert rules == {
        "vocaloid": "Art/Vocaloid",
        "touhou": "Art/Touhou",
    }


def test_extract_series_rules_only_includes_art_group():
    rules = extract_series_rules(
        ["Art/VOCALOID", "Music/VOCALOID", "Video/VOCALOID"]
    )

    assert rules == {"vocaloid": "Art/VOCALOID"}


def test_load_series_rules_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        loaded = load_series_rules(tmpdir)
        assert loaded == {}


def test_validate_series_rules():
    rules = {"vocaloid": "Art/Vocaloid", "missing": "Art/Missing"}
    validated = validate_series_rules(rules, {"Art/Vocaloid"})
    assert validated == {"vocaloid": "Art/Vocaloid"}


def test_validate_series_rules_prunes_missing_group_candidates():
    rules = {
        "vocaloid": [
            "Art/VOCALOID",
            "Music/VOCALOID",
            "Missing/VOCALOID",
        ]
    }

    assert validate_series_rules(
        rules,
        {"Art/VOCALOID", "Music/VOCALOID"},
    ) == {
        "vocaloid": ["Art/VOCALOID", "Music/VOCALOID"]
    }
