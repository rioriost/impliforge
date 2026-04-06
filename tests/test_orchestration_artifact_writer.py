from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestration_test_helpers import (
    DummySessionManager,
    DummySessionSnapshot,
    DummyStateStore,
    build_state,
    result,
)

from devagents.agents.base import AgentResult
from devagents.orchestration.artifact_writer import WorkflowArtifactWriter
from devagents.orchestration.workflow import TaskStatus


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
    acceptance_gate = state.require_task("finalization").outputs["acceptance_gate"]

    assert acceptance_gate["ready_for_completion"] is False
    assert acceptance_gate["failed_checks"] == ["acceptance_criteria_defined"]
    assert state.require_task("finalization").outputs["next_actions"] == [
        "Record explicit acceptance criteria before declaring completion"
    ]
    assert state.require_task("finalization").status.value == "blocked"
    assert any(path.endswith("workflow-state.json") for path in state.artifacts)
    assert any(path.endswith("workflow-details.json") for path in state.artifacts)
    assert any(path.endswith("run-summary.json") for path in state.artifacts)
    assert "workflow_details" in paths
    assert paths["workflow_details"].endswith("workflow-details.json")
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


def make_failure_result(
    *,
    summary: str,
    outputs: dict[str, Any] | None = None,
    next_actions: list[str] | None = None,
    failure_category: str | None = None,
    failure_cause: str | None = None,
) -> AgentResult:
    return AgentResult.failure(
        summary,
        outputs=outputs or {},
        next_actions=next_actions or [],
        failure_category=failure_category,
        failure_cause=failure_cause,
    )


def test_result_to_dict_normalizes_blank_failure_summary(tmp_path: Path) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )

    failure_result = make_failure_result(
        summary=" \n\t ",
        outputs={"review": {"severity": "high"}},
        next_actions=["address review findings"],
        failure_category="validation",
        failure_cause="missing required summary",
    )

    assert writer.result_to_dict(failure_result) == {
        "status": "failed",
        "summary": "No summary provided.",
        "outputs": {"review": {"severity": "high"}},
        "artifacts": [],
        "next_actions": ["address review findings"],
        "risks": [],
        "metrics": {},
        "failure_category": "validation",
        "failure_cause": "missing required summary",
    }


def test_result_to_dict_fills_required_failure_fields_when_blank(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )

    failure_result = make_failure_result(
        summary="planning failed",
        outputs={"review": {"severity": "high"}},
        next_actions=["address review findings"],
        failure_category=" \n ",
        failure_cause="",
    )

    assert writer.result_to_dict(failure_result) == {
        "status": "failed",
        "summary": "planning failed",
        "outputs": {"review": {"severity": "high"}},
        "artifacts": [],
        "next_actions": ["address review findings"],
        "risks": [],
        "metrics": {},
        "failure_category": "unknown_failure",
        "failure_cause": "No failure cause provided.",
    }


def test_result_to_dict_uses_pre_normalized_agent_result_fields(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )

    normalized_result = AgentResult(
        status=" completed ",
        summary=" \n ",
        outputs={"review": {"severity": "low"}},
        artifacts=["docs/design.md", " ", "docs/design.md", "docs/runbook.md"],
        next_actions=["save docs", "", "review output", "review output"],
        risks=["schema drift", " ", "schema drift", "missing field"],
        metrics={"count": 2},
        failure_category=" \n ",
        failure_cause="",
    )

    assert writer.result_to_dict(normalized_result) == {
        "status": "completed",
        "summary": "No summary provided.",
        "outputs": {"review": {"severity": "low"}},
        "artifacts": ["docs/design.md", "docs/runbook.md"],
        "next_actions": ["save docs", "review output"],
        "risks": ["schema drift", "missing field"],
        "metrics": {"count": 2},
        "failure_category": None,
        "failure_cause": None,
    }


def test_build_workflow_details_payload_includes_all_phase_results(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )
    state = build_state()

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
    fix_result = result(
        outputs={
            "fix_plan": {
                "severity": "medium",
                "change_slices": ["fix-slice-a"],
            }
        },
        next_actions=["apply fix slice"],
    )

    payload = writer.build_workflow_details_payload(
        state=state,
        requirements_result=requirements_result,
        planning_result=planning_result,
        documentation_result=documentation_result,
        implementation_result=implementation_result,
        test_design_result=test_design_result,
        test_execution_result=test_execution_result,
        review_result=review_result,
        fix_result=fix_result,
    )

    assert payload["workflow"]["workflow_id"] == state.workflow_id
    assert payload["requirements_result"]["status"] == "completed"
    assert payload["planning_result"]["outputs"]["plan"]["phases"] == ["plan"]
    assert payload["documentation_result"]["outputs"]["design_document"] == "# Design\n"
    assert payload["implementation_result"]["outputs"]["implementation"] == {
        "change_slices": []
    }
    assert payload["test_design_result"]["outputs"]["test_plan"]["test_cases"] == [
        "case-1"
    ]
    assert payload["test_execution_result"]["outputs"]["test_results"]["status"] == (
        "passed"
    )
    assert payload["review_result"]["outputs"]["review"]["severity"] == "low"
    assert payload["fix_result"]["outputs"]["fix_plan"]["severity"] == "medium"


def test_build_approval_risk_summary_reports_explicit_approval_reasons(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )
    state = build_state()
    state.add_risk("dependency additions require explicit human approval")
    state.add_risk("High token usage triggered degraded routing mode")
    state.add_open_question("Who approves the dependency change?")
    state.require_task("implementation").mark_blocked("awaiting approval")

    results = {
        "implementation_result": {
            "status": "completed",
            "summary": "implementation ready",
            "outputs": {},
            "artifacts": [],
            "next_actions": [],
            "risks": ["security-impacting edits require explicit human approval"],
            "metrics": {},
            "failure_category": None,
            "failure_cause": None,
        },
        "review_result": {
            "status": "completed",
            "summary": "review complete",
            "outputs": {},
            "artifacts": [],
            "next_actions": [],
            "risks": ["dependency additions require explicit human approval"],
            "metrics": {},
            "failure_category": None,
            "failure_cause": None,
        },
    }

    summary = writer.build_approval_risk_summary(state=state, results=results)

    assert summary["approval_required"] is True
    assert summary["approval_reasons"] == [
        "dependency additions require explicit human approval",
        "security-impacting edits require explicit human approval",
    ]
    assert summary["risk_register"] == [
        "dependency additions require explicit human approval",
        "High token usage triggered degraded routing mode",
        "security-impacting edits require explicit human approval",
    ]
    assert summary["operator_visibility"] == {
        "phase": state.phase.value,
        "blocked_tasks": ["implementation"],
        "open_questions": ["Who approves the dependency change?"],
    }


def test_build_approval_risk_summary_marks_needs_human_input_phase(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )
    state = build_state()
    state.set_phase(state.phase.NEEDS_HUMAN_INPUT)

    summary = writer.build_approval_risk_summary(
        state=state,
        results={"review_result": None},
    )

    assert summary["approval_required"] is True
    assert summary["approval_reasons"] == [
        "Workflow entered needs_human_input phase; operator review or approval is required before continuation."
    ]
    assert summary["risk_register"] == []
    assert summary["operator_visibility"] == {
        "phase": "needs_human_input",
        "blocked_tasks": [],
        "open_questions": [],
    }


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
    assert payload["execution_trace"] == [
        event.to_dict() for event in state.execution_trace
    ]
    assert payload["results"]["requirements_result"]["status"] == "completed"
    assert payload["results"]["fix_result"] is None
    assert payload["acceptance_gate"]["ready_for_completion"] is False
    assert payload["acceptance_gate"]["failed_checks"] == [
        "acceptance_criteria_defined",
        "documentation_updated",
    ]
    assert payload["completion_evidence"] == {
        "mvp_artifacts_persisted": True,
        "acceptance_ready": False,
        "acceptance_criteria_count": 0,
        "completed_task_count": 7,
        "completed_tasks": [
            "requirements_analysis",
            "planning",
            "documentation",
            "implementation",
            "test_design",
            "test_execution",
            "review",
        ],
        "docs_artifacts": ["docs/design.md"],
        "artifact_count": 1,
        "deferred_open_question_count": 0,
        "unresolved_open_question_count": 0,
        "operator_checklist_evidence": {
            "persistent_context_recorded": True,
            "resume_context_available": True,
            "docs_reviewable_before_completion": True,
            "open_questions_resolved_or_deferred": True,
            "blocked_work_visible": True,
        },
    }
    assert writer.result_to_dict(None) is None

    noisy_result = AgentResult.success(
        "normalized",
        artifacts=["docs/design.md", " ", "", "docs/runbook.md"],
        next_actions=["save docs", "", "review output", "  "],
        risks=["schema drift", "", "schema drift", "  ", "missing field"],
    )

    assert writer.result_to_dict(noisy_result) == {
        "status": "completed",
        "summary": "normalized",
        "outputs": {},
        "artifacts": ["docs/design.md", "docs/runbook.md"],
        "next_actions": ["save docs", "review output"],
        "risks": ["schema drift", "missing field"],
        "metrics": {},
        "failure_category": None,
        "failure_cause": None,
    }

    missing_summary_result = AgentResult.success(
        "   ",
        artifacts=["docs/design.md"],
        next_actions=["review output"],
    )

    assert writer.result_to_dict(missing_summary_result) == {
        "status": "completed",
        "summary": "No summary provided.",
        "outputs": {},
        "artifacts": ["docs/design.md"],
        "next_actions": ["review output"],
        "risks": [],
        "metrics": {},
        "failure_category": None,
        "failure_cause": None,
    }


def test_result_to_dict_deduplicates_large_repeated_artifact_lists(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )

    repeated_artifacts = ["docs/design.md"] * 40 + ["docs/runbook.md"] * 35
    repeated_artifacts.extend(["", "   ", "artifacts/run-summary.json"] * 20)

    noisy_result = AgentResult.success(
        "normalized",
        artifacts=repeated_artifacts,
        next_actions=["save docs", "save docs", "", "review output", "review output"],
        risks=["schema drift", "schema drift", "", "missing field", "missing field"],
    )

    assert writer.result_to_dict(noisy_result) == {
        "status": "completed",
        "summary": "normalized",
        "outputs": {},
        "artifacts": [
            "docs/design.md",
            "docs/runbook.md",
            "artifacts/run-summary.json",
        ],
        "next_actions": ["save docs", "review output"],
        "risks": ["schema drift", "missing field"],
        "metrics": {},
        "failure_category": None,
        "failure_cause": None,
    }


def test_build_run_summary_payload_includes_change_impact_summary_from_slices(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )
    state = build_state()
    state.add_changed_file("docs/design.md")

    requirements_result = result(
        outputs={"normalized_requirements": {"objective": "x"}}
    )
    planning_result = result(outputs={"plan": {"phases": ["plan"]}})
    documentation_result = result(outputs={"design_document": "# Design\n"})
    implementation_result = result(
        outputs={
            "implementation": {
                "code_change_slices": [
                    {
                        "slice_id": "slice-a",
                        "goal": "Update design generation flow",
                        "targets": [
                            "src/devagents/orchestration/artifact_writer.py",
                            "tests/test_orchestration_artifact_writer.py",
                        ],
                        "depends_on": ["implementation", "finalization"],
                    }
                ]
            }
        }
    )
    test_design_result = result(
        outputs={
            "test_plan": {
                "test_cases": [
                    {
                        "name": "test_build_run_summary_payload_includes_change_impact_summary_from_slices"
                    }
                ]
            }
        }
    )
    test_execution_result = result(
        outputs={
            "test_results": {
                "status": "passed",
                "executed_checks": [
                    {
                        "name": "test_build_run_summary_payload_includes_change_impact_summary_from_slices"
                    }
                ],
            }
        }
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
    snapshot = DummySessionSnapshot(session_id="sess-test-001", token_usage_ratio=0.4)

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

    assert payload["change_impact_summary"] == [
        {
            "changed_files": [
                "src/devagents/orchestration/artifact_writer.py",
                "tests/test_orchestration_artifact_writer.py",
            ],
            "reason": "Update design generation flow",
            "impact_scope": ["implementation", "finalization"],
            "test_target": [
                "test_build_run_summary_payload_includes_change_impact_summary_from_slices"
            ],
            "rollback_method": "Revert the affected files to the previous committed versions and re-run the targeted validation flow.",
        }
    ]


def test_build_run_summary_payload_falls_back_to_state_changed_files_for_change_impact_summary(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )
    state = build_state()
    state.add_changed_file("docs/final-summary.md")
    state.add_changed_file("artifacts/summaries/wf-test-001/run-summary.json")

    requirements_result = result(
        outputs={"normalized_requirements": {"objective": "x"}}
    )
    planning_result = result(outputs={"plan": {"phases": ["plan"]}})
    documentation_result = result(outputs={"design_document": "# Design\n"})
    implementation_result = result(
        outputs={"implementation": {"code_change_slices": []}}
    )
    test_design_result = result(
        outputs={
            "test_plan": {
                "test_cases": [
                    {
                        "name": "test_build_run_summary_payload_falls_back_to_state_changed_files_for_change_impact_summary"
                    }
                ]
            }
        }
    )
    test_execution_result = result(
        outputs={
            "test_results": {
                "status": "passed",
                "executed_checks": [
                    {
                        "name": "test_build_run_summary_payload_falls_back_to_state_changed_files_for_change_impact_summary"
                    }
                ],
            }
        }
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
    snapshot = DummySessionSnapshot(session_id="sess-test-001", token_usage_ratio=0.4)

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

    assert payload["change_impact_summary"] == [
        {
            "changed_files": [
                "docs/final-summary.md",
                "artifacts/summaries/wf-test-001/run-summary.json",
            ],
            "reason": "Persisted workflow artifacts and generated outputs.",
            "impact_scope": ["documentation", "finalization"],
            "test_target": [
                "test_build_run_summary_payload_falls_back_to_state_changed_files_for_change_impact_summary"
            ],
            "rollback_method": "Restore the affected generated files from the previous committed versions or regenerate them from the last stable workflow state.",
        }
    ]


def test_build_run_summary_payload_preserves_failure_visibility_and_next_actions(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )
    state = build_state()
    state.add_artifact("artifacts/workflows/wf-test-001/workflow-details.json")
    state.add_open_question("Need operator confirmation")
    state.add_risk("review found unresolved issue")

    requirements_result = result(
        outputs={"normalized_requirements": {"objective": "x"}}
    )
    planning_result = result(
        outputs={"plan": {"phases": ["plan"], "next_actions": ["review plan"]}}
    )
    documentation_result = result(
        outputs={
            "design_document": "# Design\n",
            "open_questions": ["Need operator confirmation"],
        }
    )
    implementation_result = result(
        outputs={"implementation": {"change_slices": ["slice-a"]}},
        next_actions=["apply implementation slice"],
    )
    test_design_result = result(
        outputs={"test_plan": {"test_cases": ["case-1"]}},
        next_actions=["persist test plan"],
    )
    test_execution_result = result(
        outputs={
            "test_results": {
                "status": "failed",
                "executed_checks": ["check-1"],
                "failure_summary": "pytest failed",
            }
        },
        next_actions=["inspect failing test output"],
    )
    review_result = result(
        outputs={
            "review": {
                "severity": "high",
                "unresolved_issues": ["missing validation"],
                "fix_loop_required": True,
            }
        },
        next_actions=["address review findings"],
    )
    review_result.risks.append("blocking review issue remains")
    fix_result = result(
        outputs={
            "fix_plan": {
                "severity": "critical",
                "change_slices": ["fix-slice-a"],
            }
        },
        next_actions=["apply highest-priority fix slice"],
    )
    snapshot = DummySessionSnapshot(session_id="sess-test-001", token_usage_ratio=0.91)

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
        fix_result=fix_result,
        session_snapshot=snapshot,
    )

    assert payload["session"]["token_usage_ratio"] == 0.91
    assert payload["artifacts"] == list(state.artifacts)
    assert payload["summary"]["open_questions"] == [
        "Need operator confirmation",
    ]
    assert payload["summary"]["risks"] == [
        "review found unresolved issue",
        "blocking review issue remains",
    ]
    assert payload["results"]["test_execution_result"]["next_actions"] == [
        "inspect failing test output"
    ]
    assert payload["results"]["review_result"]["next_actions"] == [
        "address review findings"
    ]
    assert payload["results"]["review_result"]["risks"] == [
        "blocking review issue remains"
    ]
    assert (
        payload["results"]["test_execution_result"]["outputs"]["test_results"][
            "failure_summary"
        ]
        == "pytest failed"
    )
    assert payload["results"]["review_result"]["outputs"]["review"][
        "unresolved_issues"
    ] == ["missing validation"]
    assert payload["results"]["fix_result"]["next_actions"] == [
        "apply highest-priority fix slice"
    ]
    assert (
        payload["results"]["fix_result"]["outputs"]["fix_plan"]["severity"]
        == "critical"
    )


def test_build_run_summary_payload_includes_failure_report_and_primary_next_actions(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )
    state = build_state()

    requirements_result = result(
        outputs={"normalized_requirements": {"objective": "x"}}
    )
    planning_result = make_failure_result(
        summary="planning failed",
        outputs={"open_questions": ["Need architecture decision"]},
        next_actions=[
            "Clarify the architecture decision",
            "Retry planning with the chosen direction",
        ],
        failure_category="design_inconsistency",
        failure_cause="architecture decision is still unresolved",
    )
    documentation_result = result(outputs={"design_document": "# Design\n"})
    implementation_result = result(outputs={"implementation": {"change_slices": []}})
    test_design_result = result(outputs={"test_plan": {"test_cases": ["case-1"]}})
    test_execution_result = result(
        outputs={"test_results": {"status": "skipped", "executed_checks": []}}
    )
    review_result = result(
        outputs={
            "review": {
                "severity": "unknown",
                "unresolved_issues": [],
                "fix_loop_required": False,
            }
        }
    )
    snapshot = DummySessionSnapshot(session_id="sess-test-001", token_usage_ratio=0.2)

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

    assert payload["results"]["planning_result"]["status"] == "failed"
    assert (
        payload["results"]["planning_result"]["failure_category"]
        == "design_inconsistency"
    )
    assert (
        payload["results"]["planning_result"]["failure_cause"]
        == "architecture decision is still unresolved"
    )
    assert payload["results"]["planning_result"]["next_actions"] == [
        "Clarify the architecture decision",
        "Retry planning with the chosen direction",
    ]
    assert payload["failure_report"]["failed_step_count"] == 1
    assert payload["failure_report"]["primary_failure"] == {
        "result": "planning_result",
        "summary": "planning failed",
        "failure_category": "design_inconsistency",
        "failure_cause": "architecture decision is still unresolved",
        "next_actions": [
            "Clarify the architecture decision",
            "Retry planning with the chosen direction",
        ],
    }
    assert payload["failure_report"]["next_actions"] == [
        "Clarify the architecture decision",
        "Retry planning with the chosen direction",
    ]
    assert payload["failure_report"]["operator_summary"] == "planning failed"
    assert payload["failure_report"]["operator_visibility"] == {
        "has_failures": True,
        "primary_result": "planning_result",
        "primary_failure_category": "design_inconsistency",
        "primary_failure_cause": "architecture decision is still unresolved",
        "recommended_next_actions": [
            "Clarify the architecture decision",
            "Retry planning with the chosen direction",
        ],
    }


def test_build_run_summary_payload_fills_missing_failed_required_fields(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )
    state = build_state()

    requirements_result = result(
        outputs={"normalized_requirements": {"objective": "x"}}
    )
    planning_result = make_failure_result(
        summary="planning failed",
        outputs={"open_questions": ["Need architecture decision"]},
        next_actions=["Clarify the architecture decision"],
        failure_category=" ",
        failure_cause=" \n ",
    )
    documentation_result = result(outputs={"design_document": "# Design\n"})
    implementation_result = result(outputs={"implementation": {"change_slices": []}})
    test_design_result = result(outputs={"test_plan": {"test_cases": ["case-1"]}})
    test_execution_result = result(
        outputs={"test_results": {"status": "skipped", "executed_checks": []}}
    )
    review_result = result(
        outputs={
            "review": {
                "severity": "unknown",
                "unresolved_issues": [],
                "fix_loop_required": False,
            }
        }
    )
    snapshot = DummySessionSnapshot(session_id="sess-test-001", token_usage_ratio=0.2)

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

    assert (
        payload["results"]["planning_result"]["failure_category"] == "unknown_failure"
    )
    assert (
        payload["results"]["planning_result"]["failure_cause"]
        == "No failure cause provided."
    )
    assert payload["failure_report"]["primary_failure"] == {
        "result": "planning_result",
        "summary": "planning failed",
        "failure_category": "unknown_failure",
        "failure_cause": "No failure cause provided.",
        "next_actions": ["Clarify the architecture decision"],
    }
    assert payload["failure_report"]["operator_summary"] == "planning failed"
    assert payload["failure_report"]["operator_visibility"] == {
        "has_failures": True,
        "primary_result": "planning_result",
        "primary_failure_category": "unknown_failure",
        "primary_failure_cause": "No failure cause provided.",
        "recommended_next_actions": ["Clarify the architecture decision"],
    }


def test_build_acceptance_gate_reports_ready_for_completion_when_all_checks_pass(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )
    state = build_state()
    state.add_changed_file("docs/design.md")

    acceptance_gate = writer.build_acceptance_gate(
        state=state,
        requirements_result=result(
            outputs={
                "normalized_requirements": {
                    "objective": "x",
                    "acceptance_criteria": ["Tests pass", "Docs updated"],
                }
            }
        ),
        documentation_result=result(
            outputs={"documentation_bundle": {"design": "present"}}
        ),
        test_execution_result=result(
            outputs={"test_results": {"status": "passed", "executed_checks": []}}
        ),
        review_result=result(
            outputs={
                "review": {
                    "severity": "low",
                    "unresolved_issues": [],
                    "fix_loop_required": False,
                }
            }
        ),
    )

    assert acceptance_gate["ready_for_completion"] is True
    assert acceptance_gate["failed_checks"] == []
    assert acceptance_gate["acceptance_criteria"] == [
        "Tests pass",
        "Docs updated",
    ]
    assert acceptance_gate["documentation_updated"] is True
    assert acceptance_gate["test_status"] == "passed"
    assert acceptance_gate["review_severity"] == "low"
    assert acceptance_gate["unresolved_issues"] == []
    assert acceptance_gate["open_questions"] == []
    assert acceptance_gate["resolved_decisions"] == []
    assert acceptance_gate["unresolved_open_questions"] == []


def test_build_final_summary_renders_acceptance_gate_when_present(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )
    state = build_state()
    state.require_task("finalization").outputs.update(
        {
            "acceptance_gate": {
                "ready_for_completion": False,
                "failed_checks": [
                    "tests_passing",
                    "documentation_updated",
                    "open_questions_resolved_or_deferred",
                ],
                "test_status": "failed",
                "review_severity": "high",
                "documentation_updated": False,
                "unresolved_issues": ["missing validation"],
                "open_questions": ["Who approves rollout?"],
                "resolved_decisions": ["Persist workflow state"],
                "unresolved_open_questions": ["Who approves rollout?"],
            },
            "next_actions": ["Re-run validation", "Update docs"],
        }
    )

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
                    "unresolved_issues": ["missing validation"],
                    "fix_loop_required": True,
                }
            }
        ),
        fix_result=result(
            outputs={"fix_plan": {"severity": "critical", "change_slices": "invalid"}}
        ),
    )

    assert "## Acceptance Gate" in summary
    assert "- ready_for_completion: False" in summary
    assert (
        "- failed_checks: tests_passing, documentation_updated, open_questions_resolved_or_deferred"
        in summary
    )
    assert "- test_status: failed" in summary
    assert "- review_severity: high" in summary
    assert "- documentation_updated: False" in summary
    assert "- unresolved_issues: missing validation" in summary
    assert "- open_questions: Who approves rollout?" in summary
    assert "- resolved_decisions: Persist workflow state" in summary
    assert "- unresolved_open_questions: Who approves rollout?" in summary
    assert "## Completion Evidence" in summary
    assert "- mvp_artifacts_persisted: False" in summary
    assert "- completed_task_count: 7" in summary
    assert (
        "- completed_tasks: requirements_analysis, planning, documentation, implementation, test_design, test_execution, review"
        in summary
    )
    assert "- artifact_count: 0" in summary
    assert "- docs_artifacts: none" in summary
    assert "## Operator Checklist Evidence" in summary
    assert "- persistent_context_recorded: False" in summary
    assert "- resume_context_available: True" in summary
    assert "- docs_reviewable_before_completion: False" in summary
    assert "- open_questions_resolved_or_deferred: False" in summary
    assert "- blocked_work_visible: True" in summary
    assert "- Re-run validation" in summary
    assert "- Update docs" in summary


def test_build_acceptance_gate_blocks_when_open_questions_remain_unresolved(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )
    state = build_state()
    state.add_open_question("Who approves rollout?")

    acceptance_gate = writer.build_acceptance_gate(
        state=state,
        requirements_result=result(
            outputs={
                "normalized_requirements": {
                    "objective": "x",
                    "acceptance_criteria": ["Tests pass"],
                    "open_questions": ["Who approves rollout?"],
                    "resolved_decisions": [],
                }
            }
        ),
        documentation_result=result(
            outputs={
                "documentation_bundle": {"design": "present"},
                "open_questions": ["Who approves rollout?"],
                "resolved_decisions": [],
            }
        ),
        test_execution_result=result(
            outputs={"test_results": {"status": "passed", "executed_checks": []}}
        ),
        review_result=result(
            outputs={
                "review": {
                    "severity": "low",
                    "unresolved_issues": [],
                    "fix_loop_required": False,
                },
                "open_questions": ["Who approves rollout?"],
                "resolved_decisions": [],
            }
        ),
    )

    assert acceptance_gate["ready_for_completion"] is False
    assert acceptance_gate["failed_checks"] == ["open_questions_resolved_or_deferred"]
    assert acceptance_gate["open_questions"] == ["Who approves rollout?"]
    assert acceptance_gate["resolved_decisions"] == []
    assert acceptance_gate["unresolved_open_questions"] == ["Who approves rollout?"]


def test_build_acceptance_gate_allows_explicitly_deferred_open_questions(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )
    state = build_state()
    state.add_open_question("Who approves rollout?")

    acceptance_gate = writer.build_acceptance_gate(
        state=state,
        requirements_result=result(
            outputs={
                "normalized_requirements": {
                    "objective": "x",
                    "acceptance_criteria": ["Tests pass"],
                    "open_questions": ["Who approves rollout?"],
                    "resolved_decisions": [],
                    "deferred_open_questions": ["Who approves rollout?"],
                }
            }
        ),
        documentation_result=result(
            outputs={
                "documentation_bundle": {"design": "present"},
                "open_questions": ["Who approves rollout?"],
                "resolved_decisions": [],
                "deferred_open_questions": ["Who approves rollout?"],
            }
        ),
        test_execution_result=result(
            outputs={"test_results": {"status": "passed", "executed_checks": []}}
        ),
        review_result=result(
            outputs={
                "review": {
                    "severity": "low",
                    "unresolved_issues": [],
                    "fix_loop_required": False,
                },
                "open_questions": ["Who approves rollout?"],
                "resolved_decisions": [],
                "deferred_open_questions": ["Who approves rollout?"],
            }
        ),
    )

    assert acceptance_gate["ready_for_completion"] is True
    assert acceptance_gate["failed_checks"] == []
    assert acceptance_gate["open_questions"] == ["Who approves rollout?"]
    assert acceptance_gate["resolved_decisions"] == []
    assert acceptance_gate["deferred_open_questions"] == ["Who approves rollout?"]
    assert acceptance_gate["unresolved_open_questions"] == []


def test_build_final_summary_includes_deferred_open_questions(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )
    state = build_state()
    state.add_artifact("docs/design.md")
    state.update_task_status(
        "finalization",
        TaskStatus.BLOCKED,
        outputs={
            "acceptance_gate": {
                "ready_for_completion": False,
                "failed_checks": [],
                "test_status": "passed",
                "review_severity": "low",
                "documentation_updated": True,
                "unresolved_issues": [],
                "open_questions": ["Who approves rollout?"],
                "resolved_decisions": [],
                "deferred_open_questions": ["Who approves rollout?"],
                "unresolved_open_questions": [],
            },
            "next_actions": ["Review generated artifacts"],
        },
    )

    summary = writer.build_final_summary(
        state=state,
        requirement=state.requirement,
        implementation_result=result(outputs={"implementation": {"change_slices": []}}),
        test_design_result=result(outputs={"test_plan": {"test_cases": []}}),
        test_execution_result=result(
            outputs={"test_results": {"status": "passed", "executed_checks": []}}
        ),
        review_result=result(
            outputs={
                "review": {
                    "severity": "low",
                    "unresolved_issues": [],
                    "fix_loop_required": False,
                }
            }
        ),
        fix_result=None,
    )

    assert "- deferred_open_questions: Who approves rollout?" in summary


def test_build_finalization_next_actions_includes_open_question_defer_guidance(
    tmp_path: Path,
) -> None:
    writer = WorkflowArtifactWriter(
        docs_dir=tmp_path / "docs",
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )

    actions = writer._build_finalization_next_actions(
        {
            "ready_for_completion": False,
            "failed_checks": ["open_questions_resolved_or_deferred"],
            "unresolved_issues": [],
        }
    )

    assert actions == [
        "Resolve or explicitly defer every remaining open question before declaring completion"
    ]


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
    assert "## Acceptance Gate" not in summary
    assert "- Review generated artifacts" in summary
    assert "- Promote approved changes into concrete implementation work" in summary
