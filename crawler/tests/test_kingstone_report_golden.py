"""Golden output of one Kingstone run: the report line, the terminal record and the log lines (kingstone.run, kingstone.ledger).

A pure-refactor guard. The scenario covers every outcome class at once: a completed page with an Existing touch (with an
identity warning), a new import, an ISBN attach, a failed card (parse_error on the detail page), a skipped list page
(acquisition failure) and a budget stop that leaves one page not reached. The clock and the run id are fixed, so the
expected values are literals. Offline: fake fetcher, in-memory store.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from catalog_core.identity import IdentityKind, SourceIdentity
from catalog_core.models import BookDraft, ProviderCode, SourceRef, WritePolicy
from kingstone.acquisition import AcquisitionError, AcquisitionFailure
from kingstone.artifacts import record_from_report
from kingstone.ledger import format_report
from kingstone.parse_detail import parse_detail_html
from kingstone.run import KingstoneRunDependencies, SoftBudget, run_pages
from kingstone.urls import detail_url

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "kingstone"
NOW = datetime(2026, 10, 25, 3, 0, tzinfo=UTC)

LIST_A = "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1"
LIST_B = "https://www.kingstone.com.tw/book/jdc/?dis=list&page=2"
LIST_C = "https://www.kingstone.com.tw/book/jdc/?dis=list&page=3"

KM_EXISTING = "2018630959191"  # detail fixture: 一般書，有 ISBN、目錄
KM_NEW = "2018564008187"  # detail fixture: 套書，有 ISBN
KM_ISBN = "2018741206573"  # detail fixture: 翻譯書
KM_BROKEN = "2018000000017"  # its detail page is a maintenance page: parse_error

BROKEN_HTML = "<html><body>maintenance</body></html>"
BOOK_ID = uuid.UUID("00000000-0000-4000-8000-000000000042")


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _detail_html(km_code: str) -> str:
    return _fixture(f"detail_{km_code}.html")


def _list_html(km_codes: Sequence[str]) -> str:
    cards = "".join(
        f'<div class="mod_prod_card" data-prodno="{code}"><div class="coverbox"><a href="/basic/{code}/?lid=test">x</a></div></div>' for code in km_codes
    )
    return f'<html><body><section id="allProducts"><div id="displayCSS"><div class="productGrid">{cards}</div></div></section></body></html>'


class _Clock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Fetcher:
    def __init__(self, responses: dict[str, object], on_request: Callable[[str], None] | None = None) -> None:
        self._responses = responses
        self._on_request = on_request
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
        if self._on_request is not None:
            self._on_request(url)
        value = self._responses[url]
        if isinstance(value, BaseException):
            raise value
        return value


class _Store:
    def __init__(self) -> None:
        self.refs: dict[str, SourceRef] = {}
        self.warnings: dict[str, str] = {}
        self.isbn_matches: dict[str, list[uuid.UUID]] = {}

    def resolve_source_identity(self, provider: ProviderCode, source_url: str, external_id: str | None) -> SourceIdentity:
        if external_id in self.refs:
            return SourceIdentity(IdentityKind.EXISTING, ref=self.refs[external_id], warning=self.warnings.get(external_id))
        return SourceIdentity(IdentityKind.NEW)

    def touch_source(self, provider: ProviderCode, source_id: uuid.UUID, observed_at: datetime) -> bool:
        return True

    def find_books_by_isbn(self, values: Sequence[str]) -> list[uuid.UUID]:
        found: list[uuid.UUID] = []
        for value in values:
            found.extend(self.isbn_matches.get(value, []))
        return list(dict.fromkeys(found))

    def persist_new_source(self, provider: ProviderCode, draft: BookDraft, now: datetime, attach_to_book_id):
        ref = SourceRef(source_id=uuid.uuid4(), book_id=attach_to_book_id or uuid.uuid4())
        self.refs[draft.external_id] = ref
        return ref


def _isbn_of(km_code: str) -> str:
    draft = parse_detail_html(_detail_html(km_code), detail_url(km_code))
    assert len(draft.identifiers) == 1
    return draft.identifiers[0].identifier_value


def _run_golden(caplog):
    caplog.set_level(logging.INFO)
    clock = _Clock(0.0)

    def exhaust_budget_on_page_b(url: str) -> None:
        # The budget runs out while page B is being fetched: page C is then not reached.
        if url == LIST_B:
            clock.advance(100)

    fetcher = _Fetcher(
        {
            LIST_A: _list_html([KM_EXISTING, KM_NEW, KM_ISBN, KM_BROKEN]),
            detail_url(KM_NEW): _detail_html(KM_NEW),
            detail_url(KM_ISBN): _detail_html(KM_ISBN),
            detail_url(KM_BROKEN): BROKEN_HTML,
            LIST_B: AcquisitionError(AcquisitionFailure.HTTP_STATUS, "GET failed: HTTP_STATUS", 3, 503),
            LIST_C: _list_html([KM_NEW]),
        },
        on_request=exhaust_budget_on_page_b,
    )
    store = _Store()
    store.refs[KM_EXISTING] = SourceRef(source_id=uuid.UUID("00000000-0000-4000-8000-000000000007"), book_id=uuid.UUID("00000000-0000-4000-8000-000000000008"))
    store.warnings[KM_EXISTING] = "URL drift: source_url is not the stored URL; the existing URL is kept"
    store.isbn_matches[_isbn_of(KM_ISBN)] = [BOOK_ID]

    deps = KingstoneRunDependencies(
        fetcher=fetcher,
        store=store,
        budget=SoftBudget(100, clock),
        clock=lambda: NOW,
        sleep=lambda seconds: None,
        write_policy=WritePolicy.NORMAL,
    )
    report = run_pages(deps, [LIST_A, LIST_B, LIST_C], run_id="golden-run")
    log_lines = [
        (record.name, record.levelname, record.getMessage())
        for record in caplog.records
        if record.name in ("kingstone.run", "kingstone.ledger") and record.levelno >= logging.INFO
    ]
    return report, log_lines


def test_golden_report_line_record_and_logs(caplog):
    report, log_lines = _run_golden(caplog)

    assert format_report(report) == GOLDEN_REPORT
    assert record_from_report(report) == GOLDEN_RECORD
    assert log_lines == GOLDEN_LOGS


GOLDEN_REPORT = (
    "run_id=golden-run provider_code=KINGSTONE write_policy=normal "
    "started_at=2026-10-25T03:00:00+00:00 finished_at=2026-10-25T03:00:00+00:00 "
    "status=PARTIAL_SUCCESS pages_listed=3 pages_completed=1 pages_skipped=1 pages_interrupted=0 "
    "pages_not_reached=1 zero_card_pages=0 budget_exhausted=true items_seen=4 items_listed=4 "
    "details_fetched=3 http_attempts=5 http_failures=0 existing_source=1 imported=1 isbn_attached=1 "
    "ambiguous_created=0 policy_skipped=0 failed=1 parse_error_200_count=1 recovered_commit_count=0 "
    'identity_warning_count=1 zero_progress_reason=null error=null exit_code=0 skipped_pages=[{"url": '
    '"https://www.kingstone.com.tw/book/jdc/?dis=list&page=2", "reason": "http_status", "message": '
    '"GET failed: HTTP_STATUS", "attempts": 3}] failed_items=[{"list_url": '
    '"https://www.kingstone.com.tw/book/jdc/?dis=list&page=1", "source_url": '
    '"https://www.kingstone.com.tw/basic/2018000000017/", "external_id": "2018000000017", "reason": '
    '"parse_error", "message": "no Product JSON-LD and the page is not the 404 page: '
    'https://www.kingstone.com.tw/basic/2018000000017/", "attempts": 1}]'
)

GOLDEN_RECORD = {
    "run_id": "golden-run",
    "provider": "KINGSTONE",
    "status": "PARTIAL_SUCCESS",
    "exit_code": 0,
    "reason": None,
    "error": None,
    "write_policy": "normal",
    "started_at": "2026-10-25T03:00:00+00:00",
    "finished_at": "2026-10-25T03:00:00+00:00",
    "pages_listed": 3,
    "pages_completed": 1,
    "pages_skipped": [
        {"url": "https://www.kingstone.com.tw/book/jdc/?dis=list&page=2", "reason": "http_status", "message": "GET failed: HTTP_STATUS", "attempts": 3}
    ],
    "pages_interrupted": 0,
    "pages_not_reached": 1,
    "zero_card_pages": 0,
    "parse_error_200_count": 1,
    "budget_exhausted": True,
    "items_listed": 4,
    "details_fetched": 3,
    "items_seen": 4,
    "existing_source": 1,
    "imported": 1,
    "isbn_attached": 1,
    "ambiguous_created": 0,
    "policy_skipped": 0,
    "failed": 1,
    "recovered_commit_count": 0,
    "identity_warning_count": 1,
    "failed_items": [
        {
            "list_url": "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1",
            "source_url": "https://www.kingstone.com.tw/basic/2018000000017/",
            "external_id": "2018000000017",
            "reason": "parse_error",
            "message": "no Product JSON-LD and the page is not the 404 page: https://www.kingstone.com.tw/basic/2018000000017/",
            "attempts": 1,
        }
    ],
    "http_attempts": 5,
    "http_failures": 0,
    "zero_progress_reason": None,
}

GOLDEN_LOGS = [
    ("kingstone.run", "WARNING", "card https://www.kingstone.com.tw/basic/2018630959191/: URL drift: source_url is not the stored URL; the existing URL is kept"),
    (
        "kingstone.ledger",
        "WARNING",
        (
            "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1 item failed after 1 attempt(s) (parse_error): "
            "https://www.kingstone.com.tw/basic/2018000000017/: no Product JSON-LD and the page is not the 404 page: "
            "https://www.kingstone.com.tw/basic/2018000000017/"
        ),
    ),
    (
        "kingstone.ledger",
        "WARNING",
        "page skipped after 3 attempt(s) (http_status): https://www.kingstone.com.tw/book/jdc/?dis=list&page=2: GET failed: HTTP_STATUS",
    ),
    (
        "kingstone.run",
        "INFO",
        (
            "mode=kingstone run_id=golden-run provider_code=KINGSTONE write_policy=normal "
            "started_at=2026-10-25T03:00:00+00:00 finished_at=2026-10-25T03:00:00+00:00 status=PARTIAL_SUCCESS "
            "pages_listed=3 pages_completed=1 pages_skipped=1 pages_interrupted=0 pages_not_reached=1 "
            "zero_card_pages=0 budget_exhausted=true items_seen=4 items_listed=4 details_fetched=3 http_attempts=5 "
            "http_failures=0 existing_source=1 imported=1 isbn_attached=1 ambiguous_created=0 policy_skipped=0 "
            "failed=1 parse_error_200_count=1 recovered_commit_count=0 identity_warning_count=1 "
            'zero_progress_reason=null error=null exit_code=0 skipped_pages=[{"url": '
            '"https://www.kingstone.com.tw/book/jdc/?dis=list&page=2", "reason": "http_status", "message": "GET '
            'failed: HTTP_STATUS", "attempts": 3}] failed_items=[{"list_url": '
            '"https://www.kingstone.com.tw/book/jdc/?dis=list&page=1", "source_url": '
            '"https://www.kingstone.com.tw/basic/2018000000017/", "external_id": "2018000000017", "reason": '
            '"parse_error", "message": "no Product JSON-LD and the page is not the 404 page: '
            'https://www.kingstone.com.tw/basic/2018000000017/", "attempts": 1}]'
        ),
    ),
]
