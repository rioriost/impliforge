from __future__ import annotations

import asyncio

from devagents.agents.base import AgentTask
from devagents.agents.test_execution import TestExecutionAgent
from devagents.orchestration.workflow import WorkflowState


def _state(requirement: str = "Fallback workflow requirement") -> WorkflowState:
    return WorkflowState(workflow_id="wf-test-execution", requirement=requirement)


def test_run_builds_results_document_and_metrics() -> None:
    agent = TestExecutionAgent()
    task = AgentTask(
        name="test_execution",
        objective="Execute tests",
        inputs={
            "normalized_requirements": {
                "objective": "Validate generated workflow outputs",
                "acceptance_criteria": [
                    "Artifacts are persisted",
                    "Review receives test results",
                ],
                "open_questions": ["Should unresolved items block release?"],
                "resolved_decisions": ["Use provisional pass status for draft output"],
            },
            "plan": {
                "phases": [
                    "requirements_analysis",
                    "planning",
                    "documentation",
                    "implementation",
                ]
            },
            "implementation": {
                "code_change_slices": [
                    {"slice_id": "slice-1", "goal": "Cover success path"},
                ]
            },
            "test_plan": {
                "test_cases": [
                    {
                        "name": "routing selection",
                        "objective": "Selected model is recorded",
                        "category": "unit",
                    },
                    {
                        "name": "artifact persistence",
                        "objective": "Artifacts are written",
                        "category": "integration",
                    },
                ],
                "validation_steps": [
                    "Run focused pytest targets",
                    "Inspect generated docs",
                ],
            },
            "copilot_response": "Execution draft notes",
        },
    )

    result = asyncio.run(agent.run(task, _state()))

    assert result.is_success is True
    assert result.summary == "テスト実行結果の草案を生成し、検証状況を整理した。"
    assert result.artifacts == ["docs/test-results.md"]
    assert result.next_actions == [
        "docs/test-results.md を保存する",
        "review agent に test_results を渡す",
        "必要なら失敗項目や未確認項目を fix loop に送る",
    ]
    assert result.risks == []

    outputs = result.outputs
    assert outputs["test_result_targets"] == ["docs/test-results.md"]
    assert outputs["open_questions"] == ["Should unresolved items block release?"]

    test_results = outputs["test_results"]
    assert test_results["status"] == "provisional_passed"
    assert test_results["summary"] == "4/4 checks were provisionally passed."
    assert test_results["open_questions"] == ["Should unresolved items block release?"]
    assert test_results["resolved_decisions"] == [
        "Use provisional pass status for draft output"
    ]
    assert test_results["acceptance_criteria"] == [
        "Artifacts are persisted",
        "Review receives test results",
    ]

    executed_checks = test_results["executed_checks"]
    assert executed_checks == [
        {
            "check_id": "case-1",
            "name": "routing selection",
            "category": "unit",
            "status": "passed",
            "details": "Selected model is recorded",
        },
        {
            "check_id": "case-2",
            "name": "artifact persistence",
            "category": "integration",
            "status": "passed",
            "details": "Artifacts are written",
        },
        {
            "check_id": "step-1",
            "name": "Run focused pytest targets",
            "category": "validation_step",
            "status": "passed",
            "details": "Validation step was included in the execution checklist.",
        },
        {
            "check_id": "step-2",
            "name": "Inspect generated docs",
            "category": "validation_step",
            "status": "passed",
            "details": "Validation step was included in the execution checklist.",
        },
    ]

    assert result.metrics == {
        "acceptance_criteria_count": 2,
        "test_case_count": 2,
        "executed_check_count": 4,
        "open_question_count": 1,
    }

    document = outputs["test_results_document"]
    assert document.startswith("# Test Results\n")
    assert "## Objective\nValidate generated workflow outputs\n" in document
    assert "## Acceptance Criteria Coverage\n- Artifacts are persisted" in document
    assert "## Planned Workflow Phases\n1. requirements_analysis" in document
    assert "## Executed Checks\n- routing selection [unit] => passed" in document
    assert "  - Selected model is recorded" in document
    assert (
        "## Resolved Decisions\n- Use provisional pass status for draft output"
        in document
    )
    assert "## Copilot Draft Notes\nExecution draft notes\n" in document
    assert document.endswith("\n")


def test_run_uses_fallbacks_and_reports_provisional_risks() -> None:
    agent = TestExecutionAgent()
    state = _state("Requirement from workflow state")
    task = AgentTask(
        name="test_execution",
        objective="Execute tests",
        inputs={
            "normalized_requirements": {
                "acceptance_criteria": None,
                "open_questions": ["Need final validation owner"],
                "resolved_decisions": [],
            },
            "plan": {"phases": "invalid"},
            "implementation": {
                "code_change_slices": [{"goal": "Review slice coverage"}]
            },
            "test_plan": {
                "test_cases": "invalid",
                "validation_steps": "invalid",
            },
            "copilot_response": "",
        },
    )

    result = asyncio.run(agent.run(task, state))

    assert result.is_success is True
    assert result.risks == [
        "具体的な test_cases が不足しているため、検証結果は暫定評価となる",
        "未解決の open questions が残っており、対応方針も未確定のため、最終的な合格判定は保留",
    ]

    test_results = result.outputs["test_results"]
    assert test_results["summary"] == (
        "1/1 checks were provisionally passed, "
        "but unresolved questions remain before final validation."
    )
    assert test_results["acceptance_criteria"] == []
    assert test_results["resolved_decisions"] == []
    assert test_results["open_questions"] == ["Need final validation owner"]
    assert test_results["executed_checks"] == [
        {
            "check_id": "slice-1",
            "name": "Review slice coverage",
            "category": "implementation_slice",
            "status": "passed",
            "details": (
                "Implementation slice was reviewed for testability and "
                "provisional coverage."
            ),
        }
    ]

    assert result.metrics == {
        "acceptance_criteria_count": 0,
        "test_case_count": 0,
        "executed_check_count": 1,
        "open_question_count": 1,
    }

    document = result.outputs["test_results_document"]
    assert "## Objective\nRequirement from workflow state\n" in document
    assert "## Acceptance Criteria Coverage\n- none\n" in document
    assert "## Planned Workflow Phases\n1. none\n" in document
    assert "## Open Questions\n- Need final validation owner\n" in document
    assert (
        "## Copilot Draft Notes\nNo additional Copilot draft content was provided.\n"
        in document
    )


def test_run_adds_missing_slice_risk_when_no_code_change_slices_exist() -> None:
    agent = TestExecutionAgent()
    task = AgentTask(
        name="test_execution",
        objective="Execute tests",
        inputs={
            "normalized_requirements": {
                "objective": "Validate fallback reporting",
                "acceptance_criteria": [],
                "open_questions": [],
                "resolved_decisions": [],
            },
            "plan": {"phases": []},
            "implementation": {"code_change_slices": []},
            "test_plan": {
                "test_cases": [],
                "validation_steps": [],
            },
            "copilot_response": "",
        },
    )

    result = asyncio.run(agent.run(task, _state()))

    assert result.is_success is True
    assert result.risks == [
        "具体的な test_cases が不足しているため、検証結果は暫定評価となる",
        "実装変更スライスが不足しているため、変更影響に対する検証網羅性が限定的",
    ]
    assert result.outputs["test_results"]["executed_checks"] == [
        {
            "check_id": "fallback-1",
            "name": "workflow-validation",
            "category": "fallback",
            "status": "passed",
            "details": (
                "Workflow completed through planning, documentation, and "
                "implementation proposal phases."
            ),
        }
    ]
    assert (
        result.outputs["test_results"]["summary"]
        == "1/1 checks were provisionally passed."
    )


def test_build_executed_checks_prefers_cases_then_validation_steps() -> None:
    agent = TestExecutionAgent()

    checks = agent._build_executed_checks(
        test_cases=[
            {
                "name": "case name",
                "objective": "case objective",
                "category": "unit",
            },
            {
                "objective": "",
                "category": "",
            },
        ],
        validation_steps=["step one"],
        code_change_slices=[{"goal": "slice goal"}],
    )

    assert checks == [
        {
            "check_id": "case-1",
            "name": "case name",
            "category": "unit",
            "status": "passed",
            "details": "case objective",
        },
        {
            "check_id": "case-2",
            "name": "test-case-2",
            "category": "validation",
            "status": "passed",
            "details": "Planned test case was reviewed and marked as provisionally covered.",
        },
        {
            "check_id": "step-1",
            "name": "step one",
            "category": "validation_step",
            "status": "passed",
            "details": "Validation step was included in the execution checklist.",
        },
    ]


def test_build_summary_and_render_helpers_cover_notable_branches() -> None:
    agent = TestExecutionAgent()

    assert agent._build_summary(
        executed_checks=[{"status": "passed"}, {"status": "failed"}],
        open_questions=["question"],
        resolved_decisions=[],
    ) == (
        "1/2 checks were provisionally passed, "
        "but unresolved questions remain before final validation."
    )
    assert (
        agent._build_summary(
            executed_checks=[{"status": "passed"}, {"status": "passed"}],
            open_questions=["question"],
            resolved_decisions=["decision"],
        )
        == "2/2 checks were provisionally passed."
    )

    assert agent._render_checks([]) == ["- none"]
    assert agent._render_checks(
        [{"name": "check", "category": "unit", "status": "passed", "details": ""}]
    ) == ["- check [unit] => passed"]

    assert agent._render_bullets([]) == ["- none"]
    assert agent._render_bullets(["x", "y"]) == ["- x", "- y"]

    assert agent._render_numbered([]) == ["1. none"]
    assert agent._render_numbered(["phase-1", "phase-2"]) == [
        "1. phase-1",
        "2. phase-2",
    ]

    assert agent._normalize_list([" a ", "", 3, None]) == ["a", "3", "None"]
    assert agent._normalize_list("invalid") == []

    assert agent._normalize_dict_list(
        [{"name": "ok"}, "invalid", {"goal": "still ok"}]
    ) == [{"name": "ok"}, {"goal": "still ok"}]
    assert agent._normalize_dict_list("invalid") == []

    assert agent._as_dict({"ok": True}) == {"ok": True}
    assert agent._as_dict(["not", "a", "dict"]) == {}
