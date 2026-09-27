"""Local HTTP server for journal inspection and explicit human review actions."""

from __future__ import annotations

import argparse
import json
import os
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

from src.bookmark_preview import CachedPreviewLoader, BookmarkPreviewService, PreviewLoader
from src.cover_cache import SQLiteCoverCache
from src.journal_dashboard import DASHBOARD_HTML
from src.journal_review import (
    IneligibleReviewAttempt,
    InvalidReviewDestination,
    JournalReviewService,
    ReviewApplyFailed,
    ReviewAttemptNotFound,
    StaleReviewAttempt,
)
from src.local_runner import LocalBatchProcessor, validate_local_index
from src.local_sorter_control import LocalSorterController
from src.live_library import LiveLibraryBrowser
from src.raindrop_client import RaindropClient
from src.run_journal import SQLiteRunJournal


class JournalHTTPServer(ThreadingHTTPServer):
    journal: SQLiteRunJournal
    preview_loader: PreviewLoader | None
    reviewer: JournalReviewService | None
    sorter_controller: Any | None
    sorter_unavailable_reason: str
    live_library: LiveLibraryBrowser | None
    cover_cache: SQLiteCoverCache | None

    def server_close(self) -> None:
        if self.sorter_controller is not None:
            self.sorter_controller.close()
        super().server_close()


def create_server(
    journal_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    preview_loader: PreviewLoader | None = None,
    cover_cache: SQLiteCoverCache | None = None,
    raindrop_client: Any | None = None,
    sorter_controller: Any | None = None,
    sorter_unavailable_reason: str | None = None,
    mutation_lock: threading.RLock | None = None,
    on_reviews_changed: Callable[[], dict[str, Any]] | None = None,
) -> JournalHTTPServer:
    journal_path = Path(journal_path)
    if not journal_path.is_file():
        raise FileNotFoundError(f"journal does not exist: {journal_path}")
    if (
        preview_loader is not None
        or raindrop_client is not None
        or sorter_controller is not None
    ) and host not in {
        "127.0.0.1", "localhost", "::1"
    }:
        raise ValueError(
            "live library access, image previews, review actions, and sorter controls "
            "require a loopback host"
        )
    server = JournalHTTPServer((host, port), JournalRequestHandler)
    server.journal = SQLiteRunJournal(
        journal_path,
        read_only=raindrop_client is None,
    )
    server.preview_loader = (
        CachedPreviewLoader(preview_loader) if preview_loader is not None else None
    )
    server.cover_cache = cover_cache
    server.reviewer = (
        JournalReviewService(
            server.journal,
            raindrop_client,
            mutation_lock=mutation_lock,
            cover_cache=cover_cache,
            on_reviews_changed=on_reviews_changed,
        )
        if raindrop_client is not None
        else None
    )
    server.sorter_controller = sorter_controller
    server.live_library = (
        LiveLibraryBrowser(raindrop_client) if raindrop_client is not None else None
    )
    server.sorter_unavailable_reason = sorter_unavailable_reason or (
        "RAINDROP_TOKEN is required for sorter controls"
    )
    return server


class JournalRequestHandler(BaseHTTPRequestHandler):
    server: JournalHTTPServer

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        request = urlparse(self.path)
        try:
            if request.path == "/":
                self._send(HTTPStatus.OK, DASHBOARD_HTML, "text/html; charset=utf-8")
            elif request.path == "/api/overview":
                self._overview(parse_qs(request.query))
            elif request.path == "/api/health":
                self._health()
            elif request.path == "/api/ready":
                self._readiness()
            elif request.path == "/api/attempts":
                self._attempts(parse_qs(request.query))
            elif request.path == "/api/review/collections":
                self._review_collections()
            elif request.path == "/api/library/tree":
                self._library_tree()
            elif request.path == "/api/library/bookmarks":
                self._library_bookmarks(parse_qs(request.query))
            elif request.path == "/api/sorter/status":
                self._sorter_status()
            elif request.path.startswith("/api/bookmarks/") and request.path.endswith("/preview"):
                self._preview(request.path)
            elif request.path.startswith("/api/attempts/"):
                attempt_id = request.path.removeprefix("/api/attempts/")
                trace = self.server.journal.explain_attempt(attempt_id)
                if trace is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "attempt not found"})
                else:
                    if self.server.cover_cache is not None:
                        trace["attempt"]["cover"] = self.server.cover_cache.get(
                            int(trace["attempt"]["bookmark_id"])
                        )
                    self._send_json(HTTPStatus.OK, trace)
            else:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except (KeyError, TypeError, ValueError) as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    def _library_tree(self) -> None:
        live_library = self._live_library_or_unavailable()
        if live_library is None:
            return
        try:
            tree = live_library.collection_tree()
        except Exception as error:
            self._send_library_upstream_error("load live collection tree", error)
            return
        self._send_json(HTTPStatus.OK, tree)

    def _library_bookmarks(self, query: dict[str, list[str]]) -> None:
        live_library = self._live_library_or_unavailable()
        if live_library is None:
            return
        collection_id = int(query["collection_id"][0])
        page = int(query.get("page", ["0"])[0])
        per_page = int(query.get("per_page", ["50"])[0])
        try:
            result = live_library.browse_collection(
                collection_id,
                page=page,
                per_page=per_page,
                search=query.get("q", [None])[0],
                sort=query.get("sort", [None])[0],
            )
        except (TypeError, ValueError):
            raise
        except Exception as error:
            self._send_library_upstream_error("browse live collection", error)
            return
        self._send_json(HTTPStatus.OK, result)

    def _send_library_upstream_error(self, action: str, error: Exception) -> None:
        response = getattr(error, "response", None)
        if getattr(response, "status_code", None) == HTTPStatus.TOO_MANY_REQUESTS:
            self._send_json(
                HTTPStatus.TOO_MANY_REQUESTS,
                {
                    "error": (
                        "Raindrop is rate-limiting requests. "
                        "Wait about a minute, then retry."
                    )
                },
            )
            return
        self._send_json(
            HTTPStatus.BAD_GATEWAY,
            {"error": f"could not {action}: {type(error).__name__}"},
        )

    def _live_library_or_unavailable(self) -> LiveLibraryBrowser | None:
        live_library = self.server.live_library
        if live_library is None:
            self._send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "live library browsing requires RAINDROP_TOKEN"},
            )
        return live_library

    def _review_collections(self) -> None:
        if self.server.reviewer is None:
            self._send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "review actions require RAINDROP_TOKEN"},
            )
            return
        try:
            items = self.server.reviewer.art_collections()
        except Exception as error:
            self._send_json(
                HTTPStatus.BAD_GATEWAY,
                {"error": f"could not load Art collections: {type(error).__name__}"},
            )
            return
        self._send_json(HTTPStatus.OK, {"items": items})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        request = urlparse(self.path)
        try:
            self._assert_same_origin()
            if request.path == "/api/attempts/resolve-batch":
                self._resolve_batch(self._read_json())
            elif request.path.startswith("/api/sorter/"):
                self._sorter_action(request.path)
            else:
                prefix = "/api/attempts/"
                suffix = "/resolve"
                if not request.path.startswith(prefix) or not request.path.endswith(suffix):
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                    return
                attempt_id = request.path[len(prefix):-len(suffix)]
                if not attempt_id:
                    raise ValueError("attempt ID is required")
                if self.server.reviewer is None:
                    self._send_json(
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        {"error": "review actions require RAINDROP_TOKEN"},
                    )
                    return
                payload = self._read_json()
                result = self.server.reviewer.resolve(
                    attempt_id,
                    collection_id=int(payload["collection_id"]),
                    selection_source=str(payload.get("selection_source", "custom")),
                )
                if self.server.live_library is not None:
                    self.server.live_library.invalidate_membership_cache()
                self._send_json(HTTPStatus.OK, result)
        except ReviewApplyFailed as error:
            self._send_json(
                HTTPStatus.BAD_GATEWAY,
                {
                    "error": f"Raindrop update failed: {error.error_type}",
                    "retry_attempt_id": error.retry_attempt["attempt_id"],
                    "retry_attempt": error.retry_attempt,
                    "retry_trace": error.retry_trace,
                },
            )
        except ReviewAttemptNotFound as error:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": str(error)})
        except (StaleReviewAttempt, IneligibleReviewAttempt) as error:
            self._send_json(HTTPStatus.CONFLICT, {"error": str(error)})
        except (InvalidReviewDestination, KeyError, TypeError, ValueError) as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except Exception as error:
            self._send_json(
                HTTPStatus.BAD_GATEWAY,
                {"error": f"Raindrop update failed: {type(error).__name__}"},
            )

    def _resolve_batch(self, payload: dict[str, Any]) -> None:
        if self.server.reviewer is None:
            self._send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "review actions require RAINDROP_TOKEN"},
            )
            return
        attempt_ids = payload.get("attempt_ids")
        if not isinstance(attempt_ids, list) or not attempt_ids:
            raise ValueError("attempt_ids must be a non-empty list")
        if len(attempt_ids) > 100:
            raise ValueError("a batch can contain at most 100 attempts")
        if len(set(attempt_ids)) != len(attempt_ids) or not all(
            isinstance(attempt_id, str) and attempt_id for attempt_id in attempt_ids
        ):
            raise ValueError("attempt_ids must contain unique non-empty strings")
        collection_id = int(payload["collection_id"])
        result = self.server.reviewer.resolve_batch(
            attempt_ids,
            collection_id=collection_id,
        )
        if self.server.live_library is not None:
            self.server.live_library.invalidate_membership_cache()
        self._send_json(HTTPStatus.OK, result)

    def _sorter_status(self) -> None:
        self._send_json(HTTPStatus.OK, self._sorter_status_payload())

    def _sorter_status_payload(self) -> dict[str, Any]:
        controller = self.server.sorter_controller
        if controller is None:
            return {
                "available": False,
                "state": "unavailable",
                "automatic": False,
                "error": self.server.sorter_unavailable_reason,
            }
        return controller.status()

    def _health(self) -> None:
        self._send_json(HTTPStatus.OK, {
            "status": "ok",
            "journal": True,
            "image_previews": self.server.preview_loader is not None,
            "review_actions": self.server.reviewer is not None,
            "sorter": self._sorter_status_payload(),
        })

    def _readiness(self) -> None:
        sorter = self._sorter_status_payload()
        ready = bool(sorter.get("available")) and sorter.get("state") not in {
            "error", "stopped", "stopping"
        }
        self._send_json(
            HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE,
            {"status": "ready" if ready else "not_ready", "sorter": sorter},
        )

    def _sorter_action(self, path: str) -> None:
        controller = self.server.sorter_controller
        if controller is None:
            self._send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": self.server.sorter_unavailable_reason},
            )
            return
        actions = {
            "/api/sorter/process-all": controller.process_all,
            "/api/sorter/stop": controller.stop_processing_all,
            "/api/sorter/start": controller.start_automatic,
            "/api/sorter/pause": controller.pause_automatic,
        }
        action = actions.get(path)
        if action is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        self._read_json()
        try:
            result = action()
        except RuntimeError as error:
            self._send_json(HTTPStatus.CONFLICT, {"error": str(error)})
            return
        self._send_json(HTTPStatus.ACCEPTED, result)

    def _read_json(self) -> dict[str, Any]:
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            raise ValueError("Content-Type must be application/json")
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > 10_000:
            raise ValueError("request body must be between 1 and 10000 bytes")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _assert_same_origin(self) -> None:
        origin = self.headers.get("Origin")
        if origin is not None and origin != f"http://{self.headers.get('Host')}":
            raise ValueError("cross-origin review actions are not allowed")

    def _current_location_bookmark_ids(
        self, query: dict[str, list[str]]
    ) -> tuple[bool, set[int] | None]:
        if "collection_id" not in query:
            return False, None
        live_library = self._live_library_or_unavailable()
        if live_library is None:
            return True, None
        try:
            return True, live_library.current_bookmark_ids(
                int(query["collection_id"][0])
            )
        except (TypeError, ValueError):
            raise
        except Exception as error:
            self._send_library_upstream_error(
                "load current collection membership", error
            )
            return True, None

    def _overview(self, query: dict[str, list[str]]) -> None:
        location_filtered, bookmark_ids = self._current_location_bookmark_ids(query)
        if location_filtered and bookmark_ids is None:
            return
        self._send_json(
            HTTPStatus.OK,
            self.server.journal.overview(bookmark_ids=bookmark_ids),
        )

    def _attempts(self, query: dict[str, list[str]]) -> None:
        limit = int(query.get("limit", ["50"])[0])
        if limit > 500:
            raise ValueError("limit must not exceed 500")
        latest = query.get("latest", ["0"])[0].casefold()
        if latest not in {"0", "1", "false", "true"}:
            raise ValueError("latest must be 0, 1, false, or true")
        location_filtered, bookmark_ids = self._current_location_bookmark_ids(query)
        if location_filtered and bookmark_ids is None:
            return
        items = self.server.journal.recent(
            limit=limit,
            outcome=query.get("outcome", [None])[0] or None,
            phase=query.get("phase", [None])[0] or None,
            query=query.get("q", [None])[0] or None,
            labels=tuple(query.get("label", [])),
            title=query.get("title", [None])[0] or None,
            link=query.get("link", [None])[0] or None,
            processed_on=query.get("processed_on", [None])[0] or None,
            utc_offset_minutes=int(query.get("utc_offset_minutes", ["0"])[0]),
            bookmark_ids=bookmark_ids,
            latest_per_bookmark=latest in {"1", "true"},
            status_mode=query.get("mode", [None])[0] or None,
        )
        if self.server.cover_cache is not None:
            items = self.server.cover_cache.attach(items)
        self._send_json(HTTPStatus.OK, {"items": items, "count": len(items)})

    def _preview(self, path: str) -> None:
        bookmark_id = int(path.removeprefix("/api/bookmarks/").removesuffix("/preview"))
        if not self.server.journal.has_bookmark(bookmark_id):
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "bookmark not in journal"})
            return
        if self.server.preview_loader is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "image preview unavailable"})
            return
        try:
            preview = self.server.preview_loader(bookmark_id)
        except Exception as error:
            self._send_json(
                HTTPStatus.BAD_GATEWAY,
                {"error": f"could not load image preview: {type(error).__name__}"},
            )
            return
        if preview is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "bookmark has no image preview"})
            return
        image, content_type = preview
        self._send(
            HTTPStatus.OK,
            image,
            content_type,
            cache_control="private, max-age=300",
        )

    def _send_json(self, status: HTTPStatus, payload: object) -> None:
        self._send(
            status,
            json.dumps(payload, ensure_ascii=False).encode(),
            "application/json; charset=utf-8",
        )

    def _send(
        self,
        status: HTTPStatus,
        body: str | bytes,
        content_type: str,
        *,
        cache_control: str = "no-store",
    ) -> None:
        encoded = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' blob: https:; style-src 'unsafe-inline'; "
            "script-src 'unsafe-inline'; connect-src 'self'",
        )
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            # Browsers routinely cancel lazy image requests while changing views.
            return

    def log_message(self, format: str, *args: object) -> None:
        return


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Browse the local sorter run journal")
    parser.add_argument("--db-path", default="chroma_db")
    parser.add_argument(
        "--journal-path",
        help="SQLite journal path (default: <db-path>/run-journal.sqlite)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--model-dir", default=".cache/wd14")
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--poll-seconds", type=float, default=15.0)
    parser.add_argument(
        "--auto-start",
        action="store_true",
        help="Start the applied automatic sorter after the dashboard is ready",
    )
    parser.add_argument("--open", action="store_true", help="Open the dashboard in a browser")
    args = parser.parse_args(argv)
    load_dotenv()
    path = args.journal_path or os.path.join(args.db_path, "run-journal.sqlite")
    cover_cache = SQLiteCoverCache(Path(args.db_path) / "cover-cache.sqlite")
    token = os.environ.get("RAINDROP_TOKEN")
    client = RaindropClient(token=token) if token else None
    controller = None
    sorter_unavailable_reason = None
    mutation_lock = threading.RLock()
    on_reviews_changed = None
    if client is not None:
        from src.review_learning import learn_from_review_journal

        on_reviews_changed = lambda: learn_from_review_journal(
            journal_path=path,
            db_path=args.db_path,
        )
    if client is not None:
        try:
            validate_local_index(args.db_path)
        except (FileNotFoundError, ValueError) as error:
            sorter_unavailable_reason = str(error)
        else:
            sorter_client = RaindropClient(token=token)
            processor_lock = threading.Lock()
            processor: LocalBatchProcessor | None = None
            controller: LocalSorterController | None = None

            def process_batch(limit: int) -> dict[str, Any]:
                nonlocal processor
                with processor_lock:
                    if processor is None:
                        processor = LocalBatchProcessor(
                            sorter_client,
                            db_path=args.db_path,
                            model_dir=args.model_dir,
                            journal=SQLiteRunJournal(path),
                            apply=True,
                            mutation_lock=mutation_lock,
                            cover_cache=cover_cache,
                        )
                    return processor(
                        limit,
                        should_stop=(controller.stop_requested if controller else None),
                        on_progress=(controller.record_item if controller else None),
                    )

            controller = LocalSorterController(
                process_batch,
                batch_size=args.batch_size,
                poll_seconds=args.poll_seconds,
            )
    try:
        server = create_server(
            path,
            host=args.host,
            port=args.port,
            preview_loader=BookmarkPreviewService(token) if token else None,
            cover_cache=cover_cache,
            raindrop_client=client,
            sorter_controller=controller,
            sorter_unavailable_reason=sorter_unavailable_reason,
            mutation_lock=mutation_lock,
            on_reviews_changed=on_reviews_changed,
        )
    except FileNotFoundError as error:
        parser.error(str(error))
    if args.auto_start:
        if controller is None:
            server.server_close()
            parser.error(
                f"--auto-start is unavailable: {sorter_unavailable_reason or 'RAINDROP_TOKEN is required'}"
            )
        controller.start_automatic()
    url = f"http://{args.host}:{server.server_port}"
    print(f"Raindrop Sorter dashboard: {url}")
    print(f"Reading: {Path(path).resolve()}")
    if not token:
        print("Image previews and review actions disabled: RAINDROP_TOKEN is not configured.")
    elif sorter_unavailable_reason:
        print(f"Sorter controls disabled: {sorter_unavailable_reason}")
    print("Press Ctrl+C to stop.")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
