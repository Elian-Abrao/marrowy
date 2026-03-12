from __future__ import annotations

import httpx
import pytest

from marrowy.providers.codex_bridge import CodexBridgeProvider


@pytest.mark.asyncio
async def test_codex_bridge_provider_translates_timeout_into_useful_error(monkeypatch):
    class FakeStreamContext:
        async def __aenter__(self):
            raise httpx.ReadTimeout("timed out")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, *args, **kwargs):
            return FakeStreamContext()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    provider = CodexBridgeProvider(base_url="http://127.0.0.1:8787", timeout=0.1)

    with pytest.raises(RuntimeError) as excinfo:
        await provider.complete(
            role_name="Agent Principal",
            instructions="Keep the chat short.",
            prompt="hello",
        )

    assert "timed out" in str(excinfo.value).lower()
    assert "room status" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_codex_bridge_provider_retries_without_stale_thread(monkeypatch):
    events = [
        [
            "event: error",
            "data: {\"event\":\"error\",\"message\":\"turn/start failed (-32600): thread not found: stale-thread\"}",
            "",
        ],
        [
            "event: final",
            "data: {\"event\":\"final\",\"text\":\"Recovered reply\",\"threadId\":\"fresh-thread\"}",
            "",
        ],
    ]
    thread_ids: list[str | None] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            for line in events.pop(0):
                yield line

    class FakeStreamContext:
        def __init__(self, thread_id):
            self.thread_id = thread_id

        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, json):
            thread_ids.append(json.get("threadId"))
            return FakeStreamContext(json.get("threadId"))

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    provider = CodexBridgeProvider(base_url="http://127.0.0.1:8787", timeout=0.1)
    seen_events: list[tuple[str, str]] = []

    async def on_event(kind: str, text: str):
        seen_events.append((kind, text))

    result, thread_id = await provider.complete(
        role_name="Agent Principal",
        instructions="Keep the chat short.",
        prompt="hello",
        thread_id="stale-thread",
        event_handler=on_event,
    )

    assert thread_ids == ["stale-thread", None]
    assert thread_id == "fresh-thread"
    assert result.text == "Recovered reply"
    assert any("fresh thread" in text.lower() for kind, text in seen_events if kind == "status")
