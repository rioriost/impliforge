from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from devagents.agents.base import AgentResult
from devagents.orchestration.artifact_writer import WorkflowArtifactWriter
from devagents.orchestration.edit_phase import EditPhaseOrchestrator
from devagents.orchestration.workflow import create_workflow_state
from devagents.runtime.code_editing import CodeEditRequest
from devagents.runtime.editor import EditRequest


@dataclass
class DummySessionSnapshot:
    session_id: str
    token_usage_ratio: float = 0.5


class DummySessionManager:
    def build_resume_prompt(self, snapshot: DummySessionSnapshot) -> str:
        return f"resume:{snapshot.session_id}"


class DummyStateStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir

    def save_workflow_state(self, state: Any) -> Path:
        path = self.root_dir / "workflows" / state.workflow_id / "workflow-state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        return path

    def save_session_snapshot(self, snapshot: Any) -> Path:
        path = (
            self.root_dir / "sessions" / snapshot.session_id / "session-snapshot.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        return path

    def save_run_summary(self, workflow_id: str, summary: dict[str, Any]) -> Path:
        path = self.root_dir / "summaries" / workflow_id / "run-summary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(summary), encoding="utf-8")
        return path


class DummySafeEditResult:
    def __init__(
        self,
        *,
        ok: bool,
        changed: bool,
        relative_path: str,
        message: str = "",
    ) -> None:
        self.ok = ok
        self.changed = changed
        self.relative_path = relative_path
        self.message = message


class DummySafeEditor:
    def __init__(self, results: list[DummySafeEditResult] | None = None) -> None:
        self.results = results or []
        self.requests: list[EditRequest] = []

    def apply_many(self, requests: list[EditRequest]) -> list[DummySafeEditResult]:
        self.requests.extend(requests)
        return list(self.results)


class DummyCodeEditResult:
    def __init__(self, *, ok: bool, changed: bool) -> None:
        self.ok = ok
        self.changed = changed


class DummyCodeEditor:
    def __init__(self) -> None:
        self.requests: list[CodeEditRequest] = []

    def apply(self, request: CodeEditRequest) -> DummyCodeEditResult:
        self.requests.append(request)
        return DummyCodeEditResult(ok=True, changed=True)


def _build_state() -> Any:
    state = create_workflow_state(
        workflow_id="wf-test-001",
        requirement="Build a multi-agent workflow",
        model="gpt-5.4",
    )
    state.set_session("sess-test-001")
    state.update_task_status(
        "requirements_analysis",
        state.require_task("requirements_analysis").status.COMPLETED,
        note="requirements done",
    )
    state.update_task_status(
        "planning",
        state.require_task("planning").status.COMPLETED,
        note="planning done",
    )
    state.update_task_status(
        "documentation",
        state.require_task("documentation").status.COMPLETED,
        note="documentation done",
    )
    state.update_task_status(
        "implementation",
        state.require_task("implementation").status.COMPLETED,
        note="implementation done",
    )
    state.update_task_status(
        "test_design",
        state.require_task("test_design").status.COMPLETED,
        note="test design done",
    )
    state.update_task_status(
        "test_execution",
        state.require_task("test_execution").status.COMPLETED,
        note="test execution done",
    )
    state.update_task_status(
        "review",
        state.require_task("review").status.COMPLETED,
        note="review done",
    )
    return state


def _result(
    *,
    outputs: dict[str, Any] | None = None,
    artifacts: list[str] | None = None,
    next_actions: list[str] | None = None,
) -> AgentResult:
    return AgentResult.success(
        "ok",
        outputs=outputs or {},
        artifacts=artifacts or [],
        next_actions=next_actions or [],
    )


def test_workflow_artifact_writer_persists_outputs_and_finalizes(
    tmp_path: Path,
) -> None:
    docs_dir = tmp_path / "docs"
    store_root = tmp_path / "artifacts"

    writer = WorkflowArtifactWriter(
        docs_dir=docs_dir,
        state_store=DummyStateStore(store_root),
        session_manager=DummySessionManager(),
    )
    state = _build_state()

    requirements_result = _result(
        outputs={"normalized_requirements": {"objective": "x"}}
    )
    planning_result = _result(outputs={"plan": {"phases": ["plan"]}})
    documentation_result = _result(
        outputs={
            "documentation_bundle": {"design": "present", "runbook": "present"},
            "design_document": "# Design\n",
            "runbook_document": "# Runbook\n",
        }
    )
    implementation_result = _result(
        outputs={
            "implementation": {
                "change_slices": [
                    {"name": "slice-a", "summary": "first slice"},
                ]
            }
        }
    )
    test_design_result = _result(
        outputs={
            "test_plan": {"test_cases": ["case-1", "case-2"]},
            "test_plan_document": "# Test Plan\n",
        }
    )
    test_execution_result = _result(
        outputs={
            "test_results": {
                "status": "passed",
                "executed_checks": ["check-1"],
            }
        }
    )
    review_result = _result(
        outputs={
            "review": {
                "severity": "ok",
                "unresolved_issues": [],
                "fix_loop_required": False,
            }
        }
    )

    paths = writer.write_workflow_artifacts(
        state=state,
        requirement=state.requirement,
        requirements_result=requirements_result,
        planning_result=planning_result,
        documentation_result=documentation_result,
        implementation_result=implementation_result,
        test_design_result=test_design_result,
        test_execution_result=test_execution_result,
        review_result=review_result,
        fix_result=None,
        session_snapshot=DummySessionSnapshot(session_id="sess-test-001"),
    )

    assert (docs_dir / "final-summary.md").exists()
    assert "final-summary.md" in paths["final_summary"]
    assert state.require_task("finalization").outputs["next_actions"]
    assert state.require_task("finalization").status.value == "completed"
    assert any(path.endswith("workflow-state.json") for path in state.artifacts)
    assert any(path.endswith("run-summary.json") for path in state.artifacts)
    assert any(path.endswith("final-summary.md") for path in state.changed_files)


def test_edit_phase_builds_safe_edit_operations_for_docs_and_artifacts(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )
    orchestrator = EditPhaseOrchestrator(
        safe_editor=DummySafeEditor(),
        code_editor=DummyCodeEditor(),
        artifact_writer=writer,
    )
    state = _build_state()

    requirements_result = _result(
        outputs={"normalized_requirements": {"objective": "x"}}
    )
    planning_result = _result(outputs={"plan": {"phases": ["plan"]}})
    documentation_result = _result(
        outputs={
            "design_document": "# Design\n",
            "runbook_document": "# Runbook\n",
            "documentation_bundle": {"design": "present"},
        }
    )
    implementation_result = _result(
        outputs={"implementation": {"change_slices": [{"name": "slice-a"}]}}
    )
    test_design_result = _result(
        outputs={
            "test_plan": {"test_cases": ["case-1"]},
            "test_plan_document": "# Test Plan\n",
        }
    )
    test_execution_result = _result(
        outputs={
            "test_results": {"status": "passed", "executed_checks": ["check-1"]},
            "test_results_document": "# Test Results\n",
        }
    )
    review_result = _result(
        outputs={
            "review": {
                "severity": "ok",
                "unresolved_issues": [],
                "fix_loop_required": False,
            },
            "review_report": "# Review\n",
        }
    )
    fix_result = _result(
        outputs={
            "fix_plan": {"severity": "none"},
            "fix_report": "# Fix\n",
        }
    )

    operations = orchestrator.build_safe_edit_operations(
        state=state,
        requirement=state.requirement,
        requirements_result=requirements_result,
        planning_result=planning_result,
        documentation_result=documentation_result,
        implementation_result=implementation_result,
        test_design_result=test_design_result,
        test_execution_result=test_execution_result,
        review_result=review_result,
        fix_result=fix_result,
    )

    paths = [request.relative_path for request in operations]
    assert "docs/design.md" in paths
    assert "docs/runbook.md" in paths
    assert "docs/test-plan.md" in paths
    assert "docs/test-results.md" in paths
    assert "docs/review-report.md" in paths
    assert "docs/fix-report.md" in paths
    assert "docs/final-summary.md" in paths
    assert f"artifacts/workflows/{state.workflow_id}/workflow-details.json" in paths


def test_edit_phase_applies_safe_and_structured_edits_and_records_paths(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )
    safe_editor = DummySafeEditor(
        results=[
            DummySafeEditResult(
                ok=True,
                changed=True,
                relative_path="docs/design.md",
            ),
            DummySafeEditResult(
                ok=False,
                changed=False,
                relative_path="docs/review-report.md",
                message="denied",
            ),
        ]
    )
    code_editor = DummyCodeEditor()
    orchestrator = EditPhaseOrchestrator(
        safe_editor=safe_editor,
        code_editor=code_editor,
        artifact_writer=writer,
    )
    state = _build_state()

    implementation_result = _result(
        outputs={
            "implementation": {
                "edit_proposals": [
                    {
                        "targets": ["src/devagents/runtime/editor.py"],
                        "instructions": ["apply structured update"],
                        "edits": [
                            {
                                "edit_kind": "replace_block",
                                "target_symbol": "SafeEditor.apply",
                                "intent": "update editor apply",
                            }
                        ],
                    }
                ]
            }
        }
    )
    fix_result = _result(
        outputs={
            "fix_plan": {
                "edit_proposals": [
                    {
                        "targets": ["src/devagents/agents/implementation.py"],
                        "instructions": ["apply fix update"],
                        "edits": [
                            {
                                "edit_kind": "replace_block",
                                "target_symbol": "ImplementationAgent.run",
                                "intent": "update implementation agent",
                            }
                        ],
                    }
                ]
            }
        }
    )

    orchestrator.apply_safe_edit_phase(
        state=state,
        requirement=state.requirement,
        requirements_result=_result(outputs={"normalized_requirements": {}}),
        planning_result=_result(outputs={"plan": {}}),
        documentation_result=_result(
            outputs={
                "design_document": "# Design\n",
                "documentation_bundle": {},
            }
        ),
        implementation_result=implementation_result,
        test_design_result=_result(outputs={"test_plan": {}}),
        test_execution_result=_result(outputs={"test_results": {}}),
        review_result=_result(
            outputs={
                "review": {
                    "severity": "ok",
                    "unresolved_issues": [],
                    "fix_loop_required": False,
                }
            }
        ),
        fix_result=fix_result,
    )

    assert safe_editor.requests
    assert code_editor.requests
    assert "docs/design.md" in state.changed_files
    assert "src/devagents/runtime/editor.py" in state.changed_files
    assert "src/devagents/agents/implementation.py" in state.changed_files
    assert any("拒否" in note or "denied" in note for note in state.notes)
