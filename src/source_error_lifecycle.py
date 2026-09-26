"""Journal the terminal lifecycle for an inaccessible bookmark source."""

from __future__ import annotations

from src.routing import RouteDecision
from src.run_journal import AttemptHandle, RunJournal
from src.source_health import SourceHealthResult, unavailable_source_decision


def record_source_error(
    journal: RunJournal,
    attempt: AttemptHandle,
    bookmark: dict,
    health: SourceHealthResult,
    *,
    apply: bool,
) -> RouteDecision:
    decision = unavailable_source_decision(bookmark, health)
    journal.record_event(attempt, "source_checked", health.to_dict())
    journal.record_decision(attempt, decision)
    journal.record_action(
        attempt,
        action_kind="ignore_broken_source",
        status="succeeded" if apply else "planned",
        destination=None,
        request_count=0,
        payload=health.to_dict(),
    )
    journal.complete(attempt, phase="applied" if apply else "dry_run_completed")
    return decision
