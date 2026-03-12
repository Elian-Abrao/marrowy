from __future__ import annotations


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
        json={"content": "Please build a mini dashboard MVP and add QA for validation.", "author_name": "Elian"},
    )
    assert response.status_code == 200
    messages = response.json()
    assert len(messages) >= 3

    tasks = client.get(f"/api/conversations/{conversation['id']}/tasks").json()
    assert any(task["kind"] == "pipeline" for task in tasks)

    participants = client.get(f"/api/conversations/{conversation['id']}/participants").json()
    keys = {participant["agent_key"] for participant in participants if participant["agent_key"]}
    assert {"principal", "specialist", "qa"}.issubset(keys)


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
    assert "Task Board" in conversation_page.text
