from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from marrowy.core.settings import Settings
from marrowy.core.settings import get_settings
from marrowy.db.session import get_db
from marrowy.providers.codex_bridge import CodexBridgeProvider
from marrowy.providers.fake import FakeProvider
from marrowy.services.conversations import ConversationService
from marrowy.services.projects import ProjectService
from marrowy.services.tasks import TaskService


def get_app_settings() -> Settings:
    return get_settings()


def get_provider(settings: Settings = Depends(get_app_settings)):
    if settings.model_provider == "fake":
        return FakeProvider()
    return CodexBridgeProvider(
        base_url=settings.codex_bridge_url,
        approval_policy=settings.codex_approval_policy,
        sandbox=settings.codex_sandbox,
    )


def get_project_service(db: Session = Depends(get_db)) -> ProjectService:
    return ProjectService(db)


def get_task_service(db: Session = Depends(get_db)) -> TaskService:
    return TaskService(db)


def get_conversation_service(
    db: Session = Depends(get_db),
    provider: CodexBridgeProvider = Depends(get_provider),
) -> ConversationService:
    return ConversationService(db, provider)
