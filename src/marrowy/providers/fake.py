from __future__ import annotations

from collections import defaultdict

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
    ) -> tuple[ProviderResult, str | None]:
        self._counters[role_name] += 1
        short_prompt = prompt.strip().splitlines()[-1]
        text = f"[{role_name}] {short_prompt[:180]}"
        return ProviderResult(text=text), thread_id or f"fake-{role_name}"
