"""Provider-neutral HTTP acquisition (catalog_core.http_acquisition), driven by a made-up non-Kingstone policy.

Offline. A fake transport, a fake clock and a recording fake sleep; the curl session is a fake too.
"""

import logging
import math
import re
from types import MappingProxyType
from typing import ClassVar

import pytest

from catalog_core import http_acquisition
from catalog_core.http_acquisition import (
    AcquisitionError,
    AcquisitionFailure,
    FetchPolicy,
    PacedFetcher,
    RawResponse,
    backoff_seconds,
)

EXAMPLE_HOST = "api.example.test"
LIST_URL = "https://api.example.test/v1/items?page=1"
DETAIL_URL = "https://api.example.test/v1/items/42"
LIST_REJECTED = "not an example list URL"
DETAIL_REJECTED = "not an example detail URL"
EXAMPLE_HEADERS = {"Accept": "application/json", "X-Example": "1"}
OK_BODY = '{"items": []}'


def _is_list(url):
    return re.fullmatch(r"https://api\.example\.test/v1/items\?page=[1-9][0-9]*", url) is not None


def _is_detail(url):
    return re.fullmatch(r"https://api\.example\.test/v1/items/[0-9]+", url) is not None


POLICY = FetchPolicy(
    site_host=EXAMPLE_HOST,
    is_list_url=_is_list,
    is_detail_url=_is_detail,
    list_rejected=LIST_REJECTED,
    detail_rejected=DETAIL_REJECTED,
    min_delay_seconds=1.0,
    max_delay_seconds=2.0,
    request_headers=MappingProxyType(EXAMPLE_HEADERS),
    logger_name="example.acquisition",
)


class UnexpectedRequest(BaseException):
    """Raised by the fake transport when a test did not script enough responses (BaseException: not swallowed)."""


class World:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def wall_clock(self):
        return 1_700_000_000.0


class FakeTransport:
    """Answers scripted outcomes in order: a RawResponse, or an exception to raise. Records each call."""

    def __init__(self, world, *outcomes):
        self.world = world
        self.outcomes = list(outcomes)
        self.calls = []
        self.closed = False

    def get(self, url, *, timeout, max_bytes):
        self.calls.append((url, timeout, max_bytes))
        if not self.outcomes:
            raise UnexpectedRequest(url)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def close(self):
        self.closed = True


def ok(body=OK_BODY, headers=None):
    return RawResponse(200, headers or {}, body.encode("utf-8"))


def status(code, headers=None, body=b""):
    return RawResponse(code, headers or {}, body)


def make_fetcher(world, transport, *, sample=1.5, budget=math.inf, policy=POLICY):
    return PacedFetcher(
        policy=policy,
        transport=transport,
        sleep=world.sleep,
        clock=world.clock,
        wall_clock=world.wall_clock,
        sample_delay=lambda: sample,
        budget_remaining=lambda: budget,
    )


def expect_failure(fetch, url, kind):
    with pytest.raises(AcquisitionError) as info:
        fetch(url)
    assert info.value.kind is kind
    return info.value


# --- policy ----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("low", "high"),
    [(-1.0, 2.0), (3.0, 1.0)],
)
def test_a_policy_with_an_invalid_delay_range_is_refused(low, high):
    with pytest.raises(ValueError):
        FetchPolicy(
            site_host=EXAMPLE_HOST,
            is_list_url=_is_list,
            is_detail_url=_is_detail,
            list_rejected=LIST_REJECTED,
            detail_rejected=DETAIL_REJECTED,
            min_delay_seconds=low,
            max_delay_seconds=high,
            request_headers=MappingProxyType({}),
            logger_name="example.acquisition",
        )


# --- URL guards: refused before any request --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "url", "message"),
    [
        ("fetch_list_page", "https://api.example.test/v1/other?page=1", LIST_REJECTED),
        ("fetch_list_page", "https://api.example.test/v1/items?page=0", LIST_REJECTED),
        ("fetch_list_page", DETAIL_URL, LIST_REJECTED),
        ("fetch_detail_page", LIST_URL, DETAIL_REJECTED),
        ("fetch_detail_page", "https://api.example.test/v1/items/abc", DETAIL_REJECTED),
        ("fetch_list_page", "https://www.kingstone.com.tw/v1/items?page=1", LIST_REJECTED),
        ("fetch_detail_page", "https://www.kingstone.com.tw/v1/items/42", DETAIL_REJECTED),
        ("fetch_list_page", "http://api.example.test/v1/items?page=1", LIST_REJECTED),
        ("fetch_detail_page", "http://api.example.test/v1/items/42", DETAIL_REJECTED),
        ("fetch_list_page", "https://user:secret@api.example.test/v1/items?page=1", LIST_REJECTED),
        ("fetch_detail_page", "https://user@api.example.test/v1/items/42", DETAIL_REJECTED),
        ("fetch_list_page", "https://api.example.test:8443/v1/items?page=1", LIST_REJECTED),
        ("fetch_detail_page", "https://api.example.test:443/v1/items/42", DETAIL_REJECTED),
        ("fetch_list_page", "https://127.0.0.1/v1/items?page=1", LIST_REJECTED),
        ("fetch_list_page", None, LIST_REJECTED),
        ("fetch_detail_page", None, DETAIL_REJECTED),
    ],
)
def test_off_policy_urls_are_refused_with_the_policy_message_and_no_request(method, url, message):
    world = World()
    transport = FakeTransport(world)
    fetcher = make_fetcher(world, transport)

    with pytest.raises(ValueError) as info:
        getattr(fetcher, method)(url)

    assert str(info.value) == message
    assert transport.calls == []
    assert world.sleeps == []
    assert fetcher.http_attempts == 0


def test_each_method_accepts_only_its_own_predicate():
    world = World()
    transport = FakeTransport(world, ok(), ok())
    fetcher = make_fetcher(world, transport)

    assert fetcher.fetch_list_page(LIST_URL) == OK_BODY
    assert fetcher.fetch_detail_page(DETAIL_URL) == OK_BODY
    assert [call[0] for call in transport.calls] == [LIST_URL, DETAIL_URL]


# --- pacing ----------------------------------------------------------------------------------------------------------


def test_the_default_delay_is_sampled_uniformly_from_the_policy_range(monkeypatch):
    drawn = []

    def recording_uniform(low, high):
        drawn.append((low, high))
        return (low + high) / 2

    monkeypatch.setattr(http_acquisition.random, "uniform", recording_uniform)
    world = World()
    transport = FakeTransport(world, ok(), ok())
    fetcher = PacedFetcher(policy=POLICY, transport=transport, sleep=world.sleep, clock=world.clock)

    fetcher.fetch_list_page(LIST_URL)
    fetcher.fetch_list_page(LIST_URL)

    assert drawn == [(1.0, 2.0), (1.0, 2.0)]
    assert world.sleeps == [1.5, 1.5]


def test_every_pacing_sleep_stays_inside_the_policy_range(monkeypatch):
    monkeypatch.setattr(http_acquisition.random, "uniform", lambda low, high: high)
    world = World()
    transport = FakeTransport(world, ok(), ok(), ok())
    fetcher = PacedFetcher(policy=POLICY, transport=transport, sleep=world.sleep, clock=world.clock)

    for _ in range(3):
        fetcher.fetch_list_page(LIST_URL)

    assert world.sleeps == [2.0, 2.0, 2.0]
    assert all(POLICY.min_delay_seconds <= seconds <= POLICY.max_delay_seconds for seconds in world.sleeps)


# --- retry, status and redirect outcomes ------------------------------------------------------------------------------


def test_one_retry_on_503_waits_for_the_backoff():
    world = World()
    transport = FakeTransport(world, status(503, body=b"busy"), ok())
    fetcher = make_fetcher(world, transport, sample=1.5)

    assert fetcher.fetch_list_page(LIST_URL) == OK_BODY

    assert len(transport.calls) == 2
    assert world.sleeps == [1.5, backoff_seconds(2)]
    assert (fetcher.http_attempts, fetcher.http_failures) == (2, 1)


def test_404_is_an_http_status_failure_and_is_not_retried():
    world = World()
    transport = FakeTransport(world, status(404), ok())
    error = expect_failure(make_fetcher(world, transport).fetch_detail_page, DETAIL_URL, AcquisitionFailure.HTTP_STATUS)

    assert error.status == 404
    assert error.attempts == 1
    assert len(transport.calls) == 1


def test_a_3xx_is_a_redirect_failure_and_the_redirect_is_not_followed():
    world = World()
    transport = FakeTransport(world, status(302, {"Location": "https://api.example.test/elsewhere?x=1"}), ok())
    error = expect_failure(make_fetcher(world, transport).fetch_list_page, LIST_URL, AcquisitionFailure.REDIRECT)

    assert error.status == 302
    assert error.attempts == 1
    assert "/elsewhere" in str(error)
    assert len(transport.calls) == 1


# --- budget ----------------------------------------------------------------------------------------------------------


def test_an_exhausted_budget_fails_before_anything_is_sent():
    world = World()
    transport = FakeTransport(world, ok())
    fetcher = make_fetcher(world, transport, budget=0)

    expect_failure(fetcher.fetch_list_page, LIST_URL, AcquisitionFailure.BUDGET_EXHAUSTED)

    assert transport.calls == []
    assert world.sleeps == []
    assert fetcher.http_attempts == 0


def test_a_wait_longer_than_the_remaining_budget_fails_before_sleeping_or_sending():
    world = World()
    transport = FakeTransport(world, ok())
    fetcher = make_fetcher(world, transport, sample=2.0, budget=1.0)

    expect_failure(fetcher.fetch_list_page, LIST_URL, AcquisitionFailure.BUDGET_EXHAUSTED)

    assert transport.calls == []
    assert world.sleeps == []


# --- request configuration comes from the policy -----------------------------------------------------------------------


class FakeCurlResponse:
    status_code = 200
    headers: ClassVar[dict[str, str]] = {}

    def iter_content(self, *args, **kwargs):
        yield OK_BODY.encode("utf-8")

    def close(self):
        pass


class RecordingCurlSession:
    created: ClassVar[list] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        RecordingCurlSession.created.append(self)

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeCurlResponse()

    def close(self):
        pass


def test_the_default_transport_sends_the_policy_headers_and_impersonates_chrome(monkeypatch):
    RecordingCurlSession.created = []
    monkeypatch.setattr(http_acquisition.curl_requests, "Session", RecordingCurlSession)
    fetcher = PacedFetcher(policy=POLICY, sleep=lambda seconds: None, sample_delay=lambda: 1.0)

    assert fetcher.fetch_list_page(LIST_URL) == OK_BODY
    fetcher.close()

    (session,) = RecordingCurlSession.created
    assert session.kwargs["impersonate"] == "chrome"
    (url, kwargs) = session.calls[0]
    assert url == LIST_URL
    assert kwargs["headers"] == EXAMPLE_HEADERS
    assert kwargs["allow_redirects"] is False
    assert "Accept-Language" not in kwargs["headers"]


# --- logging ---------------------------------------------------------------------------------------------------------


def test_each_request_is_logged_on_the_policy_logger_and_not_on_kingstone(caplog):
    world = World()
    transport = FakeTransport(world, status(503, body=b"abc"), ok())
    with caplog.at_level(logging.INFO, logger="example.acquisition"):
        make_fetcher(world, transport).fetch_list_page(LIST_URL)

    ours = [r for r in caplog.records if r.name == "example.acquisition"]
    assert [r.getMessage() for r in ours if r.levelno == logging.INFO] == [
        f"GET {LIST_URL} status=503 bytes=3 attempt=1",
        f"GET {LIST_URL} status=200 bytes={len(OK_BODY.encode())} attempt=2",
    ]
    assert len([r for r in ours if r.levelno == logging.WARNING]) == 1
    assert not [r for r in caplog.records if r.name == "kingstone.acquisition"]
