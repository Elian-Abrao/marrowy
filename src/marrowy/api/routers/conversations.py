from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sse_starlette.sse import EventSourceResponse

from marrowy.api.deps import get_conversation_service
from marrowy.api.deps import get_task_service
from marrowy.api.deps import get_db
from marrowy.db.models import DomainEvent
from marrowy.schemas.approvals import ApprovalRead
from marrowy.schemas.approvals import ApprovalResolve
from marrowy.schemas.conversations import AddAgentRequest
from marrowy.schemas.conversations import ConversationCreate
from marrowy.schemas.conversations import ConversationRead
from marrowy.schemas.conversations import MessageCreate
from marrowy.schemas.conversations import MessageRead
from marrowy.schemas.conversations import ParticipantRead
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


@router.get("/{conversation_id}/messages", response_model=list[MessageRead])
def list_messages(conversation_id: str, service: ConversationService = Depends(get_conversation_service)) -> list[MessageRead]:
    return [MessageRead.model_validate(item) for item in service.list_messages(conversation_id)]


@router.get("/{conversation_id}/participants", response_model=list[ParticipantRead])
def list_participants(conversation_id: str, service: ConversationService = Depends(get_conversation_service)) -> list[ParticipantRead]:
    return [ParticipantRead.model_validate(item) for item in service.list_participants(conversation_id)]


@router.get("/{conversation_id}/tasks", response_model=list[TaskRead])
def list_tasks(conversation_id: str, tasks: TaskService = Depends(get_task_service)) -> list[TaskRead]:
    return [TaskRead.model_validate(item) for item in tasks.list_for_conversation(conversation_id)]


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
        last_seen: str | None = None
        while True:
            stmt = select(DomainEvent).where(DomainEvent.conversation_id == conversation_id).order_by(DomainEvent.created_at)
            rows = list(db.scalars(stmt))
            for event in rows:
                if last_seen is not None and event.id <= last_seen:
                    continue
                last_seen = event.id
                payload = {
                    "id": event.id,
                    "eventType": event.event_type,
                    "payload": event.payload_json,
                    "createdAt": event.created_at.isoformat(),
                }
                yield {"event": event.event_type, "data": json.dumps(payload)}
            await asyncio.sleep(1.0)

    return EventSourceResponse(event_source())
