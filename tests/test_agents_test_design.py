from __future__ import annotations

import asyncio

from impliforge.agents.base import AgentTask
from impliforge.agents.test_design import TestDesignAgent
from impliforge.orchestration.workflow import WorkflowState


def _state(requirement: str = "Fallback workflow requirement") -> WorkflowState:
    return WorkflowState(workflow_id="wf-test-design", requirement=requirement)


def test_run_builds_test_plan_document_and_metrics() -> None:
    agent = TestDesignAgent()
    task = AgentTask(
        name="test_design",
        objective="Design tests",
        inputs={
            "normalized_requirements": {
                "objective": "Validate orchestrator behavior",
                "constraints": ["Keep tests focused", "Avoid broad integration scope"],
                "acceptance_criteria": [
                    "Artifacts are persisted",
                    "Routing decisions are visible",
                ],
                "open_questions": ["Should review block completion?"],
            },
            "plan": {
                "task_breakdown": [
                    {
                        "task_id": "plan-1",
                        "objective": "Add focused agent tests",
                        "depends_on": ["requirements"],
                    }
                ]
            },
            "implementation": {
                "code_change_slices": [
                    {
                        "slice_id": "slice-1",
                        "goal": "Cover success path",
                        "targets": ["impliforge/tests/test_agents_test_design.py"],
                        "depends_on": ["plan-1"],
                    }
                ]
            },
            "documentation_bundle": {
                "design": "# Design",
                "runbook": "# Runbook",
            },
            "copilot_response": "Draft validation notes " * 40,
        },
    )

    result = asyncio.run(agent.run(task, _state()))

    assert result.is_success is True
    assert result.summary == "テスト計画と検証シナリオを生成した。"
    assert result.artifacts == ["docs/test-plan.md"]
    assert result.next_actions == [
        "docs/test-plan.md を保存する",
        "test_execution agent に test_plan を渡す",
        "review agent に検証観点を渡す",
    ]
    assert "未解決の open questions" in result.risks[1]

    test_plan = result.outputs["test_plan"]
    assert test_plan["objective"] == "Validate orchestrator behavior"
    assert test_plan["acceptance_criteria"] == [
        "Artifacts are persisted",
        "Routing decisions are visible",
    ]
    assert test_plan["constraints"] == [
        "Keep tests focused",
        "Avoid broad integration scope",
    ]
    assert test_plan["task_breakdown"] == [
        {
            "task_id": "plan-1",
            "objective": "Add focused agent tests",
            "depends_on": ["requirements"],
        }
    ]
    assert test_plan["code_change_slices"] == [
        {
            "slice_id": "slice-1",
            "goal": "Cover success path",
            "targets": ["impliforge/tests/test_agents_test_design.py"],
            "depends_on": ["plan-1"],
        }
    ]
    assert test_plan["documentation_inputs"] == {
        "design_present": True,
        "runbook_present": True,
    }
    assert test_plan["open_questions"] == ["Should review block completion?"]
    assert len(test_plan["copilot_response_excerpt"]) == 500
    assert (
        test_plan["copilot_response_excerpt"]
        == (task.inputs["copilot_response"].strip()[:500])
    )

    case_ids = [item["case_id"] for item in test_plan["test_cases"]]
    assert "unit-routing-selection" in case_ids
    assert "acceptance-1" in case_ids
    assert "acceptance-2" in case_ids
    assert "slice-slice-1" in case_ids
    assert "risk-open-questions" in case_ids

    assert result.metrics == {
        "acceptance_criteria_count": 2,
        "task_breakdown_count": 1,
        "code_change_slice_count": 1,
        "test_case_count": len(test_plan["test_cases"]),
        "open_question_count": 1,
    }

    document = result.outputs["test_plan_document"]
    assert document.startswith("# Test Plan\n")
    assert "## Objective\nValidate orchestrator behavior\n" in document
    assert "## Test Levels\n- unit:" in document
    assert "## Acceptance Criteria Coverage\n- Artifacts are persisted" in document
    assert "## Test Cases\n- `unit-routing-selection` (unit):" in document
    assert "  - assertion: ModelRouter returns a selected_model" in document
    assert "## Fixtures and Data\n- Sample requirement file" in document
    assert (
        "## Environment Assumptions\n"
        "- Use `uv run` so execution uses the repository-managed Python environment\n"
        "- Default execution does not require explicit Copilot SDK path overrides when environment paths are unset\n"
        "- If `working_directory` or `config_dir` is configured, each path must already exist as a directory before SDK execution\n"
        in document
    )
    assert (
        "## Validation Commands\n"
        "- uv run python -m impliforge requirements/sample-requirement.md --routing-mode quality\n"
        "- uv run python -m impliforge requirements/sample-requirement.md --token-usage-ratio 0.9\n"
        in document
    )
    assert (
        "## Operator Environment Signals\n"
        "- Record the selected routing mode in operator-facing outputs\n"
        "- Record token usage ratio when available for degraded-routing visibility\n"
        "- Surface configured environment path validation failures before SDK execution\n"
        in document
    )
    assert "## Open Questions\n- Should review block completion?" in document
    assert "## Copilot Draft Notes\n" in document
    assert document.endswith("\n")


def test_run_uses_state_requirement_and_handles_missing_optional_inputs() -> None:
    agent = TestDesignAgent()
    state = _state("Requirement from workflow state")
    task = AgentTask(
        name="test_design",
        objective="Design tests",
        inputs={
            "normalized_requirements": {
                "constraints": "not-a-list",
                "acceptance_criteria": None,
                "open_questions": [],
            },
            "plan": {"task_breakdown": ["invalid"]},
            "implementation": {"code_change_slices": ["invalid"]},
            "documentation_bundle": {},
            "copilot_response": "",
        },
    )

    result = asyncio.run(agent.run(task, state))

    assert result.is_success is True
    assert result.outputs["open_questions"] == []
    assert result.risks == [
        "実テスト実行エージェント未接続のため、現時点では計画中心の検証に留まる"
    ]

    test_plan = result.outputs["test_plan"]
    assert test_plan["objective"] == "Requirement from workflow state"
    assert test_plan["constraints"] == []
    assert test_plan["acceptance_criteria"] == []
    assert test_plan["task_breakdown"] == []
    assert test_plan["code_change_slices"] == []
    assert test_plan["documentation_inputs"] == {
        "design_present": False,
        "runbook_present": False,
    }
    assert test_plan["copilot_response_excerpt"] == ""

    case_ids = [item["case_id"] for item in test_plan["test_cases"]]
    assert case_ids == [
        "unit-routing-selection",
        "unit-session-snapshot",
        "integration-orchestrator-flow",
        "integration-artifact-persistence",
        "e2e-cli-quality-mode",
        "unit-environment-preflight-signals",
        "integration-operator-environment-signals",
    ]

    assert result.metrics == {
        "acceptance_criteria_count": 0,
        "task_breakdown_count": 0,
        "code_change_slice_count": 0,
        "test_case_count": 7,
        "open_question_count": 0,
    }

    document = result.outputs["test_plan_document"]
    assert "## Acceptance Criteria Coverage\n- none\n" in document
    assert "## Open Questions\n- none\n" in document
    assert "## Copilot Draft Notes\nNo additional notes.\n" in document


def test_render_helpers_and_normalizers_cover_notable_branches() -> None:
    agent = TestDesignAgent()

    assert agent._render_test_levels(None) == ["- none"]
    assert agent._render_test_levels(["invalid"]) == ["- none"]
    assert agent._render_test_levels(
        [{"level": "unit", "focus": ""}, {"level": "integration", "focus": "flow"}]
    ) == ["- unit: TBD", "- integration: flow"]

    assert agent._render_test_cases(None) == ["- none"]
    assert agent._render_test_cases(
        [
            "invalid",
            {
                "case_id": "case-1",
                "level": "unit",
                "objective": "",
                "assertions": [],
            },
        ]
    ) == ["- `case-1` (unit): TBD", "  - assertion: none"]

    assert agent._normalize_code_change_slices(
        [
            "invalid",
            {
                "slice_id": " slice-2 ",
                "goal": " goal ",
                "targets": [" a.py ", "", "b.py"],
                "depends_on": [" prep "],
            },
        ]
    ) == [
        {
            "slice_id": "slice-2",
            "goal": "goal",
            "targets": ["a.py", "b.py"],
            "depends_on": ["prep"],
        }
    ]

    assert agent._normalize_task_breakdown(
        [
            "invalid",
            {
                "task_id": " task-1 ",
                "objective": " objective ",
                "depends_on": [" dep "],
            },
        ]
    ) == [
        {
            "task_id": "task-1",
            "objective": "objective",
            "depends_on": ["dep"],
        }
    ]

    assert agent._normalize_list([" a ", "", 3, None]) == ["a", "3", "None"]
    assert agent._normalize_list("invalid") == []
    assert agent._render_bullets([]) == ["- none"]
    assert agent._render_bullets(["x", "y"]) == ["- x", "- y"]
    assert agent._as_dict({"ok": True}) == {"ok": True}
    assert agent._as_dict(["not", "a", "dict"]) == {}
