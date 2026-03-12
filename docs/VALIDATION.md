# Validation

This repository was validated with:

- PostgreSQL in Docker
- the real `codex-runtime-bridge`
- the official Codex runtime behind that bridge
- Marrowy terminal console
- Marrowy browser UI
- automated tests, including Playwright browser E2E

## Automated Validation

Commands used:

```bash
source .venv/bin/activate
pytest
playwright install chromium
pytest -q tests/e2e/test_browser_ui.py
```

Result:

- unit tests passed
- API tests passed
- CLI tests passed
- browser E2E passed

## Real Runtime Smoke

Environment:

- `MARROWY_DATABASE_URL=postgresql+psycopg://marrowy:marrowy@127.0.0.1:5432/marrowy`
- `MARROWY_MODEL_PROVIDER=codex`
- `MARROWY_CODEX_BRIDGE_URL=http://127.0.0.1:8787`

Smoke outcome:

- Marrowy created a real conversation
- Marrowy called the real bridge provider
- the provider returned a real Codex response:
  - `Agent Principal => ACK`

## Manual Conversation Validation

Primary validated conversation:

- conversation id: `b3b9cdf6-213e-4c42-91e1-2cac6ecdd4a9`
- user message count: `22`
- approval command count excluded from that total

### Covered Scenarios

1. normal conversation with `Agent Principal`
2. creation of a real task pipeline
3. adding `Agent Specialist`
4. adding `Agent PO/PM`
5. adding `Agent QA`
6. adding `Agent GitHub`
7. adding `Agent DevOps`
8. onboarding / handoff in chat
9. project diagnosis and storage-choice discussion
10. task decomposition by `PO/PM`
11. QA participation and validation planning
12. GitHub participation and repo-flow guidance
13. DevOps participation and deploy-risk guidance
14. separate follow-up task creation
15. task-board summary in chat
16. policy-aware production deployment request
17. approval resolution in terminal
18. post-approval state summary
19. creation of a brand-new second MVP idea in the same conversation
20. creation of a second project pipeline for that new MVP
21. evolution of the second MVP by deferring due dates and ownership
22. browser inspection of the resulting conversation state

### Representative User Messages

Examples from the validated session:

- `Hi Principal, can you summarize how you work in this room?`
- `Please create the task pipeline for a basic single-user web todo MVP with diagnosis, implementation, QA, and deploy readiness.`
- `Add Agent Specialist and give them a short handoff for the active pipeline.`
- `Please ask Agent Specialist to diagnose the best storage choice for v1.`
- `Please ask Agent PO/PM to refine the MVP into small incremental steps.`
- `Please create a separate task for browser UI polish after the core todo flow.`
- `Please have DevOps explain the main production risks before deploy.`
- `Please prepare a production deployment for the active MVP pipeline.`
- `Create another project pipeline for the mini release checklist app in this same conversation.`
- `Please evolve the release checklist MVP so due dates and ownership exist only as deferred follow-on scope, not in v1.`

## Browser Validation

The conversation above was opened in the browser UI at:

```text
http://127.0.0.1:8000/conversations/b3b9cdf6-213e-4c42-91e1-2cac6ecdd4a9
```

Confirmed in the UI:

- multi-agent transcript visible
- participants list visible
- pending approvals visible
- task board visible with cards by status
- second pipeline visible in the board

## Findings From Real Validation

Issues found and addressed during implementation:

- duplicate pipeline creation on coordination-only prompts
- specialists auto-invoked too aggressively by keyword heuristics
- duplicate approval creation for repeated deploy requests
- QA and DevOps task statuses jumped too far automatically
- browser UI needed a direct conversation creation flow

These fixes are included in the current repository state.
