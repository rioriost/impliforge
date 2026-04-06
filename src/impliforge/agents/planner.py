"""Planning agent for the impliforge workflow."""

from __future__ import annotations

from typing import Any

from impliforge.agents.base import AgentResult, AgentTask, BaseAgent
from impliforge.orchestration.workflow import WorkflowState


class PlanningAgent(BaseAgent):
    """Create an initial implementation plan from normalized requirements."""

    agent_name = "planner"

    async def run(self, task: AgentTask, state: WorkflowState) -> AgentResult:
        normalized = self._get_normalized_requirements(task)
        objective = str(normalized.get("objective", state.requirement)).strip()
        objective_length = len(objective)
        long_objective_threshold = 4000
        long_objective_detected = objective_length >= long_objective_threshold

        constraints = self._normalize_list(normalized.get("constraints"))
        acceptance_criteria = self._normalize_list(
            normalized.get("acceptance_criteria")
        )
        open_questions = self._normalize_list(normalized.get("open_questions"))

        resolved_decisions = self._normalize_list(normalized.get("resolved_decisions"))
        inferred_capabilities = self._normalize_list(
            normalized.get("inferred_capabilities")
        )
        out_of_scope = self._normalize_list(normalized.get("out_of_scope"))

        plan = {
            "goal": objective,
            "phases": [
                "Define workflow state and agent interfaces",
                "Implement orchestrator and CLI entrypoint",
                "Add session persistence and model routing",
                "Add implementation, test, and review agents",
            ],
            "deliverables": [
                "docs/implementation-plan.md",
                "artifacts/workflow-state.json",
                "artifacts/run-summary.json",
            ],
            "constraints": constraints,
            "acceptance_criteria": acceptance_criteria,
            "open_questions": open_questions,
            "resolved_decisions": resolved_decisions,
            "inferred_capabilities": inferred_capabilities,
            "out_of_scope": out_of_scope,
            "task_breakdown": [
                {
                    "task_id": "requirements_analysis",
                    "objective": "Normalize the incoming requirement and extract constraints.",
                    "depends_on": [],
                },
                {
                    "task_id": "planning",
                    "objective": "Create an implementation plan and task breakdown.",
                    "depends_on": ["requirements_analysis"],
                },
                {
                    "task_id": "documentation",
                    "objective": "Generate or update design and workflow documentation.",
                    "depends_on": ["planning"],
                },
                {
                    "task_id": "implementation",
                    "objective": "Implement the required code changes.",
                    "depends_on": ["planning"],
                },
                {
                    "task_id": "test_design",
                    "objective": "Define test cases and validation strategy.",
                    "depends_on": ["planning"],
                },
                {
                    "task_id": "test_execution",
                    "objective": "Run tests and collect validation results.",
                    "depends_on": ["implementation", "test_design"],
                },
                {
                    "task_id": "review",
                    "objective": "Review implementation quality, risks, and acceptance coverage.",
                    "depends_on": ["implementation", "test_execution"],
                },
                {
                    "task_id": "finalization",
                    "objective": "Prepare final summary and completion artifacts.",
                    "depends_on": ["documentation", "review"],
                },
            ],
            "next_actions": [
                "Persist the workflow state and run summary",
                "Implement concrete Copilot SDK-backed agents",
                "Add session rotation and persistence",
            ],
        }

        risks = [
            "実エージェント追加前は最小フローのみ実行可能",
        ]
        if open_questions:
            risks.append(
                "未解決の open questions が残っているため、後続実装で確認が必要"
            )

        return AgentResult.success(
            "最小実装向けの実行計画を作成した。",
            outputs={
                "plan": plan,
                "open_questions": open_questions,
            },
            next_actions=plan["next_actions"],
            risks=risks,
            metrics={
                "constraint_count": len(constraints),
                "acceptance_criteria_count": len(acceptance_criteria),
                "open_question_count": len(open_questions),
                "resolved_decision_count": len(resolved_decisions),
                "inferred_capability_count": len(inferred_capabilities),
                "out_of_scope_count": len(out_of_scope),
                "task_count": len(plan["task_breakdown"]),
                "objective_length": objective_length,
                "long_objective_detected": long_objective_detected,
                "long_objective_threshold": long_objective_threshold,
            },
        )

    def _get_normalized_requirements(self, task: AgentTask) -> dict[str, Any]:
        value = task.inputs.get("normalized_requirements", {})
        if isinstance(value, dict):
            return value
        return {}

    def _normalize_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]
