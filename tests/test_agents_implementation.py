from __future__ import annotations

import asyncio

from devagents.agents.base import AgentTask
from devagents.agents.implementation import ImplementationAgent
from devagents.orchestration.workflow import create_workflow_state


def build_state():
    return create_workflow_state(
        workflow_id="wf-impl-001",
        requirement="Implement the workflow safely",
        model="gpt-5.4",
    )


def test_implementation_agent_generates_structured_proposal() -> None:
    agent = ImplementationAgent()
    state = build_state()
    task = AgentTask(
        name="implementation",
        objective="Generate implementation proposal",
        inputs={
            "normalized_requirements": {
                "objective": "Ship resumable workflow execution",
                "constraints": ["Keep changes small", "Require approval for deletes"],
                "acceptance_criteria": [
                    "Implementation proposal exists",
                    "Edit path is structured",
                ],
                "open_questions": ["Who approves destructive edits?"],
            },
            "plan": {
                "phases": ["Analyze", "Implement", "Validate"],
                "task_breakdown": [
                    {
                        "task_id": "impl-1",
                        "objective": "Add implementation agent",
                        "depends_on": ["planning"],
                    },
                    {
                        "task_id": "impl-2",
                        "objective": "Wire orchestrator integration",
                        "depends_on": ["impl-1"],
                    },
                ],
            },
            "copilot_response": "Copilot draft implementation notes." * 30,
        },
    )

    result = asyncio.run(agent.run(task, state))

    assert result.is_success is True
    assert result.summary == "実装提案を生成し、次のコード変更スライスを整理した。"
    assert result.next_actions == [
        "Add documentation and implementation agents to the orchestrator",
        "Persist generated design and implementation proposal artifacts",
        "Extend the workflow into test_design, test_execution, and review phases",
        "Promote structured src/devagents edit proposals into the safe edit phase",
    ]
    assert result.risks == [
        "実コード変更前に承認フローが未確定だと、破壊的変更の扱いが曖昧になる",
        "実装提案と既存アーキテクチャの整合確認が不足すると差分が広がる可能性がある",
        "未解決の open questions が残っているため、実装着手前に確認が必要",
    ]
    assert result.metrics == {
        "constraint_count": 2,
        "acceptance_criteria_count": 2,
        "task_breakdown_count": 2,
        "code_change_slice_count": 5,
        "open_question_count": 1,
    }

    outputs = result.outputs
    assert outputs["open_questions"] == ["Who approves destructive edits?"]

    implementation = outputs["implementation"]
    assert implementation["objective"] == "Ship resumable workflow execution"
    assert implementation["summary"] == "実装フェーズで着手すべき変更案を整理した。"
    assert implementation["strategy"] == [
        "Keep changes small and align with the existing repository structure",
        "Isolate Copilot SDK integration behind runtime/copilot_client.py",
        "Persist workflow and session state before and after meaningful milestones",
        "Prefer explicit workflow state transitions over implicit behavior",
        "Prefer structured code edits over free-form append-only source mutations",
    ]
    assert implementation["constraints"] == [
        "Keep changes small",
        "Require approval for deletes",
    ]
    assert implementation["acceptance_criteria"] == [
        "Implementation proposal exists",
        "Edit path is structured",
    ]
    assert implementation["plan_phases"] == ["Analyze", "Implement", "Validate"]
    assert implementation["task_breakdown"] == [
        {
            "task_id": "impl-1",
            "objective": "Add implementation agent",
            "depends_on": ["planning"],
        },
        {
            "task_id": "impl-2",
            "objective": "Wire orchestrator integration",
            "depends_on": ["impl-1"],
        },
    ]
    assert implementation["open_questions"] == ["Who approves destructive edits?"]
    assert len(implementation["copilot_response_excerpt"]) == 500

    proposed_modules = implementation["proposed_modules"]
    assert len(proposed_modules) == 6
    assert proposed_modules[0] == {
        "path": "src/devagents/agents/implementation.py",
        "purpose": "Generate implementation proposals and concrete code-change slices.",
    }
    assert proposed_modules[-1] == {
        "path": "src/devagents/runtime/editor.py",
        "purpose": "Apply allowlisted edits safely to docs, artifacts, and approved source files.",
    }

    code_change_slices = implementation["code_change_slices"]
    assert [item["slice_id"] for item in code_change_slices] == [
        "implementation-agent",
        "documentation-agent",
        "orchestrator-integration",
        "artifact-persistence",
        "src-allowlisted-edit-phase",
    ]
    assert code_change_slices[0]["targets"] == [
        "src/devagents/agents/implementation.py"
    ]
    assert code_change_slices[2]["depends_on"] == [
        "implementation-agent",
        "documentation-agent",
    ]
    assert code_change_slices[-1]["targets"] == [
        "src/devagents/main.py",
        "src/devagents/runtime/editor.py",
        "src/devagents/agents/implementation.py",
    ]

    assert implementation["deliverables"] == [
        "docs/design.md",
        "docs/final-summary.md",
        "artifacts/workflows/<workflow_id>/workflow-details.json",
        "artifacts/summaries/<workflow_id>/run-summary.json",
        "src/devagents/**/*.py allowlisted edit proposals",
    ]

    edit_proposals = implementation["edit_proposals"]
    assert [item["proposal_id"] for item in edit_proposals] == [
        "src-structured-main-update",
        "src-structured-editor-update",
        "src-structured-implementation-update",
    ]
    assert edit_proposals[0]["mode"] == "structured_update"
    assert edit_proposals[0]["targets"] == ["src/devagents/main.py"]
    assert (
        edit_proposals[0]["edits"][0]["target_symbol"]
        == "SkeletonOrchestrator._build_safe_edit_operations"
    )
    assert edit_proposals[1]["targets"] == ["src/devagents/runtime/editor.py"]
    assert edit_proposals[1]["edits"][0]["target_symbol"] == "SafeEditor.apply"
    assert edit_proposals[2]["targets"] == ["src/devagents/agents/implementation.py"]
    assert edit_proposals[2]["edits"][0]["target_symbol"] == "ImplementationAgent.run"


def test_implementation_agent_uses_requirement_fallback_and_empty_excerpt() -> None:
    agent = ImplementationAgent()
    state = build_state()
    task = AgentTask(
        name="implementation",
        objective="Generate implementation proposal",
        inputs={
            "normalized_requirements": {
                "constraints": "not-a-list",
                "acceptance_criteria": None,
                "open_questions": [],
            },
            "plan": {
                "phases": "not-a-list",
                "task_breakdown": [
                    {
                        "task_id": "impl-1",
                        "objective": "Keep this task",
                        "depends_on": ["planning", ""],
                    },
                    {
                        "task_id": "",
                        "objective": "",
                        "depends_on": ["ignored"],
                    },
                    "skip-me",
                    123,
                ],
            },
            "copilot_response": "   ",
        },
    )

    result = asyncio.run(agent.run(task, state))

    assert result.is_success is True
    assert result.risks == [
        "実コード変更前に承認フローが未確定だと、破壊的変更の扱いが曖昧になる",
        "実装提案と既存アーキテクチャの整合確認が不足すると差分が広がる可能性がある",
    ]
    assert result.metrics == {
        "constraint_count": 0,
        "acceptance_criteria_count": 0,
        "task_breakdown_count": 1,
        "code_change_slice_count": 5,
        "open_question_count": 0,
    }

    implementation = result.outputs["implementation"]
    assert implementation["objective"] == "Implement the workflow safely"
    assert implementation["constraints"] == []
    assert implementation["acceptance_criteria"] == []
    assert implementation["plan_phases"] == []
    assert implementation["task_breakdown"] == [
        {
            "task_id": "impl-1",
            "objective": "Keep this task",
            "depends_on": ["planning"],
        }
    ]
    assert implementation["open_questions"] == []
    assert implementation["copilot_response_excerpt"] == ""


def test_implementation_agent_normalization_helpers() -> None:
    agent = ImplementationAgent()

    assert agent._as_dict({"ok": True}) == {"ok": True}
    assert agent._as_dict(["not", "a", "dict"]) == {}

    assert agent._normalize_list([" a ", "", "b", "   ", 3]) == ["a", "b", "3"]
    assert agent._normalize_list("not-a-list") == []

    assert agent._normalize_task_breakdown(
        [
            {
                "task_id": "t1",
                "objective": "Do work",
                "depends_on": ["a", "", "b"],
            },
            {
                "task_id": "t2",
                "objective": "",
                "depends_on": [],
            },
            {
                "task_id": "",
                "objective": "Only objective",
                "depends_on": ["x"],
            },
            {
                "task_id": "",
                "objective": "",
                "depends_on": ["ignored"],
            },
            "skip",
            1,
        ]
    ) == [
        {
            "task_id": "t1",
            "objective": "Do work",
            "depends_on": ["a", "b"],
        },
        {
            "task_id": "t2",
            "objective": "",
            "depends_on": [],
        },
        {
            "task_id": "",
            "objective": "Only objective",
            "depends_on": ["x"],
        },
    ]
    assert agent._normalize_task_breakdown("not-a-list") == []
