from __future__ import annotations

from marrowy.services.conversations import ConversationService
from marrowy.services.domain_actions import AddAgentContract
from marrowy.services.domain_actions import AgentProfileContract
from marrowy.services.domain_actions import DomainActionService
from marrowy.services.domain_actions import TaskContract
from marrowy.services.domain_actions import TaskUpdateContract
from marrowy.providers.fake import FakeProvider
from marrowy.services.projects import ProjectService


def test_domain_actions_create_rich_task_contract(db_session):
    project = ProjectService(db_session).seed_default_project()
    conversation = ConversationService(db_session, FakeProvider()).create_conversation(
        title="Rich task",
        project_id=project.id,
        user_name="Elian",
    )
    db_session.commit()

    actions = DomainActionService(db_session)
    result = actions.create_task(
        conversation_id=conversation.id,
        project_id=project.id,
        contract=TaskContract(
            title="Implement image upload review",
            goal="Allow agents to review uploaded images and keep evidence.",
            kind="simple",
            scope="Upload flow and QA validation",
            acceptance_criteria_markdown="- image upload works\n- QA evidence is attached",
            repository_name="marrowy",
            branch_name="feature/image-review",
            environment_name="staging",
            assigned_agent_key="qa",
            details_markdown="Requested manually from test.",
            blockers_markdown="Waiting for sample images.",
            approval_required=True,
            observations_markdown="Keep the flow audit-friendly.",
            evidence_markdown="Attach screenshots of success and failure cases.",
            gmud_reference="GMUD-1234",
        ),
    )
    db_session.commit()

    assert result.created is True
    assert result.task.acceptance_criteria_markdown is not None
    assert result.task.repository_name == "marrowy"
    assert result.task.branch_name == "feature/image-review"
    assert result.task.environment_name == "staging"
    assert result.task.approval_required is True
    assert result.task.gmud_reference == "GMUD-1234"


def test_domain_actions_create_agent_profile_and_add_to_room(db_session):
    project = ProjectService(db_session).seed_default_project()
    service = ConversationService(db_session, FakeProvider())
    conversation = service.create_conversation(title="Custom agent", project_id=project.id, user_name="Elian")
    db_session.commit()

    actions = DomainActionService(db_session)
    profile_result = actions.create_agent_profile(
        AgentProfileContract(
            key="ux_prompt_engineer",
            display_name="Agent UX Prompt Engineer",
            summary="Designs and refines prompts for structured outputs.",
            instructions="Focus on prompt quality and controllability.",
            can_create_tasks=True,
        )
    )
    participant_result = actions.add_agent_to_room(
        conversation_id=conversation.id,
        contract=AddAgentContract(agent_key=profile_result.profile.key, reason="Prompt work is needed."),
    )
    db_session.commit()

    assert profile_result.created is True
    assert participant_result.added is True
    assert participant_result.participant.agent_key == "ux_prompt_engineer"


def test_domain_actions_restrict_task_update_fields_by_agent(db_session):
    project = ProjectService(db_session).seed_default_project()
    service = ConversationService(db_session, FakeProvider())
    conversation = service.create_conversation(title="Restricted task update", project_id=project.id, user_name="Elian")
    task = service.tasks.create_simple_task(
        conversation_id=conversation.id,
        project_id=project.id,
        title="Frontend implementation",
        goal="Implement the frontend flow",
        assigned_agent_key="specialist",
    )
    db_session.commit()

    actions = DomainActionService(db_session)
    result = actions.update_task(
        actor_agent_key="qa",
        contract=TaskUpdateContract(
            task_id=task.id,
            evidence_markdown="Added browser screenshots.",
            result_markdown="Core flow validated.",
        ),
    )
    db_session.commit()

    assert result.updated_fields == ["evidence_markdown", "result_markdown"]
    assert task.evidence_markdown == "Added browser screenshots."

    try:
        actions.update_task(
            actor_agent_key="specialist",
            contract=TaskUpdateContract(task_id=task.id, assigned_agent_key="qa"),
        )
    except ValueError as exc:
        assert "not allowed" in str(exc)
    else:
        raise AssertionError("expected restricted task update to fail")
