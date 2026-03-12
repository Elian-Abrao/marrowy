# Architecture

Marrowy evolves the earlier MVP without rewriting it.

The core design principle for this cycle is:

- chat stays human-readable and responsive
- execution moves into explicit background workers

## High-Level Shape

```text
Channels
  -> Marrowy entrypoints
  -> Conversation orchestration
  -> Policy / task / project / memory services
  -> Job scheduling and worker runner
  -> Provider adapter
  -> codex-runtime-bridge
  -> codex app-server
```

## Agent vs Worker

### Agents

Agents are visible conversational roles.

Responsibilities:

- acknowledge the user
- coordinate work
- explain decisions
- summarize progress
- request approvals
- perform handoffs

Current agent profiles:

- Agent Principal
- Agent Specialist
- Agent QA
- Agent GitHub
- Agent DevOps
- Agent PO/PM

Agents are still logical profiles inside the same Codex-backed runtime path. They are not separate OS processes.

### Workers

Workers are background execution units.

Responsibilities:

- claim queued jobs
- run provider turns asynchronously
- emit progress / status events
- update tasks and participant activity
- complete or fail jobs without blocking the room

Current worker keys:

- `summary`
- `specialist`
- `qa`
- `github`
- `devops`
- `planning`

This is intentionally pragmatic:

- one Python background runner
- DB-backed job queue
- explicit claim/lock state
- no external broker yet

## Main Layers

### Entry Layer

Entrypoints:

- FastAPI HTTP API
- terminal CLI
- WhatsApp relay

These layers translate channel input into conversation actions and expose live state back to the user.

### Conversation Layer

Main service:

- `src/marrowy/services/conversations.py`

Responsibilities:

- persist user messages
- create immediate Agent Principal ACK
- derive orchestration plan
- add agents idempotently
- emit onboarding / handoff messages
- create tasks / subtasks / approvals idempotently
- schedule background jobs

The conversation layer is now explicitly separated from execution.

### Task Layer

Main service:

- `src/marrowy/services/tasks.py`

Responsibilities:

- simple task creation
- pipeline creation
- stage creation
- subtask creation
- state transitions with explicit rules

Important change in this cycle:

- task transitions are rule-driven, not blind mutation

### Policy Layer

Main service:

- `src/marrowy/services/policies.py`

Policy decisions now consider:

- project
- environment
- action
- agent
- tool

Approvals are created idempotently and remain visible in chat and UI.

### Worker Layer

Main services:

- `src/marrowy/services/jobs.py`
- `src/marrowy/services/job_runner.py`

The worker layer introduces:

- `Job` entity
- job lifecycle
- claim/lock mechanism
- participant activity tracking
- background runner loop

#### Job Lifecycle

```text
queued -> claimed -> running -> succeeded
                      -> waiting
                      -> failed
```

Jobs carry:

- worker key
- agent key
- source message
- task / subtask association
- idempotency key
- result/progress payload

### Provider Layer

Main provider:

- `src/marrowy/providers/codex_bridge.py`

Real runtime path:

```text
Marrowy
  -> CodexBridgeProvider
  -> codex-runtime-bridge
  -> official codex app-server
```

The provider now streams intermediate events into Marrowy so the system can surface:

- commentary
- actions
- status updates
- final response

### Persistence Layer

Primary runtime database:

- PostgreSQL

Tests:

- SQLite where pragmatic

Main persisted entities:

- projects
- project repositories
- project environments
- pipeline templates
- conversations
- conversation participants
- conversation messages
- tasks
- approvals
- jobs
- domain events
- memory entries

## Responsiveness Strategy

The user should never send a message and then wait in silence.

Current flow:

1. persist the user message
2. send immediate Agent Principal ACK
3. schedule explicit jobs
4. surface participant activity as `queued`, `working`, `waiting`, `idle`, or `error`
5. emit job events through SSE / CLI / WhatsApp relay
6. persist the final agent message when the worker completes

This gives fast feedback even when the real Codex provider is slow.

## Structured Onboarding and Handoff

Adding an agent is now an explicit domain action.

Flow:

1. detect user intent to add a specialist
2. add the participant idempotently
3. emit `agent.joined`
4. create Principal onboarding/handoff message
5. queue a worker turn for the new agent

This avoids the earlier pattern where onboarding was implicit or duplicated.

## Idempotency Rules

This cycle made idempotency explicit for:

- agent addition
- onboarding / handoff
- approval creation
- pipeline creation
- simple task creation
- subtask decomposition
- worker job enqueueing

The goal is not distributed exactly-once semantics. The goal is pragmatic protection against repeated user prompts and UI retries.

## UI Model

Browser UI is intentionally simple and server-rendered.

Visible areas:

- chat transcript
- participants with activity state
- active jobs
- pending approvals
- task board grouped by status

Updates are delivered via SSE.

## WhatsApp Model

Marrowy does not own the WhatsApp socket.

Instead:

- `codex-chat-gateway` owns the transport
- Marrowy owns conversation orchestration
- the relay bridges inbound WhatsApp messages into Marrowy conversations
- background job results are pushed back out through the relay loop

This preserves channel separation while allowing WhatsApp to behave like a first-class Marrowy room.

## Tradeoffs

- V1/V2 still use one runtime-backed cognition path, not dedicated agent processes.
- Workers are DB-backed Python jobs, not a distributed queue.
- Participant activity is optimistic and UI-oriented, not a full distributed presence system.
- Some orchestration still uses deterministic heuristics rather than a full planner.
- The system favors pragmatic idempotency over complex replay semantics.

## Future Path

Most likely next architectural steps:

1. richer per-agent execution capabilities
2. stronger memory summarization and retrieval
3. more formal worker types and retries
4. deeper GitHub / DevOps execution integrations
5. promotion of selected logical agents into dedicated workers
