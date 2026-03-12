from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from .common import ORMModel


class ConversationCreate(BaseModel):
    project_id: str | None = None
    title: str
    channel: str = "browser"
    external_ref: str | None = None


class ConversationRead(ORMModel):
    id: str
    project_id: str | None = None
    title: str
    status: str
    channel: str
    external_ref: str | None = None
    summary: str | None = None
    created_at: datetime
    updated_at: datetime


class MessageCreate(BaseModel):
    content: str
    author_name: str | None = None
    metadata: dict[str, Any] | None = None


class MessageRead(ORMModel):
    id: str
    conversation_id: str
    participant_id: str | None = None
    author_name: str
    author_kind: str
    content: str
    message_type: str
    metadata_json: dict[str, Any]
    created_at: datetime


class ParticipantRead(ORMModel):
    id: str
    conversation_id: str
    kind: str
    agent_key: str | None = None
    display_name: str
    bridge_thread_id: str | None = None
    joined_at: datetime
    is_active: bool


class AddAgentRequest(BaseModel):
    agent_key: str
