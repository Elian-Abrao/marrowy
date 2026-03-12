from __future__ import annotations

from sqlalchemy.orm import Session

from marrowy.db.models import DomainEvent


class EventService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def emit(self, event_type: str, *, conversation_id: str | None = None, task_id: str | None = None, payload: dict | None = None) -> DomainEvent:
        event = DomainEvent(
            conversation_id=conversation_id,
            task_id=task_id,
            event_type=event_type,
            payload_json=payload or {},
        )
        self.db.add(event)
        self.db.flush()
        return event
