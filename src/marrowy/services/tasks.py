from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from marrowy.db.models import PipelineTemplate
from marrowy.db.models import Task
from marrowy.domain.enums import TaskKind
from marrowy.domain.enums import TaskStatus
from marrowy.services.events import EventService


class TaskService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.events = EventService(db)

    def list_for_conversation(self, conversation_id: str) -> list[Task]:
        stmt = select(Task).where(Task.conversation_id == conversation_id).order_by(Task.created_at, Task.order_index)
        return list(self.db.scalars(stmt))

    def get(self, task_id: str) -> Task | None:
        return self.db.get(Task, task_id)

    def list_subtasks(self, parent_task_id: str) -> list[Task]:
        stmt = select(Task).where(Task.parent_task_id == parent_task_id).order_by(Task.order_index, Task.created_at)
        return list(self.db.scalars(stmt))

    def find_active_by_idempotency(self, *, conversation_id: str | None, idempotency_key: str) -> Task | None:
        stmt = select(Task).where(Task.idempotency_key == idempotency_key)
        if conversation_id is not None:
            stmt = stmt.where(Task.conversation_id == conversation_id)
        return self.db.scalar(stmt.order_by(Task.created_at.desc()))

    def create_simple_task(
        self,
        *,
        conversation_id: str | None,
        project_id: str | None,
        title: str,
        goal: str,
        assigned_agent_key: str | None = None,
        scope: str | None = None,
        acceptance_criteria_markdown: str | None = None,
        repository_name: str | None = None,
        branch_name: str | None = None,
        environment_name: str | None = None,
        details_markdown: str | None = None,
        updates_markdown: str | None = None,
        blockers_markdown: str | None = None,
        approval_required: bool = False,
        result_markdown: str | None = None,
        observations_markdown: str | None = None,
        evidence_markdown: str | None = None,
        gmud_reference: str | None = None,
        created_by_message_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Task:
        if idempotency_key:
            existing = self.find_active_by_idempotency(conversation_id=conversation_id, idempotency_key=idempotency_key)
            if existing is not None:
                return existing
        task = Task(
            conversation_id=conversation_id,
            project_id=project_id,
            title=title,
            goal=goal,
            scope=scope,
            acceptance_criteria_markdown=acceptance_criteria_markdown,
            repository_name=repository_name,
            branch_name=branch_name,
            environment_name=environment_name,
            status=TaskStatus.CREATED.value,
            kind=TaskKind.SIMPLE.value,
            assigned_agent_key=assigned_agent_key,
            details_markdown=details_markdown,
            updates_markdown=updates_markdown,
            blockers_markdown=blockers_markdown,
            approval_required=approval_required,
            result_markdown=result_markdown,
            observations_markdown=observations_markdown,
            evidence_markdown=evidence_markdown,
            gmud_reference=gmud_reference,
            created_by_message_id=created_by_message_id,
            idempotency_key=idempotency_key,
        )
        self.db.add(task)
        self.db.flush()
        self.events.emit("task.created", conversation_id=conversation_id, task_id=task.id, payload={"taskId": task.id, "title": title})
        return task

    def create_pipeline_task(
        self,
        *,
        conversation_id: str,
        project_id: str | None,
        title: str,
        goal: str,
        scope: str | None = None,
        acceptance_criteria_markdown: str | None = None,
        repository_name: str | None = None,
        branch_name: str | None = None,
        environment_name: str | None = None,
        assigned_agent_key: str | None = None,
        details_markdown: str | None = None,
        updates_markdown: str | None = None,
        blockers_markdown: str | None = None,
        approval_required: bool = False,
        result_markdown: str | None = None,
        observations_markdown: str | None = None,
        evidence_markdown: str | None = None,
        gmud_reference: str | None = None,
        template_name: str = "default_delivery",
        created_by_message_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[Task, list[Task]]:
        if idempotency_key:
            existing = self.find_active_by_idempotency(conversation_id=conversation_id, idempotency_key=idempotency_key)
            if existing is not None:
                return existing, self.list_subtasks(existing.id)
        root = Task(
            conversation_id=conversation_id,
            project_id=project_id,
            title=title,
            goal=goal,
            scope=scope,
            acceptance_criteria_markdown=acceptance_criteria_markdown,
            repository_name=repository_name,
            branch_name=branch_name,
            environment_name=environment_name,
            status=TaskStatus.PLANNED.value,
            kind=TaskKind.PIPELINE.value,
            assigned_agent_key=assigned_agent_key,
            details_markdown=details_markdown,
            updates_markdown=updates_markdown,
            blockers_markdown=blockers_markdown,
            approval_required=approval_required,
            result_markdown=result_markdown,
            observations_markdown=observations_markdown,
            evidence_markdown=evidence_markdown,
            gmud_reference=gmud_reference,
            created_by_message_id=created_by_message_id,
            idempotency_key=idempotency_key,
        )
        self.db.add(root)
        self.db.flush()
        template = self.db.scalar(
            select(PipelineTemplate).where(PipelineTemplate.name == template_name, PipelineTemplate.project_id == project_id)
        ) or self.db.scalar(select(PipelineTemplate).where(PipelineTemplate.name == template_name, PipelineTemplate.project_id.is_(None)))
        stages: list[Task] = []
        definition = template.definition_json if template else {
            "stages": [
                {"title": "Diagnosis", "assignedAgent": "specialist"},
                {"title": "Implementation", "assignedAgent": "specialist"},
                {"title": "QA", "assignedAgent": "qa"},
                {"title": "Deploy", "assignedAgent": "devops"},
            ]
        }
        for index, stage in enumerate(definition.get("stages", [])):
            task = Task(
                conversation_id=conversation_id,
                project_id=project_id,
                parent_task_id=root.id,
                title=f"{title}: {stage['title']}",
                goal=stage["title"],
                status=TaskStatus.CREATED.value,
                kind=TaskKind.STAGE.value,
                assigned_agent_key=stage.get("assignedAgent"),
                order_index=index,
                idempotency_key=f"{root.id}:stage:{index}",
            )
            self.db.add(task)
            stages.append(task)
        self.db.flush()
        self.events.emit("task.created", conversation_id=conversation_id, task_id=root.id, payload={"taskId": root.id, "pipeline": True})
        return root, stages

    def create_subtask(
        self,
        *,
        conversation_id: str | None,
        project_id: str | None,
        parent_task_id: str,
        title: str,
        goal: str,
        assigned_agent_key: str | None = None,
        order_index: int = 0,
        scope: str | None = None,
        acceptance_criteria_markdown: str | None = None,
        repository_name: str | None = None,
        branch_name: str | None = None,
        environment_name: str | None = None,
        details_markdown: str | None = None,
        updates_markdown: str | None = None,
        blockers_markdown: str | None = None,
        approval_required: bool = False,
        result_markdown: str | None = None,
        observations_markdown: str | None = None,
        evidence_markdown: str | None = None,
        gmud_reference: str | None = None,
        created_by_message_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Task:
        if idempotency_key:
            existing = self.find_active_by_idempotency(conversation_id=conversation_id, idempotency_key=idempotency_key)
            if existing is not None:
                return existing
        task = Task(
            conversation_id=conversation_id,
            project_id=project_id,
            parent_task_id=parent_task_id,
            title=title,
            goal=goal,
            scope=scope,
            acceptance_criteria_markdown=acceptance_criteria_markdown,
            repository_name=repository_name,
            branch_name=branch_name,
            environment_name=environment_name,
            status=TaskStatus.CREATED.value,
            kind=TaskKind.SUBTASK.value,
            assigned_agent_key=assigned_agent_key,
            order_index=order_index,
            details_markdown=details_markdown,
            updates_markdown=updates_markdown,
            blockers_markdown=blockers_markdown,
            approval_required=approval_required,
            result_markdown=result_markdown,
            observations_markdown=observations_markdown,
            evidence_markdown=evidence_markdown,
            gmud_reference=gmud_reference,
            created_by_message_id=created_by_message_id,
            idempotency_key=idempotency_key,
        )
        self.db.add(task)
        self.db.flush()
        self.events.emit("task.created", conversation_id=conversation_id, task_id=task.id, payload={"taskId": task.id, "parentTaskId": parent_task_id, "kind": "subtask"})
        return task

    def ensure_subtasks(
        self,
        *,
        conversation_id: str | None,
        project_id: str | None,
        parent_task_id: str,
        items: list[dict[str, object]],
        created_by_message_id: str | None = None,
    ) -> list[Task]:
        created: list[Task] = []
        for index, item in enumerate(items):
            title = str(item["title"])
            task = self.create_subtask(
                conversation_id=conversation_id,
                project_id=project_id,
                parent_task_id=parent_task_id,
                title=title,
                goal=str(item.get("goal") or title),
                assigned_agent_key=item.get("assigned_agent_key"),
                order_index=int(item.get("order_index") or index),
                scope=item.get("scope"),
                acceptance_criteria_markdown=item.get("acceptance_criteria_markdown"),
                repository_name=item.get("repository_name"),
                branch_name=item.get("branch_name"),
                environment_name=item.get("environment_name"),
                details_markdown=item.get("details_markdown"),
                updates_markdown=item.get("updates_markdown"),
                blockers_markdown=item.get("blockers_markdown"),
                approval_required=bool(item.get("approval_required") or False),
                result_markdown=item.get("result_markdown"),
                observations_markdown=item.get("observations_markdown"),
                evidence_markdown=item.get("evidence_markdown"),
                gmud_reference=item.get("gmud_reference"),
                created_by_message_id=created_by_message_id,
                idempotency_key=f"{parent_task_id}:subtask:{index}:{title.lower().strip()}",
            )
            created.append(task)
        return created

    def set_status(self, task: Task, status: TaskStatus, *, result_markdown: str | None = None) -> Task:
        if not self._can_transition(task.status, status.value):
            raise ValueError(f"invalid task transition from {task.status} to {status.value}")
        task.status = status.value
        if result_markdown is not None:
            task.result_markdown = result_markdown
        self.db.flush()
        self.events.emit(
            "task.status.updated",
            conversation_id=task.conversation_id,
            task_id=task.id,
            payload={"taskId": task.id, "status": task.status},
        )
        return task

    def update_fields(self, task: Task, *, updates: dict[str, object]) -> Task:
        applied: dict[str, object] = {}
        for field_name, value in updates.items():
            if getattr(task, field_name) == value:
                continue
            setattr(task, field_name, value)
            applied[field_name] = value
        if not applied:
            return task
        self.db.flush()
        self.events.emit(
            "task.updated",
            conversation_id=task.conversation_id,
            task_id=task.id,
            payload={"taskId": task.id, "updatedFields": sorted(applied)},
        )
        return task

    @staticmethod
    def _can_transition(current: str, target: str) -> bool:
        if current == target:
            return True
        allowed = {
            TaskStatus.CREATED.value: {
                TaskStatus.PLANNED.value,
                TaskStatus.IN_PROGRESS.value,
                TaskStatus.TESTING.value,
                TaskStatus.BLOCKED.value,
                TaskStatus.CANCELLED.value,
            },
            TaskStatus.PLANNED.value: {
                TaskStatus.IN_PROGRESS.value,
                TaskStatus.BLOCKED.value,
                TaskStatus.WAITING_APPROVAL.value,
                TaskStatus.CANCELLED.value,
            },
            TaskStatus.IN_PROGRESS.value: {
                TaskStatus.TESTING.value,
                TaskStatus.BLOCKED.value,
                TaskStatus.WAITING_APPROVAL.value,
                TaskStatus.DONE.value,
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
            },
            TaskStatus.BLOCKED.value: {
                TaskStatus.PLANNED.value,
                TaskStatus.IN_PROGRESS.value,
                TaskStatus.WAITING_APPROVAL.value,
                TaskStatus.CANCELLED.value,
            },
            TaskStatus.WAITING_APPROVAL.value: {
                TaskStatus.PLANNED.value,
                TaskStatus.BLOCKED.value,
                TaskStatus.DEPLOYING.value,
                TaskStatus.CANCELLED.value,
            },
            TaskStatus.TESTING.value: {
                TaskStatus.IN_PROGRESS.value,
                TaskStatus.BLOCKED.value,
                TaskStatus.DONE.value,
                TaskStatus.FAILED.value,
            },
            TaskStatus.DEPLOYING.value: {
                TaskStatus.DONE.value,
                TaskStatus.FAILED.value,
                TaskStatus.BLOCKED.value,
            },
            TaskStatus.FAILED.value: {
                TaskStatus.PLANNED.value,
                TaskStatus.IN_PROGRESS.value,
                TaskStatus.CANCELLED.value,
            },
            TaskStatus.DONE.value: set(),
            TaskStatus.CANCELLED.value: set(),
        }
        return target in allowed.get(current, set())
