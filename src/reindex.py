"""Weekly re-index and passive learning loop."""

import json
import os
import shutil
import time
from datetime import datetime, timezone
from typing import Any

import chromadb
import numpy as np

from src.centroids import compute_folder_centroids, save_centroids
from src.embeddings import build_text_input
from src.tag_rules import (
    RuleTarget,
    extract_candidate_tag_rules,
    extract_series_rules,
    load_tag_rules,
    save_series_rules,
    save_tag_rules,
    validate_tag_rules,
)

EMBED_CHUNK_SIZE = 256

NEW_DB_DIR = "chroma_db_new"
OLD_DB_DIR = "chroma_db_old"


def _parent_id(collection: dict[str, Any]) -> int | None:
    parent = collection.get("parent") or {}
    return parent.get("$id")


def _build_collection_paths(
    collections: list[dict[str, Any]],
    groups: list[dict[str, Any]] | None = None,
) -> dict[int, str]:
    by_id: dict[int, dict[str, Any]] = {c["_id"]: c for c in collections}
    group_by_root_id: dict[int, str] = {}
    for group in groups or []:
        group_name = str(group.get("title", "")).strip()
        for collection_id in group.get("collections", []):
            existing_group = group_by_root_id.get(collection_id)
            if existing_group is not None and existing_group != group_name:
                raise ValueError(
                    f"Root collection ID {collection_id} appears in multiple groups: "
                    f"{existing_group!r} and {group_name!r}"
                )
            group_by_root_id[collection_id] = group_name

    def path_for(collection_id: int) -> str:
        collection = by_id[collection_id]
        name = collection.get("title", "")
        parent_id = _parent_id(collection)
        if parent_id and parent_id in by_id:
            return f"{path_for(parent_id)}/{name}"
        group_name = group_by_root_id.get(collection_id, "")
        if group_name and group_name.casefold() != name.casefold():
            return f"{group_name}/{name}"
        return name

    return {collection_id: path_for(collection_id) for collection_id in by_id}


def build_folder_map(
    collections: list[dict[str, Any]],
    groups: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    """Map folder path -> collection ID."""
    paths_by_id = _build_collection_paths(collections, groups)
    folder_map: dict[str, int] = {}
    for collection_id, path in paths_by_id.items():
        existing_id = folder_map.get(path)
        if existing_id is not None and existing_id != collection_id:
            raise ValueError(
                f"Duplicate canonical collection path {path!r} for collection IDs "
                f"{existing_id} and {collection_id}; fetch and pass user groups to "
                "disambiguate root collections"
            )
        folder_map[path] = collection_id
    return folder_map


def build_folder_hierarchy(
    collections: list[dict[str, Any]],
    groups: list[dict[str, Any]] | None = None,
) -> dict[str, list[str]]:
    """Build parent -> [children] mapping using folder paths."""
    build_folder_map(collections, groups)
    paths_by_id = _build_collection_paths(collections, groups)

    hierarchy: dict[str, list[str]] = {}
    for collection in collections:
        parent_id = _parent_id(collection)
        if parent_id and parent_id in paths_by_id:
            parent_path = paths_by_id[parent_id]
            child_path = paths_by_id[collection["_id"]]
            hierarchy.setdefault(parent_path, []).append(child_path)

    return hierarchy


def load_existing_metadata(db_path: str) -> dict[str, dict[str, Any]]:
    """Load bookmark metadata keyed by bookmark ID from the existing ChromaDB."""
    if not os.path.isdir(db_path):
        return {}

    try:
        chroma_client = chromadb.PersistentClient(path=db_path)
        collection = chroma_client.get_or_create_collection(name="bookmarks")
        result = collection.get(include=["metadatas"])
    except Exception:
        # DB may be corrupt or mid-swap; treat as empty
        return {}

    metadata_by_id: dict[str, dict[str, Any]] = {}
    ids = result.get("ids", [])
    metadatas = result.get("metadatas") or []
    for bid, meta in zip(ids, metadatas):
        if meta is not None:
            metadata_by_id[bid] = meta
    return metadata_by_id


def detect_manual_corrections(
    live_bookmarks: list[dict[str, Any]],
    previous_metadata: dict[str, dict[str, Any]],
    rules: dict[str, RuleTarget],
    mismatches: dict[str, int],
) -> dict[str, int]:
    """Detect manual moves and bump mismatch counts for affected rules.

    For each live bookmark whose current folder differs from the stored
    last_seen_folder, any active tag rule that would have sorted it to the
    old folder receives a mismatch penalty.
    """
    updated = dict(mismatches)

    for bm in live_bookmarks:
        bid = str(bm.get("_id", ""))
        current_folder = bm.get("folder_path", "")
        prev = previous_metadata.get(bid, {})
        last_seen_folder = prev.get("last_seen_folder", "")

        if not bid or not current_folder or not last_seen_folder:
            continue
        if current_folder == last_seen_folder:
            continue

        tags = bm.get("tags", [])
        normalized = _normalized_tags(tags)
        for tag in normalized:
            target = rules.get(tag)
            target_paths = [target] if isinstance(target, str) else (target or [])
            if last_seen_folder in target_paths:
                updated[tag] = updated.get(tag, 0) + 1

    return updated


def _normalized_tags(tags: list[str]) -> list[str]:
    """Return tags with ai:wdtag- prefix stripped for rule matching."""
    normalized: list[str] = []
    for t in tags:
        if t.startswith("ai:wdtag-"):
            normalized.append(t[len("ai:wdtag-"):])
        elif not t.startswith(("ai:", "sorter-")):
            normalized.append(t)
    return normalized


def disable_overmatched_rules(
    rules: dict[str, RuleTarget],
    mismatches: dict[str, int],
    max_mismatches: int = 3,
) -> tuple[dict[str, RuleTarget], dict[str, int]]:
    """Disable rules whose mismatch count exceeds the threshold.

    Returns the pruned rules and the retained mismatch counts.
    """
    kept_rules: dict[str, RuleTarget] = {}
    kept_mismatches = {}
    for tag, folder in rules.items():
        count = mismatches.get(tag, 0)
        if count <= max_mismatches:
            kept_rules[tag] = folder
            kept_mismatches[tag] = count
    return kept_rules, kept_mismatches


def atomic_swap_new_db(new_path: str, current_path: str) -> None:
    """Atomically replace current_path with new_path.

    Uses an intermediate backup directory so the swap is reversible on failure.
    """
    old_path = f"{current_path}_old"

    if os.path.exists(old_path):
        shutil.rmtree(old_path)

    if os.path.exists(current_path):
        os.rename(current_path, old_path)

    os.rename(new_path, current_path)

    if os.path.exists(old_path):
        shutil.rmtree(old_path)


def embed_texts_in_chunks(
    embedder: Any,
    texts: list[str],
    chunk_size: int = EMBED_CHUNK_SIZE,
) -> np.ndarray:
    """Embed a large library in bounded chunks with measurable progress."""
    started = time.monotonic()
    chunks: list[np.ndarray] = []
    total = len(texts)

    for start in range(0, total, chunk_size):
        end = min(start + chunk_size, total)
        chunks.append(np.asarray(embedder.embed(texts[start:end])))
        elapsed = max(time.monotonic() - started, 0.001)
        rate = end / elapsed
        eta_seconds = (total - end) / rate if rate else 0.0
        print(
            "Re-index embedding progress: "
            f"{end}/{total} ({end / total:.1%}), "
            f"elapsed={elapsed:.1f}s, eta={eta_seconds:.1f}s",
            flush=True,
        )

    return np.concatenate(chunks, axis=0)


def rebuild_index(
    client: Any,
    embedder: Any,
    db_path: str = "chroma_db",
    new_db_path: str | None = None,
) -> dict[str, Any]:
    """Rebuild the ChromaDB index from the live Raindrop library.

    Steps:
        1. Crawl all collections and bookmarks.
        2. Load previous metadata for manual-move detection.
        3. Detect manual corrections and update rule mismatch counts.
        4. Extract candidate tag rules from current library state.
        5. Validate rules against live folders and disable overmatched rules.
        6. Build embeddings and write to a new ChromaDB directory.
        7. Recompute folder centroids recursively.
        8. Atomically swap the new DB into place.
        9. Persist centroids, rules, mismatches, and folder ID map.
    """
    from src.raindrop_client import RaindropClient

    if client is None:
        client = RaindropClient()

    if new_db_path is None:
        new_db_path = f"{db_path}_new"

    total_started = time.monotonic()
    timings: dict[str, float] = {}

    def record_phase(name: str, started: float) -> None:
        elapsed = round(time.monotonic() - started, 3)
        timings[name] = elapsed
        print(f"Re-index phase {name} completed in {elapsed:.3f}s", flush=True)

    # 1. Crawl
    phase_started = time.monotonic()
    collections = client.get_collections()
    groups = client.get_collection_groups()
    folder_map = build_folder_map(collections, groups)
    id_to_path_map = {cid: path for path, cid in folder_map.items()}
    id_to_path_map.setdefault(-1, "Unsorted")

    all_bookmarks = client.get_all_raindrops(0)
    for item in all_bookmarks:
        collection = item.get("collection") or {}
        cid = collection.get("$id", item.get("_collection_id"))
        item["folder_path"] = id_to_path_map.get(cid, str(cid))
        item["_collection_id"] = cid

    record_phase("crawl", phase_started)

    if not all_bookmarks:
        timings["total"] = round(time.monotonic() - total_started, 3)
        return {
            "status": "no_bookmarks",
            "processed": 0,
            "timings_seconds": timings,
            "raindrop_requests": int(getattr(client, "request_count", 0)),
            "rate_limit_wait_seconds": float(
                getattr(client, "rate_limit_wait_seconds", 0.0)
            ),
        }

    # 2. Load previous metadata
    phase_started = time.monotonic()
    previous_metadata = load_existing_metadata(db_path)

    # 3. Load previous rules and detect corrections
    existing_rules, mismatches = load_tag_rules(db_path)
    mismatches = detect_manual_corrections(
        all_bookmarks, previous_metadata, existing_rules, mismatches
    )

    # 4. Extract candidate rules from current library and merge with existing rules
    candidate_rules = extract_candidate_tag_rules(all_bookmarks)
    merged_rules = dict(existing_rules)
    for tag, folder in candidate_rules.items():
        merged_rules[tag] = folder

    # 5. Validate rules against live folders and apply mismatch penalties
    live_folders = set(folder_map.keys())
    validated_rules = validate_tag_rules(merged_rules, live_folders)
    final_rules, final_mismatches = disable_overmatched_rules(validated_rules, mismatches)

    record_phase("prepare", phase_started)

    # 6. Build embeddings and write to new ChromaDB
    phase_started = time.monotonic()
    texts = [build_text_input(bm) for bm in all_bookmarks]
    embeddings = embed_texts_in_chunks(embedder, texts)
    record_phase("embed", phase_started)

    phase_started = time.monotonic()
    if os.path.exists(new_db_path):
        shutil.rmtree(new_db_path)
    os.makedirs(new_db_path, exist_ok=True)

    chroma_client = chromadb.PersistentClient(path=new_db_path)
    collection = chroma_client.get_or_create_collection(name="bookmarks")

    ids = [str(bm["_id"]) for bm in all_bookmarks]
    metadatas = []
    for bm in all_bookmarks:
        meta = {
            "title": bm.get("title", ""),
            "folder_path": bm.get("folder_path", ""),
            "last_seen_folder": bm.get("folder_path", ""),
            "domain": bm.get("domain", ""),
            "tags": ",".join(bm.get("tags", [])),
        }
        metadatas.append(meta)

    batch_size = 100
    for i in range(0, len(ids), batch_size):
        end = i + batch_size
        collection.add(
            ids=ids[i:end],
            embeddings=embeddings[i:end].tolist(),
            metadatas=metadatas[i:end],
        )

    # 7. Compute centroids
    folders = [bm.get("folder_path", "") for bm in all_bookmarks]
    hierarchy = build_folder_hierarchy(collections, groups)
    centroids = compute_folder_centroids(embeddings, folders, hierarchy)
    save_centroids(centroids, new_db_path)

    # 8. Atomic swap
    atomic_swap_new_db(new_db_path, db_path)

    # 9. Persist rules, mismatches, and folder ID map
    save_tag_rules(final_rules, final_mismatches, db_path)
    save_series_rules(extract_series_rules(list(folder_map)), db_path)
    with open(os.path.join(db_path, "folder_id_map.json"), "w", encoding="utf-8") as f:
        json.dump(folder_map, f, indent=2)

    record_phase("index", phase_started)
    timings["total"] = round(time.monotonic() - total_started, 3)

    request_count = int(getattr(client, "request_count", 0))
    rate_limit_wait_seconds = float(getattr(client, "rate_limit_wait_seconds", 0.0))
    print(
        "Re-index complete: "
        f"{request_count} Raindrop requests, "
        f"{rate_limit_wait_seconds:.1f}s waiting for rate limits, "
        f"{timings['total']:.3f}s total",
        flush=True,
    )

    return {
        "status": "ok",
        "processed": len(all_bookmarks),
        "collections": len(collections),
        "rules": len(final_rules),
        "disabled_rules": len(merged_rules) - len(final_rules),
        "retried": 0,
        "timings_seconds": timings,
        "raindrop_requests": request_count,
        "rate_limit_wait_seconds": rate_limit_wait_seconds,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
