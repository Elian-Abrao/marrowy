from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from marrowy.api.app import create_app
from marrowy.api.deps import get_conversation_service
from marrowy.api.deps import get_db
from marrowy.api.deps import get_project_service
from marrowy.api.deps import get_provider
from marrowy.api.deps import get_task_service
from marrowy.db.base import Base
from marrowy.providers.fake import FakeProvider
from marrowy.services.conversations import ConversationService
from marrowy.services.projects import ProjectService
from marrowy.services.tasks import TaskService


@pytest.fixture()
def db_session(tmp_path) -> Generator[Session, None, None]:
    db_path = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite+pysqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def app(db_session: Session):
    app = create_app()

    def _get_db():
        yield db_session

    def _get_provider():
        return FakeProvider()

    def _get_project_service():
        return ProjectService(db_session)

    def _get_task_service():
        return TaskService(db_session)

    def _get_conversation_service():
        return ConversationService(db_session, FakeProvider())

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_provider] = _get_provider
    app.dependency_overrides[get_project_service] = _get_project_service
    app.dependency_overrides[get_task_service] = _get_task_service
    app.dependency_overrides[get_conversation_service] = _get_conversation_service
    return app


@pytest.fixture()
def client(app) -> Generator[TestClient, None, None]:
    with TestClient(app) as client:
        yield client
