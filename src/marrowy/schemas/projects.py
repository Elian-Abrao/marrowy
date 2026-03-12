from __future__ import annotations

from pydantic import BaseModel

from .common import ORMModel


class ProjectCreate(BaseModel):
    slug: str
    name: str
    description: str | None = None
    context_markdown: str | None = None


class ProjectRead(ORMModel):
    id: str
    slug: str
    name: str
    description: str | None = None
    context_markdown: str | None = None
