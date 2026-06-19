"""Resolver decision logic — the single source of truth for sorting decisions."""

import math
from typing import Any, Protocol

import numpy as np

from src.centroids import load_centroids
from src.embeddings import Embedder, build_text_input
from src.state_machine import tag_sorted, tag_reviewed
from src.tag_rules import load_tag_rules


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


def decide_folder(
    bookmark: dict[str, Any],
    centroids: dict[str, np.ndarray],
    tag_rules: dict[str, str],
    embedder: _EmbedderLike | None = None,
    relative_gap_threshold: float = DEFAULT_RELATIVE_GAP_THRESHOLD,
) -> tuple[str | None, str]:
    """Decide which folder a bookmark should go to.

    Returns:
        (folder_path, reason) where folder_path is None if the item
        should stay in Unsorted (low confidence).
    """
    # Priority 1: Exact tag rules (character recognition from WD14 tags)
    # In slice 1, tag_rules may be empty or from user tags only.
    tags = bookmark.get("tags", [])
    for tag in tags:
        if tag in tag_rules:
            return tag_rules[tag], f"exact_tag_rule:{tag}"

    # Priority 4: Folder centroid matching (fallback for non-art / no tag match)
    # Priorities 2 and 3 (series rules, crossover fallback) are vision-dependent
    # and handled in slice 2. They are skipped here since no WD14 tags exist yet.
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
