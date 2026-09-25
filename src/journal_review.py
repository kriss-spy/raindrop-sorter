"""Human resolution workflow for unresolved journal attempts."""

from __future__ import annotations

import threading
from enum import StrEnum
from typing import Any

from src.reindex import build_folder_map
from src.routing import RouteDecision, RouteOutcome, TextEvidence, VisualEvidence
from src.run_journal import SQLiteRunJournal
from src.state_machine import tags_for_decision


class JournalReviewError(ValueError):
    """Base error for a rejected dashboard review operation."""


class ReviewAttemptNotFound(JournalReviewError):
    """The requested journal attempt does not exist."""


class StaleReviewAttempt(JournalReviewError):
    """The requested attempt is no longer the Raindrop's current status."""


class InvalidReviewDestination(JournalReviewError):
    """The selected destination is not a live collection in the Art group."""


class IneligibleReviewAttempt(JournalReviewError):
    """The attempt does not require a human routing decision."""


class ReviewSelectionSource(StrEnum):
    TEXT = "text"
    VISUAL = "visual"
    CUSTOM = "custom"

    @property
    def evidence_key(self) -> str | None:
        return {
            self.TEXT: "text_evidence",
            self.VISUAL: "visual_evidence",
            self.CUSTOM: None,
        }[self]


class JournalReviewService:
    """Apply explicit human choices while preserving an append-only audit trail."""

    def __init__(
        self,
        journal: SQLiteRunJournal,
        client: Any,
        mutation_lock: threading.RLock | None = None,
    ):
        self.journal = journal
        self.client = client
        self._lock = mutation_lock or threading.RLock()

    def art_collections(self) -> list[dict[str, Any]]:
        with self._lock:
            folder_map = build_folder_map(
                self.client.get_collections(),
                self.client.get_collection_groups(),
            )
            return sorted(
                (
                    {"collection_id": collection_id, "path": path}
                    for path, collection_id in folder_map.items()
                    if path.casefold() == "art"
                    or path.casefold().startswith("art/")
                ),
                key=lambda item: item["path"].casefold(),
            )

    def resolve(
        self,
        attempt_id: str,
        *,
        collection_id: int,
        selection_source: str = "custom",
    ) -> dict[str, Any]:
        with self._lock:
            trace = self.journal.explain_attempt(attempt_id)
            if trace is None:
                raise ReviewAttemptNotFound("attempt not found")
            original = trace["attempt"]
            bookmark_id = int(original["bookmark_id"])
            latest = self.journal.explain(bookmark_id)
            if latest is None or latest["attempt"]["attempt_id"] != attempt_id:
                raise StaleReviewAttempt(
                    "only the latest attempt for a Raindrop can be resolved"
                )
            retrying_manual_review = (
                original.get("mode") == "manual-review"
                and original.get("outcome") is None
                and original.get("current_phase")
                in {"failed", "manual_destination_selected"}
            )
            if original.get("outcome") not in {
                RouteOutcome.PROVISIONAL.value,
                RouteOutcome.CONFLICT.value,
                RouteOutcome.REVIEW.value,
            } and not retrying_manual_review:
                raise IneligibleReviewAttempt(
                    "only review, provisional, conflicting, or recoverable "
                    "manual-review attempts can be resolved"
                )
            try:
                source = ReviewSelectionSource(selection_source)
            except ValueError as error:
                raise InvalidReviewDestination(
                    "selection_source must be text, visual, or custom"
                ) from error

            collection = next(
                (
                    item
                    for item in self.art_collections()
                    if item["collection_id"] == collection_id
                ),
                None,
            )
            if collection is None:
                raise InvalidReviewDestination(
                    "destination must be a live collection in the Art group"
                )

            destination = str(collection["path"])
            if retrying_manual_review:
                prior_selection = next(
                    (
                        event.get("payload", {})
                        for event in reversed(trace["events"])
                        if event.get("phase") == "manual_destination_selected"
                    ),
                    {},
                )
                review_choices = prior_selection.get("review_choices") or {}
                custom_only = bool(prior_selection.get("custom_only"))
            else:
                review_choices = {
                    "text": sorted(_evidence_destinations(
                        original.get("decision") or {}, "text_evidence"
                    )),
                    "visual": sorted(_evidence_destinations(
                        original.get("decision") or {}, "visual_evidence"
                    )),
                }
                custom_only = original.get("outcome") == RouteOutcome.REVIEW.value
            if custom_only and source is not ReviewSelectionSource.CUSTOM:
                raise InvalidReviewDestination(
                    "review outcomes must use the custom Art collection picker"
                )
            if source.evidence_key is not None:
                evidence_destinations = set(review_choices.get(source.value, []))
                if destination not in evidence_destinations:
                    raise InvalidReviewDestination(
                        f"destination was not provided by {source.value} evidence"
                    )
            bookmark = self.client.get_raindrop(bookmark_id)
            tags = tags_for_decision(bookmark, RouteOutcome.CONFIRMED.value)
            review_attempt = self.journal.start_attempt(
                bookmark,
                mode="manual-review",
                runner_version="journal-dashboard-v1",
                initial_event=(
                    "manual_destination_selected",
                    {
                        "destination": destination,
                        "selection_source": source.value,
                        "source_attempt_id": attempt_id,
                        "review_choices": review_choices,
                        "custom_only": custom_only,
                    },
                ),
            )
            try:
                self.client.update_raindrop(
                    bookmark_id,
                    collection_id=collection_id,
                    tags=tags,
                )
            except Exception as error:
                self.journal.record_action(
                    review_attempt,
                    action_kind="manual_move",
                    status="failed",
                    destination=destination,
                    request_count=1,
                    error_classification=type(error).__name__,
                    payload={
                        "message": str(error),
                        "source_attempt_id": attempt_id,
                        "selection_source": source.value,
                    },
                )
                self.journal.fail(review_attempt, error)
                raise
            explanation = (
                f"The user selected this {source.value} destination "
                "in the journal dashboard."
            )
            text_evidence = (
                (TextEvidence(
                    kind="manual_review",
                    destination=destination,
                    strength="strong",
                    matched_value=attempt_id,
                    source="journal_dashboard_text",
                    explanation=explanation,
                ),)
                if source is ReviewSelectionSource.TEXT
                else ()
            )
            visual_evidence = (
                (VisualEvidence(
                    status="pass",
                    destination=destination,
                    method="manual_review",
                    explanation=explanation,
                ),)
                if source is ReviewSelectionSource.VISUAL
                else ()
            )
            decision = RouteDecision(
                bookmark_id=bookmark_id,
                outcome=RouteOutcome.CONFIRMED,
                destination=destination,
                text_evidence=text_evidence,
                visual_evidence=visual_evidence,
                summary=f"Confirmed manually and moved to {destination}.",
            )
            self.journal.record_decision(review_attempt, decision)
            self.journal.record_action(
                review_attempt,
                action_kind="manual_move",
                status="succeeded",
                destination=destination,
                request_count=1,
                payload={
                    "source_attempt_id": attempt_id,
                    "selection_source": source.value,
                },
            )
            self.journal.complete(review_attempt)
            return {
                "status": "ok",
                "attempt_id": review_attempt.attempt_id,
                "bookmark_id": bookmark_id,
                "outcome": RouteOutcome.CONFIRMED.value,
                "destination": destination,
                "collection_id": collection_id,
                "selection_source": source.value,
            }


def _evidence_destinations(
    decision: dict[str, Any], evidence_key: str
) -> set[str]:
    return {
        str(candidate)
        for evidence in decision.get(evidence_key, [])
        for candidate in [
            evidence.get("destination"),
            *(evidence.get("candidates") or []),
        ]
        if candidate
    }
