"""Cross-container leases that reserve the shared Raindrop API budget."""

import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

LEGACY_REINDEX_LEASE_KEY = "reindex_lease_expires_at"
REINDEX_LEASE_KEY = "reindex_lease"
REINDEX_LEASE_PREFIX = "reindex_lease:"
API_CONSUMER_LEASE_PREFIX = "api_consumer_lease:"


def _lease_is_active(lease: Any, now: float) -> bool:
    expires_at = lease.get("expires_at") if isinstance(lease, dict) else lease
    try:
        return float(expires_at) > now
    except (TypeError, ValueError):
        return False


def _active_leases(store: Any, prefix: str) -> list[dict[str, Any]]:
    now = time.time()
    active: list[dict[str, Any]] = []
    for key in store.keys():
        if not isinstance(key, str) or not key.startswith(prefix):
            continue
        lease = store.get(key)
        if isinstance(lease, dict) and _lease_is_active(lease, now):
            active.append(lease)
    return active


def is_reindex_active(store: Any) -> bool:
    """Return whether any non-expired reindex lease exists."""
    now = time.time()
    if _lease_is_active(store.get(REINDEX_LEASE_KEY), now):
        return True
    if _lease_is_active(store.get(LEGACY_REINDEX_LEASE_KEY), now):
        return True
    return bool(_active_leases(store, REINDEX_LEASE_PREFIX))


def acquire_reindex_lease(store: Any, duration_seconds: float) -> str:
    """Publish an expiring pause signal for the serialized reindex worker."""
    owner = uuid.uuid4().hex
    started_at = time.time()
    store.put(
        REINDEX_LEASE_KEY,
        {
            "owner": owner,
            "started_at": started_at,
            "expires_at": started_at + duration_seconds,
        },
    )
    return owner


def release_reindex_lease(store: Any, owner: str) -> None:
    """Release the pause signal only when it still belongs to this caller."""
    lease = store.get(REINDEX_LEASE_KEY)
    if isinstance(lease, dict) and lease.get("owner") == owner:
        store.pop(REINDEX_LEASE_KEY, None)


@contextmanager
def api_consumer_lease(
    store: Any,
    duration_seconds: float,
) -> Iterator[bool]:
    """Register API activity unless a reindex already owns the budget."""
    if is_reindex_active(store):
        yield False
        return

    owner = uuid.uuid4().hex
    key = f"{API_CONSUMER_LEASE_PREFIX}{owner}"
    store.put(
        key,
        {"owner": owner, "expires_at": time.time() + duration_seconds},
    )
    try:
        # Close the race where reindex starts between our first check and put.
        if is_reindex_active(store):
            yield False
        else:
            yield True
    finally:
        store.pop(key, None)


def wait_for_api_consumers(store: Any, poll_seconds: float = 1.0) -> None:
    """Wait until API consumers that started before reindex have drained."""
    while _active_leases(store, API_CONSUMER_LEASE_PREFIX):
        print("Waiting for active Raindrop API consumers to finish", flush=True)
        time.sleep(poll_seconds)
