import threading
import time

from src.bookmark_preview import CachedPreviewLoader


def test_preview_cache_reuses_values_expires_and_evicts_oldest():
    now = [0.0]
    calls = []

    def load(bookmark_id):
        calls.append(bookmark_id)
        if bookmark_id == 2:
            return None
        return f"image-{bookmark_id}-{len(calls)}".encode(), "image/webp"

    cached = CachedPreviewLoader(
        load,
        max_entries=2,
        ttl_seconds=10,
        clock=lambda: now[0],
    )

    assert cached(1) == (b"image-1-1", "image/webp")
    assert cached(1) == (b"image-1-1", "image/webp")
    assert cached(2) is None
    assert cached(2) is None
    assert calls == [1, 2]

    cached(3)
    cached(1)
    assert calls == [1, 2, 3, 1]

    now[0] = 11
    cached(3)
    assert calls == [1, 2, 3, 1, 3]


def test_preview_cache_coalesces_concurrent_requests_for_same_bookmark():
    started = threading.Event()
    release = threading.Event()
    calls = []
    results = []

    def load(bookmark_id):
        calls.append(bookmark_id)
        started.set()
        release.wait(timeout=1)
        return b"image", "image/webp"

    cached = CachedPreviewLoader(load)
    threads = [threading.Thread(target=lambda: results.append(cached(1))) for _ in range(2)]
    for thread in threads:
        thread.start()
    assert started.wait(timeout=1)
    time.sleep(0.02)
    release.set()
    for thread in threads:
        thread.join(timeout=1)

    assert calls == [1]
    assert results == [(b"image", "image/webp"), (b"image", "image/webp")]
