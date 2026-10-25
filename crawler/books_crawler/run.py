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

The per-row resolution above is implemented by ``catalog_core.service.resolve_item``; this module supplies the
Books fetch and parse step and the log lines.

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

import psycopg

from books_crawler import db
from books_crawler.fetcher import Fetcher, FetchError
from books_crawler.ledger import PagesLedger, RunLedger, RunReport
from books_crawler.models import (
    PROVIDER,
    BookDraft,
    CatalogResolution,
    Failure,
    JobName,
    RankingRow,
    ResolvedRow,
    SkippedPage,
    SkippedRow,
    SkipReason,
)
from books_crawler.parsers import (
    RANKING_PAGE_URL,
    DetailParser,
    RankingParser,
    RestrictedBookError,
)
from books_crawler.ranking import validate_ranking
from books_crawler.redact import redact
from catalog_core.identity import SourceIdentity
from catalog_core.models import ProviderCode
from catalog_core.service import CatalogItem, DraftFailure, FailureReason, ItemFailed, ItemResolved, resolve_item
from catalog_core.session import DatabaseSession
from catalog_core.store import SessionCatalogStore

log = logging.getLogger("books_crawler.run")

MAX_ATTEMPTS = 3  # crawler.md §13.1: total attempts, first try included
BACKOFF_BASE_SECONDS = 1.0  # sleep before attempt n (n = 2, 3) is 1s, then 2s


@dataclass(frozen=True)
class _RestrictedPage:
    """Detail step outcome: a restricted member page. Skipped without retry (crawler.md §13.2)."""

    message: str


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


class _BooksCatalogStore(SessionCatalogStore):
    """The run's store for one ranking row. It logs the URL-drift WARNING at the identity lookup.

    Logging there keeps the WARNING ahead of the touch's attempt lines, so it appears even when the touch
    fails. ``ItemFailed``/``ItemResolved`` also carry the warning, but logging afterwards would place it behind
    those lines. Books has no ``external_id``, so only the first lookup can carry a warning.
    """

    def __init__(self, session: DatabaseSession, row: RankingRow) -> None:
        super().__init__(session)
        self._row = row

    def resolve_source_identity(self, provider: ProviderCode, source_url: str, external_id: str | None) -> SourceIdentity:
        identity = super().resolve_source_identity(provider, source_url, external_id)
        if identity.warning is not None:
            log.warning("rank %d %s: %s", self._row.rank, self._row.url, identity.warning)
        return identity


def _resolve_row(
    session: DatabaseSession,
    row: RankingRow,
    deps: RunDependencies,
) -> ResolvedRow | SkippedRow:
    """Resolve one ranking row through ``catalog_core.service.resolve_item`` (crawler.md §6, §13).

    This adapter supplies the Books fetch/parse step (``_fetch_and_parse``), the retry budget and the log
    lines. Identity, touch, ISBN match, persistence, the retry rules and the re-resolve after a failed write
    are the service's. Returns a ``ResolvedRow`` (the Catalog side is committed) or a ``SkippedRow``.
    Whether a resolved Book may be ranked is decided by ``RunLedger``, not here.
    """
    draft: BookDraft | None = None

    def fetch_draft(attempt: int) -> BookDraft | DraftFailure:
        nonlocal draft
        fetched = _fetch_and_parse(row, deps, attempt)
        if isinstance(fetched, _RestrictedPage):
            log.info("rank %d restricted product skipped without retry: %s", row.rank, row.url)
            return DraftFailure(SkipReason.RESTRICTED_BOOK, fetched.message, retryable=False)
        if isinstance(fetched, Failure):
            return DraftFailure(fetched.error_type, fetched.error_message, retryable=True)
        draft = fetched
        return fetched

    def on_attempt_failed(attempt: int, reason: str, message: str) -> None:
        _log_attempt_failed(row, attempt, _failure(SkipReason(reason), message, attempt))

    result = resolve_item(
        _BooksCatalogStore(session, row),
        CatalogItem(PROVIDER, row.url),
        fetch_draft,
        clock=deps.clock,
        attempts=lambda: _attempts(deps),
        on_attempt_failed=on_attempt_failed,
    )

    if isinstance(result, ItemFailed):
        if result.reason == FailureReason.SOURCE_IDENTITY_CONFLICT:
            log.warning("rank %d source identity conflict, not written: %s: %s", row.rank, row.url, result.message)
        return _skipped(row, _failure(SkipReason(result.reason), result.message, result.attempts))
    # Books never passes a write policy (NORMAL), so the service cannot return a policy skip here.
    assert isinstance(result, ItemResolved)

    isbn_text = "" if draft is None else ",".join(item.identifier_value for item in draft.identifiers)
    if result.recovered_commit:
        # Reported as EXISTING: the original resolution is not stored, so it cannot be recovered (§13.1).
        # The NULL fill was in the same transaction and is not repeated.
        log.info("rank %d: the Source was committed by an earlier attempt; not inserted again: %s", row.rank, row.url)
    elif result.resolution is CatalogResolution.ISBN_ATTACHED:
        assert draft is not None
        log.info(
            "attached BOOKS_COM_TW source to existing Book: rank=%d url=%s matched=ISBN:%s book_id=%s",
            row.rank,
            row.url,
            isbn_text,
            result.matched_book_ids[0],
        )
    elif result.resolution is CatalogResolution.AMBIGUOUS_CREATED:
        assert draft is not None
        log.info(
            "ambiguous ISBN match, created a new Book: rank=%d url=%s isbn=%s matched_book_ids=%s",
            row.rank,
            row.url,
            isbn_text,
            ",".join(str(item) for item in result.matched_book_ids),
        )
    return ResolvedRow(
        rank=row.rank,
        url=row.url,
        source_ref=result.source_ref,
        resolution=result.resolution,
        attempts=result.attempts,
    )


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
