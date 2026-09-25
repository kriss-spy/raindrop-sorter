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
