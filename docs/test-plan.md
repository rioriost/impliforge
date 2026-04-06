# Test Plan

## Objective
GitHub Copilot SDKを用いたマルチエージェント環境を構築する

## Strategy
- Validate acceptance criteria and operator checklist evidence before expanding implementation scope
- Prefer focused tests with a single assertion theme per scenario
- Cover happy path, failure path, recovery path, and completion-gating behavior for orchestration flow
- Verify session persistence, model routing, approval visibility, and generated artifact evidence explicitly

## Test Levels
- unit: Agent output shaping, routing decisions, state transitions, and artifact summary helpers
- integration: Orchestrator phase progression, artifact persistence, acceptance gating, and approval visibility
- end_to_end: Requirement intake through documentation, implementation proposal generation, fix-loop recovery, and CLI summary emission
- non_functional: Long-input handling, repeated session rotation stability, budget/degraded-routing signals, and artifact-volume/operator-facing guidance

## Acceptance Criteria Coverage
- A multi-agent workflow exists with an orchestrator
- Session rotation can preserve context through persistence
- Planning, implementation, testing, and review are represented
- Completion evidence and acceptance gating are surfaced in generated artifacts
- Unresolved questions are either resolved, explicitly deferred, or block completion

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
- `integration-acceptance-gate` (integration): Acceptance gating and completion evidence are emitted in generated artifacts.
  - assertion: run summary includes acceptance_gate and completion_evidence
  - assertion: final summary includes completion evidence and operator checklist evidence
  - assertion: unresolved questions can block completion unless resolved or explicitly deferred
- `integration-fix-revalidation-linkage` (integration): Fix outputs preserve explicit linkage to follow-up review and test revalidation.
  - assertion: fix report includes validation focus tied to review and test_execution
  - assertion: revalidation plan records follow-up checks and unresolved-question handling
- `e2e-cli-quality-mode` (end_to_end): CLI execution with quality routing mode completes and emits artifacts.
  - assertion: CLI exits successfully
  - assertion: routing_mode is reflected in output
  - assertion: artifacts list includes docs and artifacts paths
- `e2e-failure-recovery` (end_to_end): Failure path can recover through fix loop and persist recovered outputs.
  - assertion: recovered implementation, test, and review outputs are used in final persistence
  - assertion: artifact ordering reflects initial failure outputs followed by rerun outputs
- `acceptance-1` (integration): A multi-agent workflow exists with an orchestrator
  - assertion: Generated workflow outputs provide evidence for this criterion
- `acceptance-2` (integration): Session rotation can preserve context through persistence
  - assertion: Generated workflow outputs provide evidence for this criterion
- `acceptance-3` (integration): Planning, implementation, testing, and review are represented
  - assertion: Generated workflow outputs provide evidence for this criterion
- `slice-implementation-agent` (integration): Validate implementation slice `implementation-agent`: Add an implementation agent that turns plans into executable change proposals.
  - assertion: Targets are identified: src/devagents/agents/implementation.py
  - assertion: Dependencies are satisfied before execution
  - assertion: Downstream handoff metadata is present for test_design, test_execution, review, and fixer
- `slice-documentation-agent` (integration): Validate implementation slice `documentation-agent`: Add a documentation agent that produces design and runbook artifacts.
  - assertion: Targets are identified: src/devagents/agents/documentation.py
  - assertion: Dependencies are satisfied before execution
  - assertion: Runbook includes blocked-state handling and escalation guidance
- `slice-orchestrator-integration` (integration): Validate implementation slice `orchestrator-integration`: Wire documentation and implementation phases into the orchestrator.
  - assertion: Targets are identified: src/devagents/main.py
  - assertion: Dependencies are satisfied before execution
  - assertion: Fix-loop reruns preserve effective implementation, test, and review results for completion
- `slice-artifact-persistence` (integration): Validate implementation slice `artifact-persistence`: Persist implementation and documentation outputs into docs/ and artifacts/.
  - assertion: Targets are identified: docs/design.md, artifacts/workflows/<workflow_id>/workflow-details.json, artifacts/summaries/<workflow_id>/run-summary.json
  - assertion: Dependencies are satisfied before execution
  - assertion: Operator-facing failure visibility and approval risk summary are emitted
- `slice-src-allowlisted-edit-phase` (integration): Validate implementation slice `src-allowlisted-edit-phase`: Promote approved implementation proposals into structured source edits under src/devagents/.
  - assertion: Targets are identified: src/devagents/main.py, src/devagents/runtime/editor.py, src/devagents/agents/implementation.py
  - assertion: Dependencies are satisfied before execution
- `risk-open-questions` (review_gate): Ensure unresolved questions are surfaced before execution expands.
  - assertion: Open questions are listed in generated artifacts
  - assertion: Review phase can block completion when needed
  - assertion: Explicitly deferred open questions are distinguished from unresolved ones

## Fixtures and Data
- Sample requirement text for a Copilot SDK multi-agent workflow
- Long requirement text fixture for non-functional and CLI quality-mode scenarios
- Temporary artifacts directory for workflow-state, session snapshots, and run summaries
- Deterministic routing mode input such as quality/balanced/cost_saver
- Mocked or dry-run Copilot response payloads for repeatable validation
- Review outputs with blocking issues, resolved decisions, deferred open questions, and unresolved open questions

## Validation Commands
- uv run python -m devagents "sample requirement" --routing-mode quality
- uv run python -m devagents "sample requirement" --token-usage-ratio 0.9
- uv run pytest -q tests
- uv run pytest --cov=src/devagents --cov-report=term-missing:skip-covered -q tests

## Open Questions
- 追加の非機能シナリオとして、artifact volume と cost ceiling の上限値をどこまで厳密に数値化するかは今後の運用判断に委ねる。
- coverage 90% 未満の個別ソースが残る場合は、例外扱いではなく focused test 追加で解消する方針を維持する。

## Copilot Draft Notes
[dry-run] Copilot SDK response placeholder
model: gpt-5.4
task_type: test_design
reason: sdk_error:JsonRpcError
session_id: sess-20260406012216
workflow_id: wf-20260406012216
persistent_context_keys: documentation_bundle, implementation, normalized_requirements, phase, plan, requirement, workflow_id
prompt_preview:
{'objective': 'GitHub Copilot SDKを用いたマルチエージェント環境を構築する', 'summary': '要件をマルチエージェント実装向けに構造化した。', 'constraints': ['Use GitHub Copilot SDK as the orchestration foundation', 'Default model
