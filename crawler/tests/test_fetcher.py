import pytest
import requests

from books_crawler.fetcher import DEFAULT_USER_AGENT, FetchError, HttpFetcher


class FakeResponse:
    def __init__(self, status_code=200, text="<html></html>"):
        self.status_code = status_code
        self.text = text
        self.encoding = None


class FakeSession:
    def __init__(self, response=None, error=None):
        self.headers = {}
        self.response = response
        self.error = error
        self.requests = []

    def get(self, url, timeout):
        self.requests.append((url, timeout))
        if self.error is not None:
            raise self.error
        return self.response


def test_sends_browser_user_agent_and_timeout():
    session = FakeSession(response=FakeResponse())
    fetcher = HttpFetcher(session=session, timeout=(3.0, 9.0), delay_seconds=0)

    assert fetcher.get("https://example.test/page") == "<html></html>"
    assert session.headers["User-Agent"] == DEFAULT_USER_AGENT
    assert session.requests == [("https://example.test/page", (3.0, 9.0))]


def test_non_200_response_raises_fetch_error():
    fetcher = HttpFetcher(session=FakeSession(response=FakeResponse(status_code=403)), delay_seconds=0)

    with pytest.raises(FetchError, match="HTTP 403"):
        fetcher.get("https://example.test/page")


def test_network_error_is_wrapped_in_fetch_error():
    session = FakeSession(error=requests.ConnectionError("boom"))
    fetcher = HttpFetcher(session=session, delay_seconds=0)

    with pytest.raises(FetchError, match="ConnectionError"):
        fetcher.get("https://example.test/page")


def test_polite_delay_is_applied_between_requests_only():
    sleeps = []
    session = FakeSession(response=FakeResponse())
    fetcher = HttpFetcher(session=session, delay_seconds=1.5, sleep=sleeps.append)

    fetcher.get("https://example.test/a")
    fetcher.get("https://example.test/b")
    fetcher.get("https://example.test/c")

    assert sleeps == pytest.approx([1.5, 1.5], abs=0.01)
