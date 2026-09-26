from src.routing import RouteDecision, RouteOutcome
from src.run_journal import SQLiteRunJournal
from src.source_health import SourceHealthResult, SourceHealthStatus
from src.source_health_migration import ignore_broken_twitter_sources


class FakeChecker:
    def check(self, bookmark):
        unavailable = bookmark["_id"] == 1
        return SourceHealthResult(
            SourceHealthStatus.UNAVAILABLE if unavailable else SourceHealthStatus.AVAILABLE,
            source="twitter_oembed",
            reason="gone" if unavailable else "available",
            http_status=404 if unavailable else 200,
        )


class FakeClient:
    def __init__(self, bookmarks):
        self.bookmarks = {item["_id"]: item for item in bookmarks}

    def get_raindrop(self, bookmark_id):
        return dict(self.bookmarks[bookmark_id])


def _record_review(journal, bookmark):
    attempt = journal.start_attempt(bookmark, mode="apply")
    journal.record_decision(
        attempt,
        RouteDecision(
            bookmark_id=bookmark["_id"],
            outcome=RouteOutcome.REVIEW,
            destination=None,
            text_evidence=(),
            visual_evidence=(),
            summary="review",
        ),
    )
    journal.complete(attempt)


def test_broken_source_migration_records_terminal_error_after_live_reconciliation(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    _record_review(journal, {
        "_id": 1,
        "title": "https://x.com/a/status/1",
        "link": "https://x.com/a/status/1",
        "collection": {"$id": -1},
    })
    _record_review(journal, {
        "_id": 2,
        "title": "https://x.com/b/status/2",
        "link": "https://x.com/b/status/2",
        "collection": {"$id": -1},
    })

    result = ignore_broken_twitter_sources(
        journal,
        client=FakeClient([
            {
                "_id": 1,
                "title": "https://x.com/a/status/1",
                "link": "https://x.com/a/status/1",
                "collection": {"$id": -1},
            },
            {
                "_id": 2,
                "title": "https://x.com/b/status/2",
                "link": "https://x.com/b/status/2",
                "collection": {"$id": -1},
            },
        ]),
        checker=FakeChecker(),
        apply=True,
    )

    assert result["checked"] == 2
    assert result["ignored"] == 1
    assert journal.explain(1)["attempt"]["outcome"] == "error"
    assert journal.explain(1)["actions"][0]["action_kind"] == "ignore_broken_source"
    assert journal.explain(2)["attempt"]["outcome"] == "review"


def test_broken_source_migration_dry_run_does_not_change_journal(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    _record_review(journal, {
        "_id": 1,
        "link": "https://x.com/a/status/1",
    })

    result = ignore_broken_twitter_sources(
        journal,
        client=FakeClient([{
            "_id": 1,
            "link": "https://x.com/a/status/1",
            "collection": {"$id": -1},
        }]),
        checker=FakeChecker(),
        apply=False,
    )

    assert result["would_ignore"] == 1
    assert result["ignored"] == 0
    assert journal.explain(1)["attempt"]["outcome"] == "review"


def test_broken_source_migration_skips_bookmark_moved_since_snapshot(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    _record_review(journal, {
        "_id": 1,
        "link": "https://x.com/a/status/1",
        "collection": {"$id": -1},
    })

    result = ignore_broken_twitter_sources(
        journal,
        client=FakeClient([{
            "_id": 1,
            "link": "https://x.com/a/status/1",
            "collection": {"$id": 42},
        }]),
        checker=FakeChecker(),
        apply=True,
    )

    assert result["checked"] == 0
    assert result["skipped_moved"] == [1]
    assert journal.explain(1)["attempt"]["outcome"] == "review"
