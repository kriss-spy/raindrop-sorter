"""Tests for the resolver decision function and related logic."""

import json
import os
import tempfile

import numpy as np
import pytest
import requests

from src.centroids import compute_folder_centroids, load_centroids, save_centroids
from src.embeddings import build_text_input
from src.resolver import (
    cosine_similarity,
    decide_folder,
    decide_folder_by_rule,
    find_best_centroid,
)
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
    assert "Tags: python test" in text
    assert "ai:wdtag-test" not in text  # prefix is normalized for embedding
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


def test_extract_candidate_tag_rules_excludes_non_art_candidates():
    bookmarks = [
        {"folder_path": folder, "tags": ["vocaloid"]}
        for folder in ("Art/VOCALOID", "Music/VOCALOID")
        for _ in range(3)
    ]

    assert extract_candidate_tag_rules(bookmarks) == {"vocaloid": "Art/VOCALOID"}


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


def test_validate_tag_rules_prunes_missing_group_candidates():
    rules = {
        "vocaloid": ["Art/VOCALOID", "Music/VOCALOID", "Missing/VOCALOID"]
    }

    assert validate_tag_rules(
        rules,
        {"Art/VOCALOID", "Music/VOCALOID"},
    ) == {"vocaloid": ["Art/VOCALOID", "Music/VOCALOID"]}


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


def test_decide_folder_honors_explicit_user_calibration():
    bookmark = {
        "_id": 1860037727,
        "type": "article",
        "tags": ["ai:wdtag-1girl"],
        "title": "시즈/しず (@sizuzang) on X",
        "domain": "x.com",
        "excerpt": "",
        "media": [{"type": "image", "link": "https://example.test/art.jpg"}],
    }

    folder, reason = decide_folder_by_rule(bookmark, {}, series_rules={})

    assert folder == "Art/GAMES/BA"
    assert reason == "user_calibration:1860037727"


def test_decide_folder_generalizes_calibrated_character_tag():
    bookmark = {
        "type": "article",
        "tags": ["ai:wdtag-hatsune_miku", "ai:wdtag-1girl"],
        "title": "untitled",
        "domain": "x.com",
        "excerpt": "",
        "media": [{"type": "image", "link": "https://example.test/art.jpg"}],
    }

    folder, reason = decide_folder_by_rule(bookmark, {}, series_rules={})

    assert folder == "Art/MIKU"
    assert reason == "calibrated_tag:hatsune_miku"


def test_calibration_uses_x_cover_as_art_evidence_without_typed_media():
    bookmark = {
        "type": "article",
        "tags": ["ai:wdtag-hatsune_miku"],
        "title": "untitled",
        "domain": "x.com",
        "cover": "https://pbs.twimg.com/media/example.jpg",
        "excerpt": "",
        "media": [],
    }

    folder, reason = decide_folder_by_rule(bookmark, {}, series_rules={})

    assert folder == "Art/MIKU"
    assert reason == "calibrated_tag:hatsune_miku"


def test_user_confirmed_character_route_overrides_stale_learned_rule():
    bookmark = {
        "type": "image",
        "tags": ["ai:wdtag-hakurei_reimu"],
        "title": "untitled",
        "domain": "x.com",
        "excerpt": "",
    }

    folder, reason = decide_folder_by_rule(
        bookmark,
        {"hakurei_reimu": "Art/ANIME"},
        series_rules={},
    )

    assert folder == "Art/TOUHOU"
    assert reason == "calibrated_tag:hakurei_reimu"


def _resolve_art_title(title, excerpt=""):
    return decide_folder_by_rule(
        {
            "type": "image",
            "tags": ["ai:wdtag-1girl"],
            "title": title,
            "domain": "x.com",
            "excerpt": excerpt,
        },
        {},
        series_rules={},
    )


@pytest.mark.parametrize(
    "title",
    [
        "Leva",
        "メイドリヴァ姉",
        "莱娅",
        "리바",
        "Girls' Frontline 2 fan art",
        "ドルフロ2",
        "少女前线2：追放",
        "소녀전선2: 망명",
        "Klukai",
        "マキアート",
        "索米",
        "콜펜",
    ],
)
def test_multilingual_gfl2_text_routes_before_visual_matching(title):
    bookmark = {
        "type": "image",
        "tags": ["ai:wdtag-1girl"],
        "title": title,
        "domain": "x.com",
        "excerpt": "",
    }

    folder, reason = decide_folder_by_rule(bookmark, {}, series_rules={})

    assert folder == "Art/GAMES/GFL2"
    assert reason.startswith("calibrated_text:")


@pytest.mark.parametrize(
    "title",
    [
        "Robella ❤",
        "ミシュティ「萌え萌えきゅん」",
        "로벨라",
        "米什緹",
        "洛贝拉",
        "米什缇",
    ],
)
def test_current_gfl2_roster_names_route_in_supported_languages(title):
    folder, reason = _resolve_art_title(title)

    assert folder == "Art/GAMES/GFL2"
    assert reason.startswith("character_text:")


@pytest.mark.parametrize(
    ("title", "expected_folder"),
    [
        ("Typhoeus", "Art/GAMES/Arknights Endfield"),
        ("ティフォロス", "Art/GAMES/Arknights Endfield"),
        ("티프로스", "Art/GAMES/Arknights Endfield"),
        ("提弗洛斯", "Art/GAMES/Arknights Endfield"),
        ("Furina", "Art/GAMES/GENSHIN"),
        ("フリーナ", "Art/GAMES/GENSHIN"),
        ("푸리나", "Art/GAMES/GENSHIN"),
        ("芙宁娜", "Art/GAMES/GENSHIN"),
        ("Ako", "Art/GAMES/BA"),
        ("アコ", "Art/GAMES/BA"),
        ("아코", "Art/GAMES/BA"),
        ("亚子", "Art/GAMES/BA"),
    ],
)
def test_current_roster_names_route_across_supported_games(title, expected_folder):
    folder, reason = _resolve_art_title(title)

    assert folder == expected_folder
    assert reason.startswith(("calibrated_text:", "character_text:"))


def test_shared_character_name_requires_franchise_evidence():
    folder, reason = _resolve_art_title("Mika")

    assert folder == "Art/ANIME"
    assert reason == "visual_art_fallback"

    folder, reason = _resolve_art_title("Mika", "#BlueArchive Mika")

    assert folder == "Art/GAMES/BA"
    assert reason == "calibrated_text:bluearchive"


def test_longer_character_name_disambiguates_a_shared_short_name():
    folder, reason = _resolve_art_title("Misono Mika")

    assert folder == "Art/GAMES/BA"
    assert reason == "character_text:misono mika"


@pytest.mark.parametrize(
    ("title", "expected_folder"),
    [("魈", "Art/GAMES/GENSHIN"), ("绯", "Art/GAMES/GFL2")],
)
def test_exact_single_character_cjk_names_route_safely(title, expected_folder):
    folder, reason = _resolve_art_title(title)

    assert folder == expected_folder
    assert reason == f"character_text:{title.casefold()}"

    folder, reason = _resolve_art_title(f"ordinary prose containing {title}")

    assert folder == "Art/ANIME"
    assert reason == "visual_art_fallback"


@pytest.mark.parametrize(
    ("bookmark_id", "title", "excerpt", "tags"),
    [
        (1494751684, "スオミちゃん", "スオミちゃん", ["Twitter", "Suomi"]),
        (1497682262, "M200~", "M200~", ["Twitter", "Cheyanne"]),
        (
            1499125984,
            "Cute Daughter Cheyanne",
            "Cute Daughter Cheyanne #ドールズフロントライン #M200 #少女前線",
            ["Twitter", "Cheyanne"],
        ),
        (1507543117, "Gmgm Lenna in a suit is hot :3", "", ["Twitter"]),
        (
            1509048999,
            "Robella ❤",
            "#GirlsFrontline2Exilium #robella",
            ["Twitter"],
        ),
        (
            1512621256,
            "ミシュティ「萌え萌えきゅん🫶🏻」",
            "",
            ["Twitter"],
        ),
        (
            1515148498,
            "セクスタンスとセ…",
            "【ドルフロ2／少女前线2】",
            ["Twitter"],
        ),
        (
            1516875878,
            "Started drawing Colphne this year and also ended it with Colphne~",
            "#GirlsFrontline2Exilium #GFL2Exilium",
            ["Twitter"],
        ),
        (
            1519714537,
            "2026年も絳雨を宜しく頼みます！！",
            "#ドルフロ2 #GirlsFrontline2Exilium",
            ["Twitter"],
        ),
        (1522670974, "ドルフロ2", "煙を味わう春田", ["Twitter"]),
        (
            1522670965,
            "Ms. Gyoza 💕",
            "#GirlsFrontline #GirlsFrontline2Exilium",
            ["Twitter"],
        ),
    ],
)
def test_supplied_gfl2_raindrops_all_resolve_from_their_real_text(
    bookmark_id, title, excerpt, tags
):
    bookmark = {
        "_id": bookmark_id,
        "type": "image",
        "domain": "x.com",
        "title": title,
        "excerpt": excerpt,
        "tags": tags,
    }

    folder, _reason = decide_folder_by_rule(bookmark, {}, series_rules={})

    assert folder == "Art/GAMES/GFL2"


def test_multilingual_character_text_does_not_route_non_art_bookmarks():
    bookmark = {
        "type": "article",
        "tags": [],
        "title": "Leva release notes",
        "domain": "example.test",
        "excerpt": "",
    }

    folder, reason = decide_folder_by_rule(bookmark, {}, series_rules={})

    assert folder is None
    assert reason == "no_rule"


@pytest.mark.parametrize(
    ("title", "expected_folder"),
    [
        ("Arknights: Endfield", "Art/GAMES/Arknights Endfield"),
        ("アークナイツ：エンドフィールド", "Art/GAMES/Arknights Endfield"),
        ("明日方舟：终末地", "Art/GAMES/Arknights Endfield"),
        ("명일방주: 엔드필드", "Art/GAMES/Arknights Endfield"),
        ("Genshin Impact", "Art/GAMES/GENSHIN"),
        ("原神", "Art/GAMES/GENSHIN"),
        ("원신", "Art/GAMES/GENSHIN"),
        ("Blue Archive", "Art/GAMES/BA"),
        ("ブルーアーカイブ", "Art/GAMES/BA"),
        ("蔚蓝档案", "Art/GAMES/BA"),
        ("블루 아카이브", "Art/GAMES/BA"),
    ],
)
def test_multilingual_franchise_text_routes_art(title, expected_folder):
    bookmark = {
        "type": "image",
        "tags": ["ai:wdtag-1girl"],
        "title": title,
        "domain": "x.com",
        "excerpt": "",
    }

    folder, reason = decide_folder_by_rule(bookmark, {}, series_rules={})

    assert folder == expected_folder
    assert reason.startswith("calibrated_text:")


@pytest.mark.parametrize(
    ("bookmark_id", "expected_folder"),
    [
        (1860416132, "Art/TOUHOU"),
        (1861076432, "Art/GAMES/BA"),
        (1860716167, "Art/GAMES/BA"),
        (1860392169, "Art/ANIME/MAJONOTABITABI"),
        (1860292294, "Art/MIKU"),
        (1860292290, "Art/ANIME/MAJONOTABITABI"),
        (1860037727, "Art/GAMES/BA"),
        (1860037717, "Art/MIKU"),
        (1859637128, "Art/GAMES/FGO"),
        (1859600128, "Art/MIKU"),
        (1859600122, "Art/ANIME/lucky star"),
        (1860052154, "Art/GAMES/BA"),
        (1859600099, "Art/VTUBERS"),
        (1859254203, "Art/GAMES/BA"),
        (1859290755, "Art/GAMES/BA"),
        (1859254200, "Art/GAMES/BA"),
        (1859152957, "Art/GAMES/GFL2"),
        (1859138295, "Art/TOUHOU"),
        (1859152949, "Art/GAMES/BA"),
        (1859160939, "Art/GAMES/BA"),
        (1859454297, "Art/GAMES/BA"),
        (1859100626, "Art/GAMES/GFL2"),
        (1859102703, "Art/NEUROVERSE/EVIL"),
        (1858587910, "Art/GAMES/BA"),
        (1859152945, "Art/GAMES/BA"),
        (1859191393, "Art/GAMES/GALGAME"),
        (1859152931, "Art/VTUBERS"),
        (1858587892, "Art/MISCE"),
        (1858587884, "Art/MIKU"),
        (1859152928, "Art/IDOL@MASTER"),
        (1859104912, "Art/GAMES/BA"),
        (1858601441, "Art/GAMES/FGO"),
        (1859117686, "Art/VTUBERS"),
    ],
)
def test_decide_folder_preserves_latest_100_user_feedback(
    bookmark_id,
    expected_folder,
):
    bookmark = {
        "_id": bookmark_id,
        "type": "article",
        "tags": ["ai:wdtag-1girl"],
        "title": "",
        "domain": "x.com",
        "excerpt": "",
        "media": [{"type": "image", "link": "https://example.test/art.jpg"}],
    }

    folder, reason = decide_folder_by_rule(bookmark, {}, series_rules={})

    assert folder == expected_folder
    assert reason == f"user_calibration:{bookmark_id}"


@pytest.mark.parametrize(
    ("title", "vision_tag", "expected_folder"),
    [
        ("untitled", "hakurei_reimu", "Art/TOUHOU"),
        ("untitled", "elaina_(majo_no_tabitabi)", "Art/ANIME/MAJONOTABITABI"),
        ("untitled", "izumi_konata", "Art/ANIME/lucky star"),
        ("untitled", "mari_(blue_archive)", "Art/GAMES/BA"),
        ("untitled", "komeiji_satori", "Art/TOUHOU"),
        ("untitled", "nero_claudius_(fate)", "Art/GAMES/FGO"),
        ("#初音ミク", "1girl", "Art/MIKU"),
        ("#ほしまちぎゃらりー", "1girl", "Art/VTUBERS"),
        ("Clannad figure", "1girl", "Art/GAMES/GALGAME"),
        ("untitled", "furukawa_nagisa", "Art/GAMES/GALGAME"),
        ("花海咲季 rkgk", "1girl", "Art/IDOL@MASTER"),
    ],
)
def test_calibrated_visual_and_text_aliases_generalize(
    title,
    vision_tag,
    expected_folder,
):
    bookmark = {
        "type": "article",
        "tags": [f"ai:wdtag-{vision_tag}"],
        "title": title,
        "domain": "x.com",
        "excerpt": "",
        "media": [{"type": "image", "link": "https://example.test/art.jpg"}],
    }

    folder, reason = decide_folder_by_rule(bookmark, {}, series_rules={})

    assert folder == expected_folder
    assert reason.startswith("calibrated_")


def test_short_text_calibration_does_not_match_source_url():
    bookmark = {
        "type": "article",
        "tags": ["ai:wdtag-1girl"],
        "title": "unrelated original character",
        "domain": "x.com",
        "link": "https://x.com/miyako_artist/status/1",
        "excerpt": "",
        "media": [{"type": "image", "link": "https://example.test/art.jpg"}],
    }

    folder, reason = decide_folder_by_rule(bookmark, {}, series_rules={})

    assert folder == "Art/ANIME"
    assert reason == "visual_art_fallback"


def test_latin_text_calibration_requires_word_boundaries():
    bookmark = {
        "type": "image",
        "tags": ["ai:wdtag-1girl"],
        "title": "Miyakojima original character",
        "domain": "x.com",
        "excerpt": "",
    }

    folder, reason = decide_folder_by_rule(bookmark, {}, series_rules={})

    assert folder == "Art/ANIME"
    assert reason == "visual_art_fallback"


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


def test_decide_folder_does_not_suggest_image_centroid():
    bookmark = {"tags": [], "title": "pose reference", "domain": "", "excerpt": ""}

    class MockEmbedder:
        def embed_one(self, text):
            return np.array([1.0, 0.0])

    folder, reason = decide_folder(
        bookmark,
        {"Image/REFERENCE": np.array([1.0, 0.0])},
        {},
        embedder=MockEmbedder(),
    )

    assert folder is None
    assert reason == "no_centroids"


def test_decide_folder_does_not_suggest_video_centroid():
    bookmark = {"tags": [], "title": "short video", "domain": "", "excerpt": ""}

    class MockEmbedder:
        def embed_one(self, text):
            return np.array([1.0, 0.0])

    folder, reason = decide_folder(
        bookmark,
        {"Video/CLIPS": np.array([1.0, 0.0])},
        {},
        embedder=MockEmbedder(),
    )

    assert folder is None
    assert reason == "no_centroids"


@pytest.mark.parametrize("destination", ["Image/REFERENCE", "Video/CLIPS"])
def test_decide_folder_by_rule_does_not_suggest_manual_only_destination(destination):
    bookmark = {
        "type": "image",
        "tags": ["reference"],
        "title": "",
        "domain": "",
        "excerpt": "",
    }

    folder, reason = decide_folder_by_rule(
        bookmark,
        {"reference": destination},
    )

    assert folder is None
    assert reason == "no_rule"


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


def test_resolve_bookmark_routes_ba_gaki_rules_to_ba_parent():
    bookmark = {
        "_id": 5,
        "tags": ["small_shun"],
        "title": "",
        "domain": "",
        "excerpt": "",
        "_folder_id_map": {
            "Art/GAMES/BA": 42,
            "Art/GAMES/BA/gaki": 43,
        },
    }

    target_id, _new_tags, reason = resolve_bookmark(
        bookmark,
        {},
        {"small_shun": "Art/GAMES/BA/gaki"},
    )

    assert target_id == 42
    assert reason == "exact_tag_rule:small_shun"


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

from unittest.mock import MagicMock, patch

from src.raindrop_client import RaindropClient


def test_raindrop_client_get_collections():
    client = RaindropClient(token="test")
    root_response = MagicMock(status_code=200, headers={})
    root_response.json.return_value = {"items": [{"_id": 1, "title": "A"}]}
    child_response = MagicMock(status_code=200, headers={})
    child_response.json.return_value = {
        "items": [{"_id": 2, "title": "B", "parent": {"$id": 1}}]
    }
    client.session.get = MagicMock(side_effect=[root_response, child_response])

    cols = client.get_collections()
    assert len(cols) == 2
    assert cols[0]["title"] == "A"
    assert cols[1]["title"] == "B"


@patch("src.raindrop_client.time.sleep")
@patch("src.raindrop_client.time.time", return_value=100.0)
def test_raindrop_client_retries_get_after_rate_limit(mock_time, mock_sleep):
    client = RaindropClient(token="test")
    rate_limited = MagicMock(
        status_code=429,
        headers={"X-RateLimit-Reset": "105"},
    )
    successful = MagicMock(status_code=200)
    successful.json.return_value = {"item": {"_id": 1}}
    client.session.get = MagicMock(side_effect=[rate_limited, successful])

    result = client.get_collection(1)

    assert result == {"_id": 1}
    assert client.session.get.call_count == 2
    mock_sleep.assert_called_once_with(5.0)


@patch("src.raindrop_client.time.sleep")
@patch("src.raindrop_client.time.time", return_value=100.0)
def test_raindrop_client_caps_rate_limit_wait(mock_time, mock_sleep):
    client = RaindropClient(token="test")
    rate_limited = MagicMock(
        status_code=429,
        headers={"X-RateLimit-Reset": "10000"},
    )
    successful = MagicMock(status_code=200)
    successful.json.return_value = {"item": {"_id": 1}}
    client.session.get = MagicMock(side_effect=[rate_limited, successful])

    assert client.get_collection(1) == {"_id": 1}
    mock_sleep.assert_called_once_with(60.0)


@patch("src.raindrop_client.time.sleep")
def test_raindrop_client_propagates_exhausted_rate_limit(mock_sleep):
    client = RaindropClient(token="test")
    responses = []
    for _ in range(6):
        response = MagicMock(status_code=429, headers={})
        response.raise_for_status.side_effect = requests.HTTPError("rate limited")
        responses.append(response)
    client.session.get = MagicMock(side_effect=responses)

    with pytest.raises(requests.HTTPError, match="rate limited"):
        client.get_collection(1)

    assert client.session.get.call_count == 6


def test_raindrop_client_update_raindrop():
    client = RaindropClient(token="test")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
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
