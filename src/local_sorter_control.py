"""Thread-safe control surface for the local sorter dashboard."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any


BatchProcessor = Callable[[int], dict[str, Any]]


class LocalSorterController:
    """Run bounded sorter batches for one-shot drains or automatic polling."""

    def __init__(
        self,
        process_batch: BatchProcessor,
        *,
        batch_size: int = 25,
        poll_seconds: float = 15.0,
    ):
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self._process_batch = process_batch
        self._batch_size = batch_size
        self._poll_seconds = poll_seconds
        self._condition = threading.Condition()
        self._automatic = False
        self._paused = False
        self._drain_unsorted = False
        self._closed = False
        self._stop_requested = False
        self._processing = False
        self._state = "idle"
        self._processed = 0
        self._attempted = 0
        self._failed = 0
        self._last_count: int | None = None
        self._last_error: str | None = None
        self._updated_at = time.time()
        self._thread = threading.Thread(
            target=self._run,
            name="local-sorter-controller",
            daemon=True,
        )
        self._thread.start()

    def status(self) -> dict[str, Any]:
        with self._condition:
            return self._status_locked()

    def process_all(self) -> dict[str, Any]:
        with self._condition:
            if self._automatic:
                raise RuntimeError("the automatic sorter is running; pause it first")
            if self._processing or self._drain_unsorted:
                raise RuntimeError("the sorter is already processing")
            self._drain_unsorted = True
            self._stop_requested = False
            self._last_error = None
            self._state = "running"
            self._touch_locked()
            self._condition.notify_all()
            return self._status_locked()

    def start_automatic(self) -> dict[str, Any]:
        with self._condition:
            if self._processing or self._drain_unsorted:
                raise RuntimeError("the sorter is already processing")
            self._automatic = True
            self._paused = False
            self._stop_requested = False
            self._last_error = None
            self._state = "running"
            self._touch_locked()
            self._condition.notify_all()
            return self._status_locked()

    def pause_automatic(self) -> dict[str, Any]:
        with self._condition:
            self._automatic = False
            self._paused = True
            self._stop_requested = True
            if not self._processing and not self._drain_unsorted:
                self._state = "paused"
            self._touch_locked()
            self._condition.notify_all()
            return self._status_locked()

    def stop_processing_all(self) -> dict[str, Any]:
        """Stop a one-shot drain at the next cooperative batch boundary."""
        with self._condition:
            if not self._drain_unsorted:
                raise RuntimeError("process all is not running")
            self._drain_unsorted = False
            self._stop_requested = True
            self._state = "stopping" if self._processing else "idle"
            self._touch_locked()
            self._condition.notify_all()
            return self._status_locked()

    def stop_requested(self) -> bool:
        """Return whether an in-flight cooperative batch should stop early."""
        with self._condition:
            return self._stop_requested or self._closed

    def record_item(self, succeeded: bool) -> None:
        """Publish one completed item while an in-flight batch is still running."""
        with self._condition:
            self._attempted += 1
            if succeeded:
                self._processed += 1
            else:
                self._failed += 1
            self._touch_locked()

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._automatic = False
            self._drain_unsorted = False
            self._stop_requested = True
            self._state = "stopping"
            self._condition.notify_all()
        self._thread.join()

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(
                    lambda: self._closed
                    or self._drain_unsorted
                    or self._automatic
                )
                if self._closed:
                    return
                self._processing = True
                self._state = "running"
                self._touch_locked()

            try:
                result = self._process_batch(self._batch_size)
                count = int(result.get("count", 0))
                succeeded = int(result.get("succeeded", count))
                failed = int(result.get("failed", 0))
                if count < 0:
                    raise ValueError("batch count must not be negative")
            except Exception as error:
                with self._condition:
                    self._processing = False
                    self._drain_unsorted = False
                    self._automatic = False
                    self._state = "error"
                    self._last_error = f"{type(error).__name__}: {error}"
                    self._touch_locked()
                continue

            with self._condition:
                self._processing = False
                if not result.get("progress_reported"):
                    self._attempted += count
                    self._processed += succeeded
                    self._failed += failed
                self._last_count = count
                if self._closed:
                    self._state = "stopped"
                    self._touch_locked()
                    return
                if failed:
                    self._drain_unsorted = False
                    self._automatic = False
                    self._state = "error"
                    self._last_error = f"{failed} item(s) failed in the last batch"
                    self._touch_locked()
                    continue
                self._last_error = None
                if self._drain_unsorted and count == 0:
                    self._drain_unsorted = False
                if self._drain_unsorted:
                    self._state = "running"
                    self._touch_locked()
                    continue
                if not self._automatic:
                    self._stop_requested = False
                    self._state = "paused" if self._paused else "idle"
                    self._touch_locked()
                    continue
                if count >= self._batch_size:
                    # A full page means more work may already be waiting. Keep
                    # draining while the models are warm instead of adding the
                    # polling delay between backlog batches.
                    self._state = "running"
                    self._touch_locked()
                    continue
                self._state = "watching"
                self._touch_locked()
                self._condition.wait_for(
                    lambda: self._closed or not self._automatic or self._drain_unsorted,
                    timeout=self._poll_seconds,
                )

    def _status_locked(self) -> dict[str, Any]:
        return {
            "available": True,
            "state": self._state,
            "automatic": self._automatic,
            "processing_all": self._drain_unsorted,
            "processed": self._processed,
            "attempted": self._attempted,
            "failed": self._failed,
            "last_count": self._last_count,
            "last_error": self._last_error,
            "batch_size": self._batch_size,
            "updated_at": self._updated_at,
        }

    def _touch_locked(self) -> None:
        self._updated_at = time.time()
