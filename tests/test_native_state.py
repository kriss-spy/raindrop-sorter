from src.state_machine import CONFLICT_TAG, tag_unreviewed, tags_for_decision


def test_tag_unreviewed_preserves_user_tags_and_replaces_final_state():
    tags = tag_unreviewed(
        {"tags": ["favorite", "sorter-reviewed:2026-09-01", "ai:wdtag-1girl"]}
    )
    assert tags == ["favorite", "sorter-unreviewed"]


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
    assert any(tag.startswith("ai:sorted:") for tag in tags)
    assert all(not tag.startswith("sorter-") for tag in tags)


def test_provisional_and_conflict_have_distinct_final_states():
    provisional = tags_for_decision({"tags": ["favorite"]}, "provisional")
    conflict = tags_for_decision({"tags": ["favorite"]}, "conflict")
    assert any(tag.startswith("sorter-needs-review:") for tag in provisional)
    assert any(tag.startswith("sorter-reviewed:") for tag in conflict)
    assert CONFLICT_TAG in conflict
