import pytest

from src.journal_review import (
    IneligibleReviewAttempt,
    InvalidReviewDestination,
    JournalReviewService,
    StaleReviewAttempt,
)
from src.routing import RouteDecision, RouteOutcome, TextEvidence, VisualEvidence
from src.run_journal import SQLiteRunJournal


class FakeReviewClient:
    def __init__(self):
        self.bookmark = {
            "_id": 123,
            "title": "Reimu and Miku",
            "tags": ["favorite", "sorter-edge-case:conflict", "sorter-reviewed:2026-09-25"],
            "collection": {"$id": -1},
        }
        self.updates = []
        self.collection_reads = 0

    def get_collections(self):
        self.collection_reads += 1
        return [
            {"_id": 10, "title": "TOUHOU", "parent": None},
            {"_id": 11, "title": "Portraits", "parent": {"$id": 10}},
            {"_id": 12, "title": "MIKU", "parent": None},
            {"_id": 20, "title": "VOCALOID", "parent": None},
            {"_id": 30, "title": "REFERENCE", "parent": None},
            {"_id": 31, "title": "POSES", "parent": {"$id": 30}},
            {"_id": 40, "title": "CLIPS", "parent": None},
            {"_id": 50, "title": "CURSOR", "parent": None},
            {"_id": 60, "title": "NEWS", "parent": None},
        ]

    def get_collection_groups(self):
        return [
            {"title": "Art", "collections": [10, 12]},
            {"title": "Music", "collections": [20]},
            {"title": "Image", "collections": [30]},
            {"title": "Video", "collections": [40]},
            {"title": "Goods", "collections": [50]},
            {"title": "Post", "collections": [60]},
        ]

    def get_raindrop(self, bookmark_id):
        assert bookmark_id == 123
        return dict(self.bookmark)

    def update_raindrop(self, bookmark_id, collection_id=None, tags=None):
        self.updates.append((bookmark_id, collection_id, tags))
        return {"result": True}


def _conflict_decision():
    return RouteDecision(
        bookmark_id=123,
        outcome=RouteOutcome.CONFLICT,
        destination=None,
        text_evidence=(TextEvidence(
            kind="personal_interest_text",
            destination="Art/TOUHOU",
            strength="strong",
            explanation="Text matched Reimu.",
        ),),
        visual_evidence=(VisualEvidence(
            status="pass",
            destination="Art/MIKU",
            method="wd14",
            explanation="Visual labels matched Miku.",
        ),),
        summary="Text and visual evidence disagree.",
    )


def _seed_conflict(journal):
    attempt = journal.start_attempt({"_id": 123, "title": "Reimu and Miku"}, mode="dry-run")
    journal.record_decision(attempt, _conflict_decision())
    journal.complete(attempt, phase="dry_run_completed")
    return attempt


def _seed_review(journal):
    attempt = journal.start_attempt({"_id": 123, "title": "Unknown artwork"}, mode="dry-run")
    journal.record_decision(
        attempt,
        RouteDecision(
            bookmark_id=123,
            outcome=RouteOutcome.REVIEW,
            destination=None,
            text_evidence=(TextEvidence(
                kind="no_match",
                destination=None,
                strength=None,
                explanation="No personal-interest text match was found.",
            ),),
            visual_evidence=(),
            summary="Kept in Unsorted for manual review.",
        ),
    )
    journal.complete(attempt, phase="dry_run_completed")
    return attempt


def test_review_service_lists_assignment_collections_in_supported_groups(tmp_path):
    service = JournalReviewService(
        SQLiteRunJournal(tmp_path / "journal.sqlite"), FakeReviewClient()
    )

    expected = [
        {"collection_id": 12, "path": "Art/MIKU"},
        {"collection_id": 10, "path": "Art/TOUHOU"},
        {"collection_id": 11, "path": "Art/TOUHOU/Portraits"},
        {"collection_id": 50, "path": "Goods/CURSOR"},
        {"collection_id": 30, "path": "Image/REFERENCE"},
        {"collection_id": 31, "path": "Image/REFERENCE/POSES"},
        {"collection_id": 60, "path": "Post/NEWS"},
        {"collection_id": 40, "path": "Video/CLIPS"},
    ]
    assert service.assignment_collections() == expected
    assert service.assignment_collections() == expected
    assert service.client.collection_reads == 2


def test_review_service_ranks_assignment_collections_by_recent_manual_use(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    for bookmark_id, destination, started_at in (
        (1, "Art/TOUHOU", "2026-09-27T10:00:00+00:00"),
        (2, "Art/MIKU", "2026-09-27T11:00:00+00:00"),
    ):
        attempt = journal.start_attempt({"_id": bookmark_id}, mode="manual-review")
        journal.record_decision(
            attempt,
            RouteDecision(
                bookmark_id=bookmark_id,
                outcome=RouteOutcome.CONFIRMED,
                destination=destination,
                text_evidence=(),
                visual_evidence=(),
                summary=f"Assigned to {destination}.",
            ),
        )
        journal.complete(attempt)
        with journal._connect() as connection:
            connection.execute(
                "UPDATE attempts SET started_at = ? WHERE attempt_id = ?",
                (started_at, attempt.attempt_id),
            )

    items = JournalReviewService(journal, FakeReviewClient()).assignment_collections()

    assert [item["path"] for item in items[:3]] == [
        "Art/MIKU",
        "Art/TOUHOU",
        "Art/TOUHOU/Portraits",
    ]
    assert items[0]["last_assigned_at"] == "2026-09-27T11:00:00+00:00"
    assert items[1]["last_assigned_at"] == "2026-09-27T10:00:00+00:00"
    assert items[2].get("last_assigned_at") is None


def test_review_service_resolves_conflict_as_new_confirmed_attempt(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    original = _seed_conflict(journal)
    client = FakeReviewClient()
    service = JournalReviewService(journal, client)

    result = service.resolve(
        original.attempt_id,
        collection_id=10,
        selection_source="text",
    )

    assert result["bookmark_id"] == 123
    assert result["destination"] == "Art/TOUHOU"
    assert result["outcome"] == "confirmed"
    assert result["selection_source"] == "text"
    assert client.updates[0][0:2] == (123, 10)
    assert "favorite" in client.updates[0][2]
    assert not any(tag.startswith("ai:sorted:") for tag in client.updates[0][2])
    assert not any(tag.startswith("sorter-reviewed:") for tag in client.updates[0][2])
    assert "sorter-edge-case:conflict" not in client.updates[0][2]

    trace = journal.explain(123)
    assert trace["attempt"]["attempt_id"] == result["attempt_id"]
    assert trace["attempt"]["mode"] == "manual-review"
    assert trace["attempt"]["outcome"] == "confirmed"
    assert trace["attempt"]["destination"] == "Art/TOUHOU"
    assert trace["actions"][0]["status"] == "succeeded"
    assert trace["actions"][0]["payload"]["selection_source"] == "text"


def test_review_service_corrects_confirmed_as_new_manual_review_attempt(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    original = _seed_conflict(journal)
    client = FakeReviewClient()
    service = JournalReviewService(journal, client)
    confirmed = service.resolve(
        original.attempt_id,
        collection_id=10,
        selection_source="text",
    )

    with pytest.raises(InvalidReviewDestination, match="confirmed corrections"):
        service.resolve(
            confirmed["attempt_id"],
            collection_id=12,
            selection_source="visual",
            confirmed_correction=True,
        )

    with pytest.raises(IneligibleReviewAttempt, match="explicit confirmation"):
        service.resolve(
            confirmed["attempt_id"],
            collection_id=12,
            selection_source="custom",
        )

    corrected = service.resolve(
        confirmed["attempt_id"],
        collection_id=12,
        selection_source="custom",
        confirmed_correction=True,
    )

    assert corrected["attempt_id"] != confirmed["attempt_id"]
    assert corrected["outcome"] == "confirmed"
    assert corrected["destination"] == "Art/MIKU"
    assert client.updates[-1][0:2] == (123, 12)
    original_confirmation = journal.explain_attempt(confirmed["attempt_id"])
    assert original_confirmation["attempt"]["outcome"] == "confirmed"
    assert original_confirmation["attempt"]["destination"] == "Art/TOUHOU"
    latest = journal.explain(123)["attempt"]
    assert latest["attempt_id"] == corrected["attempt_id"]
    assert latest["mode"] == "manual-review"
    assert latest["destination"] == "Art/MIKU"


def test_review_service_refreshes_learning_after_successful_assignment(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    original = _seed_conflict(journal)
    refreshes = []
    service = JournalReviewService(
        journal,
        FakeReviewClient(),
        on_reviews_changed=lambda: refreshes.append("refreshed") or {
            "promoted_signals": 2,
        },
    )

    result = service.resolve(
        original.attempt_id,
        collection_id=10,
        selection_source="text",
    )

    assert refreshes == ["refreshed"]
    assert result["learning"] == {"promoted_signals": 2}


def test_review_outcome_can_be_assigned_only_with_custom_picker(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    original = _seed_review(journal)
    service = JournalReviewService(journal, FakeReviewClient())

    with pytest.raises(InvalidReviewDestination, match="custom"):
        service.resolve(
            original.attempt_id,
            collection_id=10,
            selection_source="text",
        )

    result = service.resolve(
        original.attempt_id,
        collection_id=10,
        selection_source="custom",
    )
    assert result["outcome"] == "confirmed"
    assert result["destination"] == "Art/TOUHOU"
    assert result["selection_source"] == "custom"


def test_review_outcome_can_be_assigned_to_image_group_with_custom_picker(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    original = _seed_review(journal)
    client = FakeReviewClient()
    service = JournalReviewService(journal, client)

    result = service.resolve(
        original.attempt_id,
        collection_id=31,
        selection_source="custom",
    )

    assert result["outcome"] == "confirmed"
    assert result["destination"] == "Image/REFERENCE/POSES"
    assert result["selection_source"] == "custom"
    assert client.updates[0][0:2] == (123, 31)


def test_review_outcome_can_be_assigned_to_video_group_with_custom_picker(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    original = _seed_review(journal)
    client = FakeReviewClient()
    service = JournalReviewService(journal, client)

    result = service.resolve(
        original.attempt_id,
        collection_id=40,
        selection_source="custom",
    )

    assert result["outcome"] == "confirmed"
    assert result["destination"] == "Video/CLIPS"
    assert result["selection_source"] == "custom"
    assert client.updates[0][0:2] == (123, 40)


def test_review_outcome_can_be_assigned_to_goods_group_with_custom_picker(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    original = _seed_review(journal)
    client = FakeReviewClient()
    service = JournalReviewService(journal, client)

    result = service.resolve(
        original.attempt_id,
        collection_id=50,
        selection_source="custom",
    )

    assert result["outcome"] == "confirmed"
    assert result["destination"] == "Goods/CURSOR"
    assert result["selection_source"] == "custom"
    assert client.updates[0][0:2] == (123, 50)


def test_review_outcome_can_be_assigned_to_post_group_with_custom_picker(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    original = _seed_review(journal)
    client = FakeReviewClient()
    service = JournalReviewService(journal, client)

    result = service.resolve(
        original.attempt_id,
        collection_id=60,
        selection_source="custom",
    )

    assert result["outcome"] == "confirmed"
    assert result["destination"] == "Post/NEWS"
    assert result["selection_source"] == "custom"
    assert client.updates[0][0:2] == (123, 60)


def test_failed_review_outcome_retry_stays_custom_picker_only(tmp_path):
    class FlakyClient(FakeReviewClient):
        def __init__(self):
            super().__init__()
            self.fail = True

        def update_raindrop(self, bookmark_id, collection_id=None, tags=None):
            if self.fail:
                raise RuntimeError("temporary outage")
            return super().update_raindrop(bookmark_id, collection_id, tags)

    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    original = _seed_review(journal)
    client = FlakyClient()
    service = JournalReviewService(journal, client)

    with pytest.raises(RuntimeError, match="temporary outage"):
        service.resolve(
            original.attempt_id,
            collection_id=10,
            selection_source="custom",
        )

    failed = journal.explain(123)["attempt"]
    client.fail = False
    with pytest.raises(InvalidReviewDestination, match="custom"):
        service.resolve(
            failed["attempt_id"],
            collection_id=10,
            selection_source="text",
        )

    result = service.resolve(
        failed["attempt_id"],
        collection_id=10,
        selection_source="custom",
    )
    assert result["outcome"] == "confirmed"
    assert result["destination"] == "Art/TOUHOU"


def test_review_service_rejects_stale_attempt_and_non_assignment_destination(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    original = _seed_conflict(journal)
    service = JournalReviewService(journal, FakeReviewClient())

    with pytest.raises(
        InvalidReviewDestination,
        match="Art, Goods, Image, Post, or Video group",
    ):
        service.resolve(original.attempt_id, collection_id=20)

    newer = journal.start_attempt({"_id": 123}, mode="dry-run")
    journal.complete(newer, phase="dry_run_completed")
    with pytest.raises(StaleReviewAttempt, match="latest"):
        service.resolve(original.attempt_id, collection_id=10)


def test_review_service_preserves_visual_selection_as_visual_evidence(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    original = _seed_conflict(journal)
    service = JournalReviewService(journal, FakeReviewClient())

    result = service.resolve(
        original.attempt_id,
        collection_id=12,
        selection_source="visual",
    )

    trace = journal.explain_attempt(result["attempt_id"])
    assert trace["attempt"]["decision"]["text_evidence"] == []
    assert trace["attempt"]["decision"]["visual_evidence"][0]["destination"] == "Art/MIKU"
    assert trace["evidence"][0]["details"]["method"] == "manual_review"


def test_failed_review_move_is_audited_and_can_be_retried(tmp_path):
    class FlakyClient(FakeReviewClient):
        def __init__(self):
            super().__init__()
            self.fail = True

        def update_raindrop(self, bookmark_id, collection_id=None, tags=None):
            if self.fail:
                raise RuntimeError("temporary outage")
            return super().update_raindrop(bookmark_id, collection_id, tags)

    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    original = _seed_conflict(journal)
    client = FlakyClient()
    service = JournalReviewService(journal, client)

    with pytest.raises(RuntimeError, match="temporary outage"):
        service.resolve(
            original.attempt_id,
            collection_id=10,
            selection_source="text",
        )

    trace = journal.explain(123)
    assert trace["attempt"]["attempt_id"] != original.attempt_id
    assert trace["attempt"]["mode"] == "manual-review"
    assert trace["attempt"]["outcome"] is None
    assert trace["attempt"]["current_phase"] == "failed"
    assert trace["actions"][-1]["status"] == "failed"
    assert journal.overview()["outcomes"] == {"failed": 1}

    client.fail = False
    result = service.resolve(
        trace["attempt"]["attempt_id"],
        collection_id=12,
        selection_source="visual",
    )
    assert result["outcome"] == "confirmed"
    assert result["destination"] == "Art/MIKU"
    assert journal.explain(123)["attempt"]["attempt_id"] == result["attempt_id"]


def test_interrupted_manual_review_intent_can_be_resumed(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    interrupted = journal.start_attempt(
        {"_id": 123, "title": "Interrupted"},
        mode="manual-review",
        initial_event=(
            "manual_destination_selected",
            {
                "destination": "Art/TOUHOU",
                "selection_source": "text",
                "source_attempt_id": "original-attempt",
                "review_choices": {
                    "text": ["Art/TOUHOU"],
                    "visual": ["Art/MIKU"],
                },
            },
        ),
    )
    service = JournalReviewService(journal, FakeReviewClient())

    result = service.resolve(
        interrupted.attempt_id,
        collection_id=12,
        selection_source="visual",
    )

    assert result["outcome"] == "confirmed"
    assert result["destination"] == "Art/MIKU"
