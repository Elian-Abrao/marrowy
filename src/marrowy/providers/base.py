from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(slots=True)
class ProviderResult:
    text: str
    commentary: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    final_event: dict | None = None


class ModelProvider(Protocol):
    async def complete(
        self,
        *,
        role_name: str,
        instructions: str,
        prompt: str,
        thread_id: str | None = None,
        cwd: str | None = None,
    ) -> tuple[ProviderResult, str | None]: ...
