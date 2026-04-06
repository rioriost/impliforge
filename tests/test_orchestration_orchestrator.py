from __future__ import annotations

import asyncio
from pathlib import Path

from orchestration_test_helpers import DummyAgent

from devagents.agents.base import AgentResult, AgentTask
from devagents.orchestration.orchestrator import Orchestrator
from devagents.orchestration.workflow import (
    TaskStatus,
    WorkflowPhase,
    create_workflow_state,
)


def make_state() -> object:
    return create_workflow_state(
        workflow_id="wf-test-001",
        requirement="Build a multi-agent workflow",
        model="gpt-5.4",
    )


def test_dispatch_returns_agent_result_and_passes_task_and_state() -> None:
    state = make_state()
    task = AgentTask(
        name="requirements_analysis",
        objective="Normalize the incoming requirement",
        inputs={"requirement": state.requirement},
    )
    result = AgentResult.success("requirements complete", outputs={"normalized": True})
    agent = DummyAgent("requirements", result)
    orchestrator = Orchestrator(
        requirements_agent=agent,
        planning_agent=DummyAgent("planner", AgentResult.success("unused")),
    )

    dispatched = asyncio.run(orchestrator.dispatch(agent, task, state))

    assert dispatched == result
    assert len(agent.calls) == 1
    assert agent.calls[0].name == "requirements_analysis"
    assert agent.calls[0].inputs == {"requirement": "Build a multi-agent workflow"}


def test_collect_results_and_finalize_return_compact_summary() -> None:
    state = make_state()
    state.set_phase(WorkflowPhase.TESTING)
    state.update_task_status("requirements_analysis", TaskStatus.COMPLETED)
    state.update_task_status("planning", TaskStatus.IN_PROGRESS)
    state.update_task_status("implementation", TaskStatus.BLOCKED)
    state.update_task_status("review", TaskStatus.FAILED)
    state.add_artifact("artifacts/plan.md")
    state.add_note("note-1")
    state.add_open_question("question-1")
    state.add_risk("risk-1")
    state.add_changed_file("src/example.py")
    state.record_event(
        "manual_check",
        task_id="planning",
        status="observed",
        summary="Collected for summary output.",
        details={"source": "test"},
    )

    orchestrator = Orchestrator(
        requirements_agent=DummyAgent("requirements", AgentResult.success("unused")),
        planning_agent=DummyAgent("planner", AgentResult.success("unused")),
    )

    collected = orchestrator.collect_results(state)
    finalized = orchestrator.finalize(state)

    assert collected == finalized
    assert collected["workflow_id"] == "wf-test-001"
    assert collected["phase"] == "testing"
    assert collected["model"] == "gpt-5.4"
    assert collected["task_counts"] == {
        "pending": 4,
        "in_progress": 1,
        "blocked": 1,
        "completed": 1,
        "failed": 1,
    }
    assert collected["artifacts"] == ["artifacts/plan.md"]
    assert collected["notes"] == ["note-1"]
    assert collected["open_questions"] == ["question-1"]
    assert collected["risks"] == ["risk-1"]
    assert collected["changed_files"] == ["src/example.py"]
    assert collected["execution_trace"][-1] == {
        "event_type": "manual_check",
        "phase": "testing",
        "task_id": "planning",
        "agent_name": None,
        "status": "observed",
        "summary": "Collected for summary output.",
        "details": {"source": "test"},
        "timestamp": collected["execution_trace"][-1]["timestamp"],
    }


def test_handle_failure_marks_phase_task_and_note() -> None:
    state = make_state()
    orchestrator = Orchestrator(
        requirements_agent=DummyAgent("requirements", AgentResult.success("unused")),
        planning_agent=DummyAgent("planner", AgentResult.success("unused")),
    )

    returned = orchestrator.handle_failure(
        state,
        step_name="planning",
        reason="planner crashed",
    )

    assert returned is state
    assert state.phase == WorkflowPhase.FAILED
    assert state.require_task("planning").status == TaskStatus.FAILED
    assert state.require_task("planning").notes[-1] == "planner crashed"
    assert state.notes[-1] == "planning failed: planner crashed"


def test_apply_result_success_collects_outputs_risks_and_artifacts() -> None:
    state = make_state()
    orchestrator = Orchestrator(
        requirements_agent=DummyAgent("requirements", AgentResult.success("unused")),
        planning_agent=DummyAgent("planner", AgentResult.success("unused")),
    )
    result = AgentResult.success(
        "requirements complete",
        outputs={
            "open_questions": ["Need API auth", "", "Need API auth"],
            "changed_files": ["src/a.py", "", "src/a.py"],
            "normalized_requirements": {"objective": "x"},
        },
        artifacts=["artifacts/reqs.md", "artifacts/reqs.md"],
        risks=["risk-a", "", "risk-a"],
    )

    orchestrator._apply_result(
        state,
        phase=WorkflowPhase.REQUIREMENTS_ANALYZED,
        completed_step="requirements_analysis",
        result=result,
    )

    task = state.require_task("requirements_analysis")
    assert task.status == TaskStatus.COMPLETED
    assert task.outputs["normalized_requirements"] == {"objective": "x"}
    assert state.phase == WorkflowPhase.REQUIREMENTS_ANALYZED
    assert state.notes[-1] == "requirements complete"
    assert state.open_questions == ["Need API auth"]
    assert state.changed_files == ["src/a.py"]
    assert state.risks == ["risk-a"]
    assert state.artifacts == ["artifacts/reqs.md"]


def test_apply_result_failure_uses_unknown_failure_when_summary_empty() -> None:
    state = make_state()
    orchestrator = Orchestrator(
        requirements_agent=DummyAgent("requirements", AgentResult.success("unused")),
        planning_agent=DummyAgent("planner", AgentResult.success("unused")),
    )
    result = AgentResult.failure("", outputs={"open_questions": ["ignored"]})

    orchestrator._apply_result(
        state,
        phase=WorkflowPhase.PLANNED,
        completed_step="planning",
        result=result,
    )

    assert state.phase == WorkflowPhase.FAILED
    assert state.require_task("planning").status == TaskStatus.FAILED
    assert state.notes[-1] == "planning failed: No summary provided."
    assert state.open_questions == []


def test_dispatch_normalizes_blank_and_noisy_agent_result_fields() -> None:
    state = make_state()
    raw_result = AgentResult(
        status=" completed ",
        summary=" \n ",
        outputs={"normalized_requirements": {"objective": "x"}},
        artifacts=["artifacts/reqs.md", " ", "artifacts/reqs.md"],
        next_actions=["review output", "", "review output"],
        risks=["risk-a", " ", "risk-a"],
        metrics={"count": 1},
        failure_category=" \n ",
        failure_cause="",
    )
    agent = DummyAgent("requirements", raw_result)
    orchestrator = Orchestrator(
        requirements_agent=agent,
        planning_agent=DummyAgent("planner", AgentResult.success("unused")),
    )

    result = asyncio.run(
        orchestrator.dispatch(
            agent,
            AgentTask(
                name="requirements_analysis",
                objective="Normalize the incoming requirement",
                inputs={"requirement": "Build a workflow"},
            ),
            state,
        )
    )

    assert result.status == "completed"
    assert result.summary == "No summary provided."
    assert result.outputs == {"normalized_requirements": {"objective": "x"}}
    assert result.artifacts == ["artifacts/reqs.md", "artifacts/reqs.md"]
    assert result.next_actions == ["review output", "review output"]
    assert result.risks == ["risk-a", "risk-a"]
    assert result.metrics == {"count": 1}
    assert result.failure_category is None
    assert result.failure_cause is None
    assert len(agent.calls) == 1


def test_dispatch_fills_required_failed_result_fields() -> None:
    state = make_state()
    raw_result = AgentResult(
        status="failed",
        summary="",
        outputs={"open_questions": ["Need API auth"]},
        artifacts=[" ", "artifacts/failure.md"],
        next_actions=["retry planning", ""],
        risks=["schema drift", ""],
        metrics={},
        failure_category=" \t ",
        failure_cause=" \n ",
    )
    agent = DummyAgent("planner", raw_result)
    orchestrator = Orchestrator(
        requirements_agent=DummyAgent("requirements", AgentResult.success("unused")),
        planning_agent=agent,
    )

    result = asyncio.run(
        orchestrator.dispatch(
            agent,
            AgentTask(
                name="planning",
                objective="Create an implementation plan",
                inputs={"requirement": "Build a workflow"},
            ),
            state,
        )
    )

    assert result.status == "failed"
    assert result.summary == "No summary provided."
    assert result.artifacts == ["artifacts/failure.md"]
    assert result.next_actions == ["retry planning"]
    assert result.risks == ["schema drift"]
    assert result.failure_category == "unknown_failure"
    assert result.failure_cause == "No failure cause provided."
    assert len(agent.calls) == 1


def test_finalize_success_marks_pending_dependency_tasks_as_skipped() -> None:
    state = make_state()
    state.update_task_status("requirements_analysis", TaskStatus.COMPLETED)
    state.update_task_status("planning", TaskStatus.COMPLETED)

    orchestrator = Orchestrator(
        requirements_agent=DummyAgent("requirements", AgentResult.success("unused")),
        planning_agent=DummyAgent("planner", AgentResult.success("unused")),
    )

    orchestrator._finalize_success(state)

    assert state.require_task("documentation").status == TaskStatus.SKIPPED
    assert state.require_task("review").status == TaskStatus.SKIPPED
    assert state.require_task("finalization").status == TaskStatus.COMPLETED
    assert state.require_task("finalization").outputs["next_actions"] == [
        "Persist final workflow summary",
        "Review generated artifacts",
    ]
    assert state.phase == WorkflowPhase.COMPLETED
    assert state.notes[-1] == "Workflow completed."
    assert state.execution_trace[-1].event_type == "workflow_completed"
    assert state.execution_trace[-1].task_id == "finalization"
    assert state.execution_trace[-1].status == "completed"
    assert state.execution_trace[-1].details["skipped_dependencies"] == [
        "documentation",
        "review",
    ]


def test_minimal_orchestrator_completes_and_skips_optional_tasks(
    tmp_path: Path,
) -> None:
    requirements_agent = DummyAgent(
        "requirements",
        AgentResult.success(
            "requirements complete",
            outputs={"normalized_requirements": {"objective": "x"}},
        ),
    )
    planning_agent = DummyAgent(
        "planner",
        AgentResult.success(
            "planning complete",
            outputs={"plan": {"phases": ["plan"]}},
        ),
    )

    orchestrator = Orchestrator(
        requirements_agent=requirements_agent,
        planning_agent=planning_agent,
        artifacts_dir=tmp_path / "artifacts",
    )

    state = asyncio.run(orchestrator.run("Build a multi-agent workflow"))

    assert state.phase.value == "completed"
    assert state.require_task("requirements_analysis").status.value == "completed"
    assert state.require_task("planning").status.value == "completed"
    assert state.require_task("implementation").status.value == "skipped"
    assert state.require_task("test_design").status.value == "skipped"
    assert state.require_task("test_execution").status.value == "skipped"
    assert state.require_task("review").status.value == "skipped"
    assert state.require_task("documentation").status.value == "skipped"
    assert state.require_task("finalization").status.value == "completed"
    assert state.require_task("finalization").outputs["next_actions"] == [
        "Persist final workflow summary",
        "Review generated artifacts",
    ]
    assert requirements_agent.calls
    assert planning_agent.calls


def test_minimal_orchestrator_marks_failure_on_agent_error(
    tmp_path: Path,
) -> None:
    requirements_agent = DummyAgent(
        "requirements",
        AgentResult.failure(
            "requirements failed",
            outputs={"open_questions": ["missing requirement detail"]},
        ),
    )
    planning_agent = DummyAgent(
        "planner",
        AgentResult.success(
            "planning complete",
            outputs={"plan": {"phases": ["plan"]}},
        ),
    )

    orchestrator = Orchestrator(
        requirements_agent=requirements_agent,
        planning_agent=planning_agent,
        artifacts_dir=tmp_path / "artifacts",
    )

    state = asyncio.run(orchestrator.run("Build a multi-agent workflow"))

    assert state.phase.value == "failed"
    assert state.require_task("requirements_analysis").status.value == "failed"
    assert state.require_task("planning").status.value == "pending"
    assert any(
        "requirements_analysis failed: requirements failed" == note
        for note in state.notes
    )
    assert "missing requirement detail" not in state.open_questions
    assert len(planning_agent.calls) == 0


def test_orchestrator_runs_all_configured_agents_and_collects_outputs(
    tmp_path: Path,
) -> None:
    requirements_agent = DummyAgent(
        "requirements",
        AgentResult.success(
            "requirements complete",
            outputs={"normalized_requirements": {"objective": "x"}},
            artifacts=["artifacts/requirements.md"],
            risks=["requirements-risk"],
        ),
    )
    planning_agent = DummyAgent(
        "planner",
        AgentResult.success(
            "planning complete",
            outputs={
                "plan": {"phases": ["implement", "test", "review"]},
                "open_questions": ["Which API version?"],
            },
            artifacts=["artifacts/plan.md"],
            risks=["planning-risk"],
        ),
    )
    implementation_agent = DummyAgent(
        "implementer",
        AgentResult.success(
            "implementation complete",
            outputs={"changed_files": ["src/devagents/orchestration/orchestrator.py"]},
            artifacts=["artifacts/implementation.patch"],
            risks=["implementation-risk"],
        ),
    )
    test_agent = DummyAgent(
        "tester",
        AgentResult.success(
            "tests complete",
            outputs={"changed_files": ["tests/test_orchestration_orchestrator.py"]},
            artifacts=["artifacts/test-report.txt"],
            risks=["test-risk"],
        ),
    )
    review_agent = DummyAgent(
        "reviewer",
        AgentResult.success(
            "review complete",
            outputs={"open_questions": ["Need follow-up cleanup?"]},
            artifacts=["artifacts/review.md"],
            risks=["review-risk"],
        ),
    )

    orchestrator = Orchestrator(
        requirements_agent=requirements_agent,
        planning_agent=planning_agent,
        implementation_agent=implementation_agent,
        test_agent=test_agent,
        review_agent=review_agent,
        artifacts_dir=tmp_path / "artifacts",
    )

    state = asyncio.run(orchestrator.run("Build a multi-agent workflow"))

    assert state.phase == WorkflowPhase.COMPLETED
    assert state.require_task("requirements_analysis").status == TaskStatus.COMPLETED
    assert state.require_task("planning").status == TaskStatus.COMPLETED
    assert state.require_task("implementation").status == TaskStatus.COMPLETED
    assert state.require_task("test_execution").status == TaskStatus.COMPLETED
    assert state.require_task("review").status == TaskStatus.COMPLETED
    assert state.require_task("documentation").status == TaskStatus.SKIPPED
    assert state.require_task("finalization").status == TaskStatus.COMPLETED

    assert requirements_agent.calls[0].name == "requirements_analysis"
    assert planning_agent.calls[0].name == "planning"
    assert planning_agent.calls[0].inputs["requirements_outputs"] == {
        "normalized_requirements": {"objective": "x"}
    }
    assert implementation_agent.calls[0].name == "implementation"
    assert implementation_agent.calls[0].inputs["plan"] == {
        "plan": {"phases": ["implement", "test", "review"]},
        "open_questions": ["Which API version?"],
    }
    assert test_agent.calls[0].name == "test_execution"
    assert test_agent.calls[0].inputs == {"requirement": "Build a multi-agent workflow"}
    assert review_agent.calls[0].name == "review"
    assert review_agent.calls[0].inputs == {
        "requirement": "Build a multi-agent workflow"
    }

    assert state.open_questions == ["Which API version?", "Need follow-up cleanup?"]
    assert state.changed_files == [
        "src/devagents/orchestration/orchestrator.py",
        "tests/test_orchestration_orchestrator.py",
    ]
    assert state.artifacts == [
        "artifacts/requirements.md",
        "artifacts/plan.md",
        "artifacts/implementation.patch",
        "artifacts/test-report.txt",
        "artifacts/review.md",
    ]
    assert state.risks == [
        "requirements-risk",
        "planning-risk",
        "implementation-risk",
        "test-risk",
        "review-risk",
    ]

    event_types = [event.event_type for event in state.execution_trace]
    assert event_types[0] == "workflow_initialized"
    assert event_types.count("task_dispatched") == 5
    assert event_types.count("task_completed") == 5
    assert event_types.count("phase_changed") >= 5
    assert event_types[-1] == "workflow_completed"

    dispatched_events = [
        event
        for event in state.execution_trace
        if event.event_type == "task_dispatched"
    ]
    assert [event.task_id for event in dispatched_events] == [
        "requirements_analysis",
        "planning",
        "implementation",
        "test_execution",
        "review",
    ]
    assert [event.agent_name for event in dispatched_events] == [
        "requirements",
        "planner",
        "implementer",
        "tester",
        "reviewer",
    ]

    completed_events = [
        event for event in state.execution_trace if event.event_type == "task_completed"
    ]
    assert [event.task_id for event in completed_events] == [
        "requirements_analysis",
        "planning",
        "implementation",
        "test_execution",
        "review",
    ]
    assert completed_events[0].details["output_keys"] == ["normalized_requirements"]
    assert completed_events[1].details["open_question_count"] == 1
    assert completed_events[2].details["changed_file_count"] == 1
    assert completed_events[4].summary == "review complete"


def test_orchestrator_stops_on_implementation_failure(
    tmp_path: Path,
) -> None:
    requirements_agent = DummyAgent(
        "requirements",
        AgentResult.success("requirements complete"),
    )
    planning_agent = DummyAgent(
        "planner",
        AgentResult.success("planning complete", outputs={"plan": {"phases": ["x"]}}),
    )
    implementation_agent = DummyAgent(
        "implementer",
        AgentResult.failure("implementation failed"),
    )
    test_agent = DummyAgent(
        "tester",
        AgentResult.success("tests complete"),
    )
    review_agent = DummyAgent(
        "reviewer",
        AgentResult.success("review complete"),
    )

    orchestrator = Orchestrator(
        requirements_agent=requirements_agent,
        planning_agent=planning_agent,
        implementation_agent=implementation_agent,
        test_agent=test_agent,
        review_agent=review_agent,
        artifacts_dir=tmp_path / "artifacts",
    )

    state = asyncio.run(orchestrator.run("Build a multi-agent workflow"))

    assert state.phase == WorkflowPhase.FAILED
    assert state.require_task("implementation").status == TaskStatus.FAILED
    assert state.require_task("test_execution").status == TaskStatus.PENDING
    assert state.require_task("review").status == TaskStatus.PENDING
    assert len(test_agent.calls) == 0
    assert len(review_agent.calls) == 0
    assert state.notes[-1] == "implementation failed: implementation failed"

    failed_events = [
        event for event in state.execution_trace if event.event_type == "task_failed"
    ]
    assert len(failed_events) == 1
    assert failed_events[0].task_id == "implementation"
    assert failed_events[0].status == "failed"
    assert failed_events[0].details == {"reason": "implementation failed"}


def test_orchestrator_stops_on_test_failure(
    tmp_path: Path,
) -> None:
    requirements_agent = DummyAgent(
        "requirements",
        AgentResult.success("requirements complete"),
    )
    planning_agent = DummyAgent(
        "planner",
        AgentResult.success("planning complete", outputs={"plan": {"phases": ["x"]}}),
    )
    implementation_agent = DummyAgent(
        "implementer",
        AgentResult.success("implementation complete"),
    )
    test_agent = DummyAgent(
        "tester",
        AgentResult.failure("tests failed"),
    )
    review_agent = DummyAgent(
        "reviewer",
        AgentResult.success("review complete"),
    )

    orchestrator = Orchestrator(
        requirements_agent=requirements_agent,
        planning_agent=planning_agent,
        implementation_agent=implementation_agent,
        test_agent=test_agent,
        review_agent=review_agent,
        artifacts_dir=tmp_path / "artifacts",
    )

    state = asyncio.run(orchestrator.run("Build a multi-agent workflow"))

    assert state.phase == WorkflowPhase.FAILED
    assert state.require_task("implementation").status == TaskStatus.COMPLETED
    assert state.require_task("test_execution").status == TaskStatus.FAILED
    assert state.require_task("review").status == TaskStatus.PENDING
    assert len(review_agent.calls) == 0
    assert state.notes[-1] == "test_execution failed: tests failed"


def test_orchestrator_stops_on_review_failure(
    tmp_path: Path,
) -> None:
    requirements_agent = DummyAgent(
        "requirements",
        AgentResult.success("requirements complete"),
    )
    planning_agent = DummyAgent(
        "planner",
        AgentResult.success("planning complete", outputs={"plan": {"phases": ["x"]}}),
    )
    implementation_agent = DummyAgent(
        "implementer",
        AgentResult.success("implementation complete"),
    )
    test_agent = DummyAgent(
        "tester",
        AgentResult.success("tests complete"),
    )
    review_agent = DummyAgent(
        "reviewer",
        AgentResult.failure("review failed"),
    )

    orchestrator = Orchestrator(
        requirements_agent=requirements_agent,
        planning_agent=planning_agent,
        implementation_agent=implementation_agent,
        test_agent=test_agent,
        review_agent=review_agent,
        artifacts_dir=tmp_path / "artifacts",
    )

    state = asyncio.run(orchestrator.run("Build a multi-agent workflow"))

    assert state.phase == WorkflowPhase.FAILED
    assert state.require_task("implementation").status == TaskStatus.COMPLETED
    assert state.require_task("test_execution").status == TaskStatus.COMPLETED
    assert state.require_task("review").status == TaskStatus.FAILED
    assert state.require_task("finalization").status == TaskStatus.PENDING
    assert state.notes[-1] == "review failed: review failed"


def test_workflow_summary_includes_ready_and_blocked_dependency_details() -> None:
    state = make_state()
    state.update_task_status("requirements_analysis", TaskStatus.COMPLETED)

    summary = state.summary()

    assert summary["task_counts"]["ready"] == 1
    assert summary["task_counts"]["skipped"] == 0
    assert summary["ready_tasks"] == ["planning"]
    assert summary["blocked_task_details"] == {
        "documentation": ["planning"],
        "implementation": ["planning"],
        "test_design": ["planning"],
        "test_execution": ["implementation", "test_design"],
        "review": ["implementation", "test_execution"],
        "finalization": ["documentation", "review"],
    }


def test_workflow_ready_tasks_excludes_non_pending_and_dependency_blocked_tasks() -> (
    None
):
    state = make_state()
    state.update_task_status("requirements_analysis", TaskStatus.COMPLETED)
    state.update_task_status("planning", TaskStatus.IN_PROGRESS)

    ready_tasks = state.ready_tasks()
    blocked_details = state.blocked_task_details()

    assert ready_tasks == []
    assert blocked_details == {
        "documentation": ["planning"],
        "implementation": ["planning"],
        "test_design": ["planning"],
        "test_execution": ["implementation", "test_design"],
        "review": ["implementation", "test_execution"],
        "finalization": ["documentation", "review"],
    }
