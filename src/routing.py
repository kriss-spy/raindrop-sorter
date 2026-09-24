"""Structured routing records shared by the local runner and journal.

The current resolver still returns its historical ``(target, tags, reason)`` tuple.
This module is the compatibility seam that makes those results readable without
changing the resolver's routing behaviour during the architecture migration.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class RouteOutcome(StrEnum):
    """Stable outcomes from the revised routing policy."""

    CONFIRMED = "confirmed"
    PROVISIONAL = "provisional"
    REVIEW = "review"
    CONFLICT = "conflict"


class EvidenceKind(StrEnum):
    """Evidence producers that can contribute to a route decision."""

    USER_CONFIRMED_RULE = "user_confirmed_rule"
    TAG_RULE = "tag_rule"
    SERIES_RULE = "series_rule"
    TEXT_ALIAS = "text_alias"
    CENTROID = "centroid"
    VISUAL_EXEMPLAR = "visual_exemplar"
    VISUAL_CLASSIFIER = "visual_classifier"
    SYSTEM = "system"


@dataclass(frozen=True)
class RouteEvidence:
    """One inspectable piece of evidence used by a decision."""

    kind: EvidenceKind
    destination: str | None = None
    status: str | None = None
    strength: str | None = None
    explanation: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RouteDecision:
    """A structured decision at the resolver/local-runner seam."""

    bookmark_id: int
    outcome: RouteOutcome
    destination: str | None
    reason_code: str
    summary: str
    text_evidence: tuple[RouteEvidence, ...] = ()
    visual_evidence: tuple[RouteEvidence, ...] = ()
    review_tag: str | None = None
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def decision_from_legacy_result(
    *,
    bookmark_id: int,
    destination: str | None,
    reason: str,
    resulting_tags: list[str],
) -> RouteDecision:
    """Translate the current resolver result into the revised public shape.

    This deliberately preserves today's move/review policy. The future
    ``RouteEngine`` can replace this adapter while callers and journal records stay
    stable.
    """
    evidence = _evidence_from_reason(reason, destination)
    visual = evidence.kind in {
        EvidenceKind.VISUAL_EXEMPLAR,
        EvidenceKind.VISUAL_CLASSIFIER,
    }
    outcome = (
        RouteOutcome.CONFIRMED if destination is not None else RouteOutcome.REVIEW
    )
    review_tag = next(
        (tag for tag in resulting_tags if tag.startswith("sorter-reviewed:")),
        None,
    )
    if destination is None:
        summary = f"Kept in Unsorted: {evidence.explanation}"
    else:
        summary = f"Move to {destination}: {evidence.explanation}"
    return RouteDecision(
        bookmark_id=bookmark_id,
        outcome=outcome,
        destination=destination,
        reason_code=reason.partition(":")[0],
        summary=summary,
        text_evidence=() if visual else (evidence,),
        visual_evidence=(evidence,) if visual else (),
        review_tag=review_tag,
    )


def _evidence_from_reason(reason: str, destination: str | None) -> RouteEvidence:
    code, separator, value = reason.partition(":")
    details = _parse_details(value) if separator else {}
    if code == "user_calibration":
        kind = EvidenceKind.USER_CONFIRMED_RULE
        explanation = "a user-confirmed bookmark rule matched"
        details["visual_verification"] = "bypassed_by_user_confirmed_rule"
    elif code == "calibrated_tag":
        kind = EvidenceKind.VISUAL_CLASSIFIER
        explanation = "a user-confirmed visual tag rule matched"
    elif code == "calibrated_source":
        kind = EvidenceKind.USER_CONFIRMED_RULE
        explanation = "a user-confirmed source rule matched"
    elif code == "exact_tag_rule":
        kind = EvidenceKind.TAG_RULE
        explanation = f"exact tag rule {value!r} matched"
    elif code in {"series_rule", "crossover_fallback"}:
        kind = EvidenceKind.SERIES_RULE
        explanation = (
            "multiple series rules matched"
            if code == "crossover_fallback"
            else f"series rule {value!r} matched"
        )
    elif code in {"text_calibration", "calibrated_text", "character_text"}:
        kind = EvidenceKind.TEXT_ALIAS
        explanation = "a calibrated text alias matched"
    elif code in {"centroid_match", "low_confidence", "no_centroids"}:
        kind = EvidenceKind.CENTROID
        explanation = {
            "centroid_match": "the nearest folder centroid passed its gap threshold",
            "low_confidence": "the nearest folder centroid did not pass its gap threshold",
            "no_centroids": "no folder centroids were available",
        }[code]
    elif code == "visual_exemplar":
        kind = EvidenceKind.VISUAL_EXEMPLAR
        explanation = "the calibrated visual exemplar match passed its thresholds"
    elif code == "visual_art_fallback":
        kind = EvidenceKind.VISUAL_CLASSIFIER
        explanation = "visual labels indicated art but no specific route matched"
    else:
        kind = EvidenceKind.SYSTEM
        explanation = reason.replace("_", " ")
    status = "pass" if destination is not None else "inconclusive"
    if code == "visual_art_fallback":
        status = "legacy_fallback"
    return RouteEvidence(
        kind=kind,
        destination=destination,
        status=status,
        explanation=explanation,
        details=details,
    )


def _parse_details(value: str) -> dict[str, Any]:
    details: dict[str, Any] = {}
    for part in value.split(","):
        key, separator, raw = part.partition("=")
        if not separator:
            continue
        try:
            details[key] = float(raw)
        except ValueError:
            details[key] = raw
    return details
