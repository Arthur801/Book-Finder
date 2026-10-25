"""Provider-neutral item resolution: one discovery item to a Catalog outcome (crawler.md §6, §13.1).

This is the flow that ``books_crawler/run.py`` runs per ranking row, with no HTML, ranking or psycopg
connection of its own. Persistence is reached only through ``CatalogStore``; the page is reached only
through the ``fetch_draft`` callback. The caller owns the retry generator (``attempts``), the clock and
all user-facing logging, which it does from the returned value and ``on_attempt_failed``.

Decisions, in order:

- The source identity lookup is called once and never retried; its exceptions propagate.
- CONFLICT fails the item without a fetch or a write.
- EXISTING touches the Source with retries and never fetches the detail page.
- NEW fetches and parses the page (retryable failures refetch, the parsed draft is kept), then matches
  the draft's ISBN values and persists the Source. A failed persist may have committed, so the next
  attempt re-resolves the identity before writing again: EXISTING recovers the commit, CONFLICT fails
  the item without another ISBN lookup or write, NEW retries the write.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

import psycopg

from catalog_core.identity import IdentityKind, SourceIdentity
from catalog_core.models import (
    BookDraft,
    CatalogResolution,
    ProviderCode,
    SourceRef,
)


class CatalogStore(Protocol):
    """The persistence port. ``psycopg.Error`` raised by any method means a retryable database failure."""

    def resolve_source_identity(self, provider: ProviderCode, source_url: str, external_id: str | None) -> SourceIdentity: ...

    def touch_source(self, provider: ProviderCode, source_id: UUID, observed_at: datetime) -> bool: ...  # False: Source vanished / not this provider

    def find_books_by_isbn(self, values: Sequence[str]) -> list[UUID]: ...

    def persist_new_source(
        self,
        provider: ProviderCode,
        draft: BookDraft,
        now: datetime,
        attach_to_book_id: UUID | None,
    ) -> SourceRef: ...


class FailureReason(StrEnum):
    DATABASE_ERROR = "database_error"
    SOURCE_IDENTITY_CONFLICT = "source_identity_conflict"


@dataclass(frozen=True)
class CatalogItem:
    provider: ProviderCode
    source_url: str
    external_id: str | None = None


@dataclass(frozen=True)
class DraftFailure:
    """Returned by the caller's ``fetch_draft``. ``retryable=False`` is a final skip without retry."""

    reason: str  # the caller's vocabulary, e.g. "fetch_error", "parse_error", "restricted_book"
    message: str
    retryable: bool


@dataclass(frozen=True)
class ItemResolved:
    source_ref: SourceRef
    resolution: CatalogResolution
    attempts: int  # 0 for an existing Source; else the attempt that wrote / recovered it
    matched_book_ids: tuple[UUID, ...] = ()
    recovered_commit: bool = False  # an earlier attempt's commit was found on re-resolve
    identity_warning: str | None = None


@dataclass(frozen=True)
class ItemFailed:
    reason: str  # FailureReason value or the DraftFailure.reason
    message: str
    attempts: int


def _no_failure_event(attempt: int, reason: str, message: str) -> None:
    return None


def resolve_item(
    store: CatalogStore,
    item: CatalogItem,
    fetch_draft: Callable[[int], BookDraft | DraftFailure],
    *,
    clock: Callable[[], datetime],
    attempts: Callable[[], Iterable[int]],
    on_attempt_failed: Callable[[int, str, str], None] = _no_failure_event,
) -> ItemResolved | ItemFailed:
    identity = store.resolve_source_identity(item.provider, item.source_url, item.external_id)
    if identity.kind is IdentityKind.CONFLICT:
        return ItemFailed(FailureReason.SOURCE_IDENTITY_CONFLICT, identity.reason or "", attempts=0)
    if identity.kind is IdentityKind.EXISTING:
        assert identity.ref is not None
        return _touch_existing(store, item, identity, clock, attempts, on_attempt_failed)
    return _resolve_new(store, item, fetch_draft, clock, attempts, on_attempt_failed)


def _touch_existing(
    store: CatalogStore,
    item: CatalogItem,
    identity: SourceIdentity,
    clock: Callable[[], datetime],
    attempts: Callable[[], Iterable[int]],
    on_attempt_failed: Callable[[int, str, str], None],
) -> ItemResolved | ItemFailed:
    assert identity.ref is not None
    source_id = identity.ref.source_id
    last_attempt = 0
    last_message = ""
    for attempt in attempts():
        try:
            touched = store.touch_source(item.provider, source_id, clock())
        except psycopg.Error as exc:
            last_attempt, last_message = attempt, str(exc)
            on_attempt_failed(attempt, FailureReason.DATABASE_ERROR, last_message)
            continue
        if not touched:
            return ItemFailed(
                FailureReason.SOURCE_IDENTITY_CONFLICT,
                f"Book Source {source_id} vanished or is not a {item.provider} Source",
                attempts=attempt,
            )
        return ItemResolved(
            identity.ref,
            CatalogResolution.EXISTING,
            attempts=0,
            identity_warning=identity.warning,
        )
    return ItemFailed(FailureReason.DATABASE_ERROR, last_message, attempts=last_attempt)


def _resolve_new(
    store: CatalogStore,
    item: CatalogItem,
    fetch_draft: Callable[[int], BookDraft | DraftFailure],
    clock: Callable[[], datetime],
    attempts: Callable[[], Iterable[int]],
    on_attempt_failed: Callable[[int, str, str], None],
) -> ItemResolved | ItemFailed:
    draft: BookDraft | None = None
    last_reason = ""
    last_message = ""
    last_attempt = 0
    maybe_committed = False

    for attempt in attempts():
        if draft is None:
            fetched = fetch_draft(attempt)
            if isinstance(fetched, DraftFailure):
                if not fetched.retryable:
                    return ItemFailed(fetched.reason, fetched.message, attempts=attempt)
                last_attempt, last_reason, last_message = attempt, fetched.reason, fetched.message
                on_attempt_failed(attempt, fetched.reason, fetched.message)
                continue
            draft = fetched

        if maybe_committed:
            # An earlier persist may have committed before the client saw the result. Look again first.
            try:
                committed = store.resolve_source_identity(item.provider, item.source_url, item.external_id)
            except psycopg.Error as exc:
                last_attempt, last_reason, last_message = attempt, FailureReason.DATABASE_ERROR, str(exc)
                on_attempt_failed(attempt, FailureReason.DATABASE_ERROR, last_message)
                continue
            if committed.kind is IdentityKind.EXISTING:
                assert committed.ref is not None
                return ItemResolved(
                    committed.ref,
                    CatalogResolution.EXISTING,
                    attempts=attempt,
                    recovered_commit=True,
                )
            if committed.kind is IdentityKind.CONFLICT:
                return ItemFailed(FailureReason.SOURCE_IDENTITY_CONFLICT, committed.reason or "", attempts=attempt)
            maybe_committed = False  # NEW: the earlier attempt left no Source, so retry the write

        try:
            matches = store.find_books_by_isbn([identifier.identifier_value for identifier in draft.identifiers])
        except psycopg.Error as exc:
            last_attempt, last_reason, last_message = attempt, FailureReason.DATABASE_ERROR, str(exc)
            on_attempt_failed(attempt, FailureReason.DATABASE_ERROR, last_message)
            continue

        if len(matches) == 1:
            resolution = CatalogResolution.ISBN_ATTACHED
            attach_to = matches[0]
        else:
            resolution = CatalogResolution.AMBIGUOUS_CREATED if len(matches) >= 2 else CatalogResolution.IMPORTED
            attach_to = None

        try:
            ref = store.persist_new_source(item.provider, draft, clock(), attach_to)
        except psycopg.Error as exc:
            maybe_committed = True
            last_attempt, last_reason, last_message = attempt, FailureReason.DATABASE_ERROR, str(exc)
            on_attempt_failed(attempt, FailureReason.DATABASE_ERROR, last_message)
            continue

        return ItemResolved(ref, resolution, attempts=attempt, matched_book_ids=tuple(matches))

    return ItemFailed(last_reason, last_message, attempts=last_attempt)
