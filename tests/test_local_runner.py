import json
import threading

import numpy as np
import pytest

from src.centroids import save_centroids
from src.local_runner import (
    LocalBatchProcessor,
    find_local_work,
    rerun_latest_outcomes,
    run_local_bookmark,
    validate_local_index,
)
from src.run_journal import SQLiteRunJournal
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
        self.updates = []

    def get_raindrops(self, collection_id, page=0, perpage=50, search=None):
        assert collection_id == -1
        self.searches.append((page, search))
        if page == 0:
            return ([{"_id": 1}, {"_id": 2}], True)
        return ([{"_id": 3}, {"_id": 4}], False)

    def update_raindrop(self, bookmark_id, collection_id=None, tags=None):
        self.updates.append((bookmark_id, collection_id, tags))


class FailingUpdateClient(FakeRaindropClient):
    def update_raindrop(self, bookmark_id, collection_id=None, tags=None):
        raise RuntimeError("Raindrop unavailable")


def _write_state(path):
    save_centroids({"MIKU": np.array([1.0, 0.0])}, str(path))
    save_tag_rules({"Hatsune Miku": "MIKU"}, {}, str(path))
    save_series_rules({"vocaloid": "VOCALOID"}, str(path))
    (path / "folder_id_map.json").write_text(
        json.dumps({"Art/MIKU": 42, "VOCALOID": 43}),
        encoding="utf-8",
    )


def test_local_index_validation_rejects_malformed_or_inconsistent_state(tmp_path):
    (tmp_path / "folder_id_map.json").write_text(
        json.dumps({"Art/MIKU": 42}),
        encoding="utf-8",
    )
    (tmp_path / "tag_rules.json").write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="tag_rules.json is not valid JSON"):
        validate_local_index(str(tmp_path))

    (tmp_path / "tag_rules.json").write_text(
        json.dumps({"rules": {"reimu": "Art/TOUHOU"}, "mismatches": {}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown collection Art/TOUHOU"):
        validate_local_index(str(tmp_path))


def test_local_runner_executes_vision_and_resolution_without_writing(tmp_path):
    _write_state(tmp_path)
    client = FakeRaindropClient(
        {
            "_id": 123,
            "title": "art",
            "type": "image",
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
    assert result["target_folder"] == "Art/MIKU"
    assert result["decision"]["outcome"] == "provisional"
    assert result["vision_tag_count"] == 1
    assert result["applied"] is False
    assert client.updates == []


def test_local_runner_runs_vision_for_pixiv_link_with_image_media(tmp_path):
    _write_state(tmp_path)
    calls = []
    client = FakeRaindropClient(
        {
            "_id": 123,
            "title": "fanart",
            "type": "link",
            "domain": "pixiv.net",
            "link": "https://www.pixiv.net/en/artworks/149957672",
            "cover": "https://embed.pixiv.net/artwork.php?illust_id=149957672",
            "media": [
                {"type": "image", "link": "https://i.pximg.net/example.jpg"}
            ],
            "tags": ["sorter-unreviewed"],
        }
    )

    result = run_local_bookmark(
        client,
        bookmark_id=123,
        db_path=str(tmp_path),
        analyze_vision=lambda bookmark: calls.append(bookmark["_id"])
        or ["ai:wdtag-hatsune_miku"],
    )

    assert calls == [123]
    assert result["target_folder"] == "Art/MIKU"
    assert result["vision_tag_count"] == 1


def test_local_runner_writes_only_when_apply_is_explicit(tmp_path):
    _write_state(tmp_path)
    journal = SQLiteRunJournal(tmp_path / "run-journal.sqlite")
    client = FakeRaindropClient(
        {
            "_id": 123,
            "title": "art",
            "type": "image",
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
        journal=journal,
    )

    assert result["applied"] is True
    assert client.updates[0][0:2] == (123, 42)
    assert all(not tag.startswith(("sorter-", "ai:sorted:")) for tag in client.updates[0][2])
    assert journal.explain(123)["attempt"]["current_phase"] == "applied"


def test_local_runner_refuses_remote_writes_without_a_journal(tmp_path):
    _write_state(tmp_path)
    client = FakeRaindropClient({"_id": 123, "title": "art", "tags": []})

    with pytest.raises(ValueError, match="journal is required"):
        run_local_bookmark(
            client,
            bookmark_id=123,
            db_path=str(tmp_path),
            apply=True,
        )

    assert client.updates == []


def test_coordinated_apply_skips_bookmark_moved_out_of_unsorted(tmp_path):
    _write_state(tmp_path)
    journal = SQLiteRunJournal(tmp_path / "run-journal.sqlite")
    client = FakeRaindropClient(
        {
            "_id": 123,
            "title": "art",
            "type": "image",
            "domain": "example.test",
            "cover": "https://example.test/cover.jpg",
            "collection": {"$id": 42},
            "tags": ["sorter-unreviewed"],
        }
    )

    result = run_local_bookmark(
        client,
        bookmark_id=123,
        db_path=str(tmp_path),
        analyze_vision=lambda _bookmark: ["ai:wdtag-hatsune_miku"],
        apply=True,
        journal=journal,
        mutation_lock=threading.RLock(),
    )

    assert result["status"] == "skipped"
    assert result["action"] == "skip"
    assert client.updates == []
    assert journal.explain(123)["attempt"]["current_phase"] == "skipped_stale"


def test_batch_processor_reports_partial_failures_without_losing_successes(
    tmp_path, monkeypatch
):
    _write_state(tmp_path)
    processor = LocalBatchProcessor(
        FakeQueueClient(),
        db_path=str(tmp_path),
        model_dir=str(tmp_path / "model"),
        journal=SQLiteRunJournal(tmp_path / "run-journal.sqlite"),
    )

    def run_one(bookmark_id, **_kwargs):
        if bookmark_id == 2:
            raise RuntimeError("boom")
        return {"bookmark_id": bookmark_id}

    monkeypatch.setattr(processor, "run_one", run_one)
    progress = []
    result = processor(3, on_progress=progress.append)

    assert result["count"] == 3
    assert result["succeeded"] == 2
    assert result["failed"] == 1
    assert result["progress_reported"] is True
    assert progress == [True, False, True]
    assert [item["bookmark_id"] for item in result["results"]] == [1, 3]
    assert result["errors"] == [
        {"bookmark_id": 2, "type": "RuntimeError", "message": "boom"}
    ]


def test_batch_processor_batches_visual_models_and_reuses_queue_snapshots(
    tmp_path, monkeypatch
):
    _write_state(tmp_path)
    save_visual_exemplar_index(
        VisualExemplarIndex(
            embeddings=np.array([[1.0, 0.0]], dtype=np.float32),
            folder_paths=["Art/MIKU"],
            bookmark_ids=[99],
            min_similarity=0.0,
            min_margin=0.0,
            model_name=DEFAULT_CLIP_MODEL,
        ),
        str(tmp_path),
    )

    class Client:
        def __init__(self):
            self.items = [
                {
                    "_id": bookmark_id,
                    "title": f"art {bookmark_id}",
                    "type": "image",
                    "domain": "example.test",
                    "cover": f"https://example.test/{bookmark_id}.jpg",
                    "collection": {"$id": -1},
                    "tags": ["sorter-unreviewed"],
                }
                for bookmark_id in (1, 2)
            ]
            self.get_calls = 0
            self.updates = []

        def get_tags(self, collection_id):
            assert collection_id == -1
            return [{"_id": "sorter-unreviewed"}]

        def get_raindrops(self, collection_id, page=0, perpage=50, search=None):
            assert page == 0
            return ([dict(item) for item in self.items], False)

        def get_raindrop(self, bookmark_id):
            self.get_calls += 1
            return dict(next(item for item in self.items if item["_id"] == bookmark_id))

        def update_raindrop(self, bookmark_id, collection_id=None, tags=None):
            self.updates.append((bookmark_id, collection_id, tags))

    class BatchTagger:
        def __init__(self):
            self.calls = []

        def predict_batch(self, images):
            self.calls.append(images)
            return [["hatsune_miku"] for _image in images]

        def predict(self, _image):
            raise AssertionError("per-image WD14 inference should not run")

    class BatchEmbedder:
        def __init__(self):
            self.calls = []

        def embed_images(self, images):
            self.calls.append(images)
            return np.array([[1.0, 0.0] for _image in images], dtype=np.float32)

        def embed_image(self, _image):
            raise AssertionError("per-image visual embedding should not run")

    client = Client()
    processor = LocalBatchProcessor(
        client,
        db_path=str(tmp_path),
        model_dir=str(tmp_path / "model"),
        journal=SQLiteRunJournal(tmp_path / "run-journal.sqlite"),
        mutation_lock=threading.RLock(),
    )
    processor.tagger = BatchTagger()
    processor.visual_embedder = BatchEmbedder()
    monkeypatch.setattr(
        "src.local_runner.download_cover",
        lambda url: url.encode(),
    )

    result = processor(2)

    assert result["succeeded"] == 2
    assert len(processor.tagger.calls) == 1
    assert processor.tagger.calls[0] == [
        b"https://example.test/1.jpg",
        b"https://example.test/2.jpg",
    ]
    assert len(processor.visual_embedder.calls) == 1
    assert processor.visual_embedder.calls[0] == processor.tagger.calls[0]
    assert client.get_calls == 2  # stale-state checks only
    assert [update[:2] for update in client.updates] == [(1, 42), (2, 42)]


def test_batch_processor_isolates_a_bad_image_without_losing_the_batch(
    tmp_path, monkeypatch
):
    _write_state(tmp_path)

    class Client:
        def get_tags(self, _collection_id):
            return [{"_id": "sorter-unreviewed"}]

        def get_raindrops(self, _collection_id, page=0, perpage=50, search=None):
            assert page == 0
            return ([
                {
                    "_id": bookmark_id,
                    "title": "art",
                    "type": "image",
                    "cover": f"https://example.test/{bookmark_id}.jpg",
                    "tags": ["sorter-unreviewed"],
                }
                for bookmark_id in (1, 2)
            ], False)

        def update_raindrop(self, *_args, **_kwargs):
            return None

    class PartiallyFailingTagger:
        def predict_batch(self, _images):
            raise ValueError("bad image in batch")

        def predict(self, image):
            if image.endswith(b"/2.jpg"):
                raise ValueError("bad second image")
            return ["hatsune_miku"]

    processor = LocalBatchProcessor(
        Client(),
        db_path=str(tmp_path),
        model_dir=str(tmp_path / "model"),
        journal=SQLiteRunJournal(tmp_path / "run-journal.sqlite"),
    )
    processor.tagger = PartiallyFailingTagger()
    monkeypatch.setattr("src.local_runner.download_cover", lambda url: url.encode())

    result = processor(2)

    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["errors"][0]["bookmark_id"] == 2
    assert result["errors"][0]["type"] == "ValueError"


def test_batch_processor_stops_before_the_next_bookmark_when_cancelled(
    tmp_path, monkeypatch
):
    class QueueClient(FakeQueueClient):
        def get_raindrops(self, collection_id, page=0, perpage=50, search=None):
            return ([{"_id": 1}, {"_id": 2}], False)

    _write_state(tmp_path)
    monkeypatch.setattr("src.local_runner.WD14Tagger", lambda **_kwargs: object())
    processor = LocalBatchProcessor(
        QueueClient(),
        db_path=str(tmp_path),
        model_dir=str(tmp_path / "model"),
        journal=SQLiteRunJournal(tmp_path / "run-journal.sqlite"),
    )
    calls = []
    processor.run_one = lambda bookmark_id, **_kwargs: calls.append(bookmark_id) or {"status": "ok"}

    result = processor(25, should_stop=lambda: bool(calls))

    assert calls == [1]
    assert result["count"] == 1
    assert result["selected_count"] == 2


def test_rerun_latest_outcomes_only_processes_requested_latest_results():
    attempts = {
        "provisional": [
            {"bookmark_id": 1, "started_at": "2026-09-25T10:00:00", "attempt_id": "a"},
        ],
        "conflict": [
            {"bookmark_id": 2, "started_at": "2026-09-25T11:00:00", "attempt_id": "b"},
            {
                "bookmark_id": 3,
                "started_at": "2026-09-25T12:00:00",
                "attempt_id": "c",
                "current_phase": "skipped_stale",
            },
        ],
        "review": [
            {"bookmark_id": 4, "started_at": "2026-09-25T13:00:00", "attempt_id": "d"},
        ],
    }

    class Journal:
        def recent(self, *, outcome, mode, exclude_phase, **_kwargs):
            assert mode == ("apply", "manual-review", "legacy-tag-migration")
            assert exclude_phase == "skipped_stale"
            return [
                attempt
                for attempt in attempts[outcome]
                if attempt.get("current_phase") != exclude_phase
            ]

    class Processor:
        apply = False

        def __init__(self):
            self.ids = []

        def run_one(self, bookmark_id, *, expected_collection_ids):
            assert expected_collection_ids == {None}
            self.ids.append(bookmark_id)
            return {"bookmark_id": bookmark_id}

    processor = Processor()
    result = rerun_latest_outcomes(
        processor,
        Journal(),
        outcomes=["provisional", "review", "conflict"],
        limit=10,
    )

    assert processor.ids == [4, 2, 1]
    assert result["count"] == 3
    assert result["applied"] is False


def test_applied_rerun_skips_bookmark_moved_since_recorded_attempt(tmp_path):
    _write_state(tmp_path)
    journal = SQLiteRunJournal(tmp_path / "run-journal.sqlite")
    client = FakeRaindropClient(
        {
            "_id": 123,
            "type": "image",
            "collection": {"$id": 999},
            "tags": [],
        }
    )

    result = run_local_bookmark(
        client,
        bookmark_id=123,
        db_path=str(tmp_path),
        apply=True,
        journal=journal,
        expected_collection_ids={-1},
    )

    assert result["status"] == "skipped"
    assert result["action"] == "skip"
    assert client.updates == []


def test_local_runner_journals_a_structured_dry_run(tmp_path):
    _write_state(tmp_path)
    journal = SQLiteRunJournal(tmp_path / "run-journal.sqlite")
    client = FakeRaindropClient(
        {
            "_id": 123,
            "title": "art",
            "type": "image",
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
        journal=journal,
    )

    trace = journal.explain(123)
    assert trace is not None
    assert result["attempt_id"] == trace["attempt"]["attempt_id"]
    assert result["decision"]["outcome"] == "provisional"
    assert [event["phase"] for event in trace["events"]] == [
        "discovered",
        "queued_in_journal",
        "text_identified",
        "visual_queued",
        "visual_completed",
        "decided_provisional",
        "dry_run_completed",
    ]
    assert trace["actions"][0]["status"] == "planned"
    assert client.updates == []


def test_local_runner_journals_a_failed_apply(tmp_path):
    _write_state(tmp_path)
    journal = SQLiteRunJournal(tmp_path / "run-journal.sqlite")
    client = FailingUpdateClient(
        {
            "_id": 123,
            "title": "art",
            "domain": "example.test",
            "tags": ["ai:wdtag-hatsune_miku"],
        }
    )

    with pytest.raises(RuntimeError, match="Raindrop unavailable"):
        run_local_bookmark(
            client,
            bookmark_id=123,
            db_path=str(tmp_path),
            apply=True,
            journal=journal,
        )

    trace = journal.explain(123)
    assert trace is not None
    assert trace["attempt"]["current_phase"] == "failed"
    assert trace["actions"][0]["status"] == "failed"
    assert trace["actions"][0]["error_classification"] == "RuntimeError"


def test_find_local_work_uses_journal_state_and_scans_past_terminal_items(tmp_path):
    client = FakeQueueClient()
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    completed = journal.start_attempt({"_id": 1}, mode="apply")
    journal.complete(completed)
    failed = journal.start_attempt({"_id": 3}, mode="apply")
    journal.fail(failed, RuntimeError("retry"))

    items = find_local_work(client, journal=journal, limit=2, page_size=2)

    assert [item["_id"] for item in items] == [2, 3]
    assert client.searches == [(0, None), (1, None)]


def test_local_runner_reports_an_incomplete_index_before_fetching(tmp_path):
    client = FakeRaindropClient({"_id": 123})

    with pytest.raises(FileNotFoundError, match="bootstrap.py"):
        run_local_bookmark(
            client,
            bookmark_id=123,
            db_path=str(tmp_path),
        )

    assert client.updates == []


def test_local_runner_combines_explicit_hashtag_with_visual_verification(tmp_path):
    _write_state(tmp_path)
    save_series_rules({"vocaloid": "Art/VOCALOID"}, str(tmp_path))
    (tmp_path / "folder_id_map.json").write_text(
        json.dumps({"Art/MIKU": 42, "Art/VOCALOID": 43}),
        encoding="utf-8",
    )
    client = FakeRaindropClient(
        {
            "_id": 123,
            "title": "Study",
            "type": "image",
            "excerpt": "#Vocaloid",
            "domain": "x.com",
            "cover": "https://example.test/cover.jpg",
            "tags": ["sorter-pending-vision:2026-09-18"],
        }
    )

    result = run_local_bookmark(
        client,
        bookmark_id=123,
        db_path=str(tmp_path),
        analyze_vision=lambda _bookmark: [],
    )

    assert result["action"] == "move"
    assert result["target_folder"] == "Art/VOCALOID"
    assert result["vision_tag_count"] == 0
    assert result["decision"]["outcome"] == "provisional"


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
    assert result["decision"]["outcome"] == "provisional"
    assert result["decision"]["visual_evidence"][0]["winner"] == "Art/GAMES/GFL2"


def test_local_runner_recomputes_visual_evidence_from_current_attempt(tmp_path):
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
        analyze_vision=lambda _bookmark: [],
        analyze_visual=lambda bookmark: calls.append(bookmark["_id"])
        or np.array([1.0, 0.0], dtype=np.float32),
    )

    assert calls == [123]
    assert result["target_folder"] == "Art/GAMES/GFL2"
    assert result["decision"]["outcome"] == "provisional"
