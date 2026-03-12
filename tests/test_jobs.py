from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from marrowy.db.base import Base
from marrowy.db.models import ConversationMessage
from marrowy.domain.enums import JobStatus
from marrowy.domain.enums import ParticipantActivityState
from marrowy.providers.base import ProviderResult
from marrowy.providers.fake import FakeProvider
from marrowy.services.conversations import ConversationService
from marrowy.services.job_runner import JobRunner
from marrowy.services.projects import ProjectService


class SlowProvider:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(
        self,
        *,
        role_name: str,
        instructions: str,
        prompt: str,
        thread_id: str | None = None,
        cwd: str | None = None,
        event_handler=None,
    ) -> tuple[ProviderResult, str | None]:
        self.started.set()
        if event_handler is not None:
            maybe = event_handler("commentary", f"{role_name} started working.")
            if asyncio.iscoroutine(maybe):
                await maybe
        await self.release.wait()
        return ProviderResult(text=f"[{role_name}] done"), thread_id or f"slow-{role_name}"


@pytest.mark.asyncio
async def test_handle_user_message_acks_and_enqueues_jobs_immediately(db_session: Session):
    project = ProjectService(db_session).seed_default_project()
    service = ConversationService(db_session, FakeProvider())
    conversation = service.create_conversation(title="Immediate ACK", project_id=project.id, user_name="Elian")
    db_session.commit()

    messages = await service.handle_user_message(
        conversation.id,
        content="Please create the task pipeline for a basic todo MVP and add QA.",
        user_name="Elian",
    )
    db_session.commit()

    assert any("I received your message" in message.content for message in messages)
    jobs = service.jobs.list_for_conversation(conversation.id)
    assert jobs
    assert any(job.worker_key == "summary" for job in jobs)
    assert any(job.status == JobStatus.QUEUED.value for job in jobs)
    participants = service.list_participants(conversation.id)
    principal = next(item for item in participants if item.agent_key == "principal")
    assert principal.activity_state == ParticipantActivityState.QUEUED.value


@pytest.mark.asyncio
async def test_job_runner_processes_jobs_and_updates_participant_activity(db_session: Session):
    project = ProjectService(db_session).seed_default_project()
    service = ConversationService(db_session, FakeProvider())
    conversation = service.create_conversation(title="Runner flow", project_id=project.id, user_name="Elian")
    db_session.commit()

    await service.handle_user_message(
        conversation.id,
        content="Please create a simple follow-up task for documentation cleanup.",
        user_name="Elian",
    )
    db_session.commit()

    bind = db_session.get_bind()
    assert bind is not None
    SessionFactory = sessionmaker(bind=bind, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    runner = JobRunner(session_factory=SessionFactory, provider_factory=FakeProvider, poll_interval=0.05)
    await runner.run_until_idle(timeout=2.0)

    verify = SessionFactory()
    try:
        service = ConversationService(verify, FakeProvider())
        jobs = service.jobs.list_for_conversation(conversation.id)
        assert jobs
        assert all(job.status == JobStatus.SUCCEEDED.value for job in jobs)
        participants = service.list_participants(conversation.id)
        principal = next(item for item in participants if item.agent_key == "principal")
        assert principal.activity_state == ParticipantActivityState.IDLE.value
        assert any(message.author_name == "Agent Principal" and message.message_type == "agent" for message in service.list_messages(conversation.id))
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_decomposition_creates_subtasks_idempotently(db_session: Session):
    project = ProjectService(db_session).seed_default_project()
    service = ConversationService(db_session, FakeProvider())
    conversation = service.create_conversation(title="PO decomposition", project_id=project.id, user_name="Elian")
    db_session.commit()

    await service.handle_user_message(
        conversation.id,
        content="Please create the task pipeline for a release checklist MVP.",
        user_name="Elian",
    )
    await service.handle_user_message(
        conversation.id,
        content="Please ask Agent PO/PM to refine the MVP into small incremental steps with subtasks.",
        user_name="Elian",
    )
    await service.handle_user_message(
        conversation.id,
        content="Please ask Agent PO/PM to refine the MVP into small incremental steps with subtasks.",
        user_name="Elian",
    )
    db_session.commit()

    tasks = service.tasks.list_for_conversation(conversation.id)
    root = next(task for task in tasks if task.kind == "pipeline")
    subtasks = [task for task in tasks if task.parent_task_id == root.id and task.kind == "subtask"]
    assert len(subtasks) == 4


@pytest.mark.asyncio
async def test_enqueue_is_idempotent_for_same_worker_turn(db_session: Session):
    project = ProjectService(db_session).seed_default_project()
    service = ConversationService(db_session, FakeProvider())
    conversation = service.create_conversation(title="Job dedupe", project_id=project.id, user_name="Elian")
    db_session.commit()

    principal = next(item for item in service.list_participants(conversation.id) if item.agent_key == "principal")
    job_one, created_one = service.jobs.enqueue(
        conversation_id=conversation.id,
        worker_key="summary",
        agent_key="principal",
        participant_id=principal.id,
        source_message_id="source-1",
        summary="Agent Principal is preparing a coordinated reply.",
        idempotency_key=f"agent-turn:{conversation.id}:source-1:{principal.id}",
        payload={"prompt": "hello"},
    )
    job_two, created_two = service.jobs.enqueue(
        conversation_id=conversation.id,
        worker_key="summary",
        agent_key="principal",
        participant_id=principal.id,
        source_message_id="source-1",
        summary="Agent Principal is preparing a coordinated reply.",
        idempotency_key=f"agent-turn:{conversation.id}:source-1:{principal.id}",
        payload={"prompt": "hello"},
    )
    db_session.commit()

    assert created_one is True
    assert created_two is False
    assert job_one.id == job_two.id
    assert len(service.jobs.list_for_conversation(conversation.id)) == 1


@pytest.mark.asyncio
async def test_second_message_is_accepted_while_worker_is_running(db_session: Session):
    db_path = Path("/tmp/marrowy-concurrent-test.db")
    if db_path.exists():
        db_path.unlink()
    engine = create_engine(
        f"sqlite+pysqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    SessionFactory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)

    seed_session = SessionFactory()
    try:
        project = ProjectService(seed_session).seed_default_project()
        service = ConversationService(seed_session, SlowProvider())
        conversation = service.create_conversation(title="Concurrent flow", project_id=project.id, user_name="Elian")
        seed_session.commit()
    finally:
        seed_session.close()

    slow = SlowProvider()
    runner = JobRunner(session_factory=SessionFactory, provider_factory=lambda: slow, poll_interval=0.05)
    await runner.start()
    session_one = SessionFactory()
    try:
        service_one = ConversationService(session_one, slow)
        await service_one.handle_user_message(
            conversation.id,
            content="Please create a follow-up task for the release checklist.",
            user_name="Elian",
        )
        session_one.commit()
    finally:
        session_one.close()

    await asyncio.wait_for(slow.started.wait(), timeout=2.0)

    session_two = SessionFactory()
    try:
        service_two = ConversationService(session_two, slow)
        second = await service_two.handle_user_message(
            conversation.id,
            content="While that is running, add Agent QA and keep me updated.",
            user_name="Elian",
        )
        session_two.commit()
        assert any("I received your message" in message.content for message in second)
    finally:
        session_two.close()

    slow.release.set()
    await runner.stop()

    verify = SessionFactory()
    try:
        messages = (
            verify.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == conversation.id)
            .all()
        )
        user_messages = [message for message in messages if message.author_kind == "user"]
        assert len(user_messages) == 2
    finally:
        verify.close()
        engine.dispose()
