from __future__ import annotations

from dataclasses import dataclass
import asyncio

import httpx

from marrowy.providers.base import ProviderResult


@dataclass(slots=True)
class CodexBridgeProvider:
    base_url: str
    approval_policy: str | None = None
    sandbox: str | None = None
    timeout: float | None = None

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
        prompt_text = self._build_prompt(role_name=role_name, instructions=instructions, prompt=prompt)
        try:
            return await self._run_consumer_stream(
                prompt_text=prompt_text,
                thread_id=thread_id,
                cwd=cwd,
                event_handler=event_handler,
            )
        except RuntimeError as exc:
            if thread_id and self._is_missing_thread_error(str(exc)):
                if event_handler is not None:
                    maybe = event_handler(
                        "status",
                        "The previous Codex thread was not available anymore. Rebuilding the agent context in a fresh thread.",
                    )
                    if asyncio.iscoroutine(maybe):
                        await maybe
                return await self._run_consumer_stream(
                    prompt_text=prompt_text,
                    thread_id=None,
                    cwd=cwd,
                    event_handler=event_handler,
                )
            raise

    async def _run_consumer_stream(
        self,
        *,
        prompt_text: str,
        thread_id: str | None,
        cwd: str | None,
        event_handler=None,
    ) -> tuple[ProviderResult, str | None]:
        payload: dict[str, object] = {
            "prompt": prompt_text,
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
        try:
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
                            if event_handler is not None:
                                maybe = event_handler("commentary", event["text"])
                                if asyncio.iscoroutine(maybe):
                                    await maybe
                        elif event_type == "action" and isinstance(event.get("text"), str):
                            actions.append(event["text"])
                            if event_handler is not None:
                                maybe = event_handler("action", event["text"])
                                if asyncio.iscoroutine(maybe):
                                    await maybe
                        elif event_type == "status" and isinstance(event.get("text"), str):
                            if event_handler is not None:
                                maybe = event_handler("status", event["text"])
                                if asyncio.iscoroutine(maybe):
                                    await maybe
                        elif event_type == "final":
                            final_event = event
                            if isinstance(event.get("text"), str):
                                final_text = event["text"]
                            if isinstance(event.get("threadId"), str):
                                thread_value = event["threadId"]
                            if event_handler is not None and final_text:
                                maybe = event_handler("final", final_text)
                                if asyncio.iscoroutine(maybe):
                                    await maybe
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
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                "The Codex bridge timed out while waiting for a response. The runtime may still be busy; ask for room status or try again."
            ) from exc
        except httpx.HTTPStatusError as exc:
            body = (exc.response.text or "").strip()
            detail = f" {body}" if body else ""
            raise RuntimeError(f"The Codex bridge returned HTTP {exc.response.status_code}.{detail}") from exc
        except httpx.HTTPError as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            raise RuntimeError(f"The Codex bridge request failed: {detail}") from exc
        if final_event is None:
            raise RuntimeError(
                "The Codex bridge closed the consumer stream without a final response. The runtime may still be busy."
            )
        return ProviderResult(text=final_text, commentary=commentary, actions=actions, final_event=final_event), thread_value

    @staticmethod
    def _is_missing_thread_error(message: str) -> bool:
        lowered = message.lower()
        return "thread not found" in lowered or "turn/start failed" in lowered and "thread" in lowered

    @staticmethod
    def _build_prompt(*, role_name: str, instructions: str, prompt: str) -> str:
        return (
            f"You are {role_name} inside Marrowy, a multi-agent orchestration system.\n"
            f"Role instructions:\n{instructions}\n\n"
            "Respond in plain, human-readable chat. If you refer to tasks, mention task ids when available. "
            "Do not invent tool execution you did not perform.\n\n"
            f"User or orchestration prompt:\n{prompt}"
        )
