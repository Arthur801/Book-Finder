"""Source identity matrix (data-model §7.3, crawler.md §6.2). Pure: the lookups are passed in."""

import logging
from uuid import uuid4

from books_crawler.identity import IdentityKind, decide_source_identity
from books_crawler.models import SourceRecord

BOOK = uuid4()


def record(external_id: str | None = None, source_id=None) -> SourceRecord:
    return SourceRecord(source_id=source_id or uuid4(), book_id=BOOK, external_id=external_id)


def test_url_only_hit_is_existing_whatever_external_id_is_null_or_not():
    by_url = record(external_id="X-1")

    result = decide_source_identity(None, by_url, external_id=None)

    assert result.kind is IdentityKind.EXISTING
    assert result.ref.source_id == by_url.source_id and result.ref.book_id == BOOK


def test_url_only_miss_is_new_source():
    assert decide_source_identity(None, None, external_id=None).kind is IdentityKind.NEW


def test_external_and_url_hit_the_same_source_is_existing():
    same = record(external_id="E")

    result = decide_source_identity(same, same, external_id="E")

    assert result.kind is IdentityKind.EXISTING and result.ref.source_id == same.source_id


def test_external_and_url_hit_different_sources_is_a_conflict(caplog):
    result = decide_source_identity(record(external_id="E"), record(), external_id="E")

    assert result.kind is IdentityKind.CONFLICT
    assert result.reason.startswith("source_identity_conflict")


def test_external_hit_with_url_drift_keeps_the_existing_url_and_warns(caplog):
    caplog.set_level(logging.WARNING, logger="books_crawler")
    found = record(external_id="E")

    result = decide_source_identity(found, None, external_id="E")

    assert result.kind is IdentityKind.EXISTING and result.ref.source_id == found.source_id
    assert result.warning is not None and "URL drift" in result.warning


def test_url_hit_with_null_external_id_is_existing_without_backfill():
    found = record(external_id=None)

    result = decide_source_identity(None, found, external_id="E")

    assert result.kind is IdentityKind.EXISTING and result.ref.source_id == found.source_id
    assert result.warning is None  # INFO only, never a warning


def test_null_external_id_on_the_url_hit_logs_no_backfill_at_info(caplog):
    caplog.set_level(logging.INFO, logger="books_crawler")
    found = record(external_id=None)

    result = decide_source_identity(None, found, external_id="E")

    assert result.kind is IdentityKind.EXISTING
    assert [r.levelno for r in caplog.records if "no backfill" in r.getMessage()] == [logging.INFO]
    assert result.warning is None


def test_url_hit_with_a_different_non_null_external_id_is_a_conflict():
    result = decide_source_identity(None, record(external_id="OTHER"), external_id="E")

    assert result.kind is IdentityKind.CONFLICT


def test_no_hit_on_either_key_is_new_source():
    assert decide_source_identity(None, None, external_id="E").kind is IdentityKind.NEW
