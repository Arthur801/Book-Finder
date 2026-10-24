"""Offline driver for gate 9 (Docs/data/data-model.md 11.3): the previous crawler release against the 011 schema.

Runs inside the previous crawler image (v0.0.6) with PYTHONPATH=/app/crawler, so it imports that release's own
books_crawler modules: db (the DB layer), identity, models and ranking. No network is used; every input is built here
or comes from the 011 seed (deploy/migration-test/seeds/20261025120000_ContractMultiSourceCatalog.sql).

Prints one "PASS <name>" or "FAIL <name>: <reason>" line per check, and exits 1 when any check failed. The check names
are part of the contract with deploy/tests/integration/test_prev_release_on_contract.py.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from books_crawler import db
from books_crawler.db import SnapshotValidationError
from books_crawler.identity import IdentityKind
from books_crawler.models import BookDraft, Identifier, IdentifierType, RankingRow, SnapshotRow
from books_crawler.ranking import RankingValidationError, validate_ranking

# Seeded rows (011 seed): book 1 owns the BOOKS_COM_TW Source below; book 4 owns ISBN 9786263100002 (only that Book).
BOOK1 = UUID("10000000-0000-0000-0000-000000000001")
BOOK4 = UUID("10000000-0000-0000-0000-000000000004")
SOURCE1 = UUID("20000000-0000-0000-0000-000000000001")
SOURCE1_URL = "https://www.books.com.tw/products/0010000001"
SEED_ISBN = "9786263100002"
ATTACH_URL = "https://www.books.com.tw/products/0010000099"
NEW_ISBN = "9786263199901"
NEW_URL = "https://www.books.com.tw/products/0010000100"
RANKING_SIZE = 100

failures = 0


def check(name: str, body: Callable[[], str]) -> None:
    global failures
    try:
        detail = body()
    except Exception as exc:  # noqa: BLE001 - a failed check is reported by name; the other checks still run
        failures += 1
        print(f"FAIL {name}: {type(exc).__name__}: {exc}", flush=True)
        return
    print(f"PASS {name}", flush=True)
    if detail:
        print(f"INFO {name}: {detail}", flush=True)


def scalar(conn, sql: str, *params):
    return conn.execute(sql, params).fetchone()[0]


def now() -> datetime:
    return datetime.now(UTC)


def existing_source_touch(conn) -> str:
    before = scalar(conn, "SELECT last_seen_at FROM book_sources WHERE id = %s", SOURCE1)
    identity = db.resolve_source_identity(conn, SOURCE1_URL)
    assert identity.kind is IdentityKind.EXISTING, f"identity is {identity.kind}, expected existing"
    assert identity.ref is not None and identity.ref.source_id == SOURCE1, f"identity points at {identity.ref}"
    assert identity.ref.book_id == BOOK1, f"identity book is {identity.ref.book_id}, expected {BOOK1}"
    db.touch_source(conn, identity.ref.source_id, now())
    after = scalar(conn, "SELECT last_seen_at FROM book_sources WHERE id = %s", SOURCE1)
    assert after > before, f"last_seen_at did not advance: {before} -> {after}"
    return f"{before.isoformat()} -> {after.isoformat()}"


def isbn_attach(conn) -> str:
    matches = db.find_books_by_isbn(conn, [SEED_ISBN])
    assert matches == [BOOK4], f"ISBN lookup returned {matches}, expected [{BOOK4}]"
    books_before = scalar(conn, "SELECT count(*) FROM books")
    draft = BookDraft(
        source_url=ATTACH_URL,
        title="第四本書（新來源）",
        identifiers=(Identifier(IdentifierType.ISBN, SEED_ISBN),),
    )
    ref = db.persist_new_source(conn, draft, now(), attach_to_book_id=matches[0])
    books_after = scalar(conn, "SELECT count(*) FROM books")
    assert ref.book_id == BOOK4, f"source attached to {ref.book_id}, expected {BOOK4}"
    assert books_after == books_before, f"a Book was created: {books_before} -> {books_after}"
    distinct = scalar(
        conn,
        "SELECT count(DISTINCT book_id) FROM book_identifiers WHERE identifier_type = 'ISBN' AND identifier_value = %s",
        SEED_ISBN,
    )
    assert distinct == 1, f"ISBN {SEED_ISBN} is owned by {distinct} Books, expected 1"
    source_code = scalar(conn, "SELECT source_code FROM book_sources WHERE id = %s AND book_id = %s", ref.source_id, BOOK4)
    assert source_code == "BOOKS_COM_TW", f"attached source_code is {source_code}"
    return f"source {ref.source_id} attached to book {BOOK4}"


def new_source_creates_book(conn) -> str:
    assert db.find_books_by_isbn(conn, [NEW_ISBN]) == [], "a fresh ISBN must not match any Book"
    books_before = scalar(conn, "SELECT count(*) FROM books")
    draft = BookDraft(
        source_url=NEW_URL,
        title="Prev release new Book",
        publisher="測試出版社",
        identifiers=(Identifier(IdentifierType.ISBN, NEW_ISBN),),
    )
    ref = db.persist_new_source(conn, draft, now())
    books_after = scalar(conn, "SELECT count(*) FROM books")
    assert books_after == books_before + 1, f"books {books_before} -> {books_after}, expected one new Book"
    row = conn.execute("SELECT source_code, external_id, book_id FROM book_sources WHERE id = %s", (ref.source_id,)).fetchone()
    assert row == ("BOOKS_COM_TW", None, ref.book_id), f"source row is {row}"
    isbn_rows = scalar(conn, "SELECT count(*) FROM book_identifiers WHERE book_id = %s AND identifier_type = 'ISBN'", ref.book_id)
    assert isbn_rows == 1, f"new Book has {isbn_rows} ISBN rows, expected 1"
    return f"new book {ref.book_id}"


def ranking_validate_and_replace(conn, state: dict) -> str:
    rows = [RankingRow(rank=rank, url=f"https://www.books.com.tw/products/00300000{rank:02d}") for rank in range(1, RANKING_SIZE + 1)]
    ordered = validate_ranking(rows)
    assert [row.rank for row in ordered] == list(range(1, RANKING_SIZE + 1)), "validate_ranking changed the order"
    snapshot = []
    for row in ordered:
        draft = BookDraft(
            source_url=row.url,
            title=f"Prev ranking {row.rank:03d}",
            identifiers=(Identifier(IdentifierType.ISBN, f"9789990{row.rank:06d}"),),
        )
        ref = db.persist_new_source(conn, draft, now())
        snapshot.append(SnapshotRow(rank=row.rank, book_id=ref.book_id, source_id=ref.source_id))
    db.replace_bestsellers(conn, snapshot, now())
    state["snapshot"] = snapshot
    count, low, high = conn.execute("SELECT count(*), min(rank), max(rank) FROM bestsellers").fetchone()
    assert (count, low, high) == (RANKING_SIZE, 1, RANKING_SIZE), f"bestsellers are {count} rows, ranks {low}..{high}"
    seeded_left = scalar(conn, "SELECT count(*) FROM bestsellers WHERE source_id = %s", SOURCE1)
    assert seeded_left == 0, "the seeded bestseller row survived the replacement"
    return f"{RANKING_SIZE} rows replaced"


def incomplete_ranking_rejected() -> str:
    rows = [RankingRow(rank=rank, url=f"https://www.books.com.tw/products/00400000{rank:02d}") for rank in range(1, RANKING_SIZE)]
    try:
        validate_ranking(rows)
    except RankingValidationError as exc:
        return str(exc)
    raise AssertionError("a 99-row ranking was accepted")


def mismatched_source_rejected(conn, state: dict) -> str:
    snapshot = list(state["snapshot"])
    first = snapshot[0]
    # The source of rank 1 belongs to another Book, so the whole replacement must be refused before the list is touched.
    wrong_owner = SnapshotRow(rank=first.rank, book_id=BOOK4 if first.book_id != BOOK4 else BOOK1, source_id=first.source_id)
    try:
        db.replace_bestsellers(conn, [wrong_owner, *snapshot[1:]], now())
    except SnapshotValidationError as exc:
        reason = str(exc)
    else:
        raise AssertionError("a source of another Book was accepted")
    count = scalar(conn, "SELECT count(*) FROM bestsellers")
    kept = scalar(conn, "SELECT count(*) FROM bestsellers WHERE book_id = %s AND source_id = %s", first.book_id, first.source_id)
    assert (count, kept) == (RANKING_SIZE, 1), f"bestsellers are {count} rows, rank 1 kept={kept}"
    return reason


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("FAIL crawler: DATABASE_URL is not set", flush=True)
        return 1
    state: dict = {}
    with db.connect(database_url) as conn:
        check("crawler: existing Source resolves by URL and touch advances last_seen_at", lambda: existing_source_touch(conn))
        check(
            "crawler: ISBN row matches the draft, the Source is attached and no Book is created",
            lambda: isbn_attach(conn),
        )
        check(
            "crawler: new Source with a fresh ISBN creates a Book with source_code BOOKS_COM_TW",
            lambda: new_source_creates_book(conn),
        )
        check(
            "crawler: 100-row ranking validates and replaces the bestsellers",
            lambda: ranking_validate_and_replace(conn, state),
        )
        check("crawler: incomplete ranking is rejected", incomplete_ranking_rejected)
        check(
            "crawler: Source of another Book is rejected and the bestseller list is unchanged",
            lambda: mismatched_source_rejected(conn, state),
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
