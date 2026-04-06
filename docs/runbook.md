# Runbook

## Goal
GitHub Copilot SDKを用いたマルチエージェント環境を構築する

## Expected Deliverables
- docs/implementation-plan.md
- artifacts/workflow-state.json
- artifacts/run-summary.json

## Execution Flow
1. Define workflow state and agent interfaces
2. Implement orchestrator and CLI entrypoint
3. Add session persistence and model routing
4. Add implementation, test, and review agents

## Operator Checklist
- Confirm requirement text is finalized
- Confirm session snapshot and workflow state are persisted
- Confirm generated docs are reviewed before implementation
- Confirm unresolved questions are either answered or explicitly deferred
- Confirm persistent context is stored in `artifacts/workflow-state.json`, `artifacts/sessions/<session_id>/session-snapshot.json`, and `artifacts/summaries/<workflow_id>/run-summary.json`
- Confirm resume can recover `requirement`, `phase`, `workflow_id`, `session_id`, completed tasks, pending tasks, latest summary, and resume prompt
- Confirm destructive changes, dependency additions, and environment changes are not auto-approved

## Persistence Policy
- Persist workflow-level state in `artifacts/workflow-state.json`
- Persist session-level resume state in `artifacts/sessions/<session_id>/session-snapshot.json`
- Persist operator-facing execution summary in `artifacts/summaries/<workflow_id>/run-summary.json`
- Guarantee structured recovery data only; transient model reasoning and raw token streams are out of scope
- If persisted state is incomplete, resume from the latest consistent checkpoint instead of guessing missing context

## Approval Policy
- Allow routine generated writes under `docs/` and `artifacts/`
- Allow source edits under `src/devagents/` only when they pass the structured edit path and approval checks
- Require human approval for delete operations, broad overwrites, dependency additions, and execution-environment changes
- Never allow edits under protected roots

## Escalation Conditions
- Generated implementation plan conflicts with repository constraints
- Session restore data is incomplete or inconsistent
- A requested change requires destructive modification or dependency addition without explicit approval
