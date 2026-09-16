"""Modal app: Watcher (cron) + Resolver (on-demand) + Vision Worker (GPU)."""

import json
import os
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Any

import modal

# ---------------------------------------------------------------------------
# Modal image definitions
# ---------------------------------------------------------------------------
base_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_requirements("requirements.txt")
)

image = base_image.add_local_python_source("src")

vision_image = (
    base_image
    .pip_install("onnxruntime-gpu", "Pillow", "huggingface_hub")
    .add_local_python_source("src")
)

# ---------------------------------------------------------------------------
# Persistent volume for ChromaDB + centroids + rules
# ---------------------------------------------------------------------------
vol = modal.Volume.from_name("raindrop-sorter-vol", create_if_missing=True)
coordination = modal.Dict.from_name("raindrop-sorter-coordination", create_if_missing=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DB_PATH = "/data/chroma_db"
CRON_SCHEDULE = "*/30 * * * *"  # Every 30 minutes
VISION_CRON_SCHEDULE = "7,22,37,52 * * * *"  # Every 15 minutes, offset from Watcher
REINDEX_CRON_SCHEDULE = "0 3 * * 0"  # Sunday 3 AM UTC
REINDEX_TIMEOUT_SECONDS = 2 * 60 * 60
REINDEX_LEASE_SECONDS = REINDEX_TIMEOUT_SECONDS + 5 * 60
API_CONSUMER_LEASE_SECONDS = 6 * 60
WATCHER_BATCH_SIZE = 25
RESOLVER_BATCH_SIZE = 25
VISION_BATCH_SIZE = 25
VISION_DISPATCH_LEASE_PREFIX = "vision_dispatch_lease:"
VISION_DISPATCH_LEASE_SECONDS = 30 * 60

# ---------------------------------------------------------------------------
# Modal App definition (must be before @app.function decorators)
# ---------------------------------------------------------------------------
app = modal.App("raindrop-sorter")


def pause_during_reindex(paused_result: Any):
    """Wrap a Modal entry point in an expiring API-consumer lease."""
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            from src.reindex_lease import api_consumer_lease

            with api_consumer_lease(
                coordination,
                API_CONSUMER_LEASE_SECONDS,
            ) as allowed:
                if not allowed:
                    if callable(paused_result):
                        return paused_result(*args, **kwargs)
                    return dict(paused_result)
                return function(*args, **kwargs)

        return wrapped

    return decorate

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
    max_containers=1,
    volumes={"/data": vol},
    secrets=[modal.Secret.from_name("raindrop-token")],
)
@pause_during_reindex({"status": "reindex_active", "processed": 0})
def watcher() -> dict[str, Any]:
    """Poll Raindrop Unsorted, tag items for Resolver processing."""
    from src.raindrop_client import RaindropClient
    from src.state_machine import (
        PENDING_RESOLUTION,
        PENDING_VISION_PREFIX,
        REVIEWED_PREFIX,
        is_pending_resolution,
        is_pending_vision,
        is_reviewed,
        tag_pending_resolution,
    )

    client = RaindropClient()
    state_tags = {
        tag["_id"]
        for tag in client.get_tags(-1)
        if tag.get("_id") == PENDING_RESOLUTION
        or str(tag.get("_id", "")).startswith(PENDING_VISION_PREFIX)
        or str(tag.get("_id", "")).startswith(REVIEWED_PREFIX)
    }
    unprocessed_search = " ".join(
        f'-#"{tag}"' for tag in sorted(state_tags)
    ) or None
    items, has_more = client.get_raindrops(
        -1,
        perpage=WATCHER_BATCH_SIZE,
        search=unprocessed_search,
    )
    processed = 0
    skipped = 0

    for item in items:
        # Skip items already being processed or recently reviewed
        if is_pending_resolution(item) or is_pending_vision(item) or is_reviewed(item):
            skipped += 1
            continue

        # All new items go to pending_resolution.
        # The Resolver will funnel low-confidence cover items to vision.
        new_tags = tag_pending_resolution(item)
        client.update_raindrop(item["_id"], tags=new_tags)
        processed += 1

    has_resolver_work = processed > 0
    if not has_resolver_work and PENDING_RESOLUTION in state_tags:
        vision_exclusions = " ".join(
            f'-#"{tag}"'
            for tag in sorted(state_tags)
            if tag.startswith(PENDING_VISION_PREFIX)
        )
        pending_search = f'#"{PENDING_RESOLUTION}"'
        if vision_exclusions:
            pending_search = f"{pending_search} {vision_exclusions}"
        pending_items, _ = client.get_raindrops(
            -1,
            perpage=1,
            search=pending_search,
        )
        has_resolver_work = any(
            is_pending_resolution(item) and not is_pending_vision(item)
            for item in pending_items
        )

    if has_resolver_work:
        resolver.spawn()  # type: ignore[attr-defined]

    return {
        "status": "ok",
        "processed": processed,
        "skipped": skipped,
        "total": len(items),
        "has_more": has_more,
    }


# ---------------------------------------------------------------------------
# Resolver — CPU, on-demand
# ---------------------------------------------------------------------------
@app.function(
    image=image,
    max_containers=1,
    volumes={"/data": vol},
    secrets=[modal.Secret.from_name("raindrop-token")],
)
@pause_during_reindex({"status": "reindex_active"})
def resolver() -> dict[str, Any]:
    """Apply centroid/tag matching and move confident bookmarks.

    Low-confidence items with a cover URL are sent to the Vision Worker
    instead of being reviewed.
    """
    from src.embeddings import Embedder
    from src.raindrop_client import RaindropClient
    from src.resolver import resolve_bookmark
    from src.state_machine import (
        PENDING_RESOLUTION,
        has_vision_tags,
        is_pending_resolution,
        tag_pending_vision,
    )

    client = RaindropClient()
    # Ask Raindrop for one exact state-tag batch instead of crawling all of
    # Unsorted. This keeps each invocation comfortably within the shared API
    # budget even when thousands of bookmarks are waiting.
    to_resolve, has_more = client.get_raindrops(
        -1,
        perpage=RESOLVER_BATCH_SIZE,
        search=f"#{PENDING_RESOLUTION}",
    )
    to_resolve = [item for item in to_resolve if is_pending_resolution(item)]
    if not to_resolve:
        return {
            "status": "ok",
            "moved": 0,
            "rejected": 0,
            "vision": 0,
            "errors": 0,
            "total": 0,
            "has_more": False,
        }

    # Load the model only after confirming that this invocation has work.
    centroids, rules, _mismatches, folder_id_map, series_rules = _load_state()
    if not centroids:
        return {"status": "no_state", "moved": 0, "rejected": 0, "vision": 0}
    embedder = Embedder()

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

    made_progress = moved + rejected + vision
    if has_more and made_progress:
        resolver.spawn()  # type: ignore[attr-defined]

    return {
        "status": "ok",
        "moved": moved,
        "rejected": rejected,
        "vision": vision,
        "errors": errors,
        "total": len(to_resolve),
        "has_more": has_more,
    }


# ---------------------------------------------------------------------------
# Re-index — CPU, weekly Sunday 3 AM
# ---------------------------------------------------------------------------
@app.function(
    image=image,
    schedule=modal.Cron(REINDEX_CRON_SCHEDULE),
    timeout=REINDEX_TIMEOUT_SECONDS,
    max_containers=1,
    single_use_containers=True,
    volumes={"/data": vol},
    secrets=[modal.Secret.from_name("raindrop-token")],
)
def reindex_worker() -> dict[str, Any]:
    """Weekly re-index: rebuild ChromaDB, centroids, rules, and retry reviewed items."""
    from src.embeddings import Embedder
    from src.raindrop_client import RaindropClient
    from src.reindex import rebuild_index
    from src.reindex_lease import (
        acquire_reindex_lease,
        release_reindex_lease,
        wait_for_api_consumers,
    )

    lease_owner = acquire_reindex_lease(coordination, REINDEX_LEASE_SECONDS)
    run_started = time.monotonic()
    model_init_seconds = 0.0
    model_started = None
    client = None
    try:
        wait_for_api_consumers(coordination)
        client = RaindropClient()
        model_started = time.monotonic()
        embedder = Embedder()
        model_init_seconds = round(time.monotonic() - model_started, 3)
        print(
            f"Re-index phase model_init completed in {model_init_seconds:.3f}s",
            flush=True,
        )
        result = rebuild_index(client, embedder, db_path=DB_PATH)
    except Exception as exc:
        if model_started is not None and model_init_seconds == 0.0:
            model_init_seconds = round(time.monotonic() - model_started, 3)
        print(f"Re-index failed: {exc}")
        result = {"status": "error", "error": str(exc)}
    finally:
        release_reindex_lease(coordination, lease_owner)

    timings = result.setdefault("timings_seconds", {})
    timings["model_init"] = model_init_seconds
    timings["total"] = round(time.monotonic() - run_started, 3)
    result.setdefault("raindrop_requests", int(getattr(client, "request_count", 0)))
    result.setdefault(
        "rate_limit_wait_seconds",
        float(getattr(client, "rate_limit_wait_seconds", 0.0)),
    )
    print(
        "Re-index invocation finished: "
        f"status={result['status']}, total={timings['total']:.3f}s",
        flush=True,
    )
    return result


@app.local_entrypoint()
def reindex() -> None:
    """Run the deployed singleton reindex worker in the selected environment."""
    deployed_reindex = modal.Function.from_name(
        "raindrop-sorter",
        "reindex_worker",
    )
    print(deployed_reindex.remote())


# ---------------------------------------------------------------------------
# Vision Worker — GPU, on-demand (dispatched by Vision Cron)
# ---------------------------------------------------------------------------
@app.function(
    image=vision_image,
    gpu="T4",
    max_containers=1,
    volumes={"/data": vol},
    secrets=[modal.Secret.from_name("raindrop-token")],
)
@pause_during_reindex(
    lambda bookmark_id, lease_owner=None: {
        "status": "reindex_active",
        "bookmark_id": bookmark_id,
    }
)
def vision_worker(bookmark_id: int, lease_owner: str | None = None) -> dict[str, Any]:
    """Download cover image, run WD14 Tagger, update bookmark tags.

    .. note::
        GPU cold-start is ~10 s while the T4 loads the WD14 ONNX weights.
        This is acceptable for the on-demand + cron hybrid model.
    """
    from src.raindrop_client import RaindropClient
    from src.reindex_lease import release_item_lease
    from src.state_machine import is_pending_vision, tag_after_vision
    from src.vision_worker import run_vision_on_bookmark

    try:
        client = RaindropClient()
        try:
            bookmark = client.get_raindrop(bookmark_id)
        except Exception as exc:
            return {"status": "fetch_error", "bookmark_id": bookmark_id, "error": str(exc)}

        if not is_pending_vision(bookmark):
            return {"status": "not_pending", "bookmark_id": bookmark_id}

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
    finally:
        if lease_owner is not None:
            release_item_lease(
                coordination,
                VISION_DISPATCH_LEASE_PREFIX,
                bookmark_id,
                lease_owner,
            )


# ---------------------------------------------------------------------------
# Vision Cron — CPU, every 15 min (safety net for missed items)
# ---------------------------------------------------------------------------
@app.function(
    image=image,
    schedule=modal.Cron(VISION_CRON_SCHEDULE),
    max_containers=1,
    secrets=[modal.Secret.from_name("raindrop-token")],
)
@pause_during_reindex({"status": "reindex_active", "dispatched": 0})
def vision_cron() -> dict[str, Any]:
    """Dispatch bookmarks still tagged as pending-vision to GPU workers."""
    from src.raindrop_client import RaindropClient
    from src.reindex_lease import acquire_item_lease, release_item_lease
    from src.state_machine import PENDING_VISION_PREFIX, is_pending_vision

    client = RaindropClient()
    pending_tags = sorted(
        str(tag["_id"])
        for tag in client.get_tags(-1)
        if str(tag.get("_id", "")).startswith(PENDING_VISION_PREFIX)
    )
    to_process: list[dict[str, Any]] = []
    has_more = False
    for tag_index, tag in enumerate(pending_tags):
        remaining = VISION_BATCH_SIZE - len(to_process)
        if remaining == 0:
            has_more = True
            break
        items, tag_has_more = client.get_raindrops(
            -1,
            perpage=remaining,
            search=f'#"{tag}"',
        )
        to_process.extend(item for item in items if is_pending_vision(item))
        has_more = (
            has_more
            or tag_has_more
            or tag_index < len(pending_tags) - 1
        )
        if len(to_process) >= VISION_BATCH_SIZE:
            break

    dispatched = 0
    skipped_inflight = 0
    for item in to_process:
        bookmark_id = item["_id"]
        lease_owner = acquire_item_lease(
            coordination,
            VISION_DISPATCH_LEASE_PREFIX,
            bookmark_id,
            VISION_DISPATCH_LEASE_SECONDS,
        )
        if lease_owner is None:
            skipped_inflight += 1
            continue
        try:
            vision_worker.spawn(bookmark_id, lease_owner)  # type: ignore[attr-defined]
            dispatched += 1
        except Exception:
            release_item_lease(
                coordination,
                VISION_DISPATCH_LEASE_PREFIX,
                bookmark_id,
                lease_owner,
            )
            raise

    # One coalesced kick handles vision results from the previous cycle and
    # avoids every GPU worker enqueueing its own model-backed resolver call.
    resolver.spawn()  # type: ignore[attr-defined]

    return {
        "status": "ok",
        "dispatched": dispatched,
        "skipped_inflight": skipped_inflight,
        "total": len(to_process),
        "has_more": has_more,
    }
