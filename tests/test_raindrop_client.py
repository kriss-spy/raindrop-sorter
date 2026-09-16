"""Raindrop API boundary behavior."""

from unittest.mock import patch

import pytest
import requests

from src.raindrop_client import RaindropClient


class FakeResponse:
    def __init__(self, status_code, payload, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(response=response)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.headers = {}
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return next(self.responses)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)


def test_update_waits_for_rate_limit_reset_then_retries():
    session = FakeSession(
        [
            FakeResponse(429, {}, {"X-RateLimit-Reset": "150"}),
            FakeResponse(200, {"item": {"_id": 123}}),
        ]
    )
    client = RaindropClient(token="test-token")
    client.session = session

    with (
        patch("src.raindrop_client.time.time", return_value=100),
        patch("src.raindrop_client.time.sleep") as sleep,
    ):
        result = client.update_raindrop(123, tags=["sorter-pending-resolution"])

    assert result == {"item": {"_id": 123}}
    sleep.assert_called_once_with(50.0)
    assert [request[0] for request in session.requests] == ["PUT", "PUT"]


def test_collection_page_retries_transient_server_failure_in_place():
    session = FakeSession(
        [
            FakeResponse(521, {}),
            FakeResponse(200, {"items": [{"_id": 123}]}),
        ]
    )
    client = RaindropClient(token="test-token")
    client.session = session

    with patch("src.raindrop_client.time.sleep") as sleep:
        items, has_more = client.get_raindrops(0, page=202, perpage=50)

    assert items == [{"_id": 123}]
    assert has_more is False
    sleep.assert_called_once_with(2.0)
    assert [request[2]["params"]["page"] for request in session.requests] == [202, 202]


def test_collection_page_passes_exact_tag_search_to_raindrop():
    session = FakeSession([FakeResponse(200, {"items": [{"_id": 123}]})])
    client = RaindropClient(token="test-token")
    client.session = session

    items, has_more = client.get_raindrops(
        -1,
        page=0,
        perpage=25,
        search="#sorter-pending-resolution",
    )

    assert items == [{"_id": 123}]
    assert has_more is False
    assert session.requests[0][2]["params"] == {
        "page": 0,
        "perpage": 25,
        "search": "#sorter-pending-resolution",
    }


def test_collection_page_uses_total_count_for_exact_last_full_page():
    session = FakeSession(
        [FakeResponse(200, {"items": [{"_id": item_id} for item_id in range(25)], "count": 25})]
    )
    client = RaindropClient(token="test-token")
    client.session = session

    items, has_more = client.get_raindrops(-1, page=0, perpage=25)

    assert len(items) == 25
    assert has_more is False


def test_get_tags_can_be_scoped_to_unsorted():
    session = FakeSession(
        [FakeResponse(200, {"items": [{"_id": "sorter-reviewed:2026-09-16", "count": 41}]})]
    )
    client = RaindropClient(token="test-token")
    client.session = session

    tags = client.get_tags(-1)

    assert tags == [{"_id": "sorter-reviewed:2026-09-16", "count": 41}]
    assert session.requests[0][1].endswith("/tags/-1")


def test_transient_server_retries_are_bounded():
    session = FakeSession([FakeResponse(521, {}) for _ in range(6)])
    client = RaindropClient(token="test-token")
    client.session = session

    with (
        patch("src.raindrop_client.time.sleep") as sleep,
        pytest.raises(requests.HTTPError),
    ):
        client.get_raindrops(0, page=202, perpage=50)

    assert len(session.requests) == 6
    assert [call.args[0] for call in sleep.call_args_list] == [2.0, 4.0, 8.0, 16.0, 32.0]


def test_client_waits_before_next_request_when_quota_is_exhausted():
    session = FakeSession(
        [
            FakeResponse(
                200,
                {"_id": 1},
                {
                    "RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": "150",
                },
            ),
            FakeResponse(200, {"_id": 2}),
        ]
    )
    client = RaindropClient(token="test-token")
    client.session = session

    with (
        patch("src.raindrop_client.time.time", return_value=100),
        patch("src.raindrop_client.time.sleep") as sleep,
    ):
        first = client.get_collection(1)
        second = client.get_collection(2)

    assert first == {"_id": 1}
    assert second == {"_id": 2}
    sleep.assert_called_once_with(50.0)
    assert len(session.requests) == 2
