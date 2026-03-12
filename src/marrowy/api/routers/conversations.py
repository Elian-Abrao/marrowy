from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from marrowy.api.deps import get_conversation_service
from marrowy.api.deps import get_task_service
from marrowy.api.deps import get_db
from marrowy.db.models import DomainEvent
from marrowy.domain.agents import list_all_profiles
from marrowy.domain.agents import register_agent
from marrowy.schemas.approvals import ApprovalRead
from marrowy.schemas.approvals import ApprovalResolve
from marrowy.schemas.conversations import AddAgentRequest
from marrowy.schemas.conversations import ConversationCreate
from marrowy.schemas.conversations import ConversationRead
from marrowy.schemas.jobs import JobRead
from marrowy.schemas.conversations import MessageCreate
from marrowy.schemas.conversations import MessageRead
from marrowy.schemas.conversations import ParticipantRead
from marrowy.schemas.tasks import TaskCreate
from marrowy.schemas.tasks import TaskRead
from marrowy.services.conversations import ConversationService
from marrowy.services.tasks import TaskService
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationRead])
def list_conversations(service: ConversationService = Depends(get_conversation_service)) -> list[ConversationRead]:
    return [ConversationRead.model_validate(item) for item in service.list_conversations()]


@router.post("", response_model=ConversationRead)
def create_conversation(payload: ConversationCreate, service: ConversationService = Depends(get_conversation_service)) -> ConversationRead:
    conversation = service.create_conversation(
        title=payload.title,
        project_id=payload.project_id,
        channel=payload.channel,
        external_ref=payload.external_ref,
    )
    service.db.commit()
    return ConversationRead.model_validate(conversation)


@router.get("/{conversation_id}", response_model=ConversationRead)
def get_conversation(conversation_id: str, service: ConversationService = Depends(get_conversation_service)) -> ConversationRead:
    conversation = service.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return ConversationRead.model_validate(conversation)


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: str, service: ConversationService = Depends(get_conversation_service)) -> dict[str, str]:
    deleted = service.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="conversation not found")
    service.db.commit()
    return {"status": "deleted", "conversationId": conversation_id}


@router.get("/{conversation_id}/messages", response_model=list[MessageRead])
def list_messages(conversation_id: str, service: ConversationService = Depends(get_conversation_service)) -> list[MessageRead]:
    return [MessageRead.model_validate(item) for item in service.list_messages(conversation_id)]


@router.get("/{conversation_id}/participants", response_model=list[ParticipantRead])
def list_participants(conversation_id: str, service: ConversationService = Depends(get_conversation_service)) -> list[ParticipantRead]:
    return [ParticipantRead.model_validate(item) for item in service.list_participants(conversation_id)]


@router.get("/{conversation_id}/tasks", response_model=list[TaskRead])
def list_tasks(conversation_id: str, tasks: TaskService = Depends(get_task_service)) -> list[TaskRead]:
    return [TaskRead.model_validate(item) for item in tasks.list_for_conversation(conversation_id)]


@router.get("/{conversation_id}/jobs", response_model=list[JobRead])
def list_jobs(conversation_id: str, service: ConversationService = Depends(get_conversation_service)) -> list[JobRead]:
    return [JobRead.model_validate(item) for item in service.jobs.list_for_conversation(conversation_id)]


@router.post("/{conversation_id}/jobs/{job_id}/cancel", response_model=JobRead)
def cancel_job(
    conversation_id: str,
    job_id: str,
    service: ConversationService = Depends(get_conversation_service),
) -> JobRead:
    jobs = service.jobs.list_for_conversation(conversation_id)
    job = next((j for j in jobs if str(j.id) == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    canceled = service.jobs.cancel(job)
    service.db.commit()
    return JobRead.model_validate(canceled)


@router.post("/{conversation_id}/messages", response_model=list[MessageRead])
async def post_message(
    conversation_id: str,
    payload: MessageCreate,
    service: ConversationService = Depends(get_conversation_service),
) -> list[MessageRead]:
    messages = await service.handle_user_message(
        conversation_id,
        content=payload.content,
        user_name=payload.author_name or "User",
    )
    service.db.commit()
    return [MessageRead.model_validate(item) for item in messages]


@router.post("/{conversation_id}/participants", response_model=ParticipantRead)
def add_agent(
    conversation_id: str,
    payload: AddAgentRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> ParticipantRead:
    participant = service.add_agent(conversation_id, payload.agent_key)
    service.db.commit()
    return ParticipantRead.model_validate(participant)


@router.get("/{conversation_id}/approvals", response_model=list[ApprovalRead])
def list_approvals(
    conversation_id: str,
    service: ConversationService = Depends(get_conversation_service),
) -> list[ApprovalRead]:
    approvals = service.policies.pending_for_conversation(conversation_id)
    return [ApprovalRead.model_validate(item) for item in approvals]


@router.post("/approvals/{approval_id}/resolve", response_model=ApprovalRead)
def resolve_approval(
    approval_id: str,
    payload: ApprovalResolve,
    service: ConversationService = Depends(get_conversation_service),
) -> ApprovalRead:
    decision = "approve" if payload.decision.lower().startswith("app") else "reject"
    approval = service.resolve_approval(approval_id, actor_name=payload.actor_name, decision=decision)
    service.db.commit()
    return ApprovalRead.model_validate(approval)


@router.get("/{conversation_id}/events")
async def stream_events(
    conversation_id: str,
    db: Session = Depends(get_db),
) -> EventSourceResponse:
    async def event_source():
        seen_ids: set[str] = set()
        while True:
            stmt = select(DomainEvent).where(DomainEvent.conversation_id == conversation_id).order_by(DomainEvent.created_at)
            rows = list(db.scalars(stmt))
            for event in rows:
                if event.id in seen_ids:
                    continue
                seen_ids.add(event.id)
                payload = {
                    "id": event.id,
                    "eventType": event.event_type,
                    "payload": event.payload_json,
                    "createdAt": event.created_at.isoformat(),
                }
                yield {"event": event.event_type, "data": json.dumps(payload)}
            await asyncio.sleep(0.4)

    return EventSourceResponse(event_source())


# --- Agent management ---

class AgentCreateRequest(BaseModel):
    key: str
    display_name: str
    summary: str
    instructions: str
    can_create_tasks: bool = False
    can_manage_repo: bool = False
    can_manage_deploy: bool = False


class AgentProfileRead(BaseModel):
    key: str
    display_name: str
    summary: str
    instructions: str
    can_create_tasks: bool
    can_manage_repo: bool
    can_manage_deploy: bool


agents_router = APIRouter(prefix="/api/agents", tags=["agents"])


@agents_router.get("", response_model=list[AgentProfileRead])
def list_agents() -> list[AgentProfileRead]:
    from dataclasses import asdict
    return [AgentProfileRead(**asdict(p)) for p in list_all_profiles()]


@agents_router.post("", response_model=AgentProfileRead)
def create_agent(payload: AgentCreateRequest) -> AgentProfileRead:
    from dataclasses import asdict
    profile = register_agent(
        key=payload.key,
        display_name=payload.display_name,
        summary=payload.summary,
        instructions=payload.instructions,
        can_create_tasks=payload.can_create_tasks,
        can_manage_repo=payload.can_manage_repo,
        can_manage_deploy=payload.can_manage_deploy,
    )
    return AgentProfileRead(**asdict(profile))


# --- Task manual creation ---

@router.post("/{conversation_id}/tasks", response_model=TaskRead)
def create_task_manually(
    conversation_id: str,
    payload: TaskCreate,
    tasks: TaskService = Depends(get_task_service),
    service: ConversationService = Depends(get_conversation_service),
) -> TaskRead:
    conversation = service.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    task = tasks.create_simple_task(
        conversation_id=conversation_id,
        project_id=conversation.project_id,
        title=payload.title,
        goal=payload.goal,
        assigned_agent_key=payload.assigned_agent_key,
    )
    service.db.commit()
    return TaskRead.model_validate(task)
