from src.visual_order import order_by_review_group


def test_review_group_order_keeps_work_together_instead_of_shared_pose():
    records = [
        {
            "id": "a",
            "ai_group": "Art/GAMES/BA",
            "visual_labels": ["1girl", "sitting"],
        },
        {
            "id": "b",
            "ai_group": "Art/GAMES/GFL2",
            "visual_labels": ["1girl", "sitting"],
        },
        {
            "id": "c",
            "ai_group": "Art/GAMES/BA",
            "visual_labels": ["1girl", "standing"],
        },
        {"id": "d", "ai_group": None, "visual_labels": ["1girl", "sitting"]},
    ]

    assert [record["id"] for record in order_by_review_group(records)] == [
        "a",
        "c",
        "b",
        "d",
    ]


def test_review_group_order_does_not_mutate_input():
    records = [
        {"id": "a", "ai_group": "Art/GAMES/BA"},
        {"id": "b", "ai_group": "Art/GAMES/GFL2"},
    ]

    ordered = order_by_review_group(records)

    assert records[0]["id"] == "a"
    assert ordered is not records
