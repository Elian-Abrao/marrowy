from __future__ import annotations

import asyncio
from contextlib import suppress
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from marrowy.db.models import Conversation
from marrowy.db.models import ConversationMessage
from marrowy.db.session import SessionLocal
from marrowy.integrations.whatsapp import WhatsAppConversationAdapter
from marrowy.integrations.whatsapp import WhatsAppInboundMessage
from marrowy.providers.base import ModelProvider


def ensure_gateway_importable(explicit_src: str | None = None) -> None:
    if explicit_src:
        candidate = Path(explicit_src)
    else:
        env_value = os.environ.get("MARROWY_CODEX_CHAT_GATEWAY_SRC")
        candidate = Path(env_value) if env_value else Path("/dados/projetos/pessoal/open-source/codex-chat-gateway/src")
    if candidate.exists():
        sys.path.insert(0, str(candidate))


@dataclass(slots=True)
class WhatsAppRelay:
    db: Session
    provider: ModelProvider
    auth_dir: str | Path
    project_id: str | None = None
    group_subjects: list[str] | None = None
    group_chat_ids: list[str] | None = None
    include_from_me: bool = True
    cwd: str | Path | None = None

    async def run(self) -> None:
        ensure_gateway_importable()
        from codex_chat_gateway.channel_adapters.factory import create_builtin_adapter
        from codex_chat_gateway.models import OutboundMessage

        adapter = create_builtin_adapter(
            "whatsapp-baileys",
            auth_dir=self.auth_dir,
            cwd=self.cwd,
            include_from_me=self.include_from_me,
        )

        whatsapp_adapter = WhatsAppConversationAdapter(self.db, self.provider)
        sent_message_ids: set[str] = set()

        async def handle_message(message) -> None:
            if not message.is_group:
                return
            subject = message.metadata.get("groupSubject")
            if self.group_subjects and subject not in self.group_subjects:
                return
            if self.group_chat_ids and message.chat_id not in self.group_chat_ids:
                return
            payload = WhatsAppInboundMessage(
                group_key=message.chat_id,
                text=message.text or "",
                sender_name=message.metadata.get("senderName") or message.sender_id,
                project_id=self.project_id,
            )
            replies = await whatsapp_adapter.handle(payload)
            for reply in replies:
                sent_message_ids.add(reply.id)
                await adapter.send_message(OutboundMessage.from_inbound(message, text=reply.content))

        dispatch_task = asyncio.create_task(
            self._dispatch_loop(adapter=adapter, sent_message_ids=sent_message_ids),
            name="marrowy-whatsapp-dispatch",
        )
        try:
            await adapter.start(handle_message)
            await adapter.wait()
        finally:
            dispatch_task.cancel()
            with suppress(asyncio.CancelledError):
                await dispatch_task
            await adapter.close()

    async def _dispatch_loop(self, *, adapter, sent_message_ids: set[str]) -> None:
        from codex_chat_gateway.models import InboundMessage
        from codex_chat_gateway.models import OutboundMessage

        while True:
            await asyncio.sleep(0.4)
            db = SessionLocal()
            try:
                stmt = (
                    select(ConversationMessage, Conversation)
                    .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
                    .where(Conversation.channel == "whatsapp")
                    .order_by(ConversationMessage.created_at)
                )
                rows = db.execute(stmt).all()
                for message, conversation in rows:
                    if message.id in sent_message_ids:
                        continue
                    if message.author_kind == "user":
                        sent_message_ids.add(message.id)
                        continue
                    if self.project_id and conversation.project_id != self.project_id:
                        continue
                    if self.group_chat_ids and (conversation.external_ref or "") not in self.group_chat_ids:
                        continue
                    sent_message_ids.add(message.id)
                    inbound = InboundMessage(
                        message_id=message.id,
                        channel="whatsapp-baileys",
                        chat_id=conversation.external_ref or "",
                        sender_id="marrowy",
                        text="",
                        metadata={"groupSubject": conversation.title},
                        is_group=True,
                    )
                    await adapter.send_message(OutboundMessage.from_inbound(inbound, text=message.content))
            finally:
                db.close()
