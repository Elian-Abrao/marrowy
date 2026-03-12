from __future__ import annotations

import pytest

from marrowy.providers.fake import FakeProvider
from marrowy.services.conversations import ConversationService
from marrowy.services.projects import ProjectService


@pytest.mark.asyncio
async def test_conversation_service_creates_pipeline_and_agents(db_session):
    project = ProjectService(db_session).seed_default_project()
    db_session.commit()
    service = ConversationService(db_session, FakeProvider())
    conversation = service.create_conversation(title="Build MVP", project_id=project.id, user_name="Elian")
    db_session.commit()

    messages = await service.handle_user_message(
        conversation.id,
        content="Please create a todo MVP pipeline, add QA, and prepare deploy validation.",
        user_name="Elian",
    )
    db_session.commit()

    assert len(messages) >= 4
    participants = service.list_participants(conversation.id)
    participant_keys = {item.agent_key for item in participants if item.agent_key}
    assert {"principal", "specialist", "qa", "devops"}.issubset(participant_keys)

    tasks = service.tasks.list_for_conversation(conversation.id)
    assert any(task.kind == "pipeline" for task in tasks)
    assert any(task.assigned_agent_key == "qa" for task in tasks)


@pytest.mark.asyncio
async def test_resolving_approval_updates_task_state(db_session):
    project = ProjectService(db_session).seed_default_project()
    service = ConversationService(db_session, FakeProvider())
    conversation = service.create_conversation(title="Deploy check", project_id=project.id, user_name="Elian")
    db_session.commit()

    await service.handle_user_message(
        conversation.id,
        content="Create a deploy pipeline and deploy to production.",
        user_name="Elian",
    )
    db_session.commit()

    approvals = service.policies.pending_for_conversation(conversation.id)
    assert approvals
    approval = service.resolve_approval(approvals[0].id, actor_name="Elian", decision="approve")
    db_session.commit()

    assert approval.status == "approved"
    task = service.tasks.get(approval.task_id)
    assert task is not None
    assert task.status == "deploying"
