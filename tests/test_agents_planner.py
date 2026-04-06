from __future__ import annotations

import asyncio

from impliforge.agents.base import AgentTask
from impliforge.agents.planner import PlanningAgent
from impliforge.orchestration.workflow import create_workflow_state


def build_state():
    return create_workflow_state(
        workflow_id="wf-planner-001",
        requirement="Ship a planner-backed workflow",
        model="gpt-5.4",
    )


def test_run_builds_plan_from_normalized_requirements() -> None:
    agent = PlanningAgent()
    state = build_state()
    normalized = {
        "objective": "Deliver a resumable workflow",
        "constraints": [" keep Copilot SDK isolated ", "use uv"],
        "acceptance_criteria": [" restore sessions ", "route models by task "],
        "open_questions": [" clarify approval flow "],
    }
    task = AgentTask(
        name="planning",
        objective="Create implementation plan",
        inputs={"normalized_requirements": normalized},
    )

    result = asyncio.run(agent.run(task, state))

    assert result.status == "completed"
    assert result.is_success is True
    assert "実行計画" in result.summary

    plan = result.outputs["plan"]
    assert plan["goal"] == "Deliver a resumable workflow"
    assert plan["constraints"] == ["keep Copilot SDK isolated", "use uv"]
    assert plan["acceptance_criteria"] == [
        "restore sessions",
        "route models by task",
    ]
    assert plan["open_questions"] == ["clarify approval flow"]
    assert plan["resolved_decisions"] == []
    assert plan["inferred_capabilities"] == []
    assert plan["out_of_scope"] == []
    assert plan["deliverables"] == [
        "docs/implementation-plan.md",
        "artifacts/workflow-state.json",
        "artifacts/run-summary.json",
    ]
    assert plan["next_actions"] == result.next_actions
    assert len(plan["phases"]) == 4
    assert [item["task_id"] for item in plan["task_breakdown"]] == [
        "requirements_analysis",
        "planning",
        "documentation",
        "implementation",
        "test_design",
        "test_execution",
        "review",
        "finalization",
    ]
    assert result.outputs["open_questions"] == ["clarify approval flow"]
    assert result.risks == [
        "実エージェント追加前は最小フローのみ実行可能",
        "未解決の open questions が残っているため、後続実装で確認が必要",
    ]
    assert result.metrics == {
        "constraint_count": 2,
        "acceptance_criteria_count": 2,
        "open_question_count": 1,
        "resolved_decision_count": 0,
        "inferred_capability_count": 0,
        "out_of_scope_count": 0,
        "task_count": 8,
        "objective_length": len("Deliver a resumable workflow"),
        "long_objective_detected": False,
        "long_objective_threshold": 4000,
    }


def test_run_falls_back_to_state_requirement_and_empty_lists() -> None:
    agent = PlanningAgent()
    state = build_state()
    task = AgentTask(
        name="planning",
        objective="Create implementation plan",
        inputs={"normalized_requirements": "not-a-dict"},
    )

    result = asyncio.run(agent.run(task, state))

    assert result.status == "completed"
    plan = result.outputs["plan"]
    assert plan["goal"] == state.requirement
    assert plan["constraints"] == []
    assert plan["acceptance_criteria"] == []
    assert plan["open_questions"] == []
    assert plan["resolved_decisions"] == []
    assert plan["inferred_capabilities"] == []
    assert plan["out_of_scope"] == []
    assert result.outputs["open_questions"] == []
    assert result.risks == ["実エージェント追加前は最小フローのみ実行可能"]
    assert result.metrics == {
        "constraint_count": 0,
        "acceptance_criteria_count": 0,
        "open_question_count": 0,
        "resolved_decision_count": 0,
        "inferred_capability_count": 0,
        "out_of_scope_count": 0,
        "task_count": 8,
        "objective_length": len(state.requirement),
        "long_objective_detected": False,
        "long_objective_threshold": 4000,
    }


def test_get_normalized_requirements_returns_dict_only() -> None:
    agent = PlanningAgent()

    task_with_dict = AgentTask(
        name="planning",
        objective="Create implementation plan",
        inputs={"normalized_requirements": {"objective": "x"}},
    )
    task_with_other = AgentTask(
        name="planning",
        objective="Create implementation plan",
        inputs={"normalized_requirements": ["x"]},
    )

    assert agent._get_normalized_requirements(task_with_dict) == {"objective": "x"}
    assert agent._get_normalized_requirements(task_with_other) == {}


def test_normalize_list_trims_and_filters_values() -> None:
    agent = PlanningAgent()

    assert agent._normalize_list([" keep ", "", "   ", 42, None, "done"]) == [
        "keep",
        "42",
        "None",
        "done",
    ]
    assert agent._normalize_list("not-a-list") == []


def test_run_preserves_requirement_context_fields_in_plan_and_metrics() -> None:
    agent = PlanningAgent()
    state = build_state()
    task = AgentTask(
        name="planning",
        objective="Create implementation plan",
        inputs={
            "normalized_requirements": {
                "objective": "Deliver a resumable workflow",
                "constraints": ["keep changes small"],
                "acceptance_criteria": ["planner returns a plan"],
                "open_questions": ["Need approval owner"],
                "resolved_decisions": ["Persist workflow state to artifacts"],
                "inferred_capabilities": ["resume workflow", "route models by task"],
                "out_of_scope": ["web ui"],
            }
        },
    )

    result = asyncio.run(agent.run(task, state))

    plan = result.outputs["plan"]
    assert plan["resolved_decisions"] == ["Persist workflow state to artifacts"]
    assert plan["inferred_capabilities"] == [
        "resume workflow",
        "route models by task",
    ]
    assert plan["out_of_scope"] == ["web ui"]
    assert result.metrics["resolved_decision_count"] == 1
    assert result.metrics["inferred_capability_count"] == 2
    assert result.metrics["out_of_scope_count"] == 1


def test_run_records_long_objective_metrics_without_changing_plan_shape() -> None:
    agent = PlanningAgent()
    state = build_state()
    long_objective = "Long requirement slice " * 250
    task = AgentTask(
        name="planning",
        objective="Create implementation plan",
        inputs={
            "normalized_requirements": {
                "objective": long_objective,
                "constraints": ["keep changes small"],
                "acceptance_criteria": ["planner returns a plan"],
                "open_questions": [],
            }
        },
    )

    result = asyncio.run(agent.run(task, state))

    plan = result.outputs["plan"]
    assert result.status == "completed"
    assert plan["goal"] == long_objective.strip()
    assert plan["constraints"] == ["keep changes small"]
    assert plan["acceptance_criteria"] == ["planner returns a plan"]
    assert plan["resolved_decisions"] == []
    assert plan["inferred_capabilities"] == []
    assert plan["out_of_scope"] == []
    assert result.metrics["objective_length"] == len(long_objective.strip())
    assert result.metrics["long_objective_detected"] is True
    assert result.metrics["long_objective_threshold"] == 4000
    assert result.metrics["resolved_decision_count"] == 0
    assert result.metrics["inferred_capability_count"] == 0
    assert result.metrics["out_of_scope_count"] == 0
    assert result.metrics["task_count"] == 8
