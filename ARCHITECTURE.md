# Architecture

Marrowy separates:

- chat as human-visible coordination
- tasks as execution state
- memory as continuity
- agents as logical roles
- the Codex runtime as cognition

## Layers

```text
Channels
  -> Marrowy entrypoints
  -> Conversation service
  -> Policy / task / memory services
  -> Provider adapter
  -> codex-runtime-bridge
  -> codex app-server
```

## Database

Primary database: PostgreSQL.

Main persisted entities:

- projects
- project repositories
- project environments
- pipeline templates
- conversations
- conversation participants
- conversation messages
- tasks
- approval requests
- domain events
- memory entries

## Multi-Agent Strategy

V1 treats agents as logical profiles inside a shared runtime integration:

- Agent Principal
- Agent Specialist
- Agent QA
- Agent GitHub
- Agent DevOps
- Agent PO/PM

Each participant keeps an optional bridge thread id so agent memory can diverge over time while still sharing a visible conversation.

## UI

The browser UI is server-rendered with Jinja templates and uses SSE to refresh:

- chat messages
- task cards
- approvals
- participants

## WhatsApp

Marrowy exposes a `WhatsAppConversationAdapter` that can be called by a relay process built on top of the existing `codex-chat-gateway`.

That keeps channel transport ownership outside Marrowy while allowing WhatsApp to become a first-class conversation channel.

## Tradeoffs

- V1 uses deterministic orchestration plus Codex-backed agent responses instead of a full structured planner.
- V1 keeps events persisted but does not implement full replay.
- V1 uses SQLite in tests even though PostgreSQL is the primary runtime database.
