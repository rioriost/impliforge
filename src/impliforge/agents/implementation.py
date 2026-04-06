"""Implementation proposal agent for the impliforge workflow."""

from __future__ import annotations

from typing import Any

from impliforge.agents.base import AgentResult, AgentTask, BaseAgent
from impliforge.orchestration.workflow import WorkflowState


class ImplementationAgent(BaseAgent):
    """Create an implementation proposal from the current plan and requirements."""

    agent_name = "implementation"

    async def run(self, task: AgentTask, state: WorkflowState) -> AgentResult:
        # BEGIN STRUCTURED EDIT: ImplementationAgent.run
        normalized_requirements = self._as_dict(
            task.inputs.get("normalized_requirements", {})
        )
        plan = self._as_dict(task.inputs.get("plan", {}))
        copilot_response = str(task.inputs.get("copilot_response", "")).strip()

        objective = str(
            normalized_requirements.get("objective") or state.requirement
        ).strip()
        constraints = self._normalize_list(normalized_requirements.get("constraints"))
        acceptance_criteria = self._normalize_list(
            normalized_requirements.get("acceptance_criteria")
        )
        open_questions = self._normalize_list(
            normalized_requirements.get("open_questions")
        )
        plan_phases = self._normalize_list(plan.get("phases"))
        task_breakdown = self._normalize_task_breakdown(plan.get("task_breakdown"))

        implementation = {
            "objective": objective,
            "summary": "実装フェーズで着手すべき変更案を整理した。",
            "strategy": [
                "Keep changes small and align with the existing repository structure",
                "Isolate Copilot SDK integration behind runtime/copilot_client.py",
                "Persist workflow and session state before and after meaningful milestones",
                "Prefer explicit workflow state transitions over implicit behavior",
                "Prefer structured code edits over free-form append-only source mutations",
            ],
            "proposed_modules": [
                {
                    "path": "src/impliforge/agents/implementation.py",
                    "purpose": "Generate implementation proposals and concrete code-change slices.",
                },
                {
                    "path": "src/impliforge/agents/documentation.py",
                    "purpose": "Generate design and operational documentation artifacts.",
                },
                {
                    "path": "src/impliforge/runtime/copilot_client.py",
                    "purpose": "Encapsulate Copilot SDK session lifecycle and request execution.",
                },
                {
                    "path": "src/impliforge/orchestration/session_manager.py",
                    "purpose": "Manage session rotation, snapshots, and resume prompts.",
                },
                {
                    "path": "src/impliforge/orchestration/state_store.py",
                    "purpose": "Persist workflow state, summaries, and session snapshots.",
                },
                {
                    "path": "src/impliforge/runtime/editor.py",
                    "purpose": "Apply allowlisted edits safely to docs, artifacts, and approved source files.",
                },
            ],
            "code_change_slices": [
                {
                    "slice_id": "implementation-agent",
                    "goal": "Add an implementation agent that turns plans into executable change proposals.",
                    "targets": [
                        "src/impliforge/agents/implementation.py",
                    ],
                    "depends_on": [
                        "planning",
                    ],
                },
                {
                    "slice_id": "documentation-agent",
                    "goal": "Add a documentation agent that produces design and runbook artifacts.",
                    "targets": [
                        "src/impliforge/agents/documentation.py",
                    ],
                    "depends_on": [
                        "planning",
                    ],
                },
                {
                    "slice_id": "orchestrator-integration",
                    "goal": "Wire documentation and implementation phases into the orchestrator.",
                    "targets": [
                        "src/impliforge/main.py",
                    ],
                    "depends_on": [
                        "implementation-agent",
                        "documentation-agent",
                    ],
                },
                {
                    "slice_id": "artifact-persistence",
                    "goal": "Persist implementation and documentation outputs into docs/ and artifacts/.",
                    "targets": [
                        "docs/design.md",
                        "artifacts/workflows/<workflow_id>/workflow-details.json",
                        "artifacts/summaries/<workflow_id>/run-summary.json",
                    ],
                    "depends_on": [
                        "orchestrator-integration",
                    ],
                },
                {
                    "slice_id": "src-allowlisted-edit-phase",
                    "goal": "Promote approved implementation proposals into structured source edits under src/impliforge/.",
                    "targets": [
                        "src/impliforge/main.py",
                        "src/impliforge/runtime/editor.py",
                        "src/impliforge/agents/implementation.py",
                    ],
                    "depends_on": [
                        "orchestrator-integration",
                        "artifact-persistence",
                    ],
                },
            ],
            "deliverables": [
                "docs/design.md",
                "docs/final-summary.md",
                "artifacts/workflows/<workflow_id>/workflow-details.json",
                "artifacts/summaries/<workflow_id>/run-summary.json",
                "src/impliforge/**/*.py allowlisted edit proposals",
            ],
            "acceptance_criteria": acceptance_criteria,
            "constraints": constraints,
            "plan_phases": plan_phases,
            "task_breakdown": task_breakdown,
            "open_questions": open_questions,
            "copilot_response_excerpt": copilot_response[:500]
            if copilot_response
            else "",
            "downstream_handoff": {
                "consumers": [
                    {
                        "phase": "test_design",
                        "inputs": [
                            "implementation.code_change_slices",
                            "implementation.deliverables",
                            "implementation.acceptance_criteria",
                            "implementation.open_questions",
                        ],
                        "purpose": "Generate validation scenarios for proposed change slices and delivery artifacts.",
                    },
                    {
                        "phase": "test_execution",
                        "inputs": [
                            "implementation.code_change_slices",
                            "implementation.edit_proposals",
                            "implementation.constraints",
                        ],
                        "purpose": "Validate executable proposal readiness and confirm proposed targets remain testable.",
                    },
                    {
                        "phase": "review",
                        "inputs": [
                            "implementation.strategy",
                            "implementation.code_change_slices",
                            "implementation.edit_proposals",
                            "implementation.open_questions",
                        ],
                        "purpose": "Assess proposal completeness, risk, and unresolved execution blockers before completion.",
                    },
                    {
                        "phase": "fixer",
                        "inputs": [
                            "implementation.code_change_slices",
                            "implementation.edit_proposals",
                            "implementation.open_questions",
                        ],
                        "purpose": "Reuse implementation proposal structure when generating focused fix slices and revalidation steps.",
                    },
                ],
                "executable_change_proposal_ready": True,
            },
            "edit_proposals": [
                {
                    "proposal_id": "src-structured-main-update",
                    "mode": "structured_update",
                    "targets": [
                        "src/impliforge/main.py",
                    ],
                    "summary": "Wire implementation outputs into the orchestrator through a structured source edit path.",
                    "instructions": [
                        "Keep the change small and limited to orchestration flow integration.",
                        "Do not edit files outside src/impliforge/ without an explicit policy update.",
                        "Re-run test_execution and review after applying the source edit.",
                    ],
                    "edits": [
                        {
                            "edit_kind": "replace_block",
                            "target_symbol": "SkeletonOrchestrator._build_safe_edit_operations",
                            "intent": "Replace append-only SAFE-EDIT source mutations with structured source edit requests.",
                        },
                    ],
                },
                {
                    "proposal_id": "src-structured-editor-update",
                    "mode": "structured_update",
                    "targets": [
                        "src/impliforge/runtime/editor.py",
                    ],
                    "summary": "Extend the safe editor policy to support approved src/impliforge edits through structured updates.",
                    "instructions": [
                        "Restrict edits to src/impliforge/ and preserve protected roots.",
                        "Require approval for overwrite and delete operations.",
                        "Record edited files in workflow artifacts after the change.",
                    ],
                    "edits": [
                        {
                            "edit_kind": "replace_block",
                            "target_symbol": "SafeEditor.apply",
                            "intent": "Route approved source edits through structured update handling instead of append-only notes.",
                        },
                    ],
                },
                {
                    "proposal_id": "src-structured-implementation-update",
                    "mode": "structured_update",
                    "targets": [
                        "src/impliforge/agents/implementation.py",
                    ],
                    "summary": "Promote implementation proposals into structured code-edit payloads for approved source files.",
                    "instructions": [
                        "Emit structured edit payloads with explicit target symbols or blocks.",
                        "Avoid free-form append-only source mutations.",
                        "Keep each edit proposal scoped to one behavior change.",
                    ],
                    "edits": [
                        {
                            "edit_kind": "replace_block",
                            "target_symbol": "ImplementationAgent.run",
                            "intent": "Emit structured edit proposals that can be consumed by a code editing runtime.",
                        },
                    ],
                },
            ],
        }

        next_actions = [
            "Add documentation and implementation agents to the orchestrator",
            "Persist generated design and implementation proposal artifacts",
            "Extend the workflow into test_design, test_execution, and review phases",
            "Promote structured src/impliforge edit proposals into the safe edit phase",
        ]

        risks = [
            "実コード変更前に承認フローが未確定だと、破壊的変更の扱いが曖昧になる",
            "実装提案と既存アーキテクチャの整合確認が不足すると差分が広がる可能性がある",
        ]
        if open_questions:
            risks.append(
                "未解決の open questions が残っているため、実装着手前に確認が必要"
            )

        return AgentResult.success(
            "実装提案を生成し、次のコード変更スライスを整理した。",
            outputs={
                "implementation": implementation,
                "open_questions": open_questions,
            },
            next_actions=next_actions,
            risks=risks,
            metrics={
                "constraint_count": len(constraints),
                "acceptance_criteria_count": len(acceptance_criteria),
                "task_breakdown_count": len(task_breakdown),
                "code_change_slice_count": len(implementation["code_change_slices"]),
                "downstream_consumer_count": len(
                    implementation["downstream_handoff"]["consumers"]
                ),
                "open_question_count": len(open_questions),
            },
        )  # END STRUCTURED EDIT: ImplementationAgent.run

    def _as_dict(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        return {}

    def _normalize_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _normalize_task_breakdown(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []

        normalized: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            task_id = str(item.get("task_id", "")).strip()
            objective = str(item.get("objective", "")).strip()
            depends_on = self._normalize_list(item.get("depends_on"))
            if not task_id and not objective:
                continue
            normalized.append(
                {
                    "task_id": task_id,
                    "objective": objective,
                    "depends_on": depends_on,
                }
            )
        return normalized
