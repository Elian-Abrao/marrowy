from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from .common import ORMModel


class ApprovalRead(ORMModel):
    id: str
    conversation_id: str
    task_id: str | None = None
    status: str
    action_type: str
    requested_by_agent_key: str
    summary: str
    details_json: dict[str, Any]
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime


class ApprovalResolve(BaseModel):
    decision: str
    actor_name: str
