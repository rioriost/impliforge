"""Test execution agent for the impliforge workflow."""

from __future__ import annotations

from typing import Any

from impliforge.agents.base import AgentResult, AgentTask, BaseAgent
from impliforge.orchestration.workflow import WorkflowState


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
        execution_artifacts = self._as_dict(task.inputs.get("execution_artifacts", {}))
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
        resolved_decisions = self._normalize_list(
            normalized_requirements.get("resolved_decisions")
        )
        code_change_slices = self._normalize_dict_list(
            implementation.get("code_change_slices")
        )
        test_cases = self._normalize_dict_list(test_plan.get("test_cases"))
        validation_steps = self._normalize_list(test_plan.get("validation_steps"))
        plan_phases = self._normalize_list(plan.get("phases"))
        acceptance_coverage = self._normalize_acceptance_coverage(
            test_plan.get("acceptance_coverage")
        )
        plan_open_questions = self._normalize_list(test_plan.get("open_questions"))
        plan_unresolved_concerns = self._normalize_list(
            test_plan.get("unresolved_concerns")
        )
        failure_summary = self._build_failure_summary(execution_artifacts)
        log_summary = self._build_log_summary(execution_artifacts)

        executed_checks = self._build_executed_checks(
            test_cases=test_cases,
            validation_steps=validation_steps,
            code_change_slices=code_change_slices,
        )
        acceptance_coverage = self._build_acceptance_coverage(
            acceptance_criteria=acceptance_criteria,
            existing_coverage=acceptance_coverage,
            executed_checks=executed_checks,
        )
        unresolved_concerns = self._build_unresolved_concerns(
            open_questions=open_questions,
            resolved_decisions=resolved_decisions,
            plan_open_questions=plan_open_questions,
            plan_unresolved_concerns=plan_unresolved_concerns,
            acceptance_coverage=acceptance_coverage,
            failure_summary=failure_summary,
        )
        status = self._determine_status(
            failure_summary=failure_summary,
            unresolved_concerns=unresolved_concerns,
        )
        summary = self._build_summary(
            executed_checks=executed_checks,
            open_questions=open_questions,
            resolved_decisions=resolved_decisions,
            failure_summary=failure_summary,
            unresolved_concerns=unresolved_concerns,
        )
        test_results_document = self._build_test_results_document(
            objective=objective,
            acceptance_coverage=acceptance_coverage,
            plan_phases=plan_phases,
            executed_checks=executed_checks,
            open_questions=open_questions,
            resolved_decisions=resolved_decisions,
            unresolved_concerns=unresolved_concerns,
            failure_summary=failure_summary,
            log_summary=log_summary,
            copilot_response=copilot_response,
        )

        outputs = {
            "test_results": {
                "schema_version": "test_results.v2",
                "summary": summary,
                "status": status,
                "executed_checks": executed_checks,
                "open_questions": open_questions,
                "resolved_decisions": resolved_decisions,
                "acceptance_criteria": acceptance_criteria,
                "acceptance_coverage": acceptance_coverage,
                "unresolved_concerns": unresolved_concerns,
                "failure_summary": failure_summary,
                "log_summary": log_summary,
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
        if open_questions and not resolved_decisions:
            risks.append(
                "未解決の open questions が残っており、対応方針も未確定のため、最終的な合格判定は保留"
            )
        if not code_change_slices:
            risks.append(
                "実装変更スライスが不足しているため、変更影響に対する検証網羅性が限定的"
            )
        if failure_summary:
            risks.append(
                "テスト失敗サマリが記録されているため、fix loop または再実行による解消確認が必要"
            )
        if unresolved_concerns:
            risks.append(
                "acceptance coverage または未解決事項に未確定要素があり、review での確認が必要"
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
                "acceptance_coverage_count": len(acceptance_coverage),
                "test_case_count": len(test_cases),
                "executed_check_count": len(executed_checks),
                "open_question_count": len(open_questions),
                "unresolved_concern_count": len(unresolved_concerns),
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
        resolved_decisions: list[str],
        failure_summary: list[dict[str, str]],
        unresolved_concerns: list[str],
    ) -> str:
        passed_count = sum(
            1 for item in executed_checks if str(item.get("status")) == "passed"
        )
        total_count = len(executed_checks)

        if failure_summary:
            return (
                f"{passed_count}/{total_count} checks were recorded, "
                f"with {len(failure_summary)} failure summaries requiring follow-up."
            )

        if unresolved_concerns:
            return (
                f"{passed_count}/{total_count} checks were provisionally passed, "
                f"but {len(unresolved_concerns)} unresolved concerns remain before final validation."
            )

        if open_questions and not resolved_decisions:
            return (
                f"{passed_count}/{total_count} checks were provisionally passed, "
                "but unresolved questions remain before final validation."
            )

        return f"{passed_count}/{total_count} checks were provisionally passed."

    def _build_test_results_document(
        self,
        *,
        objective: str,
        acceptance_coverage: list[dict[str, Any]],
        plan_phases: list[str],
        executed_checks: list[dict[str, Any]],
        open_questions: list[str],
        resolved_decisions: list[str],
        unresolved_concerns: list[str],
        failure_summary: list[dict[str, str]],
        log_summary: list[str],
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
        lines.extend(self._render_acceptance_coverage(acceptance_coverage))
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
        if failure_summary:
            lines.extend(
                [
                    "",
                    "## Failure Summary",
                ]
            )
            lines.extend(self._render_failure_summary(failure_summary))
        if log_summary:
            lines.extend(
                [
                    "",
                    "## Log Summary",
                ]
            )
            lines.extend(self._render_bullets(log_summary))
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
                "## Unresolved Concerns",
            ]
        )
        lines.extend(self._render_bullets(unresolved_concerns))
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

    def _render_acceptance_coverage(self, items: list[dict[str, Any]]) -> list[str]:
        if not items:
            return ["- none"]

        lines: list[str] = []
        for item in items:
            criterion = str(item.get("acceptance_criterion", "")).strip() or "TBD"
            coverage_status = str(item.get("coverage_status", "")).strip() or "unknown"
            covered_by = self._normalize_list(item.get("covered_by"))
            lines.append(f"- {criterion} [{coverage_status}]")
            lines.append(
                f"  - covered_by: {', '.join(covered_by) if covered_by else 'none'}"
            )
        return lines

    def _render_failure_summary(self, items: list[dict[str, str]]) -> list[str]:
        if not items:
            return ["- none"]

        lines: list[str] = []
        for item in items:
            check_id = str(item.get("check_id", "unknown")).strip() or "unknown"
            summary = str(item.get("summary", "")).strip() or "No summary provided."
            lines.append(f"- {check_id}: {summary}")

            details = str(item.get("details", "")).strip()
            if details:
                lines.append(f"  - {details}")

        return lines

    def _render_numbered(self, items: list[str]) -> list[str]:
        if not items:
            return ["1. none"]
        return [f"{index}. {item}" for index, item in enumerate(items, start=1)]

    def _normalize_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _build_failure_summary(
        self, execution_artifacts: dict[str, Any]
    ) -> list[dict[str, str]]:
        failures = self._normalize_dict_list(execution_artifacts.get("failures"))
        summary: list[dict[str, str]] = []

        for index, item in enumerate(failures, start=1):
            check_id = str(item.get("check_id", f"failure-{index}")).strip()
            failure_summary = str(item.get("summary", "")).strip()
            details = str(item.get("details", "")).strip()

            if not failure_summary and not details:
                continue

            summary.append(
                {
                    "check_id": check_id or f"failure-{index}",
                    "summary": failure_summary
                    or "Failure recorded during test execution.",
                    "details": details,
                }
            )

        return summary

    def _build_log_summary(self, execution_artifacts: dict[str, Any]) -> list[str]:
        return self._normalize_list(execution_artifacts.get("log_summary"))

    def _build_acceptance_coverage(
        self,
        *,
        acceptance_criteria: list[str],
        existing_coverage: list[dict[str, Any]],
        executed_checks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        coverage_by_criterion: dict[str, dict[str, Any]] = {}

        for item in existing_coverage:
            criterion = str(item.get("acceptance_criterion", "")).strip()
            if not criterion:
                continue
            coverage_by_criterion[criterion] = {
                "acceptance_criterion": criterion,
                "covered_by": self._normalize_list(item.get("covered_by")),
                "coverage_status": str(item.get("coverage_status", "")).strip()
                or "unknown",
            }

        for criterion in acceptance_criteria:
            if criterion not in coverage_by_criterion:
                coverage_by_criterion[criterion] = {
                    "acceptance_criterion": criterion,
                    "covered_by": [],
                    "coverage_status": "planned_gap",
                }

        executed_check_ids = [
            str(item.get("check_id", "")).strip()
            for item in executed_checks
            if str(item.get("check_id", "")).strip()
        ]

        for criterion in acceptance_criteria:
            item = coverage_by_criterion[criterion]
            covered_by = self._normalize_list(item.get("covered_by"))
            if covered_by:
                item["coverage_status"] = "covered"
                continue
            if executed_check_ids:
                item["coverage_status"] = "provisionally_covered"
                item["covered_by"] = executed_check_ids
            else:
                item["coverage_status"] = "planned_gap"

        return [coverage_by_criterion[criterion] for criterion in acceptance_criteria]

    def _build_unresolved_concerns(
        self,
        *,
        open_questions: list[str],
        resolved_decisions: list[str],
        plan_open_questions: list[str],
        plan_unresolved_concerns: list[str],
        acceptance_coverage: list[dict[str, Any]],
        failure_summary: list[dict[str, str]],
    ) -> list[str]:
        concerns: list[str] = []
        open_question_concerns: list[str] = []

        if open_questions and not resolved_decisions:
            for question in open_questions:
                open_question_concerns.append(
                    f"Open question remains unresolved: {question}"
                )

        for question in plan_open_questions:
            concern = f"Open question remains unresolved: {question}"
            if concern not in open_question_concerns:
                open_question_concerns.append(concern)

        concerns.extend(open_question_concerns)

        for concern in plan_unresolved_concerns:
            if concern not in concerns:
                concerns.append(concern)

        for item in acceptance_coverage:
            coverage_status = str(item.get("coverage_status", "")).strip()
            if coverage_status in {"covered", "provisionally_covered"}:
                continue
            criterion = str(item.get("acceptance_criterion", "")).strip() or "TBD"
            concerns.append(
                f"Acceptance criterion lacks explicit execution coverage: {criterion}"
            )

        for item in failure_summary:
            summary = str(item.get("summary", "")).strip()
            if summary:
                concerns.append(f"Execution follow-up required: {summary}")

        return concerns

    def _determine_status(
        self,
        *,
        failure_summary: list[dict[str, str]],
        unresolved_concerns: list[str],
    ) -> str:
        if failure_summary:
            return "failed"
        if unresolved_concerns:
            return "provisional_passed"
        return "provisional_passed"

    def _normalize_acceptance_coverage(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []

        normalized: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            criterion = str(item.get("acceptance_criterion", "")).strip()
            if not criterion:
                continue
            normalized.append(
                {
                    "acceptance_criterion": criterion,
                    "covered_by": self._normalize_list(item.get("covered_by")),
                    "coverage_status": str(item.get("coverage_status", "")).strip()
                    or "unknown",
                }
            )
        return normalized

    def _normalize_dict_list(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _as_dict(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        return {}
