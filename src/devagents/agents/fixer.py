"""Fix proposal agent for the devagents workflow."""

from __future__ import annotations

from typing import Any

from devagents.agents.base import AgentResult, AgentTask, BaseAgent
from devagents.orchestration.workflow import WorkflowState


class FixerAgent(BaseAgent):
    """Generate a focused fix proposal from review and validation outputs."""

    agent_name = "fixer"

    async def run(self, task: AgentTask, state: WorkflowState) -> AgentResult:
        normalized_requirements = self._as_dict(
            task.inputs.get("normalized_requirements", {})
        )

        documentation_bundle = self._as_dict(
            task.inputs.get("documentation_bundle", {})
        )
        implementation = self._as_dict(task.inputs.get("implementation", {}))
        test_plan = self._as_dict(task.inputs.get("test_plan", {}))
        test_results = self._as_dict(task.inputs.get("test_results", {}))
        review = self._as_dict(task.inputs.get("review", {}))
        copilot_response = str(task.inputs.get("copilot_response", "")).strip()

        objective = str(
            normalized_requirements.get("objective") or state.requirement
        ).strip()
        acceptance_criteria = self._normalize_list(
            normalized_requirements.get("acceptance_criteria")
        )
        constraints = self._normalize_list(normalized_requirements.get("constraints"))
        open_questions = self._normalize_list(
            normalized_requirements.get("open_questions")
        )
        unresolved_issues = self._normalize_list(review.get("unresolved_issues"))
        recommendations = self._normalize_list(review.get("recommendations"))
        findings = self._normalize_dict_list(review.get("findings"))
        code_change_slices = self._normalize_dict_list(
            implementation.get("code_change_slices")
        )
        executed_checks = self._normalize_dict_list(test_results.get("executed_checks"))

        severity = str(review.get("severity", "unknown")).strip() or "unknown"
        fix_needed = severity in {"warning", "needs_follow_up"} or bool(
            unresolved_issues
        )

        fix_slices = self._build_fix_slices(
            unresolved_issues=unresolved_issues,
            recommendations=recommendations,
            code_change_slices=code_change_slices,
        )
        edit_proposals = self._build_edit_proposals(
            fix_slices=fix_slices,
            documentation_bundle=documentation_bundle,
            implementation=implementation,
        )

        fix_plan = {
            "objective": objective,
            "summary": "レビュー結果と検証結果に基づく修正提案を整理した。",
            "fix_needed": fix_needed,
            "severity": severity,
            "constraints": constraints,
            "acceptance_criteria": acceptance_criteria,
            "unresolved_issues": unresolved_issues,
            "recommendations": recommendations,
            "fix_strategy": self._build_fix_strategy(
                severity=severity,
                unresolved_issues=unresolved_issues,
                open_questions=open_questions,
            ),
            "fix_slices": fix_slices,
            "edit_proposals": edit_proposals,
            "revalidation_plan": self._build_revalidation_plan(
                executed_checks=executed_checks,
                unresolved_issues=unresolved_issues,
                open_questions=open_questions,
            ),
            "review_findings": findings,
            "documentation_inputs": {
                "design_present": bool(documentation_bundle.get("design")),
                "runbook_present": bool(documentation_bundle.get("runbook")),
                "test_plan_present": bool(test_plan),
                "test_results_present": bool(test_results),
            },
            "copilot_response_excerpt": copilot_response[:500]
            if copilot_response
            else "",
        }

        fix_report = self._build_fix_report(fix_plan)

        next_actions = self._build_next_actions(
            fix_needed=fix_needed,
            unresolved_issues=unresolved_issues,
            open_questions=open_questions,
        )

        risks = []
        if fix_needed:
            risks.append(
                "レビューで warning または needs_follow_up が残っているため、完了判定は保留"
            )
        if open_questions:
            risks.append(
                "要件上の open questions が残っているため、修正方針が暫定になる"
            )
        if not code_change_slices:
            risks.append(
                "既存の code change slices が不足しているため、修正対象の粒度が粗い"
            )

        return AgentResult.success(
            "修正提案を生成し、再検証に向けたアクションを整理した。",
            outputs={
                "fix_plan": fix_plan,
                "fix_report": fix_report,
                "fix_needed": fix_needed,
                "open_questions": open_questions,
            },
            artifacts=["docs/fix-report.md"],
            next_actions=next_actions,
            risks=risks,
            metrics={
                "acceptance_criteria_count": len(acceptance_criteria),
                "constraint_count": len(constraints),
                "unresolved_issue_count": len(unresolved_issues),
                "recommendation_count": len(recommendations),
                "fix_slice_count": len(fix_plan["fix_slices"]),
                "revalidation_step_count": len(fix_plan["revalidation_plan"]),
            },
        )

    def _build_fix_strategy(
        self,
        *,
        severity: str,
        unresolved_issues: list[str],
        open_questions: list[str],
    ) -> list[str]:
        strategy = [
            "Address review findings at the root cause instead of patching symptoms",
            "Keep the next change slice small and explicitly tied to unresolved issues",
            "Re-run validation after each meaningful fix proposal",
        ]

        if severity == "needs_follow_up":
            strategy.append(
                "Resolve blocking review concerns before expanding implementation scope"
            )
        elif severity == "warning":
            strategy.append(
                "Reduce warning-level ambiguity before declaring the workflow complete"
            )
        else:
            strategy.append(
                "No blocking review severity detected; only targeted cleanup is needed"
            )

        if unresolved_issues:
            strategy.append(
                "Map each unresolved issue to a concrete fix slice and revalidation step"
            )

        if open_questions:
            strategy.append(
                "Separate requirement ambiguity from implementation defects before fixing"
            )

        return strategy

    def _build_fix_slices(
        self,
        *,
        unresolved_issues: list[str],
        recommendations: list[str],
        code_change_slices: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        fix_slices: list[dict[str, Any]] = []

        for index, issue in enumerate(unresolved_issues, start=1):
            related_targets = self._collect_related_targets(code_change_slices)
            fix_slices.append(
                {
                    "slice_id": f"fix-{index}",
                    "goal": issue,
                    "targets": related_targets,
                    "depends_on": ["review", "test_execution"],
                    "validation_focus": "Confirm the issue no longer appears in review or test outputs, and record which re-run review/test steps verify the fix",
                }
            )

        if not fix_slices:
            for index, recommendation in enumerate(recommendations, start=1):
                fix_slices.append(
                    {
                        "slice_id": f"recommendation-{index}",
                        "goal": recommendation,
                        "targets": self._collect_related_targets(code_change_slices),
                        "depends_on": ["review"],
                        "validation_focus": "Confirm the recommendation is reflected in regenerated artifacts and visible in the follow-up review output",
                    }
                )

        if not fix_slices:
            fix_slices.append(
                {
                    "slice_id": "fix-fallback-1",
                    "goal": "Review outputs and tighten implementation proposal where needed",
                    "targets": self._collect_related_targets(code_change_slices),
                    "depends_on": ["review"],
                    "validation_focus": "Re-run review and confirm no unresolved issues remain, with the follow-up review step called out explicitly",
                }
            )

        return fix_slices

    def _build_revalidation_plan(
        self,
        *,
        executed_checks: list[dict[str, Any]],
        unresolved_issues: list[str],
        open_questions: list[str],
    ) -> list[str]:
        steps = [
            "Re-run test_execution after applying the proposed fix slice and record which failing or targeted checks were revalidated",
            "Re-run review and compare severity and unresolved issues against the pre-fix report",
        ]

        if executed_checks:
            steps.append(
                "Confirm previously passed checks remain stable after the fix and note that follow-up status in the fix report"
            )

        if unresolved_issues:
            steps.append(
                "Verify each unresolved issue is either resolved or explicitly deferred, with the matching review/test follow-up called out"
            )

        if open_questions:
            steps.append(
                "Confirm requirement ambiguity is documented separately from implementation defects"
            )

        return steps

    def _build_next_actions(
        self,
        *,
        fix_needed: bool,
        unresolved_issues: list[str],
        open_questions: list[str],
    ) -> list[str]:
        if fix_needed:
            actions = [
                "Persist docs/fix-report.md",
                "Apply the highest-priority fix slice",
                "Re-run test_execution",
                "Re-run review",
            ]
            if unresolved_issues:
                actions.append("Track unresolved issues until severity becomes ok")
            if open_questions:
                actions.append(
                    "Escalate requirement ambiguity before broadening code changes"
                )
            return actions

        return [
            "Persist docs/fix-report.md",
            "No immediate fix loop is required",
            "Proceed to final completion checks",
        ]

    def _build_fix_report(self, fix_plan: dict[str, Any]) -> str:
        lines: list[str] = [
            "# Fix Report",
            "",
            "## Objective",
            str(fix_plan.get("objective", "TBD")),
            "",
            "## Fix Needed",
            f"- {bool(fix_plan.get('fix_needed'))}",
            f"- severity: {fix_plan.get('severity', 'unknown')}",
            "",
            "## Fix Strategy",
        ]
        lines.extend(
            self._render_bullets(self._normalize_list(fix_plan.get("fix_strategy")))
        )
        lines.extend(
            [
                "",
                "## Unresolved Issues",
            ]
        )
        lines.extend(
            self._render_bullets(
                self._normalize_list(fix_plan.get("unresolved_issues"))
            )
        )
        lines.extend(
            [
                "",
                "## Fix Slices",
            ]
        )
        lines.extend(self._render_fix_slices(fix_plan.get("fix_slices")))
        lines.extend(
            [
                "",
                "## Revalidation Plan",
            ]
        )
        lines.extend(
            self._render_bullets(
                self._normalize_list(fix_plan.get("revalidation_plan"))
            )
        )
        lines.extend(
            [
                "",
                "## Edit Proposals",
            ]
        )
        lines.extend(self._render_edit_proposals(fix_plan.get("edit_proposals")))
        lines.extend(
            [
                "",
                "## Recommendations",
            ]
        )
        lines.extend(
            self._render_bullets(self._normalize_list(fix_plan.get("recommendations")))
        )
        lines.extend(
            [
                "",
                "## Copilot Draft Notes",
                str(
                    fix_plan.get("copilot_response_excerpt")
                    or "No additional Copilot draft content was provided."
                ),
            ]
        )
        return "\n".join(lines).strip() + "\n"

    def _render_fix_slices(self, value: Any) -> list[str]:
        if not isinstance(value, list) or not value:
            return ["- none"]

        lines: list[str] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            slice_id = str(item.get("slice_id", "unknown")).strip()
            goal = str(item.get("goal", "")).strip()
            targets = self._normalize_list(item.get("targets"))
            depends_on = self._normalize_list(item.get("depends_on"))
            validation_focus = str(item.get("validation_focus", "")).strip()

            lines.append(f"- `{slice_id}`: {goal or 'TBD'}")
            lines.append(f"  - targets: {', '.join(targets) if targets else 'none'}")
            lines.append(
                f"  - depends_on: {', '.join(depends_on) if depends_on else 'none'}"
            )
            lines.append(f"  - validation_focus: {validation_focus or 'none'}")
        return lines or ["- none"]

    def _build_edit_proposals(
        self,
        *,
        fix_slices: list[dict[str, Any]],
        documentation_bundle: dict[str, Any],
        implementation: dict[str, Any],
    ) -> list[dict[str, Any]]:
        proposals: list[dict[str, Any]] = []

        for index, fix_slice in enumerate(fix_slices, start=1):
            targets = self._normalize_list(fix_slice.get("targets"))
            goal = str(fix_slice.get("goal", "")).strip()
            validation_focus = str(fix_slice.get("validation_focus", "")).strip()

            proposals.append(
                {
                    "proposal_id": f"edit-{index}",
                    "mode": "update",
                    "targets": targets or ["docs/fix-report.md"],
                    "summary": goal or "Apply a focused fix slice",
                    "instructions": [
                        "Keep the change small and directly tied to the unresolved issue.",
                        "Prefer updating generated docs and implementation proposal artifacts first.",
                        validation_focus
                        or "Re-run validation after the proposed edit is applied.",
                    ],
                }
            )

        if not proposals:
            fallback_targets = self._collect_related_targets(
                self._normalize_dict_list(implementation.get("code_change_slices"))
            )
            if documentation_bundle.get("design"):
                fallback_targets.append("docs/design.md")
            if documentation_bundle.get("runbook"):
                fallback_targets.append("docs/runbook.md")

            deduped_targets: list[str] = []
            for target in fallback_targets:
                if target not in deduped_targets:
                    deduped_targets.append(target)

            proposals.append(
                {
                    "proposal_id": "edit-fallback-1",
                    "mode": "update",
                    "targets": deduped_targets or ["docs/fix-report.md"],
                    "summary": "Tighten generated artifacts to address review feedback.",
                    "instructions": [
                        "Update the smallest set of files needed to resolve the review concern.",
                        "Preserve existing workflow structure and artifact naming.",
                        "Re-run test_execution and review after the edit.",
                    ],
                }
            )

        return proposals

    def _render_edit_proposals(self, value: Any) -> list[str]:
        if not isinstance(value, list) or not value:
            return ["- none"]

        lines: list[str] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            proposal_id = str(item.get("proposal_id", "unknown")).strip()
            mode = str(item.get("mode", "update")).strip()
            summary = str(item.get("summary", "")).strip()
            targets = self._normalize_list(item.get("targets"))
            instructions = self._normalize_list(item.get("instructions"))

            lines.append(f"- `{proposal_id}` [{mode}]: {summary or 'TBD'}")
            lines.append(f"  - targets: {', '.join(targets) if targets else 'none'}")
            if instructions:
                for instruction in instructions:
                    lines.append(f"  - instruction: {instruction}")
            else:
                lines.append("  - instruction: none")

        return lines or ["- none"]

    def _collect_related_targets(
        self,
        code_change_slices: list[dict[str, Any]],
    ) -> list[str]:
        targets: list[str] = []
        for item in code_change_slices:
            for target in self._normalize_list(item.get("targets")):
                if target not in targets:
                    targets.append(target)
        return targets

    def _normalize_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _normalize_dict_list(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _render_bullets(self, items: list[str]) -> list[str]:
        if not items:
            return ["- none"]
        return [f"- {item}" for item in items]

    def _as_dict(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        return {}
