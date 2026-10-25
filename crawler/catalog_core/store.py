"""The session-backed ``CatalogStore`` (catalog_core.service): the persistence port over a ``DatabaseSession``.

Each method reads ``session.conn`` at call time, so a reconnect made by the session is used by the next call.
Only ``SourceTouchConflict`` is translated (to ``False``); every other exception, including ``psycopg.Error``,
reaches the service unchanged, because the service decides what a database error means.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from catalog_core import persistence
from catalog_core.identity import SourceIdentity
from catalog_core.models import BookDraft, ProviderCode, SourceRef
from catalog_core.session import DatabaseSession


class SessionCatalogStore:
    def __init__(self, session: DatabaseSession) -> None:
        self._session = session

    def resolve_source_identity(self, provider: ProviderCode, source_url: str, external_id: str | None) -> SourceIdentity:
        return persistence.resolve_source_identity(self._session.conn, provider, source_url, external_id=external_id)

    def touch_source(self, provider: ProviderCode, source_id: UUID, observed_at: datetime) -> bool:
        try:
            persistence.touch_source(self._session.conn, provider, source_id, observed_at)
        except persistence.SourceTouchConflict:
            return False
        return True

    def find_books_by_isbn(self, values: Sequence[str]) -> list[UUID]:
        return persistence.find_books_by_isbn(self._session.conn, values)

    def persist_new_source(
        self,
        provider: ProviderCode,
        draft: BookDraft,
        now: datetime,
        attach_to_book_id: UUID | None,
    ) -> SourceRef:
        return persistence.persist_new_source(self._session.conn, provider, draft, now, attach_to_book_id=attach_to_book_id)
