# Roadmap

## Current MVP+

The project now includes:

- FastAPI backend
- browser UI
- terminal console
- project / conversation / task / approval persistence
- Codex bridge provider
- WhatsApp relay entry path
- explicit worker/job model
- participant activity state
- responsive ACK + progress feedback
- subtasks and PO/PM decomposition
- stronger idempotency and policy enforcement

## Next Cycle Priorities

1. richer worker execution behavior
   - retry/backoff policy
   - worker capability registry
   - selective cancellation / superseding of stale jobs

2. deeper GitHub / DevOps automation
   - repository-aware task execution
   - PR workflow hooks
   - deploy environment actions tied to policies

3. stronger memory and summarization
   - project summaries
   - conversation compression
   - better onboarding context packs

4. better operator UX
   - cleaner active-job aggregation
   - less noisy Principal follow-up turns
   - timeline/history view for jobs and approvals

5. stronger WhatsApp validation
   - longer real relay test battery
   - approval-heavy flows through the relay
   - latency and resilience measurement

## Longer-Term Direction

1. promote selected logical agents into dedicated workers where it truly helps
2. add first-class repository/environment execution backends
3. improve domain event inspection and replay tooling
4. add analytics and operational dashboards
