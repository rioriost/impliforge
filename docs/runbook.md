# Runbook

## Goal
GitHub Copilot SDKを用いたマルチエージェント環境を構築し、要件分析から計画、ソースコード実装提案、テスト設計、テストコード実装、テスト実行、レビュー、修正ループ、成果物保存までを一貫して運用できる状態を維持する

## Expected Deliverables
- `docs/implementation-plan.md`
- `docs/design.md`
- `docs/runbook.md`
- `docs/test-plan.md`
- `docs/test-results.md`
- `docs/review-report.md`
- `docs/fix-report.md`
- `docs/final-summary.md`
- `artifacts/workflow-state.json`
- `artifacts/sessions/<session_id>/session-snapshot.json`
- `artifacts/workflows/<workflow_id>/workflow-details.json`
- `artifacts/summaries/<workflow_id>/run-summary.json`

## Execution Flow
1. Define workflow state and agent interfaces
2. Implement orchestrator and CLI entrypoint
3. Add session persistence and model routing
4. Add source-code implementation, test design, test implementation, and review agents
5. Persist workflow artifacts and operator-facing summaries
6. Apply safe edit orchestration for source and test changes, then run fix-loop reruns when review requires follow-up

## Operator Checklist
- Confirm requirement text is finalized
- Confirm generated docs are reviewed before implementation expands
- Confirm source-code implementation scope and paired test implementation scope are both explicit
- Confirm session snapshot and workflow state are persisted
- Confirm persistent context is stored in `artifacts/workflow-state.json`, `artifacts/sessions/<session_id>/session-snapshot.json`, and `artifacts/summaries/<workflow_id>/run-summary.json`
- Confirm resume can recover `requirement`, `phase`, `workflow_id`, `session_id`, completed tasks, pending tasks, latest summary, and resume prompt
- Confirm unresolved questions are either answered or explicitly deferred
- Confirm blocked work and escalation-required states are visible in generated summaries
- Confirm destructive changes, dependency additions, and environment changes are not auto-approved
- Confirm source edits and test edits both follow the approved structured edit path
- Confirm completion evidence shows acceptance readiness before treating the workflow as done

## Blocked-State Handling
- If `acceptance_gate.ready_for_completion` is false, do not treat the run as complete
- If unresolved questions remain, resolve them or explicitly defer them before closeout
- If source-code implementation is updated without corresponding test implementation work, treat the run as incomplete unless the omission is explicitly justified
- If a task is blocked or failed, use the recorded `next_actions`, `risk_register`, and review/fix outputs to decide whether to retry or escalate
- If fix-loop retry limits are reached, stop automatic retries and switch to human escalation
- If persisted state is incomplete, resume from the latest consistent checkpoint instead of guessing missing context

## Operator Escalation Actions
- For destructive changes, dependency additions, execution-environment changes, or protected-root edits, require explicit human approval before proceeding
- For blocked review findings, convert the recommendation into a concrete fix slice and re-run `test_implementation`, `test_execution`, and `review` as needed
- For unresolved questions that cannot be answered immediately, record an explicit defer decision and keep that decision visible in generated artifacts
- For repeated fix-loop failures or retry-limit exhaustion, escalate with the current failure category, failure cause, and recommended next actions
- Resume only after the blocking condition, approval requirement, or unresolved-question handling has been recorded

## Persistence Policy
- Persist workflow-level state in `artifacts/workflow-state.json`
- Persist session-level resume state in `artifacts/sessions/<session_id>/session-snapshot.json`
- Persist workflow detail payloads in `artifacts/workflows/<workflow_id>/workflow-details.json`
- Persist operator-facing execution summaries in `artifacts/summaries/<workflow_id>/run-summary.json`
- Guarantee structured recovery data only; transient model reasoning and raw token streams are out of scope
- If persisted state is incomplete, resume from the latest consistent checkpoint instead of guessing missing context

## Approval Policy
- Allow routine generated writes under `docs/` and `artifacts/`
- Allow source edits under `src/impliforge/` only when they pass the structured edit path and approval checks
- Allow test edits under `tests/` only when they pass the structured edit path and approval checks
- Require human approval for delete operations, broad overwrites, dependency additions, execution-environment changes, and security-impacting edits
- Never allow edits under protected roots

## Non-Functional Guidance
- Watch budget-pressure signals in operator-facing summaries before cost ceilings are exceeded
- Keep artifact lists deduplicated and operator-meaningful so recovery and review remain readable
- Treat repeated session rotation as a normal recovery path and confirm resumable context remains intact across rotations
- Prefer focused validation slices so failure causes and revalidation steps stay attributable

## Escalation Conditions
- Generated implementation plan conflicts with repository constraints
- Session restore data is incomplete or inconsistent
- A requested change requires destructive modification or dependency addition without explicit approval
- Fix-loop retry limits are reached
- Acceptance gating remains blocked because unresolved questions, blocked tasks, or failed tasks remain visible in generated artifacts
