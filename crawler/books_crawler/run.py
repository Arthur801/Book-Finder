"""One crawler run: ranking → resolve sources to Books → replace bestsellers (crawler.md §5, §14).

Resolution of a discovery item gives a ``CatalogResolution`` (crawler.md §6):
1. Known BOOKS_COM_TW Book Source URL → reuse its Book, no detail request (``EXISTING``).
2. Unknown URL → fetch and parse the detail page, then match its normalized ISBN values (data-model §7.1)
   against the distinct Books that own an ``ISBN`` identifier (§7.2, only ``ISBN`` since migration 011):
   a. no Book → create a new Book (``IMPORTED``);
   b. exactly one Book → attach a new BOOKS_COM_TW Book Source to it, and in the same transaction fill
      only its NULL columns, a missing AUTHOR, its identifiers and the source's subjects (§7.4)
      (``ISBN_ATTACHED``);
   c. two or more Books → create a new Book and log an INFO line; no existing Book changes
      (``AMBIGUOUS_CREATED``).
   A draft without any ISBN value is always a new Book (``IMPORTED``).

Retry and skip (crawler.md §13.1). A new source gets at most ``MAX_ATTEMPTS`` attempts in total:

- a fetch or parse failure is retried from the detail request (the page is fetched again);
- a failure of the database write (ISBN lookup or the Book transaction) is retried with the
  already-parsed draft; the detail page is not fetched again.

A row that still fails is skipped: no rows are written for it, and the snapshot keeps the other
ranks' numbers. The ranking page is retried on fetch failure only and is never skipped (crawler.md §14.1).

The resolver always commits the Catalog side of an item (its Source, its gap filling, its touch). It does
not decide whether the item may be ranked: a Book may appear at most once in a ranking
(``bestsellers.book_id`` is unique), so when a later rank resolves to a Book already used by an earlier
rank, ``RunLedger`` decides ``DUPLICATE_BOOK`` and skips that rank without retrying (crawler.md §14.2).

A browser that cannot be started raises ``BrowserUnavailableError``. That is not a ``FetchError``,
so it is neither retried nor skipped per row: it fails the whole run.

Every item outcome goes, in rank order, to a ``RunLedger`` (``ledger.py``), which owns the counters, the
ranking decision, the consecutive-error streak and abort, the snapshot rows and the final status. This
module only does the I/O: fetching, parsing, writing and publishing.

Pages mode (``run_pages``, crawler.md §15) is the exception to the ranking rules: its rows go to a
``PagesLedger`` instead, which keeps the counters and status but has no rank order, no snapshot, no
duplicate-Book rule and no consecutive-error limit. A category page that cannot be fetched or parsed
is skipped, not retried into a failed run.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg

from books_crawler import db
from books_crawler.fetcher import Fetcher, FetchError
from books_crawler.identity import IdentityKind
from books_crawler.ledger import PagesLedger, RunLedger, RunReport
from books_crawler.models import (
    BookDraft,
    CatalogResolution,
    Failure,
    JobName,
    RankingRow,
    ResolvedRow,
    SkippedPage,
    SkippedRow,
    SkipReason,
    SourceRef,
)
from books_crawler.parsers import (
    RANKING_PAGE_URL,
    DetailParser,
    RankingParser,
    RestrictedBookError,
)
from books_crawler.ranking import validate_ranking
from books_crawler.redact import redact
from books_crawler.session import DatabaseSession

log = logging.getLogger("books_crawler.run")

MAX_ATTEMPTS = 3  # crawler.md §13.1: total attempts, first try included
BACKOFF_BASE_SECONDS = 1.0  # sleep before attempt n (n = 2, 3) is 1s, then 2s


@dataclass(frozen=True)
class _RestrictedPage:
    """Detail step outcome: a restricted member page. Skipped without retry (crawler.md §13.2)."""

    message: str


@dataclass(frozen=True)
class _WrittenSource:
    """Write step outcome: the new source was written, with its Catalog resolution (data-model §7.2)."""

    ref: SourceRef
    resolution: CatalogResolution
    matched_book_ids: tuple[UUID, ...]


def utc_now() -> datetime:
    return datetime.now(UTC)


def backoff_seconds(attempt: int) -> float:
    """Seconds to wait before ``attempt`` (2 or 3): 1s, then 2s (crawler.md §13.1)."""
    return BACKOFF_BASE_SECONDS * 2 ** (attempt - 2)


def _attempts(deps: RunDependencies) -> Iterator[int]:
    """The shared retry loop: yields attempt numbers 1..MAX_ATTEMPTS, sleeping the backoff before each retry.

    The caller decides what is retryable: it ``continue``s on a retryable failure and returns on success.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt > 1:
            deps.sleep(backoff_seconds(attempt))
        yield attempt


@dataclass
class RunDependencies:
    fetcher: Fetcher
    parse_ranking: RankingParser
    parse_detail: DetailParser
    connect: Callable[[], psycopg.Connection]
    clock: Callable[[], datetime] = utc_now
    # Injected so that retry backoff never really waits in tests.
    sleep: Callable[[float], None] = time.sleep


def format_report(report: RunReport) -> str:
    """One line per run for stdout (crawler.md §19.2, §15.8). ``skipped`` is a JSON list of the skipped rows.

    Pages mode (``pages_total`` is set) reports its page and row counters instead of the ranking
    counters, and adds ``skipped_pages`` (crawler.md §15.8). The field order is the one of the spec.
    """
    fields: dict[str, Any] = {
        "run_id": report.run_id,
        "provider_code": report.provider_code,
        "job_name": report.job_name,
        "started_at": report.started_at.isoformat(),
        "finished_at": report.finished_at.isoformat(),
        "status": report.status,
    }
    if report.pages_total is None:
        fields["ranking_count"] = report.ranking_count
    else:
        fields["pages_total"] = report.pages_total
        fields["pages_skipped"] = len(report.skipped_pages)
        fields["rows_seen"] = report.rows_seen
    fields.update(
        {
            "items_seen": report.items_seen,
            "existing_book_count": report.existing_book_count,
            "new_book_count": report.new_book_count,
            "attached_source_count": report.attached_source_count,
            "existing_source_count": report.existing_source_count,
            "new_source_count": report.new_source_count,
            "ambiguous_isbn_count": report.ambiguous_isbn_count,
            "offer_updated_count": report.offer_updated_count,
            "skipped_count": report.skipped_count,
            "restricted_book_count": report.restricted_book_count,
            "error_count": report.error_count,
        }
    )
    if report.pages_total is None:
        fields["consecutive_error_count"] = report.consecutive_error_count
        fields["aborted_at_rank"] = "none" if report.aborted_at_rank is None else report.aborted_at_rank
    fields["exit_code"] = report.exit_code
    line = " ".join(f"{key}={value}" for key, value in fields.items())
    skipped = [
        {
            "rank": item.rank,
            "url": item.url,
            "error_type": item.failure.error_type,
            "error_message": item.failure.error_message,
            "attempts": item.failure.attempts,
        }
        for item in report.skipped
    ]
    line += f" skipped={json.dumps(skipped, ensure_ascii=False)}"
    if report.pages_total is not None:
        skipped_pages = [
            {
                "url": item.url,
                "error_type": item.failure.error_type,
                "error_message": item.failure.error_message,
                "attempts": item.failure.attempts,
            }
            for item in report.skipped_pages
        ]
        line += f" skipped_pages={json.dumps(skipped_pages, ensure_ascii=False)}"
    if report.error:
        line += f" error={report.error!r}"
    return redact(line)


def _failure(reason: SkipReason, message: str, attempts: int) -> Failure:
    """Every stored error message is redacted here, so no later log line can leak a secret."""
    return Failure(error_type=reason, error_message=redact(message), attempts=attempts)


def _skipped(row: RankingRow, failure: Failure) -> SkippedRow:
    return SkippedRow(rank=row.rank, url=row.url, failure=failure)


def _fetch_page_with_retries(deps: RunDependencies, url: str, label: str = "ranking page") -> str:
    """Fetch a ranking-style page with the shared retry loop (crawler.md §14.1, §15.4).

    Returns the HTML, or raises FetchError after MAX_ATTEMPTS failed attempts. What that
    error means is up to the caller: the daily and first-book runs fail on it, pages mode skips the
    category page. label names the page in the log and in the error text.
    """
    last_error: FetchError | None = None
    for attempt in _attempts(deps):
        try:
            return deps.fetcher.get(url)
        except FetchError as exc:
            last_error = exc
            log.warning("%s attempt %d/%d failed: %s", label, attempt, MAX_ATTEMPTS, redact(str(exc)))
    raise FetchError(f"{label} failed after {MAX_ATTEMPTS} attempts: {last_error}") from last_error


def _log_attempt_failed(row: RankingRow, attempt: int, failure: Failure) -> None:
    log.warning(
        "rank %d attempt %d/%d failed (%s): %s",
        row.rank,
        attempt,
        MAX_ATTEMPTS,
        failure.error_type,
        failure.error_message,
    )


def _fetch_and_parse(
    row: RankingRow,
    deps: RunDependencies,
    attempt: int,
) -> BookDraft | _RestrictedPage | Failure:
    """Detail request and parse. Returns the outcome; a ``Failure`` is retried by the caller with a new request."""
    try:
        html = deps.fetcher.get(row.url)
    except FetchError as exc:
        return _failure(SkipReason.FETCH_ERROR, str(exc), attempt)
    try:
        return deps.parse_detail(html, row.url)
    except RestrictedBookError as exc:
        return _RestrictedPage(str(exc))
    except ValueError as exc:
        # Classification: ParseError (e.g. missing title or product container) and BookDraft
        # validation both raise ValueError; they are a retryable parse_error (crawler.md §13.1).
        return _failure(SkipReason.PARSE_ERROR, str(exc), attempt)


@dataclass(frozen=True)
class _WriteFailure:
    """A failed write step. ``maybe_committed``: the Book transaction may have committed before the client saw it (§13.1)."""

    failure: Failure
    maybe_committed: bool


def _touch_with_retries(session: DatabaseSession, row: RankingRow, source_id: UUID, deps: RunDependencies) -> Failure | None:
    """``last_seen_at`` touch of an existing Source (crawler.md §6.1): DB retry rule, no detail refetch.

    Each attempt uses the run's session, which reconnects when the connection is broken (crawler.md §13.1).
    Returns None on success, or the database failure after the last attempt.
    """
    last_failure: Failure | None = None
    for attempt in _attempts(deps):
        try:
            db.touch_source(session.conn, source_id, deps.clock())
            return None
        except psycopg.Error as exc:
            last_failure = _failure(SkipReason.DATABASE_ERROR, str(exc), attempt)
            _log_attempt_failed(row, attempt, last_failure)
    assert last_failure is not None  # the loop runs at least once and only continues on failure
    return last_failure


def _write_new_source(
    session: DatabaseSession,
    draft: BookDraft,
    deps: RunDependencies,
    attempt: int,
) -> _WrittenSource | _WriteFailure:
    """ISBN match and the Book transaction for one parsed draft (data-model §7.2). Database errors are retryable.

    Exactly one matching Book attaches the source (ISBN_ATTACHED, with gap filling); none creates a
    Book (IMPORTED); two or more create a Book (AMBIGUOUS_CREATED). The source is written even when its
    Book is already used by an earlier rank: that decision is the ledger's (crawler.md §14.2).
    """
    values = [item.identifier_value for item in draft.identifiers]
    try:
        matches = db.find_books_by_isbn(session.conn, values)
    except psycopg.Error as exc:
        return _WriteFailure(_failure(SkipReason.DATABASE_ERROR, str(exc), attempt), maybe_committed=False)

    if len(matches) == 1:
        resolution = CatalogResolution.ISBN_ATTACHED
        attach_to = matches[0]
    else:
        resolution = CatalogResolution.AMBIGUOUS_CREATED if len(matches) >= 2 else CatalogResolution.IMPORTED
        attach_to = None
    try:
        ref = db.persist_new_source(session.conn, draft, deps.clock(), attach_to_book_id=attach_to)
    except psycopg.Error as exc:
        return _WriteFailure(_failure(SkipReason.DATABASE_ERROR, str(exc), attempt), maybe_committed=True)
    return _WrittenSource(ref, resolution, tuple(matches))


def _resolve_row(
    session: DatabaseSession,
    row: RankingRow,
    deps: RunDependencies,
) -> ResolvedRow | SkippedRow:
    """Resolve one ranking row to a Catalog outcome, or fail it (crawler.md §6, §13).

    Returns a ``ResolvedRow`` with its ``CatalogResolution`` (the Catalog side is committed), or a
    ``SkippedRow`` (``RESTRICTED`` or ``FAILED``). Whether a resolved Book may be ranked is decided by
    ``RunLedger``, not here.

    The source identity lookup is not retried (crawler.md §6.1): a connection error there fails the run.
    Retries after a write re-resolve the identity first (crawler.md §13.1): if the earlier attempt had
    committed, the Source is reported as EXISTING and is not inserted again.
    """
    identity = db.resolve_source_identity(session.conn, row.url)
    if identity.kind is IdentityKind.CONFLICT:
        log.warning("rank %d source identity conflict, not written: %s: %s", row.rank, row.url, identity.reason)
        return _skipped(row, _failure(SkipReason.SOURCE_IDENTITY_CONFLICT, identity.reason or "", attempts=0))
    if identity.kind is IdentityKind.EXISTING:
        # The detail page is never fetched for a known URL (attempts = 0); the touch is its only write.
        assert identity.ref is not None
        if identity.warning is not None:
            log.warning("rank %d %s: %s", row.rank, row.url, identity.warning)
        touch_failure = _touch_with_retries(session, row, identity.ref.source_id, deps)
        if touch_failure is not None:
            return _skipped(row, touch_failure)
        return ResolvedRow(rank=row.rank, url=row.url, source_ref=identity.ref, resolution=CatalogResolution.EXISTING)

    draft: BookDraft | None = None
    last_failure: Failure | None = None
    maybe_committed = False
    for attempt in _attempts(deps):
        if draft is None:
            fetched = _fetch_and_parse(row, deps, attempt)
            if isinstance(fetched, _RestrictedPage):
                log.info("rank %d restricted product skipped without retry: %s", row.rank, row.url)
                return _skipped(row, _failure(SkipReason.RESTRICTED_BOOK, fetched.message, attempts=attempt))
            if isinstance(fetched, Failure):
                last_failure = fetched
                _log_attempt_failed(row, attempt, fetched)
                continue
            draft = fetched

        if maybe_committed:
            # An earlier write may have committed before the client saw the result. Look again before writing.
            try:
                committed = db.resolve_source_identity(session.conn, row.url)
            except psycopg.Error as exc:
                last_failure = _failure(SkipReason.DATABASE_ERROR, str(exc), attempt)
                _log_attempt_failed(row, attempt, last_failure)
                continue
            if committed.kind is IdentityKind.EXISTING:
                # Reported as EXISTING: the original resolution is not stored, so it cannot be recovered (§13.1).
                # The NULL fill was in the same transaction and is not repeated.
                assert committed.ref is not None
                log.info("rank %d: the Source was committed by an earlier attempt; not inserted again: %s", row.rank, row.url)
                return ResolvedRow(
                    rank=row.rank,
                    url=row.url,
                    source_ref=committed.ref,
                    resolution=CatalogResolution.EXISTING,
                    attempts=attempt,
                )
            maybe_committed = False

        written = _write_new_source(session, draft, deps, attempt)
        if isinstance(written, _WriteFailure):
            last_failure = written.failure
            maybe_committed = written.maybe_committed
            _log_attempt_failed(row, attempt, last_failure)
            continue

        isbn_text = ",".join(item.identifier_value for item in draft.identifiers)
        if written.resolution is CatalogResolution.ISBN_ATTACHED:
            log.info(
                "attached BOOKS_COM_TW source to existing Book: rank=%d url=%s matched=ISBN:%s book_id=%s",
                row.rank,
                row.url,
                isbn_text,
                written.matched_book_ids[0],
            )
        elif written.resolution is CatalogResolution.AMBIGUOUS_CREATED:
            log.info(
                "ambiguous ISBN match, created a new Book: rank=%d url=%s isbn=%s matched_book_ids=%s",
                row.rank,
                row.url,
                isbn_text,
                ",".join(str(item) for item in written.matched_book_ids),
            )
        return ResolvedRow(
            rank=row.rank,
            url=row.url,
            source_ref=written.ref,
            resolution=written.resolution,
            attempts=attempt,
        )

    assert last_failure is not None  # the loop runs at least once and only continues on failure
    return _skipped(row, last_failure)


def run_first_book(deps: RunDependencies, run_id: str | None = None) -> RunReport:
    """Import only rank 1 into the catalog; never replace the bestseller snapshot.

    The ranking page is still validated in full. Resolution, normalization, ISBN matching,
    transactions and retry rules are shared with the daily crawler.
    """
    started_at = deps.clock()
    # Limit 0: a general error on the only row fails the import; a restricted page is a partial success.
    ledger = RunLedger(max_consecutive_errors=0)
    ranking_count = 0
    error: str | None = None
    try:
        rows = validate_ranking(deps.parse_ranking(_fetch_page_with_retries(deps, RANKING_PAGE_URL)))
        ranking_count = len(rows)
        row = rows[0]
        with DatabaseSession(deps.connect) as session:
            outcome = _resolve_row(session, row, deps)
        ledger.record(outcome)
        if isinstance(outcome, ResolvedRow):
            ref = outcome.source_ref
            log.info("rank=1 url=%s book_id=%s source_id=%s", row.url, ref.book_id, ref.source_id)
    except Exception as exc:  # noqa: BLE001 - a run failure is recorded in the report, not raised
        error = redact(f"{type(exc).__name__}: {exc}")
    report = ledger.report(
        run_id=run_id or str(uuid.uuid4()),
        job_name=JobName.FIRST_BOOK,
        started_at=started_at,
        finished_at=deps.clock(),
        ranking_count=ranking_count,
        error=error,
    )
    if report.error:
        log.error("first-book import failed: %s", report.error)
    log.info("mode=first-book %s", format_report(report))
    return report


def run_once(deps: RunDependencies, run_id: str | None = None) -> RunReport:
    """Execute one crawl. Never raises: failures are reported through ``RunReport``."""
    started_at = deps.clock()
    ledger = RunLedger()
    ranking_count = 0
    error: str | None = None
    try:
        html = _fetch_page_with_retries(deps, RANKING_PAGE_URL)
        rows = validate_ranking(deps.parse_ranking(html))
        ranking_count = len(rows)

        with DatabaseSession(deps.connect) as session:
            for row in rows:
                ledger.record(_resolve_row(session, row, deps))
                if ledger.aborted:
                    break
            if not ledger.aborted:
                db.replace_bestsellers(session.conn, ledger.snapshot, captured_at=deps.clock())
    except Exception as exc:  # noqa: BLE001 - any failure fails the run; the previous bestsellers are untouched
        error = redact(f"{type(exc).__name__}: {exc}")

    report = ledger.report(
        run_id=run_id or str(uuid.uuid4()),
        job_name=JobName.DAILY_BESTSELLER,
        started_at=started_at,
        finished_at=deps.clock(),
        ranking_count=ranking_count,
        error=error,
    )
    if report.error:  # one ERROR line per failed run, abort included
        log.error("run failed: %s", report.error)
    log.info("%s", format_report(report))
    return report


def run_pages(deps: RunDependencies, page_urls: Sequence[str], run_id: str | None = None) -> RunReport:
    """Supplement the Catalog from category 7-day ranking pages (crawler.md §15, pages mode).

    The pages are not the bestseller ranking: nothing is written to ``bestsellers``. Existing Sources
    are touched (``last_seen_at``) exactly as in the daily run (§15). Rows are resolved with the rules of the daily run (§6, §13), but a
    row failure never stops the run. A page that cannot be fetched (after ``MAX_ATTEMPTS``) or
    parsed is recorded as a skipped page and the run goes on. The run fails only when it cannot
    continue: an error escaping row resolution (for example the database), ``BrowserUnavailableError``,
    or every page skipped. Pages already written stay written (one transaction per Book).
    Never raises: failures are reported through ``RunReport``.
    """
    started_at = deps.clock()
    ledger = PagesLedger()
    error: str | None = None
    try:
        with DatabaseSession(deps.connect) as session:
            for page_url in page_urls:
                log.info("importing page: %s", page_url)
                try:
                    rows = deps.parse_ranking(_fetch_page_with_retries(deps, page_url, "category page"))
                except FetchError as exc:
                    failure = _failure(SkipReason.FETCH_ERROR, str(exc), MAX_ATTEMPTS)
                    ledger.record_page_skipped(SkippedPage(url=page_url, failure=failure))
                    continue
                except ValueError as exc:  # ParseError: the page is not a category ranking page
                    failure = _failure(SkipReason.PARSE_ERROR, str(exc), attempts=1)
                    ledger.record_page_skipped(SkippedPage(url=page_url, failure=failure))
                    continue
                ledger.record_page_ok()
                for row in rows:
                    # No ranking decision on pages: the same Book may appear on several pages.
                    ledger.record(_resolve_row(session, row, deps))
    except Exception as exc:  # noqa: BLE001 - the run cannot continue; the Catalog keeps what was already committed
        error = redact(f"{type(exc).__name__}: {exc}")

    report = ledger.report(
        run_id=run_id or str(uuid.uuid4()),
        job_name=JobName.CATEGORY_PAGES,
        started_at=started_at,
        finished_at=deps.clock(),
        error=error,
    )
    if report.error:  # one ERROR line per failed run
        log.error("pages import failed: %s", report.error)
    log.info("mode=pages %s", format_report(report))
    return report
