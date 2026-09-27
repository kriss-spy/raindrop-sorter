from src.visual_order import order_by_visual_similarity


def test_visual_similarity_order_keeps_shared_distinctive_labels_together():
    records = [
        {"id": "a", "visual_labels": ["1girl", "halo", "blue_hair"]},
        {"id": "b", "visual_labels": ["1girl", "red_hair", "dress"]},
        {
            "id": "c",
            "visual_labels": ["1girl", "halo", "blue_hair", "school_uniform"],
        },
        {"id": "d", "visual_labels": []},
    ]

    assert [record["id"] for record in order_by_visual_similarity(records)] == [
        "c",
        "a",
        "b",
        "d",
    ]


def test_visual_similarity_order_does_not_mutate_input():
    records = [
        {"id": "a", "visual_labels": ["halo"]},
        {"id": "b", "visual_labels": ["red_hair"]},
    ]

    ordered = order_by_visual_similarity(records)

    assert records[0]["id"] == "a"
    assert ordered is not records
