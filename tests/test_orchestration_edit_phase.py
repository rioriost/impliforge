from __future__ import annotations

from pathlib import Path

from orchestration_test_helpers import (
    DummyCodeEditor,
    DummySafeEditor,
    DummySafeEditResult,
    DummySessionManager,
    DummyStateStore,
    build_state,
    result,
)

from devagents.orchestration.artifact_writer import WorkflowArtifactWriter
from devagents.orchestration.edit_phase import EditPhaseOrchestrator
from devagents.runtime.code_editing import CodeEditKind, CodeEditRiskFlag


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
    state = build_state()

    requirements_result = result(
        outputs={"normalized_requirements": {"objective": "x"}}
    )
    planning_result = result(outputs={"plan": {"phases": ["plan"]}})
    documentation_result = result(
        outputs={
            "design_document": "# Design\n",
            "runbook_document": "# Runbook\n",
            "documentation_bundle": {"design": "present"},
        }
    )
    implementation_result = result(
        outputs={"implementation": {"change_slices": [{"name": "slice-a"}]}}
    )
    test_design_result = result(
        outputs={
            "test_plan": {"test_cases": ["case-1"]},
            "test_plan_document": "# Test Plan\n",
        }
    )
    test_execution_result = result(
        outputs={
            "test_results": {"status": "passed", "executed_checks": ["check-1"]},
            "test_results_document": "# Test Results\n",
        }
    )
    review_result = result(
        outputs={
            "review": {
                "severity": "ok",
                "unresolved_issues": [],
                "fix_loop_required": False,
            },
            "review_report": "# Review\n",
        }
    )
    fix_result = result(
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
    state = build_state()

    implementation_result = result(
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
    fix_result = result(
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
        requirements_result=result(outputs={"normalized_requirements": {}}),
        planning_result=result(outputs={"plan": {}}),
        documentation_result=result(
            outputs={
                "design_document": "# Design\n",
                "documentation_bundle": {},
            }
        ),
        implementation_result=implementation_result,
        test_design_result=result(outputs={"test_plan": {}}),
        test_execution_result=result(outputs={"test_results": {}}),
        review_result=result(
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


def test_edit_phase_ignores_non_src_targets_in_fix_proposals(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )
    code_editor = DummyCodeEditor()
    orchestrator = EditPhaseOrchestrator(
        safe_editor=DummySafeEditor(),
        code_editor=code_editor,
        artifact_writer=writer,
    )

    requests = orchestrator.build_structured_fix_code_edit_requests(
        {
            "edit_proposals": [
                {
                    "targets": [
                        "docs/design.md",
                        "src/devagents/runtime/editor.py",
                    ],
                    "instructions": ["apply fix update"],
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
    )

    assert len(requests) == 1
    assert requests[0].relative_path == "src/devagents/runtime/editor.py"
    assert requests[0].kind is CodeEditKind.REPLACE_MARKED_BLOCK
    assert requests[0].risk_flags == ()


def test_edit_phase_builds_structured_code_edit_requests_with_risk_flags(
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

    requests = orchestrator.build_structured_code_edit_requests(
        {
            "edit_proposals": [
                {
                    "targets": ["src/devagents/runtime/editor.py"],
                    "instructions": ["apply structured update"],
                    "risk_flags": [
                        "dependency_change",
                        "security_impact",
                        "dependency_change",
                        "unknown_flag",
                    ],
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
    )

    assert len(requests) == 1
    assert requests[0].relative_path == "src/devagents/runtime/editor.py"
    assert requests[0].kind is CodeEditKind.REPLACE_MARKED_BLOCK
    assert requests[0].risk_flags == (
        CodeEditRiskFlag.DEPENDENCY_CHANGE,
        CodeEditRiskFlag.SECURITY_IMPACT,
    )


def test_edit_phase_records_note_when_structured_code_edit_is_denied(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )

    class DeniedCodeEditResult:
        def __init__(self) -> None:
            self.ok = False
            self.changed = False

    class DeniedCodeEditor:
        def __init__(self) -> None:
            self.requests = []

        def apply(self, request):
            self.requests.append(request)
            return DeniedCodeEditResult()

    code_editor = DeniedCodeEditor()
    orchestrator = EditPhaseOrchestrator(
        safe_editor=DummySafeEditor(),
        code_editor=code_editor,
        artifact_writer=writer,
    )
    state = build_state()

    implementation_result = result(
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

    orchestrator.apply_safe_edit_phase(
        state=state,
        requirement=state.requirement,
        requirements_result=result(outputs={"normalized_requirements": {}}),
        planning_result=result(outputs={"plan": {}}),
        documentation_result=result(
            outputs={
                "design_document": "# Design\n",
                "documentation_bundle": {},
            }
        ),
        implementation_result=implementation_result,
        test_design_result=result(outputs={"test_plan": {}}),
        test_execution_result=result(outputs={"test_results": {}}),
        review_result=result(
            outputs={
                "review": {
                    "severity": "ok",
                    "unresolved_issues": [],
                    "fix_loop_required": False,
                }
            }
        ),
        fix_result=None,
    )

    assert code_editor.requests
    assert "src/devagents/runtime/editor.py" not in state.changed_files
    assert any("safe edit phase" in note for note in state.notes)
