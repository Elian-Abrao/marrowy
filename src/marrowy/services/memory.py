from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from marrowy.db.models import MemoryEntry
from marrowy.domain.enums import MemoryScope
from marrowy.domain.enums import MemoryStatus


class MemoryService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_memory(self, scope_type: MemoryScope, scope_id: str) -> list[MemoryEntry]:
        stmt = select(MemoryEntry).where(MemoryEntry.scope_type == scope_type.value, MemoryEntry.scope_id == scope_id)
        return list(self.db.scalars(stmt.order_by(MemoryEntry.created_at)))

    def store_active(self, scope_type: MemoryScope, scope_id: str, category: str, content: str, *, proposed_by: str | None = None) -> MemoryEntry:
        entry = MemoryEntry(
            scope_type=scope_type.value,
            scope_id=scope_id,
            category=category,
            content=content,
            proposed_by_agent_key=proposed_by,
            status=MemoryStatus.ACTIVE.value,
        )
        self.db.add(entry)
        self.db.flush()
        return entry

    def suggest(self, scope_type: MemoryScope, scope_id: str, category: str, content: str, *, proposed_by: str) -> MemoryEntry:
        entry = MemoryEntry(
            scope_type=scope_type.value,
            scope_id=scope_id,
            category=category,
            content=content,
            proposed_by_agent_key=proposed_by,
            status=MemoryStatus.SUGGESTED.value,
        )
        self.db.add(entry)
        self.db.flush()
        return entry
