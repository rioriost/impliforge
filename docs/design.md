# Design

## Objective
GitHub Copilot SDKを用いたマルチエージェント環境を構築する

## Architecture Direction
- Orchestrator-centric multi-agent workflow
- GitHub Copilot SDK is isolated behind a client layer
- Session continuity is handled through snapshot and resume flow
- Model routing is selected per task kind

## Constraints
- Use GitHub Copilot SDK as the orchestration foundation
- Default model is GPT-5.4 with task-aware routing
- Development workflow is managed with uv
- Copilot SDK integration points must be isolated behind a client layer

## Acceptance Criteria
- A multi-agent workflow exists with an orchestrator
- Session rotation can preserve context through persistence
- Planning, implementation, testing, and review are represented

## Inferred Capabilities
- requirements_analysis
- planning
- documentation
- implementation
- test_design
- test_execution
- review

## Planned Phases
1. Define workflow state and agent interfaces
2. Implement orchestrator and CLI entrypoint
3. Add session persistence and model routing
4. Add implementation, test, and review agents

## Task Breakdown
- `requirements_analysis`: Normalize the incoming requirement and extract constraints.
  - depends_on: none
- `planning`: Create an implementation plan and task breakdown.
  - depends_on: requirements_analysis
- `documentation`: Generate or update design and workflow documentation.
  - depends_on: planning
- `implementation`: Implement the required code changes.
  - depends_on: planning
- `test_design`: Define test cases and validation strategy.
  - depends_on: planning
- `test_execution`: Run tests and collect validation results.
  - depends_on: implementation, test_design
- `review`: Review implementation quality, risks, and acceptance coverage.
  - depends_on: implementation, test_execution
- `finalization`: Prepare final summary and completion artifacts.
  - depends_on: documentation, review

## Out of Scope
- Web UI
- 複数リポジトリ同時対応
- 高度な分散スケジューリング

## Persistent Context Policy
- persistent context は `artifacts/workflow-state.json`、`artifacts/sessions/<session_id>/session-snapshot.json`、`artifacts/summaries/<workflow_id>/run-summary.json` に保存する。
- 復元粒度は workflow 単位と session 単位を基本とし、最低限 `requirement`、`phase`、`workflow_id`、`session_id`、完了済みタスク、未完了タスク、直近の要約、resume prompt を保証対象にする。
- エージェントごとの一時的な推論全文やトークン列は保証対象に含めず、再開に必要な構造化状態のみを永続化する。
- 永続化データが欠落している場合は、最後に整合している checkpoint まで戻して再開する。

## Approval Policy
- 破壊的変更はデフォルトで自動承認しない。
- `src/devagents/` 配下の allowlisted source edit は構造化 edit proposal と approval hook を通した場合のみ許可する。
- delete 操作、広範囲 overwrite、依存追加、実行環境変更は human approval を必須とする。
- `docs/` と `artifacts/` への生成物保存は通常運用として許可するが、protected roots は常に対象外とする。

## Resolved Decisions
- persistent context は `artifacts/workflow-state.json`、`artifacts/sessions/<session_id>/session-snapshot.json`、`artifacts/summaries/<workflow_id>/run-summary.json` に保存する。
- 復元粒度は workflow/session 単位とし、`requirement`、`phase`、`workflow_id`、`session_id`、完了済みタスク、未完了タスク、直近要約、resume prompt を保証対象にする。
- delete 操作、広範囲 overwrite、依存追加、実行環境変更は human approval 必須とする。

## Copilot Draft Notes
[dry-run] Copilot SDK response placeholder
model: gpt-5.4
task_type: documentation
reason: sdk_error:JsonRpcError
session_id: sess-20260406011449
workflow_id: wf-20260406011449
persistent_context_keys: normalized_requirements, phase, plan, requirement, workflow_id
prompt_preview:
{'objective': 'GitHub Copilot SDKを用いたマルチエージェント環境を構築する', 'summary': '要件をマルチエージェント実装向けに構造化した。', 'constraints': ['Use GitHub Copilot SDK as the orchestration foundation', 'Default model is GPT-5.4 with task-aware routing', 'Development workflow is managed with uv', 'Copilot SDK integration points must be isolated behind a client layer'], 'acceptance_criteria': ['A multi-agent workflow exists with an
