"""Compile conservative reusable routing rules from audited dashboard reviews."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from src.destinations import canonical_destination
from src.wd14_tagger import normalize_tag


REVIEW_FEEDBACK_FILE = "review_feedback.json"
SCHEMA_VERSION = 1
TAG_SOURCES = {"user_tag_or_hashtag"}
ALIAS_SOURCES = {"character_alias", "curated_text"}


@dataclass(frozen=True)
class ReviewObservation:
    source: str
    matched_value: str
    selected_destination: str


def _normalized_signal(source: str, value: str) -> tuple[str, str] | None:
    value = unicodedata.normalize("NFKC", value).strip()
    if source in TAG_SOURCES:
        return "tag_rules", normalize_tag(value.removeprefix("#"))
    if source in ALIAS_SOURCES:
        return "alias_rules", value.casefold()
    return None


def compile_review_feedback(
    observations: Iterable[ReviewObservation],
    *,
    existing_folders: set[str],
    min_support: int = 3,
    min_purity: float = 1.0,
    reviewed_attempts: int = 0,
) -> dict[str, Any]:
    """Promote only well-supported review signals with one dominant destination."""
    if min_support < 1:
        raise ValueError("min_support must be at least 1")
    if not 0 < min_purity <= 1:
        raise ValueError("min_purity must be in (0, 1]")

    votes: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    observation_count = 0
    for observation in observations:
        normalized = _normalized_signal(
            observation.source,
            observation.matched_value,
        )
        if normalized is None:
            continue
        destination = canonical_destination(observation.selected_destination)
        if destination not in existing_folders:
            continue
        votes[normalized][destination] += 1
        observation_count += 1

    promoted: dict[str, dict[str, dict[str, Any]]] = {
        "tag_rules": {},
        "alias_rules": {},
    }
    for (rule_kind, signal), destinations in sorted(votes.items()):
        total = sum(destinations.values())
        destination, support = destinations.most_common(1)[0]
        purity = support / total
        if support < min_support or purity < min_purity:
            continue
        promoted[rule_kind][signal] = {
            "destination": destination,
            "support": support,
            "observations": total,
            "purity": round(purity, 6),
        }

    promoted_count = sum(len(rules) for rules in promoted.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "min_support": min_support,
        "min_purity": min_purity,
        "reviewed_attempts": reviewed_attempts,
        "observations": observation_count,
        "promoted_signals": promoted_count,
        "rejected_signals": len(votes) - promoted_count,
        **promoted,
    }


def review_observations_from_journal(
    journal_path: str,
) -> tuple[list[ReviewObservation], int]:
    """Read successful manual reviews and their source decisions from SQLite."""
    connection = sqlite3.connect(journal_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT attempt.destination, event.payload_json
              FROM attempts AS attempt
              JOIN events AS event ON event.attempt_id = attempt.attempt_id
             WHERE attempt.mode = 'manual-review'
               AND attempt.outcome = 'confirmed'
               AND event.phase = 'manual_destination_selected'
            """
        ).fetchall()
        observations: list[ReviewObservation] = []
        reviewed_attempts = 0
        for row in rows:
            payload = json.loads(row["payload_json"])
            source_attempt_id = payload.get("source_attempt_id")
            destination = row["destination"]
            if not source_attempt_id or not destination:
                continue
            source = connection.execute(
                "SELECT decision_json FROM attempts WHERE attempt_id = ?",
                (source_attempt_id,),
            ).fetchone()
            if source is None or not source["decision_json"]:
                continue
            reviewed_attempts += 1
            decision = json.loads(source["decision_json"])
            for evidence in decision.get("text_evidence", []):
                matched_value = evidence.get("matched_value")
                evidence_source = evidence.get("source")
                if matched_value and evidence_source:
                    observations.append(
                        ReviewObservation(
                            source=str(evidence_source),
                            matched_value=str(matched_value),
                            selected_destination=str(destination),
                        )
                    )
        return observations, reviewed_attempts
    finally:
        connection.close()


def load_review_feedback(base_path: str) -> dict[str, Any]:
    path = os.path.join(base_path, REVIEW_FEEDBACK_FILE)
    if not os.path.exists(path):
        return {
            "schema_version": SCHEMA_VERSION,
            "tag_rules": {},
            "alias_rules": {},
        }
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported review feedback schema version")
    if not isinstance(payload.get("tag_rules"), dict) or not isinstance(
        payload.get("alias_rules"), dict
    ):
        raise ValueError("review feedback must contain tag_rules and alias_rules")
    return payload


def save_review_feedback(feedback: dict[str, Any], base_path: str) -> None:
    os.makedirs(base_path, exist_ok=True)
    path = os.path.join(base_path, REVIEW_FEEDBACK_FILE)
    temporary_path = f"{path}.tmp"
    with open(temporary_path, "w", encoding="utf-8") as handle:
        json.dump(feedback, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(temporary_path, path)


def learn_from_review_journal(
    *,
    journal_path: str,
    db_path: str,
    min_support: int = 3,
    min_purity: float = 1.0,
) -> dict[str, Any]:
    with open(
        os.path.join(db_path, "folder_id_map.json"),
        encoding="utf-8",
    ) as handle:
        existing_folders = set(json.load(handle))
    observations, reviewed_attempts = review_observations_from_journal(journal_path)
    feedback = compile_review_feedback(
        observations,
        existing_folders=existing_folders,
        min_support=min_support,
        min_purity=min_purity,
        reviewed_attempts=reviewed_attempts,
    )
    save_review_feedback(feedback, db_path)
    return feedback


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="chroma_db")
    parser.add_argument("--journal-path")
    parser.add_argument("--min-support", type=int, default=3)
    parser.add_argument("--min-purity", type=float, default=1.0)
    args = parser.parse_args()
    journal_path = args.journal_path or os.path.join(
        args.db_path,
        "run-journal.sqlite",
    )
    result = learn_from_review_journal(
        journal_path=journal_path,
        db_path=args.db_path,
        min_support=args.min_support,
        min_purity=args.min_purity,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
