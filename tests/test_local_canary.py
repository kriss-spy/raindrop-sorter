import json

import numpy as np

from src.centroids import save_centroids
from src.local_canary import run_local_canary
from src.tag_rules import save_series_rules, save_tag_rules


class FakeRaindropClient:
    def __init__(self, bookmark):
        self.bookmark = bookmark
        self.updates = []

    def get_raindrop(self, bookmark_id):
        assert bookmark_id == self.bookmark["_id"]
        return dict(self.bookmark)

    def update_raindrop(self, *args, **kwargs):
        self.updates.append((args, kwargs))


def test_local_canary_reports_end_to_end_decision_without_writing(tmp_path):
    bookmark = {
        "_id": 123,
        "title": "Miku",
        "domain": "example.test",
        "cover": "https://example.test/cover.jpg",
        "tags": ["sorter-pending-vision:2026-09-17"],
    }
    client = FakeRaindropClient(bookmark)
    save_centroids(
        {"Art/Vocaloid/Hatsune Miku": np.array([1.0, 0.0])},
        str(tmp_path),
    )
    save_tag_rules(
        {"hatsune_miku": "Art/Vocaloid/Hatsune Miku"},
        {},
        str(tmp_path),
    )
    save_series_rules({}, str(tmp_path))
    (tmp_path / "folder_id_map.json").write_text(
        json.dumps({"Art/Vocaloid/Hatsune Miku": 99}),
        encoding="utf-8",
    )

    result = run_local_canary(
        client,
        bookmark_id=123,
        db_path=str(tmp_path),
        analyze_vision=lambda _bookmark: ["ai:wdtag-hatsune_miku"],
    )

    state_tags = result.pop("result_state_tags")
    assert result == {
        "status": "ok",
        "dry_run": True,
        "bookmark_id": 123,
        "vision_tag_count": 1,
        "target_collection_id": 99,
        "target_folder": "Art/Vocaloid/Hatsune Miku",
        "reason": "exact_tag_rule:hatsune_miku",
    }
    assert len(state_tags) == 1
    assert state_tags[0].startswith("ai:sorted:")
    assert client.updates == []
