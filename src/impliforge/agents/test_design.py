"""Test design agent for the impliforge workflow."""

from __future__ import annotations

from typing import Any

from impliforge.agents.base import AgentResult, AgentTask, BaseAgent
from impliforge.orchestration.workflow import WorkflowState


class TestDesignAgent(BaseAgent):
    """Generate a test plan and validation scenarios from workflow context."""

    agent_name = "test_design"

    async def run(self, task: AgentTask, state: WorkflowState) -> AgentResult:
        normalized_requirements = self._as_dict(
            task.inputs.get("normalized_requirements", {})
        )
        plan = self._as_dict(task.inputs.get("plan", {}))
        implementation = self._as_dict(task.inputs.get("implementation", {}))
        documentation_bundle = self._as_dict(
            task.inputs.get("documentation_bundle", {})
        )
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
        task_breakdown = self._normalize_task_breakdown(plan.get("task_breakdown"))
        code_change_slices = self._normalize_code_change_slices(
            implementation.get("code_change_slices")
        )

        test_plan = {
            "objective": objective,
            "summary": "実装提案に対する検証観点とテスト計画を整理した。",
            "strategy": [
                "Validate acceptance criteria before expanding implementation scope",
                "Prefer focused tests with a single assertion theme per scenario",
                "Cover both happy path and failure path for orchestration flow",
                "Verify session persistence and model routing behavior explicitly",
            ],
            "test_levels": [
                {
                    "level": "unit",
                    "focus": "Agent output shaping, routing decisions, and state transitions",
                },
                {
                    "level": "integration",
                    "focus": "Orchestrator phase progression and artifact persistence",
                },
                {
                    "level": "end_to_end",
                    "focus": "Requirement intake through documentation and implementation proposal generation",
                },
            ],
            "acceptance_criteria": acceptance_criteria,
            "constraints": constraints,
            "task_breakdown": task_breakdown,
            "code_change_slices": code_change_slices,
            "test_cases": self._build_test_cases(
                acceptance_criteria=acceptance_criteria,
                code_change_slices=code_change_slices,
                open_questions=open_questions,
            ),
            "fixtures_and_data": [
                "Sample requirement file for a Copilot SDK multi-agent workflow",
                "Temporary artifacts directory for workflow-state and session snapshots",
                "Deterministic routing mode input such as quality/balanced/cost_saver",
                "Mocked or dry-run Copilot response payloads for repeatable validation",
            ],
            "environment_assumptions": [
                "Use `uv run` so execution uses the repository-managed Python environment",
                "Default execution does not require explicit Copilot SDK path overrides when environment paths are unset",
                "If `working_directory` or `config_dir` is configured, each path must already exist as a directory before SDK execution",
            ],
            "validation_commands": [
                "uv run python -m impliforge requirements/sample-requirement.md --routing-mode quality",
                "uv run python -m impliforge requirements/sample-requirement.md --token-usage-ratio 0.9",
            ],
            "operator_environment_signals": [
                "Record the selected routing mode in operator-facing outputs",
                "Record token usage ratio when available for degraded-routing visibility",
                "Surface configured environment path validation failures before SDK execution",
            ],
            "documentation_inputs": {
                "design_present": bool(documentation_bundle.get("design")),
                "runbook_present": bool(documentation_bundle.get("runbook")),
            },
            "open_questions": open_questions,
            "copilot_response_excerpt": copilot_response[:500]
            if copilot_response
            else "",
        }

        test_plan_document = self._build_test_plan_document(test_plan)

        risks = [
            "実テスト実行エージェント未接続のため、現時点では計画中心の検証に留まる",
        ]
        if open_questions:
            risks.append(
                "未解決の open questions があるため、一部テスト期待値が暫定になる"
            )

        return AgentResult.success(
            "テスト計画と検証シナリオを生成した。",
            outputs={
                "test_plan": test_plan,
                "test_plan_document": test_plan_document,
                "open_questions": open_questions,
            },
            artifacts=["docs/test-plan.md"],
            next_actions=[
                "docs/test-plan.md を保存する",
                "test_execution agent に test_plan を渡す",
                "review agent に検証観点を渡す",
            ],
            risks=risks,
            metrics={
                "acceptance_criteria_count": len(acceptance_criteria),
                "task_breakdown_count": len(task_breakdown),
                "code_change_slice_count": len(code_change_slices),
                "test_case_count": len(test_plan["test_cases"]),
                "open_question_count": len(open_questions),
            },
        )

    def _build_test_cases(
        self,
        *,
        acceptance_criteria: list[str],
        code_change_slices: list[dict[str, Any]],
        open_questions: list[str],
    ) -> list[dict[str, Any]]:
        cases: list[dict[str, Any]] = [
            {
                "case_id": "unit-routing-selection",
                "level": "unit",
                "objective": "Task kind and routing mode select an expected model candidate.",
                "assertions": [
                    "ModelRouter returns a selected_model",
                    "RoutingDecision includes fallback_model or explicit absence",
                    "Routing reason is recorded",
                ],
            },
            {
                "case_id": "unit-session-snapshot",
                "level": "unit",
                "objective": "Session snapshot captures resumable workflow context.",
                "assertions": [
                    "SessionSnapshot contains session_id and last_checkpoint",
                    "Persistent context includes completed and pending tasks",
                    "Resume prompt can be generated from the snapshot",
                ],
            },
            {
                "case_id": "integration-orchestrator-flow",
                "level": "integration",
                "objective": "Orchestrator completes requirements, planning, documentation, and implementation phases.",
                "assertions": [
                    "requirements_analysis is completed",
                    "planning is completed",
                    "documentation is completed",
                    "implementation is completed",
                ],
            },
            {
                "case_id": "integration-artifact-persistence",
                "level": "integration",
                "objective": "Workflow artifacts and docs are persisted after execution.",
                "assertions": [
                    "workflow-state.json is written",
                    "session-snapshot.json is written",
                    "run-summary.json is written",
                    "design.md, runbook.md, and final-summary.md are written",
                ],
            },
            {
                "case_id": "e2e-cli-quality-mode",
                "level": "end_to_end",
                "objective": "CLI execution with quality routing mode completes and emits artifacts.",
                "assertions": [
                    "CLI exits successfully",
                    "routing_mode is reflected in output",
                    "artifacts list includes docs and artifacts paths",
                ],
            },
            {
                "case_id": "unit-environment-preflight-signals",
                "level": "unit",
                "objective": "Configured SDK environment assumptions are validated before execution starts.",
                "assertions": [
                    "Unset environment paths keep default execution guidance valid",
                    "Configured working_directory must exist as a directory",
                    "Configured config_dir must exist as a directory",
                ],
            },
            {
                "case_id": "integration-operator-environment-signals",
                "level": "integration",
                "objective": "Operator-facing artifacts expose environment and execution signals consistently.",
                "assertions": [
                    "routing_mode is reflected in output",
                    "token usage ratio is preserved when available",
                    "environment preflight failures are surfaced in operator-facing outputs",
                ],
            },
        ]

        for index, criterion in enumerate(acceptance_criteria, start=1):
            cases.append(
                {
                    "case_id": f"acceptance-{index}",
                    "level": "integration",
                    "objective": criterion,
                    "assertions": [
                        "Generated workflow outputs provide evidence for this criterion",
                    ],
                }
            )

        for slice_item in code_change_slices:
            slice_id = str(slice_item.get("slice_id", "unknown")).strip() or "unknown"
            goal = str(slice_item.get("goal", "")).strip() or "TBD"
            targets = self._normalize_list(slice_item.get("targets"))
            cases.append(
                {
                    "case_id": f"slice-{slice_id}",
                    "level": "integration",
                    "objective": f"Validate implementation slice `{slice_id}`: {goal}",
                    "assertions": [
                        f"Targets are identified: {', '.join(targets) if targets else 'none'}",
                        "Dependencies are satisfied before execution",
                    ],
                }
            )

        if open_questions:
            cases.append(
                {
                    "case_id": "risk-open-questions",
                    "level": "review_gate",
                    "objective": "Ensure unresolved questions are surfaced before execution expands.",
                    "assertions": [
                        "Open questions are listed in generated artifacts",
                        "Review phase can block completion when needed",
                    ],
                }
            )

        return cases

    def _build_test_plan_document(self, test_plan: dict[str, Any]) -> str:
        lines: list[str] = [
            "# Test Plan",
            "",
            "## Objective",
            str(test_plan.get("objective", "TBD")),
            "",
            "## Strategy",
        ]
        lines.extend(
            self._render_bullets(self._normalize_list(test_plan.get("strategy")))
        )
        lines.extend(
            [
                "",
                "## Test Levels",
            ]
        )
        lines.extend(self._render_test_levels(test_plan.get("test_levels")))
        lines.extend(
            [
                "",
                "## Acceptance Criteria Coverage",
            ]
        )
        lines.extend(
            self._render_bullets(
                self._normalize_list(test_plan.get("acceptance_criteria"))
            )
        )
        lines.extend(
            [
                "",
                "## Test Cases",
            ]
        )
        lines.extend(self._render_test_cases(test_plan.get("test_cases")))
        lines.extend(
            [
                "",
                "## Fixtures and Data",
            ]
        )
        lines.extend(
            self._render_bullets(
                self._normalize_list(test_plan.get("fixtures_and_data"))
            )
        )
        lines.extend(
            [
                "",
                "## Environment Assumptions",
            ]
        )
        lines.extend(
            self._render_bullets(
                self._normalize_list(test_plan.get("environment_assumptions"))
            )
        )
        lines.extend(
            [
                "",
                "## Validation Commands",
            ]
        )
        lines.extend(
            self._render_bullets(
                self._normalize_list(test_plan.get("validation_commands"))
            )
        )
        lines.extend(
            [
                "",
                "## Operator Environment Signals",
            ]
        )
        lines.extend(
            self._render_bullets(
                self._normalize_list(test_plan.get("operator_environment_signals"))
            )
        )
        lines.extend(
            [
                "",
                "## Open Questions",
            ]
        )
        lines.extend(
            self._render_bullets(self._normalize_list(test_plan.get("open_questions")))
        )
        lines.extend(
            [
                "",
                "## Copilot Draft Notes",
                str(
                    test_plan.get("copilot_response_excerpt") or "No additional notes."
                ),
            ]
        )
        return "\n".join(lines).strip() + "\n"

    def _render_test_levels(self, value: Any) -> list[str]:
        if not isinstance(value, list) or not value:
            return ["- none"]
        lines: list[str] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            level = str(item.get("level", "unknown")).strip()
            focus = str(item.get("focus", "")).strip()
            lines.append(f"- {level}: {focus or 'TBD'}")
        return lines or ["- none"]

    def _render_test_cases(self, value: Any) -> list[str]:
        if not isinstance(value, list) or not value:
            return ["- none"]

        lines: list[str] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            case_id = str(item.get("case_id", "unknown")).strip()
            level = str(item.get("level", "unknown")).strip()
            objective = str(item.get("objective", "")).strip()
            assertions = self._normalize_list(item.get("assertions"))
            lines.append(f"- `{case_id}` ({level}): {objective or 'TBD'}")
            if assertions:
                for assertion in assertions:
                    lines.append(f"  - assertion: {assertion}")
            else:
                lines.append("  - assertion: none")
        return lines

    def _normalize_code_change_slices(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []

        normalized: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "slice_id": str(item.get("slice_id", "")).strip(),
                    "goal": str(item.get("goal", "")).strip(),
                    "targets": self._normalize_list(item.get("targets")),
                    "depends_on": self._normalize_list(item.get("depends_on")),
                }
            )
        return normalized

    def _normalize_task_breakdown(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []

        normalized: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "task_id": str(item.get("task_id", "")).strip(),
                    "objective": str(item.get("objective", "")).strip(),
                    "depends_on": self._normalize_list(item.get("depends_on")),
                }
            )
        return normalized

    def _normalize_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _render_bullets(self, items: list[str]) -> list[str]:
        if not items:
            return ["- none"]
        return [f"- {item}" for item in items]

    def _as_dict(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        return {}
