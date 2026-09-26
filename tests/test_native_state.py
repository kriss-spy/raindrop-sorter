from src.state_machine import (
    is_remote_lifecycle_tag,
    is_remote_sorter_tag,
    tags_for_decision,
    without_remote_lifecycle_tags,
    without_remote_sorter_tags,
)


def test_remote_lifecycle_cleanup_preserves_user_and_visual_evidence_tags():
    tags = without_remote_lifecycle_tags([
        "favorite",
        "sorter-reviewed:2026-09-01",
        "sorter-edge-case:conflict",
        "ai:sorted:2026-09-01",
        "ai:new-rule-miku",
        "ai:wdtag-1girl",
    ])

    assert tags == ["favorite", "ai:wdtag-1girl"]


def test_remote_lifecycle_cleanup_preserves_near_prefix_user_tags():
    user_tags = [
        "sorter-reviewed-books",
        "sorter-unreviewed-notes",
        "sorter-pending-resolution-later",
        "sorter-edge-casebook",
        "ai:sortedness",
        "ai:new-rulebook",
    ]

    assert without_remote_lifecycle_tags(user_tags) == user_tags
    assert not any(is_remote_lifecycle_tag(tag) for tag in user_tags)


def test_remote_sorter_cleanup_removes_lifecycle_and_extraction_residue():
    tags = without_remote_sorter_tags([
        "favorite",
        "sorter-reviewed:2026-09-01",
        "ai:wdtag-1girl",
        "ai:sauce-pixiv",
    ])

    assert tags == ["favorite"]


def test_remote_sorter_cleanup_preserves_near_prefix_user_tags():
    user_tags = ["ai:wdtagged", "ai:saucepan", "sorter-reviewed-books"]

    assert without_remote_sorter_tags(user_tags) == user_tags
    assert not any(is_remote_sorter_tag(tag) for tag in user_tags)


def test_confirmed_tags_remove_transient_and_lifecycle_state():
    tags = tags_for_decision(
        {
            "tags": [
                "favorite",
                "sorter-unreviewed",
                "sorter-pending-vision:2026-09-24",
                "sorter-edge-case:conflict",
                "ai:wdtag-blue_archive",
            ]
        },
        "confirmed",
    )
    assert "favorite" in tags
    assert tags == ["favorite"]


def test_outcomes_no_longer_render_database_state_as_raindrop_tags():
    provisional = tags_for_decision({"tags": ["favorite"]}, "provisional")
    conflict = tags_for_decision({"tags": ["favorite"]}, "conflict")

    assert provisional == ["favorite"]
    assert conflict == ["favorite"]
