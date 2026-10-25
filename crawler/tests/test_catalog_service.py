"""Provider-neutral item resolution (catalog_core.service): every branch of the run.py resolver, with an in-memory store."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
import pytest

from catalog_core.identity import IdentityKind, SourceIdentity
from catalog_core.models import (
    BookDraft,
    CatalogResolution,
    Identifier,
    IdentifierType,
    ProviderCode,
    SourceRef,
)
from catalog_core.service import (
    CatalogItem,
    DraftFailure,
    FailureReason,
    ItemFailed,
    ItemResolved,
    resolve_item,
)

URL = "https://www.kingstone.com.tw/book/KS1"
EXTERNAL_ID = "KS1"
NOW = datetime(2026, 10, 25, 8, 0, tzinfo=UTC)
ISBN = "9780000000001"


def item(external_id: str | None = None) -> CatalogItem:
    return CatalogItem(provider=ProviderCode.KINGSTONE, source_url=URL, external_id=external_id)


def draft(*isbns: str) -> BookDraft:
    return BookDraft(
        source_url=URL,
        title="A Book",
        identifiers=tuple(Identifier(IdentifierType.ISBN, value) for value in isbns),
    )


def ref() -> SourceRef:
    return SourceRef(source_id=uuid4(), book_id=uuid4())


def existing(source_ref: SourceRef, warning: str | None = None) -> SourceIdentity:
    return SourceIdentity(IdentityKind.EXISTING, ref=source_ref, warning=warning)


NEW = SourceIdentity(IdentityKind.NEW)
CONFLICT = SourceIdentity(IdentityKind.CONFLICT, reason="source_identity_conflict: test")
DB_ERROR = psycopg.OperationalError("connection lost")


class FakeStore:
    """In-memory CatalogStore. Each method pops its next scripted result; an exception is raised."""

    def __init__(
        self,
        identities: Sequence[SourceIdentity | BaseException] = (),
        touches: Sequence[bool | BaseException] = (),
        isbn_lookups: Sequence[list[UUID] | BaseException] = (),
        persists: Sequence[SourceRef | BaseException] = (),
    ) -> None:
        self._identities = list(identities)
        self._touches = list(touches)
        self._isbn_lookups = list(isbn_lookups)
        self._persists = list(persists)
        self.calls: list[tuple[str, tuple]] = []

    def _next(self, script: list, name: str):
        if not script:
            raise AssertionError(f"unscripted call to {name}")
        result = script.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def resolve_source_identity(self, provider, source_url, external_id):
        self.calls.append(("resolve_source_identity", (provider, source_url, external_id)))
        return self._next(self._identities, "resolve_source_identity")

    def touch_source(self, provider, source_id, observed_at):
        self.calls.append(("touch_source", (provider, source_id, observed_at)))
        return self._next(self._touches, "touch_source")

    def find_books_by_isbn(self, values: Sequence[str]):
        self.calls.append(("find_books_by_isbn", (tuple(values),)))
        return self._next(self._isbn_lookups, "find_books_by_isbn")

    def persist_new_source(self, provider, draft, now, attach_to_book_id):
        self.calls.append(("persist_new_source", (provider, draft, now, attach_to_book_id)))
        return self._next(self._persists, "persist_new_source")

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def args_of(self, name: str) -> list[tuple]:
        return [args for called, args in self.calls if called == name]


class Fetch:
    """fetch_draft double: returns scripted results in order and records the attempt numbers it was called with."""

    def __init__(self, *results: BookDraft | DraftFailure | BaseException) -> None:
        self._results = list(results)
        self.attempts: list[int] = []

    def __call__(self, attempt: int) -> BookDraft | DraftFailure:
        self.attempts.append(attempt)
        result = self._results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class Failures:
    """on_attempt_failed recorder."""

    def __init__(self) -> None:
        self.events: list[tuple[int, str, str]] = []

    def __call__(self, attempt: int, reason: str, message: str) -> None:
        self.events.append((attempt, reason, message))


def attempts() -> Iterable[int]:
    return iter(range(1, 4))


def resolve(store: FakeStore, fetch: Callable, *, the_item: CatalogItem | None = None, failures: Failures | None = None):
    return resolve_item(
        store,
        the_item or item(EXTERNAL_ID),
        fetch,
        clock=lambda: NOW,
        attempts=attempts,
        on_attempt_failed=failures or Failures(),
    )


# --- 1. identity lookup -------------------------------------------------------------------


def test_identity_exception_propagates_without_retry():
    store = FakeStore(identities=[psycopg.OperationalError("down")])
    fetch = Fetch()

    with pytest.raises(psycopg.OperationalError):
        resolve(store, fetch)

    assert store.names() == ["resolve_source_identity"]
    assert fetch.attempts == []


# --- 2. conflict ----------------------------------------------------------------------------


def test_conflict_is_failed_without_fetch_or_writes():
    store = FakeStore(identities=[CONFLICT])
    fetch = Fetch()

    result = resolve(store, fetch)

    assert result == ItemFailed(
        reason=FailureReason.SOURCE_IDENTITY_CONFLICT,
        message="source_identity_conflict: test",
        attempts=0,
    )
    assert fetch.attempts == []
    assert store.names() == ["resolve_source_identity"]


# --- 3. existing source ----------------------------------------------------------------------


def test_existing_source_is_touched_and_reused_without_fetch():
    source = ref()
    store = FakeStore(identities=[existing(source)], touches=[True])
    fetch = Fetch()

    result = resolve(store, fetch)

    assert result == ItemResolved(source, CatalogResolution.EXISTING, attempts=0, identity_warning=None)
    assert fetch.attempts == []
    assert store.names() == ["resolve_source_identity", "touch_source"]


def test_existing_source_carries_identity_warning():
    source = ref()
    store = FakeStore(identities=[existing(source, warning="URL drift")], touches=[True])

    result = resolve(store, Fetch())

    assert isinstance(result, ItemResolved)
    assert result.identity_warning == "URL drift"


def test_touch_retries_then_succeeds():
    source = ref()
    failures = Failures()
    store = FakeStore(identities=[existing(source)], touches=[DB_ERROR, DB_ERROR, True])

    result = resolve(store, Fetch(), failures=failures)

    assert result == ItemResolved(source, CatalogResolution.EXISTING, attempts=0)
    assert failures.events == [
        (1, "database_error", "connection lost"),
        (2, "database_error", "connection lost"),
    ]
    assert store.names().count("touch_source") == 3


def test_touch_exhausted_fails_with_last_message_and_attempt():
    source = ref()
    failures = Failures()
    store = FakeStore(
        identities=[existing(source)],
        touches=[DB_ERROR, DB_ERROR, psycopg.OperationalError("last one")],
    )

    result = resolve(store, Fetch(), failures=failures)

    assert result == ItemFailed(reason=FailureReason.DATABASE_ERROR, message="last one", attempts=3)
    assert len(failures.events) == 3
    assert failures.events[-1] == (3, "database_error", "last one")


def test_touch_failures_carry_the_identity_warning():
    # The adapter logs the identity warning before the touch, so a failed touch must still report it.
    source = ref()
    conflict = resolve(
        FakeStore(identities=[existing(source, warning="URL drift")], touches=[False]),
        Fetch(),
        failures=Failures(),
    )
    exhausted = resolve(
        FakeStore(
            identities=[existing(source, warning="URL drift")],
            touches=[DB_ERROR, DB_ERROR, psycopg.OperationalError("last one")],
        ),
        Fetch(),
        failures=Failures(),
    )

    assert isinstance(conflict, ItemFailed) and conflict.identity_warning == "URL drift"
    assert isinstance(exhausted, ItemFailed) and exhausted.identity_warning == "URL drift"


def test_touch_false_is_identity_conflict_without_retry_or_fetch():
    source = ref()
    failures = Failures()
    store = FakeStore(identities=[existing(source)], touches=[False])
    fetch = Fetch()

    result = resolve(store, fetch, failures=failures)

    assert isinstance(result, ItemFailed)
    assert result.reason == FailureReason.SOURCE_IDENTITY_CONFLICT
    assert result.attempts == 1
    assert str(source.source_id) in result.message
    assert store.names().count("touch_source") == 1
    assert failures.events == []
    assert fetch.attempts == []


def test_touch_receives_provider_source_id_and_clock_value():
    source = ref()
    store = FakeStore(identities=[existing(source)], touches=[True])

    resolve(store, Fetch())

    assert store.args_of("touch_source") == [(ProviderCode.KINGSTONE, source.source_id, NOW)]


# --- 4. new source: fetch ---------------------------------------------------------------------


def test_new_source_without_isbn_is_imported_with_attach_none():
    created = ref()
    store = FakeStore(identities=[NEW], isbn_lookups=[[]], persists=[created])
    fetch = Fetch(draft())

    result = resolve(store, fetch)

    assert result == ItemResolved(created, CatalogResolution.IMPORTED, attempts=1, matched_book_ids=())
    assert store.args_of("find_books_by_isbn") == [((),)]
    assert store.args_of("persist_new_source")[0][3] is None


def test_new_source_with_one_isbn_match_is_attached():
    book = uuid4()
    created = ref()
    store = FakeStore(identities=[NEW], isbn_lookups=[[book]], persists=[created])

    result = resolve(store, Fetch(draft(ISBN)))

    assert result == ItemResolved(created, CatalogResolution.ISBN_ATTACHED, attempts=1, matched_book_ids=(book,))
    assert store.args_of("persist_new_source")[0][3] == book


def test_new_source_with_two_isbn_matches_is_ambiguous_and_creates_new_book():
    first, second = uuid4(), uuid4()
    created = ref()
    store = FakeStore(identities=[NEW], isbn_lookups=[[first, second]], persists=[created])

    result = resolve(store, Fetch(draft(ISBN)))

    assert result == ItemResolved(
        created,
        CatalogResolution.AMBIGUOUS_CREATED,
        attempts=1,
        matched_book_ids=(first, second),
    )
    assert store.args_of("persist_new_source")[0][3] is None


def test_isbn_values_are_passed_to_lookup_in_draft_order():
    store = FakeStore(identities=[NEW], isbn_lookups=[[]], persists=[ref()])

    resolve(store, Fetch(draft("9780000000001", "9780000000002")))

    assert store.args_of("find_books_by_isbn") == [(("9780000000001", "9780000000002"),)]


def test_provider_and_external_id_reach_every_store_call():
    store = FakeStore(identities=[NEW], isbn_lookups=[[]], persists=[ref()])
    resolve(store, Fetch(draft()), the_item=item(EXTERNAL_ID))

    assert store.args_of("resolve_source_identity") == [(ProviderCode.KINGSTONE, URL, EXTERNAL_ID)]
    assert store.args_of("persist_new_source")[0][0] is ProviderCode.KINGSTONE


def test_external_id_none_is_passed_through_to_identity():
    store = FakeStore(identities=[NEW], isbn_lookups=[[]], persists=[ref()])

    resolve(store, Fetch(draft()), the_item=item(None))

    assert store.args_of("resolve_source_identity") == [(ProviderCode.KINGSTONE, URL, None)]


def test_persist_receives_clock_value():
    store = FakeStore(identities=[NEW], isbn_lookups=[[]], persists=[ref()])

    resolve(store, Fetch(draft()))

    persist_now = store.args_of("persist_new_source")[0][2]
    assert persist_now == NOW


def test_fetch_retryable_failure_then_success_fetches_twice():
    failures = Failures()
    created = ref()
    store = FakeStore(identities=[NEW], isbn_lookups=[[]], persists=[created])
    fetch = Fetch(DraftFailure(reason="fetch_error", message="timeout", retryable=True), draft())

    result = resolve(store, fetch, failures=failures)

    assert result == ItemResolved(created, CatalogResolution.IMPORTED, attempts=2)
    assert fetch.attempts == [1, 2]
    assert failures.events == [(1, "fetch_error", "timeout")]


def test_non_retryable_draft_failure_is_final_after_single_fetch_without_writes():
    failures = Failures()
    store = FakeStore(identities=[NEW])
    fetch = Fetch(DraftFailure(reason="restricted_book", message="member only", retryable=False))

    result = resolve(store, fetch, failures=failures)

    assert result == ItemFailed(reason="restricted_book", message="member only", attempts=1)
    assert fetch.attempts == [1]
    assert store.names() == ["resolve_source_identity"]
    assert failures.events == []


def test_draft_failure_exhausted_reports_last_reason_and_attempt():
    failures = Failures()
    store = FakeStore(identities=[NEW])
    fetch = Fetch(
        DraftFailure(reason="fetch_error", message="one", retryable=True),
        DraftFailure(reason="parse_error", message="two", retryable=True),
        DraftFailure(reason="fetch_error", message="three", retryable=True),
    )

    result = resolve(store, fetch, failures=failures)

    assert result == ItemFailed(reason="fetch_error", message="three", attempts=3)
    assert fetch.attempts == [1, 2, 3]
    assert [event[0] for event in failures.events] == [1, 2, 3]


# --- 4. new source: write -----------------------------------------------------------------------


def test_isbn_lookup_failure_then_success_does_not_re_resolve_identity():
    failures = Failures()
    created = ref()
    store = FakeStore(
        identities=[NEW, NEW],
        isbn_lookups=[DB_ERROR, []],
        persists=[created],
    )
    fetch = Fetch(draft())

    result = resolve(store, fetch, failures=failures)

    assert result == ItemResolved(created, CatalogResolution.IMPORTED, attempts=2)
    assert store.names() == [
        "resolve_source_identity",
        "find_books_by_isbn",
        "find_books_by_isbn",
        "persist_new_source",
    ]
    assert fetch.attempts == [1]
    assert failures.events == [(1, "database_error", "connection lost")]


def test_persist_failure_then_re_resolve_finds_existing_recovers_commit():
    committed = ref()
    failures = Failures()
    store = FakeStore(
        identities=[NEW, existing(committed)],
        isbn_lookups=[[], []],
        persists=[DB_ERROR],
    )
    fetch = Fetch(draft())

    result = resolve(store, fetch, failures=failures)

    assert result == ItemResolved(committed, CatalogResolution.EXISTING, attempts=2, recovered_commit=True)
    assert store.names().count("persist_new_source") == 1
    assert store.names().count("resolve_source_identity") == 2
    assert fetch.attempts == [1]
    assert failures.events == [(1, "database_error", "connection lost")]


def test_persist_failure_then_re_resolve_new_persists_again():
    created = ref()
    store = FakeStore(
        identities=[NEW, NEW],
        isbn_lookups=[[], []],
        persists=[DB_ERROR, created],
    )
    fetch = Fetch(draft())

    result = resolve(store, fetch)

    assert result == ItemResolved(created, CatalogResolution.IMPORTED, attempts=2)
    assert store.names().count("persist_new_source") == 2
    assert fetch.attempts == [1]


def test_re_resolve_exception_counts_as_attempt_and_keeps_maybe_committed():
    committed = ref()
    failures = Failures()
    store = FakeStore(
        identities=[NEW, psycopg.OperationalError("re-resolve down"), existing(committed)],
        isbn_lookups=[[], []],
        persists=[DB_ERROR],
    )
    fetch = Fetch(draft())

    result = resolve(store, fetch, failures=failures)

    assert result == ItemResolved(committed, CatalogResolution.EXISTING, attempts=3, recovered_commit=True)
    assert store.names().count("persist_new_source") == 1
    assert failures.events == [
        (1, "database_error", "connection lost"),
        (2, "database_error", "re-resolve down"),
    ]
    assert fetch.attempts == [1]


def test_conflict_found_on_re_resolve_after_uncertain_commit_fails_without_another_write():
    failures = Failures()
    store = FakeStore(
        identities=[NEW, CONFLICT],
        isbn_lookups=[[]],
        persists=[DB_ERROR],
    )
    fetch = Fetch(draft(ISBN))

    result = resolve(store, fetch, failures=failures)

    assert result == ItemFailed(reason="source_identity_conflict", message=CONFLICT.reason, attempts=2)
    assert store.names().count("persist_new_source") == 1
    assert store.names().count("find_books_by_isbn") == 1
    assert store.names().count("resolve_source_identity") == 2
    assert failures.events == [(1, "database_error", "connection lost")]
    assert fetch.attempts == [1]


def test_all_attempts_exhausted_fails_with_last_reason_and_attempts_three():
    failures = Failures()
    store = FakeStore(
        identities=[NEW, NEW, NEW],
        isbn_lookups=[DB_ERROR, DB_ERROR, psycopg.OperationalError("final")],
    )
    fetch = Fetch(draft())

    result = resolve(store, fetch, failures=failures)

    assert result == ItemFailed(reason=FailureReason.DATABASE_ERROR, message="final", attempts=3)
    assert len(failures.events) == 3
    assert fetch.attempts == [1]


def test_write_failure_after_fetch_does_not_refetch_page():
    created = ref()
    store = FakeStore(identities=[NEW, NEW], isbn_lookups=[DB_ERROR, []], persists=[created])
    fetch = Fetch(draft())

    result = resolve(store, fetch)

    assert isinstance(result, ItemResolved)
    assert fetch.attempts == [1]


def test_attempts_factory_is_consumed_lazily_and_bounded():
    produced: list[int] = []

    def tracked() -> Iterable[int]:
        for n in range(1, 4):
            produced.append(n)
            yield n

    store = FakeStore(identities=[NEW], isbn_lookups=[[]], persists=[ref()])
    resolve_item(
        store,
        item(EXTERNAL_ID),
        Fetch(draft()),
        clock=lambda: NOW,
        attempts=tracked,
    )

    assert produced == [1]
