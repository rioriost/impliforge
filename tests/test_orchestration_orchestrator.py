from __future__ import annotations

import asyncio
from pathlib import Path

from orchestration_test_helpers import DummyAgent

from devagents.agents.base import AgentResult
from devagents.orchestration.orchestrator import Orchestrator


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
