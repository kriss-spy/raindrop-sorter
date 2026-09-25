from src.routing import RouteDecision, RouteOutcome, TextEvidence, VisualEvidence
from src.run_journal import SQLiteRunJournal


def _decision():
    return RouteDecision(
        bookmark_id=123,
        outcome=RouteOutcome.PROVISIONAL,
        destination="Art/VTUBERS",
        text_evidence=(TextEvidence(
            kind="personal_interest_text", destination="Art/VTUBERS",
            strength="contextual", matched_value="mini", source="vault",
            explanation="Matched Mini with outfit context.",
        ),),
        visual_evidence=(VisualEvidence(
            status="inconclusive", destination=None, method="visual_exemplar",
            explanation="Below threshold.", winner="Art/VTUBERS",
            runner_up="Art/GAMES/BA", similarity=0.72,
            runner_up_similarity=0.70, margin=0.02,
            min_similarity=0.80, min_margin=0.10,
        ),),
        summary="Moved provisionally to Art/VTUBERS.",
    )


def test_journal_records_queryable_native_attempt_trace(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    attempt = journal.start_attempt(
        {"_id": 123, "title": "Mini's new outfit", "cover": "secret-url"},
        mode="dry-run", pinned_index_version="v1", runner_version="native-two-step-v1",
    )
    journal.record_event(attempt, "text_identified", _decision().text_evidence[0].to_dict())
    journal.record_event(attempt, "visual_completed", _decision().visual_evidence[0].to_dict())
    journal.record_decision(attempt, _decision())
    journal.record_action(attempt, action_kind="move", status="planned", destination="Art/VTUBERS")
    journal.complete(attempt, phase="dry_run_completed")

    trace = journal.explain(123)
    assert trace is not None
    assert trace["attempt"]["outcome"] == "provisional"
    assert "cover" not in trace["attempt"]["bookmark_snapshot"]
    assert "cover_fingerprint" in trace["attempt"]["bookmark_snapshot"]
    assert [item["source_kind"] for item in trace["evidence"]] == [
        "personal_interest_text", "visual_exemplar"
    ]
    assert trace["evidence"][1]["details"]["runner_up"] == "Art/GAMES/BA"


def test_journal_records_failure_without_losing_prior_events(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    attempt = journal.start_attempt({"_id": 456}, mode="apply")
    journal.record_event(attempt, "visual_queued")
    journal.fail(attempt, RuntimeError("Raindrop unavailable"))
    trace = journal.explain(456)
    assert trace is not None
    assert trace["attempt"]["current_phase"] == "failed"
    assert trace["events"][-1]["phase"] == "failed"


def test_status_counts_only_latest_attempt_per_bookmark(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    first = journal.start_attempt({"_id": 123}, mode="dry-run")
    journal.complete(first, phase="failed")
    retry = journal.start_attempt({"_id": 123}, mode="dry-run")
    journal.complete(retry, phase="dry_run_completed")
    assert journal.status() == {"dry_run_completed": 1}


def test_dashboard_queries_include_snapshot_summary_and_filters(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    attempt = journal.start_attempt(
        {"_id": 123, "title": "Mini's new outfit", "link": "https://example.test/mini"},
        mode="dry-run",
    )
    journal.record_decision(attempt, _decision())
    journal.complete(attempt, phase="dry_run_completed")

    recent = journal.recent(limit=10, outcome="provisional", query="new outfit")
    assert recent[0]["title"] == "Mini's new outfit"
    assert recent[0]["summary"] == "Moved provisionally to Art/VTUBERS."
    assert journal.recent(limit=10, outcome="review") == []

    overview = journal.overview()
    assert overview["total_attempts"] == 1
    assert overview["outcomes"] == {"provisional": 1}
    assert overview["phases"] == {"dry_run_completed": 1}

    trace = journal.explain_attempt(attempt.attempt_id)
    assert trace is not None
    assert trace["attempt"]["bookmark_snapshot"]["title"] == "Mini's new outfit"
