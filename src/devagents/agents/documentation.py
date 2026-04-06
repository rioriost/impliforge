"""Documentation generation agent for the devagents workflow."""

from __future__ import annotations

from typing import Any

from devagents.agents.base import AgentResult, AgentTask, BaseAgent
from devagents.orchestration.workflow import WorkflowState


class DocumentationAgent(BaseAgent):
    """Generate design-oriented documentation artifacts from workflow context."""

    agent_name = "documentation"

    async def run(self, task: AgentTask, state: WorkflowState) -> AgentResult:
        normalized_requirements = self._as_dict(
            task.inputs.get("normalized_requirements", {})
        )
        plan = self._as_dict(task.inputs.get("plan", {}))
        copilot_response = str(task.inputs.get("copilot_response", "")).strip()

        objective = str(
            normalized_requirements.get("objective", state.requirement)
        ).strip()
        constraints = self._normalize_list(normalized_requirements.get("constraints"))
        acceptance_criteria = self._normalize_list(
            normalized_requirements.get("acceptance_criteria")
        )
        open_questions = self._normalize_list(
            normalized_requirements.get("open_questions")
        )
        resolved_decisions = self._normalize_list(
            normalized_requirements.get("resolved_decisions")
        )
        inferred_capabilities = self._normalize_list(
            normalized_requirements.get("inferred_capabilities")
        )
        out_of_scope = self._normalize_list(normalized_requirements.get("out_of_scope"))
        phases = self._normalize_list(plan.get("phases"))
        deliverables = self._normalize_list(plan.get("deliverables"))
        task_breakdown = self._normalize_task_breakdown(plan.get("task_breakdown"))

        design_document = self._build_design_document(
            objective=objective,
            constraints=constraints,
            acceptance_criteria=acceptance_criteria,
            open_questions=open_questions,
            resolved_decisions=resolved_decisions,
            inferred_capabilities=inferred_capabilities,
            out_of_scope=out_of_scope,
            phases=phases,
            task_breakdown=task_breakdown,
            copilot_response=copilot_response,
        )

        runbook_document = self._build_runbook_document(
            objective=objective,
            deliverables=deliverables,
            phases=phases,
            open_questions=open_questions,
            resolved_decisions=resolved_decisions,
        )

        outputs = {
            "design_document": design_document,
            "runbook_document": runbook_document,
            "documentation_bundle": {
                "design": design_document,
                "runbook": runbook_document,
            },
            "documentation_targets": [
                "docs/design.md",
                "docs/runbook.md",
            ],
            "open_questions": open_questions,
            "resolved_decisions": resolved_decisions,
        }

        risks = []
        if open_questions and not resolved_decisions:
            risks.append("未解決の open questions があるため、設計文書は暫定版となる")
        if not phases:
            risks.append("計画フェーズ情報が不足しているため、運用手順の粒度が粗い")

        return AgentResult.success(
            "設計文書と運用向けドキュメントの草案を生成した。",
            outputs=outputs,
            artifacts=["docs/design.md", "docs/runbook.md"],
            next_actions=[
                "docs/design.md と docs/runbook.md を保存する",
                "implementation agent に設計文書を渡す",
            ],
            risks=risks,
            metrics={
                "constraint_count": len(constraints),
                "acceptance_criteria_count": len(acceptance_criteria),
                "open_question_count": len(open_questions),
                "resolved_decision_count": len(resolved_decisions),
                "task_breakdown_count": len(task_breakdown),
            },
        )

    def _build_design_document(
        self,
        *,
        objective: str,
        constraints: list[str],
        acceptance_criteria: list[str],
        open_questions: list[str],
        resolved_decisions: list[str],
        inferred_capabilities: list[str],
        out_of_scope: list[str],
        phases: list[str],
        task_breakdown: list[dict[str, Any]],
        copilot_response: str,
    ) -> str:
        lines: list[str] = [
            "# Design",
            "",
            "## Objective",
            objective or "TBD",
            "",
            "## Architecture Direction",
            "- Orchestrator-centric multi-agent workflow",
            "- GitHub Copilot SDK is isolated behind a client layer",
            "- Session continuity is handled through snapshot and resume flow",
            "- Model routing is selected per task kind",
            "",
            "## Constraints",
        ]

        lines.extend(self._render_bullets(constraints))
        lines.extend(
            [
                "",
                "## Acceptance Criteria",
            ]
        )
        lines.extend(self._render_bullets(acceptance_criteria))
        lines.extend(
            [
                "",
                "## Inferred Capabilities",
            ]
        )
        lines.extend(self._render_bullets(inferred_capabilities))
        lines.extend(
            [
                "",
                "## Planned Phases",
            ]
        )
        lines.extend(self._render_numbered(phases))
        lines.extend(
            [
                "",
                "## Task Breakdown",
            ]
        )
        lines.extend(self._render_task_breakdown(task_breakdown))
        lines.extend(
            [
                "",
                "## Out of Scope",
            ]
        )
        lines.extend(self._render_bullets(out_of_scope))
        lines.extend(
            [
                "",
                "## Persistent Context Policy",
                "- persistent context は `artifacts/workflow-state.json`、`artifacts/sessions/<session_id>/session-snapshot.json`、`artifacts/summaries/<workflow_id>/run-summary.json` に保存する。",
                "- 復元粒度は workflow 単位と session 単位を基本とし、最低限 `requirement`、`phase`、`workflow_id`、`session_id`、完了済みタスク、未完了タスク、直近の要約、resume prompt を保証対象にする。",
                "- エージェントごとの一時的な推論全文やトークン列は保証対象に含めず、再開に必要な構造化状態のみを永続化する。",
                "- 永続化データが欠落している場合は、最後に整合している checkpoint まで戻して再開する。",
                "",
                "## Approval Policy",
                "- 破壊的変更はデフォルトで自動承認しない。",
                "- `src/devagents/` 配下の allowlisted source edit は構造化 edit proposal と approval hook を通した場合のみ許可する。",
                "- delete 操作、広範囲 overwrite、依存追加、実行環境変更は human approval を必須とする。",
                "- `docs/` と `artifacts/` への生成物保存は通常運用として許可するが、protected roots は常に対象外とする。",
            ]
        )
        if resolved_decisions:
            lines.extend(
                [
                    "",
                    "## Resolved Decisions",
                ]
            )
            lines.extend(self._render_bullets(resolved_decisions))
        else:
            lines.extend(
                [
                    "",
                    "## Open Questions",
                ]
            )
            lines.extend(self._render_bullets(open_questions))
        lines.extend(
            [
                "",
                "## Copilot Draft Notes",
                copilot_response or "No additional Copilot draft content was provided.",
            ]
        )
        return "\n".join(lines).strip() + "\n"

    def _build_runbook_document(
        self,
        *,
        objective: str,
        deliverables: list[str],
        phases: list[str],
        open_questions: list[str],
        resolved_decisions: list[str],
    ) -> str:
        lines: list[str] = [
            "# Runbook",
            "",
            "## Goal",
            objective or "TBD",
            "",
            "## Expected Deliverables",
        ]
        lines.extend(self._render_bullets(deliverables))
        lines.extend(
            [
                "",
                "## Execution Flow",
            ]
        )
        lines.extend(self._render_numbered(phases))
        lines.extend(
            [
                "",
                "## Operator Checklist",
                "- Confirm requirement text is finalized",
                "- Confirm session snapshot and workflow state are persisted",
                "- Confirm generated docs are reviewed before implementation",
                "- Confirm unresolved questions are either answered or explicitly deferred",
                "- Confirm persistent context is stored in `artifacts/workflow-state.json`, `artifacts/sessions/<session_id>/session-snapshot.json`, and `artifacts/summaries/<workflow_id>/run-summary.json`",
                "- Confirm resume can recover `requirement`, `phase`, `workflow_id`, `session_id`, completed tasks, pending tasks, latest summary, and resume prompt",
                "- Confirm destructive changes, dependency additions, and environment changes are not auto-approved",
                "",
                "## Persistence Policy",
                "- Persist workflow-level state in `artifacts/workflow-state.json`",
                "- Persist session-level resume state in `artifacts/sessions/<session_id>/session-snapshot.json`",
                "- Persist operator-facing execution summary in `artifacts/summaries/<workflow_id>/run-summary.json`",
                "- Guarantee structured recovery data only; transient model reasoning and raw token streams are out of scope",
                "- If persisted state is incomplete, resume from the latest consistent checkpoint instead of guessing missing context",
                "",
                "## Approval Policy",
                "- Allow routine generated writes under `docs/` and `artifacts/`",
                "- Allow source edits under `src/devagents/` only when they pass the structured edit path and approval checks",
                "- Require human approval for delete operations, broad overwrites, dependency additions, and execution-environment changes",
                "- Never allow edits under protected roots",
                "",
                "## Escalation Conditions",
            ]
        )

        if open_questions and not resolved_decisions:
            lines.extend(
                [
                    "- Open questions remain unresolved before implementation starts",
                    "- Design assumptions conflict with repository constraints",
                    "- Session restore data is incomplete or inconsistent",
                ]
            )
        else:
            lines.extend(
                [
                    "- Generated implementation plan conflicts with repository constraints",
                    "- Session restore data is incomplete or inconsistent",
                    "- A requested change requires destructive modification or dependency addition without explicit approval",
                ]
            )

        return "\n".join(lines).strip() + "\n"

    def _render_bullets(self, items: list[str]) -> list[str]:
        if not items:
            return ["- none"]
        return [f"- {item}" for item in items]

    def _render_numbered(self, items: list[str]) -> list[str]:
        if not items:
            return ["1. none"]
        return [f"{index}. {item}" for index, item in enumerate(items, start=1)]

    def _render_task_breakdown(self, tasks: list[dict[str, Any]]) -> list[str]:
        if not tasks:
            return ["- none"]

        lines: list[str] = []
        for task in tasks:
            task_id = str(task.get("task_id", "unknown")).strip()
            objective = str(task.get("objective", "")).strip()
            depends_on = self._normalize_list(task.get("depends_on"))
            dependency_text = ", ".join(depends_on) if depends_on else "none"
            lines.append(f"- `{task_id}`: {objective or 'TBD'}")
            lines.append(f"  - depends_on: {dependency_text}")
        return lines

    def _normalize_task_breakdown(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                normalized.append(item)
        return normalized

    def _normalize_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _as_dict(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        return {}


# SAFE-EDIT-NOTE
# Proposed implementation slice: Add a documentation agent that produces design and runbook artifacts.

# SAFE-EDIT-FIX-NOTE
# Proposed fix slice: 未解決の open questions が残っているため、実装前に確認が必要。

# SAFE-EDIT-FIX-NOTE
# Proposed fix slice: テスト結果が `needs_review` のため、追加確認または修正が必要。
