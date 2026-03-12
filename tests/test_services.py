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
    assert {"principal", "qa"}.issubset(participant_keys)

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


@pytest.mark.asyncio
async def test_follow_up_coordination_does_not_duplicate_pipeline(db_session):
    project = ProjectService(db_session).seed_default_project()
    service = ConversationService(db_session, FakeProvider())
    conversation = service.create_conversation(title="Pipeline dedupe", project_id=project.id, user_name="Elian")
    db_session.commit()

    await service.handle_user_message(
        conversation.id,
        content="Please create the task pipeline for a basic todo MVP with diagnosis, implementation, QA, and deploy readiness.",
        user_name="Elian",
    )
    db_session.commit()
    initial_pipeline_count = len([task for task in service.tasks.list_for_conversation(conversation.id) if task.kind == "pipeline"])

    await service.handle_user_message(
        conversation.id,
        content="Add Agent PO/PM and give them a short onboarding handoff for the active todo MVP pipeline.",
        user_name="Elian",
    )
    db_session.commit()
    pipeline_count = len([task for task in service.tasks.list_for_conversation(conversation.id) if task.kind == "pipeline"])
    participants = service.list_participants(conversation.id)

    assert pipeline_count == initial_pipeline_count == 1
    assert any(participant.agent_key == "po_pm" for participant in participants)


@pytest.mark.asyncio
async def test_repeated_agent_addition_does_not_duplicate_handoff_or_participant(db_session):
    project = ProjectService(db_session).seed_default_project()
    service = ConversationService(db_session, FakeProvider())
    conversation = service.create_conversation(title="Onboarding dedupe", project_id=project.id, user_name="Elian")
    db_session.commit()

    await service.handle_user_message(
        conversation.id,
        content="Add Agent QA and give them a short onboarding handoff for the active pipeline.",
        user_name="Elian",
    )
    await service.handle_user_message(
        conversation.id,
        content="Add Agent QA and give them a short onboarding handoff for the active pipeline.",
        user_name="Elian",
    )
    db_session.commit()

    participants = [item for item in service.list_participants(conversation.id) if item.agent_key == "qa"]
    handoffs = [
        message
        for message in service.list_messages(conversation.id)
        if message.message_type == "handoff" and message.metadata_json.get("handoffFor") == "qa"
    ]

    assert len(participants) == 1
    assert len(handoffs) == 1


@pytest.mark.asyncio
async def test_repeated_deploy_requests_do_not_duplicate_pending_approvals(db_session):
    project = ProjectService(db_session).seed_default_project()
    service = ConversationService(db_session, FakeProvider())
    conversation = service.create_conversation(title="Approval dedupe", project_id=project.id, user_name="Elian")
    db_session.commit()

    await service.handle_user_message(
        conversation.id,
        content="Please create the task pipeline for a basic single-user web todo MVP with diagnosis, implementation, QA, and deploy readiness.",
        user_name="Elian",
    )
    await service.handle_user_message(
        conversation.id,
        content="Please prepare a production deployment for the active MVP pipeline.",
        user_name="Elian",
    )
    db_session.commit()

    approvals = service.policies.pending_for_conversation(conversation.id)
    assert len(approvals) == 1


@pytest.mark.asyncio
async def test_qa_and_devops_statuses_do_not_jump_to_done_or_deploying(db_session):
    project = ProjectService(db_session).seed_default_project()
    service = ConversationService(db_session, FakeProvider())
    conversation = service.create_conversation(title="Status guard", project_id=project.id, user_name="Elian")
    db_session.commit()

    await service.handle_user_message(
        conversation.id,
        content="Please create the task pipeline for a basic single-user web todo MVP with diagnosis, implementation, QA, and deploy readiness.",
        user_name="Elian",
    )
    await service.handle_user_message(
        conversation.id,
        content="Add Agent QA and ask for the first validation focus.",
        user_name="Elian",
    )
    await service.handle_user_message(
        conversation.id,
        content="Add Agent DevOps and ask for the environment and deploy prerequisites.",
        user_name="Elian",
    )
    db_session.commit()

    tasks = service.tasks.list_for_conversation(conversation.id)
    qa_task = next(task for task in tasks if task.assigned_agent_key == "qa")
    devops_task = next(task for task in tasks if task.assigned_agent_key == "devops")
    assert qa_task.status == "testing"
    assert devops_task.status == "blocked"


@pytest.mark.asyncio
async def test_deploy_request_reuses_active_pipeline_instead_of_creating_new_one(db_session):
    project = ProjectService(db_session).seed_default_project()
    service = ConversationService(db_session, FakeProvider())
    conversation = service.create_conversation(title="Deploy reuse", project_id=project.id, user_name="Elian")
    db_session.commit()

    await service.handle_user_message(
        conversation.id,
        content="Please create the task pipeline for a release checklist MVP.",
        user_name="Elian",
    )
    await service.handle_user_message(
        conversation.id,
        content="Please prepare a production deployment for the active pipeline.",
        user_name="Elian",
    )
    db_session.commit()

    root_tasks = [task for task in service.tasks.list_for_conversation(conversation.id) if task.parent_task_id is None]
    assert len(root_tasks) == 1


@pytest.mark.asyncio
async def test_decomposition_targets_the_named_pipeline(db_session):
    project = ProjectService(db_session).seed_default_project()
    service = ConversationService(db_session, FakeProvider())
    conversation = service.create_conversation(title="Targeted decomposition", project_id=project.id, user_name="Elian")
    db_session.commit()

    await service.handle_user_message(
        conversation.id,
        content="Please create the task pipeline for a release checklist MVP.",
        user_name="Elian",
    )
    await service.handle_user_message(
        conversation.id,
        content="Create another project pipeline for a personal notes MVP.",
        user_name="Elian",
    )
    await service.handle_user_message(
        conversation.id,
        content="Please ask Agent PO/PM to decompose the personal notes MVP into small incremental steps with subtasks.",
        user_name="Elian",
    )
    db_session.commit()

    tasks = service.tasks.list_for_conversation(conversation.id)
    notes_root = next(task for task in tasks if task.parent_task_id is None and "notes" in task.title.lower())
    note_subtasks = [task for task in tasks if task.parent_task_id == notes_root.id and task.kind == "subtask"]
    assert len(note_subtasks) == 4
