"""Client for the Raindrop.io REST API."""

import os
import time
from collections.abc import Callable
from typing import Any

import requests

RAINDROP_API_BASE = "https://api.raindrop.io/rest/v1"
MAX_REQUEST_RETRIES = 5
RATE_LIMIT_WINDOW_SECONDS = 60.0
TRANSIENT_RETRY_BASE_SECONDS = 2.0
TRANSIENT_RETRY_MAX_SECONDS = 60.0


class RaindropClient:
    """Thin wrapper around the Raindrop.io REST API."""

    def __init__(self, token: str | None = None):
        self.token = token or os.environ["RAINDROP_TOKEN"]
        self.session = requests.Session()
        self.request_count = 0
        self.rate_limit_wait_seconds = 0.0
        self._rate_limit_remaining: int | None = None
        self._rate_limit_reset_at: float | None = None
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        })

    def _capture_rate_limit(self, headers: Any) -> None:
        remaining = headers.get("RateLimit-Remaining")
        if remaining is None:
            remaining = headers.get("X-RateLimit-Remaining")
        try:
            self._rate_limit_remaining = int(remaining)
        except (TypeError, ValueError):
            self._rate_limit_remaining = None

        try:
            self._rate_limit_reset_at = float(headers.get("X-RateLimit-Reset"))
        except (TypeError, ValueError):
            self._rate_limit_reset_at = None

    def _wait_for_rate_limit_reset(self, reason: str) -> None:
        if self._rate_limit_reset_at is None:
            delay = RATE_LIMIT_WINDOW_SECONDS
        else:
            delay = self._rate_limit_reset_at - time.time()
        delay = min(max(delay, 1.0), RATE_LIMIT_WINDOW_SECONDS)
        self.rate_limit_wait_seconds += delay
        print(f"Raindrop rate limit {reason}; waiting {delay:.1f}s for reset")
        time.sleep(delay)
        self._rate_limit_remaining = None
        self._rate_limit_reset_at = None

    def _request(
        self,
        send: Callable[..., requests.Response],
        method_name: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{RAINDROP_API_BASE}/{path}"
        for attempt in range(MAX_REQUEST_RETRIES + 1):
            if self._rate_limit_remaining == 0:
                self._wait_for_rate_limit_reset("quota exhausted")

            request_options: dict[str, Any] = {"timeout": 30}
            if params is not None:
                request_options["params"] = params
            if json is not None:
                request_options["json"] = json
            resp = send(url, **request_options)
            self.request_count += 1
            self._capture_rate_limit(resp.headers)
            is_transient_server_error = 500 <= resp.status_code < 600
            if resp.status_code != 429 and not is_transient_server_error:
                resp.raise_for_status()
                return resp.json()

            if attempt == MAX_REQUEST_RETRIES:
                resp.raise_for_status()

            if resp.status_code == 429:
                print(
                    f"Raindrop {method_name} retry "
                    f"{attempt + 1}/{MAX_REQUEST_RETRIES}"
                )
                self._wait_for_rate_limit_reset("response received")
                continue

            delay = min(
                TRANSIENT_RETRY_BASE_SECONDS * (2**attempt),
                TRANSIENT_RETRY_MAX_SECONDS,
            )
            print(
                f"Raindrop {method_name} received {resp.status_code}; "
                f"retrying {attempt + 1}/{MAX_REQUEST_RETRIES} "
                f"in {delay:.1f}s",
                flush=True,
            )
            time.sleep(delay)

        raise RuntimeError("unreachable")

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request(self.session.get, "GET", path, params=params)

    def _put(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        return self._request(self.session.put, "PUT", path, json=json)

    def get_collections(self) -> list[dict[str, Any]]:
        """Return all collections (folders)."""
        roots = self._get("collections").get("items", [])
        children = self._get("collections/childrens").get("items", [])
        return [*roots, *children]

    def get_collection(self, collection_id: int) -> dict[str, Any]:
        """Return a single collection."""
        return self._get(f"collection/{collection_id}")

    def get_tags(self, collection_id: int) -> list[dict[str, Any]]:
        """Return tag names and counts scoped to a collection."""
        return self._get(f"tags/{collection_id}").get("items", [])

    def get_raindrop(self, raindrop_id: int) -> dict[str, Any]:
        """Return a single raindrop by ID."""
        return self._get(f"raindrop/{raindrop_id}")

    def get_raindrops(
        self,
        collection_id: int,
        page: int = 0,
        perpage: int = 50,
        search: str | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Return raindrops in a collection and whether more pages exist."""
        params: dict[str, Any] = {"page": page, "perpage": perpage}
        if search is not None:
            params["search"] = search
        data = self._get(
            f"raindrops/{collection_id}",
            params=params,
        )
        items = data.get("items", [])
        try:
            has_more = (page + 1) * perpage < int(data["count"])
        except (KeyError, TypeError, ValueError):
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
