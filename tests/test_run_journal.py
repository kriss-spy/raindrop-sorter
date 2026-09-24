from src.routing import decision_from_legacy_result
from src.run_journal import SQLiteRunJournal


def test_journal_records_queryable_attempt_trace(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    attempt = journal.start_attempt(
        {
            "_id": 123,
            "title": "Mini's new outfit",
            "tags": ["sorter-pending-resolution"],
        },
        mode="dry-run",
        pinned_index_version="legacy-local-index",
    )
    journal.record_event(attempt, "text_identified", {"matches": 1})
    decision = decision_from_legacy_result(
        bookmark_id=123,
        destination="Art/VTUBERS",
        reason="series_rule:Art/VTUBERS",
        resulting_tags=["ai:sorted:2026-09-24"],
    )
    journal.record_decision(attempt, decision)
    journal.record_action(
        attempt,
        action_kind="move",
        status="planned",
        destination="Art/VTUBERS",
    )
    journal.complete(attempt, phase="dry_run_completed")

    trace = journal.explain(123)

    assert trace is not None
    assert trace["attempt"]["outcome"] == "confirmed"
    assert trace["attempt"]["bookmark_snapshot"]["title"] == "Mini's new outfit"
    assert [event["phase"] for event in trace["events"]] == [
        "discovered",
        "text_identified",
        "decided_confirmed",
        "dry_run_completed",
    ]
    assert trace["evidence"][0]["source_kind"] == "series_rule"
    assert trace["actions"][0]["status"] == "planned"
    assert journal.status() == {"dry_run_completed": 1}
    assert journal.recent(limit=1)[0]["bookmark_id"] == 123


def test_journal_records_failure_without_losing_prior_events(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    attempt = journal.start_attempt({"_id": 456}, mode="apply")
    journal.record_event(attempt, "visual_queued")

    journal.fail(attempt, RuntimeError("Raindrop unavailable"))

    trace = journal.explain(456)
    assert trace is not None
    assert trace["attempt"]["current_phase"] == "failed"
    assert trace["attempt"]["error"]["type"] == "RuntimeError"
    assert trace["events"][-1]["phase"] == "failed"


def test_status_counts_only_the_latest_attempt_per_bookmark(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    first = journal.start_attempt({"_id": 123}, mode="dry-run")
    journal.complete(first, phase="failed")
    retry = journal.start_attempt({"_id": 123}, mode="dry-run")
    journal.complete(retry, phase="dry_run_completed")

    assert journal.status() == {"dry_run_completed": 1}
