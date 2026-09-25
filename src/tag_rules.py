"""Tag rule extraction and management."""

import json
import os
from collections import defaultdict
from typing import Any

from src.destinations import is_art_destination

TAG_RULES_FILE = "tag_rules.json"
TAG_RULES_CANDIDATES_FILE = "tag_rules_candidates.json"
SERIES_RULES_FILE = "series_rules.json"
MIN_TAG_FREQUENCY = 3
MAX_MISMATCHES = 3
RuleTarget = str | list[str]

# Explicit user-library vocabulary that can be matched in titles/excerpts.
# These are series signals, not generic prose keywords; keeping the allowlist
# narrow avoids turning every mention of a short folder name into a route.
TEXT_SERIES_ALIASES: dict[str, str] = {
    "コノカ": "Art/GAMES/BA",
    "クルミ": "Art/GAMES/BA",
    "ヒフミ": "Art/GAMES/BA",
    "パジャマリー": "Art/GAMES/BA",
    "ブルアカ": "Art/GAMES/BA",
    "ブルーアーカイブ": "Art/GAMES/BA",
    "アビドス": "Art/GAMES/BA",
    "vedal": "Art/NEUROVERSE",
    "heartheartart": "Art/NEUROVERSE",
}
SERIES_ALIASES: dict[str, str] = {
    **TEXT_SERIES_ALIASES,
    "girls_und_panzer": "Art/ANIME/GUP",
}


def _canonical_tag(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def extract_candidate_tag_rules(
    bookmarks: list[dict[str, Any]],
) -> dict[str, RuleTarget]:
    """Extract candidate exact tag rules: tag -> folder where tag appears >= 3 times.

    Returns a dict mapping tag to folder path.
    """
    # Count tag occurrences per folder
    folder_tag_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for bm in bookmarks:
        folder = bm.get("folder_path", "")
        if not is_art_destination(folder):
            continue
        tags = bm.get("tags", [])
        user_tags = [t for t in tags if not t.startswith(("ai:", "sorter-"))]
        for tag in user_tags:
            folder_tag_counts[folder][tag] += 1

    # Extract rules where frequency >= threshold
    paths_by_tag: dict[str, set[str]] = defaultdict(set)
    for folder, tag_counts in folder_tag_counts.items():
        for tag, count in tag_counts.items():
            if count >= MIN_TAG_FREQUENCY:
                paths_by_tag[tag].add(folder)

    rules: dict[str, RuleTarget] = {}
    for tag, paths in paths_by_tag.items():
        ordered_paths = sorted(paths)
        rules[tag] = ordered_paths[0] if len(ordered_paths) == 1 else ordered_paths
    return rules


def save_tag_rules(
    rules: dict[str, RuleTarget],
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


def load_tag_rules(base_path: str) -> tuple[dict[str, RuleTarget], dict[str, int]]:
    """Load validated tag rules and mismatch counts."""
    path = os.path.join(base_path, TAG_RULES_FILE)
    if not os.path.exists(path):
        return {}, {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("rules", {}), data.get("mismatches", {})


def validate_tag_rules(
    rules: dict[str, RuleTarget],
    existing_folders: set[str],
) -> dict[str, RuleTarget]:
    """Disable rules that point to missing folders."""
    validated: dict[str, RuleTarget] = {}
    for tag, target in rules.items():
        if isinstance(target, str):
            if target in existing_folders:
                validated[tag] = target
            continue
        candidates = [path for path in target if path in existing_folders]
        if candidates:
            validated[tag] = candidates[0] if len(candidates) == 1 else candidates
    return validated


# ---------------------------------------------------------------------------
# Series rules
# ---------------------------------------------------------------------------

def extract_series_rules(folder_paths: list[str]) -> dict[str, RuleTarget]:
    """Map terminal folder names to one or more canonical folder paths.

    WD14 copyright/series labels commonly use the normalized collection name
    (for example ``touhou``). Duplicate names retain every group-specific
    candidate so the resolver can select one from bookmark modality.
    """
    paths_by_tag: dict[str, set[str]] = defaultdict(set)
    art_paths = [path for path in folder_paths if is_art_destination(path)]
    for path in art_paths:
        terminal_name = path.rsplit("/", 1)[-1]
        tag = _canonical_tag(terminal_name)
        if tag:
            paths_by_tag[tag].add(path)

    rules: dict[str, RuleTarget] = {}
    for tag, paths in paths_by_tag.items():
        ordered_paths = sorted(paths)
        rules[tag] = ordered_paths[0] if len(ordered_paths) == 1 else ordered_paths
    live_folders = set(art_paths)
    for alias, target in SERIES_ALIASES.items():
        if target in live_folders:
            rules[_canonical_tag(alias)] = target
    return rules


def load_series_rules(base_path: str) -> dict[str, RuleTarget]:
    """Load series tag -> folder mappings.

    Returns empty dict if the file doesn't exist.
    """
    path = os.path.join(base_path, SERIES_RULES_FILE)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_series_rules(rules: dict[str, RuleTarget], base_path: str) -> None:
    """Save series tag -> folder mappings."""
    path = os.path.join(base_path, SERIES_RULES_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rules, f, indent=2)


def validate_series_rules(
    rules: dict[str, RuleTarget],
    existing_folders: set[str],
) -> dict[str, RuleTarget]:
    """Disable series rules that point to missing folders."""
    validated: dict[str, RuleTarget] = {}
    for tag, target in rules.items():
        if isinstance(target, str):
            if target in existing_folders:
                validated[tag] = target
            continue
        candidates = [path for path in target if path in existing_folders]
        if candidates:
            validated[tag] = candidates[0] if len(candidates) == 1 else candidates
    return validated
