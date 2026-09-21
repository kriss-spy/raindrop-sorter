"""Behavior tests for local visual exemplar indexing."""

import numpy as np

from src.resolver import decide_folder
from src.visual_exemplars import (
    DEFAULT_CLIP_MODEL,
    LocalVisualEmbeddingCache,
    VisualExemplarIndex,
    classify_visual_embedding,
    evaluate_visual_index,
    load_visual_exemplar_index,
    partition_visual_examples,
    save_visual_exemplar_index,
)


def test_partition_visual_examples_reserves_latest_holdout_and_caps_training():
    bookmarks = [
        {
            "_id": index,
            "folder_path": folder,
            "created": f"2026-01-{day:02d}T00:00:00.000Z",
            "cover": f"https://example.test/{index}.jpg",
        }
        for folder_index, folder in enumerate(("Art/GFL2", "Art/Endfield"))
        for day, index in enumerate(
            range(folder_index * 100 + 1, folder_index * 100 + 16),
            start=1,
        )
    ]

    training, holdout = partition_visual_examples(
        bookmarks,
        folder_paths=["Art/GFL2", "Art/Endfield"],
        holdout_per_folder=3,
        max_exemplars_per_folder=4,
    )

    assert {item["_id"] for item in holdout} == {
        13, 14, 15, 113, 114, 115,
    }
    assert {item["_id"] for item in training} == {
        9, 10, 11, 12, 109, 110, 111, 112,
    }
    assert not ({item["_id"] for item in training} & {item["_id"] for item in holdout})


def test_partition_visual_examples_can_reserve_oldest_holdout():
    bookmarks = [
        {
            "_id": day,
            "folder_path": "Art/GFL2",
            "created": f"2026-01-{day:02d}T00:00:00.000Z",
            "cover": f"https://example.test/{day}.jpg",
        }
        for day in range(1, 16)
    ]

    training, holdout = partition_visual_examples(
        bookmarks,
        folder_paths=["Art/GFL2"],
        holdout_per_folder=3,
        max_exemplars_per_folder=4,
        holdout_position="oldest",
    )

    assert [item["_id"] for item in holdout] == [1, 2, 3]
    assert [item["_id"] for item in training] == [15, 14, 13, 12]
    assert not ({item["_id"] for item in training} & {item["_id"] for item in holdout})


def test_visual_exemplar_match_requires_similarity_and_margin():
    index = VisualExemplarIndex(
        embeddings=np.array(
            [
                [1.0, 0.0],
                [0.98, 0.02],
                [0.0, 1.0],
                [0.02, 0.98],
            ],
            dtype=np.float32,
        ),
        folder_paths=["Art/GFL2", "Art/GFL2", "Art/Endfield", "Art/Endfield"],
        bookmark_ids=[1, 2, 3, 4],
        model_name=DEFAULT_CLIP_MODEL,
    )

    confident = classify_visual_embedding(
        np.array([0.99, 0.01], dtype=np.float32),
        index,
        min_similarity=0.8,
        min_margin=0.1,
    )
    ambiguous = classify_visual_embedding(
        np.array([0.7, 0.7], dtype=np.float32),
        index,
        min_similarity=0.8,
        min_margin=0.1,
    )

    assert confident is not None
    assert confident.folder_path == "Art/GFL2"
    assert confident.similarity > 0.99
    assert confident.margin > 0.9
    assert ambiguous is None


def test_visual_exemplar_index_round_trips_without_pickle(tmp_path):
    expected = VisualExemplarIndex(
        embeddings=np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        folder_paths=["Art/GFL2", "Art/Arknights Endfield"],
        bookmark_ids=[101, 202],
        min_similarity=0.5,
        min_margin=0.125,
        model_name=DEFAULT_CLIP_MODEL,
        neighbors_per_folder=5,
    )

    save_visual_exemplar_index(expected, str(tmp_path))
    actual = load_visual_exemplar_index(str(tmp_path))

    assert actual is not None
    np.testing.assert_array_equal(actual.embeddings, expected.embeddings)
    assert actual.folder_paths == expected.folder_paths
    assert actual.bookmark_ids == expected.bookmark_ids
    assert actual.min_similarity == expected.min_similarity
    assert actual.min_margin == expected.min_margin
    assert actual.model_name == expected.model_name
    assert actual.neighbors_per_folder == expected.neighbors_per_folder


def test_visual_exemplar_route_precedes_generic_anime_fallback():
    index = VisualExemplarIndex(
        embeddings=np.array([[1.0, 0.0], [0.99, 0.01], [0.0, 1.0]], dtype=np.float32),
        folder_paths=["Art/GFL2", "Art/GFL2", "Art/GENSHIN"],
        bookmark_ids=[1, 2, 3],
        model_name=DEFAULT_CLIP_MODEL,
    )
    bookmark = {
        "type": "image",
        "tags": ["ai:wdtag-1girl", "ai:wdtag-solo"],
        "title": "unknown new character",
        "_visual_embedding": np.array([1.0, 0.0], dtype=np.float32),
    }

    folder, reason = decide_folder(
        bookmark,
        {},
        {},
        visual_index=index,
        visual_min_similarity=0.8,
        visual_min_margin=0.1,
    )

    assert folder == "Art/GFL2"
    assert reason.startswith("visual_exemplar:similarity=")


def test_visual_evaluation_reports_exact_wrong_and_review():
    index = VisualExemplarIndex(
        embeddings=np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        folder_paths=["Art/GFL2", "Art/GENSHIN"],
        bookmark_ids=[1, 2],
        model_name=DEFAULT_CLIP_MODEL,
    )
    holdout = [
        {"_id": 11, "folder_path": "Art/GFL2"},
        {"_id": 12, "folder_path": "Art/GFL2"},
        {"_id": 13, "folder_path": "Art/GENSHIN"},
    ]
    embeddings = {
        11: np.array([1.0, 0.0], dtype=np.float32),
        12: np.array([0.0, 1.0], dtype=np.float32),
        13: np.array([0.7, 0.7], dtype=np.float32),
    }

    evaluation = evaluate_visual_index(
        holdout,
        index,
        embed=lambda bookmark: embeddings[bookmark["_id"]],
        min_similarity=0.8,
        min_margin=0.1,
    )

    assert (evaluation.exact, evaluation.wrong, evaluation.review) == (1, 1, 1)


def test_visual_embedding_cache_resumes_and_invalidates_changed_cover(tmp_path):
    cache = LocalVisualEmbeddingCache(str(tmp_path))
    bookmark = {
        "_id": 101,
        "folder_path": "Art/GFL2",
        "cover": "https://example.test/old.jpg",
    }
    cache.put(bookmark, np.array([1.0, 2.0], dtype=np.float32))
    cache.save()

    resumed = LocalVisualEmbeddingCache(str(tmp_path))

    np.testing.assert_array_equal(resumed.get(bookmark), [1.0, 2.0])
    assert resumed.get({**bookmark, "cover": "https://example.test/new.jpg"}) is None
