from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from marrowy.api.deps import get_conversation_service
from marrowy.api.deps import get_project_service
from marrowy.api.deps import get_task_service
from marrowy.core.settings import get_settings
from marrowy.domain.agents import list_all_profiles
from marrowy.services.conversations import ConversationService
from marrowy.services.projects import ProjectService
from marrowy.services.tasks import TaskService

templates = Jinja2Templates(directory=str(get_settings().base_dir / "src" / "marrowy" / "api" / "templates"))

router = APIRouter(tags=["ui"])


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    projects: ProjectService = Depends(get_project_service),
    conversations: ConversationService = Depends(get_conversation_service),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "title": get_settings().ui_title,
            "projects": projects.list_projects(),
            "conversations": conversations.list_conversations(),
        },
    )


@router.get("/conversations/{conversation_id}", response_class=HTMLResponse)
def conversation_page(
    conversation_id: str,
    request: Request,
    conversations: ConversationService = Depends(get_conversation_service),
    tasks: TaskService = Depends(get_task_service),
) -> HTMLResponse:
    conversation = conversations.get_conversation(conversation_id)
    if conversation is None:
        return templates.TemplateResponse(request, "404.html", {"title": "Not found"}, status_code=404)
    participants = conversations.list_participants(conversation_id)
    return templates.TemplateResponse(
        request,
        "conversation.html",
        {
            "title": conversation.title,
            "conversation": conversation,
            "all_conversations": conversations.list_conversations(),
            "messages": conversations.list_messages(conversation_id),
            "participants": participants,
            "participant_agent_keys": [participant.agent_key for participant in participants if participant.agent_key],
            "tasks": tasks.list_for_conversation(conversation_id),
            "approvals": conversations.policies.pending_for_conversation(conversation_id),
            "agent_profiles": [asdict(profile) for profile in list_all_profiles()],
        },
    )
