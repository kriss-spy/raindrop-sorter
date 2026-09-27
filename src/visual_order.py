"""Order review records into likely work or character-destination groups."""

from __future__ import annotations

import csv
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeVar


Record = TypeVar("Record", bound=Mapping[str, Any])

_COLORS = {
    "aqua", "black", "blonde", "blue", "brown", "green", "grey", "gray",
    "multicolored", "orange", "pink", "purple", "red", "silver", "teal",
    "two-tone", "white", "yellow",
}
_IDENTITY_FEATURES = {
    "ahoge", "antenna_hair", "asymmetrical_bangs", "bob_cut", "braid",
    "crossed_bangs", "double_bun", "drill_hair", "dreadlocks", "eyepatch",
    "facial_mark", "fang", "glasses", "hair_bun", "hair_ornament",
    "hairclip", "hairpods", "halo", "headphones", "heterochromia",
    "horns", "low_twintails", "mole_under_eye", "multicolored_hair",
    "one_side_up", "pointy_ears", "ponytail", "rabbit_ears", "side_ponytail",
    "streaked_hair", "symbol-shaped_pupils", "tail", "twin_braids",
    "twintails", "two-tone_hair", "wings",
}


@lru_cache(maxsize=1)
def _wd14_character_labels() -> frozenset[str]:
    """Load the model's raw character-label category when it is available."""
    project_root = Path(__file__).resolve().parents[1]
    candidates = (
        project_root / ".cache" / "wd14" / "selected_tags.csv",
        project_root / ".scratch" / "wd14_model" / "selected_tags.csv",
    )
    for path in candidates:
        if not path.is_file():
            continue
        with path.open(encoding="utf-8") as source:
            return frozenset(
                row["name"].strip().casefold().replace(" ", "_")
                for row in csv.DictReader(source)
                if row.get("category") == "4"
            )
    return frozenset()


def visual_identity_labels(labels: Sequence[object]) -> list[str]:
    """Keep raw labels that describe identity, not pose or composition."""
    character_labels = _wd14_character_labels()
    selected: set[str] = set()
    for value in labels:
        label = str(value).strip().casefold().replace(" ", "_")
        if not label:
            continue
        tokens = label.split("_")
        is_colored_identity = (
            tokens[-1] in {"hair", "eyes"}
            and any(token in _COLORS for token in tokens[:-1])
        )
        is_specific_ears = label.endswith("_ears") and label not in {"ears", "animal_ears"}
        if (
            label in character_labels
            or label in _IDENTITY_FEATURES
            or is_colored_identity
            or is_specific_ears
        ):
            selected.add(label)
    return sorted(selected)


def visual_character_labels(labels: Sequence[object]) -> list[str]:
    """Return raw WD14 labels from the model's explicit character category."""
    character_labels = _wd14_character_labels()
    return sorted({
        str(value).strip().casefold().replace(" ", "_")
        for value in labels
        if str(value).strip().casefold().replace(" ", "_") in character_labels
    })


def _raw_label_order(records: list[Record], *, labels_key: str) -> list[Record]:
    indexed = [
        (record, set(str(label) for label in record.get(labels_key, ()) or ()))
        for record in records
    ]
    if len(indexed) < 2:
        return list(records)
    frequencies = Counter(label for _record, labels in indexed for label in labels)
    character_labels = _wd14_character_labels()
    weights = {
        label: (4 if label in character_labels else 1)
        * (1 + math.log((len(indexed) + 1) / (frequency + 1)))
        for label, frequency in frequencies.items()
    }

    def similarity(left: set[str], right: set[str]) -> float:
        union = left | right
        if not union:
            return 0.0
        return sum(weights[label] for label in left & right) / sum(
            weights[label] for label in union
        )

    remaining = list(indexed)
    current = remaining.pop(0)
    ordered: list[Record] = []
    while True:
        ordered.append(current[0])
        if not remaining:
            return ordered
        best_index = max(
            range(len(remaining)),
            key=lambda index: (similarity(current[1], remaining[index][1]), -index),
        )
        current = remaining.pop(best_index)


def order_by_review_group(
    records: Sequence[Record],
    *,
    group_key: str = "ai_group",
    labels_key: str = "ai_group_labels",
) -> list[Record]:
    """Group trusted text candidates, then cluster raw identity labels.

    The visual classifier's inferred work is deliberately excluded. Raw pose,
    framing, body, and composition labels are removed before this function is
    called, so shared poses cannot pull unrelated characters together.
    """
    groups: dict[str, list[Record]] = {}
    label_records: list[Record] = []
    ungrouped: list[Record] = []
    for record in records:
        group = str(record.get(group_key) or "").strip()
        if group:
            groups.setdefault(group.casefold(), []).append(record)
        elif record.get(labels_key):
            label_records.append(record)
        else:
            ungrouped.append(record)
    text_grouped = [record for group in groups.values() for record in group]
    return text_grouped + _raw_label_order(label_records, labels_key=labels_key) + ungrouped
