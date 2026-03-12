# AGENTS.md

## 1. Purpose

This repository implements a **multi-agent conversational orchestration system**.

Agents collaborate through a shared chat interface to:

* analyze problems
* plan solutions
* create and execute tasks
* interact with tools
* request approvals
* deploy or validate systems

The system is designed to be:

* auditable
* deterministic in orchestration
* flexible in cognition (LLM reasoning)
* extensible to multiple agents and providers

Agents **communicate through chat**, but **operate through structured tasks and events**.

---

# 2. Architectural Principles

The system follows four core principles.

### 2.1 Chat carries intent and coordination

The chat is the human-visible interface where:

* users communicate goals
* agents coordinate work
* approvals are requested
* decisions are explained

The chat is **not** the execution system.

---

### 2.2 Tasks carry execution

Tasks represent operational work:

* diagnostics
* implementations
* validations
* deployments
* automation

Tasks contain:

* structured context
* progress
* artifacts
* execution status

---

### 2.3 Memory carries continuity

Memory stores persistent knowledge across conversations.

There are four memory layers:

| Memory              | Scope        | Purpose                  |
| ------------------- | ------------ | ------------------------ |
| Conversation Memory | conversation | maintain chat context    |
| Task Memory         | task         | execution state          |
| Project Memory      | project      | technical context        |
| User Memory         | user         | preferences and patterns |

---

### 2.4 Agents carry roles

Agents are specialized roles that collaborate to complete tasks.

Examples:

* Agent Principal
* Agent Specialist
* Agent QA
* Agent DevOps
* Agent GitHub
* Agent PO/PM

Agents must **respect role boundaries and policies**.

---

# 3. Core System Components

The system is composed of the following layers.

```
Channels
  ↓
Runtime Bridge
  ↓
Conversation System
  ↓
Agent Core
  ↓
Task System
  ↓
Tools / Integrations
```

## Channels

Supported user interfaces:

* WhatsApp
* Browser Chat
* Terminal Chat

All channels converge into the conversation system.

---

## Runtime Bridge

`codex-runtime-bridge` acts as a multiprotocol adapter that exposes:

* CLI interface
* HTTP interface
* Python SDK

It communicates with the official `codex app-server` via:

```
JSON-RPC over stdio
```

---

## Agent Core

The Agent Core orchestrates reasoning and actions.

Responsibilities:

* build context
* invoke the LLM
* interpret model output
* enforce policies
* call tools
* update tasks
* emit events

Important rule:

> The LLM does not orchestrate the system.
> The Agent Core orchestrates the system.

---

## Model Adapter

The model adapter provides a unified interface to any LLM provider.

Supported providers may include:

* Codex runtime
* OpenAI
* Anthropic
* local models

Agents must **never call providers directly**.

They must go through the **Model Adapter**.

---

## Provider Adapter

Provider adapters translate requests into provider-specific protocols.

Examples:

| Provider  | Transport        |
| --------- | ---------------- |
| Codex     | JSON-RPC / stdio |
| OpenAI    | HTTP             |
| Anthropic | HTTP             |
| Local     | direct runtime   |

---

# 4. Agents

Agents are logical profiles that execute within the runtime.

Agents are **not separate processes by default**.

They are defined by:

* role
* policies
* allowed tools
* behavioral guidelines

In the future, some agents may evolve into **dedicated workers**.

---

# 5. Agent Roles

## Agent Principal

The primary coordinator.

Responsibilities:

* respond to the user
* coordinate agents
* assign tasks
* enforce project policies
* request approvals
* summarize progress

The principal **does not specialize in execution**.

---

## Agent Specialist

Responsible for technical implementation.

Typical tasks:

* debugging
* code changes
* architecture fixes
* refactoring

---

## Agent QA

Responsible for validation.

Responsibilities:

* test execution
* validation
* verification
* reporting issues

---

## Agent DevOps

Responsible for infrastructure.

Responsibilities:

* deployment
* container orchestration
* environment configuration

Deployments may require **explicit approval**.

---

## Agent GitHub

Responsible for repository operations.

Responsibilities:

* commits
* pull requests
* branch management

---

## Agent PO / PM

Responsible for task planning.

Responsibilities:

* decompose tasks
* define subtasks
* manage pipelines

---

# 6. Conversation Model

Conversations are collaborative chat rooms.

Participants include:

* the user
* Agent Principal
* specialized agents

All agents may speak in the chat.

This ensures:

* transparency
* auditability
* intervention capability

---

## Conversation Lifecycle

Possible states:

```
active
waiting_user
waiting_agent
blocked
completed
archived
```

---

# 7. Tasks

Tasks represent operational work units.

Tasks may be simple or structured as pipelines.

Example pipeline:

```
diagnosis → implementation → QA → deploy
```

Tasks may contain **subtasks** created by:

* Agent Principal
* Agent PO/PM
* specialized agents (with approval)

---

## Task Status

```
created
planned
in_progress
blocked
waiting_approval
testing
deploying
done
failed
cancelled
```

---

## Task Content

Tasks contain:

* goal
* scope
* repository
* branch
* environment
* assigned agents
* progress updates
* artifacts
* results

Detailed execution information belongs **inside the task**, not the chat.

---

# 8. Project Context

Projects are independent entities.

A project may contain:

* repositories
* environments
* deployment policies
* pipeline templates
* technical documentation

The project context may include a structured section and a freeform `AGENTS.md` style description.

Multiple conversations may operate on the same project.

---

# 9. Authorization System

Some actions require explicit authorization.

Examples:

* production deployment
* infrastructure modification
* critical system changes
* agent hiring in restricted projects

Authorization requests should be issued in chat.

The system may also reflect approvals in a UI dashboard.

If the user does not respond:

* tasks may remain blocked
* or the Agent Principal may decide according to project policy.

---

# 10. Event System

Important system events are persisted.

Examples:

```
conversation.message.created
agent.joined
task.created
task.status.updated
tool.executed
approval.requested
approval.granted
deployment.completed
```

Events allow:

* audit trails
* observability
* debugging
* analytics

---

# 11. Memory Governance

Agents may suggest memory updates.

Examples:

* user preferences
* project conventions
* repeated patterns

However:

Agents **do not directly persist memory**.

Memory updates must be **reviewed and consolidated by the Agent Principal**.

---

# 12. Tool Usage

Agents may use tools such as:

* browser automation
* repository operations
* infrastructure management
* testing systems

Tool access is controlled by:

```
agent role
project policy
environment
task context
```

---

# 13. Message Guidelines

Agents should:

* communicate clearly
* summarize technical work in chat
* store detailed execution data in tasks
* explicitly reference task IDs

Example:

```
[Agent Specialist]
Fix applied. Task T-148 moved to testing.
```

---

# 14. Agent Onboarding

When a new agent enters a conversation, it receives:

* conversation summary
* introduction from the Agent Principal
* relevant task context
* project context
* permissions and policies

This ensures agents join with full situational awareness.

---

# 15. Observability

The system should support future observability features:

* execution dashboards
* task pipelines
* agent performance metrics
* event timelines

The architecture must be designed to support these features even if they are not implemented initially.

---

# 16. Design Philosophy

The system intentionally separates:

```
Chat → intent
Tasks → execution
Memory → continuity
Agents → roles
LLM → cognition
Core system → orchestration
```

This separation ensures:

* control
* auditability
* extensibility
* provider independence

---

# 17. Final Guiding Rule

> The LLM assists decisions, but the system enforces structure.

Agents collaborate through reasoning,
but the **architecture guarantees reliability**.
