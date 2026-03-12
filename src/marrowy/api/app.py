from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from marrowy.api.deps import build_provider
from marrowy.api.routers import channels
from marrowy.api.routers import conversations
from marrowy.api.routers import health
from marrowy.api.routers import projects
from marrowy.api.routers import ui
from marrowy.core.logging import configure_logging
from marrowy.core.settings import get_settings
from marrowy.db.session import SessionLocal
from marrowy.services.job_runner import JobRunner


def create_app(*, start_job_runner: bool = True) -> FastAPI:
    configure_logging()
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runner = None
        if start_job_runner:
            runner = JobRunner(
                session_factory=SessionLocal,
                provider_factory=lambda: build_provider(settings),
                poll_interval=0.4,
            )
            await runner.start()
            app.state.job_runner = runner
        try:
            yield
        finally:
            if runner is not None:
                await runner.stop()

    app = FastAPI(title=settings.ui_title, lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(channels.router)
    app.include_router(projects.router)
    app.include_router(conversations.router)
    app.include_router(ui.router)
    static_dir = settings.base_dir / "src" / "marrowy" / "api" / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app


app = create_app()
