"""Live image previews for bookmark journal entries."""

from __future__ import annotations

import io
import threading
import time
from collections import OrderedDict
from collections.abc import Callable

from PIL import Image

from src.raindrop_client import RaindropClient
from src.vision_worker import download_cover, resolve_cover_url


Preview = tuple[bytes, str]
PreviewLoader = Callable[[int], Preview | None]


class CachedPreviewLoader:
    """Keep a bounded, short-lived cache of dashboard preview bytes in memory."""

    def __init__(
        self,
        loader: PreviewLoader,
        *,
        max_entries: int = 64,
        ttl_seconds: float = 300,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._loader = loader
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._cache: OrderedDict[int, tuple[float, Preview | None]] = OrderedDict()
        self._lock = threading.Lock()

    def __call__(self, bookmark_id: int) -> Preview | None:
        now = self._clock()
        with self._lock:
            cached = self._cache.get(bookmark_id)
            if cached is not None and now - cached[0] < self._ttl_seconds:
                self._cache.move_to_end(bookmark_id)
                return cached[1]
            self._cache.pop(bookmark_id, None)

        preview = self._loader(bookmark_id)
        with self._lock:
            self._cache[bookmark_id] = (now, preview)
            self._cache.move_to_end(bookmark_id)
            while len(self._cache) > self._max_entries:
                self._cache.popitem(last=False)
        return preview


class BookmarkPreviewService:
    """Resolve the current Raindrop cover without persisting its URL or bytes."""

    def __init__(self, token: str):
        self._client = RaindropClient(token=token)
        self._client_lock = threading.Lock()

    def __call__(self, bookmark_id: int) -> Preview | None:
        with self._client_lock:
            bookmark = self._client.get_raindrop(bookmark_id)
            cover_url = resolve_cover_url(bookmark)
            image = download_cover(cover_url) if cover_url else None
        if not image:
            return None
        return image, _image_content_type(image)


def _image_content_type(image: bytes) -> str:
    try:
        image_format = Image.open(io.BytesIO(image)).format
    except (OSError, ValueError):
        return "application/octet-stream"
    return Image.MIME.get(image_format or "", "application/octet-stream")
