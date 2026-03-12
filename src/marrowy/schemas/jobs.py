from __future__ import annotations

from datetime import datetime
from typing import Any

from .common import ORMModel


class JobRead(ORMModel):
    id: str
    conversation_id: str | None = None
    task_id: str | None = None
    participant_id: str | None = None
    source_message_id: str | None = None
    worker_key: str
    agent_key: str | None = None
    status: str
    summary: str
    payload_json: dict[str, Any]
    result_json: dict[str, Any]
    idempotency_key: str | None = None
    priority: int
    available_at: datetime
    claim_token: str | None = None
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempt_count: int
    max_attempts: int
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime
