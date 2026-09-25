"""Local HTTP server for journal inspection and explicit human review actions."""

from __future__ import annotations

import argparse
import json
import os
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

from src.bookmark_preview import BookmarkPreviewService, PreviewLoader
from src.journal_dashboard import DASHBOARD_HTML
from src.journal_review import (
    IneligibleReviewAttempt,
    InvalidReviewDestination,
    JournalReviewService,
    ReviewAttemptNotFound,
    StaleReviewAttempt,
)
from src.raindrop_client import RaindropClient
from src.run_journal import SQLiteRunJournal


class JournalHTTPServer(ThreadingHTTPServer):
    journal: SQLiteRunJournal
    preview_loader: PreviewLoader | None
    reviewer: JournalReviewService | None


def create_server(
    journal_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    preview_loader: PreviewLoader | None = None,
    raindrop_client: Any | None = None,
) -> JournalHTTPServer:
    journal_path = Path(journal_path)
    if not journal_path.is_file():
        raise FileNotFoundError(f"journal does not exist: {journal_path}")
    if (preview_loader is not None or raindrop_client is not None) and host not in {
        "127.0.0.1", "localhost", "::1"
    }:
        raise ValueError("image previews and review actions require a loopback host")
    server = JournalHTTPServer((host, port), JournalRequestHandler)
    server.journal = SQLiteRunJournal(
        journal_path,
        read_only=raindrop_client is None,
    )
    server.preview_loader = preview_loader
    server.reviewer = (
        JournalReviewService(server.journal, raindrop_client)
        if raindrop_client is not None
        else None
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
                self._send_json(HTTPStatus.OK, self.server.journal.overview())
            elif request.path == "/api/attempts":
                self._attempts(parse_qs(request.query))
            elif request.path == "/api/review/collections":
                self._review_collections()
            elif request.path.startswith("/api/bookmarks/") and request.path.endswith("/preview"):
                self._preview(request.path)
            elif request.path.startswith("/api/attempts/"):
                attempt_id = request.path.removeprefix("/api/attempts/")
                trace = self.server.journal.explain_attempt(attempt_id)
                if trace is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "attempt not found"})
                else:
                    self._send_json(HTTPStatus.OK, trace)
            else:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except (TypeError, ValueError) as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

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
            prefix = "/api/attempts/"
            suffix = "/resolve"
            if request.path.startswith(prefix) and request.path.endswith(suffix):
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
                self._send_json(HTTPStatus.OK, result)
            else:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
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

    def _attempts(self, query: dict[str, list[str]]) -> None:
        limit = int(query.get("limit", ["50"])[0])
        if limit > 500:
            raise ValueError("limit must not exceed 500")
        latest = query.get("latest", ["0"])[0].casefold()
        if latest not in {"0", "1", "false", "true"}:
            raise ValueError("latest must be 0, 1, false, or true")
        items = self.server.journal.recent(
            limit=limit,
            outcome=query.get("outcome", [None])[0] or None,
            phase=query.get("phase", [None])[0] or None,
            query=query.get("q", [None])[0] or None,
            latest_per_bookmark=latest in {"1", "true"},
        )
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
        self._send(HTTPStatus.OK, image, content_type)

    def _send_json(self, status: HTTPStatus, payload: object) -> None:
        self._send(
            status,
            json.dumps(payload, ensure_ascii=False).encode(),
            "application/json; charset=utf-8",
        )

    def _send(self, status: HTTPStatus, body: str | bytes, content_type: str) -> None:
        encoded = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'",
        )
        self.end_headers()
        self.wfile.write(encoded)

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
    parser.add_argument("--open", action="store_true", help="Open the dashboard in a browser")
    args = parser.parse_args(argv)
    load_dotenv()
    path = args.journal_path or os.path.join(args.db_path, "run-journal.sqlite")
    token = os.environ.get("RAINDROP_TOKEN")
    client = RaindropClient(token=token) if token else None
    try:
        server = create_server(
            path,
            host=args.host,
            port=args.port,
            preview_loader=BookmarkPreviewService(token) if token else None,
            raindrop_client=client,
        )
    except FileNotFoundError as error:
        parser.error(str(error))
    url = f"http://{args.host}:{server.server_port}"
    print(f"Raindrop Journal: {url}")
    print(f"Reading: {Path(path).resolve()}")
    if not token:
        print("Image previews and review actions disabled: RAINDROP_TOKEN is not configured.")
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
