"""Raindrop API boundary behavior."""

from unittest.mock import patch

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
