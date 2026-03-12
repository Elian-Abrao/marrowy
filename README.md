# Marrowy

Marrowy is a multi-agent conversational orchestration system built in Python.

It sits above the existing `codex-runtime-bridge` and `codex-chat-gateway`:

- `codex-runtime-bridge` exposes the official `codex app-server`
- `codex-chat-gateway` exposes chat channels such as WhatsApp
- `marrowy` orchestrates conversations, agents, tasks, approvals, policies, and project context

## MVP Scope

- shared conversations with multiple visible agents
- Agent Principal as coordinator
- project-aware task creation and task pipelines
- approvals in chat
- browser UI with chat, participants, approvals, and task cards
- terminal console
- Codex runtime integration through the existing bridge
- WhatsApp integration entry path compatible with the existing gateway architecture

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
docker compose up -d postgres
alembic upgrade head
marrowy seed
marrowy serve
```

Open `http://127.0.0.1:8000`.

## Terminal Console

```bash
marrowy console --project marrowy-demo
```

## Core Flow

```text
Browser / Terminal / WhatsApp relay
  -> Marrowy API / CLI
  -> Conversation Service
  -> Agent Orchestrator
  -> Codex bridge provider
  -> codex-runtime-bridge
  -> official codex app-server
```

## Development

```bash
scripts/bootstrap.sh
scripts/dev_up.sh
scripts/test.sh
```
