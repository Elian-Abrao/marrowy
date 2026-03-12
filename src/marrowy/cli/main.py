from __future__ import annotations

import asyncio
from typing import Optional

import typer
import uvicorn

from marrowy.api.app import create_app
from marrowy.core.logging import configure_logging
from marrowy.core.settings import get_settings
from marrowy.db.base import Base
from marrowy.db.session import SessionLocal
from marrowy.db.session import engine
from marrowy.integrations.whatsapp_relay import WhatsAppRelay
from marrowy.providers.codex_bridge import CodexBridgeProvider
from marrowy.providers.fake import FakeProvider
from marrowy.services.conversations import ConversationService
from marrowy.services.projects import ProjectService

app = typer.Typer(help="Marrowy CLI")


@app.command("serve")
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    configure_logging()
    uvicorn.run(create_app(), host=host, port=port)


@app.command("init-db")
def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    typer.echo("database initialized")


@app.command("seed")
def seed() -> None:
    db = SessionLocal()
    try:
        project = ProjectService(db).seed_default_project()
        db.commit()
        typer.echo(f"seeded project {project.slug} ({project.id})")
    finally:
        db.close()


@app.command("console")
def console(
    conversation_id: Optional[str] = typer.Option(None, "--conversation-id"),
    project_slug: Optional[str] = typer.Option("marrowy-demo", "--project"),
    user_name: str = typer.Option(get_settings().default_user_name, "--user-name"),
) -> None:
    asyncio.run(_console(conversation_id=conversation_id, project_slug=project_slug, user_name=user_name))


@app.command("whatsapp-relay")
def whatsapp_relay(
    auth_dir: str = typer.Option(".state/whatsapp", "--auth-dir"),
    project_slug: str | None = typer.Option(None, "--project"),
    group_subject: list[str] | None = typer.Option(None, "--group-subject"),
    group_chat_id: list[str] | None = typer.Option(None, "--group-chat-id"),
    include_from_me: bool = typer.Option(True, "--include-from-me/--exclude-from-me"),
    cwd: str | None = typer.Option(None, "--cwd"),
) -> None:
    asyncio.run(
        _whatsapp_relay(
            auth_dir=auth_dir,
            project_slug=project_slug,
            group_subject=group_subject or [],
            group_chat_id=group_chat_id or [],
            include_from_me=include_from_me,
            cwd=cwd,
        )
    )


async def _console(*, conversation_id: str | None, project_slug: str | None, user_name: str) -> None:
    configure_logging()
    db = SessionLocal()
    try:
        project_service = ProjectService(db)
        if conversation_id is None:
            project = next((item for item in project_service.list_projects() if item.slug == project_slug), None)
            if project is None:
                project = project_service.seed_default_project()
                db.commit()
            provider = _build_provider()
            service = ConversationService(db, provider)
            conversation = service.create_conversation(
                title="Terminal validation conversation",
                project_id=project.id,
                channel="terminal",
                user_name=user_name,
            )
            db.commit()
            conversation_id = conversation.id
        provider = _build_provider()
        service = ConversationService(db, provider)
        typer.echo(f"Conversation: {conversation_id}")
        typer.echo("Type /exit to leave. Use /approve <id> or /reject <id> for approvals.")
        while True:
            line = typer.prompt("you")
            if line.strip() == "/exit":
                break
            if line.startswith("/approve ") or line.startswith("/reject "):
                command, approval_id = line.split(maxsplit=1)
                decision = "approve" if command == "/approve" else "reject"
                approval = service.resolve_approval(approval_id, actor_name=user_name, decision=decision)
                db.commit()
                typer.echo(f"[approval] {approval.id} -> {approval.status}")
                continue
            messages = await service.handle_user_message(conversation_id, content=line, user_name=user_name)
            db.commit()
            for message in messages[1:]:
                typer.echo(f"{message.author_name}: {message.content}")
    finally:
        db.close()


def _build_provider():
    settings = get_settings()
    if settings.model_provider == "fake":
        return FakeProvider()
    return CodexBridgeProvider(
        base_url=settings.codex_bridge_url,
        approval_policy=settings.codex_approval_policy,
        sandbox=settings.codex_sandbox,
    )


async def _whatsapp_relay(
    *,
    auth_dir: str,
    project_slug: str | None,
    group_subject: list[str],
    group_chat_id: list[str],
    include_from_me: bool,
    cwd: str | None,
) -> None:
    configure_logging()
    db = SessionLocal()
    try:
        provider = _build_provider()
        project_service = ProjectService(db)
        project_id: str | None = None
        if project_slug:
            project = project_service.get_by_slug(project_slug)
            if project is None:
                raise typer.BadParameter(f"project {project_slug!r} not found")
            project_id = project.id
        relay = WhatsAppRelay(
            db=db,
            provider=provider,
            auth_dir=auth_dir,
            project_id=project_id,
            group_subjects=group_subject,
            group_chat_ids=group_chat_id,
            include_from_me=include_from_me,
            cwd=cwd,
        )
        await relay.run()
    finally:
        db.close()
