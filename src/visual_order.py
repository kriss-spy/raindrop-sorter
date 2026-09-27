"""Order review records into likely work or character-destination groups."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypeVar


Record = TypeVar("Record", bound=Mapping[str, Any])


def order_by_review_group(
    records: Sequence[Record],
    *,
    group_key: str = "ai_group",
) -> list[Record]:
    """Return a stable order with records for the same likely work adjacent.

    The journal derives ``ai_group`` from text candidates first and the visual
    classifier's likely work second. Generic pose and composition labels are
    deliberately irrelevant here because they do not imply one assignment.
    """
    groups: dict[str, list[Record]] = {}
    ungrouped: list[Record] = []
    for record in records:
        group = str(record.get(group_key) or "").strip()
        if not group:
            ungrouped.append(record)
            continue
        groups.setdefault(group.casefold(), []).append(record)
    return [record for group in groups.values() for record in group] + ungrouped
