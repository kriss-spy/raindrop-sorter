import json

import pytest

from src.journal_cli import main
from src.run_journal import SQLiteRunJournal


def test_journal_cli_exposes_status_recent_and_explain(tmp_path, capsys):
    path = tmp_path / "journal.sqlite"
    journal = SQLiteRunJournal(path)
    attempt = journal.start_attempt({"_id": 123, "title": "example"}, mode="dry-run")
    journal.complete(attempt, phase="dry_run_completed")

    main(["--journal-path", str(path), "status"])
    assert json.loads(capsys.readouterr().out) == {"dry_run_completed": 1}

    main(["--journal-path", str(path), "recent", "--limit", "1"])
    assert json.loads(capsys.readouterr().out)[0]["bookmark_id"] == 123

    main(["--journal-path", str(path), "explain", "123"])
    assert json.loads(capsys.readouterr().out)["attempt"]["bookmark_id"] == 123


def test_journal_cli_reports_missing_bookmark(tmp_path):
    path = tmp_path / "journal.sqlite"

    with pytest.raises(SystemExit):
        main(["--journal-path", str(path), "explain", "999"])
