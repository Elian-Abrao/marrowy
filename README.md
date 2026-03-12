# Marrowy

Marrowy is a multi-agent conversational orchestration system built in Python.

It sits on top of the two adapter repositories that already exist locally:

- `codex-runtime-bridge`: exposes the official `codex app-server` through HTTP, CLI, and Python SDK
- `codex-chat-gateway`: owns chat transport concerns such as WhatsApp/Baileys
- `marrowy`: owns conversations, agent roles, tasks, approvals, memory, project context, and user-facing orchestration

## What The MVP Delivers

- shared conversations with multiple visible agents
- `Agent Principal` as the default coordinator
- explicit distinction between conversational agents and execution workers
- logical specialist roles:
  - `Agent Specialist`
  - `Agent QA`
  - `Agent GitHub`
  - `Agent DevOps`
  - `Agent PO/PM`
- project-aware task creation and pipeline stages
- formal subtasks for PO/PM-driven decomposition
- asynchronous execution jobs with background runner
- chat-visible approvals
- browser UI with:
  - chat view
  - participants
  - participant activity state
  - active jobs
  - pending approvals
  - task board/cards
- terminal console interaction
- WhatsApp relay entry path compatible with the existing `codex-chat-gateway`
- real Codex runtime integration through `codex-runtime-bridge`

## Runtime / Provider Flow

The main provider path is real, not mocked:

```text
Marrowy Agent Core
  -> Codex bridge provider
  -> codex-runtime-bridge
  -> official codex app-server
```

Tests use a fake provider only where deterministic automation is useful.
Manual validation and smoke tests use the real bridge/runtime path.

## Agent vs Worker

Marrowy now treats these as different concepts:

- agents are visible conversational roles
- workers are background execution units

### Agents

Agents speak in the room, explain decisions, request approvals, and summarize work:

- Agent Principal
- Agent Specialist
- Agent QA
- Agent GitHub
- Agent DevOps
- Agent PO/PM

### Workers

Workers claim background jobs, execute provider turns, emit progress, and update tasks without blocking the chat.

Initial worker keys:

- `summary`
- `specialist`
- `qa`
- `github`
- `devops`
- `planning`

This keeps the room responsive while execution is still happening in the background.

## Project / Conversation / Task Model

### Projects

Projects are independent from conversations and store:

- structured metadata
- repository references
- environments
- pipeline templates
- freeform project context

### Conversations

Conversations are shared rooms where the user and multiple agents can speak.
The default participant set starts with:

- the user
- `Agent Principal`

Specialized agents are added later by chat request.

### Tasks

Tasks are the execution unit. Marrowy supports:

- simple tasks
- pipeline parent tasks
- stage tasks for delivery flow
- formal subtasks

Statuses:

- `created`
- `planned`
- `in_progress`
- `blocked`
- `waiting_approval`
- `testing`
- `deploying`
- `done`
- `failed`
- `cancelled`

### Jobs

Jobs are the first explicit worker-execution entity in the system.

Each job may reference:

- conversation
- task or subtask
- participant/agent role
- source message
- worker key
- idempotency key

Job statuses:

- `queued`
- `claimed`
- `running`
- `waiting`
- `succeeded`
- `failed`

Jobs are claimed by the background runner and surface progress to:

- terminal console
- browser UI
- WhatsApp relay

### Approvals

Approvals are persisted and surfaced in:

- chat
- API
- browser UI

Current MVP examples:

- production deployment approval
- policy-aware task blocking

## Quick Start

### 1. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

### 2. Start PostgreSQL

```bash
docker compose up -d postgres
```

### 3. Run migrations and seed data

```bash
alembic upgrade head
marrowy seed
```

### 4. Start the Codex bridge

This project expects the existing `codex-runtime-bridge` to be available.

Example:

```bash
cd /home/elian/projetos/pessoal/open-source/codex-runtime-bridge
source .venv/bin/activate
env PYTHONPATH=src python -m codex_runtime_bridge serve --port 8787
```

### 5. Start Marrowy

```bash
cd /home/elian/projetos/pessoal/open-source/marrowy
source .venv/bin/activate
marrowy serve
```

Open `http://127.0.0.1:8000`.

## Browser UI

The browser UI includes:

- project list
- conversation list
- conversation creation form
- live chat area
- participant sidebar
- participant activity state and summary
- active jobs list
- pending approvals
- task board grouped by status

The UI refreshes through SSE and now exposes:

- immediate Agent Principal ACK
- worker progress
- blocked / waiting visibility
- approval buttons while work is still pending

## Terminal Console

```bash
marrowy console --project marrowy-demo --user-name Elian
```

Useful approval commands inside the console:

```text
/approve <approval-id>
/reject <approval-id>
/exit
```

The console also shows:

- immediate Agent Principal ACK
- job queued / started events
- participant activity updates
- background agent messages while the prompt stays interactive

## WhatsApp Relay

Marrowy does not own the low-level WhatsApp socket. It reuses the existing gateway path.

The relay command reuses the adapter/worker from `codex-chat-gateway` and forwards group messages into Marrowy:

```bash
marrowy whatsapp-relay \
  --project marrowy-demo \
  --auth-dir /dados/projetos/pessoal/open-source/codex-chat-gateway/.state/whatsapp \
  --group-subject Codex
```

Environment variable:

- `MARROWY_CODEX_CHAT_GATEWAY_SRC`
  Path to the `codex-chat-gateway/src` directory if it is not in the default local location.

The relay now forwards:

- immediate ACK messages
- background worker completions
- approval-driven follow-up messages

without requiring the WhatsApp channel to block on the whole provider turn.

## Environment Variables

See `.env.example`.

Most important:

- `MARROWY_DATABASE_URL`
- `MARROWY_CODEX_BRIDGE_URL`
- `MARROWY_MODEL_PROVIDER`
- `MARROWY_CODEX_APPROVAL_POLICY`
- `MARROWY_CODEX_SANDBOX`

## Tests

### Unit + API + CLI + browser E2E

```bash
pytest
```

### Browser E2E only

```bash
scripts/browser_e2e.sh
```

The suite covers:

- task / approval / onboarding idempotency
- worker claim and background execution
- responsiveness under long-running jobs
- browser rendering of activity and active jobs
- duplicate prevention for approvals, jobs, onboarding, and decomposition

## Bootstrap Scripts

- `scripts/bootstrap.sh`
- `scripts/migrate.sh`
- `scripts/seed.sh`
- `scripts/serve.sh`
- `scripts/dev_up.sh`
- `scripts/test.sh`
- `scripts/browser_e2e.sh`

## Validation Evidence

See [docs/VALIDATION.md](docs/VALIDATION.md) for the real validation pass, including:

- terminal conversation with a real 20-message responsiveness battery
- browser UI inspection of active jobs, participant activity, approvals, and task state
- real Codex bridge/provider smoke validation

## Responsiveness Strategy

This cycle focused on reducing silent waiting time.

Current strategy:

1. persist the user message immediately
2. emit an immediate Agent Principal ACK
3. create explicit worker jobs
4. surface queued/running/waiting state through participant activity
5. stream progress and final results back into the conversation

This means the user sees visible progress even when the real Codex provider is still busy.
