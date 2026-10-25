"""Kingstone HTTP acquisition: URL guards, pacing, retry, budget, response classification and the curl transport.

Offline. Every test uses a fake transport (or a fake curl session), a fake clock and a recording fake sleep.
"""

import logging
import math
from datetime import UTC, datetime
from email.utils import format_datetime

import pytest
from curl_cffi.requests import exceptions as curl_exceptions

from kingstone import acquisition
from kingstone.acquisition import (
    MAX_ATTEMPTS,
    MAX_BACKOFF_SECONDS,
    MAX_RESPONSE_BYTES,
    MAX_RETRY_AFTER_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    AcquisitionError,
    AcquisitionFailure,
    CurlTransport,
    KingstoneFetcher,
    RawResponse,
    ResponseTooLarge,
    TransportConnectionError,
    TransportTimeout,
    backoff_seconds,
)

LIST_URL = "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1"
DETAIL_URL = "https://www.kingstone.com.tw/basic/9789570000001/"
WALL_NOW = 1_700_000_000.0
OK_BODY = "<html>金石堂 ok</html>"


class UnexpectedRequest(BaseException):
    """Raised by the fake transport when a test did not script enough responses (BaseException: not swallowed)."""


class World:
    """Fake clock plus a timeline of sleeps and transport calls, in the order they happened."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []
        self.timeline = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.timeline.append(("sleep", seconds))
        self.now += seconds

    def advance(self, seconds):
        self.now += seconds

    def wall_clock(self):
        return WALL_NOW


class FakeTransport:
    """Answers scripted outcomes in order: a RawResponse, or an exception to raise. Records each call."""

    def __init__(self, world, *outcomes, duration=0.0):
        self.world = world
        self.outcomes = list(outcomes)
        self.duration = duration
        self.calls = []
        self.closed = False

    def get(self, url, *, timeout, max_bytes):
        self.calls.append((url, timeout, max_bytes))
        self.world.timeline.append(("get", url))
        self.world.now += self.duration
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


def make_fetcher(world, transport, *, sample=3.0, budget=math.inf):
    return KingstoneFetcher(
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


# --- constants -------------------------------------------------------------------------------------------------------


def test_constants_match_the_contract():
    assert MAX_ATTEMPTS == 3
    assert REQUEST_TIMEOUT_SECONDS == 30
    assert MAX_BACKOFF_SECONDS == 60
    assert MAX_RETRY_AFTER_SECONDS == 120
    assert MAX_RESPONSE_BYTES == 5 * 1024 * 1024
    assert acquisition.MIN_PAGE_DELAY_SECONDS == 3
    assert acquisition.MAX_PAGE_DELAY_SECONDS == 10


# --- URL guards ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1&sort=sa_desc",  # default sort must be omitted
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=01",
        "http://www.kingstone.com.tw/book/jdc/?dis=list&page=1",
        "https://example.com/book/jdc/?dis=list&page=1",
        "https://user:secret@www.kingstone.com.tw/book/jdc/?dis=list&page=1",
        "https://www.kingstone.com.tw:443/book/jdc/?dis=list&page=1",
        "https://127.0.0.1/book/jdc/?dis=list&page=1",
        "https://[::1]/book/jdc/?dis=list&page=1",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1#frag",
        "https://www.kingstone.com.tw/normal/book/jdc/?dis=list&page=1",
        DETAIL_URL,
    ],
)
def test_list_fetch_rejects_urls_outside_the_grammar_without_a_request(url):
    world = World()
    transport = FakeTransport(world, ok())
    fetcher = make_fetcher(world, transport)
    with pytest.raises(ValueError):
        fetcher.fetch_list_page(url)
    assert transport.calls == []
    assert world.timeline == []


@pytest.mark.parametrize(
    "url",
    [
        "https://www.kingstone.com.tw/basic/9789570000001/?lid=1",
        "http://www.kingstone.com.tw/basic/9789570000001/",
        "https://example.com/basic/9789570000001/",
        "https://user:secret@www.kingstone.com.tw/basic/9789570000001/",
        "https://www.kingstone.com.tw:443/basic/9789570000001/",
        "https://127.0.0.1/basic/9789570000001/",
        "https://www.kingstone.com.tw/basic/978957000000/",
        LIST_URL,
    ],
)
def test_detail_fetch_rejects_urls_outside_the_grammar_without_a_request(url):
    world = World()
    transport = FakeTransport(world, ok())
    fetcher = make_fetcher(world, transport)
    with pytest.raises(ValueError):
        fetcher.fetch_detail_page(url)
    assert transport.calls == []


def test_accepted_urls_are_requested_with_timeout_and_size_bound():
    world = World()
    transport = FakeTransport(world, ok(), ok())
    fetcher = make_fetcher(world, transport)
    assert fetcher.fetch_list_page(LIST_URL) == OK_BODY
    assert fetcher.fetch_detail_page(DETAIL_URL) == OK_BODY
    assert transport.calls == [(LIST_URL, 30, MAX_RESPONSE_BYTES), (DETAIL_URL, 30, MAX_RESPONSE_BYTES)]


# --- pacing ----------------------------------------------------------------------------------------------------------


def test_first_request_waits_for_the_sampled_delay():
    world = World()
    transport = FakeTransport(world, ok())
    make_fetcher(world, transport, sample=5.0).fetch_list_page(LIST_URL)
    assert world.timeline == [("sleep", 5.0), ("get", LIST_URL)]


def test_default_sampled_delay_is_between_3_and_10_seconds():
    world = World()
    transport = FakeTransport(world, ok())
    fetcher = KingstoneFetcher(transport=transport, sleep=world.sleep, clock=world.clock)
    fetcher.fetch_list_page(LIST_URL)
    assert 3.0 <= world.sleeps[0] <= 10.0


def test_time_since_the_previous_request_ended_counts_toward_the_delay():
    world = World()
    transport = FakeTransport(world, ok(), ok(), duration=1.0)
    fetcher = make_fetcher(world, transport, sample=5.0)
    fetcher.fetch_list_page(LIST_URL)  # sleep 5, request takes 1 second
    world.advance(2.0)  # parsing and DB work between requests
    fetcher.fetch_detail_page(DETAIL_URL)
    assert world.sleeps == [5.0, 3.0]


def test_no_extra_wait_when_the_previous_request_is_older_than_the_delay():
    world = World()
    transport = FakeTransport(world, ok(), ok())
    fetcher = make_fetcher(world, transport, sample=5.0)
    fetcher.fetch_list_page(LIST_URL)
    world.advance(60.0)
    fetcher.fetch_detail_page(DETAIL_URL)
    assert world.sleeps == [5.0]


def test_retry_is_paced_and_the_longer_of_pacing_and_backoff_wins():
    world = World()
    transport = FakeTransport(world, status(503), ok())
    make_fetcher(world, transport, sample=8.0).fetch_list_page(LIST_URL)
    # Pacing 8 and backoff 5 both count from the failed response; the wait is their maximum, 8.
    assert world.sleeps == [8.0, 8.0]


def test_backoff_wins_over_a_shorter_pacing_delay():
    world = World()
    transport = FakeTransport(world, status(500), status(500), ok())
    make_fetcher(world, transport, sample=3.0).fetch_list_page(LIST_URL)
    # First request: pacing 3. Retry 2: max(pacing 3, backoff 5) = 5. Retry 3: max(3, backoff 10) = 10.
    assert world.sleeps == [3.0, 5.0, 10.0]


# --- backoff helper ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("attempt", "expected"), [(2, 5.0), (3, 10.0), (4, 20.0), (5, 40.0), (6, 60.0), (7, 60.0)])
def test_backoff_doubles_from_five_seconds_and_is_capped(attempt, expected):
    assert backoff_seconds(attempt) == expected


# --- retry -----------------------------------------------------------------------------------------------------------


def test_timeout_then_success_retries_once():
    world = World()
    transport = FakeTransport(world, TransportTimeout("slow"), ok())
    assert make_fetcher(world, transport).fetch_list_page(LIST_URL) == OK_BODY
    assert len(transport.calls) == 2


def test_connection_error_then_success_retries_once():
    world = World()
    transport = FakeTransport(world, TransportConnectionError("reset"), ok())
    assert make_fetcher(world, transport).fetch_detail_page(DETAIL_URL) == OK_BODY
    assert len(transport.calls) == 2


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_retryable_statuses_are_retried(code):
    world = World()
    transport = FakeTransport(world, status(code), ok())
    assert make_fetcher(world, transport).fetch_list_page(LIST_URL) == OK_BODY
    assert len(transport.calls) == 2


def test_retryable_status_exhaustion_reports_http_status_with_three_attempts():
    world = World()
    transport = FakeTransport(world, status(503), status(503), status(503))
    error = expect_failure(make_fetcher(world, transport).fetch_list_page, LIST_URL, AcquisitionFailure.HTTP_STATUS)
    assert error.attempts == 3
    assert error.status == 503
    assert len(transport.calls) == 3


def test_transport_retry_exhaustion_reports_transport_with_three_attempts():
    world = World()
    transport = FakeTransport(world, TransportTimeout("a"), TransportConnectionError("b"), TransportTimeout("c"))
    error = expect_failure(make_fetcher(world, transport).fetch_list_page, LIST_URL, AcquisitionFailure.TRANSPORT)
    assert error.attempts == 3
    assert error.status is None
    assert len(transport.calls) == 3


@pytest.mark.parametrize("code", [400, 403, 404])
def test_client_errors_are_not_retried(code):
    world = World()
    transport = FakeTransport(world, status(code), ok())
    error = expect_failure(make_fetcher(world, transport).fetch_detail_page, DETAIL_URL, AcquisitionFailure.HTTP_STATUS)
    assert error.attempts == 1
    assert error.status == code
    assert len(transport.calls) == 1


def test_unexpected_transport_exception_is_a_non_retryable_transport_failure():
    world = World()
    transport = FakeTransport(world, RuntimeError("boom"), ok())
    error = expect_failure(make_fetcher(world, transport).fetch_list_page, LIST_URL, AcquisitionFailure.TRANSPORT)
    assert error.attempts == 1
    assert len(transport.calls) == 1
    assert isinstance(error.__cause__, RuntimeError)


# --- Retry-After -----------------------------------------------------------------------------------------------------


def test_retry_after_seconds_extend_the_wait():
    world = World()
    transport = FakeTransport(world, status(429, {"Retry-After": "7"}), ok())
    make_fetcher(world, transport, sample=3.0).fetch_list_page(LIST_URL)
    assert world.sleeps == [3.0, 7.0]


def test_retry_after_is_honoured_on_503_and_is_case_insensitive():
    world = World()
    transport = FakeTransport(world, status(503, {"retry-after": "20"}), ok())
    make_fetcher(world, transport, sample=3.0).fetch_list_page(LIST_URL)
    assert world.sleeps == [3.0, 20.0]


def test_retry_after_below_backoff_does_not_shorten_the_wait():
    world = World()
    transport = FakeTransport(world, status(429, {"Retry-After": "2"}), ok())
    make_fetcher(world, transport, sample=3.0).fetch_list_page(LIST_URL)
    assert world.sleeps == [3.0, 5.0]


def test_retry_after_at_the_limit_is_still_honoured():
    world = World()
    transport = FakeTransport(world, status(429, {"Retry-After": "120"}), ok())
    make_fetcher(world, transport, sample=3.0).fetch_list_page(LIST_URL)
    assert world.sleeps == [3.0, 120.0]


def test_retry_after_over_the_limit_fails_without_resending():
    world = World()
    transport = FakeTransport(world, status(429, {"Retry-After": "121"}), ok())
    error = expect_failure(make_fetcher(world, transport).fetch_list_page, LIST_URL, AcquisitionFailure.RETRY_AFTER_TOO_LONG)
    assert error.attempts == 1
    assert error.status == 429
    assert len(transport.calls) == 1
    assert len(world.sleeps) == 1  # only the first request's pacing; no wait for the rejected retry


def test_retry_after_http_date_uses_the_wall_clock():
    world = World()
    when = format_datetime(datetime.fromtimestamp(WALL_NOW + 30, UTC), usegmt=True)
    transport = FakeTransport(world, status(503, {"Retry-After": when}), ok())
    make_fetcher(world, transport, sample=3.0).fetch_list_page(LIST_URL)
    assert world.sleeps == [3.0, pytest.approx(30.0)]


def test_retry_after_http_date_in_the_past_falls_back_to_backoff():
    world = World()
    when = format_datetime(datetime.fromtimestamp(WALL_NOW - 300, UTC), usegmt=True)
    transport = FakeTransport(world, status(503, {"Retry-After": when}), ok())
    make_fetcher(world, transport, sample=3.0).fetch_list_page(LIST_URL)
    assert world.sleeps == [3.0, 5.0]


def test_unparseable_retry_after_is_ignored():
    world = World()
    transport = FakeTransport(world, status(429, {"Retry-After": "soon"}), ok())
    make_fetcher(world, transport, sample=3.0).fetch_list_page(LIST_URL)
    assert world.sleeps == [3.0, 5.0]


def test_retry_after_is_ignored_for_statuses_other_than_429_and_503():
    world = World()
    transport = FakeTransport(world, status(500, {"Retry-After": "999"}), ok())
    make_fetcher(world, transport, sample=3.0).fetch_list_page(LIST_URL)
    assert world.sleeps == [3.0, 5.0]


def test_retry_after_too_long_on_the_last_attempt_is_plain_retry_exhaustion():
    world = World()
    transport = FakeTransport(world, status(503), status(503), status(503, {"Retry-After": "999"}))
    error = expect_failure(make_fetcher(world, transport).fetch_list_page, LIST_URL, AcquisitionFailure.HTTP_STATUS)
    assert error.attempts == 3
    assert len(transport.calls) == 3


# --- budget ----------------------------------------------------------------------------------------------------------


def test_pacing_over_the_budget_fails_before_any_sleep_or_request():
    world = World()
    transport = FakeTransport(world, ok())
    error = expect_failure(make_fetcher(world, transport, sample=5.0, budget=4.0).fetch_list_page, LIST_URL, AcquisitionFailure.BUDGET_EXHAUSTED)
    assert error.attempts == 0
    assert world.sleeps == []
    assert transport.calls == []


def test_backoff_over_the_budget_fails_before_the_retry_is_sent():
    world = World()
    transport = FakeTransport(world, status(500), ok())
    error = expect_failure(make_fetcher(world, transport, sample=3.0, budget=4.0).fetch_list_page, LIST_URL, AcquisitionFailure.BUDGET_EXHAUSTED)
    assert error.attempts == 1
    assert world.sleeps == [3.0]
    assert len(transport.calls) == 1


def test_retry_after_over_the_budget_fails_before_the_retry_is_sent():
    world = World()
    transport = FakeTransport(world, status(429, {"Retry-After": "10"}), ok())
    error = expect_failure(make_fetcher(world, transport, sample=3.0, budget=9.0).fetch_list_page, LIST_URL, AcquisitionFailure.BUDGET_EXHAUSTED)
    assert error.attempts == 1
    assert world.sleeps == [3.0]
    assert len(transport.calls) == 1


def test_waits_within_the_budget_are_taken():
    world = World()
    transport = FakeTransport(world, status(500), ok())
    make_fetcher(world, transport, sample=3.0, budget=5.0).fetch_list_page(LIST_URL)
    assert world.sleeps == [3.0, 5.0]


# --- redirects -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("code", [301, 302])
def test_redirect_is_reported_not_followed_and_not_retried(code):
    world = World()
    transport = FakeTransport(world, status(code, {"Location": "https://www.kingstone.com.tw/book/?x=1"}), ok())
    error = expect_failure(make_fetcher(world, transport).fetch_list_page, LIST_URL, AcquisitionFailure.REDIRECT)
    assert error.attempts == 1
    assert error.status == code
    assert "/book/" in str(error)
    assert "x=1" not in str(error)
    assert len(transport.calls) == 1


# --- size and decoding -----------------------------------------------------------------------------------------------


def test_transport_size_rejection_is_oversize_and_not_retried():
    world = World()
    transport = FakeTransport(world, ResponseTooLarge("too big"), ok())
    error = expect_failure(make_fetcher(world, transport).fetch_list_page, LIST_URL, AcquisitionFailure.OVERSIZE)
    assert error.attempts == 1
    assert len(transport.calls) == 1


def test_body_larger_than_the_limit_is_oversize_even_if_the_transport_let_it_through():
    world = World()
    transport = FakeTransport(world, status(200, body=b"x" * (MAX_RESPONSE_BYTES + 1)))
    expect_failure(make_fetcher(world, transport).fetch_list_page, LIST_URL, AcquisitionFailure.OVERSIZE)


def test_200_that_is_not_utf8_is_a_non_retryable_decode_error():
    world = World()
    transport = FakeTransport(world, status(200, body=b"\xff\xfe\xfd"), ok())
    error = expect_failure(make_fetcher(world, transport).fetch_list_page, LIST_URL, AcquisitionFailure.DECODE_ERROR)
    assert error.attempts == 1
    assert error.status == 200
    assert len(transport.calls) == 1


def test_200_utf8_body_is_returned_as_text():
    world = World()
    transport = FakeTransport(world, status(200, body="繁體中文".encode()))
    assert make_fetcher(world, transport).fetch_list_page(LIST_URL) == "繁體中文"


def test_other_non_200_non_redirect_statuses_are_http_status_failures():
    world = World()
    transport = FakeTransport(world, status(204), ok())
    error = expect_failure(make_fetcher(world, transport).fetch_list_page, LIST_URL, AcquisitionFailure.HTTP_STATUS)
    assert error.status == 204
    assert len(transport.calls) == 1


# --- messages and logs -----------------------------------------------------------------------------------------------


def test_error_messages_never_contain_body_cookies_or_header_values():
    world = World()
    transport = FakeTransport(world, status(404, {"Set-Cookie": "sid=SECRET-COOKIE", "X-Debug": "SECRET-HEADER"}, body=b"SECRET-BODY"))
    error = expect_failure(make_fetcher(world, transport).fetch_list_page, LIST_URL, AcquisitionFailure.HTTP_STATUS)
    assert "SECRET" not in str(error)


def test_decode_error_message_does_not_echo_the_body():
    world = World()
    transport = FakeTransport(world, status(200, body=b"\xff SECRET-BODY"))
    error = expect_failure(make_fetcher(world, transport).fetch_list_page, LIST_URL, AcquisitionFailure.DECODE_ERROR)
    assert "SECRET" not in str(error)


def test_transport_exception_message_is_not_echoed():
    world = World()
    transport = FakeTransport(world, RuntimeError("SECRET-DETAIL"))
    error = expect_failure(make_fetcher(world, transport).fetch_list_page, LIST_URL, AcquisitionFailure.TRANSPORT)
    assert "SECRET" not in str(error)


def test_each_request_logs_one_info_line_and_each_retry_a_warning(caplog):
    world = World()
    transport = FakeTransport(world, status(503, body=b"abc"), ok())
    with caplog.at_level(logging.INFO, logger="kingstone.acquisition"):
        make_fetcher(world, transport).fetch_list_page(LIST_URL)
    infos = [r for r in caplog.records if r.name == "kingstone.acquisition" and r.levelno == logging.INFO]
    warnings = [r for r in caplog.records if r.name == "kingstone.acquisition" and r.levelno == logging.WARNING]
    assert [r.getMessage() for r in infos] == [
        f"GET {LIST_URL} status=503 bytes=3 attempt=1",
        f"GET {LIST_URL} status=200 bytes={len(OK_BODY.encode())} attempt=2",
    ]
    assert len(warnings) == 1


def test_close_closes_the_transport():
    world = World()
    transport = FakeTransport(world)
    make_fetcher(world, transport).close()
    assert transport.closed


# --- CurlTransport ---------------------------------------------------------------------------------------------------


class FakeCurlResponse:
    def __init__(self, status_code=200, headers=None, chunks=(b"<html>", b"ok</html>"), error_after=None):
        self.status_code = status_code
        self.headers = headers if headers is not None else {}
        self._chunks = list(chunks)
        self._error_after = error_after
        self.iterated = False
        self.closed = False

    def iter_content(self, *args, **kwargs):
        self.iterated = True
        for index, chunk in enumerate(self._chunks):
            if self._error_after is not None and index == self._error_after:
                raise self._error_after_exc
            yield chunk

    def close(self):
        self.closed = True


class FakeCurlSession:
    def __init__(self, response=None, error=None):
        self.response = response if response is not None else FakeCurlResponse()
        self.error = error
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return self.response

    def close(self):
        self.closed = True


def test_curl_transport_request_configuration():
    session = FakeCurlSession()
    transport = CurlTransport(session=session)
    response = transport.get(LIST_URL, timeout=30, max_bytes=MAX_RESPONSE_BYTES)
    assert response == RawResponse(200, {}, b"<html>ok</html>")
    url, kwargs = session.calls[0]
    assert url == LIST_URL
    assert kwargs == {
        "timeout": 30,
        "allow_redirects": False,
        "stream": True,
        "headers": {"Accept-Language": "zh-TW,zh;q=0.9"},
    }
    assert session.response.closed


def test_curl_transport_default_session_impersonates_chrome_and_verifies_tls(monkeypatch):
    created = []

    class RecordingSession(FakeCurlSession):
        def __init__(self, **kwargs):
            super().__init__()
            created.append(kwargs)

    monkeypatch.setattr(acquisition.curl_requests, "Session", RecordingSession)
    transport = CurlTransport()
    assert created == [{"impersonate": "chrome"}]
    transport.close()


def test_curl_transport_close_closes_the_session():
    session = FakeCurlSession()
    CurlTransport(session=session).close()
    assert session.closed


def test_curl_transport_rejects_declared_oversize_before_reading_the_body():
    response = FakeCurlResponse(headers={"content-length": str(MAX_RESPONSE_BYTES + 1)})
    transport = CurlTransport(session=FakeCurlSession(response=response))
    with pytest.raises(ResponseTooLarge):
        transport.get(LIST_URL, timeout=30, max_bytes=MAX_RESPONSE_BYTES)
    assert not response.iterated
    assert response.closed


def test_curl_transport_stops_streaming_when_the_body_exceeds_the_limit():
    response = FakeCurlResponse(chunks=[b"aaa", b"bbb", b"ccc"])
    transport = CurlTransport(session=FakeCurlSession(response=response))
    with pytest.raises(ResponseTooLarge):
        transport.get(LIST_URL, timeout=30, max_bytes=5)
    assert response.closed


def test_curl_transport_accepts_a_body_exactly_at_the_limit():
    response = FakeCurlResponse(chunks=[b"aaa", b"bb"])
    transport = CurlTransport(session=FakeCurlSession(response=response))
    assert transport.get(LIST_URL, timeout=30, max_bytes=5).body == b"aaabb"


@pytest.mark.parametrize("error", [curl_exceptions.ReadTimeout("t"), curl_exceptions.ConnectTimeout("t")])
def test_curl_timeouts_map_to_retryable_timeout(error):
    transport = CurlTransport(session=FakeCurlSession(error=error))
    with pytest.raises(TransportTimeout):
        transport.get(LIST_URL, timeout=30, max_bytes=MAX_RESPONSE_BYTES)


def test_curl_connection_errors_map_to_retryable_connection_error():
    transport = CurlTransport(session=FakeCurlSession(error=curl_exceptions.ConnectionError("c")))
    with pytest.raises(TransportConnectionError):
        transport.get(LIST_URL, timeout=30, max_bytes=MAX_RESPONSE_BYTES)


def test_curl_timeout_while_streaming_maps_to_retryable_timeout():
    response = FakeCurlResponse(chunks=[b"aa", b"bb"], error_after=1)
    response._error_after_exc = curl_exceptions.ReadTimeout("t")
    transport = CurlTransport(session=FakeCurlSession(response=response))
    with pytest.raises(TransportTimeout):
        transport.get(LIST_URL, timeout=30, max_bytes=MAX_RESPONSE_BYTES)
    assert response.closed


def test_curl_tls_failures_are_not_retried_and_propagate_unmapped():
    error = curl_exceptions.SSLError("tls")
    transport = CurlTransport(session=FakeCurlSession(error=error))
    with pytest.raises(curl_exceptions.SSLError):
        transport.get(LIST_URL, timeout=30, max_bytes=MAX_RESPONSE_BYTES)


def test_fetcher_treats_curl_tls_failure_as_a_non_retryable_transport_failure():
    world = World()
    transport = CurlTransport(session=FakeCurlSession(error=curl_exceptions.SSLError("tls")))
    fetcher = make_fetcher(world, transport)
    expect_failure(fetcher.fetch_list_page, LIST_URL, AcquisitionFailure.TRANSPORT)
    assert len(world.timeline) == 1  # one pacing wait, one attempt


@pytest.mark.parametrize("value", [None, 123, ["https://www.kingstone.com.tw/book/jdc/?dis=list&page=1"]])
def test_non_string_urls_are_rejected_without_a_request(value):
    world = World()
    transport = FakeTransport(world, ok())
    fetcher = make_fetcher(world, transport)
    with pytest.raises(ValueError):
        fetcher.fetch_list_page(value)
    with pytest.raises(ValueError):
        fetcher.fetch_detail_page(value)
    assert transport.calls == []
