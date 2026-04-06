from __future__ import annotations

import asyncio

from impliforge.agents.base import AgentTask
from impliforge.agents.documentation import DocumentationAgent
from impliforge.orchestration.workflow import create_workflow_state


def build_state():
    return create_workflow_state(
        workflow_id="wf-docs-001",
        requirement="Document the workflow design",
        model="gpt-5.4",
    )


def test_documentation_agent_generates_design_and_runbook_outputs() -> None:
    agent = DocumentationAgent()
    state = build_state()
    task = AgentTask(
        name="documentation",
        objective="Generate docs",
        inputs={
            "normalized_requirements": {
                "objective": "Ship a resumable multi-agent workflow",
                "constraints": ["Keep changes small", "Protect destructive edits"],
                "acceptance_criteria": ["Design doc exists", "Runbook exists"],
                "open_questions": ["How should approval escalation work?"],
                "resolved_decisions": ["Persist structured state only"],
                "inferred_capabilities": ["Resume from checkpoints"],
                "out_of_scope": ["Raw token persistence"],
            },
            "plan": {
                "phases": ["Analyze", "Document", "Review"],
                "deliverables": ["docs/design.md", "docs/runbook.md"],
                "task_breakdown": [
                    {
                        "task_id": "doc-1",
                        "objective": "Draft design",
                        "depends_on": ["planning"],
                    },
                    {
                        "task_id": "doc-2",
                        "objective": "Draft runbook",
                        "depends_on": [],
                    },
                ],
            },
            "copilot_response": "Draft notes from Copilot.",
        },
    )

    result = asyncio.run(agent.run(task, state))

    assert result.is_success is True
    assert result.summary == "設計文書と運用向けドキュメントの草案を生成した。"
    assert result.artifacts == ["docs/design.md", "docs/runbook.md"]
    assert result.next_actions == [
        "docs/design.md と docs/runbook.md を保存する",
        "implementation agent に設計文書を渡す",
    ]
    assert result.risks == []
    assert result.metrics == {
        "constraint_count": 2,
        "acceptance_criteria_count": 2,
        "open_question_count": 1,
        "resolved_decision_count": 1,
        "task_breakdown_count": 2,
    }

    outputs = result.outputs
    assert outputs["documentation_targets"] == ["docs/design.md", "docs/runbook.md"]
    assert outputs["open_questions"] == ["How should approval escalation work?"]
    assert outputs["resolved_decisions"] == ["Persist structured state only"]
    assert outputs["documentation_bundle"]["design"] == outputs["design_document"]
    assert outputs["documentation_bundle"]["runbook"] == outputs["runbook_document"]

    design = outputs["design_document"]
    assert "# Design" in design
    assert "## Objective" in design
    assert "Ship a resumable multi-agent workflow" in design
    assert "- Keep changes small" in design
    assert "- Protect destructive edits" in design
    assert "## Acceptance Criteria" in design
    assert "- Design doc exists" in design
    assert "## Inferred Capabilities" in design
    assert "- Resume from checkpoints" in design
    assert "## Planned Phases" in design
    assert "1. Analyze" in design
    assert "2. Document" in design
    assert "## Task Breakdown" in design
    assert "- `doc-1`: Draft design" in design
    assert "  - depends_on: planning" in design
    assert "- `doc-2`: Draft runbook" in design
    assert "  - depends_on: none" in design
    assert "## Out of Scope" in design
    assert "- Raw token persistence" in design
    assert "## Persistent Context Policy" in design
    assert "artifacts/workflow-state.json" in design
    assert "## Approval Policy" in design
    assert "## Resolved Decisions" in design
    assert "- Persist structured state only" in design
    assert "## Open Questions" not in design
    assert "## Copilot Draft Notes" in design
    assert "Draft notes from Copilot." in design
    assert design.endswith("\n")

    runbook = outputs["runbook_document"]
    assert "# Runbook" in runbook
    assert "## Goal" in runbook
    assert "Ship a resumable multi-agent workflow" in runbook
    assert "## Expected Deliverables" in runbook
    assert "- docs/design.md" in runbook
    assert "- docs/runbook.md" in runbook
    assert "## Execution Flow" in runbook
    assert "1. Analyze" in runbook
    assert "2. Document" in runbook
    assert "## Operator Checklist" in runbook
    assert (
        "- Confirm blocked work is reflected in operator-facing outputs with explicit next actions and escalation triggers"
        in runbook
    )
    assert (
        "- Confirm run summary surfaces budget pressure signals before cost ceilings are exceeded"
        in runbook
    )
    assert (
        "- Confirm artifact lists stay deduplicated and limited to operator-meaningful outputs"
        in runbook
    )
    assert "## Persistence Policy" in runbook
    assert (
        "- Surface token usage ratio in the run summary so operators can react before budget ceilings are exceeded"
        in runbook
    )
    assert (
        "- Keep artifact references deduplicated so repeated generated paths do not inflate operator-facing artifact volume"
        in runbook
    )
    assert "## Approval Policy" in runbook
    assert "## Blocked-State Handling" in runbook
    assert (
        "- Mark the workflow as blocked when unresolved questions, repository-policy conflicts, or missing restore data prevent safe progress"
        in runbook
    )
    assert (
        "- List the immediate next action, the human decision needed, and the condition for resuming execution"
        in runbook
    )
    assert "## Escalation Conditions" in runbook
    assert (
        "- Generated implementation plan conflicts with repository constraints"
        in runbook
    )
    assert (
        "- A requested change requires destructive modification or dependency addition without explicit approval"
        in runbook
    )
    assert "## Operator Escalation Actions" in runbook
    assert (
        "- Stop before applying the blocked change and request explicit human approval or a narrower alternative"
        in runbook
    )
    assert (
        "- Ask the operator to capture the blocking constraint, required decision, and approved next action in the run summary"
        in runbook
    )
    assert (
        "- Resume only after the blocked-state record identifies the approval or repository decision that unblocks execution"
        in runbook
    )
    assert runbook.endswith("\n")


def test_documentation_agent_uses_fallbacks_and_open_question_branch() -> None:
    agent = DocumentationAgent()
    state = build_state()
    task = AgentTask(
        name="documentation",
        objective="Generate docs",
        inputs={
            "normalized_requirements": {
                "constraints": "not-a-list",
                "acceptance_criteria": None,
                "open_questions": ["Need approval owner"],
                "resolved_decisions": [],
                "inferred_capabilities": [],
                "out_of_scope": [],
            },
            "plan": {
                "phases": "not-a-list",
                "deliverables": [],
                "task_breakdown": [
                    {
                        "task_id": "doc-1",
                        "objective": "Keep this task",
                        "depends_on": [],
                    },
                    "ignore-me",
                    123,
                ],
            },
            "copilot_response": "   ",
        },
    )

    result = asyncio.run(agent.run(task, state))

    assert result.is_success is True
    assert result.risks == [
        "未解決の open questions があるため、設計文書は暫定版となる",
        "計画フェーズ情報が不足しているため、運用手順の粒度が粗い",
    ]
    assert result.metrics == {
        "constraint_count": 0,
        "acceptance_criteria_count": 0,
        "open_question_count": 1,
        "resolved_decision_count": 0,
        "task_breakdown_count": 1,
    }

    outputs = result.outputs
    assert outputs["open_questions"] == ["Need approval owner"]
    assert outputs["resolved_decisions"] == []

    design = outputs["design_document"]
    assert "## Objective" in design
    assert "Document the workflow design" in design
    assert "## Constraints" in design
    assert "- none" in design
    assert "## Acceptance Criteria" in design
    assert "## Inferred Capabilities" in design
    assert "## Planned Phases" in design
    assert "1. none" in design
    assert "## Task Breakdown" in design
    assert "- `doc-1`: Keep this task" in design
    assert "## Out of Scope" in design
    assert "## Open Questions" in design
    assert "- Need approval owner" in design
    assert "## Resolved Decisions" not in design
    assert "No additional Copilot draft content was provided." in design

    runbook = outputs["runbook_document"]
    assert "## Goal" in runbook
    assert "Document the workflow design" in runbook
    assert "## Expected Deliverables" in runbook
    assert "## Execution Flow" in runbook
    assert "1. none" in runbook
    assert "## Blocked-State Handling" in runbook
    assert "- Open questions remain unresolved before implementation starts" in runbook
    assert "- Design assumptions conflict with repository constraints" in runbook
    assert "- Session restore data is incomplete or inconsistent" in runbook
    assert "## Operator Escalation Actions" in runbook
    assert (
        "- Pause implementation until the open questions are answered or explicitly deferred"
        in runbook
    )
    assert (
        "- Ask the operator to record the decision owner and the expected follow-up action in the run summary"
        in runbook
    )
    assert (
        "- Resume only after blocked-state outputs include the chosen next action and restart condition"
        in runbook
    )


def test_documentation_agent_helper_methods_normalize_and_render() -> None:
    agent = DocumentationAgent()

    assert agent._as_dict({"ok": True}) == {"ok": True}
    assert agent._as_dict(["not", "a", "dict"]) == {}

    assert agent._normalize_list([" a ", "", "b", "   ", 3]) == ["a", "b", "3"]
    assert agent._normalize_list("not-a-list") == []

    assert agent._normalize_task_breakdown(
        [
            {"task_id": "t1", "objective": "Do work", "depends_on": ["x"]},
            "skip",
            1,
        ]
    ) == [{"task_id": "t1", "objective": "Do work", "depends_on": ["x"]}]
    assert agent._normalize_task_breakdown("not-a-list") == []

    assert agent._render_bullets([]) == ["- none"]
    assert agent._render_bullets(["x", "y"]) == ["- x", "- y"]

    assert agent._render_numbered([]) == ["1. none"]
    assert agent._render_numbered(["x", "y"]) == ["1. x", "2. y"]

    assert agent._render_task_breakdown([]) == ["- none"]
    assert agent._render_task_breakdown(
        [
            {"task_id": "t1", "objective": "Do work", "depends_on": ["a", "b"]},
            {"task_id": "t2", "objective": "", "depends_on": []},
        ]
    ) == [
        "- `t1`: Do work",
        "  - depends_on: a, b",
        "- `t2`: TBD",
        "  - depends_on: none",
    ]
