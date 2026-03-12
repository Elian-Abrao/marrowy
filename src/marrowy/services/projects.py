from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from marrowy.db.models import PipelineTemplate
from marrowy.db.models import Project
from marrowy.db.models import ProjectEnvironment
from marrowy.db.models import ProjectRepository
from marrowy.schemas.projects import ProjectCreate
from marrowy.services.events import EventService


class ProjectService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.events = EventService(db)

    def list_projects(self) -> list[Project]:
        return list(self.db.scalars(select(Project).order_by(Project.name)))

    def get_project(self, project_id: str) -> Project | None:
        return self.db.get(Project, project_id)

    def get_by_slug(self, slug: str) -> Project | None:
        return self.db.scalar(select(Project).where(Project.slug == slug))

    def create_project(self, payload: ProjectCreate) -> Project:
        project = Project(
            slug=payload.slug,
            name=payload.name,
            description=payload.description,
            context_markdown=payload.context_markdown,
            metadata_json={},
        )
        self.db.add(project)
        self.db.flush()
        self.events.emit("project.created", payload={"projectId": project.id, "slug": project.slug})
        return project

    def seed_default_project(self) -> Project:
        existing = self.db.scalar(select(Project).where(Project.slug == "marrowy-demo"))
        if existing is not None:
            return existing
        project = Project(
            slug="marrowy-demo",
            name="Marrowy Demo",
            description="Sample project used to validate multi-agent orchestration flows.",
            context_markdown=(
                "# Project Context\n\n"
                "- Default sandbox: development\n"
                "- Production deploys require approval\n"
                "- QA must validate before deploy tasks can finish"
            ),
            metadata_json={"defaultUserName": "Elian"},
        )
        self.db.add(project)
        self.db.flush()
        self.db.add_all(
            [
                ProjectRepository(project_id=project.id, name="marrowy", local_path=str(project.slug), is_primary=True),
                ProjectEnvironment(
                    project_id=project.id,
                    name="development",
                    kind="app",
                    approval_policy_json={"deploy_requires_approval": False},
                    details_json={"url": "http://127.0.0.1:8000"},
                ),
                ProjectEnvironment(
                    project_id=project.id,
                    name="production",
                    kind="app",
                    approval_policy_json={"deploy_requires_approval": True},
                    details_json={"url": "https://example.invalid"},
                ),
                PipelineTemplate(
                    project_id=project.id,
                    name="default_delivery",
                    definition_json={
                        "stages": [
                            {"title": "Diagnosis", "assignedAgent": "specialist"},
                            {"title": "Implementation", "assignedAgent": "specialist"},
                            {"title": "QA", "assignedAgent": "qa"},
                            {"title": "Deploy", "assignedAgent": "devops"},
                        ]
                    },
                ),
            ]
        )
        self.db.flush()
        self.events.emit("project.seeded", payload={"projectId": project.id})
        return project
