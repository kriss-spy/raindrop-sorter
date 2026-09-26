import requests

from src.source_health import (
    SourceHealthStatus,
    TwitterSourceHealthChecker,
    twitter_status_url,
)


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def test_twitter_status_url_accepts_only_x_and_twitter_status_links():
    assert twitter_status_url("https://x.com/user/status/123") == "https://x.com/user/status/123"
    assert twitter_status_url("https://twitter.com/user/status/456?ref=home") == "https://twitter.com/user/status/456?ref=home"
    assert twitter_status_url("https://x.com/home") is None
    assert twitter_status_url("https://example.com/user/status/123") is None


def test_twitter_checker_marks_definitive_inaccessibility_unavailable():
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(403)

    result = TwitterSourceHealthChecker(get=get).check(
        {"link": "https://x.com/user/status/123"}
    )

    assert result.status is SourceHealthStatus.UNAVAILABLE
    assert result.http_status == 403
    assert calls[0][0] == "https://publish.twitter.com/oembed"
    assert calls[0][1]["params"] == {"url": "https://x.com/user/status/123"}


def test_twitter_checker_keeps_transient_failures_retryable():
    for status_code in (429, 500):
        result = TwitterSourceHealthChecker(
            get=lambda *_args, **_kwargs: FakeResponse(status_code)
        ).check({"link": "https://x.com/user/status/123"})
        assert result.status is SourceHealthStatus.UNKNOWN

    def timeout(*_args, **_kwargs):
        raise requests.Timeout("slow")

    result = TwitterSourceHealthChecker(get=timeout).check(
        {"link": "https://x.com/user/status/123"}
    )
    assert result.status is SourceHealthStatus.UNKNOWN


def test_twitter_checker_ignores_non_twitter_bookmarks():
    called = False

    def get(*_args, **_kwargs):
        nonlocal called
        called = True

    result = TwitterSourceHealthChecker(get=get).check(
        {"link": "https://example.com/post/123"}
    )

    assert result.status is SourceHealthStatus.NOT_APPLICABLE
    assert called is False


def test_twitter_checker_does_not_probe_status_with_good_metadata():
    called = False

    def get(*_args, **_kwargs):
        nonlocal called
        called = True

    result = TwitterSourceHealthChecker(get=get).check({
        "title": "An ordinary post with retained metadata",
        "link": "https://x.com/user/status/123",
    })

    assert result.status is SourceHealthStatus.NOT_APPLICABLE
    assert called is False
