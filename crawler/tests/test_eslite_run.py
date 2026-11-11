"""Eslite page-by-page run (eslite.run), offline: fake fetcher keyed by the www URLs, in-memory store, fake clock and sleep.

The bodies are the real JSON fixtures under ``tests/fixtures/eslite/``. A list page is the real list response with its
product cards replaced by the guids the test needs (the parser reads only ``guid``). No network, no database.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from catalog_core.category_ledger import RunStatus
from catalog_core.category_run import CategoryAdapter
from catalog_core.http_acquisition import AcquisitionError, AcquisitionFailure
from catalog_core.identity import IdentityKind, SourceIdentity
from catalog_core.models import ProviderCode, SourceRef, WritePolicy
from eslite.run import ESLITE_ADAPTER, EsliteRunDependencies, SoftBudget, run_pages

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "eslite"
NOW = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)

LIST_101 = "https://www.eslite.com/category/3/101"
LIST_101_P2 = "https://www.eslite.com/category/3/101?page=2"
LIST_101_P6 = "https://www.eslite.com/category/3/101?page=6"
LIST_34 = "https://www.eslite.com/category/3/34"
LIST_EMPTY = "https://www.eslite.com/category/3/9999999"

G_DICTIONARY = "10012016112683201069007"  # detail fixture: no isbn13, ean used
G_16 = "1001114412021700"  # 16 digit guid, detail fixture
G_TRANSLATION_ISBN = "1001136502682294792007"  # detail fixture with isbn13 9789888773701
G_SERIES = "1001124912682006780001"  # detail fixture with 目錄
G_NOVEL = "10012030392683263913003"  # detail fixture: translated novel (list_34)
G_NOT_FOUND = "10019999999999999999999"  # detail API answers 404 for it
REAL_GUIDS = [G_DICTIONARY, G_16, G_TRANSLATION_ISBN, G_SERIES, G_NOVEL]
DETAIL_FIXTURES = {
    G_DICTIONARY: "detail_10012016112683201069007.json",
    G_16: "detail_1001114412021700.json",
    G_TRANSLATION_ISBN: "detail_1001136502682294792007.json",
    G_SERIES: "detail_1001124912682006780001.json",
    G_NOVEL: "detail_10012030392683263913003.json",
}


def fixture_text(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def list_body(guids: Sequence[str], *, page: int = 1, total: int = 188) -> str:
    """A list response with one card per guid: the real card shape (from list_101_p1.json) with the guid replaced."""
    card = json.loads(fixture_text("list_101_p1.json"))["products"][0]
    products = [{**card, "guid": guid} for guid in guids]
    return json.dumps({"total": total, "page_no": page, "page_size": 40, "products": products}, ensure_ascii=False)


def detail_body(guid: str) -> str:
    return fixture_text(DETAIL_FIXTURES[guid])


def product(guid: str) -> str:
    return f"https://www.eslite.com/product/{guid}"


class FakeClock:
    """A monotonic clock the test moves by hand (the budget reads it)."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class FakeFetcher:
    """URL -> response. A value is a body or an exception; a list is consumed in order, its last item repeats."""

    def __init__(self, responses: dict[str, object]) -> None:
        self._responses = dict(responses)
        self.calls: list[str] = []
        self.failures = 0
        self.closed = 0

    @property
    def http_attempts(self) -> int:
        return len(self.calls)

    @property
    def http_failures(self) -> int:
        return self.failures

    def fetch_list_page(self, url: str) -> str:
        return self._get(url)

    def fetch_detail_page(self, url: str) -> str:
        return self._get(url)

    def _get(self, url: str) -> str:
        self.calls.append(url)
        if url not in self._responses:
            raise AssertionError(f"unexpected request: {url}")
        value = self._responses[url]
        if isinstance(value, list):
            value = value.pop(0) if len(value) > 1 else value[0]
        if isinstance(value, BaseException):
            raise value
        return value

    def detail_calls(self) -> list[str]:
        return [url for url in self.calls if url.startswith("https://www.eslite.com/product/")]

    def close(self) -> None:
        self.closed += 1


class MemoryStore:
    """In-memory CatalogStore. Identity is by external_id. Records the provider of every write."""

    def __init__(self) -> None:
        self.refs: dict[str, SourceRef] = {}
        self.persisted: list[tuple[ProviderCode, str]] = []
        self.touched: list[uuid.UUID] = []
        self.isbn_matches: dict[str, list[uuid.UUID]] = {}

    def resolve_source_identity(self, provider: ProviderCode, source_url: str, external_id: str | None) -> SourceIdentity:
        if external_id in self.refs:
            return SourceIdentity(IdentityKind.EXISTING, ref=self.refs[external_id])
        return SourceIdentity(IdentityKind.NEW)

    def touch_source(self, provider: ProviderCode, source_id: uuid.UUID, observed_at: datetime) -> bool:
        self.touched.append(source_id)
        return True

    def find_books_by_isbn(self, values: Sequence[str]) -> list[uuid.UUID]:
        found: list[uuid.UUID] = []
        for value in values:
            found.extend(self.isbn_matches.get(value, []))
        return list(dict.fromkeys(found))

    def persist_new_source(self, provider: ProviderCode, draft, now: datetime, attach_to_book_id):
        ref = SourceRef(source_id=uuid.uuid4(), book_id=attach_to_book_id or uuid.uuid4())
        self.refs[draft.external_id] = ref
        self.persisted.append((provider, draft.external_id))
        return ref


def make_deps(
    fetcher: FakeFetcher,
    store: MemoryStore,
    *,
    budget: SoftBudget | None = None,
    sleeps: list[float] | None = None,
    write_policy: WritePolicy = WritePolicy.NORMAL,
) -> EsliteRunDependencies:
    return EsliteRunDependencies(
        fetcher=fetcher,
        store=store,
        budget=budget if budget is not None else SoftBudget(10_000, FakeClock()),
        clock=lambda: NOW,
        sleep=(sleeps if sleeps is not None else []).append,
        write_policy=write_policy,
    )


def not_found() -> AcquisitionError:
    return AcquisitionError(AcquisitionFailure.HTTP_STATUS, "GET detail failed: http_status 404", 1, 404)


def full_site() -> dict[str, object]:
    """Two list pages, every real detail fixture, and the 404 product on the second page."""
    return {
        LIST_101: list_body([G_DICTIONARY, G_16, G_TRANSLATION_ISBN]),
        LIST_34: list_body([G_NOVEL], total=1333),
        product(G_DICTIONARY): detail_body(G_DICTIONARY),
        product(G_16): detail_body(G_16),
        product(G_TRANSLATION_ISBN): detail_body(G_TRANSLATION_ISBN),
        product(G_NOVEL): detail_body(G_NOVEL),
    }


# ---------------------------------------------------------------------------
# The adapter binding
# ---------------------------------------------------------------------------


def test_the_adapter_binds_the_eslite_names_and_modes():
    assert isinstance(ESLITE_ADAPTER, CategoryAdapter)
    assert ESLITE_ADAPTER.provider is ProviderCode.ESLITE
    assert ESLITE_ADAPTER.mode == "eslite"
    assert ESLITE_ADAPTER.run_logger_name == "eslite.run"
    assert ESLITE_ADAPTER.ledger_logger_name == "eslite.ledger"


# ---------------------------------------------------------------------------
# Full flow, provider, replay and the terminal status
# ---------------------------------------------------------------------------


def test_full_run_imports_every_new_card_under_the_eslite_provider(caplog):
    caplog.set_level(logging.INFO)
    fetcher = FakeFetcher(full_site())
    store = MemoryStore()

    report = run_pages(make_deps(fetcher, store), [LIST_101, LIST_34], run_id="run-1")

    assert report.status is RunStatus.SUCCESS
    assert report.error is None
    assert report.provider_code is ProviderCode.ESLITE
    assert (report.pages_listed, report.pages_completed) == (2, 2)
    assert (report.items_seen, report.imported, report.failed, report.existing_source) == (4, 4, 0, 0)
    assert fetcher.detail_calls() == [product(G_DICTIONARY), product(G_16), product(G_TRANSLATION_ISBN), product(G_NOVEL)]
    assert store.persisted == [(ProviderCode.ESLITE, guid) for guid in (G_DICTIONARY, G_16, G_TRANSLATION_ISBN, G_NOVEL)]
    assert report.run_id == "run-1"
    messages = [record.getMessage() for record in caplog.records]
    assert any(message.startswith("mode=eslite ") and "status=SUCCESS" in message for message in messages)
    assert any(record.name == "eslite.run" for record in caplog.records)


def test_replay_touches_existing_cards_without_any_detail_request():
    store = MemoryStore()
    run_pages(make_deps(FakeFetcher(full_site()), store), [LIST_101, LIST_34])

    replay = FakeFetcher(full_site())
    report = run_pages(make_deps(replay, store), [LIST_101, LIST_34])

    assert report.status is RunStatus.SUCCESS
    assert replay.detail_calls() == []
    assert report.existing_source == 4
    assert report.imported == 0
    assert len(store.touched) == 4


def test_a_listed_page_twice_is_run_once():
    fetcher = FakeFetcher(full_site())

    report = run_pages(make_deps(fetcher, MemoryStore()), [LIST_101, LIST_101])

    assert report.pages_listed == 1
    assert fetcher.calls.count(LIST_101) == 1


def test_the_list_pages_run_in_list_order():
    fetcher = FakeFetcher(full_site())

    run_pages(make_deps(fetcher, MemoryStore()), [LIST_34, LIST_101])

    assert [url for url in fetcher.calls if url.startswith("https://www.eslite.com/category/")] == [LIST_34, LIST_101]


# ---------------------------------------------------------------------------
# Category pages: the empty category, a page beyond the end, parse and HTTP failures
# ---------------------------------------------------------------------------


def test_a_first_page_with_total_zero_is_skipped_with_reason_empty_category():
    fetcher = FakeFetcher({LIST_EMPTY: fixture_text("list_9999999_p1.json"), LIST_34: list_body([G_NOVEL], total=1333), product(G_NOVEL): detail_body(G_NOVEL)})

    report = run_pages(make_deps(fetcher, MemoryStore()), [LIST_EMPTY, LIST_34])

    assert [(page.url, page.reason, page.attempts) for page in report.pages_skipped] == [(LIST_EMPTY, "empty_category", 1)]
    assert report.pages_completed == 1
    assert report.imported == 1
    assert report.status is RunStatus.PARTIAL_SUCCESS


def test_a_page_beyond_the_last_is_a_completed_zero_card_page():
    fetcher = FakeFetcher({LIST_101_P6: fixture_text("list_101_p6.json")})

    report = run_pages(make_deps(fetcher, MemoryStore()), [LIST_101_P6])

    assert report.pages_skipped == ()
    assert report.pages_completed == 1
    assert report.zero_card_pages == 1
    assert report.items_seen == 0
    assert report.status is RunStatus.SUCCESS


def test_a_list_page_that_is_not_json_is_skipped_with_reason_parse_error_and_the_run_goes_on():
    fetcher = FakeFetcher({LIST_101: "<html>Vue shell</html>", LIST_34: list_body([G_NOVEL], total=1333), product(G_NOVEL): detail_body(G_NOVEL)})

    report = run_pages(make_deps(fetcher, MemoryStore()), [LIST_101, LIST_34])

    assert [(page.url, page.reason) for page in report.pages_skipped] == [(LIST_101, "parse_error")]
    assert report.pages_completed == 1
    assert report.imported == 1


def test_a_list_page_with_a_mismatched_page_number_is_a_parse_error():
    fetcher = FakeFetcher({LIST_101_P2: list_body([G_NOVEL], page=1)})

    report = run_pages(make_deps(fetcher, MemoryStore()), [LIST_101_P2])

    assert [(page.url, page.reason) for page in report.pages_skipped] == [(LIST_101_P2, "parse_error")]


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        (AcquisitionFailure.HTTP_STATUS, "http_status"),
        (AcquisitionFailure.TRANSPORT, "transport"),
        (AcquisitionFailure.REDIRECT, "redirect"),
    ],
)
def test_a_list_fetch_failure_skips_that_page_with_the_acquisition_reason(kind, reason):
    fetcher = FakeFetcher(
        {LIST_101: AcquisitionError(kind, "GET failed", 3, 503), LIST_34: list_body([G_NOVEL], total=1333), product(G_NOVEL): detail_body(G_NOVEL)}
    )

    report = run_pages(make_deps(fetcher, MemoryStore()), [LIST_101, LIST_34])

    assert [(page.reason, page.attempts) for page in report.pages_skipped] == [(reason, 3)]
    assert report.pages_completed == 1


def test_a_run_whose_budget_is_already_spent_makes_no_request():
    fetcher = FakeFetcher(full_site())

    report = run_pages(make_deps(fetcher, MemoryStore(), budget=SoftBudget(0, FakeClock())), [LIST_101, LIST_34])

    assert fetcher.calls == []
    assert report.budget_exhausted is True
    assert report.pages_not_reached == 2


# ---------------------------------------------------------------------------
# Cards: the detail 404 and other card failures
# ---------------------------------------------------------------------------


def test_a_detail_404_fails_that_card_with_http_status_and_writes_nothing():
    fetcher = FakeFetcher(
        {
            LIST_101: list_body([G_DICTIONARY, G_NOT_FOUND]),
            product(G_DICTIONARY): detail_body(G_DICTIONARY),
            product(G_NOT_FOUND): not_found(),
        }
    )
    store = MemoryStore()

    report = run_pages(make_deps(fetcher, store), [LIST_101])

    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.pages_completed == 1
    assert (report.imported, report.failed) == (1, 1)
    assert [(item.external_id, item.reason, item.attempts) for item in report.failed_items] == [(G_NOT_FOUND, "http_status", 1)]
    assert fetcher.calls.count(product(G_NOT_FOUND)) == 1  # not retried by the run
    assert [guid for _, guid in store.persisted] == [G_DICTIONARY]  # nothing written for the 404 product


def test_a_card_already_in_the_store_is_touched_and_its_detail_is_never_requested():
    store = MemoryStore()
    store.refs[G_DICTIONARY] = SourceRef(source_id=uuid.uuid4(), book_id=uuid.uuid4())
    fetcher = FakeFetcher({LIST_101: list_body([G_DICTIONARY])})

    report = run_pages(make_deps(fetcher, store), [LIST_101])

    assert report.existing_source == 1
    assert fetcher.detail_calls() == []
    assert len(store.touched) == 1


def test_the_card_is_fetched_from_its_product_url_and_the_list_from_its_category_url():
    fetcher = FakeFetcher({LIST_101: list_body([G_DICTIONARY]), product(G_DICTIONARY): detail_body(G_DICTIONARY)})

    run_pages(make_deps(fetcher, MemoryStore()), [LIST_101])

    assert fetcher.calls == [LIST_101, product(G_DICTIONARY)]


def test_the_run_and_the_ledger_log_on_the_eslite_loggers(caplog):
    caplog.set_level(logging.INFO)
    fetcher = FakeFetcher(
        {
            LIST_EMPTY: fixture_text("list_9999999_p1.json"),
            LIST_101: list_body([G_DICTIONARY, G_NOT_FOUND]),
            product(G_DICTIONARY): detail_body(G_DICTIONARY),
            product(G_NOT_FOUND): not_found(),
        }
    )

    run_pages(make_deps(fetcher, MemoryStore()), [LIST_EMPTY, LIST_101])

    names = {record.name for record in caplog.records}
    assert {"eslite.run", "eslite.ledger"} <= names  # the skipped page is a ledger warning
    assert not {name for name in names if name.startswith("kingstone")}
