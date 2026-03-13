from __future__ import annotations

import uuid
from datetime import datetime
from datetime import timezone

from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import JSON
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

from marrowy.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    context_markdown: Mapped[str | None] = mapped_column(Text(), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON(), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)

    repositories: Mapped[list["ProjectRepository"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    environments: Mapped[list["ProjectEnvironment"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    pipeline_templates: Mapped[list["PipelineTemplate"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="project")


class ProjectRepository(Base):
    __tablename__ = "project_repositories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    local_path: Mapped[str | None] = mapped_column(String(400), nullable=True)
    remote_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean(), default=False)

    project: Mapped[Project] = relationship(back_populates="repositories")


class ProjectEnvironment(Base):
    __tablename__ = "project_environments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(80))
    approval_policy_json: Mapped[dict] = mapped_column(JSON(), default=dict)
    details_json: Mapped[dict] = mapped_column(JSON(), default=dict)

    project: Mapped[Project] = relationship(back_populates="environments")


class PipelineTemplate(Base):
    __tablename__ = "pipeline_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    definition_json: Mapped[dict] = mapped_column(JSON(), default=dict)

    project: Mapped[Project | None] = relationship(back_populates="pipeline_templates")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(40), index=True)
    channel: Mapped[str] = mapped_column(String(40), default="terminal")
    external_ref: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    summary: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(), default=_now, onupdate=_now)

    project: Mapped[Project | None] = relationship(back_populates="conversations")
    participants: Mapped[list["ConversationParticipant"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")
    messages: Mapped[list["ConversationMessage"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")
    tasks: Mapped[list["Task"]] = relationship(back_populates="conversation")
    approvals: Mapped[list["ApprovalRequest"]] = relationship(back_populates="conversation")


class ConversationParticipant(Base):
    __tablename__ = "conversation_participants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    agent_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    display_name: Mapped[str] = mapped_column(String(120))
    bridge_thread_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True)
    activity_state: Mapped[str] = mapped_column(String(40), default="idle", index=True)
    activity_summary: Mapped[str | None] = mapped_column(String(240), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)

    conversation: Mapped[Conversation] = relationship(back_populates="participants")
    messages: Mapped[list["ConversationMessage"]] = relationship(back_populates="participant")


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    participant_id: Mapped[str | None] = mapped_column(ForeignKey("conversation_participants.id"), nullable=True, index=True)
    author_name: Mapped[str] = mapped_column(String(120))
    author_kind: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(Text())
    message_type: Mapped[str] = mapped_column(String(40), index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON(), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now, index=True)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    participant: Mapped[ConversationParticipant | None] = relationship(back_populates="messages")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    parent_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    goal: Mapped[str] = mapped_column(Text())
    scope: Mapped[str | None] = mapped_column(Text(), nullable=True)
    acceptance_criteria_markdown: Mapped[str | None] = mapped_column(Text(), nullable=True)
    repository_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    branch_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    environment_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(40), default="simple")
    assigned_agent_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer(), default=0)
    details_markdown: Mapped[str | None] = mapped_column(Text(), nullable=True)
    updates_markdown: Mapped[str | None] = mapped_column(Text(), nullable=True)
    blockers_markdown: Mapped[str | None] = mapped_column(Text(), nullable=True)
    approval_required: Mapped[bool] = mapped_column(Boolean(), default=False)
    result_markdown: Mapped[str | None] = mapped_column(Text(), nullable=True)
    observations_markdown: Mapped[str | None] = mapped_column(Text(), nullable=True)
    evidence_markdown: Mapped[str | None] = mapped_column(Text(), nullable=True)
    gmud_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_by_message_id: Mapped[str | None] = mapped_column(ForeignKey("conversation_messages.id"), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(), default=_now, onupdate=_now)

    conversation: Mapped[Conversation | None] = relationship(back_populates="tasks")
    parent: Mapped["Task | None"] = relationship(remote_side=[id])


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    action_type: Mapped[str] = mapped_column(String(80))
    requested_by_agent_key: Mapped[str] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(Text())
    details_json: Mapped[dict] = mapped_column(JSON(), default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    resolved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)

    conversation: Mapped[Conversation] = relationship(back_populates="approvals")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    participant_id: Mapped[str | None] = mapped_column(ForeignKey("conversation_participants.id"), nullable=True, index=True)
    source_message_id: Mapped[str | None] = mapped_column(ForeignKey("conversation_messages.id"), nullable=True, index=True)
    worker_key: Mapped[str] = mapped_column(String(80), index=True)
    agent_key: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    summary: Mapped[str] = mapped_column(String(240))
    payload_json: Mapped[dict] = mapped_column(JSON(), default=dict)
    result_json: Mapped[dict] = mapped_column(JSON(), default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    priority: Mapped[int] = mapped_column(Integer(), default=100)
    available_at: Mapped[datetime] = mapped_column(DateTime(), default=_now, index=True)
    claim_token: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    claimed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer(), default=0)
    max_attempts: Mapped[int] = mapped_column(Integer(), default=3)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(), default=_now, onupdate=_now)


class DomainEvent(Base):
    __tablename__ = "domain_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON(), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now, index=True)


class MemoryEntry(Base):
    __tablename__ = "memory_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scope_type: Mapped[str] = mapped_column(String(40), index=True)
    scope_id: Mapped[str] = mapped_column(String(120), index=True)
    category: Mapped[str] = mapped_column(String(80))
    content: Mapped[str] = mapped_column(Text())
    proposed_by_agent_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(), default=_now, onupdate=_now)
