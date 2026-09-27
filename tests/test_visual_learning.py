import pytest

from src.visual_learning import VisualLearningConfig, learn_visual_rules


def test_visual_learning_rejects_unbounded_or_invalid_configuration():
    with pytest.raises(ValueError, match="max_samples"):
        VisualLearningConfig(max_samples=-1)
    with pytest.raises(ValueError, match="min_tag_purity"):
        VisualLearningConfig(min_tag_purity=1.1)


def test_visual_learning_learns_a_supported_pure_destination_rule():
    bookmarks = [
        {"_id": 1, "folder_path": "Art/TOUHOU", "cover": "1.jpg", "type": "image"},
        {"_id": 2, "folder_path": "Art/TOUHOU", "cover": "2.jpg", "type": "image"},
        {"_id": 3, "folder_path": "Art/GAMES/BA", "cover": "3.jpg", "type": "image"},
    ]
    detected = {
        1: ["hakurei_reimu"],
        2: ["hakurei_reimu"],
        3: ["hina_(blue_archive)"],
    }

    result = learn_visual_rules(
        bookmarks,
        analyze=lambda bookmark: detected[bookmark["_id"]],
        config=VisualLearningConfig(
            max_samples=3,
            min_tag_support=2,
            min_tag_purity=0.9,
            stability_patience=10,
            min_folder_rounds=1,
        ),
    )

    assert result.rules == {"hakurei_reimu": "Art/TOUHOU"}
    assert result.tags_by_bookmark_id == {
        1: ["hakurei_reimu"],
        2: ["hakurei_reimu"],
        3: ["hina_(blue_archive)"],
    }
    assert result.samples_analyzed == 3
    assert result.stop_reason == "sample_budget"


def test_visual_learning_samples_folders_round_robin():
    bookmarks = [
        {"_id": 1, "folder_path": "Art/TOUHOU", "cover": "1.jpg"},
        {"_id": 2, "folder_path": "Art/TOUHOU", "cover": "2.jpg"},
        {"_id": 3, "folder_path": "Art/GAMES/BA", "cover": "3.jpg"},
        {"_id": 4, "folder_path": "Art/GAMES/BA", "cover": "4.jpg"},
    ]
    analyzed: list[int] = []

    learn_visual_rules(
        bookmarks,
        analyze=lambda bookmark: analyzed.append(bookmark["_id"]) or [],
        config=VisualLearningConfig(max_samples=2),
    )

    assert analyzed == [3, 1]


def test_visual_learning_stops_when_rules_are_stable_after_folder_coverage():
    bookmarks = [
        {"_id": index, "folder_path": folder, "cover": f"{index}.jpg"}
        for index, folder in enumerate(
            ["Art/TOUHOU", "Art/GAMES/BA"] * 5,
            start=1,
        )
    ]

    result = learn_visual_rules(
        bookmarks,
        analyze=lambda bookmark: (
            ["hakurei_reimu"]
            if bookmark["folder_path"] == "Art/TOUHOU"
            else []
        ),
        config=VisualLearningConfig(
            max_samples=10,
            min_tag_support=1,
            min_tag_purity=0.9,
            stability_patience=2,
            min_folder_rounds=1,
        ),
    )

    assert result.rules == {"hakurei_reimu": "Art/TOUHOU"}
    assert result.samples_analyzed == 4
    assert result.stop_reason == "stable_rules"


def test_visual_learning_counts_failed_images_without_aborting_initialization():
    bookmarks = [
        {"_id": 1, "folder_path": "Art/TOUHOU", "cover": "bad.jpg"},
        {"_id": 2, "folder_path": "Art/TOUHOU", "cover": "good.jpg"},
    ]

    def analyze(bookmark):
        if bookmark["_id"] == 1:
            raise ValueError("corrupt image")
        return ["hakurei_reimu"]

    result = learn_visual_rules(
        bookmarks,
        analyze=analyze,
        config=VisualLearningConfig(max_samples=2, min_tag_support=1),
    )

    assert result.rules == {"hakurei_reimu": "Art/TOUHOU"}
    assert result.samples_analyzed == 2
    assert result.analysis_failures == 1


def test_visual_learning_focuses_budget_on_the_busiest_folders():
    bookmarks = [
        {"_id": 1, "folder_path": "Art/Large", "cover": "1.jpg"},
        {"_id": 2, "folder_path": "Art/Large", "cover": "2.jpg"},
        {"_id": 3, "folder_path": "Art/Large", "cover": "3.jpg"},
        {"_id": 4, "folder_path": "Art/Medium", "cover": "4.jpg"},
        {"_id": 5, "folder_path": "Art/Medium", "cover": "5.jpg"},
        {"_id": 6, "folder_path": "Art/Small", "cover": "6.jpg"},
    ]
    analyzed: list[int] = []

    learn_visual_rules(
        bookmarks,
        analyze=lambda bookmark: analyzed.append(bookmark["_id"]) or [],
        config=VisualLearningConfig(max_samples=4, max_folders=2),
    )

    assert set(analyzed) == {1, 2, 4, 5}


def test_visual_learning_combines_character_variants_into_a_series_rule():
    bookmarks = [
        {"_id": 1, "folder_path": "Art/GAMES/BA", "cover": "1.jpg"},
        {"_id": 2, "folder_path": "Art/GAMES/BA", "cover": "2.jpg"},
        {"_id": 3, "folder_path": "Art/GAMES/BA", "cover": "3.jpg"},
    ]
    detected = {
        1: ["hina_(blue_archive)"],
        2: ["hibiki_(cheerleader)_(blue_archive)"],
        3: ["mari_(blue_archive)"],
    }

    result = learn_visual_rules(
        bookmarks,
        analyze=lambda bookmark: detected[bookmark["_id"]],
        config=VisualLearningConfig(
            max_samples=3,
            min_tag_support=3,
            stability_patience=10,
            min_folder_rounds=1,
        ),
    )

    assert result.rules == {"blue_archive": "Art/GAMES/BA"}


def test_visual_learning_keeps_pure_destinations_per_modality():
    bookmarks = [
        {
            "_id": index,
            "folder_path": folder,
            "cover": f"{index}.jpg",
            "type": "image",
        }
        for index, folder in enumerate(
            ["Art/GAMES/BA"] * 3 + ["Post/JOKES"] * 3,
            start=1,
        )
    ]

    result = learn_visual_rules(
        bookmarks,
        analyze=lambda bookmark: [f"character_{bookmark['_id']}_(blue_archive)"],
        config=VisualLearningConfig(
            max_samples=6,
            min_tag_support=3,
            min_tag_purity=0.9,
            stability_patience=10,
            min_folder_rounds=1,
        ),
    )

    assert result.rules == {
        "blue_archive": ["Art/GAMES/BA", "Post/JOKES"],
    }


def test_visual_learning_excludes_image_group_from_suggestion_training():
    bookmarks = [
        {
            "_id": index,
            "folder_path": folder,
            "cover": f"{index}.jpg",
            "type": "image",
        }
        for index, folder in enumerate(
            ["Image/REFERENCE"] * 3 + ["Art/GAMES/BA"] * 3,
            start=1,
        )
    ]
    analyzed: list[int] = []

    result = learn_visual_rules(
        bookmarks,
        analyze=lambda bookmark: analyzed.append(bookmark["_id"])
        or ["blue_archive"],
        config=VisualLearningConfig(
            max_samples=6,
            min_tag_support=3,
            min_tag_purity=0.9,
            stability_patience=10,
            min_folder_rounds=1,
        ),
    )

    assert analyzed == [4, 5, 6]
    assert result.eligible_candidates == 3
    assert result.rules == {"blue_archive": "Art/GAMES/BA"}


def test_visual_learning_excludes_video_group_from_suggestion_training():
    bookmarks = [
        {
            "_id": index,
            "folder_path": folder,
            "cover": f"{index}.jpg",
            "type": "image",
        }
        for index, folder in enumerate(
            ["Video/CLIPS"] * 3 + ["Art/GAMES/BA"] * 3,
            start=1,
        )
    ]
    analyzed: list[int] = []

    result = learn_visual_rules(
        bookmarks,
        analyze=lambda bookmark: analyzed.append(bookmark["_id"])
        or ["blue_archive"],
        config=VisualLearningConfig(
            max_samples=6,
            min_tag_support=3,
            min_tag_purity=0.9,
            stability_patience=10,
            min_folder_rounds=1,
        ),
    )

    assert analyzed == [4, 5, 6]
    assert result.eligible_candidates == 3
    assert result.rules == {"blue_archive": "Art/GAMES/BA"}


def test_visual_learning_counts_series_support_once_per_bookmark():
    bookmark = {
        "_id": 1,
        "folder_path": "Art/GAMES/BA",
        "cover": "1.jpg",
        "type": "image",
    }

    result = learn_visual_rules(
        [bookmark],
        analyze=lambda _bookmark: [
            "hina_(blue_archive)",
            "hibiki_(blue_archive)",
            "mari_(blue_archive)",
        ],
        config=VisualLearningConfig(
            max_samples=1,
            min_tag_support=3,
            stability_patience=10,
            min_folder_rounds=1,
        ),
    )

    assert result.rules == {}


def test_visual_learning_does_not_spend_image_budget_on_audio_cover_art():
    bookmarks = [
        {
            "_id": 1,
            "folder_path": "Music/VOCALOID",
            "cover": "album.jpg",
            "type": "audio",
            "media": [],
        },
        {
            "_id": 2,
            "folder_path": "Art/VOCALOID",
            "cover": "art.jpg",
            "type": "article",
            "media": [{"type": "image", "link": "art.jpg"}],
        },
    ]
    analyzed: list[int] = []

    result = learn_visual_rules(
        bookmarks,
        analyze=lambda bookmark: analyzed.append(bookmark["_id"]) or [],
        config=VisualLearningConfig(max_samples=2),
    )

    assert analyzed == [2]
    assert result.samples_analyzed == 1


def test_visual_learning_does_not_call_an_empty_rule_set_good_enough():
    bookmarks = [
        {
            "_id": folder_index * 3 + sample_index,
            "folder_path": f"Art/Folder {folder_index:02d}",
            "cover": "art.jpg",
            "type": "image",
        }
        for folder_index in range(32)
        for sample_index in range(3)
    ]

    result = learn_visual_rules(
        bookmarks,
        analyze=lambda _bookmark: [],
        config=VisualLearningConfig(
            max_samples=96,
            max_folders=32,
            min_tag_support=3,
            stability_patience=1,
            min_folder_rounds=2,
        ),
    )

    assert result.rules == {}
    assert result.samples_analyzed == 96
    assert result.stop_reason == "sample_budget"
