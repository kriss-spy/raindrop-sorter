import threading
import time

import pytest

from src.local_sorter_control import LocalSorterController


def _wait_for(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached")


def test_process_all_runs_batches_until_unsorted_is_empty():
    remaining = iter([2, 1, 0])
    calls = []

    def process_batch(limit):
        calls.append(limit)
        return {"count": next(remaining)}

    controller = LocalSorterController(process_batch, batch_size=25, poll_seconds=0.01)
    try:
        controller.process_all()
        _wait_for(lambda: controller.status()["state"] == "idle")
        status = controller.status()
        assert calls == [25, 25, 25]
        assert status["processed"] == 3
        assert status["automatic"] is False
    finally:
        controller.close()


def test_process_all_can_be_stopped_after_the_inflight_batch():
    started = threading.Event()
    release = threading.Event()
    calls = []

    def process_batch(limit):
        calls.append(limit)
        started.set()
        release.wait(timeout=1)
        return {"count": limit}

    controller = LocalSorterController(process_batch, batch_size=25)
    try:
        controller.process_all()
        assert started.wait(timeout=1)
        status = controller.stop_processing_all()
        assert status["state"] == "stopping"
        assert status["processing_all"] is False
        release.set()
        _wait_for(lambda: controller.status()["state"] == "idle")
        assert calls == [25]
    finally:
        release.set()
        controller.close()


def test_process_all_and_automatic_modes_cannot_be_mixed():
    started = threading.Event()
    release = threading.Event()
    block_next = [False]

    def process_batch(_limit):
        if block_next[0]:
            started.set()
            release.wait(timeout=1)
        return {"count": 0}

    controller = LocalSorterController(process_batch, poll_seconds=60)
    try:
        controller.start_automatic()
        _wait_for(lambda: controller.status()["state"] == "watching")
        with pytest.raises(RuntimeError, match="automatic sorter is running"):
            controller.process_all()
        controller.pause_automatic()
        _wait_for(lambda: controller.status()["state"] == "paused")

        block_next[0] = True
        controller.process_all()
        assert started.wait(timeout=1)
        with pytest.raises(RuntimeError, match="already processing"):
            controller.start_automatic()
    finally:
        release.set()
        controller.close()


def test_automatic_sorter_can_be_started_and_paused():
    calls = []

    def process_batch(limit):
        calls.append(limit)
        return {"count": 0}

    controller = LocalSorterController(process_batch, batch_size=10, poll_seconds=0.01)
    try:
        controller.start_automatic()
        _wait_for(lambda: len(calls) >= 1)
        assert controller.status()["automatic"] is True
        controller.pause_automatic()
        _wait_for(lambda: controller.status()["state"] == "paused")
        paused_calls = len(calls)
        time.sleep(0.04)
        assert len(calls) == paused_calls
    finally:
        controller.close()


def test_automatic_sorter_drains_full_batches_before_polling():
    remaining = iter([25, 7])
    calls = []

    def process_batch(limit):
        calls.append(limit)
        return {"count": next(remaining)}

    controller = LocalSorterController(
        process_batch,
        batch_size=25,
        poll_seconds=60,
    )
    try:
        controller.start_automatic()
        _wait_for(lambda: len(calls) == 2)
        assert calls == [25, 25]
        assert controller.status()["state"] == "watching"
    finally:
        controller.close()


def test_pause_during_inflight_batch_finishes_as_paused():
    started = threading.Event()
    release = threading.Event()

    def process_batch(_limit):
        started.set()
        release.wait()
        return {"count": 1, "succeeded": 1, "failed": 0}

    controller = LocalSorterController(process_batch, poll_seconds=0.01)
    try:
        controller.start_automatic()
        assert started.wait(timeout=1)
        controller.pause_automatic()
        release.set()
        _wait_for(lambda: controller.status()["state"] == "paused")
    finally:
        release.set()
        controller.close()


def test_close_waits_for_inflight_applied_batch():
    started = threading.Event()
    release = threading.Event()

    def process_batch(_limit):
        started.set()
        release.wait()
        return {"count": 1}

    controller = LocalSorterController(process_batch, poll_seconds=0.01)
    controller.start_automatic()
    assert started.wait(timeout=1)
    closer = threading.Thread(target=controller.close)
    closer.start()
    time.sleep(0.02)
    assert closer.is_alive()
    release.set()
    closer.join(timeout=1)
    assert not closer.is_alive()
    assert controller.status()["state"] == "stopped"


def test_partial_batch_stops_automatic_mode_and_preserves_progress():
    controller = LocalSorterController(
        lambda _limit: {"count": 3, "succeeded": 2, "failed": 1},
        poll_seconds=0.01,
    )
    try:
        controller.start_automatic()
        _wait_for(lambda: controller.status()["state"] == "error")
        status = controller.status()
        assert status["automatic"] is False
        assert status["processed"] == 2
        assert status["last_count"] == 3
        assert "1 item(s) failed" in status["last_error"]
    finally:
        controller.close()
