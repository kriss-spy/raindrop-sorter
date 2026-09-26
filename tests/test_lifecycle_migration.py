from src.lifecycle_migration import _legacy_state, migrate_remote_lifecycle
from src.run_journal import SQLiteRunJournal
from src.state_machine import is_remote_lifecycle_tag


class FakeMigrationClient:
    def __init__(self):
        self.updates = []
        self.items = {
            1: {"_id": 1, "title": "Already journaled", "tags": ["favorite", "sorter-reviewed:2026-09-25"]},
            2: {"_id": 2, "title": "Conflict", "tags": ["favorite", "sorter-reviewed:2026-09-25", "sorter-edge-case:conflict"]},
            3: {"_id": 3, "title": "Pending", "tags": ["favorite", "sorter-pending-resolution"]},
            4: {"_id": 4, "title": "Sorted", "collection": {"$id": 42}, "tags": ["favorite", "ai:sorted:2026-09-25"]},
        }

    def get_tags(self, collection_id):
        if collection_id == -99:
            return []
        return [
            {"_id": tag}
            for tag in sorted({
                tag
                for item in self.items.values()
                for tag in item["tags"]
                if is_remote_lifecycle_tag(tag)
            })
        ]

    def get_raindrops(self, collection_id, page=0, perpage=50, search=None):
        assert page == 0
        matches = {
            '#"sorter-reviewed:2026-09-25"': [self.items[1], self.items[2]],
            '#"sorter-edge-case:conflict"': [self.items[2]],
            '#"sorter-pending-resolution"': [self.items[3]],
            '#"ai:sorted:2026-09-25"': [self.items[4]],
        }
        return ([dict(item) for item in matches[search]], False)

    def get_raindrop(self, bookmark_id):
        return dict(self.items[bookmark_id])

    def update_raindrop(self, bookmark_id, collection_id=None, tags=None):
        self.updates.append((bookmark_id, tags))
        self.items[bookmark_id]["tags"] = tags


def test_lifecycle_migration_is_dry_run_by_default(tmp_path):
    client = FakeMigrationClient()
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")

    result = migrate_remote_lifecycle(client, journal)

    assert result["discovered"] == 4
    assert result["would_import"] == 4
    assert result["would_clean"] == 4
    assert result["applied"] is False
    assert result["items"][1]["outcome"] == "conflict"
    assert result["items"][1]["cleaned_tags"] == ["favorite"]
    assert client.updates == []
    assert journal.terminal_bookmark_ids() == set()


def test_lifecycle_migration_persists_before_cleaning_and_is_idempotent(tmp_path):
    client = FakeMigrationClient()
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    journal.import_legacy_state(client.items[1], outcome="review", phase="applied")

    first = migrate_remote_lifecycle(client, journal, apply=True)
    second = migrate_remote_lifecycle(client, journal, apply=True)

    assert first["imported"] == 3
    assert first["already_journaled"] == 1
    assert first["cleaned"] == 4
    assert first["failed"] == 0
    assert first["remaining"] == 0
    assert second["imported"] == 0
    assert second["discovered"] == 0
    assert {bookmark_id for bookmark_id, _tags in client.updates} == {1, 2, 3, 4}
    assert all(tags == ["favorite"] for _bookmark_id, tags in client.updates)
    assert journal.terminal_bookmark_ids() == {1, 2, 4}
    pending = journal.explain(3)
    assert pending is not None
    assert pending["attempt"]["current_phase"] == "pending_resolution"
    conflict = journal.explain(2)
    assert conflict is not None
    assert conflict["attempt"]["outcome"] == "conflict"


def test_failed_attempt_does_not_count_as_reconciled_legacy_state(tmp_path):
    client = FakeMigrationClient()
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    failed = journal.start_attempt(client.items[1], mode="apply")
    journal.fail(failed, RuntimeError("offline"))

    result = migrate_remote_lifecycle(client, journal, apply=True)

    assert result["imported"] == 4
    assert result["remaining"] == 0
    trace = journal.explain(1)
    assert trace["attempt"]["mode"] == "legacy-tag-migration"
    assert trace["attempt"]["outcome"] == "review"


def test_migration_reimports_when_destination_differs(tmp_path):
    client = FakeMigrationClient()
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    journal.import_legacy_state(
        client.items[4],
        outcome="confirmed",
        phase="applied",
        destination="Old/Folder",
    )

    result = migrate_remote_lifecycle(
        client,
        journal,
        apply=True,
        destination_paths={42: "New/Folder"},
    )

    assert result["imported"] == 4
    trace = journal.explain(4)
    assert trace["attempt"]["destination"] == "New/Folder"


def test_apply_refetches_before_cleanup_and_preserves_late_user_tags(tmp_path):
    client = FakeMigrationClient()
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    original_get = client.get_raindrop

    def get_with_late_tag(bookmark_id):
        bookmark = original_get(bookmark_id)
        bookmark["tags"] = [*bookmark["tags"], "late-user-tag"]
        return bookmark

    client.get_raindrop = get_with_late_tag

    migrate_remote_lifecycle(client, journal, apply=True)

    assert all("late-user-tag" in tags for _bookmark_id, tags in client.updates)


def test_legacy_state_ignores_near_prefix_user_tags_and_tracks_vision_attempt():
    assert _legacy_state([
        "ai:sorted:2026-09-25",
        "sorter-pending-visionary",
        "sorter-reviewed-books",
    ]) == ("applied", "confirmed")
    assert _legacy_state(["sorter-vision-attempted"]) == ("visual_completed", None)
