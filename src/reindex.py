"""Weekly re-index and passive learning loop."""

import json
import os
import shutil
from datetime import datetime, timezone
from typing import Any

import chromadb
import numpy as np

from src.centroids import compute_folder_centroids, save_centroids
from src.embeddings import build_text_input
from src.state_machine import strip_reviewed_tags
from src.tag_rules import (
    extract_candidate_tag_rules,
    load_tag_rules,
    save_tag_rules,
    validate_tag_rules,
)

NEW_DB_DIR = "chroma_db_new"
OLD_DB_DIR = "chroma_db_old"


def build_folder_map(collections: list[dict[str, Any]]) -> dict[str, int]:
    """Map folder path -> collection ID."""
    by_id: dict[int, dict[str, Any]] = {c["_id"]: c for c in collections}

    def path_for(cid: int) -> str:
        c = by_id[cid]
        name = c.get("title", "")
        parent = c.get("parent", {}).get("$id")
        if parent and parent in by_id:
            return f"{path_for(parent)}/{name}"
        return name

    return {path_for(c["_id"]): c["_id"] for c in collections}


def build_folder_hierarchy(collections: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Build parent -> [children] mapping using folder paths."""
    by_id = {c["_id"]: c for c in collections}
    folder_map = build_folder_map(collections)

    def path_for(cid: int) -> str:
        c = by_id[cid]
        name = c.get("title", "")
        parent = c.get("parent", {}).get("$id")
        if parent and parent in by_id:
            return f"{path_for(parent)}/{name}"
        return name

    hierarchy: dict[str, list[str]] = {}
    for c in collections:
        parent = c.get("parent", {}).get("$id")
        if parent and parent in by_id:
            parent_path = path_for(parent)
            child_path = path_for(c["_id"])
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
    rules: dict[str, str],
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
            if tag in rules and rules[tag] == last_seen_folder:
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
    rules: dict[str, str],
    mismatches: dict[str, int],
    max_mismatches: int = 3,
) -> tuple[dict[str, str], dict[str, int]]:
    """Disable rules whose mismatch count exceeds the threshold.

    Returns the pruned rules and the retained mismatch counts.
    """
    kept_rules = {}
    kept_mismatches = {}
    for tag, folder in rules.items():
        count = mismatches.get(tag, 0)
        if count <= max_mismatches:
            kept_rules[tag] = folder
            kept_mismatches[tag] = count
    return kept_rules, kept_mismatches


def strip_reviewed_tags_from_unsorted(
    client: Any,
    unsorted_items: list[dict[str, Any]],
) -> int:
    """Remove sorter-reviewed tags from Unsorted items so they are retried.

    Returns the number of bookmarks updated.
    """
    from src.raindrop_client import RaindropClient

    if client is None:
        client = RaindropClient()

    updated = 0
    for item in unsorted_items:
        tags = item.get("tags", [])
        cleaned = strip_reviewed_tags(tags)
        if cleaned != tags:
            try:
                client.update_raindrop(item["_id"], tags=cleaned)
                updated += 1
            except Exception as exc:
                print(f"Error stripping reviewed tags for {item['_id']}: {exc}")

    return updated


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
        6. Strip sorter-reviewed tags from Unsorted items.
        7. Build embeddings and write to a new ChromaDB directory.
        8. Recompute folder centroids recursively.
        9. Atomically swap the new DB into place.
        10. Persist centroids, rules, mismatches, and folder ID map.
    """
    from src.raindrop_client import RaindropClient

    if client is None:
        client = RaindropClient()

    if new_db_path is None:
        new_db_path = f"{db_path}_new"

    # 1. Crawl
    collections = client.get_collections()
    folder_map = build_folder_map(collections)
    id_to_path_map = {cid: path for path, cid in folder_map.items()}

    all_bookmarks: list[dict[str, Any]] = []
    for coll in collections:
        cid = coll["_id"]
        if cid == -99:
            continue
        path = id_to_path_map.get(cid, str(cid))
        items = client.get_all_raindrops(cid)
        for item in items:
            item["folder_path"] = path
            item["_collection_id"] = cid
        all_bookmarks.extend(items)

    if not all_bookmarks:
        return {"status": "no_bookmarks", "processed": 0}

    # 2. Load previous metadata
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

    # 6. Strip reviewed tags from Unsorted so they are retried
    unsorted_id = -1
    unsorted_items = [
        bm for bm in all_bookmarks if bm.get("_collection_id") == unsorted_id
    ]
    retried = strip_reviewed_tags_from_unsorted(client, unsorted_items)

    # 7. Build embeddings and write to new ChromaDB
    texts = [build_text_input(bm) for bm in all_bookmarks]
    embeddings = embedder.embed(texts)

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

    # 8. Compute centroids
    folders = [bm.get("folder_path", "") for bm in all_bookmarks]
    hierarchy = build_folder_hierarchy(collections)
    centroids = compute_folder_centroids(embeddings, folders, hierarchy)
    save_centroids(centroids, new_db_path)

    # 9. Atomic swap
    atomic_swap_new_db(new_db_path, db_path)

    # 10. Persist rules, mismatches, and folder ID map
    save_tag_rules(final_rules, final_mismatches, db_path)
    with open(os.path.join(db_path, "folder_id_map.json"), "w", encoding="utf-8") as f:
        json.dump(folder_map, f, indent=2)

    return {
        "status": "ok",
        "processed": len(all_bookmarks),
        "collections": len(collections),
        "rules": len(final_rules),
        "disabled_rules": len(merged_rules) - len(final_rules),
        "retried": retried,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
