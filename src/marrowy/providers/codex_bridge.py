from __future__ import annotations

from dataclasses import dataclass

import httpx

from marrowy.providers.base import ProviderResult


@dataclass(slots=True)
class CodexBridgeProvider:
    base_url: str
    approval_policy: str | None = None
    sandbox: str | None = None
    timeout: float = 180.0

    async def complete(
        self,
        *,
        role_name: str,
        instructions: str,
        prompt: str,
        thread_id: str | None = None,
        cwd: str | None = None,
    ) -> tuple[ProviderResult, str | None]:
        payload: dict[str, object] = {
            "prompt": self._build_prompt(role_name=role_name, instructions=instructions, prompt=prompt),
        }
        if thread_id:
            payload["threadId"] = thread_id
        if self.approval_policy:
            payload["approvalPolicy"] = self.approval_policy
        if self.sandbox:
            payload["sandbox"] = self.sandbox
        if cwd:
            payload["cwd"] = cwd

        commentary: list[str] = []
        actions: list[str] = []
        final_text = ""
        final_event: dict | None = None
        current_event: str | None = None
        thread_value: str | None = thread_id
        async with httpx.AsyncClient(base_url=self.base_url.rstrip("/"), timeout=self.timeout) as client:
            async with client.stream("POST", "/v1/chat/consumer-stream", json=payload) as response:
                response.raise_for_status()
                data_lines: list[str] = []
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        current_event = line[7:]
                        continue
                    if line.startswith("data: "):
                        data_lines.append(line[6:])
                        continue
                    if line:
                        continue
                    if not data_lines:
                        current_event = None
                        continue
                    event = httpx.Response(200, content="\n".join(data_lines)).json()
                    event_type = event.get("event") or current_event
                    if event_type == "commentary" and isinstance(event.get("text"), str):
                        commentary.append(event["text"])
                    elif event_type == "action" and isinstance(event.get("text"), str):
                        actions.append(event["text"])
                    elif event_type == "final":
                        final_event = event
                        if isinstance(event.get("text"), str):
                            final_text = event["text"]
                        if isinstance(event.get("threadId"), str):
                            thread_value = event["threadId"]
                    elif event_type == "error":
                        message = event.get("message") or "consumer stream error"
                        raise RuntimeError(str(message))
                    data_lines = []
                    current_event = None
                if data_lines:
                    event = httpx.Response(200, content="\n".join(data_lines)).json()
                    if event.get("event") == "final" and isinstance(event.get("text"), str):
                        final_text = event["text"]
                        final_event = event
                        if isinstance(event.get("threadId"), str):
                            thread_value = event["threadId"]
        return ProviderResult(text=final_text, commentary=commentary, actions=actions, final_event=final_event), thread_value

    @staticmethod
    def _build_prompt(*, role_name: str, instructions: str, prompt: str) -> str:
        return (
            f"You are {role_name} inside Marrowy, a multi-agent orchestration system.\n"
            f"Role instructions:\n{instructions}\n\n"
            "Respond in plain, human-readable chat. If you refer to tasks, mention task ids when available. "
            "Do not invent tool execution you did not perform.\n\n"
            f"User or orchestration prompt:\n{prompt}"
        )
