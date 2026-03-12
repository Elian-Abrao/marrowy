from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel

from marrowy.api.deps import get_db
from marrowy.api.deps import get_provider
from marrowy.db.models import Project
from marrowy.integrations.whatsapp import WhatsAppConversationAdapter
from marrowy.integrations.whatsapp import WhatsAppInboundMessage
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/channels", tags=["channels"])


class WhatsAppInboundRequest(BaseModel):
    group_key: str
    text: str
    sender_name: str
    project_slug: str | None = None


@router.post("/whatsapp/inbound")
async def whatsapp_inbound(
    payload: WhatsAppInboundRequest,
    db: Session = Depends(get_db),
    provider=Depends(get_provider),
) -> dict[str, list[str]]:
    project_id: str | None = None
    if payload.project_slug:
        project = db.scalar(select(Project).where(Project.slug == payload.project_slug))
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        project_id = project.id
    adapter = WhatsAppConversationAdapter(db, provider)
    replies = await adapter.handle(
        WhatsAppInboundMessage(
            group_key=payload.group_key,
            text=payload.text,
            sender_name=payload.sender_name,
            project_id=project_id,
        )
    )
    return {"replies": replies}
