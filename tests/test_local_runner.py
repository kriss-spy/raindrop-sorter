import json

import numpy as np
import pytest

from src.centroids import save_centroids
from src.local_runner import find_local_work, run_local_bookmark
from src.tag_rules import save_series_rules, save_tag_rules
from src.visual_exemplars import (
    DEFAULT_CLIP_MODEL,
    VisualExemplarIndex,
    save_visual_exemplar_index,
)


class FakeRaindropClient:
    def __init__(self, bookmark):
        self.bookmark = bookmark
        self.updates = []

    def get_raindrop(self, bookmark_id):
        assert bookmark_id == self.bookmark["_id"]
        return dict(self.bookmark)

    def update_raindrop(self, bookmark_id, collection_id=None, tags=None):
        self.updates.append((bookmark_id, collection_id, tags))


class FakeQueueClient:
    def __init__(self):
        self.searches = []

    def get_tags(self, collection_id):
        assert collection_id == -1
        return [
            {"_id": "sorter-pending-vision:2026-09-18"},
            {"_id": "sorter-pending-resolution"},
            {"_id": "sorter-reviewed:2026-09-17"},
        ]

    def get_raindrops(self, collection_id, perpage, search):
        assert collection_id == -1
        self.searches.append(search)
        if search == '#"sorter-pending-vision:2026-09-18"':
            return ([{"_id": 1}], False)
        if search.startswith('#"sorter-pending-resolution"'):
            return ([{"_id": 2}], False)
        return ([{"_id": 3}], False)


def _write_state(path):
    save_centroids({"MIKU": np.array([1.0, 0.0])}, str(path))
    save_tag_rules({"Hatsune Miku": "MIKU"}, {}, str(path))
    save_series_rules({"vocaloid": "VOCALOID"}, str(path))
    (path / "folder_id_map.json").write_text(
        json.dumps({"MIKU": 42, "VOCALOID": 43}),
        encoding="utf-8",
    )


def test_local_runner_executes_vision_and_resolution_without_writing(tmp_path):
    _write_state(tmp_path)
    client = FakeRaindropClient(
        {
            "_id": 123,
            "title": "art",
            "domain": "example.test",
            "cover": "https://example.test/cover.jpg",
            "tags": ["sorter-pending-vision:2026-09-17"],
        }
    )

    result = run_local_bookmark(
        client,
        bookmark_id=123,
        db_path=str(tmp_path),
        analyze_vision=lambda _bookmark: ["ai:wdtag-hatsune_miku"],
    )

    assert result["action"] == "move"
    assert result["target_collection_id"] == 42
    assert result["target_folder"] == "MIKU"
    assert result["reason"] == "exact_tag_rule:hatsune_miku"
    assert result["vision_tag_count"] == 1
    assert result["applied"] is False
    assert client.updates == []


def test_local_runner_writes_only_when_apply_is_explicit(tmp_path):
    _write_state(tmp_path)
    client = FakeRaindropClient(
        {
            "_id": 123,
            "title": "art",
            "domain": "example.test",
            "cover": "https://example.test/cover.jpg",
            "tags": ["sorter-pending-vision:2026-09-17"],
        }
    )

    result = run_local_bookmark(
        client,
        bookmark_id=123,
        db_path=str(tmp_path),
        analyze_vision=lambda _bookmark: ["ai:wdtag-hatsune_miku"],
        apply=True,
    )

    assert result["applied"] is True
    assert client.updates[0][0:2] == (123, 42)
    assert any(tag.startswith("ai:sorted:") for tag in client.updates[0][2])


def test_find_local_work_prioritizes_queues_and_includes_new_items():
    client = FakeQueueClient()

    items = find_local_work(client, limit=3)

    assert [item["_id"] for item in items] == [1, 2, 3]
    assert client.searches[0] == '#"sorter-pending-vision:2026-09-18"'
    assert client.searches[1].startswith('#"sorter-pending-resolution"')
    assert all(
        f'-#"{tag}"' in client.searches[2]
        for tag in (
            "sorter-pending-vision:2026-09-18",
            "sorter-pending-resolution",
            "sorter-reviewed:2026-09-17",
        )
    )


def test_local_runner_reports_an_incomplete_index_before_fetching(tmp_path):
    client = FakeRaindropClient({"_id": 123})

    with pytest.raises(FileNotFoundError, match="bootstrap.py"):
        run_local_bookmark(
            client,
            bookmark_id=123,
            db_path=str(tmp_path),
        )

    assert client.updates == []


def test_local_runner_uses_explicit_hashtag_before_queued_vision(tmp_path):
    _write_state(tmp_path)
    save_series_rules({"bluearchive": "VOCALOID"}, str(tmp_path))
    client = FakeRaindropClient(
        {
            "_id": 123,
            "title": "Study",
            "excerpt": "#BlueArchive",
            "domain": "x.com",
            "cover": "https://example.test/cover.jpg",
            "tags": ["sorter-pending-vision:2026-09-18"],
        }
    )

    result = run_local_bookmark(
        client,
        bookmark_id=123,
        db_path=str(tmp_path),
        analyze_vision=lambda _bookmark: pytest.fail("vision should not run"),
    )

    assert result["action"] == "move"
    assert result["target_folder"] == "VOCALOID"
    assert result["vision_tag_count"] == 0


def test_local_runner_uses_visual_exemplars_before_anime_fallback(tmp_path):
    _write_state(tmp_path)
    (tmp_path / "folder_id_map.json").write_text(
        json.dumps(
            {
                "MIKU": 42,
                "VOCALOID": 43,
                "Art/GAMES/GFL2": 44,
                "Art/ANIME": 45,
            }
        ),
        encoding="utf-8",
    )
    save_visual_exemplar_index(
        VisualExemplarIndex(
            embeddings=np.array([[1.0, 0.0], [0.99, 0.01]], dtype=np.float32),
            folder_paths=["Art/GAMES/GFL2", "Art/GAMES/GFL2"],
            bookmark_ids=[1, 2],
            min_similarity=0.8,
            min_margin=0.1,
            model_name=DEFAULT_CLIP_MODEL,
        ),
        str(tmp_path),
    )
    client = FakeRaindropClient(
        {
            "_id": 123,
            "title": "new character",
            "type": "image",
            "cover": "https://example.test/cover.jpg",
            "tags": ["sorter-pending-vision:2026-09-18"],
        }
    )

    result = run_local_bookmark(
        client,
        bookmark_id=123,
        db_path=str(tmp_path),
        analyze_vision=lambda _bookmark: ["ai:wdtag-1girl"],
        analyze_visual=lambda _bookmark: np.array([1.0, 0.0], dtype=np.float32),
    )

    assert result["target_folder"] == "Art/GAMES/GFL2"
    assert result["reason"].startswith("visual_exemplar:")


def test_local_runner_adds_visual_match_after_completed_vision(tmp_path):
    _write_state(tmp_path)
    (tmp_path / "folder_id_map.json").write_text(
        json.dumps(
            {
                "MIKU": 42,
                "VOCALOID": 43,
                "Art/GAMES/GFL2": 44,
                "Art/ANIME": 45,
            }
        ),
        encoding="utf-8",
    )
    save_visual_exemplar_index(
        VisualExemplarIndex(
            embeddings=np.array([[1.0, 0.0]], dtype=np.float32),
            folder_paths=["Art/GAMES/GFL2"],
            bookmark_ids=[1],
            min_similarity=0.8,
            min_margin=0.1,
            model_name=DEFAULT_CLIP_MODEL,
        ),
        str(tmp_path),
    )
    client = FakeRaindropClient(
        {
            "_id": 123,
            "title": "new character",
            "type": "image",
            "cover": "https://example.test/cover.jpg",
            "tags": ["sorter-pending-resolution", "ai:wdtag-1girl"],
        }
    )
    calls = []

    result = run_local_bookmark(
        client,
        bookmark_id=123,
        db_path=str(tmp_path),
        analyze_vision=lambda _bookmark: pytest.fail("vision already completed"),
        analyze_visual=lambda bookmark: calls.append(bookmark["_id"])
        or np.array([1.0, 0.0], dtype=np.float32),
    )

    assert calls == [123]
    assert result["target_folder"] == "Art/GAMES/GFL2"
    assert result["reason"].startswith("visual_exemplar:")
