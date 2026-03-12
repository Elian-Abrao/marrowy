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

    def create_simple_task(
        self,
        *,
        conversation_id: str | None,
        project_id: str | None,
        title: str,
        goal: str,
        assigned_agent_key: str | None = None,
        scope: str | None = None,
        details_markdown: str | None = None,
        created_by_message_id: str | None = None,
    ) -> Task:
        task = Task(
            conversation_id=conversation_id,
            project_id=project_id,
            title=title,
            goal=goal,
            scope=scope,
            status=TaskStatus.CREATED.value,
            kind=TaskKind.SIMPLE.value,
            assigned_agent_key=assigned_agent_key,
            details_markdown=details_markdown,
            created_by_message_id=created_by_message_id,
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
        template_name: str = "default_delivery",
        created_by_message_id: str | None = None,
    ) -> tuple[Task, list[Task]]:
        root = Task(
            conversation_id=conversation_id,
            project_id=project_id,
            title=title,
            goal=goal,
            status=TaskStatus.PLANNED.value,
            kind=TaskKind.PIPELINE.value,
            created_by_message_id=created_by_message_id,
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
            )
            self.db.add(task)
            stages.append(task)
        self.db.flush()
        self.events.emit("task.created", conversation_id=conversation_id, task_id=root.id, payload={"taskId": root.id, "pipeline": True})
        return root, stages

    def set_status(self, task: Task, status: TaskStatus, *, result_markdown: str | None = None) -> Task:
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
