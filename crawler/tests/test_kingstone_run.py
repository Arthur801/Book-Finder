"""Kingstone page-by-page run (kingstone.run), offline: fake fetcher, in-memory store, fake clock and sleep.

The HTML is the real detail fixtures plus synthetic list pages built from the same card markup. No network, no database.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest

from catalog_core.identity import IdentityKind, SourceIdentity
from catalog_core.models import BookDraft, ProviderCode, SourceRef, WritePolicy
from kingstone.acquisition import AcquisitionError, AcquisitionFailure
from kingstone.ledger import RunStatus
from kingstone.parse_detail import parse_detail_html
from kingstone.run import (
    MAX_ITEM_ATTEMPTS,
    KingstoneRunDependencies,
    SoftBudget,
    run_pages,
)
from kingstone.urls import detail_url

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "kingstone"
NOW = datetime(2026, 10, 25, 3, 0, tzinfo=UTC)

LIST_A = "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1"
LIST_B = "https://www.kingstone.com.tw/book/jdc/?dis=list&page=2"
LIST_C = "https://www.kingstone.com.tw/book/jdc/?dis=list&page=3"

KM_1 = "2018630959191"  # detail fixture: 一般書，有 ISBN、目錄
KM_2 = "2018564008187"  # detail fixture: 套書，有 ISBN
KM_3 = "2018741206573"  # detail fixture: 翻譯書
SOFT_404 = "2099999999999"

SOFT_404_HTML = "<html><head><title>金石堂</title></head><body></body></html>"
DSN_SECRET = "postgresql://kingstone_user:hunter2@db.internal:5432/books"


def fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def detail_html(km_code: str) -> str:
    return fixture(f"detail_{km_code}.html")


def list_html(km_codes: Sequence[str]) -> str:
    cards = "".join(
        f'<div class="mod_prod_card" data-prodno="{code}"><div class="coverbox"><a href="/basic/{code}/?lid=test">x</a></div></div>' for code in km_codes
    )
    return f'<html><body><section id="allProducts"><div id="displayCSS"><div class="productGrid">{cards}</div></div></section></body></html>'


EMPTY_LIST_HTML = '<html><body><section id="allProducts"><div id="displayCSS"><div class="emptyCategory">此分類沒有相關商品唷！</div></div></section></body></html>'


class FakeClock:
    """A monotonic clock the test moves by hand (the budget reads it)."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeFetcher:
    """URL -> response. A value is a page body or an exception; a list is consumed in order, its last item repeats."""

    def __init__(self, responses: dict[str, object], on_request: Callable[[str], None] | None = None) -> None:
        self._responses = dict(responses)
        self._on_request = on_request
        self.calls: list[str] = []
        self.failures = 0

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
        if self._on_request is not None:
            self._on_request(url)
        if url not in self._responses:
            raise AssertionError(f"unexpected request: {url}")
        value = self._responses[url]
        if isinstance(value, list):
            value = value.pop(0) if len(value) > 1 else value[0]
        if isinstance(value, BaseException):
            raise value
        return value

    def detail_calls(self) -> list[str]:
        return [url for url in self.calls if "/basic/" in url]


class MemoryStore:
    """In-memory CatalogStore. Identity is by external_id. ``faults`` queues exceptions per method name."""

    def __init__(self) -> None:
        self.refs: dict[str, SourceRef] = {}  # external_id -> SourceRef
        self.warnings: dict[str, str] = {}  # external_id -> identity warning returned on the touch path
        self.persisted: list[BookDraft] = []
        self.touched: list[uuid.UUID] = []
        self.isbn_matches: dict[str, list[uuid.UUID]] = {}
        self.faults: dict[str, list[BaseException]] = {}
        self.commit_then_fail: list[BaseException] = []  # persist commits, then raises (uncertain commit)

    def _fault(self, name: str) -> None:
        queue = self.faults.get(name)
        if queue:
            raise queue.pop(0)

    def resolve_source_identity(self, provider: ProviderCode, source_url: str, external_id: str | None) -> SourceIdentity:
        self._fault("resolve_source_identity")
        if external_id in self.refs:
            return SourceIdentity(IdentityKind.EXISTING, ref=self.refs[external_id], warning=self.warnings.get(external_id))
        return SourceIdentity(IdentityKind.NEW)

    def touch_source(self, provider: ProviderCode, source_id: uuid.UUID, observed_at: datetime) -> bool:
        self._fault("touch_source")
        self.touched.append(source_id)
        return True

    def find_books_by_isbn(self, values: Sequence[str]) -> list[uuid.UUID]:
        self._fault("find_books_by_isbn")
        found: list[uuid.UUID] = []
        for value in values:
            found.extend(self.isbn_matches.get(value, []))
        return list(dict.fromkeys(found))

    def persist_new_source(self, provider: ProviderCode, draft: BookDraft, now: datetime, attach_to_book_id):
        self._fault("persist_new_source")
        ref = SourceRef(source_id=uuid.uuid4(), book_id=attach_to_book_id or uuid.uuid4())
        self.refs[draft.external_id] = ref
        self.persisted.append(draft)
        if self.commit_then_fail:
            raise self.commit_then_fail.pop(0)
        return ref


def make_deps(
    fetcher: FakeFetcher,
    store: MemoryStore,
    *,
    budget: SoftBudget | None = None,
    sleeps: list[float] | None = None,
    max_item_attempts: int = MAX_ITEM_ATTEMPTS,
    write_policy: WritePolicy = WritePolicy.NORMAL,
) -> KingstoneRunDependencies:
    return KingstoneRunDependencies(
        fetcher=fetcher,
        store=store,
        budget=budget if budget is not None else SoftBudget(10_000, FakeClock()),
        clock=lambda: NOW,
        sleep=(sleeps if sleeps is not None else []).append,
        write_policy=write_policy,
        max_item_attempts=max_item_attempts,
    )


def isbn_of(km_code: str) -> str:
    """The ISBN the detail fixture carries: the value the ISBN lookup is scripted with."""
    draft = parse_detail_html(detail_html(km_code), detail_url(km_code))
    assert len(draft.identifiers) == 1
    return draft.identifiers[0].identifier_value


def db_error(message: str = "connection lost") -> psycopg.OperationalError:
    return psycopg.OperationalError(message)


def acquisition(kind: AcquisitionFailure, attempts: int = 3, status: int | None = None) -> AcquisitionError:
    return AcquisitionError(kind, f"GET test failed: {kind.value}", attempts, status)


# ---------------------------------------------------------------------------
# SoftBudget
# ---------------------------------------------------------------------------


def test_soft_budget_counts_down_from_its_creation_and_reports_exhaustion():
    clock = FakeClock(100.0)
    budget = SoftBudget(30.0, clock)

    assert budget.remaining() == 30.0
    assert budget.exhausted() is False

    clock.advance(29.5)
    assert budget.remaining() == pytest.approx(0.5)
    assert budget.exhausted() is False

    clock.advance(0.5)
    assert budget.remaining() == 0.0
    assert budget.exhausted() is True


def test_soft_budget_with_no_seconds_is_exhausted_at_once():
    assert SoftBudget(0, FakeClock()).exhausted() is True


# ---------------------------------------------------------------------------
# Full flow, replay and the run's terminal status
# ---------------------------------------------------------------------------


def test_full_run_imports_every_new_card_and_reports_success(caplog):
    caplog.set_level(logging.INFO)
    fetcher = FakeFetcher(
        {
            LIST_A: list_html([KM_1, KM_2]),
            detail_url(KM_1): detail_html(KM_1),
            detail_url(KM_2): detail_html(KM_2),
        }
    )
    store = MemoryStore()

    report = run_pages(make_deps(fetcher, store), [LIST_A], run_id="run-1")

    assert report.status is RunStatus.SUCCESS
    assert report.error is None
    assert report.pages_completed == 1
    assert report.items_seen == 2
    assert report.imported == 2
    assert report.existing_source == 0
    assert fetcher.detail_calls() == [detail_url(KM_1), detail_url(KM_2)]
    assert [draft.external_id for draft in store.persisted] == [KM_1, KM_2]
    assert report.run_id == "run-1"
    assert any(record.getMessage().startswith("mode=kingstone ") and "status=SUCCESS" in record.getMessage() for record in caplog.records)


def test_replay_touches_existing_cards_without_any_detail_request():
    fetcher = FakeFetcher({LIST_A: list_html([KM_1, KM_2]), detail_url(KM_1): detail_html(KM_1), detail_url(KM_2): detail_html(KM_2)})
    store = MemoryStore()
    run_pages(make_deps(fetcher, store), [LIST_A])

    second_fetcher = FakeFetcher({LIST_A: list_html([KM_1, KM_2])})
    report = run_pages(make_deps(second_fetcher, store), [LIST_A])

    assert report.status is RunStatus.SUCCESS
    assert second_fetcher.detail_calls() == []
    assert report.existing_source == 2
    assert report.imported == 0
    assert len(store.touched) == 2


def test_list_redirect_skips_that_page_and_the_next_page_still_runs():
    fetcher = FakeFetcher(
        {
            LIST_A: acquisition(AcquisitionFailure.REDIRECT, attempts=1, status=302),
            LIST_B: list_html([KM_1]),
            detail_url(KM_1): detail_html(KM_1),
        }
    )
    store = MemoryStore()

    report = run_pages(make_deps(fetcher, store), [LIST_A, LIST_B])

    assert [item.url for item in report.pages_skipped] == [LIST_A]
    assert report.pages_skipped[0].reason == "redirect"
    assert report.pages_skipped[0].attempts == 1
    assert report.pages_completed == 1
    assert report.status is RunStatus.PARTIAL_SUCCESS


def test_list_parse_error_skips_the_page_with_reason_parse_error():
    fetcher = FakeFetcher({LIST_A: "<html><body>maintenance</body></html>", LIST_B: EMPTY_LIST_HTML})

    report = run_pages(make_deps(fetcher, MemoryStore()), [LIST_A, LIST_B])

    assert len(report.pages_skipped) == 1
    assert report.pages_skipped[0].reason == "parse_error"
    assert report.pages_skipped[0].attempts == 1
    assert report.pages_completed == 1


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        (AcquisitionFailure.HTTP_STATUS, "http_status"),
        (AcquisitionFailure.TRANSPORT, "transport"),
        (AcquisitionFailure.OVERSIZE, "oversize"),
        (AcquisitionFailure.DECODE_ERROR, "decode_error"),
        (AcquisitionFailure.RETRY_AFTER_TOO_LONG, "retry_after_too_long"),
    ],
)
def test_every_other_acquisition_failure_skips_the_page_with_its_lowercase_kind(kind, reason):
    fetcher = FakeFetcher({LIST_A: acquisition(kind), LIST_B: EMPTY_LIST_HTML})

    report = run_pages(make_deps(fetcher, MemoryStore()), [LIST_A, LIST_B])

    assert report.pages_skipped[0].reason == reason
    assert report.pages_skipped[0].attempts == 3


def test_every_listed_page_skipped_is_failed_with_zero_progress_reason():
    fetcher = FakeFetcher(
        {
            LIST_A: acquisition(AcquisitionFailure.REDIRECT, attempts=1, status=302),
            LIST_B: "<html>no grid</html>",
        }
    )

    report = run_pages(make_deps(fetcher, MemoryStore()), [LIST_A, LIST_B])

    assert report.status is RunStatus.FAILED
    assert report.zero_progress_reason == "every listed page was skipped (2 of 2)"
    assert report.exit_code == 1


def test_legal_empty_page_completes_with_no_cards_and_counts_a_zero_card_page():
    fetcher = FakeFetcher({LIST_A: EMPTY_LIST_HTML})

    report = run_pages(make_deps(fetcher, MemoryStore()), [LIST_A])

    assert report.status is RunStatus.SUCCESS
    assert report.pages_completed == 1
    assert report.zero_card_pages == 1
    assert report.items_seen == 0
    assert fetcher.detail_calls() == []


def test_soft_404_fails_only_that_book_and_writes_nothing_for_it():
    fetcher = FakeFetcher(
        {
            LIST_A: list_html([SOFT_404, KM_1]),
            detail_url(SOFT_404): SOFT_404_HTML,
            detail_url(KM_1): detail_html(KM_1),
        }
    )
    store = MemoryStore()

    report = run_pages(make_deps(fetcher, store), [LIST_A])

    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.failed == 1
    assert report.imported == 1
    assert report.failed_items[0].reason == "product_not_found"
    assert report.failed_items[0].external_id == SOFT_404
    assert report.failed_items[0].attempts == 1
    assert [draft.external_id for draft in store.persisted] == [KM_1]


def test_detail_acquisition_error_is_not_retried_by_the_service():
    fetcher = FakeFetcher(
        {
            LIST_A: list_html([KM_1, KM_2]),
            detail_url(KM_1): acquisition(AcquisitionFailure.HTTP_STATUS, attempts=3, status=404),
            detail_url(KM_2): detail_html(KM_2),
        }
    )

    report = run_pages(make_deps(fetcher, MemoryStore()), [LIST_A])

    assert fetcher.calls.count(detail_url(KM_1)) == 1
    assert report.failed_items[0].reason == "http_status"
    assert report.failed_items[0].attempts == 1
    assert report.imported == 1
    assert report.status is RunStatus.PARTIAL_SUCCESS


def test_detail_parse_error_fails_the_book_as_parse_error_without_retry():
    fetcher = FakeFetcher({LIST_A: list_html([KM_1]), detail_url(KM_1): "<html><body>no product</body></html>"})

    report = run_pages(make_deps(fetcher, MemoryStore()), [LIST_A])

    assert fetcher.calls.count(detail_url(KM_1)) == 1
    assert report.failed_items[0].reason == "parse_error"


def test_a_database_failure_before_persist_is_retried_with_the_parsed_draft():
    fetcher = FakeFetcher({LIST_A: list_html([KM_1]), detail_url(KM_1): detail_html(KM_1)})
    store = MemoryStore()
    store.faults["persist_new_source"] = [db_error()]
    sleeps: list[float] = []

    report = run_pages(make_deps(fetcher, store, sleeps=sleeps), [LIST_A])

    assert report.status is RunStatus.SUCCESS
    assert report.imported == 1
    assert fetcher.detail_calls() == [detail_url(KM_1)]  # the draft was kept: no second detail request
    assert sleeps == [1.0]
    assert report.recovered_commit_count == 0


def test_uncertain_commit_is_recovered_by_re_resolving_the_identity():
    fetcher = FakeFetcher({LIST_A: list_html([KM_1]), detail_url(KM_1): detail_html(KM_1)})
    store = MemoryStore()
    store.commit_then_fail = [db_error("commit result unknown")]

    report = run_pages(make_deps(fetcher, store), [LIST_A])

    assert report.status is RunStatus.SUCCESS
    assert report.recovered_commit_count == 1
    assert report.existing_source == 1
    assert report.imported == 0
    assert len(store.persisted) == 1  # written once, the second attempt only re-resolved


def test_database_failures_after_all_attempts_fail_the_book_not_the_run():
    fetcher = FakeFetcher({LIST_A: list_html([KM_1, KM_2]), detail_url(KM_1): detail_html(KM_1), detail_url(KM_2): detail_html(KM_2)})
    store = MemoryStore()
    store.faults["find_books_by_isbn"] = [db_error(), db_error(), db_error()]
    sleeps: list[float] = []

    report = run_pages(make_deps(fetcher, store, sleeps=sleeps), [LIST_A])

    assert report.failed_items[0].reason == "database_error"
    assert report.failed_items[0].attempts == 3
    assert sleeps == [1.0, 2.0]
    assert report.imported == 1
    assert report.status is RunStatus.PARTIAL_SUCCESS


def test_identity_warning_is_logged_as_a_warning_and_counted(caplog):
    caplog.set_level(logging.WARNING, logger="kingstone.run")
    fetcher = FakeFetcher({LIST_A: list_html([KM_1])})
    store = MemoryStore()
    store.refs[KM_1] = SourceRef(source_id=uuid.uuid4(), book_id=uuid.uuid4())
    store.warnings[KM_1] = "URL drift: source_url is not the stored URL; the existing URL is kept"

    report = run_pages(make_deps(fetcher, store), [LIST_A])

    assert report.identity_warning_count == 1
    assert report.existing_source == 1
    warnings = [record for record in caplog.records if record.name == "kingstone.run" and record.levelno == logging.WARNING]
    assert any("URL drift" in record.getMessage() for record in warnings)


def test_store_exception_stops_the_run_as_failed_and_the_error_is_redacted(caplog):
    caplog.set_level(logging.ERROR)
    fetcher = FakeFetcher({LIST_A: list_html([KM_1, KM_2]), detail_url(KM_1): detail_html(KM_1)})
    store = MemoryStore()
    store.faults["resolve_source_identity"] = [db_error(f"could not connect using {DSN_SECRET} password=hunter2")]

    report = run_pages(make_deps(fetcher, store), [LIST_A])

    assert report.status is RunStatus.FAILED
    assert report.error is not None
    assert report.error.startswith("OperationalError: ")
    assert "hunter2" not in report.error
    assert "kingstone_user" not in report.error
    assert "postgresql://<redacted>" in report.error
    assert "password=<redacted>" in report.error
    assert report.exit_code == 1
    assert any(record.levelname == "ERROR" and "hunter2" not in record.getMessage() for record in caplog.records)


def test_unexpected_value_error_is_fatal_too():
    fetcher = FakeFetcher({LIST_A: ValueError("programming error")})

    report = run_pages(make_deps(fetcher, MemoryStore()), [LIST_A])

    assert report.status is RunStatus.FAILED
    assert report.error == "ValueError: programming error"


def test_a_skipped_page_message_is_redacted_before_it_reaches_the_report():
    secret_error = AcquisitionError(AcquisitionFailure.TRANSPORT, f"proxy {DSN_SECRET} refused", 3)
    fetcher = FakeFetcher({LIST_A: secret_error, LIST_B: EMPTY_LIST_HTML})

    report = run_pages(make_deps(fetcher, MemoryStore()), [LIST_A])

    assert "hunter2" not in report.pages_skipped[0].message
    assert "postgresql://<redacted>" in report.pages_skipped[0].message
    assert report.pages_skipped[0].reason == "transport"


def test_an_empty_page_list_is_failed_with_its_reason():
    report = run_pages(make_deps(FakeFetcher({}), MemoryStore()), [])

    assert report.status is RunStatus.FAILED
    assert report.zero_progress_reason == "the page list has no pages"


def test_duplicate_page_urls_are_run_once_and_never_raise():
    fetcher = FakeFetcher({LIST_A: EMPTY_LIST_HTML})

    report = run_pages(make_deps(fetcher, MemoryStore()), [LIST_A, LIST_A])

    assert report.pages_listed == 1
    assert fetcher.calls == [LIST_A]


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


def test_budget_exhausted_before_the_first_page_is_failed_with_no_request():
    fetcher = FakeFetcher({LIST_A: EMPTY_LIST_HTML})
    budget = SoftBudget(0, FakeClock())

    report = run_pages(make_deps(fetcher, MemoryStore(), budget=budget), [LIST_A, LIST_B])

    assert fetcher.calls == []
    assert report.status is RunStatus.FAILED
    assert report.budget_exhausted is True
    assert report.pages_not_reached == 2
    assert report.zero_progress_reason == "the run budget ran out before any listed page was completed"


def test_budget_exhausted_before_the_second_page_is_partial_with_the_rest_not_reached():
    clock = FakeClock()
    fetcher = FakeFetcher(
        {LIST_A: list_html([KM_1]), LIST_B: list_html([KM_2]), detail_url(KM_1): detail_html(KM_1)},
        on_request=lambda url: clock.advance(4 if url == LIST_A else 6),
    )
    budget = SoftBudget(10, clock)

    report = run_pages(make_deps(fetcher, MemoryStore(), budget=budget), [LIST_A, LIST_B, LIST_C])

    assert LIST_B not in fetcher.calls
    assert report.pages_completed == 1
    assert report.pages_not_reached == 2
    assert report.pages_interrupted == 0
    assert report.budget_exhausted is True
    assert report.status is RunStatus.PARTIAL_SUCCESS


def test_budget_exhausted_mid_page_interrupts_that_page_and_stops_cleanly():
    clock = FakeClock()
    store = MemoryStore()
    fetcher = FakeFetcher(
        {
            LIST_A: list_html([KM_1]),
            LIST_B: list_html([KM_2, KM_3]),
            detail_url(KM_1): detail_html(KM_1),
            detail_url(KM_2): detail_html(KM_2),
            detail_url(KM_3): detail_html(KM_3),
        },
        on_request=lambda url: clock.advance(10 if "/basic/" in url else 0),
    )
    budget = SoftBudget(20, clock)

    report = run_pages(make_deps(fetcher, store, budget=budget), [LIST_A, LIST_B])

    assert fetcher.detail_calls() == [detail_url(KM_1), detail_url(KM_2)]
    assert report.pages_completed == 1
    assert report.pages_interrupted == 1
    assert report.pages_not_reached == 0
    assert report.items_seen == 2
    assert report.status is RunStatus.PARTIAL_SUCCESS
    assert report.error is None


def test_detail_budget_error_from_the_fetcher_stops_cleanly():
    fetcher = FakeFetcher(
        {
            LIST_A: list_html([KM_1]),
            LIST_B: list_html([KM_2]),
            detail_url(KM_1): detail_html(KM_1),
            detail_url(KM_2): acquisition(AcquisitionFailure.BUDGET_EXHAUSTED, attempts=0),
        }
    )

    report = run_pages(make_deps(fetcher, MemoryStore()), [LIST_A, LIST_B, LIST_C])

    assert LIST_C not in fetcher.calls
    assert report.failed_items[0].reason == "budget_exhausted"
    assert report.pages_completed == 1
    assert report.pages_interrupted == 1
    assert report.pages_not_reached == 1
    assert report.budget_exhausted is True
    assert report.status is RunStatus.PARTIAL_SUCCESS


def test_list_budget_error_from_the_fetcher_stops_cleanly_and_the_page_is_not_reached():
    fetcher = FakeFetcher(
        {
            LIST_A: list_html([KM_1]),
            LIST_B: acquisition(AcquisitionFailure.BUDGET_EXHAUSTED, attempts=0),
            detail_url(KM_1): detail_html(KM_1),
        }
    )

    report = run_pages(make_deps(fetcher, MemoryStore()), [LIST_A, LIST_B, LIST_C])

    assert LIST_C not in fetcher.calls
    assert report.pages_completed == 1
    assert report.pages_not_reached == 2
    assert report.pages_skipped == ()
    assert report.budget_exhausted is True
    assert report.status is RunStatus.PARTIAL_SUCCESS


def test_a_second_run_with_a_fresh_budget_replays_from_the_top_and_advances():
    clock = FakeClock()
    store = MemoryStore()
    responses = {
        LIST_A: list_html([KM_1]),
        LIST_B: list_html([KM_2]),
        detail_url(KM_1): detail_html(KM_1),
        detail_url(KM_2): detail_html(KM_2),
    }
    first = run_pages(
        make_deps(FakeFetcher(responses, on_request=lambda url: clock.advance(0 if "/basic/" not in url else 10)), store, budget=SoftBudget(10, clock)),
        [LIST_A, LIST_B],
    )
    assert first.pages_completed == 1
    assert first.status is RunStatus.PARTIAL_SUCCESS

    second_fetcher = FakeFetcher(responses)
    second = run_pages(make_deps(second_fetcher, store), [LIST_A, LIST_B])

    assert second_fetcher.calls[0] == LIST_A
    assert second_fetcher.detail_calls() == [detail_url(KM_2)]
    assert second.existing_source == 1
    assert second.imported == 1
    assert second.status is RunStatus.SUCCESS


# --- write policy (CB-07 Phase 5, spec §5 and §7) ----------------------------------------------------------------------


def test_new_books_only_one_isbn_match_is_policy_skipped_with_no_write_and_no_touch():
    book = uuid.uuid4()
    fetcher = FakeFetcher({LIST_A: list_html([KM_1]), detail_url(KM_1): detail_html(KM_1)})
    store = MemoryStore()
    store.isbn_matches[isbn_of(KM_1)] = [book]

    report = run_pages(make_deps(fetcher, store, write_policy=WritePolicy.NEW_BOOKS_ONLY), [LIST_A], run_id="run-1")

    assert report.status is RunStatus.SUCCESS
    assert report.zero_progress_reason is None
    assert report.policy_skipped_count == 1
    assert report.items_seen == 1
    assert (report.imported, report.isbn_attached, report.ambiguous_created, report.existing_source, report.failed) == (0, 0, 0, 0, 0)
    assert report.write_policy is WritePolicy.NEW_BOOKS_ONLY
    assert store.persisted == []
    assert store.touched == []
    assert fetcher.detail_calls() == [detail_url(KM_1)]


def test_normal_one_isbn_match_attaches_the_source_to_that_book():
    book = uuid.uuid4()
    fetcher = FakeFetcher({LIST_A: list_html([KM_1]), detail_url(KM_1): detail_html(KM_1)})
    store = MemoryStore()
    store.isbn_matches[isbn_of(KM_1)] = [book]

    report = run_pages(make_deps(fetcher, store, write_policy=WritePolicy.NORMAL), [LIST_A], run_id="run-1")

    assert report.status is RunStatus.SUCCESS
    assert report.isbn_attached == 1
    assert report.policy_skipped_count == 0
    assert [draft.external_id for draft in store.persisted] == [KM_1]
    assert store.refs[KM_1].book_id == book


def test_new_books_only_no_isbn_match_still_imports_and_ambiguous_still_creates():
    ambiguous_book = uuid.uuid4()
    fetcher = FakeFetcher(
        {
            LIST_A: list_html([KM_1, KM_2]),
            detail_url(KM_1): detail_html(KM_1),
            detail_url(KM_2): detail_html(KM_2),
        }
    )
    store = MemoryStore()
    store.isbn_matches[isbn_of(KM_2)] = [ambiguous_book, uuid.uuid4()]

    report = run_pages(make_deps(fetcher, store, write_policy=WritePolicy.NEW_BOOKS_ONLY), [LIST_A], run_id="run-1")

    assert report.status is RunStatus.SUCCESS
    assert report.imported == 1
    assert report.ambiguous_created == 1
    assert report.policy_skipped_count == 0
    assert [draft.external_id for draft in store.persisted] == [KM_1, KM_2]


def test_policy_skipped_book_stays_new_so_the_next_run_fetches_it_again():
    fetcher = FakeFetcher({LIST_A: list_html([KM_1]), detail_url(KM_1): detail_html(KM_1)})
    store = MemoryStore()
    store.isbn_matches[isbn_of(KM_1)] = [uuid.uuid4()]
    deps = make_deps(fetcher, store, write_policy=WritePolicy.NEW_BOOKS_ONLY)

    first = run_pages(deps, [LIST_A], run_id="run-1")
    second = run_pages(deps, [LIST_A], run_id="run-2")

    assert first.policy_skipped_count == second.policy_skipped_count == 1
    assert fetcher.detail_calls() == [detail_url(KM_1), detail_url(KM_1)]
    assert store.persisted == []


# ---------------------------------------------------------------------------
# Counts, diagnostics (plan v12 §8)
# ---------------------------------------------------------------------------


class RecordingSink:
    """A diagnostic sink that records the calls. ``error`` makes every call raise."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.saved: list[tuple[str, str, str]] = []
        self.error = error

    def save_html(self, *, kind: str, code: str, html: str) -> None:
        if self.error is not None:
            raise self.error
        self.saved.append((kind, code, html))


def test_the_counts_cover_listed_cards_detail_fetches_and_the_fetcher_counters():
    fetcher = FakeFetcher(
        {
            LIST_A: list_html([KM_1, KM_2]),
            detail_url(KM_1): detail_html(KM_1),
            detail_url(KM_2): acquisition(AcquisitionFailure.HTTP_STATUS, attempts=1, status=500),
        }
    )
    store = MemoryStore()

    report = run_pages(make_deps(fetcher, store), [LIST_A], run_id="run-counts")

    assert report.items_listed == 2
    assert report.details_fetched == 2  # a fetch that failed still counts as a detail fetch
    assert report.failed == 1
    assert report.http_attempts == len(fetcher.calls) == 3
    assert report.items_seen == 2


def test_a_skipped_list_page_adds_no_listed_items_and_no_details():
    fetcher = FakeFetcher({LIST_A: acquisition(AcquisitionFailure.REDIRECT, attempts=1, status=302), LIST_B: list_html([])})

    report = run_pages(make_deps(fetcher, MemoryStore()), [LIST_A, LIST_B])

    assert report.items_listed == 0
    assert report.details_fetched == 0


def test_a_list_parse_error_is_saved_as_a_list_diagnostic_with_the_category_code():
    sink = RecordingSink()
    broken = "<html><body>no product section</body></html>"
    fetcher = FakeFetcher({LIST_A: broken, LIST_B: list_html([KM_1]), detail_url(KM_1): detail_html(KM_1)})
    deps = make_deps(fetcher, MemoryStore())
    deps = KingstoneRunDependencies(**{**deps.__dict__, "diagnostics": sink})

    report = run_pages(deps, [LIST_A, LIST_B])

    assert sink.saved == [("list", "jdc", broken)]
    assert report.pages_skipped[0].reason == "parse_error"


def test_a_detail_parse_error_is_saved_as_a_detail_diagnostic_with_the_km_code():
    sink = RecordingSink()
    broken = "<html><head><title>金石堂網路書店</title></head><body>layout changed</body></html>"
    fetcher = FakeFetcher({LIST_A: list_html([KM_1]), detail_url(KM_1): broken})
    deps = KingstoneRunDependencies(**{**make_deps(fetcher, MemoryStore()).__dict__, "diagnostics": sink})

    report = run_pages(deps, [LIST_A])

    assert sink.saved == [("detail", KM_1, broken)]
    assert report.failed == 1


def test_a_soft_404_and_an_acquisition_failure_are_not_saved():
    sink = RecordingSink()
    fetcher = FakeFetcher(
        {
            LIST_A: list_html([SOFT_404, KM_1]),
            detail_url(SOFT_404): SOFT_404_HTML,
            detail_url(KM_1): acquisition(AcquisitionFailure.TRANSPORT, attempts=3),
        }
    )
    deps = KingstoneRunDependencies(**{**make_deps(fetcher, MemoryStore()).__dict__, "diagnostics": sink})

    run_pages(deps, [LIST_A])

    assert sink.saved == []


def test_a_failing_diagnostic_sink_never_changes_the_run():
    fetcher = FakeFetcher({LIST_A: "<html><body>broken</body></html>", LIST_B: list_html([KM_1]), detail_url(KM_1): detail_html(KM_1)})
    deps = KingstoneRunDependencies(**{**make_deps(fetcher, MemoryStore()).__dict__, "diagnostics": RecordingSink(OSError("disk full"))})

    report = run_pages(deps, [LIST_A, LIST_B])

    assert report.error is None
    assert report.pages_completed == 1
    assert report.imported == 1
