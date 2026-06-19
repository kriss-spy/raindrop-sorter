"""Folder centroid computation and storage."""

import json
import os
from collections import defaultdict
from typing import Any

import numpy as np

from src.embeddings import Embedder

CENTROIDS_FILE = "centroids.json"


def compute_folder_centroids(
    embeddings: np.ndarray,
    folders: list[str],
    folder_hierarchy: dict[str, list[str]],
) -> dict[str, np.ndarray]:
    """Compute mean embeddings for each folder, recursively.

    Args:
        embeddings: (N, D) array of bookmark embeddings.
        folders: List of folder paths, same length as embeddings.
        folder_hierarchy: Mapping from parent folder -> list of direct child folders.

    Returns:
        Mapping from folder path -> centroid vector.

    Recursive contribution: subfolder bookmarks feed parent centroids.
    """
    # Group embeddings by folder
    folder_embeddings: dict[str, list[np.ndarray]] = defaultdict(list)
    for folder, emb in zip(folders, embeddings):
        folder_embeddings[folder].append(emb)

    def gather_descendants(folder: str) -> list[str]:
        """Return this folder and all descendants."""
        result = [folder]
        for child in folder_hierarchy.get(folder, []):
            result.extend(gather_descendants(child))
        return result

    centroids: dict[str, np.ndarray] = {}
    all_folders = set(folders) | set(folder_hierarchy.keys())

    for folder in all_folders:
        descendants = gather_descendants(folder)
        embs = []
        for desc in descendants:
            embs.extend(folder_embeddings.get(desc, []))
        if embs:
            centroids[folder] = np.mean(embs, axis=0)
        else:
            # Folder exists in hierarchy but has no bookmarks
            centroids[folder] = np.zeros(embeddings.shape[1])

    return centroids


def save_centroids(
    centroids: dict[str, np.ndarray],
    base_path: str,
) -> None:
    """Serialize centroids to JSON as lists."""
    path = os.path.join(base_path, CENTROIDS_FILE)
    serializable = {folder: vec.tolist() for folder, vec in centroids.items()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2)


def load_centroids(base_path: str) -> dict[str, np.ndarray]:
    """Deserialize centroids from JSON."""
    path = os.path.join(base_path, CENTROIDS_FILE)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {folder: np.array(vec, dtype=np.float32) for folder, vec in data.items()}
