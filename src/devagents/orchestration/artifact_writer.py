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
        finalization_task.mark_completed(
            outputs={
                "next_actions": [
                    "Expand safe edit phase from docs/artifacts into source-code allowlists",
                    "Add session resume flow using resume_session",
                    "Promote fix loop outputs into concrete code edits when needed",
                ]
            }
        )
        state.update_task_status(
            "finalization",
            TaskStatus.COMPLETED,
            note="成果物保存と次アクション整理を完了した。",
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
        return {
            "workflow_id": state.workflow_id,
            "model": state.model,
            "phase": state.phase.value,
            "requirement": requirement,
            "summary": state.summary(),
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
            "results": {
                "requirements_result": self.result_to_dict(requirements_result),
                "planning_result": self.result_to_dict(planning_result),
                "documentation_result": self.result_to_dict(documentation_result),
                "implementation_result": self.result_to_dict(implementation_result),
                "test_design_result": self.result_to_dict(test_design_result),
                "test_execution_result": self.result_to_dict(test_execution_result),
                "review_result": self.result_to_dict(review_result),
                "fix_result": self.result_to_dict(fix_result) if fix_result else None,
            },
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

        next_actions = (
            state.require_task("finalization").outputs.get("next_actions", [])
            if state.get_task("finalization") is not None
            else []
        )
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
        }

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

    def _count_list_like(self, value: Any) -> int:
        return len(value) if isinstance(value, list) else 0

    def _format_list_or_none(self, value: Any) -> str:
        if not isinstance(value, list) or not value:
            return "none"
        return ", ".join(str(item) for item in value if str(item).strip()) or "none"
