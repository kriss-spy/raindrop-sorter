"""Client for the Raindrop.io REST API."""

import os
from typing import Any

import requests

RAINDROP_API_BASE = "https://api.raindrop.io/rest/v1"


class RaindropClient:
    """Thin wrapper around the Raindrop.io REST API."""

    def __init__(self, token: str | None = None):
        self.token = token or os.environ["RAINDROP_TOKEN"]
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        })

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{RAINDROP_API_BASE}/{path}"
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        url = f"{RAINDROP_API_BASE}/{path}"
        resp = self.session.put(url, json=json, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_collections(self) -> list[dict[str, Any]]:
        """Return all collections (folders)."""
        data = self._get("collections")
        return data.get("items", [])

    def get_collection(self, collection_id: int) -> dict[str, Any]:
        """Return a single collection."""
        return self._get(f"collection/{collection_id}")

    def get_raindrop(self, raindrop_id: int) -> dict[str, Any]:
        """Return a single raindrop by ID."""
        return self._get(f"raindrop/{raindrop_id}")

    def get_raindrops(
        self,
        collection_id: int,
        page: int = 0,
        perpage: int = 50,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Return raindrops in a collection and whether more pages exist."""
        data = self._get(
            f"raindrops/{collection_id}",
            params={"page": page, "perpage": perpage},
        )
        items = data.get("items", [])
        has_more = len(items) == perpage
        return items, has_more

    def get_all_raindrops(self, collection_id: int) -> list[dict[str, Any]]:
        """Paginate through all raindrops in a collection."""
        all_items: list[dict[str, Any]] = []
        page = 0
        while True:
            items, has_more = self.get_raindrops(collection_id, page=page, perpage=50)
            all_items.extend(items)
            if not has_more:
                break
            page += 1
        return all_items

    def update_raindrop(
        self,
        raindrop_id: int,
        collection_id: int | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Update a raindrop's folder and/or tags."""
        payload: dict[str, Any] = {}
        if collection_id is not None:
            payload["collection"] = {"$id": collection_id}
        if tags is not None:
            payload["tags"] = tags
        return self._put(f"raindrop/{raindrop_id}", payload)

    def get_unsorted_collection(self) -> dict[str, Any] | None:
        """Return the special Unsorted collection, or None if not found."""
        # Raindrop uses collection id -1 for Unsorted
        try:
            return self.get_collection(-1)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            raise
