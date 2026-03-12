from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends

from marrowy.api.deps import get_project_service
from marrowy.schemas.projects import ProjectCreate
from marrowy.schemas.projects import ProjectRead
from marrowy.services.projects import ProjectService

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRead])
def list_projects(service: ProjectService = Depends(get_project_service)) -> list[ProjectRead]:
    return [ProjectRead.model_validate(project) for project in service.list_projects()]


@router.post("", response_model=ProjectRead)
def create_project(payload: ProjectCreate, service: ProjectService = Depends(get_project_service)) -> ProjectRead:
    project = service.create_project(payload)
    service.db.commit()
    return ProjectRead.model_validate(project)
