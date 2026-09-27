"""Behavior of the live Raindrop library browsing seam."""

from src.live_library import LiveLibraryBrowser


class FakeLibrarySource:
    def __init__(self):
        self.last_search = None
        self.collections = [
            {"_id": 10, "title": "Art", "count": 12, "sort": 0, "view": "grid"},
            {
                "_id": 11,
                "title": "Miku",
                "count": 5,
                "sort": 0,
                "parent": {"$id": 10},
                "view": "masonry",
            },
            {"_id": 20, "title": "Reading", "count": 7, "sort": 0},
        ]
        self.groups = [
            {"title": "Creative", "sort": 0, "collections": [10]},
            {"title": "Reference", "sort": 1, "collections": [20]},
        ]
        self.system = {
            0: {"_id": 0, "title": "All bookmarks", "count": 0},
            -1: {"_id": -1, "title": "Unsorted", "count": 0},
            -99: {"_id": -99, "title": "Trash", "count": 0},
        }

    def get_collections(self):
        return self.collections

    def get_collection_groups(self):
        return self.groups

    def get_collection(self, collection_id):
        return self.system[collection_id]

    def get_collection_count(self, collection_id):
        return {0: 24, -1: 3, -99: 2}[collection_id]

    def get_raindrops(self, collection_id, page=0, perpage=50, search=None, sort=None):
        self.last_search = search
        assert (collection_id, page, perpage, sort) == (11, 2, 2, "-title")
        return [
            {"_id": 101, "title": "First", "collection": {"$id": 11}},
            {"_id": 102, "title": "Second", "collection": {"$id": 11}},
        ], True


def test_collection_tree_preserves_groups_ancestry_counts_and_system_collections():
    tree = LiveLibraryBrowser(FakeLibrarySource()).collection_tree()

    assert [group["title"] for group in tree["groups"]] == [
        "System",
        "Creative",
        "Reference",
    ]
    assert [node["id"] for node in tree["groups"][0]["collections"]] == [0, -1, -99]
    assert [node["count"] for node in tree["groups"][0]["collections"]] == [24, 3, 2]
    art = tree["groups"][1]["collections"][0]
    assert art == {
        "id": 10,
        "title": "Art",
        "path": "Art",
        "count": 12,
        "view": "grid",
        "children": [
            {
                "id": 11,
                "title": "Miku",
                "path": "Art/Miku",
                "count": 5,
                "view": "masonry",
                "children": [],
            }
        ],
    }


def test_browse_collection_returns_one_incremental_live_page():
    source = FakeLibrarySource()
    page = LiveLibraryBrowser(source).browse_collection(
        11,
        page=2,
        per_page=2,
        search='#tag "exact phrase" / 日本語',
        sort="-title",
    )

    assert page == {
        "collection_id": 11,
        "page": 2,
        "per_page": 2,
        "search": '#tag "exact phrase" / 日本語',
        "sort": "-title",
        "has_more": True,
        "next_page": 3,
        "items": [
            {"_id": 101, "title": "First", "collection": {"$id": 11}},
            {"_id": 102, "title": "Second", "collection": {"$id": 11}},
        ],
    }
    assert source.last_search == '#tag "exact phrase" / 日本語'


def test_current_bookmark_ids_reads_every_live_collection_page():
    class PagedSource(FakeLibrarySource):
        def __init__(self):
            super().__init__()
            self.pages = []

        def get_raindrops(
            self, collection_id, page=0, perpage=50, search=None, sort=None
        ):
            self.pages.append((collection_id, page, perpage, search, sort))
            if page == 0:
                return [{"_id": bookmark_id} for bookmark_id in range(1, 51)], True
            return [{"_id": 51}], False

    source = PagedSource()
    browser = LiveLibraryBrowser(source)

    assert browser.current_bookmark_ids(11) == set(range(1, 52))
    assert source.pages == [
        (11, 0, 50, None, None),
        (11, 1, 50, None, None),
    ]

    # Local filter edits and the 15-second dashboard refresh reuse one bounded
    # live snapshot instead of repaging the Raindrop API.
    assert browser.current_bookmark_ids(11) == set(range(1, 52))
    assert len(source.pages) == 2


def test_collection_tree_keeps_duplicate_names_and_surfaces_missing_parents():
    source = FakeLibrarySource()
    source.collections = [
        {"_id": 1, "title": "First", "sort": 1},
        {"_id": 2, "title": "Second", "sort": 0},
        {"_id": 3, "title": "Shared", "parent": {"$id": 1}},
        {"_id": 4, "title": "Shared", "parent": {"$id": 2}},
        {"_id": 5, "title": "Detached", "parent": {"$id": 999}},
    ]
    source.groups = [{"title": "Library", "sort": 0, "collections": [{"$id": 2}, 1]}]

    tree = LiveLibraryBrowser(source).collection_tree()

    library = tree["groups"][1]
    assert [node["id"] for node in library["collections"]] == [2, 1]
    assert library["collections"][0]["children"][0]["path"] == "Second/Shared"
    assert library["collections"][1]["children"][0]["path"] == "First/Shared"
    assert tree["groups"][2]["title"] == "Other"
    assert tree["groups"][2]["collections"][0]["id"] == 5


def test_collection_tree_preserves_remote_order_when_sort_values_match():
    source = FakeLibrarySource()
    source.collections = [
        {"_id": 1, "title": "Root", "sort": 0},
        {"_id": 2, "title": "Zulu", "sort": 0, "parent": {"$id": 1}},
        {"_id": 3, "title": "Alpha", "sort": 0, "parent": {"$id": 1}},
    ]
    source.groups = [{"title": "Library", "sort": 0, "collections": [1]}]

    children = LiveLibraryBrowser(source).collection_tree()["groups"][1]["collections"][0]["children"]

    assert [child["title"] for child in children] == ["Zulu", "Alpha"]
