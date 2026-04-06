"""Review agent for the impliforge workflow."""

from __future__ import annotations

from typing import Any

from impliforge.agents.base import AgentResult, AgentTask, BaseAgent
from impliforge.orchestration.workflow import WorkflowState


class ReviewAgent(BaseAgent):
    """Review generated plans, documentation, and implementation proposals."""

    agent_name = "review"

    async def run(self, task: AgentTask, state: WorkflowState) -> AgentResult:
        normalized_requirements = self._as_dict(
            task.inputs.get("normalized_requirements", {})
        )
        plan = self._as_dict(task.inputs.get("plan", {}))
        documentation_bundle = self._as_dict(
            task.inputs.get("documentation_bundle", {})
        )
        implementation = self._as_dict(task.inputs.get("implementation", {}))
        test_plan = self._as_dict(task.inputs.get("test_plan", {}))
        test_results = self._as_dict(task.inputs.get("test_results", {}))
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
        resolved_decisions = self._normalize_list(
            normalized_requirements.get("resolved_decisions")
        )
        task_breakdown = self._normalize_task_breakdown(plan.get("task_breakdown"))
        code_change_slices = self._normalize_code_change_slices(
            implementation.get("code_change_slices")
        )

        findings = self._build_findings(
            acceptance_criteria=acceptance_criteria,
            constraints=constraints,
            open_questions=open_questions,
            resolved_decisions=resolved_decisions,
            documentation_bundle=documentation_bundle,
            implementation=implementation,
            task_breakdown=task_breakdown,
            code_change_slices=code_change_slices,
            test_plan=test_plan,
            test_results=test_results,
        )
        recommendations = self._build_recommendations(
            open_questions=open_questions,
            resolved_decisions=resolved_decisions,
            documentation_bundle=documentation_bundle,
            implementation=implementation,
            code_change_slices=code_change_slices,
            test_plan=test_plan,
            test_results=test_results,
        )
        severity = self._determine_severity(findings)
        unresolved_issues = [
            finding["summary"]
            for finding in findings
            if finding.get("status") in {"warning", "needs_follow_up"}
        ]
        fix_loop_required = severity in {"warning", "needs_follow_up"}
        fix_targets = self._build_fix_targets(
            findings=findings,
            unresolved_issues=unresolved_issues,
            recommendations=recommendations,
        )
        risks = []
        if unresolved_issues:
            risks.append("レビューで未解決事項が残っているため、実装完了判定は保留")
        if open_questions and not resolved_decisions:
            risks.append(
                "要件上の open questions が残っており、対応方針も未確定のため、レビュー結果は暫定"
            )
        if fix_loop_required:
            risks.append("warning 以上のレビュー結果のため、fix loop が必要")

        review_report = self._build_review_report(
            objective=objective,
            findings=findings,
            recommendations=recommendations,
            acceptance_criteria=acceptance_criteria,
            constraints=constraints,
            open_questions=open_questions,
            resolved_decisions=resolved_decisions,
            risks=risks,
            copilot_response=copilot_response,
            fix_loop_required=fix_loop_required,
            fix_targets=fix_targets,
        )

        return AgentResult.success(
            "レビュー報告を生成し、未解決事項と次アクションを整理した。",
            outputs={
                "review_report": review_report,
                "review": {
                    "objective": objective,
                    "severity": severity,
                    "findings": findings,
                    "recommendations": recommendations,
                    "unresolved_issues": unresolved_issues,
                    "fix_loop_required": fix_loop_required,
                    "fix_targets": fix_targets,
                },
                "open_questions": open_questions,
                "resolved_decisions": resolved_decisions,
            },
            artifacts=["docs/review-report.md"],
            next_actions=recommendations,
            risks=risks,
            metrics={
                "acceptance_criteria_count": len(acceptance_criteria),
                "constraint_count": len(constraints),
                "finding_count": len(findings),
                "unresolved_issue_count": len(unresolved_issues),
                "recommendation_count": len(recommendations),
                "fix_target_count": len(fix_targets),
            },
        )

    def _build_findings(
        self,
        *,
        acceptance_criteria: list[str],
        constraints: list[str],
        open_questions: list[str],
        resolved_decisions: list[str],
        documentation_bundle: dict[str, Any],
        implementation: dict[str, Any],
        task_breakdown: list[dict[str, Any]],
        code_change_slices: list[dict[str, Any]],
        test_plan: dict[str, Any],
        test_results: dict[str, Any],
    ) -> list[dict[str, str]]:
        findings: list[dict[str, str]] = []

        if documentation_bundle.get("design"):
            findings.append(
                {
                    "status": "ok",
                    "summary": "設計文書が生成されており、レビュー対象の設計情報が存在する。",
                }
            )
        else:
            findings.append(
                {
                    "status": "warning",
                    "summary": "設計文書が不足しており、実装提案の妥当性確認が難しい。",
                }
            )

        if documentation_bundle.get("runbook"):
            findings.append(
                {
                    "status": "ok",
                    "summary": "運用手順書が生成されており、実行フローの確認材料がある。",
                }
            )
        else:
            findings.append(
                {
                    "status": "warning",
                    "summary": "運用手順書が不足しており、運用時の確認手順が曖昧。",
                }
            )

        if task_breakdown:
            findings.append(
                {
                    "status": "ok",
                    "summary": "タスク分解が存在し、依存関係を追跡できる。",
                }
            )
        else:
            findings.append(
                {
                    "status": "warning",
                    "summary": "タスク分解が不足しており、後続フェーズの追跡が難しい。",
                }
            )

        if code_change_slices:
            findings.append(
                {
                    "status": "ok",
                    "summary": "実装提案に code change slices が含まれている。",
                }
            )
        else:
            findings.append(
                {
                    "status": "warning",
                    "summary": "実装提案に具体的な code change slices が不足している。",
                }
            )

        if acceptance_criteria:
            findings.append(
                {
                    "status": "ok",
                    "summary": "受け入れ条件が整理されており、完了判定の基準がある。",
                }
            )
        else:
            findings.append(
                {
                    "status": "warning",
                    "summary": "受け入れ条件が不足しており、完了判定が曖昧。",
                }
            )

        if constraints:
            findings.append(
                {
                    "status": "ok",
                    "summary": "制約条件が整理されており、設計・実装の境界が明示されている。",
                }
            )
        else:
            findings.append(
                {
                    "status": "warning",
                    "summary": "制約条件が不足しており、設計判断の前提が弱い。",
                }
            )

        if open_questions and not resolved_decisions:
            findings.append(
                {
                    "status": "needs_follow_up",
                    "summary": "未解決の open questions が残っているため、実装前に確認が必要。",
                }
            )
        else:
            findings.append(
                {
                    "status": "ok",
                    "summary": "open questions は解消済み、または対応方針が明文化されている。",
                }
            )

        if implementation.get("strategy"):
            findings.append(
                {
                    "status": "ok",
                    "summary": "実装戦略が整理されており、変更方針が明示されている。",
                }
            )
        else:
            findings.append(
                {
                    "status": "warning",
                    "summary": "実装戦略の記述が不足しており、変更方針が不明瞭。",
                }
            )

        if test_plan.get("test_cases"):
            findings.append(
                {
                    "status": "ok",
                    "summary": "テスト計画に test cases が含まれており、検証観点が整理されている。",
                }
            )
        else:
            findings.append(
                {
                    "status": "warning",
                    "summary": "テスト計画に具体的な test cases が不足している。",
                }
            )

        test_status = str(test_results.get("status", "")).strip()
        if test_status == "provisional_passed":
            findings.append(
                {
                    "status": "ok",
                    "summary": "テスト結果は provisional_passed で、現時点の検証は通過している。",
                }
            )
        elif test_status:
            findings.append(
                {
                    "status": "needs_follow_up",
                    "summary": f"テスト結果が `{test_status}` のため、追加確認または修正が必要。",
                }
            )
        else:
            findings.append(
                {
                    "status": "warning",
                    "summary": "テスト結果のステータスが不足しており、検証完了を判断できない。",
                }
            )

        return findings

    def _build_recommendations(
        self,
        *,
        open_questions: list[str],
        resolved_decisions: list[str],
        documentation_bundle: dict[str, Any],
        implementation: dict[str, Any],
        code_change_slices: list[dict[str, Any]],
        test_plan: dict[str, Any],
        test_results: dict[str, Any],
    ) -> list[str]:
        recommendations: list[str] = []

        if open_questions and not resolved_decisions:
            recommendations.append("open questions を解消してから実コード変更に進む")
        elif resolved_decisions:
            recommendations.append(
                "文書化した persistent context policy と approval policy を前提に実コード変更を進める"
            )
        if not documentation_bundle.get("design"):
            recommendations.append("docs/design.md を補強して設計判断を明文化する")
        if not documentation_bundle.get("runbook"):
            recommendations.append("docs/runbook.md を補強して運用手順を明文化する")
        if not code_change_slices:
            recommendations.append(
                "implementation proposal に具体的な code change slices を追加する"
            )
        if implementation.get("strategy"):
            recommendations.append(
                "implementation strategy を基に test_design フェーズへ進む"
            )
        else:
            recommendations.append(
                "implementation strategy を補強してから test_design に進む"
            )

        if not test_plan.get("test_cases"):
            recommendations.append(
                "test_plan に具体的な test cases を追加して検証観点を補強する"
            )

        test_status = str(test_results.get("status", "")).strip()
        if test_status and test_status != "provisional_passed":
            recommendations.append(
                "test_results の未解決項目を fix loop に送り、再テストする"
            )

        if not recommendations:
            recommendations.append(
                "test_design と test_execution を追加して検証フェーズへ進む"
            )

        return recommendations

    def _build_review_report(
        self,
        *,
        objective: str,
        findings: list[dict[str, str]],
        recommendations: list[str],
        acceptance_criteria: list[str],
        constraints: list[str],
        open_questions: list[str],
        resolved_decisions: list[str],
        risks: list[str],
        copilot_response: str,
        fix_loop_required: bool,
        fix_targets: list[dict[str, str]],
    ) -> str:
        lines: list[str] = [
            "# Review Report",
            "",
            "## Objective",
            objective or "TBD",
            "",
            "## Findings",
        ]
        lines.extend(self._render_findings(findings))
        lines.extend(
            [
                "",
                "## Recommendations",
            ]
        )
        lines.extend(self._render_bullets(recommendations))
        lines.extend(
            [
                "",
                "## Acceptance Criteria Coverage",
            ]
        )
        lines.extend(self._render_bullets(acceptance_criteria))
        lines.extend(
            [
                "",
                "## Constraints",
            ]
        )
        lines.extend(self._render_bullets(constraints))
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
                "## Risks",
            ]
        )
        lines.extend(self._render_bullets(risks))
        lines.extend(
            [
                "",
                "## Fix Loop",
                f"- required: {'yes' if fix_loop_required else 'no'}",
                "",
                "## Fix Targets",
            ]
        )
        lines.extend(self._render_fix_targets(fix_targets))
        lines.extend(
            [
                "",
                "## Copilot Draft Notes",
                copilot_response or "No additional Copilot draft content was provided.",
            ]
        )
        return "\n".join(lines).strip() + "\n"

    def _determine_severity(self, findings: list[dict[str, str]]) -> str:
        statuses = {finding.get("status", "") for finding in findings}
        if "needs_follow_up" in statuses:
            return "needs_follow_up"
        if "warning" in statuses:
            return "warning"
        return "ok"

    def _build_fix_targets(
        self,
        *,
        findings: list[dict[str, str]],
        unresolved_issues: list[str],
        recommendations: list[str],
    ) -> list[dict[str, str]]:
        targets: list[dict[str, str]] = []

        for index, issue in enumerate(unresolved_issues, start=1):
            targets.append(
                {
                    "target_id": f"issue-{index}",
                    "source": "review",
                    "summary": issue,
                    "action": "Generate a focused fix proposal and re-run validation.",
                }
            )

        if not targets:
            for index, finding in enumerate(findings, start=1):
                status = str(finding.get("status", "")).strip()
                if status not in {"warning", "needs_follow_up"}:
                    continue
                targets.append(
                    {
                        "target_id": f"finding-{index}",
                        "source": status,
                        "summary": str(finding.get("summary", "")).strip(),
                        "action": "Address the finding and re-run test_execution and review.",
                    }
                )

        if not targets and recommendations:
            for index, recommendation in enumerate(recommendations, start=1):
                targets.append(
                    {
                        "target_id": f"recommendation-{index}",
                        "source": "recommendation",
                        "summary": recommendation,
                        "action": "Convert the recommendation into a concrete fix slice.",
                    }
                )

        return targets

    def _render_findings(self, findings: list[dict[str, str]]) -> list[str]:
        if not findings:
            return ["- none"]

        lines: list[str] = []
        for finding in findings:
            status = str(finding.get("status", "unknown")).strip()
            summary = str(finding.get("summary", "")).strip()
            lines.append(f"- [{status}] {summary or 'TBD'}")
        return lines

    def _render_fix_targets(self, targets: list[dict[str, str]]) -> list[str]:
        if not targets:
            return ["- none"]

        lines: list[str] = []
        for target in targets:
            target_id = str(target.get("target_id", "unknown")).strip()
            source = str(target.get("source", "unknown")).strip()
            summary = str(target.get("summary", "")).strip()
            action = str(target.get("action", "")).strip()
            lines.append(f"- `{target_id}` [{source}] {summary or 'TBD'}")
            if action:
                lines.append(f"  - action: {action}")
        return lines

    def _render_bullets(self, items: list[str]) -> list[str]:
        if not items:
            return ["- none"]
        return [f"- {item}" for item in items]

    def _normalize_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _normalize_task_breakdown(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _normalize_code_change_slices(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _as_dict(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        return {}
