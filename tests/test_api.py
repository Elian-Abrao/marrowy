from __future__ import annotations

from sqlalchemy import select

from marrowy.db.models import ApprovalRequest
from marrowy.db.models import Conversation
from marrowy.db.models import ConversationMessage
from marrowy.db.models import ConversationParticipant
from marrowy.db.models import DomainEvent
from marrowy.db.models import Job
from marrowy.db.models import Task


def test_project_and_conversation_api_flow(client, db_session):
    response = client.post(
        "/api/projects",
        json={
            "slug": "sample-project",
            "name": "Sample Project",
            "description": "API test project",
            "context_markdown": "# Context",
        },
    )
    assert response.status_code == 200
    project = response.json()

    response = client.post(
        "/api/conversations",
        json={
            "title": "Investigate issue",
            "project_id": project["id"],
            "channel": "browser",
        },
    )
    assert response.status_code == 200
    conversation = response.json()

    response = client.post(
        f"/api/conversations/{conversation['id']}/messages",
        json={"content": "Please create a mini dashboard MVP pipeline and add QA for validation.", "author_name": "Elian"},
    )
    assert response.status_code == 200
    messages = response.json()
    assert len(messages) >= 3

    tasks = client.get(f"/api/conversations/{conversation['id']}/tasks").json()
    assert any(task["kind"] == "pipeline" for task in tasks)

    participants = client.get(f"/api/conversations/{conversation['id']}/participants").json()
    keys = {participant["agent_key"] for participant in participants if participant["agent_key"]}
    assert {"principal", "qa"}.issubset(keys)
    assert any(participant["activity_state"] == "queued" for participant in participants if participant["agent_key"] == "principal")

    jobs = client.get(f"/api/conversations/{conversation['id']}/jobs").json()
    assert jobs
    assert any(job["worker_key"] == "summary" for job in jobs)


def test_whatsapp_channel_inbound(client, db_session):
    project_response = client.post(
        "/api/projects",
        json={"slug": "whatsapp-project", "name": "WhatsApp Project"},
    )
    project = project_response.json()
    response = client.post(
        "/api/channels/whatsapp/inbound",
        json={
            "group_key": "whatsapp:codex-group",
            "text": "Create a task to diagnose the repo and bring in specialist",
            "sender_name": "Elian",
            "project_slug": "whatsapp-project",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["replies"]


def test_browser_ui_pages_render(client, db_session):
    project = client.post("/api/projects", json={"slug": "ui-project", "name": "UI Project"}).json()
    conversation = client.post(
        "/api/conversations",
        json={"title": "UI conversation", "project_id": project["id"], "channel": "browser"},
    ).json()

    index = client.get("/")
    assert index.status_code == 200
    assert "Start Conversation" in index.text

    conversation_page = client.get(f"/conversations/{conversation['id']}")
    assert conversation_page.status_code == 200
    assert "Task Pipeline" in conversation_page.text


def test_delete_conversation_removes_related_state(client, db_session):
    project = client.post("/api/projects", json={"slug": "delete-project", "name": "Delete Project"}).json()
    conversation = client.post(
        "/api/conversations",
        json={"title": "Delete me", "project_id": project["id"], "channel": "browser"},
    ).json()
    response = client.post(
        f"/api/conversations/{conversation['id']}/messages",
        json={"content": "Please create a mini dashboard MVP pipeline and add QA for validation.", "author_name": "Elian"},
    )
    assert response.status_code == 200

    delete_response = client.delete(f"/api/conversations/{conversation['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "deleted"

    assert db_session.get(Conversation, conversation["id"]) is None
    assert db_session.scalar(select(ConversationMessage.id).where(ConversationMessage.conversation_id == conversation["id"])) is None
    assert db_session.scalar(select(ConversationParticipant.id).where(ConversationParticipant.conversation_id == conversation["id"])) is None
    assert db_session.scalar(select(Task.id).where(Task.conversation_id == conversation["id"])) is None
    assert db_session.scalar(select(Job.id).where(Job.conversation_id == conversation["id"])) is None
    assert db_session.scalar(select(ApprovalRequest.id).where(ApprovalRequest.conversation_id == conversation["id"])) is None
    assert db_session.scalar(select(DomainEvent.id).where(DomainEvent.conversation_id == conversation["id"])) is None
