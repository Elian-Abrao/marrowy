from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from marrowy.db.models import ConversationParticipant
from marrowy.domain.agents import AgentProfile
from marrowy.domain.agents import get_agent_profile
from marrowy.domain.agents import register_agent
from marrowy.domain.enums import ParticipantActivityState
from marrowy.domain.enums import ParticipantKind
from marrowy.domain.enums import TaskKind
from marrowy.services.events import EventService
from marrowy.services.tasks import TaskService


EffortLevel = Literal["low", "medium", "high", "xhigh"]
TaskKindLiteral = Literal["simple", "pipeline", "subtask"]


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_markdown(value: str) -> str:
    return value.strip()


def _slugify_agent_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized or "custom_agent"


class TaskContract(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    goal: str = Field(min_length=3)
    kind: TaskKindLiteral = "simple"
    scope: str | None = None
    acceptance_criteria_markdown: str | None = None
    repository_name: str | None = None
    branch_name: str | None = None
    environment_name: str | None = None
    assigned_agent_key: str | None = None
    details_markdown: str | None = None
    updates_markdown: str | None = None
    blockers_markdown: str | None = None
    approval_required: bool = False
    result_markdown: str | None = None
    observations_markdown: str | None = None
    evidence_markdown: str | None = None
    gmud_reference: str | None = None

    @field_validator("title", "goal")
    @classmethod
    def _clean_required(cls, value: str) -> str:
        return _normalize_whitespace(value)

    @field_validator(
        "assigned_agent_key",
        "repository_name",
        "branch_name",
        "environment_name",
        "gmud_reference",
    )
    @classmethod
    def _clean_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _normalize_whitespace(value)
        return cleaned or None

    @field_validator(
        "scope",
        "acceptance_criteria_markdown",
        "details_markdown",
        "updates_markdown",
        "blockers_markdown",
        "result_markdown",
        "observations_markdown",
        "evidence_markdown",
    )
    @classmethod
    def _clean_markdown(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _normalize_markdown(value)
        return cleaned or None


class SubtaskContract(TaskContract):
    kind: Literal["subtask"] = "subtask"


class AgentProfileContract(BaseModel):
    display_name: str = Field(min_length=3, max_length=120)
    summary: str = Field(min_length=3)
    instructions: str = Field(min_length=3)
    key: str | None = None
    effort: EffortLevel = "medium"
    can_create_tasks: bool = False
    can_manage_repo: bool = False
    can_manage_deploy: bool = False

    @field_validator("display_name", "summary", "instructions")
    @classmethod
    def _clean_text(cls, value: str) -> str:
        return _normalize_whitespace(value)

    @field_validator("key")
    @classmethod
    def _clean_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _slugify_agent_key(value)
        return cleaned or None


class AddAgentContract(BaseModel):
    agent_key: str
    reason: str | None = None
    handoff_markdown: str | None = None

    @field_validator("agent_key")
    @classmethod
    def _normalize_agent_key(cls, value: str) -> str:
        return _slugify_agent_key(value)

    @field_validator("reason", "handoff_markdown")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _normalize_whitespace(value)
        return cleaned or None


@dataclass(slots=True)
class TaskActionResult:
    task: object
    created: bool
    subtasks: list[object] = field(default_factory=list)


@dataclass(slots=True)
class AgentProfileActionResult:
    profile: AgentProfile
    created: bool


@dataclass(slots=True)
class AddAgentActionResult:
    participant: ConversationParticipant
    added: bool


class TaskUpdateContract(BaseModel):
    task_id: str
    scope: str | None = None
    acceptance_criteria_markdown: str | None = None
    repository_name: str | None = None
    branch_name: str | None = None
    environment_name: str | None = None
    assigned_agent_key: str | None = None
    updates_markdown: str | None = None
    blockers_markdown: str | None = None
    result_markdown: str | None = None
    observations_markdown: str | None = None
    evidence_markdown: str | None = None
    gmud_reference: str | None = None

    @field_validator("task_id")
    @classmethod
    def _clean_task_id(cls, value: str) -> str:
        return _normalize_whitespace(value)

    @field_validator("assigned_agent_key", "repository_name", "branch_name", "environment_name", "gmud_reference")
    @classmethod
    def _clean_optional_scalar(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _normalize_whitespace(value)
        return cleaned or None

    @field_validator(
        "scope",
        "acceptance_criteria_markdown",
        "updates_markdown",
        "blockers_markdown",
        "result_markdown",
        "observations_markdown",
        "evidence_markdown",
    )
    @classmethod
    def _clean_optional_markdown(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _normalize_markdown(value)
        return cleaned or None

    def to_updates(self) -> dict[str, object]:
        return self.model_dump(exclude_none=True, exclude={"task_id"})


@dataclass(slots=True)
class TaskUpdateActionResult:
    task: object
    updated_fields: list[str]


class DomainActionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.tasks = TaskService(db)
        self.events = EventService(db)

    def create_task(
        self,
        *,
        conversation_id: str | None,
        project_id: str | None,
        contract: TaskContract,
        created_by_message_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> TaskActionResult:
        self._validate_agent_key(contract.assigned_agent_key)
        key = idempotency_key or self._default_idempotency_key(
            conversation_id=conversation_id,
            kind=contract.kind,
            title=contract.title,
            parent_task_id=None,
        )
        existing_before = self.tasks.find_active_by_idempotency(conversation_id=conversation_id, idempotency_key=key)
        if contract.kind == TaskKind.PIPELINE.value:
            task, subtasks = self.tasks.create_pipeline_task(
                conversation_id=conversation_id or "",
                project_id=project_id,
                title=contract.title,
                goal=contract.goal,
                scope=contract.scope,
                acceptance_criteria_markdown=contract.acceptance_criteria_markdown,
                repository_name=contract.repository_name,
                branch_name=contract.branch_name,
                environment_name=contract.environment_name,
                assigned_agent_key=contract.assigned_agent_key,
                details_markdown=contract.details_markdown,
                updates_markdown=contract.updates_markdown,
                blockers_markdown=contract.blockers_markdown,
                approval_required=contract.approval_required,
                result_markdown=contract.result_markdown,
                observations_markdown=contract.observations_markdown,
                evidence_markdown=contract.evidence_markdown,
                gmud_reference=contract.gmud_reference,
                created_by_message_id=created_by_message_id,
                idempotency_key=key,
            )
            return TaskActionResult(task=task, created=existing_before is None, subtasks=subtasks)
        task = self.tasks.create_simple_task(
            conversation_id=conversation_id,
            project_id=project_id,
            title=contract.title,
            goal=contract.goal,
            assigned_agent_key=contract.assigned_agent_key,
            scope=contract.scope,
            acceptance_criteria_markdown=contract.acceptance_criteria_markdown,
            repository_name=contract.repository_name,
            branch_name=contract.branch_name,
            environment_name=contract.environment_name,
            details_markdown=contract.details_markdown,
            updates_markdown=contract.updates_markdown,
            blockers_markdown=contract.blockers_markdown,
            approval_required=contract.approval_required,
            result_markdown=contract.result_markdown,
            observations_markdown=contract.observations_markdown,
            evidence_markdown=contract.evidence_markdown,
            gmud_reference=contract.gmud_reference,
            created_by_message_id=created_by_message_id,
            idempotency_key=key,
        )
        return TaskActionResult(task=task, created=existing_before is None)

    def create_subtasks(
        self,
        *,
        conversation_id: str | None,
        project_id: str | None,
        parent_task_id: str,
        contracts: list[SubtaskContract],
        created_by_message_id: str | None = None,
    ) -> TaskActionResult:
        parent = self.tasks.get(parent_task_id)
        if parent is None:
            raise ValueError(f"parent task {parent_task_id!r} not found")
        existing = [task for task in self.tasks.list_subtasks(parent_task_id) if task.kind == TaskKind.SUBTASK.value]
        if existing:
            return TaskActionResult(task=parent, created=False, subtasks=existing)
        items: list[dict[str, object]] = []
        for index, contract in enumerate(contracts):
            self._validate_agent_key(contract.assigned_agent_key)
            items.append(
                {
                    "title": contract.title,
                    "goal": contract.goal,
                    "assigned_agent_key": contract.assigned_agent_key,
                    "order_index": index,
                    "scope": contract.scope,
                    "acceptance_criteria_markdown": contract.acceptance_criteria_markdown,
                    "repository_name": contract.repository_name,
                    "branch_name": contract.branch_name,
                    "environment_name": contract.environment_name,
                    "details_markdown": contract.details_markdown,
                    "updates_markdown": contract.updates_markdown,
                    "blockers_markdown": contract.blockers_markdown,
                    "approval_required": contract.approval_required,
                    "result_markdown": contract.result_markdown,
                    "observations_markdown": contract.observations_markdown,
                    "evidence_markdown": contract.evidence_markdown,
                    "gmud_reference": contract.gmud_reference,
                }
            )
        subtasks = self.tasks.ensure_subtasks(
            conversation_id=conversation_id,
            project_id=project_id,
            parent_task_id=parent_task_id,
            items=items,
            created_by_message_id=created_by_message_id,
        )
        return TaskActionResult(task=parent, created=True, subtasks=subtasks)

    def create_agent_profile(self, contract: AgentProfileContract) -> AgentProfileActionResult:
        key = contract.key or _slugify_agent_key(contract.display_name.replace("Agent ", "").replace("Agente ", ""))
        created = key not in self._agent_keys()
        profile = register_agent(
            key=key,
            display_name=contract.display_name,
            summary=contract.summary,
            instructions=contract.instructions,
            effort=contract.effort,
            can_create_tasks=contract.can_create_tasks,
            can_manage_repo=contract.can_manage_repo,
            can_manage_deploy=contract.can_manage_deploy,
        )
        return AgentProfileActionResult(profile=profile, created=created)

    def add_agent_to_room(self, *, conversation_id: str, contract: AddAgentContract) -> AddAgentActionResult:
        profile = get_agent_profile(contract.agent_key)
        existing = self.db.scalar(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.agent_key == profile.key,
            )
        )
        if existing is not None:
            return AddAgentActionResult(participant=existing, added=False)
        participant = ConversationParticipant(
            conversation_id=conversation_id,
            kind=ParticipantKind.AGENT.value,
            agent_key=profile.key,
            display_name=profile.display_name,
            activity_state=ParticipantActivityState.IDLE.value,
            activity_summary="Available for assignment.",
        )
        self.db.add(participant)
        self.db.flush()
        self.events.emit("agent.joined", conversation_id=conversation_id, payload={"agentKey": profile.key})
        return AddAgentActionResult(participant=participant, added=True)

    def update_task(
        self,
        *,
        actor_agent_key: str,
        contract: TaskUpdateContract,
    ) -> TaskUpdateActionResult:
        task = self.tasks.get(contract.task_id)
        if task is None:
            raise ValueError(f"task {contract.task_id!r} not found")
        updates = contract.to_updates()
        if not updates:
            return TaskUpdateActionResult(task=task, updated_fields=[])
        self._validate_task_update(actor_agent_key=actor_agent_key, updates=updates)
        if "assigned_agent_key" in updates:
            self._validate_agent_key(updates["assigned_agent_key"])
        updated_task = self.tasks.update_fields(task, updates=updates)
        return TaskUpdateActionResult(task=updated_task, updated_fields=sorted(updates))

    @staticmethod
    def _default_idempotency_key(
        *,
        conversation_id: str | None,
        kind: str,
        title: str,
        parent_task_id: str | None,
    ) -> str:
        normalized = _normalize_whitespace(title).lower()
        scope = parent_task_id or conversation_id or "global"
        return f"{kind}:{scope}:{normalized}"

    @staticmethod
    def _validate_agent_key(agent_key: str | None) -> None:
        if agent_key is None:
            return
        get_agent_profile(agent_key)

    @staticmethod
    def _validate_task_update(*, actor_agent_key: str, updates: dict[str, object]) -> None:
        allowed_fields = {
            "principal": {
                "scope",
                "acceptance_criteria_markdown",
                "assigned_agent_key",
                "updates_markdown",
                "blockers_markdown",
                "observations_markdown",
            },
            "po_pm": {
                "scope",
                "acceptance_criteria_markdown",
                "assigned_agent_key",
                "updates_markdown",
                "blockers_markdown",
                "observations_markdown",
            },
            "specialist": {
                "updates_markdown",
                "blockers_markdown",
                "result_markdown",
                "observations_markdown",
            },
            "qa": {
                "updates_markdown",
                "blockers_markdown",
                "result_markdown",
                "observations_markdown",
                "evidence_markdown",
            },
            "github": {
                "repository_name",
                "branch_name",
                "updates_markdown",
                "observations_markdown",
                "evidence_markdown",
            },
            "devops": {
                "environment_name",
                "updates_markdown",
                "blockers_markdown",
                "observations_markdown",
                "evidence_markdown",
                "gmud_reference",
            },
            "frontend": {
                "updates_markdown",
                "blockers_markdown",
                "result_markdown",
                "observations_markdown",
                "evidence_markdown",
            },
            "backend_python": {
                "updates_markdown",
                "blockers_markdown",
                "result_markdown",
                "observations_markdown",
                "evidence_markdown",
            },
        }.get(actor_agent_key, {"updates_markdown", "observations_markdown"})
        forbidden = sorted(set(updates) - allowed_fields)
        if forbidden:
            raise ValueError(
                f"agent {actor_agent_key!r} is not allowed to update task fields: {', '.join(forbidden)}"
            )

    @staticmethod
    def _agent_keys() -> set[str]:
        from marrowy.domain.agents import AGENT_PROFILES

        return set(AGENT_PROFILES)
