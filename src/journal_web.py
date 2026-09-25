"""Local, read-only HTTP server for the sorter run journal dashboard."""

from __future__ import annotations

import argparse
import json
import os
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.journal_dashboard import DASHBOARD_HTML
from src.run_journal import SQLiteRunJournal


class JournalHTTPServer(ThreadingHTTPServer):
    journal: SQLiteRunJournal


def create_server(
    journal_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> JournalHTTPServer:
    server = JournalHTTPServer((host, port), JournalRequestHandler)
    server.journal = SQLiteRunJournal(journal_path, read_only=True)
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

    def _attempts(self, query: dict[str, list[str]]) -> None:
        limit = int(query.get("limit", ["50"])[0])
        if limit > 500:
            raise ValueError("limit must not exceed 500")
        items = self.server.journal.recent(
            limit=limit,
            outcome=query.get("outcome", [None])[0] or None,
            phase=query.get("phase", [None])[0] or None,
            query=query.get("q", [None])[0] or None,
        )
        self._send_json(HTTPStatus.OK, {"items": items, "count": len(items)})

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
            "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'",
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
    path = args.journal_path or os.path.join(args.db_path, "run-journal.sqlite")
    try:
        server = create_server(path, host=args.host, port=args.port)
    except FileNotFoundError as error:
        parser.error(str(error))
    url = f"http://{args.host}:{server.server_port}"
    print(f"Raindrop Journal: {url}")
    print(f"Reading: {Path(path).resolve()}")
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
