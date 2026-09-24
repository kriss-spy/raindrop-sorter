"""Operator commands for inspecting the local run journal."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from src.run_journal import SQLiteRunJournal


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Inspect local sorter run history")
    parser.add_argument("--db-path", default="chroma_db")
    parser.add_argument(
        "--journal-path",
        help="SQLite journal path (default: <db-path>/run-journal.sqlite)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Count attempts by current lifecycle phase")
    recent = commands.add_parser("recent", help="Show recent attempts")
    recent.add_argument("--limit", type=int, default=20)
    explain = commands.add_parser("explain", help="Explain the latest attempt for a bookmark")
    explain.add_argument("bookmark_id", type=int)
    args = parser.parse_args(argv)

    journal = SQLiteRunJournal(
        args.journal_path or os.path.join(args.db_path, "run-journal.sqlite")
    )
    result: Any
    if args.command == "status":
        result = journal.status()
    elif args.command == "recent":
        result = journal.recent(limit=args.limit)
    else:
        result = journal.explain(args.bookmark_id)
        if result is None:
            parser.error(f"no journal attempt found for bookmark {args.bookmark_id}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
