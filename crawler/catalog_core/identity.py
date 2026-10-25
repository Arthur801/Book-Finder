"""Source identity resolution: the one function that decides Existing / New / Conflict (data-model §7.3).

The matrix is applied to the two lookups the caller made: by ``external_id`` (only when the item
carries one) and by ``source_url``. Pure: no database, no logging except the WARNING/INFO of §7.3.
The Books.com.tw adapter passes no ``external_id``, so only the URL lookup is ever meaningful for it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from catalog_core.models import SourceRecord, SourceRef

log = logging.getLogger("catalog_core.identity")


class IdentityKind(StrEnum):
    EXISTING = "existing"
    NEW = "new"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class SourceIdentity:
    kind: IdentityKind
    ref: SourceRef | None = None  # the Existing Source (its Book is reused)
    reason: str | None = None  # the source_identity_conflict message
    warning: str | None = None  # URL drift: the existing URL is kept and a WARNING is logged


def decide_source_identity(
    by_external_id: SourceRecord | None,
    by_url: SourceRecord | None,
    *,
    external_id: str | None,
) -> SourceIdentity:
    """Apply data-model §7.3 to the two lookups. ``by_external_id`` is None when ``external_id`` is None."""
    if external_id is None:
        return _existing(by_url) if by_url is not None else SourceIdentity(IdentityKind.NEW)

    if by_external_id is not None and by_url is not None:
        if by_external_id.source_id == by_url.source_id:
            return _existing(by_external_id)
        return _conflict("external_id and source_url match different Book Sources")
    if by_external_id is not None:
        drift = "URL drift: source_url is not the stored URL; the existing URL is kept"
        return SourceIdentity(IdentityKind.EXISTING, ref=_ref(by_external_id), warning=drift)
    if by_url is not None:
        if by_url.external_id is None:
            # Not backfilled in this release (§7.3): the Source stays as it is, only the observation is logged.
            log.info("no backfill: Book Source %s has no external_id; the item's external_id is not stored", by_url.source_id)
            return _existing(by_url)
        return _conflict("source_url matches a Book Source with a different external_id")
    return SourceIdentity(IdentityKind.NEW)


def _ref(record: SourceRecord) -> SourceRef:
    return SourceRef(source_id=record.source_id, book_id=record.book_id)


def _existing(record: SourceRecord) -> SourceIdentity:
    return SourceIdentity(IdentityKind.EXISTING, ref=_ref(record))


def _conflict(detail: str) -> SourceIdentity:
    return SourceIdentity(IdentityKind.CONFLICT, reason=f"source_identity_conflict: {detail}")
