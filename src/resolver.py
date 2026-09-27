"""Resolver decision logic — the single source of truth for sorting decisions."""

import re
import unicodedata

from typing import Any, Protocol

import numpy as np

from src.calibrations import (
    calibrated_bookmark_folder,
    calibrated_content_folder,
    calibrated_text_folder,
)
from src.destinations import canonical_destination, is_image_destination
from src.embeddings import Embedder, build_text_input
from src.modality import bookmark_modality
from src.state_machine import tag_sorted, tag_reviewed
from src.tag_rules import RuleTarget, TEXT_SERIES_ALIASES
from src.visual_exemplars import VisualExemplarIndex, classify_visual_embedding
from src.wd14_tagger import normalize_tag, semantic_tag_keys


class _EmbedderLike(Protocol):
    def embed_one(self, text: str) -> np.ndarray: ...

# Configurable threshold: relative gap between 1st and 2nd nearest centroids
# must exceed this for a confident sort.
DEFAULT_RELATIVE_GAP_THRESHOLD = 0.15


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    dot = np.dot(a, b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0:
        return 0.0
    return float(dot / norm)


def find_best_centroid(
    embedding: np.ndarray,
    centroids: dict[str, np.ndarray],
) -> tuple[str | None, float]:
    """Find the nearest folder centroid and the gap to the 2nd nearest.

    Returns:
        (best_folder, relative_gap) where relative_gap is
        (sim1 - sim2) / sim1.  None if no centroids exist.
    """
    if not centroids:
        return None, 0.0

    similarities = []
    for folder, centroid in centroids.items():
        # Skip zero centroids (folders with no bookmarks)
        if np.linalg.norm(centroid) == 0:
            continue
        sim = cosine_similarity(embedding, centroid)
        similarities.append((folder, sim))

    if not similarities:
        return None, 0.0

    similarities.sort(key=lambda x: x[1], reverse=True)
    best_folder, best_sim = similarities[0]

    if len(similarities) == 1:
        return best_folder, 1.0

    second_sim = similarities[1][1]
    if best_sim <= 0:
        return best_folder, 0.0

    gap = (best_sim - second_sim) / best_sim
    return best_folder, gap


def _normalized_tags(tags: list[str]) -> list[str]:
    """Return canonical tag names for rule matching."""
    normalized: list[str] = []
    for t in tags:
        if t.startswith("ai:wdtag-"):
            t = t[len("ai:wdtag-"):]
            normalized.extend(semantic_tag_keys(t))
        else:
            normalized.append(normalize_tag(t))
    return list(dict.fromkeys(normalized))


def _normalized_hashtags(bookmark: dict[str, Any]) -> list[str]:
    """Extract explicit ASCII hashtags from user-visible bookmark text."""
    text = "\n".join(
        str(bookmark.get(field, "") or "")
        for field in ("title", "excerpt", "note")
    )
    return [normalize_tag(tag) for tag in re.findall(r"#([A-Za-z0-9_]+)", text)]


def _normalized_text_aliases(bookmark: dict[str, Any]) -> list[str]:
    """Return allowlisted series aliases found in user-visible text."""
    text = "\n".join(
        str(bookmark.get(field, "") or "")
        for field in ("title", "excerpt", "note")
    )
    normalized_text = normalize_tag(unicodedata.normalize("NFKC", text))
    return [
        normalize_tag(unicodedata.normalize("NFKC", alias))
        for alias in TEXT_SERIES_ALIASES
        if normalize_tag(unicodedata.normalize("NFKC", alias)) in normalized_text
    ]


def _has_visual_art_evidence(bookmark: dict[str, Any]) -> bool:
    """Whether completed vision found an anime-style person in an art post."""
    if bookmark_modality(bookmark) != "art":
        return False
    art_markers = {"1girl", "1boy", "multiple_girls", "multiple_boys"}
    return bool(art_markers.intersection(_normalized_tags(bookmark.get("tags", []))))


def _resolve_rule_target(
    bookmark: dict[str, Any],
    target: RuleTarget,
) -> str | None:
    """Choose one canonical route from a rule's possible destinations."""
    candidates = list(
        dict.fromkeys([target] if isinstance(target, str) else target)
    )
    candidates = [
        candidate
        for candidate in candidates
        if not is_image_destination(candidate)
    ]
    if len(candidates) == 1:
        return candidates[0]
    modality = bookmark_modality(bookmark)
    if modality is None:
        return None
    matching = [
        path
        for path in candidates
        if path.partition("/")[0].casefold() == modality
    ]
    return matching[0] if len(matching) == 1 else None


def _resolve_series_target(
    bookmark: dict[str, Any],
    target: RuleTarget,
) -> str | None:
    """Resolve a series target without crossing an explicit media group."""
    folder = _resolve_rule_target(bookmark, target)
    if folder is None:
        return None
    modality = bookmark_modality(bookmark)
    target_group = folder.partition("/")[0].casefold()
    if (
        modality is not None
        and target_group in {"art", "music", "video"}
        and target_group != modality
    ):
        return None
    return folder


def decide_folder(
    bookmark: dict[str, Any],
    centroids: dict[str, np.ndarray],
    tag_rules: dict[str, RuleTarget],
    embedder: _EmbedderLike | None = None,
    relative_gap_threshold: float = DEFAULT_RELATIVE_GAP_THRESHOLD,
    series_rules: dict[str, RuleTarget] | None = None,
    crossover_folder: str = "Art/ANIME",
    visual_index: VisualExemplarIndex | None = None,
    visual_min_similarity: float | None = None,
    visual_min_margin: float | None = None,
) -> tuple[str | None, str]:
    """Decide which folder a bookmark should go to.

    Priority order:
        1. Exact bookmark and reusable user calibrations.
        2. Exact tag rules (including normalized WD14 tags).
        3. Series rules (single matched series).
        4. Crossover fallback (multiple matched series).
        5. Folder centroid matching.

    Returns:
        (folder_path, reason) where folder_path is None if the item
        should stay in Unsorted (low confidence).
    """
    rule_folder, rule_reason = decide_folder_by_rule(
        bookmark,
        tag_rules,
        series_rules=series_rules,
        crossover_folder=crossover_folder,
        visual_index=visual_index,
        visual_min_similarity=visual_min_similarity,
        visual_min_margin=visual_min_margin,
    )
    if rule_folder is not None:
        return rule_folder, rule_reason

    # Priority 4: Folder centroid matching (fallback for non-art / no tag match)
    text = build_text_input(bookmark)
    if embedder is None:
        embedder = Embedder()
    embedding = embedder.embed_one(text)

    suggestion_centroids = {
        folder: centroid
        for folder, centroid in centroids.items()
        if not is_image_destination(folder)
    }
    best_folder, gap = find_best_centroid(embedding, suggestion_centroids)
    if best_folder is None:
        return None, "no_centroids"

    if gap >= relative_gap_threshold:
        return best_folder, f"centroid_match:gap={gap:.3f}"

    return None, f"low_confidence:gap={gap:.3f}"


def decide_folder_by_rule(
    bookmark: dict[str, Any],
    tag_rules: dict[str, RuleTarget],
    *,
    series_rules: dict[str, RuleTarget] | None = None,
    crossover_folder: str = "Art/ANIME",
    visual_index: VisualExemplarIndex | None = None,
    visual_min_similarity: float | None = None,
    visual_min_margin: float | None = None,
) -> tuple[str | None, str]:
    """Apply exact and series rules without loading an embedding model."""
    calibration = calibrated_bookmark_folder(bookmark)
    if calibration is not None and not is_image_destination(calibration[0]):
        return calibration

    normalized = _normalized_tags(bookmark.get("tags", []))
    rule_inputs = list(dict.fromkeys([*normalized, *_normalized_hashtags(bookmark)]))

    calibration = calibrated_content_folder(bookmark)
    if calibration is not None and not is_image_destination(calibration[0]):
        return calibration

    normalized_tag_rules = {
        normalize_tag(tag): folder for tag, folder in tag_rules.items()
    }
    for tag in rule_inputs:
        if tag in normalized_tag_rules:
            folder = _resolve_rule_target(bookmark, normalized_tag_rules[tag])
            if folder is not None:
                return folder, f"exact_tag_rule:{tag}"

    normalized_series_rules = {
        normalize_tag(tag): folder for tag, folder in (series_rules or {}).items()
    }
    matched_series: list[str] = []
    for tag in [*rule_inputs, *_normalized_text_aliases(bookmark)]:
        if tag in normalized_series_rules:
            folder = _resolve_series_target(bookmark, normalized_series_rules[tag])
            if folder is not None and folder not in matched_series:
                matched_series.append(folder)

    if len(matched_series) == 1:
        return matched_series[0], f"series_rule:{matched_series[0]}"
    if len(matched_series) > 1:
        return crossover_folder, "crossover_fallback"

    calibration = calibrated_text_folder(bookmark)
    if calibration is not None and not is_image_destination(calibration[0]):
        return calibration

    visual_embedding = bookmark.get("_visual_embedding")
    if visual_index is not None and visual_embedding is not None:
        visual_match = classify_visual_embedding(
            np.asarray(visual_embedding, dtype=np.float32),
            visual_index,
            min_similarity=(
                visual_index.min_similarity
                if visual_min_similarity is None
                else visual_min_similarity
            ),
            min_margin=(
                visual_index.min_margin
                if visual_min_margin is None
                else visual_min_margin
            ),
            neighbors_per_folder=visual_index.neighbors_per_folder,
        )
        if (
            visual_match is not None
            and not is_image_destination(visual_match.folder_path)
        ):
            return (
                visual_match.folder_path,
                "visual_exemplar:"
                f"similarity={visual_match.similarity:.3f},"
                f"margin={visual_match.margin:.3f}",
            )
    if _has_visual_art_evidence(bookmark):
        return crossover_folder, "visual_art_fallback"
    return None, "no_rule"


def resolve_bookmark(
    bookmark: dict[str, Any],
    centroids: dict[str, np.ndarray],
    tag_rules: dict[str, RuleTarget],
    embedder: _EmbedderLike | None = None,
    relative_gap_threshold: float = DEFAULT_RELATIVE_GAP_THRESHOLD,
    series_rules: dict[str, RuleTarget] | None = None,
    crossover_folder: str = "Art/ANIME",
    visual_index: VisualExemplarIndex | None = None,
    visual_min_similarity: float | None = None,
    visual_min_margin: float | None = None,
) -> tuple[int | None, list[str], str]:
    """Run the full resolver on a bookmark.

    Returns:
        (target_collection_id, new_tags, reason)
        target_collection_id is None if the bookmark stays in Unsorted.
    """
    folder, reason = decide_folder(
        bookmark,
        centroids,
        tag_rules,
        embedder=embedder,
        relative_gap_threshold=relative_gap_threshold,
        series_rules=series_rules,
        crossover_folder=crossover_folder,
        visual_index=visual_index,
        visual_min_similarity=visual_min_similarity,
        visual_min_margin=visual_min_margin,
    )

    if folder is None:
        new_tags = tag_reviewed(bookmark)
        return None, new_tags, reason

    folder = canonical_destination(folder)

    # Map folder path to collection ID
    collection_id = bookmark.get("_folder_id_map", {}).get(folder)
    if collection_id is None:
        # Folder not found in live hierarchy — safety invariant
        new_tags = tag_reviewed(bookmark)
        return None, new_tags, f"missing_folder:{folder}"

    new_tags = tag_sorted(bookmark, by_rule=_rule_name_from_reason(reason))
    return collection_id, new_tags, reason


def _rule_name_from_reason(reason: str) -> str | None:
    """Extract the rule tag from an exact_tag_rule reason, if present."""
    if reason.startswith("exact_tag_rule:"):
        return reason[len("exact_tag_rule:"):]
    return None
