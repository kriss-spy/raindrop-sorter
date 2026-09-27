"""Live Raindrop library browsing behind one dashboard-facing interface."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class SystemCollection:
    id: int
    title: str


SYSTEM_COLLECTIONS = (
    SystemCollection(0, "All bookmarks"),
    SystemCollection(-1, "Unsorted"),
    SystemCollection(-99, "Trash"),
)


class LibrarySource(Protocol):
    """Remote operations required by the live-library browser."""

    def get_collections(self) -> list[dict[str, Any]]: ...

    def get_collection_groups(self) -> list[dict[str, Any]]: ...

    def get_collection(self, collection_id: int) -> dict[str, Any]: ...

    def get_collection_count(self, collection_id: int) -> int: ...

    def get_raindrops(
        self,
        collection_id: int,
        page: int = 0,
        perpage: int = 50,
        search: str | None = None,
        sort: str | None = None,
    ) -> tuple[list[dict[str, Any]], bool]: ...


class LiveLibraryBrowser:
    """Expose live collection hierarchy and bookmark pages to UI callers."""

    def __init__(self, source: LibrarySource):
        self.source = source
        self._membership_cache: dict[int, tuple[float, frozenset[int]]] = {}

    def collection_tree(self) -> dict[str, Any]:
        collections = self.source.get_collections()
        by_id = {int(item["_id"]): item for item in collections}
        children: dict[int, list[int]] = {}
        for collection_id, collection in by_id.items():
            parent_id = _parent_id(collection.get("parent"))
            if parent_id in by_id:
                children.setdefault(parent_id, []).append(collection_id)

        def node(collection_id: int, ancestry: tuple[str, ...] = ()) -> dict[str, Any]:
            collection = by_id[collection_id]
            title = str(collection.get("title") or f"Collection {collection_id}")
            path = "/".join((*ancestry, title))
            return {
                "id": collection_id,
                "title": title,
                "path": path,
                "count": int(collection.get("count") or 0),
                "view": collection.get("view"),
                "children": [
                    node(child_id, (*ancestry, title))
                    for child_id in sorted(
                        children.get(collection_id, []),
                        key=lambda item: _collection_order(by_id[item]),
                    )
                ],
            }

        grouped_roots: set[int] = set()
        groups = []
        for index, group in enumerate(
            sorted(
                self.source.get_collection_groups(),
                key=lambda item: int(item.get("sort") or 0),
            )
        ):
            root_ids = [
                collection_id
                for raw_id in group.get("collections", [])
                if (collection_id := _collection_id(raw_id)) in by_id
                and _parent_id(by_id[collection_id].get("parent")) not in by_id
            ]
            grouped_roots.update(root_ids)
            groups.append({
                "id": f"group:{index}",
                "title": str(group.get("title") or "Collections"),
                "collections": [node(collection_id) for collection_id in root_ids],
            })

        orphan_roots = [
            collection_id
            for collection_id, collection in by_id.items()
            if _parent_id(collection.get("parent")) not in by_id
            and collection_id not in grouped_roots
        ]
        if orphan_roots:
            groups.append({
                "id": "other",
                "title": "Other",
                "collections": [
                    node(collection_id)
                    for collection_id in sorted(
                        orphan_roots,
                        key=lambda item: _collection_order(by_id[item]),
                    )
                ],
            })

        system_nodes = []
        for system_collection in SYSTEM_COLLECTIONS:
            collection_id = system_collection.id
            collection = self.source.get_collection(collection_id)
            title = str(collection.get("title") or system_collection.title)
            system_nodes.append({
                "id": collection_id,
                "title": title,
                "path": title,
                "count": self.source.get_collection_count(collection_id),
                "view": collection.get("view"),
                "children": [],
            })
        return {
            "groups": [{
                "id": "system",
                "title": "System",
                "collections": system_nodes,
            }, *groups],
        }

    def browse_collection(
        self,
        collection_id: int,
        *,
        page: int = 0,
        per_page: int = 50,
        search: str | None = None,
        sort: str | None = None,
    ) -> dict[str, Any]:
        if page < 0:
            raise ValueError("page must not be negative")
        if not 1 <= per_page <= 100:
            raise ValueError("per_page must be between 1 and 100")
        request = {
            "page": page,
            "perpage": per_page,
            "search": search,
        }
        if sort is not None:
            request["sort"] = sort
        items, has_more = self.source.get_raindrops(collection_id, **request)
        return {
            "collection_id": collection_id,
            "page": page,
            "per_page": per_page,
            "search": search,
            "sort": sort,
            "has_more": has_more,
            "next_page": page + 1 if has_more else None,
            "items": items,
        }

    def current_bookmark_ids(self, collection_id: int) -> set[int]:
        """Return every bookmark currently present in one Raindrop collection."""
        cached = self._membership_cache.get(collection_id)
        now = time.monotonic()
        if cached is not None and now - cached[0] < 60:
            return set(cached[1])
        bookmark_ids: set[int] = set()
        page = 0
        while True:
            items, has_more = self.source.get_raindrops(
                collection_id,
                page=page,
                perpage=50,
                search=None,
                sort=None,
            )
            bookmark_ids.update(int(item["_id"]) for item in items)
            if not has_more:
                self._membership_cache[collection_id] = (
                    now,
                    frozenset(bookmark_ids),
                )
                return bookmark_ids
            page += 1

    def invalidate_membership_cache(self) -> None:
        """Discard cached Raindrop locations after a local move."""
        self._membership_cache.clear()


def _collection_id(value: Any) -> int:
    if isinstance(value, dict):
        value = value.get("$id", value.get("_id"))
    return int(value)


def _parent_id(value: Any) -> int | None:
    if value in (None, {}):
        return None
    try:
        return _collection_id(value)
    except (TypeError, ValueError):
        return None


def _collection_order(collection: dict[str, Any]) -> int:
    return int(collection.get("sort") or 0)
