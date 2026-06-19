"""Modal app: Watcher (cron) + Resolver (on-demand) for text-only sorting."""

import json
import os
from datetime import datetime, timezone
from typing import Any

import modal

# ---------------------------------------------------------------------------
# Modal image definition
# ---------------------------------------------------------------------------
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_requirements("requirements.txt")
)

# ---------------------------------------------------------------------------
# Persistent volume for ChromaDB + centroids + rules
# ---------------------------------------------------------------------------
vol = modal.Volume.from_name("raindrop-sorter-vol", create_if_missing=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DB_PATH = "/data/chroma_db"
CRON_SCHEDULE = "*/30 * * * *"  # Every 30 minutes

# ---------------------------------------------------------------------------
# Modal App definition (must be before @app.function decorators)
# ---------------------------------------------------------------------------
app = modal.App("raindrop-sorter")

# ---------------------------------------------------------------------------
# Helper: load state from volume
# ---------------------------------------------------------------------------

def _load_state() -> tuple[dict[str, Any], dict[str, str], dict[str, int], dict[str, Any]]:
    """Load centroids, tag rules, mismatches, and folder ID map from the volume."""
    from src.centroids import load_centroids
    from src.tag_rules import load_tag_rules

    centroids = load_centroids(DB_PATH)
    rules, mismatches = load_tag_rules(DB_PATH)

    folder_id_map_path = os.path.join(DB_PATH, "folder_id_map.json")
    with open(folder_id_map_path, "r", encoding="utf-8") as f:
        folder_id_map = json.load(f)

    return centroids, rules, mismatches, folder_id_map


# ---------------------------------------------------------------------------
# Watcher — CPU, cron every 30 min
# ---------------------------------------------------------------------------
@app.function(
    image=image,
    schedule=modal.Cron(CRON_SCHEDULE),
    volumes={"/data": vol},
    secrets=[modal.Secret.from_name("raindrop-token")],
)
def watcher() -> dict[str, Any]:
    """Poll Raindrop Unsorted, tag items for Resolver processing."""
    from src.raindrop_client import RaindropClient
    from src.state_machine import (
        is_pending_resolution,
        is_reviewed,
        tag_pending_resolution,
    )

    client = RaindropClient()
    unsorted = client.get_unsorted_collection()
    if unsorted is None:
        return {"status": "no_unsorted_collection", "processed": 0}

    items = client.get_all_raindrops(-1)
    processed = 0
    skipped = 0

    for item in items:
        # Skip items already being processed or recently reviewed
        if is_pending_resolution(item) or is_reviewed(item):
            skipped += 1
            continue

        # In slice 1, there is no vision worker.
        # Text-only bookmarks go straight to pending resolution.
        new_tags = tag_pending_resolution(item)
        client.update_raindrop(item["_id"], tags=new_tags)
        processed += 1

    return {
        "status": "ok",
        "processed": processed,
        "skipped": skipped,
        "total": len(items),
    }


# ---------------------------------------------------------------------------
# Resolver — CPU, on-demand
# ---------------------------------------------------------------------------
@app.function(
    image=image,
    volumes={"/data": vol},
    secrets=[modal.Secret.from_name("raindrop-token")],
)
def resolver() -> dict[str, Any]:
    """Apply centroid matching and move confident bookmarks."""
    from src.embeddings import Embedder
    from src.raindrop_client import RaindropClient
    from src.resolver import resolve_bookmark
    from src.state_machine import is_pending_resolution

    # Load state from volume
    centroids, rules, _mismatches, folder_id_map = _load_state()

    if not centroids:
        return {"status": "no_state", "moved": 0, "rejected": 0}

    client = RaindropClient()
    embedder = Embedder()

    # Fetch Unsorted items that are tagged pending resolution
    items = client.get_all_raindrops(-1)
    to_resolve = [item for item in items if is_pending_resolution(item)]

    moved = 0
    rejected = 0
    errors = 0

    for item in to_resolve:
        # Inject folder ID map for safety check
        item["_folder_id_map"] = folder_id_map

        try:
            target_id, new_tags, reason = resolve_bookmark(
                item,
                centroids,
                rules,
                embedder=embedder,
            )
        except Exception as exc:
            # Log and continue — retry next cycle
            print(f"Error resolving {item['_id']}: {exc}")
            errors += 1
            continue

        try:
            if target_id is not None:
                client.update_raindrop(item["_id"], collection_id=target_id, tags=new_tags)
                moved += 1
            else:
                client.update_raindrop(item["_id"], tags=new_tags)
                rejected += 1
        except Exception as exc:
            print(f"Error updating {item['_id']}: {exc}")
            errors += 1

    return {
        "status": "ok",
        "moved": moved,
        "rejected": rejected,
        "errors": errors,
        "total": len(to_resolve),
    }
