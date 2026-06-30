"""Modal app: Watcher (cron) + Resolver (on-demand) + Vision Worker (GPU)."""

import json
import os
from datetime import datetime, timezone
from typing import Any

import modal

# ---------------------------------------------------------------------------
# Modal image definitions
# ---------------------------------------------------------------------------
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_requirements("requirements.txt")
)

vision_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_requirements("requirements.txt")
    .pip_install("onnxruntime-gpu", "Pillow", "huggingface_hub")
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
VISION_CRON_SCHEDULE = "*/15 * * * *"  # Every 15 minutes
REINDEX_CRON_SCHEDULE = "0 3 * * 0"  # Sunday 3 AM UTC

# ---------------------------------------------------------------------------
# Modal App definition (must be before @app.function decorators)
# ---------------------------------------------------------------------------
app = modal.App("raindrop-sorter")

# ---------------------------------------------------------------------------
# Helper: load state from volume
# ---------------------------------------------------------------------------

def _load_state() -> tuple[dict[str, Any], dict[str, str], dict[str, int], dict[str, Any], dict[str, str]]:
    """Load centroids, tag rules, mismatches, folder ID map, and series rules from the volume."""
    from src.centroids import load_centroids
    from src.tag_rules import load_series_rules, load_tag_rules

    centroids = load_centroids(DB_PATH)
    rules, mismatches = load_tag_rules(DB_PATH)
    series_rules = load_series_rules(DB_PATH)

    folder_id_map_path = os.path.join(DB_PATH, "folder_id_map.json")
    with open(folder_id_map_path, "r", encoding="utf-8") as f:
        folder_id_map = json.load(f)

    return centroids, rules, mismatches, folder_id_map, series_rules


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

        # All new items go to pending_resolution.
        # The Resolver will funnel low-confidence cover items to vision.
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
    """Apply centroid/tag matching and move confident bookmarks.

    Low-confidence items with a cover URL are sent to the Vision Worker
    instead of being reviewed.
    """
    from src.embeddings import Embedder
    from src.raindrop_client import RaindropClient
    from src.resolver import resolve_bookmark
    from src.state_machine import has_vision_tags, is_pending_resolution, tag_pending_vision

    # Load state from volume
    centroids, rules, _mismatches, folder_id_map, series_rules = _load_state()

    if not centroids:
        return {"status": "no_state", "moved": 0, "rejected": 0, "vision": 0}

    client = RaindropClient()
    embedder = Embedder()

    # Fetch Unsorted items that are tagged pending resolution
    items = client.get_all_raindrops(-1)
    to_resolve = [item for item in items if is_pending_resolution(item)]

    moved = 0
    rejected = 0
    vision = 0
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
                series_rules=series_rules,
            )
        except Exception as exc:
            # Log and continue — retry next cycle
            print(f"Error resolving {item['_id']}: {exc}")
            errors += 1
            continue

        # Funnel: low confidence + cover URL + no existing vision tags -> vision worker
        if target_id is None and reason.startswith("low_confidence"):
            if item.get("cover") and not has_vision_tags(item):
                try:
                    vision_tags = tag_pending_vision(item)
                    client.update_raindrop(item["_id"], tags=vision_tags)
                    vision_worker.spawn(item["_id"])  # type: ignore[attr-defined]
                    vision += 1
                except Exception as exc:
                    print(f"Error sending {item['_id']} to vision: {exc}")
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
        "vision": vision,
        "errors": errors,
        "total": len(to_resolve),
    }


# ---------------------------------------------------------------------------
# Re-index — CPU, weekly Sunday 3 AM
# ---------------------------------------------------------------------------
@app.function(
    image=image,
    schedule=modal.Cron(REINDEX_CRON_SCHEDULE),
    volumes={"/data": vol},
    secrets=[modal.Secret.from_name("raindrop-token")],
)
def reindex() -> dict[str, Any]:
    """Weekly re-index: rebuild ChromaDB, centroids, rules, and retry reviewed items."""
    from src.embeddings import Embedder
    from src.raindrop_client import RaindropClient
    from src.reindex import rebuild_index

    client = RaindropClient()
    embedder = Embedder()

    try:
        result = rebuild_index(client, embedder, db_path=DB_PATH)
    except Exception as exc:
        print(f"Re-index failed: {exc}")
        return {"status": "error", "error": str(exc)}

    return result


# ---------------------------------------------------------------------------
# Vision Worker — GPU, on-demand (spawned by Resolver)
# ---------------------------------------------------------------------------
@app.function(
    image=vision_image,
    gpu="T4",
    volumes={"/data": vol},
    secrets=[modal.Secret.from_name("raindrop-token")],
)
def vision_worker(bookmark_id: int) -> dict[str, Any]:
    """Download cover image, run WD14 Tagger, update bookmark tags.

    .. note::
        GPU cold-start is ~10 s while the T4 loads the WD14 ONNX weights.
        This is acceptable for the on-demand + cron hybrid model.
    """
    from src.raindrop_client import RaindropClient
    from src.state_machine import tag_after_vision
    from src.vision_worker import run_vision_on_bookmark

    client = RaindropClient()

    try:
        bookmark = client.get_raindrop(bookmark_id)
    except Exception as exc:
        return {"status": "fetch_error", "bookmark_id": bookmark_id, "error": str(exc)}

    if not bookmark.get("cover"):
        return {"status": "no_cover", "bookmark_id": bookmark_id}

    try:
        vision_tags = run_vision_on_bookmark(bookmark)
    except Exception as exc:
        return {"status": "vision_error", "bookmark_id": bookmark_id, "error": str(exc)}

    new_tags = tag_after_vision(bookmark)
    for vt in vision_tags:
        if vt not in new_tags:
            new_tags.append(vt)

    client.update_raindrop(bookmark_id, tags=new_tags)
    return {"status": "ok", "bookmark_id": bookmark_id, "tags_added": vision_tags}


# ---------------------------------------------------------------------------
# Vision Cron — GPU, every 15 min (safety net for missed items)
# ---------------------------------------------------------------------------
@app.function(
    image=vision_image,
    gpu="T4",
    schedule=modal.Cron(VISION_CRON_SCHEDULE),
    volumes={"/data": vol},
    secrets=[modal.Secret.from_name("raindrop-token")],
)
def vision_cron() -> dict[str, Any]:
    """Process any bookmarks still tagged as pending-vision."""
    from src.raindrop_client import RaindropClient
    from src.state_machine import is_pending_vision, tag_after_vision
    from src.vision_worker import run_vision_on_bookmark

    client = RaindropClient()
    items = client.get_all_raindrops(-1)
    to_process = [item for item in items if is_pending_vision(item)]

    processed = 0
    errors = 0

    for item in to_process:
        try:
            vision_tags = run_vision_on_bookmark(item)
            new_tags = tag_after_vision(item)
            for vt in vision_tags:
                if vt not in new_tags:
                    new_tags.append(vt)
            client.update_raindrop(item["_id"], tags=new_tags)
            processed += 1
        except Exception as exc:
            print(f"Error in vision cron for {item['_id']}: {exc}")
            errors += 1

    return {
        "status": "ok",
        "processed": processed,
        "errors": errors,
        "total": len(to_process),
    }
