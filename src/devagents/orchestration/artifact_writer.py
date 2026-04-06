"""Helpers for persisting workflow artifacts and generated documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from devagents.agents.base import AgentResult
from devagents.orchestration.session_manager import SessionManager
from devagents.orchestration.state_store import StateStore
from devagents.orchestration.workflow import TaskStatus, WorkflowState


class WorkflowArtifactWriter:
    """Persist workflow documents, summaries, and state snapshots."""

    def __init__(
        self,
        *,
        docs_dir: str | Path = "docs",
        state_store: StateStore | None = None,
        session_manager: SessionManager | None = None,
    ) -> None:
        self.docs_dir = Path(docs_dir)
        self.state_store = state_store or StateStore()
        self.session_manager = session_manager or SessionManager()

    def persist_documentation_outputs(
        self,
        *,
        state: WorkflowState,
        result: AgentResult,
    ) -> None:
        """Write generated design and runbook documents to `docs/`."""
        design_document = result.outputs.get("design_document")
        runbook_document = result.outputs.get("runbook_document")

        if isinstance(design_document, str) and design_document.strip():
            self._write_doc(
                state=state,
                target_name="design.md",
                content=design_document,
            )

        if isinstance(runbook_document, str) and runbook_document.strip():
            self._write_doc(
                state=state,
                target_name="runbook.md",
                content=runbook_document,
            )

    def persist_text_output(
        self,
        *,
        state: WorkflowState,
        result: AgentResult,
        output_key: str,
        target_name: str,
    ) -> None:
        """Write a single text output from an agent result to `docs/`."""
        content = result.outputs.get(output_key)
        if not isinstance(content, str) or not content.strip():
            return

        self._write_doc(
            state=state,
            target_name=target_name,
            content=content,
        )

    def write_workflow_artifacts(
        self,
        *,
        state: WorkflowState,
        requirement: str,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        documentation_result: AgentResult,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
        test_execution_result: AgentResult,
        review_result: AgentResult,
        fix_result: AgentResult | None,
        session_snapshot: Any,
    ) -> dict[str, str]:
        """Persist workflow state, session snapshot, run summary, and final summary."""
        self.docs_dir.mkdir(parents=True, exist_ok=True)

        workflow_state_path = self.state_store.save_workflow_state(state)
        session_snapshot_path = self.state_store.save_session_snapshot(session_snapshot)
        run_summary_payload = self.build_run_summary_payload(
            state=state,
            requirement=requirement,
            requirements_result=requirements_result,
            planning_result=planning_result,
            documentation_result=documentation_result,
            implementation_result=implementation_result,
            test_design_result=test_design_result,
            test_execution_result=test_execution_result,
            review_result=review_result,
            fix_result=fix_result,
            session_snapshot=session_snapshot,
        )
        run_summary_path = self.state_store.save_run_summary(
            state.workflow_id,
            run_summary_payload,
        )

        final_summary = self.build_final_summary(
            state=state,
            requirement=requirement,
            implementation_result=implementation_result,
            test_design_result=test_design_result,
            test_execution_result=test_execution_result,
            review_result=review_result,
            fix_result=fix_result,
        )
        final_summary_path = self.docs_dir / "final-summary.md"
        final_summary_path.write_text(final_summary, encoding="utf-8")

        for path in (
            workflow_state_path,
            session_snapshot_path,
            run_summary_path,
            final_summary_path,
        ):
            self._record_artifact(state, path)

        finalization_task = state.require_task("finalization")
        acceptance_gate = self.build_acceptance_gate(
            state=state,
            requirements_result=requirements_result,
            documentation_result=documentation_result,
            test_execution_result=test_execution_result,
            review_result=review_result,
        )
        finalization_outputs = {
            "acceptance_gate": acceptance_gate,
            "next_actions": self._build_finalization_next_actions(acceptance_gate),
        }
        finalization_note = "受け入れ条件駆動の完了判定を記録した。"
        finalization_status = TaskStatus.COMPLETED

        if acceptance_gate["ready_for_completion"]:
            finalization_task.mark_completed(outputs=finalization_outputs)
        else:
            finalization_task.outputs.update(finalization_outputs)
            finalization_status = TaskStatus.BLOCKED
            finalization_note = "受け入れ条件駆動の完了判定で未達項目が残ったため finalization を block した。"

        state.update_task_status(
            "finalization",
            finalization_status,
            note=finalization_note,
            outputs=finalization_task.outputs,
        )

        return {
            "workflow_state": workflow_state_path.as_posix(),
            "session_snapshot": session_snapshot_path.as_posix(),
            "run_summary": run_summary_path.as_posix(),
            "final_summary": final_summary_path.as_posix(),
        }

    def build_run_summary_payload(
        self,
        *,
        state: WorkflowState,
        requirement: str,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        documentation_result: AgentResult,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
        test_execution_result: AgentResult,
        review_result: AgentResult,
        fix_result: AgentResult | None,
        session_snapshot: Any,
    ) -> dict[str, Any]:
        """Build the operator-facing run summary payload."""
        summary = state.summary()
        summary["open_questions"] = self._merge_unique_strings(
            summary.get("open_questions", []),
            documentation_result.outputs.get("open_questions", []),
        )
        summary["risks"] = self._merge_unique_strings(
            summary.get("risks", []),
            review_result.risks,
        )

        results = {
            "requirements_result": self.result_to_dict(requirements_result),
            "planning_result": self.result_to_dict(planning_result),
            "documentation_result": self.result_to_dict(documentation_result),
            "implementation_result": self.result_to_dict(implementation_result),
            "test_design_result": self.result_to_dict(test_design_result),
            "test_execution_result": self.result_to_dict(test_execution_result),
            "review_result": self.result_to_dict(review_result),
            "fix_result": self.result_to_dict(fix_result) if fix_result else None,
        }
        failure_report = self._build_failure_report(results)

        return {
            "workflow_id": state.workflow_id,
            "model": state.model,
            "phase": state.phase.value,
            "requirement": requirement,
            "summary": summary,
            "session": {
                "session_id": state.session_id,
                "parent_session_id": state.parent_session_id,
                "token_usage_ratio": getattr(
                    session_snapshot, "token_usage_ratio", None
                ),
                "resume_prompt": self.session_manager.build_resume_prompt(
                    session_snapshot
                ),
            },
            "artifacts": list(state.artifacts),
            "execution_trace": [event.to_dict() for event in state.execution_trace],
            "change_impact_summary": self.build_change_impact_summary(
                state=state,
                implementation_result=implementation_result,
                test_design_result=test_design_result,
                test_execution_result=test_execution_result,
                fix_result=fix_result,
            ),
            "results": results,
            "failure_report": failure_report,
        }

    def build_acceptance_gate(
        self,
        *,
        state: WorkflowState,
        requirements_result: AgentResult,
        documentation_result: AgentResult,
        test_execution_result: AgentResult,
        review_result: AgentResult,
    ) -> dict[str, Any]:
        """Build acceptance-driven finalization status for workflow completion."""
        normalized_requirements = self._as_dict(
            requirements_result.outputs.get("normalized_requirements")
        )
        documentation_bundle = self._as_dict(
            documentation_result.outputs.get("documentation_bundle")
        )
        test_results = self._as_dict(test_execution_result.outputs.get("test_results"))
        review = self._as_dict(review_result.outputs.get("review"))

        acceptance_criteria = self._normalize_list(
            normalized_requirements.get("acceptance_criteria")
        )
        unresolved_issues = self._normalize_list(review.get("unresolved_issues"))
        documentation_updated = bool(documentation_bundle) or any(
            path.startswith("docs/") for path in state.changed_files
        )
        test_status = str(test_results.get("status", "unknown")).strip() or "unknown"
        review_severity = str(review.get("severity", "unknown")).strip() or "unknown"

        checks = [
            {
                "name": "acceptance_criteria_defined",
                "passed": bool(acceptance_criteria),
                "details": acceptance_criteria
                or ["No acceptance criteria were recorded for this workflow."],
            },
            {
                "name": "tests_passing",
                "passed": test_status == "passed",
                "details": [f"test_status={test_status}"],
            },
            {
                "name": "review_has_no_major_findings",
                "passed": review_severity
                not in {"high", "critical", "needs_follow_up"},
                "details": [f"review_severity={review_severity}"],
            },
            {
                "name": "documentation_updated",
                "passed": documentation_updated,
                "details": (
                    self._normalize_list(state.changed_files)
                    if documentation_updated
                    else ["No documentation artifact update was recorded."]
                ),
            },
            {
                "name": "unresolved_issues_explicit",
                "passed": True,
                "details": unresolved_issues or ["none"],
            },
        ]

        failed_checks = [
            check["name"] for check in checks if not bool(check.get("passed"))
        ]

        return {
            "ready_for_completion": not failed_checks,
            "failed_checks": failed_checks,
            "checks": checks,
            "acceptance_criteria": acceptance_criteria,
            "test_status": test_status,
            "review_severity": review_severity,
            "unresolved_issues": unresolved_issues,
            "documentation_updated": documentation_updated,
        }

    def build_final_summary(
        self,
        *,
        state: WorkflowState,
        requirement: str,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
        test_execution_result: AgentResult,
        review_result: AgentResult,
        fix_result: AgentResult | None,
    ) -> str:
        """Build the markdown final summary document."""
        implementation = self._as_dict(
            implementation_result.outputs.get("implementation")
        )
        test_plan = self._as_dict(test_design_result.outputs.get("test_plan"))
        test_results = self._as_dict(test_execution_result.outputs.get("test_results"))
        review = self._as_dict(review_result.outputs.get("review"))
        fix_plan = (
            self._as_dict(fix_result.outputs.get("fix_plan")) if fix_result else {}
        )

        proposed_slices = implementation.get("change_slices", [])
        if not isinstance(proposed_slices, list):
            proposed_slices = []

        completed_tasks = [task.task_id for task in state.completed_tasks()]
        unresolved_issues = review.get("unresolved_issues", [])
        if not isinstance(unresolved_issues, list):
            unresolved_issues = []

        lines = [
            "# Final Summary",
            "",
            "## Requirement",
            requirement,
            "",
            "## Workflow Status",
            f"- workflow_id: {state.workflow_id}",
            f"- phase: {state.phase.value}",
            f"- model: {state.model}",
            f"- session_id: {state.session_id or 'none'}",
            "",
            "## Completed Tasks",
        ]

        if completed_tasks:
            lines.extend(f"- {task_id}" for task_id in completed_tasks)
        else:
            lines.append("- none")

        lines.extend(
            [
                "",
                "## Proposed Code Change Slices",
            ]
        )
        if proposed_slices:
            for item in proposed_slices:
                if isinstance(item, dict):
                    name = (
                        str(item.get("name", "unnamed-slice")).strip()
                        or "unnamed-slice"
                    )
                    summary = str(item.get("summary", "")).strip()
                    lines.append(f"- {name}: {summary or 'No summary provided.'}")
                else:
                    lines.append(f"- {str(item).strip()}")
        else:
            lines.append("- none")

        lines.extend(
            [
                "",
                "## Test Summary",
                f"- test_case_count: {self._count_list_like(test_plan.get('test_cases'))}",
                f"- executed_check_count: {self._count_list_like(test_results.get('executed_checks'))}",
                f"- test_status: {test_results.get('status', 'unknown')}",
                "",
                "## Review Summary",
                f"- severity: {review.get('severity', 'unknown')}",
                f"- unresolved_issues: {self._format_list_or_none(unresolved_issues)}",
                "",
                "## Fix Summary",
                f"- fix_needed: {bool(review.get('fix_loop_required'))}",
                f"- fix_severity: {fix_plan.get('severity', 'none') if fix_plan else 'none'}",
                f"- fix_slice_count: {self._count_list_like(fix_plan.get('change_slices')) if fix_plan else 0}",
                "",
                "## Next Actions",
            ]
        )

        finalization_outputs = (
            state.require_task("finalization").outputs
            if state.get_task("finalization") is not None
            else {}
        )
        acceptance_gate = self._as_dict(finalization_outputs.get("acceptance_gate"))

        if acceptance_gate:
            lines.extend(
                [
                    "",
                    "## Acceptance Gate",
                    f"- ready_for_completion: {bool(acceptance_gate.get('ready_for_completion'))}",
                    f"- failed_checks: {self._format_list_or_none(acceptance_gate.get('failed_checks'))}",
                    f"- test_status: {acceptance_gate.get('test_status', 'unknown')}",
                    f"- review_severity: {acceptance_gate.get('review_severity', 'unknown')}",
                    f"- documentation_updated: {bool(acceptance_gate.get('documentation_updated'))}",
                    f"- unresolved_issues: {self._format_list_or_none(acceptance_gate.get('unresolved_issues'))}",
                ]
            )

        next_actions = finalization_outputs.get("next_actions", [])
        if not isinstance(next_actions, list) or not next_actions:
            next_actions = [
                "Review generated artifacts",
                "Promote approved changes into concrete implementation work",
            ]
        lines.extend(
            f"- {str(action)}" for action in next_actions if str(action).strip()
        )

        return "\n".join(lines) + "\n"

    def result_to_dict(self, result: AgentResult | None) -> dict[str, Any] | None:
        """Convert an agent result into a JSON-serializable dictionary."""
        if result is None:
            return None

        return {
            "status": result.status,
            "summary": result.summary,
            "outputs": result.outputs,
            "artifacts": list(result.artifacts),
            "next_actions": list(result.next_actions),
            "risks": list(result.risks),
            "metrics": dict(result.metrics),
            "failure_category": result.failure_category,
            "failure_cause": result.failure_cause,
        }

    def build_change_impact_summary(
        self,
        *,
        state: WorkflowState,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
        test_execution_result: AgentResult,
        fix_result: AgentResult | None,
    ) -> list[dict[str, Any]]:
        """Build change-impact visibility entries for operator-facing artifacts."""
        implementation = self._as_dict(
            implementation_result.outputs.get("implementation")
        )
        test_plan = self._as_dict(test_design_result.outputs.get("test_plan"))
        test_results = self._as_dict(test_execution_result.outputs.get("test_results"))
        fix_plan = (
            self._as_dict(fix_result.outputs.get("fix_plan")) if fix_result else {}
        )

        entries: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str]] = set()

        for item in self._normalize_dict_list(implementation.get("code_change_slices")):
            changed_files = self._normalize_list(item.get("targets"))
            reason = str(item.get("goal", "")).strip()
            if not changed_files or not reason:
                continue

            impact_scope = self._normalize_list(item.get("depends_on"))
            test_targets = self._collect_test_targets(test_plan, test_results)
            rollback_method = self._build_rollback_method(changed_files)

            entry = {
                "changed_files": changed_files,
                "reason": reason,
                "impact_scope": impact_scope,
                "test_target": test_targets,
                "rollback_method": rollback_method,
            }
            key = ("|".join(changed_files), reason)
            if key not in seen_keys:
                entries.append(entry)
                seen_keys.add(key)

        for item in self._normalize_dict_list(fix_plan.get("fix_slices")):
            changed_files = self._normalize_list(item.get("targets"))
            reason = str(item.get("goal", "")).strip()
            if not changed_files or not reason:
                continue

            impact_scope = self._normalize_list(item.get("depends_on"))
            test_targets = self._collect_test_targets(test_plan, test_results)
            rollback_method = self._build_rollback_method(changed_files)

            entry = {
                "changed_files": changed_files,
                "reason": reason,
                "impact_scope": impact_scope,
                "test_target": test_targets,
                "rollback_method": rollback_method,
            }
            key = ("|".join(changed_files), reason)
            if key not in seen_keys:
                entries.append(entry)
                seen_keys.add(key)

        if entries:
            return entries

        fallback_files = list(state.changed_files)
        if not fallback_files:
            return []

        return [
            {
                "changed_files": fallback_files,
                "reason": "Persisted workflow artifacts and generated outputs.",
                "impact_scope": ["documentation", "finalization"],
                "test_target": self._collect_test_targets(test_plan, test_results),
                "rollback_method": self._build_rollback_method(fallback_files),
            }
        ]

    def json_text(self, payload: dict[str, Any]) -> str:
        """Render a JSON payload as pretty-printed text."""
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    def _write_doc(
        self,
        *,
        state: WorkflowState,
        target_name: str,
        content: str,
    ) -> Path:
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        target_path = self.docs_dir / target_name
        target_path.write_text(content, encoding="utf-8")
        self._record_artifact(state, target_path)
        return target_path

    def _record_artifact(self, state: WorkflowState, path: str | Path) -> None:
        artifact_path = Path(path).as_posix()
        state.add_artifact(artifact_path)
        state.add_changed_file(artifact_path)

    def _as_dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _normalize_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _normalize_dict_list(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _collect_test_targets(
        self,
        test_plan: dict[str, Any],
        test_results: dict[str, Any],
    ) -> list[str]:
        targets: list[str] = []

        for item in self._normalize_dict_list(test_plan.get("test_cases")):
            name = str(item.get("name", "")).strip()
            if name and name not in targets:
                targets.append(name)

        for item in self._normalize_dict_list(test_results.get("executed_checks")):
            name = str(item.get("name", "")).strip()
            if name and name not in targets:
                targets.append(name)

        return targets

    def _build_rollback_method(self, changed_files: list[str]) -> str:
        if not changed_files:
            return "No rollback method recorded."
        if all(
            path.startswith("docs/") or path.startswith("artifacts/")
            for path in changed_files
        ):
            return "Restore the affected generated files from the previous committed versions or regenerate them from the last stable workflow state."
        return "Revert the affected files to the previous committed versions and re-run the targeted validation flow."

    def _build_finalization_next_actions(
        self,
        acceptance_gate: dict[str, Any],
    ) -> list[str]:
        if acceptance_gate.get("ready_for_completion"):
            return [
                "Review generated artifacts",
                "Promote approved changes into concrete implementation work",
            ]

        failed_checks = self._normalize_list(acceptance_gate.get("failed_checks"))
        actions: list[str] = []

        if "acceptance_criteria_defined" in failed_checks:
            actions.append(
                "Record explicit acceptance criteria before declaring completion"
            )
        if "tests_passing" in failed_checks:
            actions.append("Re-run targeted validation until the test status is passed")
        if "review_has_no_major_findings" in failed_checks:
            actions.append(
                "Resolve blocking review findings before declaring completion"
            )
        if "documentation_updated" in failed_checks:
            actions.append("Update and persist the required documentation artifacts")

        unresolved_issues = self._normalize_list(
            acceptance_gate.get("unresolved_issues")
        )
        if unresolved_issues:
            actions.append(
                "Keep unresolved issues explicitly tracked in the final handoff"
            )

        return actions or [
            "Review generated artifacts",
            "Promote approved changes into concrete implementation work",
        ]

    def _merge_unique_strings(self, *values: Any) -> list[str]:
        merged: list[str] = []
        for value in values:
            if not isinstance(value, list):
                continue
            for item in value:
                text = str(item).strip()
                if text and text not in merged:
                    merged.append(text)
        return merged

    def _count_list_like(self, value: Any) -> int:
        return len(value) if isinstance(value, list) else 0

    def _build_failure_report(
        self,
        results: dict[str, dict[str, Any] | None],
    ) -> dict[str, Any] | None:
        failed_steps: list[dict[str, Any]] = []

        for result_name, result_payload in results.items():
            if not isinstance(result_payload, dict):
                continue
            if result_payload.get("status") != "failed":
                continue

            next_actions = result_payload.get("next_actions")
            if not isinstance(next_actions, list):
                next_actions = []

            failed_steps.append(
                {
                    "result": result_name,
                    "summary": result_payload.get("summary"),
                    "failure_category": result_payload.get("failure_category"),
                    "failure_cause": result_payload.get("failure_cause"),
                    "next_actions": [
                        str(action) for action in next_actions if str(action).strip()
                    ],
                }
            )

        if not failed_steps:
            return None

        primary_failure = failed_steps[0]
        return {
            "failed_step_count": len(failed_steps),
            "primary_failure": primary_failure,
            "failed_steps": failed_steps,
            "next_actions": primary_failure["next_actions"],
        }

    def _format_list_or_none(self, value: Any) -> str:
        if not isinstance(value, list) or not value:
            return "none"
        return ", ".join(str(item) for item in value if str(item).strip()) or "none"
