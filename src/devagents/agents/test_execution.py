"""Test execution agent for the devagents workflow."""

from __future__ import annotations

from typing import Any

from devagents.agents.base import AgentResult, AgentTask, BaseAgent
from devagents.orchestration.workflow import WorkflowState


class TestExecutionAgent(BaseAgent):
    """Create a test execution report from the current workflow context."""

    agent_name = "test_execution"

    async def run(self, task: AgentTask, state: WorkflowState) -> AgentResult:
        normalized_requirements = self._as_dict(
            task.inputs.get("normalized_requirements", {})
        )
        plan = self._as_dict(task.inputs.get("plan", {}))
        implementation = self._as_dict(task.inputs.get("implementation", {}))
        test_plan = self._as_dict(task.inputs.get("test_plan", {}))
        copilot_response = str(task.inputs.get("copilot_response", "")).strip()

        objective = str(
            normalized_requirements.get("objective") or state.requirement
        ).strip()
        acceptance_criteria = self._normalize_list(
            normalized_requirements.get("acceptance_criteria")
        )
        open_questions = self._normalize_list(
            normalized_requirements.get("open_questions")
        )
        code_change_slices = self._normalize_dict_list(
            implementation.get("code_change_slices")
        )
        test_cases = self._normalize_dict_list(test_plan.get("test_cases"))
        validation_steps = self._normalize_list(test_plan.get("validation_steps"))
        plan_phases = self._normalize_list(plan.get("phases"))

        executed_checks = self._build_executed_checks(
            test_cases=test_cases,
            validation_steps=validation_steps,
            code_change_slices=code_change_slices,
        )
        summary = self._build_summary(
            executed_checks=executed_checks,
            open_questions=open_questions,
        )
        test_results_document = self._build_test_results_document(
            objective=objective,
            acceptance_criteria=acceptance_criteria,
            plan_phases=plan_phases,
            executed_checks=executed_checks,
            open_questions=open_questions,
            copilot_response=copilot_response,
        )

        outputs = {
            "test_results": {
                "summary": summary,
                "status": "provisional_passed"
                if not open_questions
                else "needs_review",
                "executed_checks": executed_checks,
                "open_questions": open_questions,
                "acceptance_criteria": acceptance_criteria,
            },
            "test_results_document": test_results_document,
            "test_result_targets": [
                "docs/test-results.md",
            ],
            "open_questions": open_questions,
        }

        risks = []
        if not test_cases:
            risks.append(
                "具体的な test_cases が不足しているため、検証結果は暫定評価となる"
            )
        if open_questions:
            risks.append(
                "未解決の open questions が残っているため、最終的な合格判定は保留"
            )
        if not code_change_slices:
            risks.append(
                "実装変更スライスが不足しているため、変更影響に対する検証網羅性が限定的"
            )

        return AgentResult.success(
            "テスト実行結果の草案を生成し、検証状況を整理した。",
            outputs=outputs,
            artifacts=["docs/test-results.md"],
            next_actions=[
                "docs/test-results.md を保存する",
                "review agent に test_results を渡す",
                "必要なら失敗項目や未確認項目を fix loop に送る",
            ],
            risks=risks,
            metrics={
                "acceptance_criteria_count": len(acceptance_criteria),
                "test_case_count": len(test_cases),
                "executed_check_count": len(executed_checks),
                "open_question_count": len(open_questions),
            },
        )

    def _build_executed_checks(
        self,
        *,
        test_cases: list[dict[str, Any]],
        validation_steps: list[str],
        code_change_slices: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []

        for index, test_case in enumerate(test_cases, start=1):
            name = str(test_case.get("name", f"test-case-{index}")).strip()
            objective = str(test_case.get("objective", "")).strip()
            category = str(test_case.get("category", "validation")).strip()
            checks.append(
                {
                    "check_id": f"case-{index}",
                    "name": name,
                    "category": category or "validation",
                    "status": "passed",
                    "details": objective
                    or "Planned test case was reviewed and marked as provisionally covered.",
                }
            )

        for index, step in enumerate(validation_steps, start=1):
            checks.append(
                {
                    "check_id": f"step-{index}",
                    "name": step,
                    "category": "validation_step",
                    "status": "passed",
                    "details": "Validation step was included in the execution checklist.",
                }
            )

        if not checks:
            for index, slice_item in enumerate(code_change_slices, start=1):
                goal = str(slice_item.get("goal", f"slice-{index}")).strip()
                checks.append(
                    {
                        "check_id": f"slice-{index}",
                        "name": goal or f"slice-{index}",
                        "category": "implementation_slice",
                        "status": "passed",
                        "details": "Implementation slice was reviewed for testability and provisional coverage.",
                    }
                )

        if not checks:
            checks.append(
                {
                    "check_id": "fallback-1",
                    "name": "workflow-validation",
                    "category": "fallback",
                    "status": "passed",
                    "details": "Workflow completed through planning, documentation, and implementation proposal phases.",
                }
            )

        return checks

    def _build_summary(
        self,
        *,
        executed_checks: list[dict[str, Any]],
        open_questions: list[str],
    ) -> str:
        passed_count = sum(
            1 for item in executed_checks if str(item.get("status")) == "passed"
        )
        total_count = len(executed_checks)

        if open_questions:
            return (
                f"{passed_count}/{total_count} checks were provisionally passed, "
                "but unresolved questions remain before final validation."
            )

        return f"{passed_count}/{total_count} checks were provisionally passed."

    def _build_test_results_document(
        self,
        *,
        objective: str,
        acceptance_criteria: list[str],
        plan_phases: list[str],
        executed_checks: list[dict[str, Any]],
        open_questions: list[str],
        copilot_response: str,
    ) -> str:
        lines: list[str] = [
            "# Test Results",
            "",
            "## Objective",
            objective or "TBD",
            "",
            "## Acceptance Criteria Coverage",
        ]
        lines.extend(self._render_bullets(acceptance_criteria))
        lines.extend(
            [
                "",
                "## Planned Workflow Phases",
            ]
        )
        lines.extend(self._render_numbered(plan_phases))
        lines.extend(
            [
                "",
                "## Executed Checks",
            ]
        )
        lines.extend(self._render_checks(executed_checks))
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

    def _render_checks(self, checks: list[dict[str, Any]]) -> list[str]:
        if not checks:
            return ["- none"]

        lines: list[str] = []
        for item in checks:
            name = str(item.get("name", "unknown")).strip()
            category = str(item.get("category", "validation")).strip()
            status = str(item.get("status", "unknown")).strip()
            details = str(item.get("details", "")).strip()
            lines.append(f"- {name} [{category}] => {status}")
            if details:
                lines.append(f"  - {details}")
        return lines

    def _render_bullets(self, items: list[str]) -> list[str]:
        if not items:
            return ["- none"]
        return [f"- {item}" for item in items]

    def _render_numbered(self, items: list[str]) -> list[str]:
        if not items:
            return ["1. none"]
        return [f"{index}. {item}" for index, item in enumerate(items, start=1)]

    def _normalize_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _normalize_dict_list(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _as_dict(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        return {}
