from __future__ import annotations

from pathlib import Path

from orchestration_test_helpers import (
    DummySessionManager,
    DummySessionSnapshot,
    DummyStateStore,
    build_state,
    result,
)

from devagents.orchestration.artifact_writer import WorkflowArtifactWriter


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
    state = build_state()

    requirements_result = result(
        outputs={"normalized_requirements": {"objective": "x"}}
    )
    planning_result = result(outputs={"plan": {"phases": ["plan"]}})
    documentation_result = result(
        outputs={
            "documentation_bundle": {"design": "present", "runbook": "present"},
            "design_document": "# Design\n",
            "runbook_document": "# Runbook\n",
        }
    )
    implementation_result = result(
        outputs={
            "implementation": {
                "change_slices": [
                    {"name": "slice-a", "summary": "first slice"},
                ]
            }
        }
    )
    test_design_result = result(
        outputs={
            "test_plan": {"test_cases": ["case-1", "case-2"]},
            "test_plan_document": "# Test Plan\n",
        }
    )
    test_execution_result = result(
        outputs={
            "test_results": {
                "status": "passed",
                "executed_checks": ["check-1"],
            }
        }
    )
    review_result = result(
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


def test_persist_documentation_and_text_outputs_only_write_non_blank_strings(
    tmp_path: Path,
) -> None:
    docs_dir = tmp_path / "docs"
    writer = WorkflowArtifactWriter(
        docs_dir=docs_dir,
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )
    state = build_state()

    writer.persist_documentation_outputs(
        state=state,
        result=result(
            outputs={
                "design_document": "# Design\n",
                "runbook_document": "   ",
            }
        ),
    )
    writer.persist_text_output(
        state=state,
        result=result(outputs={"test_plan_document": "# Test Plan\n"}),
        output_key="test_plan_document",
        target_name="test-plan.md",
    )
    writer.persist_text_output(
        state=state,
        result=result(outputs={"test_plan_document": None}),
        output_key="test_plan_document",
        target_name="ignored.md",
    )

    assert (docs_dir / "design.md").read_text(encoding="utf-8") == "# Design\n"
    assert (docs_dir / "test-plan.md").read_text(encoding="utf-8") == "# Test Plan\n"
    assert not (docs_dir / "runbook.md").exists()
    assert not (docs_dir / "ignored.md").exists()
    assert (docs_dir / "design.md").as_posix() in state.artifacts
    assert (docs_dir / "test-plan.md").as_posix() in state.changed_files


def test_build_run_summary_payload_and_result_to_dict_handle_optional_fix_result(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )
    state = build_state()
    state.add_artifact("docs/design.md")

    requirements_result = result(
        outputs={"normalized_requirements": {"objective": "x"}}
    )
    planning_result = result(outputs={"plan": {"phases": ["plan"]}})
    documentation_result = result(outputs={"design_document": "# Design\n"})
    implementation_result = result(outputs={"implementation": {"change_slices": []}})
    test_design_result = result(outputs={"test_plan": {"test_cases": ["case-1"]}})
    test_execution_result = result(
        outputs={"test_results": {"status": "passed", "executed_checks": ["check-1"]}}
    )
    review_result = result(
        outputs={
            "review": {
                "severity": "low",
                "unresolved_issues": [],
                "fix_loop_required": False,
            }
        }
    )
    snapshot = DummySessionSnapshot(session_id="sess-test-001", token_usage_ratio=0.75)

    payload = writer.build_run_summary_payload(
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
        session_snapshot=snapshot,
    )

    assert payload["workflow_id"] == state.workflow_id
    assert payload["session"]["session_id"] == "sess-test-001"
    assert payload["session"]["token_usage_ratio"] == 0.75
    assert payload["session"]["resume_prompt"] == "resume:sess-test-001"
    assert payload["artifacts"] == list(state.artifacts)
    assert payload["results"]["requirements_result"]["status"] == "completed"
    assert payload["results"]["fix_result"] is None
    assert writer.result_to_dict(None) is None


def test_build_final_summary_uses_defaults_for_non_list_values_and_missing_actions(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )
    state = build_state()
    state.require_task("finalization").outputs["next_actions"] = "not-a-list"

    summary = writer.build_final_summary(
        state=state,
        requirement=state.requirement,
        implementation_result=result(
            outputs={"implementation": {"change_slices": "invalid"}}
        ),
        test_design_result=result(outputs={"test_plan": {"test_cases": "invalid"}}),
        test_execution_result=result(
            outputs={"test_results": {"status": "failed", "executed_checks": "invalid"}}
        ),
        review_result=result(
            outputs={
                "review": {
                    "severity": "high",
                    "unresolved_issues": "invalid",
                    "fix_loop_required": True,
                }
            }
        ),
        fix_result=result(
            outputs={"fix_plan": {"severity": "critical", "change_slices": "invalid"}}
        ),
    )

    assert "## Proposed Code Change Slices" in summary
    assert "- none" in summary
    assert "- test_case_count: 0" in summary
    assert "- executed_check_count: 0" in summary
    assert "- unresolved_issues: none" in summary
    assert "- fix_needed: True" in summary
    assert "- fix_severity: critical" in summary
    assert "- fix_slice_count: 0" in summary
    assert "- Review generated artifacts" in summary
    assert "- Promote approved changes into concrete implementation work" in summary
