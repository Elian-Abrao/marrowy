from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from marrowy.api.routers import channels
from marrowy.api.routers import conversations
from marrowy.api.routers import health
from marrowy.api.routers import projects
from marrowy.api.routers import ui
from marrowy.core.logging import configure_logging
from marrowy.core.settings import get_settings


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(title=settings.ui_title)
    app.include_router(health.router)
    app.include_router(channels.router)
    app.include_router(projects.router)
    app.include_router(conversations.router)
    app.include_router(ui.router)
    static_dir = settings.base_dir / "src" / "marrowy" / "api" / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app


app = create_app()
