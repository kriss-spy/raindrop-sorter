"""Human resolution workflow for unresolved journal attempts."""

from __future__ import annotations

import threading
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from src.cover_cache import SQLiteCoverCache
from src.destinations import is_manual_assignment_destination
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
    """The selected destination is not a live assignment collection."""


class IneligibleReviewAttempt(JournalReviewError):
    """The attempt does not require a human routing decision."""


class ReviewApplyFailed(RuntimeError):
    """A live move failed after its recoverable review attempt was recorded."""

    def __init__(
        self,
        cause: Exception,
        *,
        retry_attempt: dict[str, Any],
        retry_trace: dict[str, Any],
    ):
        super().__init__(str(cause))
        self.error_type = type(cause).__name__
        self.retry_attempt = retry_attempt
        self.retry_trace = retry_trace


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


class JournalRecordService:
    """Apply local human lifecycle changes without a Raindrop client."""

    def __init__(
        self,
        journal: SQLiteRunJournal,
        mutation_lock: threading.RLock | None = None,
    ):
        self.journal = journal
        self._lock = mutation_lock or threading.RLock()

    def mark_deleted_batch(self, attempt_ids: list[str]) -> dict[str, Any]:
        """Mark latest journal records deleted without mutating Raindrop."""
        deleted = 0
        errors = []
        for attempt_id in attempt_ids:
            try:
                self._mark_deleted(attempt_id)
                deleted += 1
            except Exception as error:
                errors.append({
                    "attempt_id": attempt_id,
                    "error": str(error),
                    "type": type(error).__name__,
                })
        return {
            "status": "ok" if not errors else "partial",
            "deleted": deleted,
            "failed": len(errors),
            "errors": errors,
        }

    def _mark_deleted(self, attempt_id: str) -> None:
        with self._lock:
            trace = self.journal.explain_attempt(attempt_id)
            if trace is None:
                raise ReviewAttemptNotFound("attempt not found")
            original = trace["attempt"]
            bookmark_id = int(original["bookmark_id"])
            latest = self.journal.explain(bookmark_id)
            if latest is None or latest["attempt"]["attempt_id"] != attempt_id:
                raise StaleReviewAttempt(
                    "only the latest record for a Raindrop can be marked deleted"
                )
            if original.get("outcome") == RouteOutcome.DELETED.value:
                raise IneligibleReviewAttempt("record is already marked deleted")
            if original.get("ended_at") is None:
                raise IneligibleReviewAttempt("an active record cannot be marked deleted")
            bookmark = dict(original.get("bookmark_snapshot") or {})
            bookmark["_id"] = bookmark_id
            deleted_attempt = self.journal.start_attempt(
                bookmark,
                mode="manual-delete",
                runner_version="journal-dashboard-v1",
                initial_event=(
                    "manual_delete_selected",
                    {"source_attempt_id": attempt_id},
                ),
            )
            decision = RouteDecision(
                bookmark_id=bookmark_id,
                outcome=RouteOutcome.DELETED,
                destination=None,
                text_evidence=(),
                visual_evidence=(),
                summary="Marked deleted because the Raindrop no longer exists.",
            )
            self.journal.record_decision(deleted_attempt, decision)
            self.journal.record_action(
                deleted_attempt,
                action_kind="mark_raindrop_deleted",
                status="succeeded",
                destination=None,
                request_count=0,
                payload={"source_attempt_id": attempt_id},
            )
            self.journal.complete(deleted_attempt)


class JournalReviewService:
    """Apply explicit human choices while preserving an append-only audit trail."""

    def __init__(
        self,
        journal: SQLiteRunJournal,
        client: Any,
        mutation_lock: threading.RLock | None = None,
        cover_cache: SQLiteCoverCache | None = None,
        on_reviews_changed: Callable[[], dict[str, Any]] | None = None,
    ):
        self.journal = journal
        self.client = client
        self._lock = mutation_lock or threading.RLock()
        self.cover_cache = cover_cache
        self.on_reviews_changed = on_reviews_changed

    def assignment_collections(self) -> list[dict[str, Any]]:
        with self._lock:
            folder_map = build_folder_map(
                self.client.get_collections(),
                self.client.get_collection_groups(),
            )
            return sorted(
                (
                    {"collection_id": collection_id, "path": path}
                    for path, collection_id in folder_map.items()
                    if is_manual_assignment_destination(path)
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
        collection = self._assignment_destination(collection_id)
        result = self._resolve_validated(
            attempt_id,
            collection=collection,
            selection_source=selection_source,
        )
        result["learning"] = self._refresh_learning()
        return result

    def resolve_batch(
        self,
        attempt_ids: list[str],
        *,
        collection_id: int,
    ) -> dict[str, Any]:
        """Resolve a batch after validating its shared destination once."""
        collection = self._assignment_destination(collection_id)
        results = []
        errors = []
        for attempt_id in attempt_ids:
            trace = self.journal.explain_attempt(attempt_id)
            bookmark_id = trace["attempt"]["bookmark_id"] if trace is not None else None
            try:
                results.append(
                    self._resolve_validated(
                        attempt_id,
                        collection=collection,
                        selection_source="custom",
                    )
                )
            except Exception as error:
                if isinstance(error, ReviewApplyFailed):
                    retry_attempt = error.retry_attempt
                    error_type = error.error_type
                else:
                    retry_attempts = (
                        self.journal.recent(
                            limit=1,
                            bookmark_ids={int(bookmark_id)},
                            latest_per_bookmark=True,
                        )
                        if bookmark_id is not None
                        else []
                    )
                    retry_attempt = retry_attempts[0] if retry_attempts else None
                    error_type = type(error).__name__
                errors.append({
                    "attempt_id": attempt_id,
                    "retry_attempt_id": (
                        retry_attempt["attempt_id"]
                        if retry_attempt is not None
                        else attempt_id
                    ),
                    "retry_attempt": retry_attempt,
                    "error": str(error),
                    "type": error_type,
                })
        response = {
            "status": "ok" if not errors else "partial",
            "resolved": len(results),
            "failed": len(errors),
            "results": results,
            "errors": errors,
        }
        if results:
            response["learning"] = self._refresh_learning()
        return response

    def _refresh_learning(self) -> dict[str, Any] | None:
        if self.on_reviews_changed is None:
            return None
        try:
            return self.on_reviews_changed()
        except Exception as error:
            # The Raindrop move and journal record already succeeded. Learning is
            # an independent derived artifact and must not make that review look
            # failed or encourage the user to retry the mutation.
            return {
                "status": "error",
                "error": type(error).__name__,
                "message": str(error),
            }

    def _assignment_destination(self, collection_id: int) -> dict[str, Any]:
        collection = next(
            (
                item
                for item in self.assignment_collections()
                if item["collection_id"] == collection_id
            ),
            None,
        )
        if collection is None:
            raise InvalidReviewDestination(
                "destination must be a live collection in the Art, Image, or Video group"
            )
        return collection

    def _resolve_validated(
        self,
        attempt_id: str,
        *,
        collection: dict[str, Any],
        selection_source: str,
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

            collection_id = int(collection["collection_id"])
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
                    "review outcomes must use the custom assignment collection picker"
                )
            if source.evidence_key is not None:
                evidence_destinations = set(review_choices.get(source.value, []))
                if destination not in evidence_destinations:
                    raise InvalidReviewDestination(
                        f"destination was not provided by {source.value} evidence"
                    )
            bookmark = self.client.get_raindrop(bookmark_id)
            if self.cover_cache is not None:
                self.cover_cache.record(bookmark)
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
                retry_trace = self.journal.explain_attempt(review_attempt.attempt_id)
                retry_attempts = self.journal.recent(
                    limit=1,
                    bookmark_ids={bookmark_id},
                    latest_per_bookmark=True,
                )
                if (  # pragma: no cover - defensive invariant
                    retry_trace is None or not retry_attempts
                ):
                    raise
                raise ReviewApplyFailed(
                    error,
                    retry_attempt=retry_attempts[0],
                    retry_trace=retry_trace,
                ) from error
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
