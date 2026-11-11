"""Eslite HTTP acquisition (eslite.acquisition): URL mapping, guards, pacing, retry and the 404 rule. Offline.

Every test uses a fake transport (or a fake curl session), a fake clock and a recording fake sleep. Nothing reaches
the network: the only URLs that appear are the www pages (never requested) and the athena API URLs (answered by fakes).
"""

from __future__ import annotations

import json
import logging
import math

import pytest

from catalog_core.http_acquisition import AcquisitionError, AcquisitionFailure, RawResponse, TransportTimeout, backoff_seconds
from eslite import acquisition
from eslite.acquisition import ESLITE_POLICY, MAX_PAGE_DELAY_SECONDS, MIN_PAGE_DELAY_SECONDS, EsliteFetcher
from eslite.urls import detail_api_url, guid_from_product_url, list_api_url, product_url

WWW_LIST = "https://www.eslite.com/category/3/101"
WWW_LIST_P2 = "https://www.eslite.com/category/3/101?page=2"
GUID = "1001136502682294792007"
WWW_PRODUCT = f"https://www.eslite.com/product/{GUID}"
DETAIL_API = f"https://athena.eslite.com/api/v4/products/{GUID}/description"
LIST_API = "https://athena.eslite.com/api/v1/categories/101/products?page_no=1&sort_type=date&sort_order=desc&page_size=40&is_available=true"
WALL_NOW = 1_700_000_000.0
OK_BODY = '{"total": 0, "page_no": 1, "page_size": 40, "products": []}'


class UnexpectedRequest(BaseException):
    """Raised by the fake transport when a test did not script enough responses (BaseException: not swallowed)."""


class World:
    """Fake clock plus a timeline of sleeps and transport calls, in the order they happened."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []
        self.timeline: list[tuple] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.timeline.append(("sleep", seconds))
        self.now += seconds

    def wall_clock(self) -> float:
        return WALL_NOW


class FakeTransport:
    """Answers scripted outcomes in order: a RawResponse, or an exception to raise. Records each call."""

    def __init__(self, world: World, *outcomes) -> None:
        self.world = world
        self.outcomes = list(outcomes)
        self.calls: list[str] = []
        self.closed = False

    def get(self, url, *, timeout, max_bytes):
        self.calls.append(url)
        self.world.timeline.append(("get", url))
        if not self.outcomes:
            raise UnexpectedRequest(url)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def close(self) -> None:
        self.closed = True


def ok(body: str = OK_BODY) -> RawResponse:
    return RawResponse(200, {"Content-Type": "application/json"}, body.encode("utf-8"))


def status(code: int, headers=None, body: bytes = b"") -> RawResponse:
    return RawResponse(code, headers or {}, body)


def make_fetcher(world: World, transport: FakeTransport, *, sample: float = 3.0, budget: float = math.inf) -> EsliteFetcher:
    return EsliteFetcher(
        transport=transport,
        sleep=world.sleep,
        clock=world.clock,
        wall_clock=world.wall_clock,
        sample_delay=lambda: sample,
        budget_remaining=lambda: budget,
    )


# --- guid_from_product_url (the inverse of eslite.urls.product_url, exact canonical form only) -------------------------


@pytest.mark.parametrize("guid", ["1001136502682294792007", "1001114412021700", "10012016112683201069007", "1" * 23])
def test_guid_from_product_url_inverts_product_url(guid):
    assert guid_from_product_url(product_url(guid)) == guid


@pytest.mark.parametrize(
    "raw",
    [
        "http://www.eslite.com/product/1001136502682294792007",  # scheme
        "https://eslite.com/product/1001136502682294792007",  # host without www
        "https://athena.eslite.com/product/1001136502682294792007",  # API host
        "https://www.eslite.com/product/1001136502682294792007/",  # trailing slash
        "https://www.eslite.com/product/1001136502682294792007?x=1",  # query
        "https://www.eslite.com/product/1001136502682294792007#top",  # fragment
        "https://www.eslite.com/product/12345678901234",  # 14 digits: too short
        "https://www.eslite.com/product/123456789012345678901234",  # 24 digits: too long
        "https://www.eslite.com/product/1001136502682294792a",  # not digits
        "https://www.eslite.com/product/",  # no guid
        "https://www.eslite.com/category/3/101",  # a list page
        f"https://athena.eslite.com/api/v4/products/{GUID}/description",  # a detail API URL
        "",
    ],
)
def test_guid_from_product_url_rejects_everything_but_the_canonical_form(raw):
    assert guid_from_product_url(raw) is None


def test_guid_from_product_url_rejects_non_strings():
    assert guid_from_product_url(None) is None  # type: ignore[arg-type]
    assert guid_from_product_url(123) is None  # type: ignore[arg-type]


# --- constants and the policy ---------------------------------------------------------------------------------------


def test_policy_constants_are_the_contract_values():
    assert ESLITE_POLICY.site_host == "athena.eslite.com"
    assert (MIN_PAGE_DELAY_SECONDS, MAX_PAGE_DELAY_SECONDS) == (3, 10)
    assert (ESLITE_POLICY.min_delay_seconds, ESLITE_POLICY.max_delay_seconds) == (3, 10)
    assert dict(ESLITE_POLICY.request_headers) == {"Accept": "application/json", "Accept-Language": "zh-TW,zh;q=0.9"}
    assert ESLITE_POLICY.logger_name == "eslite.acquisition"
    assert "Eslite" in ESLITE_POLICY.list_rejected and "Eslite" in ESLITE_POLICY.detail_rejected


def test_the_policy_predicates_accept_only_the_api_shapes():
    assert ESLITE_POLICY.is_list_url(LIST_API)
    assert not ESLITE_POLICY.is_list_url(WWW_LIST)
    assert ESLITE_POLICY.is_detail_url(DETAIL_API)
    assert not ESLITE_POLICY.is_detail_url(WWW_PRODUCT)


def test_the_module_exposes_the_fetcher_and_the_engine_error_types():
    assert acquisition.EsliteFetcher is EsliteFetcher
    assert acquisition.AcquisitionError is AcquisitionError


# --- URL mapping ----------------------------------------------------------------------------------------------------


def test_a_canonical_list_page_is_requested_as_its_list_api_url():
    world = World()
    transport = FakeTransport(world, ok())

    body = make_fetcher(world, transport).fetch_list_page(WWW_LIST)

    assert body == OK_BODY
    assert transport.calls == [list_api_url(WWW_LIST)] == [LIST_API]


def test_page_two_maps_to_page_no_two():
    world = World()
    transport = FakeTransport(world, ok())

    make_fetcher(world, transport).fetch_list_page(WWW_LIST_P2)

    assert transport.calls == [list_api_url(WWW_LIST_P2)]
    assert "page_no=2" in transport.calls[0]


def test_a_product_page_url_is_requested_as_its_detail_api_url():
    world = World()
    transport = FakeTransport(world, ok(json.dumps({"product_guid": GUID})))

    make_fetcher(world, transport).fetch_detail_page(WWW_PRODUCT)

    assert transport.calls == [DETAIL_API] == [detail_api_url(GUID)]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.eslite.com/category/3/101?page=1",  # page 1 must be written without the query
        "https://www.eslite.com/category/3/101/",  # trailing slash
        "https://www.eslite.com/category/3/0101",  # leading zero
        "https://www.eslite.com/category/2/28",  # level 2
        "https://www.eslite.com/category/3/101?sort=date",  # foreign query key
        "http://www.eslite.com/category/3/101",  # scheme
        "https://eslite.com/category/3/101",  # host without www
        LIST_API,  # an API URL is not a web list page
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1",  # other site
        "",
    ],
)
def test_a_non_canonical_list_url_is_refused_before_any_request(url):
    world = World()
    transport = FakeTransport(world)

    with pytest.raises(ValueError):
        make_fetcher(world, transport).fetch_list_page(url)

    assert transport.calls == []
    assert world.sleeps == []


@pytest.mark.parametrize(
    "url",
    [
        DETAIL_API,  # an API URL is not a product page
        "https://www.eslite.com/product/1001136502682294792007/",  # trailing slash
        "https://www.eslite.com/product/12345",  # not a guid
        "https://www.eslite.com/category/3/101",  # a list page
        "https://www.eslite.com/product/1001136502682294792007?x=1",  # query
        "https://www.kingstone.com.tw/basic/2018630959191/",  # other site
        "http://www.eslite.com/product/1001136502682294792007",  # scheme
    ],
)
def test_a_non_canonical_product_url_is_refused_before_any_request(url):
    world = World()
    transport = FakeTransport(world)

    with pytest.raises(ValueError):
        make_fetcher(world, transport).fetch_detail_page(url)

    assert transport.calls == []


@pytest.mark.parametrize("url", [LIST_API, DETAIL_API, "https://athena.eslite.com/api/v1/categories"])
def test_an_athena_url_passed_as_a_list_page_is_refused_without_a_request(url):
    world = World()
    transport = FakeTransport(world)

    with pytest.raises(ValueError):
        make_fetcher(world, transport).fetch_list_page(url)

    assert transport.calls == []


@pytest.mark.parametrize("url", [WWW_LIST, "https://athena.eslite.com/api/v1/categories/101/products", "https://evil.example/product/1"])
def test_a_non_product_url_passed_as_a_detail_page_is_refused_without_a_request(url):
    world = World()
    transport = FakeTransport(world)

    with pytest.raises(ValueError):
        make_fetcher(world, transport).fetch_detail_page(url)

    assert transport.calls == []


def test_the_refusal_message_names_eslite():
    world = World()
    with pytest.raises(ValueError, match="Eslite"):
        make_fetcher(world, FakeTransport(world)).fetch_list_page("https://www.kingstone.com.tw/x")


def test_a_non_string_url_is_refused_without_a_request():
    world = World()
    transport = FakeTransport(world)

    with pytest.raises(ValueError):
        make_fetcher(world, transport).fetch_list_page(None)  # type: ignore[arg-type]

    assert transport.calls == []


# --- pacing ---------------------------------------------------------------------------------------------------------


def test_the_default_pacing_samples_between_3_and_10_seconds_before_each_request():
    seen = []
    for _ in range(200):
        world = World()
        transport = FakeTransport(world, ok())
        fetcher = EsliteFetcher(transport=transport, sleep=world.sleep, clock=world.clock, wall_clock=world.wall_clock)
        fetcher.fetch_list_page(WWW_LIST)
        seen.append(world.sleeps[0])

    assert all(MIN_PAGE_DELAY_SECONDS <= value <= MAX_PAGE_DELAY_SECONDS for value in seen)
    assert len(set(seen)) > 1  # a uniform draw, not a constant


def test_each_request_waits_the_sampled_delay_before_it_is_sent():
    world = World()
    transport = FakeTransport(world, ok(), ok())
    fetcher = make_fetcher(world, transport, sample=4.5)

    fetcher.fetch_list_page(WWW_LIST)
    fetcher.fetch_detail_page(WWW_PRODUCT)

    assert transport.calls == [LIST_API, DETAIL_API]
    assert world.timeline[0] == ("sleep", 4.5)
    assert world.timeline[1][0] == "get"


# --- headers ---------------------------------------------------------------------------------------------------------


class FakeCurlResponse:
    def __init__(self) -> None:
        self.status_code = 200
        self.headers: dict[str, str] = {}
        self.closed = False

    def iter_content(self, *args, **kwargs):
        yield OK_BODY.encode("utf-8")

    def close(self) -> None:
        self.closed = True


class FakeCurlSession:
    def __init__(self, *args, **kwargs) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeCurlResponse()

    def close(self) -> None:
        self.closed = True


def test_the_default_transport_sends_the_eslite_request_headers(monkeypatch):
    sessions: list[FakeCurlSession] = []

    def make_session(*args, **kwargs):
        session = FakeCurlSession()
        sessions.append(session)
        return session

    monkeypatch.setattr(acquisition.curl_requests, "Session", make_session)
    world = World()
    fetcher = EsliteFetcher(sleep=world.sleep, clock=world.clock, wall_clock=world.wall_clock, sample_delay=lambda: 3.0)
    try:
        fetcher.fetch_list_page(WWW_LIST)
    finally:
        fetcher.close()

    ((url, kwargs),) = sessions[0].calls
    assert url == LIST_API
    assert kwargs["headers"] == {"Accept": "application/json", "Accept-Language": "zh-TW,zh;q=0.9"}
    assert kwargs["allow_redirects"] is False
    assert sessions[0].closed


# --- counters, close and response classification -------------------------------------------------------------------


def test_counters_and_close_are_delegated_to_the_engine():
    world = World()
    transport = FakeTransport(world, status(503), ok())
    fetcher = make_fetcher(world, transport)

    fetcher.fetch_list_page(WWW_LIST)
    assert fetcher.http_attempts == 2
    assert fetcher.http_failures == 1

    fetcher.close()
    assert transport.closed


def test_a_detail_404_is_http_status_404_not_retried_and_keeps_no_body():
    world = World()
    transport = FakeTransport(world, status(404, body=b'{"message": "Product not found", "code": "404"}'))
    fetcher = make_fetcher(world, transport)

    with pytest.raises(AcquisitionError) as info:
        fetcher.fetch_detail_page(WWW_PRODUCT)

    assert info.value.kind is AcquisitionFailure.HTTP_STATUS
    assert info.value.status == 404
    assert info.value.attempts == 1
    assert transport.calls == [DETAIL_API]  # not retried
    assert world.sleeps == [3.0]  # only the pacing wait before the one request
    assert fetcher.http_attempts == 1
    assert fetcher.http_failures == 1


def test_a_503_list_response_is_retried_with_backoff_and_then_succeeds():
    world = World()
    transport = FakeTransport(world, status(503), ok())
    fetcher = make_fetcher(world, transport)

    assert fetcher.fetch_list_page(WWW_LIST) == OK_BODY

    assert transport.calls == [LIST_API, LIST_API]
    assert world.sleeps == [3.0, backoff_seconds(2)]  # pacing, then the shared engine backoff (5 s) before the retry


def test_timeouts_are_retried_up_to_the_attempt_limit_then_fail():
    world = World()
    transport = FakeTransport(world, TransportTimeout("t1"), TransportTimeout("t2"), TransportTimeout("t3"))
    fetcher = make_fetcher(world, transport)

    with pytest.raises(AcquisitionError) as info:
        fetcher.fetch_list_page(WWW_LIST)

    assert info.value.kind is AcquisitionFailure.TRANSPORT
    assert info.value.attempts == 3
    assert len(transport.calls) == 3


def test_a_redirect_is_not_followed():
    world = World()
    transport = FakeTransport(world, status(302, headers={"Location": "https://athena.eslite.com/elsewhere"}))

    with pytest.raises(AcquisitionError) as info:
        make_fetcher(world, transport).fetch_list_page(WWW_LIST)

    assert info.value.kind is AcquisitionFailure.REDIRECT
    assert transport.calls == [LIST_API]


def test_the_budget_refusal_is_raised_before_any_request():
    world = World()
    transport = FakeTransport(world)

    with pytest.raises(AcquisitionError) as info:
        make_fetcher(world, transport, budget=0.0).fetch_list_page(WWW_LIST)

    assert info.value.kind is AcquisitionFailure.BUDGET_EXHAUSTED
    assert transport.calls == []


def test_the_fetcher_logs_its_requests_on_the_eslite_acquisition_logger(caplog):
    caplog.set_level(logging.INFO, logger="eslite.acquisition")
    world = World()
    make_fetcher(world, FakeTransport(world, ok())).fetch_list_page(WWW_LIST)

    assert any(record.name == "eslite.acquisition" and LIST_API in record.getMessage() for record in caplog.records)
