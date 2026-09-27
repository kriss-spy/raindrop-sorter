from src.visual_order import order_by_review_group, visual_identity_labels


def test_review_group_order_uses_identity_labels_instead_of_shared_pose():
    records = [
        {
            "id": "a",
            "ai_group": None,
            "ai_group_labels": ["black_hair", "red_eyes"],
            "visual_labels": ["1girl", "sitting"],
        },
        {
            "id": "b",
            "ai_group": None,
            "ai_group_labels": ["blue_hair", "blue_eyes"],
            "visual_labels": ["1girl", "sitting"],
        },
        {
            "id": "c",
            "ai_group": None,
            "ai_group_labels": ["black_hair", "red_eyes"],
            "visual_labels": ["1girl", "standing"],
        },
        {
            "id": "d",
            "ai_group": None,
            "ai_group_labels": [],
            "visual_labels": ["1girl", "sitting"],
        },
    ]

    assert [record["id"] for record in order_by_review_group(records)] == [
        "a",
        "c",
        "b",
        "d",
    ]


def test_review_group_order_does_not_mutate_input():
    records = [
        {"id": "a", "ai_group_labels": ["black_hair"]},
        {"id": "b", "ai_group_labels": ["blue_hair"]},
    ]

    ordered = order_by_review_group(records)

    assert records[0]["id"] == "a"
    assert ordered is not records


def test_visual_identity_labels_exclude_pose_body_and_composition_tags():
    assert visual_identity_labels([
        "1girl",
        "sitting",
        "looking_at_viewer",
        "breasts",
        "white_background",
        "black_hair",
        "light_blue_hair",
        "red_eyes",
        "halo",
        "twintails",
    ]) == ["black_hair", "halo", "light_blue_hair", "red_eyes", "twintails"]
