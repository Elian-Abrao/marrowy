from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

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

        async def handle_message(message) -> None:
            if not message.is_group:
                return
            subject = message.metadata.get("groupSubject")
            if self.group_subjects and subject not in self.group_subjects:
                return
            if self.group_chat_ids and message.chat_id not in self.group_chat_ids:
                return
            replies = await whatsapp_adapter.handle(
                WhatsAppInboundMessage(
                    group_key=message.chat_id,
                    text=message.text or "",
                    sender_name=message.metadata.get("senderName") or message.sender_id,
                    project_id=self.project_id,
                )
            )
            for reply in replies:
                await adapter.send_message(OutboundMessage.from_inbound(message, text=reply))

        try:
            await adapter.start(handle_message)
            await adapter.wait()
        finally:
            await adapter.close()
