from __future__ import annotations

from collections import defaultdict
import asyncio

from marrowy.providers.base import ProviderResult


class FakeProvider:
    def __init__(self) -> None:
        self._counters = defaultdict(int)

    async def complete(
        self,
        *,
        role_name: str,
        instructions: str,
        prompt: str,
        thread_id: str | None = None,
        cwd: str | None = None,
        event_handler=None,
    ) -> tuple[ProviderResult, str | None]:
        self._counters[role_name] += 1
        short_prompt = prompt.strip().splitlines()[-1]
        if event_handler is not None:
            maybe = event_handler("commentary", f"{role_name} is reviewing the request.")
            if asyncio.iscoroutine(maybe):
                await maybe
            maybe = event_handler("action", f"{role_name} is preparing the next update.")
            if asyncio.iscoroutine(maybe):
                await maybe
        text = f"[{role_name}] {short_prompt[:180]}"
        return ProviderResult(text=text), thread_id or f"fake-{role_name}"
