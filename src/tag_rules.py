"""Tag rule extraction and management."""

import json
import os
from collections import defaultdict
from typing import Any

TAG_RULES_FILE = "tag_rules.json"
TAG_RULES_CANDIDATES_FILE = "tag_rules_candidates.json"
MIN_TAG_FREQUENCY = 3
MAX_MISMATCHES = 3


def extract_candidate_tag_rules(
    bookmarks: list[dict[str, Any]],
) -> dict[str, str]:
    """Extract candidate exact tag rules: tag -> folder where tag appears >= 3 times.

    Returns a dict mapping tag to folder path.
    """
    # Count tag occurrences per folder
    folder_tag_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for bm in bookmarks:
        folder = bm.get("folder_path", "")
        if not folder:
            continue
        tags = bm.get("tags", [])
        user_tags = [t for t in tags if not t.startswith(("ai:", "sorter-"))]
        for tag in user_tags:
            folder_tag_counts[folder][tag] += 1

    # Extract rules where frequency >= threshold
    rules: dict[str, str] = {}
    for folder, tag_counts in folder_tag_counts.items():
        for tag, count in tag_counts.items():
            if count >= MIN_TAG_FREQUENCY:
                # If tag maps to multiple folders, keep the one with highest count
                if tag in rules:
                    # We don't have the count for the existing rule here,
                    # so we skip duplicates for simplicity in bootstrap.
                    # Re-index handles refinement.
                    continue
                rules[tag] = folder

    return rules


def save_tag_rules(
    rules: dict[str, str],
    mismatches: dict[str, int],
    base_path: str,
) -> None:
    """Save validated tag rules and mismatch counts."""
    path = os.path.join(base_path, TAG_RULES_FILE)
    data = {
        "rules": rules,
        "mismatches": mismatches,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_tag_rules(base_path: str) -> tuple[dict[str, str], dict[str, int]]:
    """Load validated tag rules and mismatch counts."""
    path = os.path.join(base_path, TAG_RULES_FILE)
    if not os.path.exists(path):
        return {}, {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("rules", {}), data.get("mismatches", {})


def validate_tag_rules(
    rules: dict[str, str],
    existing_folders: set[str],
) -> dict[str, str]:
    """Disable rules that point to missing folders."""
    return {tag: folder for tag, folder in rules.items() if folder in existing_folders}
