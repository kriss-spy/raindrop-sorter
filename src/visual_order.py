"""Order journal records so AI-generated visual labels form local clusters."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, TypeVar


Record = TypeVar("Record", bound=Mapping[str, Any])


def order_by_visual_similarity(
    records: Sequence[Record],
    *,
    labels_key: str = "visual_labels",
) -> list[Record]:
    """Return a deterministic nearest-neighbour order using weighted Jaccard.

    Rare labels carry more weight than ubiquitous composition labels, which
    keeps visually distinctive records adjacent without requiring image loads.
    """
    if len(records) < 2:
        return list(records)

    indexed = [
        (
            index,
            record,
            {
                str(label).strip().casefold()
                for label in record.get(labels_key, ()) or ()
                if str(label).strip()
            },
        )
        for index, record in enumerate(records)
    ]
    frequencies = Counter(label for _index, _record, labels in indexed for label in labels)
    weights = {
        label: 1 + math.log((len(indexed) + 1) / (frequency + 1))
        for label, frequency in frequencies.items()
    }

    def label_score(item: tuple[int, Record, set[str]]) -> float:
        return sum(weights[label] for label in item[2])

    def similarity(
        left: tuple[int, Record, set[str]],
        right: tuple[int, Record, set[str]],
    ) -> float:
        union = left[2] | right[2]
        if not union:
            return 0.0
        union_weight = sum(weights[label] for label in union)
        intersection_weight = sum(weights[label] for label in left[2] & right[2])
        return intersection_weight / union_weight if union_weight else 0.0

    remaining = list(indexed)
    remaining.sort(key=lambda item: (-label_score(item), item[0]))
    current = remaining.pop(0)
    ordered: list[Record] = []
    while True:
        ordered.append(current[1])
        if not remaining:
            return ordered
        best_index = max(
            range(len(remaining)),
            key=lambda index: (
                similarity(current, remaining[index]),
                label_score(remaining[index]),
                -remaining[index][0],
            ),
        )
        current = remaining.pop(best_index)
