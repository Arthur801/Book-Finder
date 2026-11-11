"""The provider-neutral category run (catalog_core.category_run) with a non-Kingstone fake adapter.

The adapter is ESLITE in name only: provider ``ProviderCode.ESLITE``, mode ``fake``, loggers ``fake.run`` and
``fake.ledger``, its own parse errors and a custom ``list_skip_reason``. It shows that the run takes everything
provider-specific from the adapter and nothing from Kingstone. Offline: fake fetcher, in-memory store, fake clock.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from catalog_core.category_ledger import PARSE_ERROR_REASON, CategoryReport, RunStatus
from catalog_core.category_run import CategoryAdapter, CategoryRunDependencies, SoftBudget, run_category_pages
from catalog_core.http_acquisition import AcquisitionError, AcquisitionFailure
from catalog_core.identity import IdentityKind, SourceIdentity
from catalog_core.models import BookDraft, ListedItem, ListPage, ProviderCode, SourceRef, WritePolicy

NOW = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)
LIST_A = "https://fake.test/list/a"
LIST_B = "https://fake.test/list/b"


def item_url(code: str) -> str:
    return f"https://fake.test/item/{code}"


class FakeParseError(ValueError):
    """The fake provider's parse error."""


class FakeNotFound(Exception):
    """The fake provider's soft 404."""


class FakeEmptyCategory(FakeParseError):
    """A list page that is an empty category: its skip reason is decided by the adapter, not by the run."""


def fake_parse_list(text: str, url: str) -> ListPage:
    if text == "bad":
        raise FakeParseError("bad list page")
    if text == "empty":
        raise FakeEmptyCategory("no products in this category")
    codes = [code for code in text.split(",") if code]
    items = tuple(ListedItem(external_id=code, source_url=item_url(code), list_url=url) for code in codes)
    return ListPage(url=url, items=items, total_pages=None, total_count=None, empty=not items)


@dataclass
class FakeProvider:
    """Records what the run asked of the adapter's detail parser and the store."""

    detail_calls: list[ListedItem] = field(default_factory=list)

    def parse_detail(self, text: str, item: ListedItem) -> BookDraft:
        self.detail_calls.append(item)
        if text == "soft404":
            raise FakeNotFound(item.source_url)
        if text == "bad":
            raise FakeParseError(f"bad detail {item.external_id}")
        return BookDraft(source_url=item.source_url, title=f"Book {item.external_id}", external_id=item.external_id)

    def adapter(self) -> CategoryAdapter:
        return CategoryAdapter(
            provider=ProviderCode.ESLITE,
            mode="fake",
            run_logger_name="fake.run",
            ledger_logger_name="fake.ledger",
            parse_list=fake_parse_list,
            parse_detail=self.parse_detail,
            parse_error=FakeParseError,
            not_found=FakeNotFound,
            list_page_code=lambda url: url.rsplit("/", 1)[-1],
            list_skip_reason=lambda exc: "empty_category" if isinstance(exc, FakeEmptyCategory) else PARSE_ERROR_REASON,
        )


class FakeFetcher:
    def __init__(self, responses: dict[str, object]) -> None:
        self._responses = dict(responses)
        self.calls: list[str] = []

    @property
    def http_attempts(self) -> int:
        return len(self.calls)

    @property
    def http_failures(self) -> int:
        return 0

    def fetch_list_page(self, url: str) -> str:
        return self._get(url)

    def fetch_detail_page(self, url: str) -> str:
        return self._get(url)

    def _get(self, url: str) -> str:
        self.calls.append(url)
        value = self._responses[url]
        if isinstance(value, BaseException):
            raise value
        return value


class FakeStore:
    def __init__(self) -> None:
        self.providers: list[ProviderCode] = []
        self.persisted: list[BookDraft] = []
        self.faults: list[BaseException] = []

    def resolve_source_identity(self, provider: ProviderCode, source_url: str, external_id: str | None) -> SourceIdentity:
        if self.faults:
            raise self.faults.pop(0)
        return SourceIdentity(IdentityKind.NEW)

    def touch_source(self, provider: ProviderCode, source_id: uuid.UUID, observed_at: datetime) -> bool:
        return True

    def find_books_by_isbn(self, values: Sequence[str]) -> list[uuid.UUID]:
        return []

    def persist_new_source(self, provider: ProviderCode, draft: BookDraft, now: datetime, attach_to_book_id):
        self.providers.append(provider)
        self.persisted.append(draft)
        return SourceRef(source_id=uuid.uuid4(), book_id=uuid.uuid4())


@dataclass
class FakeSink:
    saved: list[tuple[str, str, str]] = field(default_factory=list)

    def save_html(self, *, kind: str, code: str, html: str) -> None:
        self.saved.append((kind, code, html))


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def make_deps(
    fetcher: FakeFetcher,
    store: FakeStore,
    *,
    diagnostics: FakeSink | None = None,
    budget: SoftBudget | None = None,
) -> CategoryRunDependencies:
    return CategoryRunDependencies(
        fetcher=fetcher,
        store=store,
        budget=budget if budget is not None else SoftBudget(10_000, FakeClock()),
        clock=lambda: NOW,
        sleep=lambda seconds: None,
        write_policy=WritePolicy.NORMAL,
        diagnostics=diagnostics,
    )


def run(fetcher: FakeFetcher, store: FakeStore, provider: FakeProvider, page_urls: Sequence[str], **kwargs):
    return run_category_pages(provider.adapter(), make_deps(fetcher, store, **kwargs), page_urls, run_id="fake-run")


def test_the_report_and_the_catalog_items_carry_the_adapter_provider():
    provider = FakeProvider()
    store = FakeStore()
    report = run(FakeFetcher({LIST_A: "K1,K2", item_url("K1"): "ok", item_url("K2"): "ok"}), store, provider, [LIST_A])

    assert report.provider_code is ProviderCode.ESLITE
    assert report.status is RunStatus.SUCCESS
    assert report.imported == 2
    assert store.providers == [ProviderCode.ESLITE, ProviderCode.ESLITE]
    assert [draft.external_id for draft in store.persisted] == ["K1", "K2"]
    assert type(report) is CategoryReport


def test_log_records_go_to_the_adapter_loggers(caplog):
    caplog.set_level(logging.INFO)
    provider = FakeProvider()
    fetcher = FakeFetcher(
        {LIST_A: "K1,K2", item_url("K1"): "bad", item_url("K2"): "ok", LIST_B: AcquisitionError(AcquisitionFailure.HTTP_STATUS, "GET failed", 3, 503)}
    )

    run(fetcher, FakeStore(), provider, [LIST_A, LIST_B])

    fake_records = [record for record in caplog.records if record.name.startswith("fake.")]
    assert {record.name for record in fake_records} == {"fake.run", "fake.ledger"}
    assert [record.name for record in caplog.records if record.name.startswith("kingstone")] == []
    run_info = [record.getMessage() for record in fake_records if record.name == "fake.run" and record.levelno == logging.INFO]
    assert len(run_info) == 1 and run_info[0].startswith("mode=fake run_id=fake-run provider_code=ESLITE ")
    ledger_warnings = [record.getMessage() for record in fake_records if record.name == "fake.ledger" and record.levelno == logging.WARNING]
    assert any(message.startswith(f"{LIST_A} item failed after 1 attempt(s) (parse_error): {item_url('K1')}: ") for message in ledger_warnings)
    assert any(message.startswith(f"page skipped after 3 attempt(s) (http_status): {LIST_B}") for message in ledger_warnings)


def test_a_fatal_error_is_logged_as_a_mode_run_failure_on_the_run_logger(caplog):
    caplog.set_level(logging.ERROR)
    store = FakeStore()
    store.faults = [RuntimeError("boom")]

    report = run(FakeFetcher({LIST_A: "K1", item_url("K1"): "ok"}), store, FakeProvider(), [LIST_A])

    assert report.status is RunStatus.FAILED
    assert report.error == "RuntimeError: boom"
    errors = [(record.name, record.getMessage()) for record in caplog.records if record.levelno == logging.ERROR]
    assert errors == [("fake.run", "fake run failed: RuntimeError: boom")]


def test_the_list_skip_reason_of_the_adapter_decides_the_skipped_page_reason():
    provider = FakeProvider()
    fetcher = FakeFetcher({LIST_A: "empty", LIST_B: "bad"})

    report = run(fetcher, FakeStore(), provider, [LIST_A, LIST_B])

    assert [(page.url, page.reason, page.attempts) for page in report.pages_skipped] == [(LIST_A, "empty_category", 1), (LIST_B, "parse_error", 1)]
    assert report.pages_completed == 0
    assert report.status is RunStatus.FAILED
    assert report.zero_progress_reason == "every listed page was skipped (2 of 2)"


def test_parse_detail_receives_the_listed_item_of_the_card():
    provider = FakeProvider()

    run(FakeFetcher({LIST_A: "K7", item_url("K7"): "ok"}), FakeStore(), provider, [LIST_A])

    assert len(provider.detail_calls) == 1
    listed = provider.detail_calls[0]
    assert listed == ListedItem(external_id="K7", source_url=item_url("K7"), list_url=LIST_A)


def test_a_soft_404_fails_only_that_card_as_product_not_found():
    report = run(
        FakeFetcher({LIST_A: "K1,K2", item_url("K1"): "soft404", item_url("K2"): "ok"}),
        FakeStore(),
        FakeProvider(),
        [LIST_A],
    )

    assert report.failed == 1
    assert report.imported == 1
    assert [(item.external_id, item.reason, item.message) for item in report.failed_items] == [
        ("K1", "product_not_found", "the detail page is a soft 404: no product")
    ]
    assert report.status is RunStatus.PARTIAL_SUCCESS


def test_a_parse_error_saves_the_diagnostics_and_fails_the_card_with_parse_error():
    sink = FakeSink()
    report = run(
        FakeFetcher({LIST_A: "K1", item_url("K1"): "bad"}),
        FakeStore(),
        FakeProvider(),
        [LIST_A],
        diagnostics=sink,
    )

    assert sink.saved == [("detail", "K1", "bad")]
    assert [(item.reason, item.attempts) for item in report.failed_items] == [(PARSE_ERROR_REASON, 1)]
    assert report.parse_error_200_count == 1


def test_a_list_parse_error_saves_the_list_diagnostic_under_the_adapter_code():
    sink = FakeSink()
    report = run(FakeFetcher({LIST_A: "bad", LIST_B: "K9", item_url("K9"): "ok"}), FakeStore(), FakeProvider(), [LIST_A, LIST_B], diagnostics=sink)

    assert sink.saved == [("list", "a", "bad")]
    assert [(page.url, page.reason) for page in report.pages_skipped] == [(LIST_A, PARSE_ERROR_REASON)]
    assert report.pages_completed == 1


def test_the_budget_stops_the_run_before_the_next_page():
    clock = FakeClock()
    budget = SoftBudget(10, clock)
    clock.now = 10.0  # exhausted before the first page starts
    report = run(FakeFetcher({LIST_A: "K1"}), FakeStore(), FakeProvider(), [LIST_A], budget=budget)

    assert report.budget_exhausted is True
    assert report.pages_not_reached == 1
    assert report.status is RunStatus.FAILED


@pytest.mark.parametrize("provider_code", [ProviderCode.ESLITE, ProviderCode.BOOKS_COM_TW])
def test_the_report_takes_the_provider_of_the_adapter_it_was_given(provider_code):
    provider = FakeProvider()
    adapter = CategoryAdapter(
        provider=provider_code,
        mode="fake",
        run_logger_name="fake.run",
        ledger_logger_name="fake.ledger",
        parse_list=fake_parse_list,
        parse_detail=provider.parse_detail,
        parse_error=FakeParseError,
        not_found=FakeNotFound,
        list_page_code=lambda url: url.rsplit("/", 1)[-1],
    )
    report = run_category_pages(adapter, make_deps(FakeFetcher({LIST_A: "K1", item_url("K1"): "ok"}), FakeStore()), [LIST_A])

    assert report.provider_code is provider_code


def test_an_adapter_without_a_provider_is_refused_when_the_report_is_built():
    # The run reads the provider from the adapter only. A missing provider is a programming error: the report refuses it,
    # it is never defaulted to another provider.
    provider = FakeProvider()
    adapter = provider.adapter()
    broken = CategoryAdapter(
        provider=None,  # type: ignore[arg-type]
        mode=adapter.mode,
        run_logger_name=adapter.run_logger_name,
        ledger_logger_name=adapter.ledger_logger_name,
        parse_list=adapter.parse_list,
        parse_detail=adapter.parse_detail,
        parse_error=adapter.parse_error,
        not_found=adapter.not_found,
        list_page_code=adapter.list_page_code,
    )

    with pytest.raises(ValueError, match="needs a provider_code"):
        run_category_pages(broken, make_deps(FakeFetcher({LIST_A: "K1"}), FakeStore()), [LIST_A])
