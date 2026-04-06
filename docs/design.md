# Design

## Objective
GitHub Copilot SDKを用いたマルチエージェント環境を構築する

## Status
- 実装済みの orchestrator-centric workflow が存在する
- session persistence / rotation / resume flow は実装済み
- task-aware routing、artifact persistence、review/fix loop、safe edit phase は実装済み
- 主要な docs-driven refinement と回帰テスト追加まで完了している
- 現在のテストスイートは `291 passed`
- source coverage は全体で高水準で、主要 source file は概ね 90% 以上を満たしている

## Architecture Direction
- Orchestrator-centric multi-agent workflow
- GitHub Copilot SDK is isolated behind a client layer
- Session continuity is handled through snapshot and resume flow
- Model routing is selected per task kind
- `main.py` の orchestrator は phase sequencing を中心に保ち、成果物保存と edit 実行は専用 helper に分離する
- acceptance gating、operator-facing summary、approval/risk visibility を artifact layer に集約する

## Constraints
- Use GitHub Copilot SDK as the orchestration foundation
- Default model is GPT-5.4 with task-aware routing
- Development workflow is managed with uv
- Copilot SDK integration points must be isolated behind a client layer
- Orchestrator responsibilities should stay thin by delegating artifact persistence and edit execution to dedicated helpers

## Acceptance Criteria
- A multi-agent workflow exists with an orchestrator
- Session rotation can preserve context through persistence
- Planning, source-code implementation, test-code implementation, testing, and review are represented
- Artifact persistence and safe edit execution are separated from phase sequencing logic

## Inferred Capabilities
- requirements_analysis
- planning
- documentation
- implementation
- test_design
- test_implementation
- test_execution
- review
- fix
- acceptance_gating
- operator_summary
- approval_visibility

## Implemented Phases
1. requirements analysis
2. planning
3. documentation
4. implementation
5. test design
6. test implementation
7. test execution
8. review
9. fix loop
10. safe edit phase
11. final artifact persistence and completion evidence generation

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
- `test_implementation`: Implement and update test code, fixtures, and test helpers based on the plan and implementation diff.
  - depends_on: planning, implementation, test_design
- `test_execution`: Run tests and collect validation results.
  - depends_on: implementation, test_implementation
- `review`: Review implementation quality, risks, acceptance coverage, and source/test alignment.
  - depends_on: implementation, test_execution
- `fix`: Generate focused fix slices and revalidation guidance when review requires follow-up.
  - depends_on: review, test_execution
- `finalization`: Prepare final summary, acceptance evidence, and operator-facing completion artifacts.
  - depends_on: documentation, review, fix

## Current Implementation Shape
- `src/impliforge/main.py`
  - `SkeletonOrchestrator` が workflow の phase 順序、依存注入、session rotation の呼び出しを担当する
  - phase 実行は `_execute_phase` に共通化され、routing / Copilot request / agent dispatch / result 適用をまとめて扱う
  - fix loop 成功後は rerun 済み implementation / test / review 結果を completion 側へ引き継ぐ
- `src/impliforge/orchestration/artifact_writer.py`
  - `WorkflowArtifactWriter` が design/runbook/test/review/fix の文書出力、final summary 生成、workflow state / session snapshot / run summary 保存を担当する
  - acceptance gate、completion evidence、operator checklist evidence、approval risk summary、failure visibility を生成する
  - `artifacts/workflows/<workflow_id>/workflow-details.json` を保存する
- `src/impliforge/orchestration/edit_phase.py`
  - `EditPhaseOrchestrator` が safe edit operations 構築、allowlisted file edits、structured code edit request と structured test edit request の生成・適用を担当する
- `src/impliforge/orchestration/orchestrator.py`
  - minimal orchestrator 実装を shared agent interfaces と canonical workflow state に揃えた参照実装として保持する
  - open questions や blocked/failed task が残る場合は acceptance-driven に completion を block する
- `src/impliforge/orchestration/workflow.py`
  - canonical な `WorkflowState`、`WorkflowTask`、phase / task status、default task graph を提供する
  - ready task / dependency blocker 可視化を提供する
- `src/impliforge/orchestration/session_manager.py`
  - session snapshot、restore、rotation、resume prompt 生成を担当する
- `src/impliforge/orchestration/runtime_support.py`
  - session rotation helper、budget-like degraded routing、approval hook 連携を担当する
- `src/impliforge/models/routing.py`
  - task-aware routing、fallback metadata、routing reason を提供する
- `src/impliforge/runtime/copilot_client.py`
  - Copilot SDK 呼び出しと environment preflight を担当する
- `src/impliforge/agents/`
  - requirements / planner / documentation / implementation / test_design / test_implementation / reviewer / fixer が構造化出力を返す
  - implementation agent は source-code implementation の downstream handoff metadata を返す
  - test implementation agent は implementation diff と test plan に基づいて test code / fixture / helper の変更提案を返す
  - fixer は unresolved question の resolved / deferred / unresolved 状態を fix report に反映する
  - documentation agent は blocked-state handling、escalation actions、budget-pressure guidance、artifact-volume guidance を runbook に反映する

## Validation Status
- full test suite: `291 passed`
- docs-driven slices は複数回の並列実行で検証済み
- failure-recovery E2E、session rotation stability、acceptance gating、operator-facing summaries、approval visibility、environment assumptions の回帰テストを追加済み

## Out of Scope
- Web UI
- 複数リポジトリ同時対応
- 高度な分散スケジューリング
- 複雑なコスト最適化
- 高度な履歴検索

## Persistent Context Policy
- persistent context は `artifacts/workflow-state.json`、`artifacts/sessions/<session_id>/session-snapshot.json`、`artifacts/summaries/<workflow_id>/run-summary.json` に保存する。
- 復元粒度は workflow 単位と session 単位を基本とし、最低限 `requirement`、`phase`、`workflow_id`、`session_id`、完了済みタスク、未完了タスク、直近の要約、resume prompt を保証対象にする。
- エージェントごとの一時的な推論全文やトークン列は保証対象に含めず、再開に必要な構造化状態のみを永続化する。
- 永続化データが欠落している場合は、最後に整合している checkpoint まで戻して再開する。

## Approval Policy
- 破壊的変更はデフォルトで自動承認しない。
- `src/impliforge/` 配下の allowlisted source edit は構造化 edit proposal と approval hook を通した場合のみ許可する。
- delete 操作、広範囲 overwrite、依存追加、実行環境変更は human approval を必須とする。
- `docs/` と `artifacts/` への生成物保存は通常運用として許可するが、protected roots は常に対象外とする。

## Resolved Decisions
- persistent context は `artifacts/workflow-state.json`、`artifacts/sessions/<session_id>/session-snapshot.json`、`artifacts/summaries/<workflow_id>/run-summary.json` に保存する。
- 復元粒度は workflow/session 単位とし、`requirement`、`phase`、`workflow_id`、`session_id`、完了済みタスク、未完了タスク、直近要約、resume prompt を保証対象にする。
- delete 操作、広範囲 overwrite、依存追加、実行環境変更は human approval 必須とする。
- `main.py` の `SkeletonOrchestrator` は phase の並びと依存注入を主責務とし、成果物永続化は `orchestration/artifact_writer.py`、safe edit / structured code edit は `orchestration/edit_phase.py` に委譲する。
- phase 実行の routing、Copilot request 構築、agent dispatch、result 適用は `_execute_phase` に共通化する。
- `orchestration/orchestrator.py` の minimal orchestrator は shared agent interfaces と canonical workflow state を使う。
- acceptance gate は unresolved open questions、deferred open questions、blocked work、completion evidence を operator-facing artifact に反映する。
- fix loop 後の rerun 結果は final artifact persistence と safe edit phase に引き継ぐ。
