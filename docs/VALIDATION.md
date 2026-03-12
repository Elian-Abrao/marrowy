# Validation

This cycle focused on responsiveness, visible progress, and explicit worker execution.

Validation was performed against:

- PostgreSQL in Docker
- the real `codex-runtime-bridge`
- the official Codex runtime behind that bridge
- Marrowy terminal console
- Marrowy browser UI
- automated tests, including browser E2E

## Automated Validation

Commands used:

```bash
source .venv/bin/activate
pytest -q
bash scripts/browser_e2e.sh
```

Coverage added in this cycle includes:

- worker/job lifecycle
- background execution without blocking the room
- idempotent job enqueueing
- idempotent onboarding / handoff
- idempotent approvals
- idempotent subtask decomposition
- browser visibility for active jobs and participant activity

## Real Runtime Setup

Environment used:

- `MARROWY_DATABASE_URL=postgresql+psycopg://marrowy:marrowy@127.0.0.1:5432/marrowy`
- `MARROWY_MODEL_PROVIDER=codex`
- `MARROWY_CODEX_BRIDGE_URL=http://127.0.0.1:8787`

Bridge readiness check:

```bash
curl http://127.0.0.1:8787/readyz
```

Result:

- bridge was healthy
- Marrowy reached the real provider path successfully

## Serious Terminal Validation Battery

Primary conversation for this cycle:

- conversation id: `33d6ec1d-b1e2-4c57-a018-2a1e2108c615`
- user message count: `20`
- approval commands excluded from the count

### Validation Goal

Prove that the system:

- acknowledges the user immediately
- stays responsive while work is ongoing
- shows visible activity instead of silent waiting
- handles approvals while jobs remain pending
- coordinates multiple visible agents on top of explicit workers

### Representative User Messages

The following requests were sent manually in the terminal:

1. `Hi Principal, explain how agents and workers differ in this room and how you will keep me updated while work is happening.`
2. `Please create the task pipeline for a release checklist MVP with diagnosis, implementation, QA, and deploy readiness.`
3. `Add Agent PO/PM.`
4. `Ask Agent PO/PM to refine the release checklist MVP into small incremental steps with explicit subtasks.`
5. `Add Agent Specialist.`
6. `Add Agent QA.`
7. `Add Agent GitHub.`
8. `Add Agent DevOps.`
9. `Summarize the current active jobs, visible activity, and any blocked state.`
10. `Create a separate follow-up task for browser UX polish after the main release checklist work.`
11. `Please prepare a production deployment for the active pipeline.`
12. `Summarize what changed in task state after the approval flow.`
13. `Create another project pipeline for a personal notes MVP.`
14. `Ask Agent PO/PM to decompose the personal notes MVP into small incremental steps with subtasks.`
15. `Ask Agent Specialist to diagnose persistence choices for the notes MVP.`
16. `Give me a concise room status update.`
17. `Ask Agent QA for the minimum test plan for the notes MVP.`
18. `Ask Agent GitHub for the branch and PR strategy for the notes MVP.`
19. `Ask Agent DevOps for the environment assumptions before production.`
20. `Summarize the visible task board at the end of this validation.`

Approval command used during the session:

- `/approve 10e5255e-bc54-436d-a327-15f260920b7a`

That command is intentionally excluded from the 20-message count.

## Terminal UX Findings

Observed positive behavior:

- the Agent Principal ACK was immediate after each user message
- the room accepted another user message while a worker was still running
- job state became visible through console updates such as:
  - `job.queued`
  - `job.started`
  - participant activity updates
- users no longer had to wait in silence for the final provider answer

This cycle therefore improved perceived responsiveness in a meaningful way.

## Browser Validation

The same real conversation was opened in the browser UI and inspected live.

Example URL:

```text
http://127.0.0.1:8012/conversations/33d6ec1d-b1e2-4c57-a018-2a1e2108c615
```

Confirmed in the browser:

- live transcript with ACK + multi-agent messages
- participant list with activity states such as:
  - `queued`
  - `working`
  - `idle`
- `Active Jobs` panel visible
- pending approval visible with action buttons
- task board visible with pipeline and subtask state
- blocked / waiting state surfaced in the room instead of hidden behind provider latency

## Bugs Found During Real Validation

The validation battery surfaced several issues that were fixed in this cycle:

1. deploy prompts created duplicate pipelines
   - fixed by reusing the active root task unless the user is clearly starting a new project

2. decomposition could target the wrong pipeline
   - fixed by selecting the most relevant root task instead of blindly using the first one

3. repeated deploy requests created duplicate approvals
   - fixed with explicit approval idempotency keys

4. the room could feel stalled while provider turns were executing
   - fixed with immediate ACK, explicit jobs, and participant activity visibility

5. onboarding / handoff could be repeated
   - fixed with idempotent agent addition and dedicated onboarding flow

## Residual Tradeoffs

These are known and acceptable for the current stage:

- workers are still a DB-backed Python runner, not a distributed queue
- specialist execution is still Codex-backed logical-role execution, not separate agent processes
- the Active Jobs panel can get noisy when many Principal follow-up turns are queued
- WhatsApp relay support exists, but the deepest validation for this cycle focused on terminal + browser responsiveness

## Conclusion

This cycle met its validation goals:

- workers exist as explicit execution units
- the chat remains responsive while work is pending
- the user gets immediate feedback
- long-running work no longer leaves the room silently stuck
- approvals can coexist with ongoing background execution
- browser and terminal both expose visible progress
