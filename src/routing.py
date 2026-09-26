"""Native two-step routing policy for the revised local architecture."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Literal

import numpy as np

from src.calibrations import BOOKMARK_ROUTES, CHARACTER_ALIAS_ROUTES, TAG_ROUTES, TEXT_ROUTES
from src.destinations import canonical_destination, is_art_destination
from src.modality import bookmark_modality
from src.tag_rules import RuleTarget
from src.visual_exemplars import VisualExemplarIndex, score_visual_embedding
from src.wd14_tagger import normalize_tag, semantic_tag_keys


class RouteOutcome(StrEnum):
    CONFIRMED = "confirmed"
    PROVISIONAL = "provisional"
    REVIEW = "review"
    CONFLICT = "conflict"


TextStrength = Literal["strong", "contextual", "weak", "conflicting"]
VisualStatus = Literal["pass", "inconclusive", "conflict", "unavailable", "not_applicable", "bypassed"]


@dataclass(frozen=True)
class TextEvidence:
    kind: str
    destination: str | None
    strength: TextStrength | None
    matched_value: str | None = None
    entity: str | None = None
    source: str | None = None
    explanation: str = ""
    candidates: tuple[str, ...] = ()
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VisualEvidence:
    status: VisualStatus
    destination: str | None
    method: str
    explanation: str
    labels: tuple[str, ...] = ()
    candidates: tuple[str, ...] = ()
    winner: str | None = None
    runner_up: str | None = None
    similarity: float | None = None
    runner_up_similarity: float | None = None
    margin: float | None = None
    min_similarity: float | None = None
    min_margin: float | None = None
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RouteDecision:
    bookmark_id: int
    outcome: RouteOutcome
    destination: str | None
    text_evidence: tuple[TextEvidence, ...]
    visual_evidence: tuple[VisualEvidence, ...]
    summary: str
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TextIdentifier:
    """Identify destinations only from user-visible text and user tags."""

    def __init__(
        self,
        tag_rules: dict[str, RuleTarget],
        series_rules: dict[str, RuleTarget],
        review_feedback: dict[str, Any] | None = None,
    ):
        self.tag_rules = {normalize_tag(key): value for key, value in tag_rules.items()}
        self.series_rules = {normalize_tag(key): value for key, value in series_rules.items()}
        feedback = review_feedback or {}
        self.confirmed_tag_rules = {
            normalize_tag(key): value["destination"]
            for key, value in feedback.get("tag_rules", {}).items()
        }
        self.confirmed_alias_rules = {
            unicodedata.normalize("NFKC", key).casefold(): value["destination"]
            for key, value in feedback.get("alias_rules", {}).items()
        }

    def identify(self, bookmark: dict[str, Any]) -> TextEvidence:
        bookmark_id = _bookmark_id(bookmark)
        if bookmark_id is not None and bookmark_id in BOOKMARK_ROUTES:
            destination = canonical_destination(BOOKMARK_ROUTES[bookmark_id])
            return TextEvidence(
                kind="user_confirmed_rule", destination=destination, strength="strong",
                matched_value=str(bookmark_id), source="bookmark_calibration",
                explanation="A user-confirmed bookmark assignment matched exactly.",
            )

        modality = bookmark_modality(bookmark)
        visible_tags = [str(tag) for tag in bookmark.get("tags", []) if not str(tag).startswith(("ai:", "sorter-"))]
        fields = {field: unicodedata.normalize("NFKC", str(bookmark.get(field, "") or "")) for field in ("title", "excerpt", "note")}
        hashtags = [match for value in fields.values() for match in re.findall(r"#([\w-]+)", value, flags=re.UNICODE)]
        searchable = "\n".join(fields.values()).casefold()
        confirmed_matches: list[tuple[str, str]] = []
        for value in [*visible_tags, *hashtags]:
            destination = _resolve_target(
                self.confirmed_tag_rules.get(normalize_tag(value)),
                modality,
            )
            if destination is not None:
                confirmed_matches.append((str(value), destination))
        for alias, target in self.confirmed_alias_rules.items():
            destination = _resolve_target(target, modality)
            if destination is not None and _contains_alias(searchable, alias):
                confirmed_matches.append((alias, destination))
        confirmed_destinations = sorted({match[1] for match in confirmed_matches})
        if len(confirmed_destinations) == 1:
            return TextEvidence(
                kind="user_confirmed_rule",
                destination=confirmed_destinations[0],
                strength="strong",
                matched_value=", ".join(dict.fromkeys(match[0] for match in confirmed_matches)),
                source="review_feedback",
                explanation="Repeated dashboard reviews confirmed this routing signal.",
            )
        if len(confirmed_destinations) > 1:
            return TextEvidence(
                kind="personal_interest_text",
                destination=None,
                strength="conflicting",
                matched_value=", ".join(dict.fromkeys(match[0] for match in confirmed_matches)),
                source="review_feedback",
                explanation="Confirmed review signals lead to multiple destinations.",
                candidates=tuple(confirmed_destinations),
            )
        matches: list[TextEvidence] = []
        for value in [*visible_tags, *hashtags]:
            key = normalize_tag(value)
            target = self.tag_rules.get(key) or self.series_rules.get(key)
            destination = _resolve_target(target, modality)
            if destination is not None:
                matches.append(TextEvidence(
                    kind="personal_interest_text", destination=destination, strength="strong",
                    matched_value=value, source="user_tag_or_hashtag",
                    explanation=f"Explicit tag or hashtag {value!r} matched.",
                ))

        for alias, target in TEXT_ROUTES.items():
            normalized_alias = unicodedata.normalize("NFKC", alias).casefold()
            destination = _resolve_target(target, modality)
            if destination and _contains_alias(searchable, normalized_alias):
                matches.append(_alias_evidence(normalized_alias, destination, "curated_text"))
        character_matches: list[
            tuple[str, tuple[str, ...], tuple[tuple[int, int], ...]]
        ] = []
        for alias, targets in CHARACTER_ALIAS_ROUTES.items():
            spans = _alias_spans(
                searchable,
                alias,
                require_script_boundaries=not alias.isascii() and len(alias) <= 2,
            )
            if spans:
                character_matches.append((alias, targets, spans))
        specific_character_matches = [
            (alias, targets)
            for alias, targets, spans in character_matches
            if any(
                not any(
                    alias != longer_alias
                    and longer_start <= start
                    and end <= longer_end
                    for longer_alias, _longer_targets, longer_spans in character_matches
                    for longer_start, longer_end in longer_spans
                )
                for start, end in spans
            )
        ]
        for alias, targets in specific_character_matches:
            matches.extend(
                _alias_evidence(alias, destination, "character_alias")
                for target in targets
                if (destination := _resolve_target(target, modality)) is not None
            )

        if not matches:
            return TextEvidence(kind="no_match", destination=None, strength=None, explanation="No personal-interest text match was found.")
        source_priority = {
            "user_tag_or_hashtag": 3,
            "curated_text": 2,
            "character_alias": 1,
        }
        highest_priority = max(source_priority.get(match.source or "", 0) for match in matches)
        decisive_matches = [
            match
            for match in matches
            if source_priority.get(match.source or "", 0) == highest_priority
        ]
        destinations = tuple(sorted({
            canonical_destination(match.destination)
            for match in decisive_matches
            if match.destination
        }))
        if len(destinations) > 1:
            details = "; ".join(
                f"{match.matched_value!r} → {canonical_destination(match.destination)}"
                for match in decisive_matches
                if match.destination
            )
            return TextEvidence(
                kind="personal_interest_text", destination=None, strength="conflicting",
                matched_value=", ".join(
                    dict.fromkeys(
                        match.matched_value
                        for match in decisive_matches
                        if match.matched_value
                    )
                ) or None,
                source="multiple",
                explanation=f"Text matches lead to multiple destinations: {details}.",
                candidates=destinations,
            )
        strongest = max(decisive_matches, key=lambda match: _strength_rank(match.strength))
        return TextEvidence(**{**strongest.to_dict(), "destination": destinations[0], "candidates": destinations})


class VisualVerifier:
    """Turn WD14 labels and an optional exemplar embedding into visual evidence."""

    def __init__(self, tag_rules: dict[str, RuleTarget], series_rules: dict[str, RuleTarget], exemplar_index: VisualExemplarIndex | None):
        self.tag_rules = {normalize_tag(key): value for key, value in tag_rules.items()}
        self.series_rules = {normalize_tag(key): value for key, value in series_rules.items()}
        self.character_alias_rules = {
            normalize_tag(key): list(targets)
            for key, targets in CHARACTER_ALIAS_ROUTES.items()
        }
        self.exemplar_index = exemplar_index

    def verify(self, bookmark: dict[str, Any], *, labels: list[str], embedding: Any | None, bypass: bool = False) -> VisualEvidence:
        if bypass:
            return VisualEvidence(status="bypassed", destination=None, method="user_confirmed_rule", explanation="Visual verification was bypassed by a user-confirmed rule.")
        if bookmark_modality(bookmark) != "art":
            return VisualEvidence(status="not_applicable", destination=None, method="none", explanation="The bookmark is not visual art.")
        if not _has_image_source(bookmark):
            return VisualEvidence(status="unavailable", destination=None, method="cover", explanation="The bookmark has no cover image.")

        normalized_labels = tuple(dict.fromkeys(semantic for raw in labels for semantic in semantic_tag_keys(str(raw).removeprefix("ai:wdtag-"))))
        modality = bookmark_modality(bookmark)
        identity_destinations: set[str] = set()
        learned_destinations: set[str] = set()
        for label in normalized_labels:
            target = (
                TAG_ROUTES.get(label)
                or self.series_rules.get(label)
                or self.character_alias_rules.get(label)
            )
            destination = _resolve_target(target, modality)
            if destination is not None:
                identity_destinations.add(canonical_destination(destination))
            learned_destination = _resolve_target(self.tag_rules.get(label), modality)
            if learned_destination is not None:
                learned_destinations.add(canonical_destination(learned_destination))

        exemplar = None
        exemplar_pass = False
        if self.exemplar_index is not None and embedding is not None:
            exemplar = score_visual_embedding(np.asarray(embedding, dtype=np.float32), self.exemplar_index, neighbors_per_folder=self.exemplar_index.neighbors_per_folder)
            exemplar_pass = bool(exemplar and exemplar.similarity >= self.exemplar_index.min_similarity and exemplar.margin >= self.exemplar_index.min_margin)

        if len(identity_destinations) > 1:
            return _visual_result(status="conflict", destination=None, candidates=tuple(sorted(identity_destinations)), labels=normalized_labels, exemplar=exemplar, index=self.exemplar_index, explanation="Recognized WD14 identity labels disagree.")
        if identity_destinations:
            destination = next(iter(identity_destinations))
            return _visual_result(status="pass", destination=destination, labels=normalized_labels, exemplar=exemplar, index=self.exemplar_index, explanation=f"Recognized WD14 identity labels support {destination}; generic learned tags and visual similarity cannot override an explicit identity.")
        if exemplar_pass and exemplar is not None:
            destination = canonical_destination(exemplar.folder_path)
            return _visual_result(status="pass", destination=destination, labels=normalized_labels, exemplar=exemplar, index=self.exemplar_index, explanation=f"Visual exemplar similarity supports {destination} because no explicit identity label matched.")
        if len(learned_destinations) > 1:
            return _visual_result(status="conflict", destination=None, candidates=tuple(sorted(learned_destinations)), labels=normalized_labels, exemplar=exemplar, index=self.exemplar_index, explanation="Lower-confidence learned visual tags disagree and no explicit identity label matched.")
        if learned_destinations:
            destination = next(iter(learned_destinations))
            return _visual_result(status="pass", destination=destination, labels=normalized_labels, exemplar=exemplar, index=self.exemplar_index, explanation=f"A learned visual tag supports {destination}; no explicit identity label or passing exemplar was available.")
        return _visual_result(status="inconclusive", destination=None, labels=normalized_labels, exemplar=exemplar, index=self.exemplar_index, explanation="No visual destination passed its calibrated thresholds.")


class RouteEngine:
    """Pure implementation of the decision table in ARCHITECTURE.md."""

    def route(self, *, bookmark_id: int, text: TextEvidence, visual: VisualEvidence) -> RouteDecision:
        text_destination = canonical_destination(text.destination) if text.destination else None
        visual_destination = canonical_destination(visual.destination) if visual.destination else None
        if text.kind == "user_confirmed_rule":
            outcome, destination = RouteOutcome.CONFIRMED, text_destination
        elif text.strength == "conflicting" or visual.status == "conflict":
            outcome, destination = RouteOutcome.CONFLICT, None
        elif text_destination and visual.status == "pass":
            outcome, destination = ((RouteOutcome.CONFIRMED, text_destination) if text_destination == visual_destination else (RouteOutcome.CONFLICT, None))
        elif text_destination and text.strength in {"strong", "contextual"}:
            outcome, destination = RouteOutcome.PROVISIONAL, text_destination
        elif text_destination:
            outcome, destination = RouteOutcome.REVIEW, None
        elif visual.status == "pass" and visual_destination:
            outcome, destination = RouteOutcome.PROVISIONAL, visual_destination
        else:
            outcome, destination = RouteOutcome.REVIEW, None
        return RouteDecision(
            bookmark_id=bookmark_id, outcome=outcome, destination=destination,
            text_evidence=(text,), visual_evidence=(visual,),
            summary=_decision_summary(outcome, destination, text, visual),
        )


def _bookmark_id(bookmark: dict[str, Any]) -> int | None:
    try:
        return int(bookmark["_id"])
    except (KeyError, TypeError, ValueError):
        return None


def _has_image_source(bookmark: dict[str, Any]) -> bool:
    return bool(bookmark.get("cover")) or any(
        str(item.get("type", "")).casefold() == "image" and item.get("link")
        for item in bookmark.get("media") or []
    )


def _resolve_target(target: RuleTarget | None, modality: str | None) -> str | None:
    if target is None or modality != "art":
        return None
    candidates = [
        candidate
        for candidate in ([target] if isinstance(target, str) else list(target))
        if is_art_destination(candidate)
    ]
    if len(candidates) == 1:
        return canonical_destination(candidates[0])
    return None


def _contains_alias(
    text: str,
    alias: str,
    *,
    require_script_boundaries: bool = False,
) -> bool:
    return bool(
        _alias_spans(
            text,
            alias,
            require_script_boundaries=require_script_boundaries,
        )
    )


def _alias_spans(
    text: str,
    alias: str,
    *,
    require_script_boundaries: bool = False,
) -> tuple[tuple[int, int], ...]:
    if not alias:
        return ()
    if alias.isascii():
        return tuple(
            (match.start(), match.end())
            for match in re.finditer(rf"(?<![\w]){re.escape(alias)}(?![\w])", text)
        )
    if not alias.isascii():
        if not require_script_boundaries:
            return tuple(
                (match.start(), match.end())
                for match in re.finditer(re.escape(alias), text)
            )
        spans: list[tuple[int, int]] = []
        start = 0
        while (index := text.find(alias, start)) != -1:
            before = text[index - 1] if index > 0 else ""
            after_index = index + len(alias)
            after = text[after_index] if after_index < len(text) else ""
            if (
                _script_family(before) != _script_family(alias[0])
                and _script_family(after) != _script_family(alias[-1])
            ):
                spans.append((index, after_index))
            start = index + 1
        return tuple(spans)
    return ()


def _script_family(character: str) -> str | None:
    if not character:
        return None
    name = unicodedata.name(character, "")
    if character.isalpha() and name:
        return name.partition(" ")[0]
    if character.isascii() and (character.isalnum() or character == "_"):
        return "ASCII_WORD"
    return None


def _alias_evidence(alias: str, target: str, source: str) -> TextEvidence:
    weak = (alias.isascii() and len(alias) <= 4) or (not alias.isascii() and len(alias) == 1)
    return TextEvidence(
        kind="personal_interest_text", destination=canonical_destination(target),
        strength="weak" if weak else "strong", matched_value=alias, source=source,
        explanation=f"Matched alias {alias!r} with Unicode-aware boundaries.",
    )


def _strength_rank(strength: TextStrength | None) -> int:
    return {None: 0, "weak": 1, "contextual": 2, "strong": 3, "conflicting": 4}[strength]


def _visual_result(*, status: VisualStatus, destination: str | None, labels: tuple[str, ...], exemplar: Any | None, index: VisualExemplarIndex | None, explanation: str, candidates: tuple[str, ...] = ()) -> VisualEvidence:
    return VisualEvidence(
        status=status, destination=destination, method="wd14+visual_exemplar",
        explanation=explanation, labels=labels,
        candidates=candidates or tuple(sorted({destination} if destination else set())),
        winner=canonical_destination(exemplar.folder_path) if exemplar else None,
        runner_up=getattr(exemplar, "runner_up_folder", None),
        similarity=exemplar.similarity if exemplar else None,
        runner_up_similarity=getattr(exemplar, "runner_up_similarity", None),
        margin=exemplar.margin if exemplar else None,
        min_similarity=index.min_similarity if index else None,
        min_margin=index.min_margin if index else None,
    )


def _decision_summary(
    outcome: RouteOutcome,
    destination: str | None,
    text: TextEvidence,
    visual: VisualEvidence,
) -> str:
    if outcome is RouteOutcome.CONFIRMED:
        if text.kind == "user_confirmed_rule" and visual.status == "bypassed":
            return f"Confirmed {destination} by user rule; visual verification was bypassed."
        return f"Confirmed {destination}: text and visual evidence agree."
    if outcome is RouteOutcome.PROVISIONAL:
        return f"Moved provisionally to {destination}; independent confirmation is incomplete."
    if outcome is RouteOutcome.CONFLICT:
        return "Kept in Unsorted because text and visual evidence conflict."
    return "Kept in Unsorted because no destination met the routing policy."
