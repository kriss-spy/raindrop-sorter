import json

from src.review_learning import (
    ReviewObservation,
    compile_review_feedback,
    load_review_feedback,
    save_review_feedback,
)


def test_compile_review_feedback_promotes_only_unanimous_supported_signals():
    observations = [
        ReviewObservation("user_tag_or_hashtag", "#ブルアカ", "Art/GAMES/BA"),
        ReviewObservation("user_tag_or_hashtag", "ブルアカ", "Art/GAMES/BA"),
        ReviewObservation("user_tag_or_hashtag", "ブルアカ", "Art/GAMES/BA"),
        ReviewObservation("character_alias", "重音テト", "Art/VOICEBANKS/TETO"),
        ReviewObservation("character_alias", "重音テト", "Art/VOICEBANKS/TETO"),
        ReviewObservation("character_alias", "アリス", "Art/TOUHOU"),
        ReviewObservation("character_alias", "アリス", "Art/TOUHOU"),
        ReviewObservation("character_alias", "アリス", "Art/GAMES/BA"),
    ]

    feedback = compile_review_feedback(
        observations,
        existing_folders={"Art/GAMES/BA", "Art/VOICEBANKS/TETO", "Art/TOUHOU"},
        min_support=3,
        min_purity=1.0,
    )

    assert feedback["tag_rules"] == {
        "ブルアカ": {
            "destination": "Art/GAMES/BA",
            "support": 3,
            "observations": 3,
            "purity": 1.0,
        }
    }
    assert feedback["alias_rules"] == {}
    assert feedback["rejected_signals"] == 2


def test_compile_review_feedback_does_not_promote_image_assignments():
    observations = [
        ReviewObservation("user_tag_or_hashtag", "reference", "Image/REFERENCE")
        for _ in range(3)
    ]

    feedback = compile_review_feedback(
        observations,
        existing_folders={"Image/REFERENCE"},
        min_support=3,
        min_purity=1.0,
    )

    assert feedback["observations"] == 0
    assert feedback["promoted_signals"] == 0
    assert feedback["tag_rules"] == {}
    assert feedback["alias_rules"] == {}


def test_review_feedback_round_trips(tmp_path):
    feedback = {
        "schema_version": 1,
        "min_support": 3,
        "min_purity": 1.0,
        "reviewed_attempts": 12,
        "observations": 9,
        "promoted_signals": 1,
        "rejected_signals": 2,
        "tag_rules": {
            "date_a_live": {
                "destination": "Art/ANIME/Date a Live",
                "support": 3,
                "observations": 3,
                "purity": 1.0,
            }
        },
        "alias_rules": {},
    }

    save_review_feedback(feedback, str(tmp_path))

    assert load_review_feedback(str(tmp_path)) == feedback
    assert json.loads((tmp_path / "review_feedback.json").read_text()) == feedback


def test_load_review_feedback_defaults_to_empty_rules(tmp_path):
    assert load_review_feedback(str(tmp_path)) == {
        "schema_version": 1,
        "tag_rules": {},
        "alias_rules": {},
    }


def test_load_review_feedback_filters_legacy_image_destinations(tmp_path):
    feedback = {
        "schema_version": 1,
        "tag_rules": {
            "reference": {
                "destination": "Image/REFERENCE",
                "support": 3,
                "observations": 3,
                "purity": 1.0,
            },
            "blue_archive": {
                "destination": "Art/GAMES/BA",
                "support": 3,
                "observations": 3,
                "purity": 1.0,
            },
        },
        "alias_rules": {
            "pose": {
                "destination": "Image/REFERENCE/POSES",
                "support": 4,
                "observations": 4,
                "purity": 1.0,
            }
        },
    }
    (tmp_path / "review_feedback.json").write_text(json.dumps(feedback))

    loaded = load_review_feedback(str(tmp_path))

    assert set(loaded["tag_rules"]) == {"blue_archive"}
    assert loaded["alias_rules"] == {}
