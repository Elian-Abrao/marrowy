from __future__ import annotations

from enum import StrEnum


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    WAITING_USER = "waiting_user"
    WAITING_AGENT = "waiting_agent"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ParticipantKind(StrEnum):
    USER = "user"
    AGENT = "agent"


class MessageKind(StrEnum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"
    APPROVAL = "approval"
    HANDOFF = "handoff"


class TaskStatus(StrEnum):
    CREATED = "created"
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    WAITING_APPROVAL = "waiting_approval"
    TESTING = "testing"
    DEPLOYING = "deploying"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskKind(StrEnum):
    SIMPLE = "simple"
    PIPELINE = "pipeline"
    STAGE = "stage"
    SUBTASK = "subtask"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ParticipantActivityState(StrEnum):
    IDLE = "idle"
    QUEUED = "queued"
    WORKING = "working"
    WAITING = "waiting"
    ERROR = "error"


class JobStatus(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MemoryScope(StrEnum):
    CONVERSATION = "conversation"
    TASK = "task"
    PROJECT = "project"
    USER = "user"
    AGENT_PROFILE = "agent_profile"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    SUGGESTED = "suggested"
    REJECTED = "rejected"
