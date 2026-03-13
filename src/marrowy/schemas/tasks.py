from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from .common import ORMModel


class TaskRead(ORMModel):
    id: str
    conversation_id: str | None = None
    project_id: str | None = None
    parent_task_id: str | None = None
    title: str
    goal: str
    scope: str | None = None
    acceptance_criteria_markdown: str | None = None
    repository_name: str | None = None
    branch_name: str | None = None
    environment_name: str | None = None
    status: str
    kind: str
    assigned_agent_key: str | None = None
    order_index: int
    details_markdown: str | None = None
    updates_markdown: str | None = None
    blockers_markdown: str | None = None
    approval_required: bool = False
    result_markdown: str | None = None
    observations_markdown: str | None = None
    evidence_markdown: str | None = None
    gmud_reference: str | None = None
    idempotency_key: str | None = None
    created_at: datetime
    updated_at: datetime


class TaskStatusUpdate(BaseModel):
    status: str


class TaskCreate(BaseModel):
    title: str
    goal: str
    scope: str | None = None
    acceptance_criteria_markdown: str | None = None
    repository_name: str | None = None
    branch_name: str | None = None
    environment_name: str | None = None
    assigned_agent_key: str | None = None
    parent_task_id: str | None = None
    kind: str = "simple"
    details_markdown: str | None = None
    updates_markdown: str | None = None
    blockers_markdown: str | None = None
    approval_required: bool = False
    result_markdown: str | None = None
    observations_markdown: str | None = None
    evidence_markdown: str | None = None
    gmud_reference: str | None = None
