# Test Plan

## Objective
GitHub Copilot SDKを用いたマルチエージェント環境を構築する

## Strategy
- Validate acceptance criteria before expanding implementation scope
- Prefer focused tests with a single assertion theme per scenario
- Cover both happy path and failure path for orchestration flow
- Verify session persistence and model routing behavior explicitly

## Test Levels
- unit: Agent output shaping, routing decisions, and state transitions
- integration: Orchestrator phase progression and artifact persistence
- end_to_end: Requirement intake through documentation and implementation proposal generation

## Acceptance Criteria Coverage
- A multi-agent workflow exists with an orchestrator
- Session rotation can preserve context through persistence
- Planning, implementation, testing, and review are represented

## Test Cases
- `unit-routing-selection` (unit): Task kind and routing mode select an expected model candidate.
  - assertion: ModelRouter returns a selected_model
  - assertion: RoutingDecision includes fallback_model or explicit absence
  - assertion: Routing reason is recorded
- `unit-session-snapshot` (unit): Session snapshot captures resumable workflow context.
  - assertion: SessionSnapshot contains session_id and last_checkpoint
  - assertion: Persistent context includes completed and pending tasks
  - assertion: Resume prompt can be generated from the snapshot
- `integration-orchestrator-flow` (integration): Orchestrator completes requirements, planning, documentation, and implementation phases.
  - assertion: requirements_analysis is completed
  - assertion: planning is completed
  - assertion: documentation is completed
  - assertion: implementation is completed
- `integration-artifact-persistence` (integration): Workflow artifacts and docs are persisted after execution.
  - assertion: workflow-state.json is written
  - assertion: session-snapshot.json is written
  - assertion: run-summary.json is written
  - assertion: design.md, runbook.md, and final-summary.md are written
- `e2e-cli-quality-mode` (end_to_end): CLI execution with quality routing mode completes and emits artifacts.
  - assertion: CLI exits successfully
  - assertion: routing_mode is reflected in output
  - assertion: artifacts list includes docs and artifacts paths
- `acceptance-1` (integration): A multi-agent workflow exists with an orchestrator
  - assertion: Generated workflow outputs provide evidence for this criterion
- `acceptance-2` (integration): Session rotation can preserve context through persistence
  - assertion: Generated workflow outputs provide evidence for this criterion
- `acceptance-3` (integration): Planning, implementation, testing, and review are represented
  - assertion: Generated workflow outputs provide evidence for this criterion
- `slice-implementation-agent` (integration): Validate implementation slice `implementation-agent`: Add an implementation agent that turns plans into executable change proposals.
  - assertion: Targets are identified: src/devagents/agents/implementation.py
  - assertion: Dependencies are satisfied before execution
- `slice-documentation-agent` (integration): Validate implementation slice `documentation-agent`: Add a documentation agent that produces design and runbook artifacts.
  - assertion: Targets are identified: src/devagents/agents/documentation.py
  - assertion: Dependencies are satisfied before execution
- `slice-orchestrator-integration` (integration): Validate implementation slice `orchestrator-integration`: Wire documentation and implementation phases into the orchestrator.
  - assertion: Targets are identified: src/devagents/main.py
  - assertion: Dependencies are satisfied before execution
- `slice-artifact-persistence` (integration): Validate implementation slice `artifact-persistence`: Persist implementation and documentation outputs into docs/ and artifacts/.
  - assertion: Targets are identified: docs/design.md, artifacts/workflows/<workflow_id>/workflow-details.json, artifacts/summaries/<workflow_id>/run-summary.json
  - assertion: Dependencies are satisfied before execution
- `slice-src-allowlisted-edit-phase` (integration): Validate implementation slice `src-allowlisted-edit-phase`: Promote approved implementation proposals into allowlisted source edits under src/devagents/.
  - assertion: Targets are identified: src/devagents/main.py, src/devagents/runtime/editor.py, src/devagents/agents/implementation.py
  - assertion: Dependencies are satisfied before execution
- `risk-open-questions` (review_gate): Ensure unresolved questions are surfaced before execution expands.
  - assertion: Open questions are listed in generated artifacts
  - assertion: Review phase can block completion when needed

## Fixtures and Data
- Sample requirement text for a Copilot SDK multi-agent workflow
- Temporary artifacts directory for workflow-state and session snapshots
- Deterministic routing mode input such as quality/balanced/cost_saver
- Mocked or dry-run Copilot response payloads for repeatable validation

## Validation Commands
- uv run python -m devagents "sample requirement" --routing-mode quality
- uv run python -m devagents "sample requirement" --token-usage-ratio 0.9

## Open Questions
- persistent context の保存先と復元粒度をどこまで保証するか未確定。
- 破壊的変更や依存追加時の承認フロー要否が未確定。

## Copilot Draft Notes
[dry-run] Copilot SDK response placeholder
model: gpt-5.4
task_type: test_design
reason: sdk_error:JsonRpcError
session_id: sess-20260406005343
workflow_id: wf-20260406005343
persistent_context_keys: documentation_bundle, implementation, normalized_requirements, phase, plan, requirement, workflow_id
prompt_preview:
{'objective': 'GitHub Copilot SDKを用いたマルチエージェント環境を構築する', 'summary': '要件をマルチエージェント実装向けに構造化した。', 'constraints': ['Use GitHub Copilot SDK as the orchestration foundation', 'Default model
