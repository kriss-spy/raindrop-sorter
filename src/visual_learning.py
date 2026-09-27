"""Bounded visual rule learning for historical bookmarks."""

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.destinations import is_image_destination
from src.tag_rules import RuleTarget
from src.wd14_tagger import semantic_tag_keys


@dataclass(frozen=True)
class VisualLearningConfig:
    """Cost and confidence limits for historical cover analysis."""

    max_samples: int = 192
    max_folders: int = 32
    min_tag_support: int = 3
    min_tag_purity: float = 0.9
    stability_patience: int = 48
    min_folder_rounds: int = 2

    def __post_init__(self) -> None:
        if self.max_samples < 0:
            raise ValueError("max_samples must be non-negative")
        if self.max_folders < 0:
            raise ValueError("max_folders must be non-negative")
        if self.min_tag_support < 1:
            raise ValueError("min_tag_support must be at least 1")
        if not 0 < self.min_tag_purity <= 1:
            raise ValueError("min_tag_purity must be between 0 and 1")
        if self.stability_patience < 0:
            raise ValueError("stability_patience must be non-negative")
        if self.min_folder_rounds < 0:
            raise ValueError("min_folder_rounds must be non-negative")


@dataclass(frozen=True)
class VisualLearningResult:
    """Rules and accounting produced by a bounded learning run."""

    rules: dict[str, RuleTarget]
    tags_by_bookmark_id: dict[int, list[str]]
    samples_analyzed: int
    analysis_failures: int
    eligible_candidates: int
    folders_selected: int
    stop_reason: str


def _supported_rules(
    counts: dict[str, Counter[str]],
    config: VisualLearningConfig,
) -> dict[str, RuleTarget]:
    rules: dict[str, RuleTarget] = {}
    for tag, folder_counts in counts.items():
        counts_by_modality: dict[str, Counter[str]] = defaultdict(Counter)
        for folder, support in folder_counts.items():
            modality = folder.partition("/")[0].casefold()
            counts_by_modality[modality][folder] += support

        targets: list[str] = []
        for modality_counts in counts_by_modality.values():
            folder, support = sorted(
                modality_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[0]
            total = sum(modality_counts.values())
            if (
                support >= config.min_tag_support
                and support / total >= config.min_tag_purity
            ):
                targets.append(folder)
        targets.sort()
        if targets:
            rules[tag] = targets[0] if len(targets) == 1 else targets
    return rules


def _has_image_content(bookmark: dict[str, Any]) -> bool:
    if not bookmark.get("cover"):
        return False
    if str(bookmark.get("type", "")).casefold() == "image":
        return True
    media = bookmark.get("media") or []
    if any(str(item.get("type", "")).casefold() == "image" for item in media):
        return True
    # Older cached/test records may predate Raindrop's type/media fields.
    return "type" not in bookmark and "media" not in bookmark


def learn_visual_rules(
    bookmarks: list[dict[str, Any]],
    *,
    analyze: Callable[[dict[str, Any]], list[str]],
    config: VisualLearningConfig | None = None,
) -> VisualLearningResult:
    """Learn high-purity visual tag routes within a hard sample budget."""
    config = config or VisualLearningConfig()
    bookmarks_by_folder: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for bookmark in bookmarks:
        folder = str(bookmark.get("folder_path", ""))
        if (
            _has_image_content(bookmark)
            and folder
            and not is_image_destination(folder)
        ):
            bookmarks_by_folder[folder].append(bookmark)
    selected_folder_names = sorted(
        bookmarks_by_folder,
        key=lambda folder: (-len(bookmarks_by_folder[folder]), folder),
    )[: config.max_folders]
    bookmarks_by_folder = {
        folder: bookmarks_by_folder[folder]
        for folder in selected_folder_names
    }

    candidates: list[dict[str, Any]] = []
    round_index = 0
    while len(candidates) < config.max_samples:
        added = False
        for folder in sorted(bookmarks_by_folder):
            folder_bookmarks = bookmarks_by_folder[folder]
            if round_index < len(folder_bookmarks):
                candidates.append(folder_bookmarks[round_index])
                added = True
                if len(candidates) == config.max_samples:
                    break
        if not added:
            break
        round_index += 1
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    rules: dict[str, RuleTarget] = {}
    stable_samples = 0
    minimum_samples = min(
        config.max_samples,
        max(config.min_folder_rounds, config.min_tag_support)
        * len(bookmarks_by_folder),
    )
    stop_reason = (
        "sample_budget"
        if len(candidates) == config.max_samples
        else "candidates_exhausted"
    )
    samples_analyzed = 0
    analysis_failures = 0
    tags_by_bookmark_id: dict[int, list[str]] = {}
    for bookmark in candidates:
        folder = str(bookmark["folder_path"])
        try:
            detected_tags = sorted(set(analyze(bookmark)))
        except Exception:
            detected_tags = []
            analysis_failures += 1
        tags_by_bookmark_id[int(bookmark["_id"])] = detected_tags
        semantic_keys = {
            semantic_key
            for tag in detected_tags
            for semantic_key in semantic_tag_keys(tag)
        }
        for semantic_key in semantic_keys:
            counts[semantic_key][folder] += 1
        samples_analyzed += 1
        updated_rules = _supported_rules(counts, config)
        if updated_rules == rules:
            stable_samples += 1
        else:
            rules = updated_rules
            stable_samples = 0
        if (
            samples_analyzed >= minimum_samples
            and bool(rules)
            and stable_samples >= config.stability_patience
        ):
            stop_reason = "stable_rules"
            break

    return VisualLearningResult(
        rules=rules,
        tags_by_bookmark_id=tags_by_bookmark_id,
        samples_analyzed=samples_analyzed,
        analysis_failures=analysis_failures,
        eligible_candidates=sum(len(items) for items in bookmarks_by_folder.values()),
        folders_selected=len(bookmarks_by_folder),
        stop_reason=stop_reason,
    )
