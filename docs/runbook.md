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

## Escalation Conditions
- Open questions remain unresolved before implementation starts
- Design assumptions conflict with repository constraints
- Session restore data is incomplete or inconsistent
