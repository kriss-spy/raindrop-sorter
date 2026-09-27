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


def test_recent_can_return_only_latest_attempt_per_bookmark(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    older = journal.start_attempt({"_id": 123, "title": "Old title"}, mode="dry-run")
    journal.record_decision(older, _decision())
    journal.complete(older, phase="dry_run_completed")

    latest = journal.start_attempt({"_id": 123, "title": "Current title"}, mode="apply")
    current_decision = RouteDecision(
        bookmark_id=123,
        outcome=RouteOutcome.CONFIRMED,
        destination="Art/VTUBERS",
        text_evidence=(),
        visual_evidence=(),
        summary="Current status.",
    )
    journal.record_decision(latest, current_decision)
    journal.complete(latest)

    other = journal.start_attempt({"_id": 456, "title": "Other"}, mode="dry-run")
    journal.complete(other, phase="dry_run_completed")

    recent = journal.recent(limit=10, latest_per_bookmark=True)
    assert {item["bookmark_id"] for item in recent} == {123, 456}
    assert next(item for item in recent if item["bookmark_id"] == 123)["title"] == "Current title"

    # Filters describe current status; they must not resurrect matching older attempts.
    assert journal.recent(
        limit=10, latest_per_bookmark=True, outcome="provisional"
    ) == []

    latest_applied = journal.recent(
        limit=10,
        latest_per_bookmark=True,
        mode="apply",
    )
    assert [item["bookmark_id"] for item in latest_applied] == [123]
    latest_dry_runs = journal.recent(
        limit=10,
        latest_per_bookmark=True,
        status_mode="dry-run",
    )
    assert [item["bookmark_id"] for item in latest_dry_runs] == [456]


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
    assert overview["total_bookmarks"] == 1
    assert overview["outcomes"] == {"provisional": 1}
    assert overview["phases"] == {"dry_run_completed": 1}
    assert overview["attempt_outcomes"] == {"provisional": 1}
    assert overview["attempt_phases"] == {"dry_run_completed": 1}

    trace = journal.explain_attempt(attempt.attempt_id)
    assert trace is not None
    assert trace["attempt"]["bookmark_snapshot"]["title"] == "Mini's new outfit"
    assert journal.has_bookmark(123)
    assert not journal.has_bookmark(999)


def test_dashboard_query_filters_structured_attempt_fields(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    attempt = journal.start_attempt(
        {
            "_id": 123,
            "title": "Halo study",
            "link": "https://x.com/artist/status/123",
        },
        mode="dry-run",
    )
    decision = RouteDecision(
        bookmark_id=123,
        outcome=RouteOutcome.PROVISIONAL,
        destination="Art/GAMES/BA",
        text_evidence=(),
        visual_evidence=(VisualEvidence(
            status="pass",
            destination="Art/GAMES/BA",
            method="wd14+visual_exemplar",
            explanation="Halo prior.",
            labels=("1girl", "halo", "blue_hair"),
        ),),
        summary="Moved provisionally to Blue Archive.",
    )
    journal.record_decision(attempt, decision)
    journal.complete(attempt, phase="dry_run_completed")
    with journal._connect() as connection:
        connection.execute(
            "UPDATE attempts SET started_at = ?, ended_at = ? WHERE attempt_id = ?",
            (
                "2026-09-26T16:30:00+00:00",
                "2026-09-26T16:30:01+00:00",
                attempt.attempt_id,
            ),
        )

    matching = journal.recent(
        limit=10,
        labels=("halo", "blue_hair"),
        title="study",
        link="x.com/artist",
        processed_on="2026-09-27",
        utc_offset_minutes=480,
        status_mode="dry-run",
        bookmark_ids={123},
    )

    assert [item["bookmark_id"] for item in matching] == [123]
    assert journal.recent(limit=10, labels=("halo", "red_hair")) == []
    assert journal.recent(limit=10, bookmark_ids={999}) == []
    assert journal.recent(
        limit=10,
        processed_on="2026-09-26",
        utc_offset_minutes=480,
    ) == []


def test_overview_can_be_scoped_to_live_location_bookmarks(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    for bookmark_id, outcome in ((1, RouteOutcome.REVIEW), (2, RouteOutcome.PROVISIONAL)):
        attempt = journal.start_attempt({"_id": bookmark_id}, mode="dry-run")
        journal.record_decision(
            attempt,
            RouteDecision(
                bookmark_id=bookmark_id,
                outcome=outcome,
                destination=None,
                text_evidence=(),
                visual_evidence=(),
                summary="Scoped count fixture.",
            ),
        )
        journal.complete(attempt, phase="dry_run_completed")

    overview = journal.overview(bookmark_ids={2})

    assert overview["total_attempts"] == 1
    assert overview["total_bookmarks"] == 1
    assert overview["outcomes"] == {"provisional": 1}
    assert overview["attempt_outcomes"] == {"provisional": 1}
    assert overview["phases"] == {"dry_run_completed": 1}
    assert overview["attempt_phases"] == {"dry_run_completed": 1}


def test_processed_date_uses_completion_time_with_started_fallback(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    completed = journal.start_attempt({"_id": 1}, mode="dry-run")
    journal.complete(completed, phase="dry_run_completed")
    running = journal.start_attempt({"_id": 2}, mode="dry-run")
    with journal._connect() as connection:
        connection.execute(
            "UPDATE attempts SET started_at = ?, ended_at = ? WHERE attempt_id = ?",
            ("2026-09-26T23:59:00+00:00", "2026-09-27T00:01:00+00:00", completed.attempt_id),
        )
        connection.execute(
            "UPDATE attempts SET started_at = ? WHERE attempt_id = ?",
            ("2026-09-27T12:00:00+00:00", running.attempt_id),
        )

    assert {
        item["bookmark_id"]
        for item in journal.recent(limit=10, processed_on="2026-09-27")
    } == {1, 2}
    assert journal.recent(limit=10, processed_on="2026-09-26") == []


def test_latest_mutating_attempt_does_not_resurrect_pre_manual_outcome(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    older = journal.start_attempt({"_id": 123}, mode="apply")
    journal.record_decision(older, _decision())
    journal.complete(older)

    manual = journal.start_attempt({"_id": 123}, mode="manual-review")
    journal.record_decision(
        manual,
        RouteDecision(
            bookmark_id=123,
            outcome=RouteOutcome.CONFIRMED,
            destination="Art/TOUHOU",
            text_evidence=(),
            visual_evidence=(),
            summary="Manually confirmed.",
        ),
    )
    journal.complete(manual)

    assert journal.recent(
        limit=10,
        outcome="provisional",
        latest_per_bookmark=True,
        mode=("apply", "manual-review"),
    ) == []


def test_terminal_bookmark_ids_use_latest_database_backed_mutating_state(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    completed = journal.start_attempt({"_id": 1}, mode="apply")
    journal.record_decision(completed, _decision())
    journal.complete(completed)
    dry_run = journal.start_attempt({"_id": 2}, mode="dry-run")
    journal.record_decision(dry_run, _decision())
    journal.complete(dry_run, phase="dry_run_completed")
    failed = journal.start_attempt({"_id": 3}, mode="apply")
    journal.fail(failed, RuntimeError("retry me"))
    manual = journal.start_attempt(
        {"_id": 4},
        mode="manual-review",
        initial_event=("manual_destination_selected", {"destination": "Art/MIKU"}),
    )
    active = journal.start_attempt({"_id": 5}, mode="apply")
    stale = journal.start_attempt({"_id": 6}, mode="apply")
    with journal._connect() as connection:
        connection.execute(
            "UPDATE attempts SET started_at = ? WHERE attempt_id = ?",
            ("2000-01-01T00:00:00+00:00", stale.attempt_id),
        )
        connection.execute(
            "UPDATE attempts SET claim_heartbeat_at = ? WHERE attempt_id = ?",
            ("2000-01-01T00:00:00+00:00", stale.attempt_id),
        )

    assert journal.terminal_bookmark_ids() == {1}
    assert journal.automatic_processing_exclusions() == {1, 4, 5}


def test_imported_legacy_state_is_idempotent_and_queryable(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    bookmark = {"_id": 44, "title": "Legacy", "tags": ["sorter-reviewed:2026-09-25"]}

    first = journal.import_legacy_state(bookmark, outcome="review", phase="applied")
    second = journal.import_legacy_state(bookmark, outcome="review", phase="applied")

    assert first is True
    assert second is False
    trace = journal.explain(44)
    assert trace is not None
    assert trace["attempt"]["mode"] == "legacy-tag-migration"
    assert trace["attempt"]["outcome"] == "review"
    assert trace["attempt"]["current_phase"] == "applied"
    assert journal.terminal_bookmark_ids() == {44}


def test_automatic_claim_is_atomic_and_retryable_after_failure(tmp_path):
    path = tmp_path / "journal.sqlite"
    first_journal = SQLiteRunJournal(path)
    second_journal = SQLiteRunJournal(path)
    bookmark = {"_id": 55, "title": "Claim me"}

    first = first_journal.claim_automatic(bookmark)
    blocked = second_journal.claim_automatic(bookmark)

    assert first is not None
    assert blocked is None

    first_journal.fail(first, RuntimeError("retry"))
    retry = second_journal.claim_automatic(bookmark)

    assert retry is not None
    assert retry.attempt_id != first.attempt_id


def test_rerun_claim_requires_selected_attempt_to_remain_latest(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    bookmark = {"_id": 58, "title": "Rerun me"}
    selected = journal.start_attempt(bookmark, mode="apply")
    journal.record_decision(selected, _decision())
    journal.complete(selected)

    claim = journal.claim_rerun(
        bookmark,
        expected_attempt_id=selected.attempt_id,
    )

    assert claim is not None
    assert journal.claim_rerun(
        bookmark,
        expected_attempt_id=selected.attempt_id,
    ) is None
    assert journal.renew_automatic_claim(claim) is True


def test_automatic_claim_heartbeat_renews_a_stale_attempt(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    claim = journal.claim_automatic({"_id": 56, "title": "Long batch"})
    assert claim is not None
    with journal._connect() as connection:
        connection.execute(
            "UPDATE attempts SET started_at = ? WHERE attempt_id = ?",
            ("2000-01-01T00:00:00+00:00", claim.attempt_id),
        )
        connection.execute(
            "UPDATE attempts SET claim_heartbeat_at = ? WHERE attempt_id = ?",
            ("2000-01-01T00:00:00+00:00", claim.attempt_id),
        )

    assert journal.automatic_processing_exclusions() == set()
    assert journal.renew_automatic_claim(claim) is True
    assert journal.automatic_processing_exclusions() == {56}


def test_old_owner_cannot_renew_after_stale_claim_is_replaced(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    old_claim = journal.claim_automatic({"_id": 57, "title": "Fence me"})
    assert old_claim is not None
    with journal._connect() as connection:
        connection.execute(
            "UPDATE attempts SET started_at = ?, claim_heartbeat_at = ? "
            "WHERE attempt_id = ?",
            (
                "2000-01-01T00:00:00+00:00",
                "2000-01-01T00:00:00+00:00",
                old_claim.attempt_id,
            ),
        )

    new_claim = journal.claim_automatic({"_id": 57, "title": "Fence me"})

    assert new_claim is not None
    assert journal.renew_automatic_claim(old_claim) is False
    assert journal.renew_automatic_claim(new_claim) is True


def test_recent_excludes_stale_skip_before_applying_limit(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    valid = journal.start_attempt({"_id": 123}, mode="apply")
    journal.record_decision(valid, _decision())
    journal.complete(valid)

    skipped = journal.start_attempt({"_id": 456}, mode="apply")
    journal.record_decision(skipped, _decision())
    journal.complete(skipped, phase="skipped_stale")

    recent = journal.recent(
        limit=1,
        outcome="provisional",
        latest_per_bookmark=True,
        mode=("apply", "manual-review"),
        exclude_phase="skipped_stale",
    )

    assert [item["bookmark_id"] for item in recent] == [123]


def test_overview_keeps_failed_and_pending_manual_reviews_separate(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    failed = journal.start_attempt(
        {"_id": 123},
        mode="manual-review",
        initial_event=("manual_destination_selected", {"destination": "Art/TOUHOU"}),
    )
    journal.fail(failed, RuntimeError("offline"))
    journal.start_attempt(
        {"_id": 456},
        mode="manual-review",
        initial_event=("manual_destination_selected", {"destination": "Art/MIKU"}),
    )

    overview = journal.overview()
    assert overview["outcomes"] == {"failed": 1, "pending": 1}
    assert overview["attempt_outcomes"] == {"failed": 1, "pending": 1}
