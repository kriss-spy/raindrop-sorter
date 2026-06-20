"""Resolver decision logic — the single source of truth for sorting decisions."""

from typing import Any, Protocol

import numpy as np

from src.embeddings import Embedder, build_text_input
from src.state_machine import tag_sorted, tag_reviewed


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
    """Return tags with ai:wdtag- prefix stripped for rule matching."""
    normalized: list[str] = []
    for t in tags:
        if t.startswith("ai:wdtag-"):
            normalized.append(t[len("ai:wdtag-"):])
        else:
            normalized.append(t)
    return normalized


def decide_folder(
    bookmark: dict[str, Any],
    centroids: dict[str, np.ndarray],
    tag_rules: dict[str, str],
    embedder: _EmbedderLike | None = None,
    relative_gap_threshold: float = DEFAULT_RELATIVE_GAP_THRESHOLD,
    series_rules: dict[str, str] | None = None,
    crossover_folder: str = "Art/ANIME",
) -> tuple[str | None, str]:
    """Decide which folder a bookmark should go to.

    Priority order:
        1. Exact tag rules (including normalized WD14 tags).
        2. Series rules (single matched series).
        3. Crossover fallback (multiple matched series).
        4. Folder centroid matching.

    Returns:
        (folder_path, reason) where folder_path is None if the item
        should stay in Unsorted (low confidence).
    """
    tags = bookmark.get("tags", [])
    normalized = _normalized_tags(tags)

    # Priority 1: Exact tag rules (character recognition from WD14 or user tags)
    for tag in normalized:
        if tag in tag_rules:
            return tag_rules[tag], f"exact_tag_rule:{tag}"

    # Priority 2 & 3: Series rules and crossover fallback
    series_rules = series_rules or {}
    matched_series: list[str] = []
    for tag in normalized:
        if tag in series_rules:
            matched_series.append(series_rules[tag])

    if len(matched_series) == 1:
        return matched_series[0], f"series_rule:{matched_series[0]}"

    if len(matched_series) > 1:
        return crossover_folder, "crossover_fallback"

    # Priority 4: Folder centroid matching (fallback for non-art / no tag match)
    text = build_text_input(bookmark)
    if embedder is None:
        embedder = Embedder()
    embedding = embedder.embed_one(text)

    best_folder, gap = find_best_centroid(embedding, centroids)
    if best_folder is None:
        return None, "no_centroids"

    if gap >= relative_gap_threshold:
        return best_folder, f"centroid_match:gap={gap:.3f}"

    return None, f"low_confidence:gap={gap:.3f}"


def resolve_bookmark(
    bookmark: dict[str, Any],
    centroids: dict[str, np.ndarray],
    tag_rules: dict[str, str],
    embedder: _EmbedderLike | None = None,
    relative_gap_threshold: float = DEFAULT_RELATIVE_GAP_THRESHOLD,
    series_rules: dict[str, str] | None = None,
    crossover_folder: str = "Art/ANIME",
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
    )

    if folder is None:
        new_tags = tag_reviewed(bookmark)
        return None, new_tags, reason

    # Map folder path to collection ID
    collection_id = bookmark.get("_folder_id_map", {}).get(folder)
    if collection_id is None:
        # Folder not found in live hierarchy — safety invariant
        new_tags = tag_reviewed(bookmark)
        return None, new_tags, f"missing_folder:{folder}"

    new_tags = tag_sorted(bookmark, by_rule=None)
    return collection_id, new_tags, reason
