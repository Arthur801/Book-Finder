"""Curl request pacing and failure handling, without connecting to books.com.tw."""

import json

import pytest
from curl_cffi import requests

from books_crawler.fetcher import CurlCffiFetcher, FetchError
from books_crawler.parsers import RestrictedBookError, parse_detail_html
from tests.fakes import RESTRICTED_GATE_FIXTURE, fixture_html, product_url


def _fetcher(**kwargs):
    kwargs.setdefault("sample_delay", lambda: 3.0)
    kwargs.setdefault("sleep", lambda seconds: None)
    return CurlCffiFetcher(**kwargs)


class FakeCurlResponse:
    def __init__(self, status=200, headers=None, html='<title>商品</title><div class="main_column"></div>'):
        self.status_code = status
        self.headers = headers or {}
        self.text = html
        self.content = html.encode()


class FakeCurlSession:
    def __init__(self, response=None, error=None):
        self.response = response or FakeCurlResponse()
        self.error = error
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response

    def close(self):
        self.closed = True


def test_request_configuration_and_close():
    session = FakeCurlSession()
    fetcher = _fetcher(session=session)
    assert fetcher.get("https://example.test") == session.response.text
    assert session.calls[0][1] == {"timeout": 30.0, "allow_redirects": False, "headers": {"Accept-Language": "zh-TW,zh;q=0.9"}}
    fetcher.close()
    assert session.closed


@pytest.mark.parametrize("failed_first", [False, True])
def test_random_delay_boundaries_include_first_request_and_failed_attempts(tmp_path, failed_first):
    current = [10.0]
    sleeps = []
    starts = []

    def sleep(seconds):
        sleeps.append(seconds)
        current[0] += seconds

    class TimedSession(FakeCurlSession):
        def get(self, url, **kwargs):
            starts.append(current[0])
            current[0] += 0.3
            return super().get(url, **kwargs)

    session = TimedSession(FakeCurlResponse(status=403 if failed_first else 200))
    delays = iter([3.0, 30.0, 3.0])
    fetcher = _fetcher(session=session, sleep=sleep, clock=lambda: current[0], sample_delay=lambda: next(delays), diagnostic_dir=tmp_path)
    if failed_first:
        with pytest.raises(FetchError):
            fetcher.get("https://example.test")
        session.response = FakeCurlResponse()
    else:
        fetcher.get("https://example.test")
    current[0] += 0.4  # DB / parsing time also counts toward the gap.
    fetcher.get("https://example.test")
    assert sleeps == pytest.approx([3.0, 29.6])
    assert starts[1] - starts[0] == pytest.approx(30.3)
    current[0] += 2.0  # Retry backoff already exceeds the minimum delay.
    fetcher.get("https://example.test")
    assert sleeps == pytest.approx([3.0, 29.6, 1.0])


@pytest.mark.parametrize(
    ("status", "headers", "message"),
    [
        (403, {"cf-mitigated": "challenge", "set-cookie": "secret"}, "Cloudflare challenge"),
        (200, {"cf-mitigated": "challenge"}, "Cloudflare challenge"),
        (484, {}, "HTTP 484"),
        (302, {"location": "/redirect"}, "HTTP 302"),
    ],
)
def test_failed_response_is_saved_and_wrapped(tmp_path, status, headers, message):
    fetcher = _fetcher(session=FakeCurlSession(FakeCurlResponse(status, headers)), diagnostic_dir=tmp_path)
    with pytest.raises(FetchError, match=message):
        fetcher.get("https://example.test")
    assert len(list(tmp_path.glob("*.html"))) == 1
    metadata = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert metadata["status"] == status
    assert "set-cookie" not in metadata["headers"]


def test_network_error_is_redacted_and_wrapped():
    session = FakeCurlSession(error=requests.RequestsError("connection failed password=secret"))
    with pytest.raises(FetchError) as error:
        _fetcher(session=session).get("https://example.test")
    assert "secret" not in str(error.value)


def test_diagnostic_failure_preserves_fetch_error(tmp_path):
    target = tmp_path / "not-a-directory"
    target.write_text("file")
    with pytest.raises(FetchError, match="HTTP 403"):
        _fetcher(session=FakeCurlSession(FakeCurlResponse(403)), diagnostic_dir=target).get("https://example.test")


def test_default_session_uses_chrome_preset(monkeypatch):
    seen = []
    monkeypatch.setattr(requests, "Session", lambda **kwargs: seen.append(kwargs) or FakeCurlSession())
    fetcher = _fetcher()
    fetcher.close()
    assert seen == [{"impersonate": "chrome"}]


def test_http_200_connection_error_page_is_not_a_product(tmp_path):
    html = "<h2>您的連線暫時異常 請稍後再嘗試 謝謝！</h2>"
    fetcher = _fetcher(session=FakeCurlSession(FakeCurlResponse(html=html)), diagnostic_dir=tmp_path)
    with pytest.raises(FetchError, match="website connection-error page"):
        fetcher.get("https://example.test")
    assert next(tmp_path.glob("*.html")).read_text() == html


def test_real_restricted_member_gate_reaches_the_parser_unchanged(tmp_path):
    # The real logged-out response is HTTP 200 and redirects to login with JavaScript, not with a 3xx.
    gate = fixture_html(RESTRICTED_GATE_FIXTURE)
    fetcher = _fetcher(session=FakeCurlSession(FakeCurlResponse(html=gate)), diagnostic_dir=tmp_path)

    html = fetcher.get(product_url(11063006))

    assert html == gate
    assert list(tmp_path.iterdir()) == []  # not a fetch failure, so no diagnostics are saved
    with pytest.raises(RestrictedBookError):
        parse_detail_html(html, product_url(11063006))


def test_connection_error_phrase_inside_real_content_does_not_block():
    html = '<div class="main_column">Connection is temporarily unavailable</div>'
    assert _fetcher(session=FakeCurlSession(FakeCurlResponse(html=html))).get("https://example.test") == html
