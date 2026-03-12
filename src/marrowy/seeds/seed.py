from __future__ import annotations

from sqlalchemy.orm import Session

from marrowy.services.projects import ProjectService


def seed_database(db: Session) -> None:
    ProjectService(db).seed_default_project()
