from src.cover_cache import SQLiteCoverCache
from src.cover_cache_migration import migrate_cover_cache
from src.run_journal import SQLiteRunJournal


class FakeCoverSource:
    def __init__(self):
        self.calls = []

    def get_raindrops(self, collection_id, page=0, perpage=50):
        self.calls.append((collection_id, page, perpage))
        pages = {
            (0, 0): ([
                {"_id": 1, "cover": "https://rdl.ink/one.webp"},
                {"_id": 2, "cover": "https://rdl.ink/untracked.webp"},
            ], True),
            (0, 1): ([
                {"_id": 3, "cover": "https://rdl.ink/three.webp"},
                {"_id": 4, "cover": ""},
            ], False),
            (-99, 0): ([], False),
        }
        return pages[(collection_id, page)]


def test_cover_migration_populates_cache_from_paged_raindrop_lists(tmp_path):
    journal = SQLiteRunJournal(tmp_path / "journal.sqlite")
    journal.start_attempt({"_id": 1, "title": "One"}, mode="dry-run")
    journal.start_attempt({"_id": 3, "title": "Three"}, mode="dry-run")
    journal.start_attempt({"_id": 4, "title": "No cover"}, mode="dry-run")
    cover_cache = SQLiteCoverCache(tmp_path / "cover-cache.sqlite")
    source = FakeCoverSource()

    result = migrate_cover_cache(source, journal, cover_cache)

    assert result == {
        "status": "ok",
        "journal_bookmarks": 3,
        "scanned": 4,
        "cached": 2,
        "without_cover": 1,
    }
    assert {item["bookmark_id"]: item["cover"] for item in cover_cache.attach(journal.recent(limit=10))} == {
        1: "https://rdl.ink/one.webp",
        3: "https://rdl.ink/three.webp",
        4: None,
    }

    second = migrate_cover_cache(source, journal, cover_cache)
    assert second["journal_bookmarks"] == 0
    assert source.calls == [(0, 0, 50), (0, 1, 50)]
