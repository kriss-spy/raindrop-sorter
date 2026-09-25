"""Live image previews for bookmark journal entries."""

from __future__ import annotations

import io
import threading
from collections.abc import Callable

from PIL import Image

from src.raindrop_client import RaindropClient
from src.vision_worker import download_cover, resolve_cover_url


Preview = tuple[bytes, str]
PreviewLoader = Callable[[int], Preview | None]


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
