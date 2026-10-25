"""Command-line entry point for the Kingstone (金石堂) category run: ``python -m kingstone`` (run from ``crawler/``).

Composition only: it reads and validates the settings, builds the real fetcher and the database store, and runs
``kingstone.run.run_pages`` once. Parsing, the write policy and the terminal status are not decided here.

Environment:
    DATABASE_URL                    PostgreSQL URL of the shared database (required; secret, never logged).
    KINGSTONE_PAGES_FILE            Category list page file (default ``crawler/kingstone-pages.txt``).
    KINGSTONE_WRITE_POLICY          ``normal`` (default) or ``new-books-only``.
    KINGSTONE_SOFT_RUN_BUDGET_SECONDS  Soft run budget (default 7200); no request starts once it runs out.
    CRAWLER_RUN_HARD_LIMIT_SECONDS  The hard run limit (default 9000); the soft budget must be below it.
    KINGSTONE_HTTP_TIMEOUT_SECONDS, KINGSTONE_HTTP_MAX_ATTEMPTS, KINGSTONE_MAX_RESPONSE_BYTES
                                    HTTP settings (defaults in ``kingstone.acquisition``).
    KINGSTONE_ARTIFACTS_DIR         Root of the run artifacts (default ``crawler/artifacts``; see ``kingstone.artifacts``).
    KINGSTONE_DIAGNOSTIC_MAX_BYTES  Size cap of one saved diagnostic HTML file (default 2 MiB).

Exit codes:
    0 = SUCCESS or PARTIAL_SUCCESS,
    1 = FAILED (the run could not continue, the provider registry could not be read, or the database was busy:
        a migration holds the Catalog lock, see ``catalog_core.migration_lock``),
    2 = configuration error: DATABASE_URL, a setting, the page list, a disabled or unregistered provider, or a
        missing post-011 schema prerequisite (``SCHEMA_PREREQUISITE_MISSING``).
        Each of these is checked before the fetcher is built, so a configuration error sends no request.

Database order (plan v12 §8): the first connection takes the shared migration lock, then the schema is checked
read-only, and only then is the fetcher built and the run started. A busy lock or a missing prerequisite makes no
request and no write.

The hard limit (``CRAWLER_RUN_HARD_LIMIT_SECONDS``) is enforced by the runner's watchdog (Phase 6). This module only
validates the value and keeps the soft budget below it.

Artifacts (plan v12 §8). Every terminal result after the configuration is loaded writes ``kingstone/last-run.json``
and a history entry: the full report of a run, or the minimal pre-run record for the results before or instead of
one (a page list, provider, schema or lock problem, a database connection problem). A configuration that is invalid
(or an environment without DATABASE_URL) writes nothing, because the artifacts directory is then unknown. Every such
terminal record is also printed to stdout as one JSON line (``json.dumps(record, ensure_ascii=False, sort_keys=True)``),
before the artifact files are written, so the line is there even when a write fails. It is the same record as
``last-run.json``. When the alert reasons are not empty, one ``ALERT`` line is logged on ``kingstone.cli``. Artifact
failures are logged and never change the exit code.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

import psycopg

from catalog_core import persistence
from catalog_core.migration_lock import MigrationLockBusy
from catalog_core.models import ProviderCode
from catalog_core.normalize import ensure_runtime_unicode_supported
from catalog_core.redact import redact
from catalog_core.session import DatabaseSession
from catalog_core.store import SessionCatalogStore
from kingstone.acquisition import KingstoneFetcher
from kingstone.alerts import BUSY_REASON, SCHEMA_REASON
from kingstone.artifacts import KingstoneArtifacts, record_from_report, record_pre_run
from kingstone.config import KingstoneConfig, KingstoneConfigError, load_config
from kingstone.diagnostics import DiagnosticWriter
from kingstone.ledger import KingstoneReport, RunStatus
from kingstone.page_list import PageListError, load_page_urls
from kingstone.run import KingstoneFetcherPort, KingstoneRunDependencies, SoftBudget, run_pages

EXIT_FAILED = 1
EXIT_CONFIG_ERROR = 2
PROVIDER = ProviderCode.KINGSTONE


def configure_logging() -> logging.Logger:
    """Send ``kingstone`` and ``catalog_core`` logs to stdout at INFO. Own handler: the Books entry point is not imported."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger("kingstone")
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    core = logging.getLogger("catalog_core")
    core.handlers[:] = [handler]
    core.setLevel(logging.INFO)
    return root


def _default_fetcher(config: KingstoneConfig, budget: SoftBudget) -> KingstoneFetcher:
    """The production fetcher. The budget is the same clock the run checks, so both guards read one budget."""
    return KingstoneFetcher(
        timeout=config.http_timeout_seconds,
        max_attempts=config.http_max_attempts,
        max_response_bytes=config.max_response_bytes,
        budget_remaining=budget.remaining,
    )


class _RunRecorder:
    """Writes the terminal record of one run (plan v12 §8). A write failure is logged and never changes the exit code."""

    def __init__(self, artifacts: KingstoneArtifacts, *, write_policy: str, clock: Callable[[], datetime]) -> None:
        self.run_id = str(uuid.uuid4())
        self.artifacts = artifacts
        self._write_policy = write_policy
        self._clock = clock
        self._started_at = clock()
        self._log = logging.getLogger("kingstone.cli")

    def pre_run(self, *, status: str, exit_code: int, reason: str | None = None, error: str | None = None) -> int:
        """A result before or instead of the run. Returns ``exit_code`` so the caller can return it."""
        record = record_pre_run(
            run_id=self.run_id,
            status=status,
            exit_code=exit_code,
            reason=reason,
            write_policy=self._write_policy,
            started_at=self._started_at,
            finished_at=self._clock(),
            error=error,
        )
        self._publish(record)
        return exit_code

    def finished(self, report: KingstoneReport) -> int:
        """The result of a run that went through ``run_pages``. Returns the report's exit code."""
        self._publish(record_from_report(report))
        return report.exit_code

    def _publish(self, record: Mapping[str, object]) -> None:
        try:
            final = self.artifacts.finalize(dict(record))
        except Exception as exc:  # noqa: BLE001 - the record is built from our own facts; log and keep the exit code
            self._log.error("could not build the kingstone run record: %s: %s", type(exc).__name__, redact(str(exc)))
            return
        # The one terminal line on stdout. print, not logging: the line is raw JSON, so json.loads() reads it directly.
        print(json.dumps(final, ensure_ascii=False, sort_keys=True), flush=True)
        self.artifacts.write(final)  # never raises; a failure is logged there
        reasons = final["alert_reasons"]
        if reasons:
            self._log.warning("ALERT reasons=%s last_run=%s", ",".join(reasons), self.artifacts.last_run_path)


def main(
    environ: Mapping[str, str] | None = None,
    *,
    provider_enabled: Callable[[str, ProviderCode], bool | None] | None = None,
    fetcher_factory: Callable[[KingstoneConfig, SoftBudget], KingstoneFetcherPort] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    configure_logging()
    log = logging.getLogger("kingstone.cli")
    env = os.environ if environ is None else environ

    # Fail fast on a runtime whose Unicode data would give wrong ISBN keys (data-model 7.1).
    try:
        ensure_runtime_unicode_supported()
    except RuntimeError as exc:
        log.error("%s", exc)
        return EXIT_CONFIG_ERROR

    database_url = env.get("DATABASE_URL", "").strip()
    if not database_url:
        log.error("DATABASE_URL is not set; nothing was crawled")
        return EXIT_CONFIG_ERROR

    try:
        config = load_config(env)
    except KingstoneConfigError as exc:
        log.error("%s", redact(str(exc)))
        return EXIT_CONFIG_ERROR

    recorder = _RunRecorder(KingstoneArtifacts(config.artifacts_dir), write_policy=config.write_policy.value, clock=clock)

    # The page list is read and validated before the fetcher exists, so an invalid list makes no request at all.
    try:
        page_urls = load_page_urls(config.pages_file)
    except PageListError as exc:
        log.error("%s", redact(str(exc)))
        return recorder.pre_run(status=RunStatus.FAILED.value, exit_code=EXIT_CONFIG_ERROR, error=redact(str(exc)))

    # A disabled (or unregistered) provider is a configuration error: nothing is fetched (crawler.md §3.1, §14.5).
    try:
        check = provider_enabled or persistence.provider_enabled  # resolved per call so tests can replace it
        enabled = check(database_url, PROVIDER)
    except psycopg.Error as exc:
        log.error("could not read source_providers: %s", redact(str(exc)))
        return recorder.pre_run(status=RunStatus.FAILED.value, exit_code=EXIT_FAILED, error=redact(f"could not read source_providers: {exc}"))
    if enabled is not True:
        log.error("source provider %s is disabled or not registered; nothing was crawled", PROVIDER)
        return recorder.pre_run(
            status=RunStatus.FAILED.value,
            exit_code=EXIT_CONFIG_ERROR,
            error=f"source provider {PROVIDER} is disabled or not registered",
        )

    budget = SoftBudget(config.soft_budget_seconds, monotonic)
    with DatabaseSession(lambda: persistence.connect(database_url)) as session:
        # The first connection takes the shared migration lock; the schema is checked before anything is fetched.
        try:
            missing = persistence.missing_schema_prerequisites(session.conn)
        except MigrationLockBusy:
            log.error("maintenance busy: a database migration holds the Catalog lock; nothing was crawled")
            return recorder.pre_run(status=RunStatus.FAILED.value, exit_code=EXIT_FAILED, reason=BUSY_REASON)
        except psycopg.Error as exc:
            log.error("could not connect to the database or check its schema: %s", redact(str(exc)))
            return recorder.pre_run(
                status=RunStatus.FAILED.value,
                exit_code=EXIT_FAILED,
                error=redact(f"could not connect to the database or check its schema: {exc}"),
            )
        if missing:
            log.error("SCHEMA_PREREQUISITE_MISSING: %s", redact("; ".join(missing)))
            return recorder.pre_run(
                status=RunStatus.FAILED.value,
                exit_code=EXIT_CONFIG_ERROR,
                reason=SCHEMA_REASON,
                error=redact("; ".join(missing)),
            )

        fetcher = (fetcher_factory or _default_fetcher)(config, budget)
        log.info("using the kingstone HTTP fetcher; write policy %s", config.write_policy.value)

        # The fetcher must be closed however the run ends: normal result, FAILED, or an exception.
        try:
            deps = KingstoneRunDependencies(
                fetcher=fetcher,
                store=SessionCatalogStore(session),
                budget=budget,
                clock=clock,
                sleep=time.sleep,
                write_policy=config.write_policy,
                diagnostics=DiagnosticWriter(recorder.artifacts.diagnostics_dir, max_bytes=config.diagnostic_max_bytes),
            )
            report = run_pages(deps, page_urls, run_id=recorder.run_id)
        finally:
            fetcher.close()
    return recorder.finished(report)


if __name__ == "__main__":
    raise SystemExit(main())
