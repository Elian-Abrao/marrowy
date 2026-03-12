from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from marrowy.providers.base import ModelProvider
from marrowy.services.conversations import ConversationService


@dataclass(slots=True)
class WhatsAppInboundMessage:
    group_key: str
    text: str
    sender_name: str
    project_id: str | None = None


class WhatsAppConversationAdapter:
    """Adapter entrypoint intended to be called by a relay built on top of codex-chat-gateway."""

    def __init__(self, db: Session, provider: ModelProvider) -> None:
        self.service = ConversationService(db, provider)
        self.db = db

    async def handle(self, payload: WhatsAppInboundMessage) -> list[str]:
        conversation = next(
            (
                item
                for item in self.service.list_conversations()
                if item.channel == "whatsapp" and item.external_ref == payload.group_key
            ),
            None,
        )
        if conversation is None:
            conversation = self.service.create_conversation(
                title=f"WhatsApp {payload.group_key}",
                project_id=payload.project_id,
                channel="whatsapp",
                external_ref=payload.group_key,
                user_name=payload.sender_name,
            )
            self.db.commit()
        messages = await self.service.handle_user_message(conversation.id, content=payload.text, user_name=payload.sender_name)
        self.db.commit()
        return [message.content for message in messages[1:]]
