from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Optional

import typer
import uvicorn

from marrowy.api.deps import build_provider
from marrowy.api.app import create_app
from marrowy.core.logging import configure_logging
from marrowy.core.settings import get_settings
from marrowy.devtools import BridgeProcess
from marrowy.devtools import bridge_ready
from marrowy.devtools import ensure_env_file
from marrowy.devtools import ensure_postgres_container
from marrowy.devtools import run_migrations
from marrowy.devtools import seed_default_project
from marrowy.devtools import start_local_bridge
from marrowy.devtools import wait_for_bridge
from marrowy.devtools import wait_for_database
from marrowy.db.base import Base
from marrowy.db.models import ConversationMessage
from marrowy.db.models import DomainEvent
from marrowy.db.session import SessionLocal
from marrowy.db.session import engine
from marrowy.integrations.whatsapp_relay import WhatsAppRelay
from marrowy.providers.codex_bridge import CodexBridgeProvider
from marrowy.providers.fake import FakeProvider
from marrowy.services.conversations import ConversationService
from marrowy.services.job_runner import JobRunner
from marrowy.services.projects import ProjectService

app = typer.Typer(help="Marrowy CLI")


@app.command("serve")
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    configure_logging()
    uvicorn.run(create_app(), host=host, port=port)


@app.command("doctor")
def doctor() -> None:
    settings = get_settings()
    env_created = ensure_env_file(settings.base_dir)
    typer.echo(f".env: {'created from .env.example' if env_created else 'ok'}")
    if settings.is_sqlite:
        typer.echo(f"database: sqlite ({settings.database_url})")
    else:
        db_ok = True
        db_error = ""
        try:
            wait_for_database(settings.database_url, timeout_seconds=3.0)
        except Exception as exc:
            db_ok = False
            db_error = str(exc)
        typer.echo(f"database: {'ok' if db_ok else f'not ready ({db_error})'}")
    bridge_ok = bridge_ready(settings.codex_bridge_url)
    typer.echo(f"bridge: {'ok' if bridge_ok else f'not ready at {settings.codex_bridge_url}'}")
    if not bridge_ok:
        typer.echo(
            "hint: run `marrowy dev-web` / `marrowy dev-console` to auto-start local dependencies, "
            "or start codex-runtime-bridge manually."
        )


@app.command("dev-web")
def dev_web(
    host: str = "127.0.0.1",
    port: int = 8000,
    start_bridge: bool = typer.Option(True, "--start-bridge/--no-start-bridge"),
) -> None:
    configure_logging()
    bridge_process = _prepare_dev_environment(start_bridge=start_bridge)
    try:
        typer.echo(f"Marrowy web ready on http://{host}:{port}")
        uvicorn.run(create_app(), host=host, port=port)
    finally:
        _stop_bridge_process(bridge_process)


@app.command("dev-console")
def dev_console(
    conversation_id: Optional[str] = typer.Option(None, "--conversation-id"),
    project_slug: Optional[str] = typer.Option("marrowy-demo", "--project"),
    user_name: str = typer.Option(get_settings().default_user_name, "--user-name"),
    start_bridge: bool = typer.Option(True, "--start-bridge/--no-start-bridge"),
) -> None:
    configure_logging()
    bridge_process = _prepare_dev_environment(start_bridge=start_bridge)
    try:
        asyncio.run(_console(conversation_id=conversation_id, project_slug=project_slug, user_name=user_name))
    finally:
        _stop_bridge_process(bridge_process)


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
    settings = get_settings()
    runner = JobRunner(
        session_factory=SessionLocal,
        provider_factory=lambda: build_provider(settings),
        poll_interval=0.3,
    )
    await runner.start()
    db = SessionLocal()
    poller_task: asyncio.Task | None = None
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
        poller_task = asyncio.create_task(_console_poller(conversation_id))
        while True:
            line = await asyncio.to_thread(typer.prompt, "you")
            if line.strip() == "/exit":
                break
            if line.startswith("/approve ") or line.startswith("/reject "):
                command, approval_id = line.split(maxsplit=1)
                decision = "approve" if command == "/approve" else "reject"
                approval = service.resolve_approval(approval_id, actor_name=user_name, decision=decision)
                db.commit()
                typer.echo(f"[approval] {approval.id} -> {approval.status}")
                continue
            await service.handle_user_message(conversation_id, content=line, user_name=user_name)
            db.commit()
    finally:
        if poller_task is not None:
            poller_task.cancel()
            with suppress(asyncio.CancelledError):
                await poller_task
        await runner.stop()
        db.close()


def _build_provider():
    settings = get_settings()
    if settings.model_provider == "fake":
        return FakeProvider()
    return CodexBridgeProvider(
        base_url=settings.codex_bridge_url,
        approval_policy=settings.codex_approval_policy,
        sandbox=settings.codex_sandbox,
        timeout=settings.codex_timeout_seconds,
    )


def _prepare_dev_environment(*, start_bridge: bool) -> BridgeProcess | None:
    settings = get_settings()
    created_env = ensure_env_file(settings.base_dir)
    if created_env:
        typer.echo("Created .env from .env.example")
    if not settings.is_sqlite:
        typer.echo("Starting PostgreSQL container...")
        ensure_postgres_container(settings.base_dir)
        typer.echo("Waiting for database...")
        wait_for_database(settings.database_url)
    typer.echo("Applying migrations...")
    run_migrations(settings.base_dir)
    seeded_project = seed_default_project()
    typer.echo(f"Seeded default project: {seeded_project}")

    bridge_process: BridgeProcess | None = None
    if settings.model_provider == "codex":
        if bridge_ready(settings.codex_bridge_url):
            typer.echo(f"Codex bridge already ready at {settings.codex_bridge_url}")
        elif start_bridge:
            typer.echo("Starting local codex-runtime-bridge...")
            bridge_process = start_local_bridge(settings)
            wait_for_bridge(settings.codex_bridge_url)
            typer.echo(
                f"Codex bridge started at {settings.codex_bridge_url} "
                f"(pid={bridge_process.process.pid}, log={bridge_process.log_path})"
            )
        else:
            raise typer.BadParameter(
                f"Codex bridge is not ready at {settings.codex_bridge_url}. "
                "Start it manually or use --start-bridge."
            )
    return bridge_process


def _stop_bridge_process(bridge_process: BridgeProcess | None) -> None:
    if bridge_process is None:
        return
    typer.echo(f"Stopping local codex-runtime-bridge (pid={bridge_process.process.pid})")
    bridge_process.stop()


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
    settings = get_settings()
    runner = JobRunner(
        session_factory=SessionLocal,
        provider_factory=lambda: build_provider(settings),
        poll_interval=0.3,
    )
    await runner.start()
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
        await runner.stop()
        db.close()


async def _console_poller(conversation_id: str) -> None:
    db = SessionLocal()
    try:
        last_message_count = db.query(DomainEvent).count()
        last_chat_count = db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation_id).count()
    finally:
        db.close()
    while True:
        await asyncio.sleep(0.3)
        db = SessionLocal()
        try:
            messages = (
                db.query(ConversationMessage)
                .filter(ConversationMessage.conversation_id == conversation_id)
                .order_by(ConversationMessage.created_at)
                .all()
            )
            if len(messages) > last_chat_count:
                for message in messages[last_chat_count:]:
                    if message.author_kind == "user":
                        continue
                    typer.echo(f"{message.author_name}: {message.content}")
                last_chat_count = len(messages)
            events = list(
                db.query(DomainEvent)
                .filter(DomainEvent.conversation_id == conversation_id)
                .order_by(DomainEvent.created_at)
            )
            new_events = events[last_message_count:]
            for event in new_events:
                if event.event_type.startswith("job.") and event.event_type not in {"job.completed"}:
                    summary = event.payload_json.get("summary") or event.payload_json.get("text")
                    if summary:
                        typer.echo(f"[{event.event_type}] {summary}")
                if event.event_type == "participant.activity.updated":
                    summary = event.payload_json.get("activitySummary")
                    display = event.payload_json.get("displayName")
                    if display and summary:
                        typer.echo(f"[activity] {display}: {summary}")
            last_message_count = len(events)
        finally:
            db.close()
