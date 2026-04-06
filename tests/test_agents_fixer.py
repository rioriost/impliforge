from __future__ import annotations

import asyncio

from devagents.agents.base import AgentTask
from devagents.agents.fixer import FixerAgent
from devagents.orchestration.workflow import WorkflowState


def _build_state(requirement: str = "Stabilize the workflow") -> WorkflowState:
    return WorkflowState(workflow_id="wf-fixer-test", requirement=requirement)


def _build_task(inputs: dict) -> AgentTask:
    return AgentTask(
        name="fixer",
        objective="Generate a focused fix proposal",
        inputs=inputs,
    )


def test_fixer_run_builds_fix_loop_plan_from_review_outputs() -> None:
    agent = FixerAgent()
    state = _build_state("Fallback objective from workflow state")
    task = _build_task(
        {
            "normalized_requirements": {
                "acceptance_criteria": ["Warnings are resolved"],
                "constraints": ["Keep edits small"],
                "open_questions": ["Should rollout be gated?"],
            },
            "documentation_bundle": {
                "design": "# Design\n",
                "runbook": "# Runbook\n",
            },
            "implementation": {
                "code_change_slices": [
                    {
                        "targets": [
                            "src/devagents/agents/fixer.py",
                            "devagents/tests/test_agents_fixer.py",
                        ]
                    }
                ]
            },
            "test_plan": {"test_cases": ["fix loop path"]},
            "test_results": {
                "executed_checks": [{"name": "pytest -q tests", "status": "failed"}]
            },
            "review": {
                "severity": "needs_follow_up",
                "unresolved_issues": [
                    "Review severity is still elevated",
                    "Validation output needs another pass",
                ],
                "recommendations": [
                    "Apply the smallest fix slice first",
                    "Re-run validation after each change",
                ],
                "findings": [
                    {"status": "needs_follow_up", "summary": "Review still blocked"}
                ],
            },
            "copilot_response": "Copilot suggested a narrow follow-up edit.",
        }
    )

    result = asyncio.run(agent.run(task, state))

    assert result.is_success is True
    assert result.summary == "修正提案を生成し、再検証に向けたアクションを整理した。"
    assert result.artifacts == ["docs/fix-report.md"]
    assert result.outputs["fix_needed"] is True
    assert result.outputs["open_questions"] == ["Should rollout be gated?"]

    fix_plan = result.outputs["fix_plan"]
    assert fix_plan["objective"] == "Fallback objective from workflow state"
    assert fix_plan["fix_needed"] is True
    assert fix_plan["severity"] == "needs_follow_up"
    assert fix_plan["constraints"] == ["Keep edits small"]
    assert fix_plan["acceptance_criteria"] == ["Warnings are resolved"]
    assert fix_plan["unresolved_issues"] == [
        "Review severity is still elevated",
        "Validation output needs another pass",
    ]
    assert fix_plan["recommendations"] == [
        "Apply the smallest fix slice first",
        "Re-run validation after each change",
    ]
    assert fix_plan["review_findings"] == [
        {"status": "needs_follow_up", "summary": "Review still blocked"}
    ]
    assert fix_plan["documentation_inputs"] == {
        "design_present": True,
        "runbook_present": True,
        "test_plan_present": True,
        "test_results_present": True,
    }
    assert (
        fix_plan["copilot_response_excerpt"]
        == "Copilot suggested a narrow follow-up edit."
    )

    assert fix_plan["fix_strategy"] == [
        "Address review findings at the root cause instead of patching symptoms",
        "Keep the next change slice small and explicitly tied to unresolved issues",
        "Re-run validation after each meaningful fix proposal",
        "Resolve blocking review concerns before expanding implementation scope",
        "Map each unresolved issue to a concrete fix slice and revalidation step",
        "Separate requirement ambiguity from implementation defects before fixing",
    ]
    assert fix_plan["fix_slices"] == [
        {
            "slice_id": "fix-1",
            "goal": "Review severity is still elevated",
            "targets": [
                "src/devagents/agents/fixer.py",
                "devagents/tests/test_agents_fixer.py",
            ],
            "depends_on": ["review", "test_execution"],
            "validation_focus": "Confirm the issue no longer appears in review or test outputs",
        },
        {
            "slice_id": "fix-2",
            "goal": "Validation output needs another pass",
            "targets": [
                "src/devagents/agents/fixer.py",
                "devagents/tests/test_agents_fixer.py",
            ],
            "depends_on": ["review", "test_execution"],
            "validation_focus": "Confirm the issue no longer appears in review or test outputs",
        },
    ]
    assert fix_plan["edit_proposals"] == [
        {
            "proposal_id": "edit-1",
            "mode": "update",
            "targets": [
                "src/devagents/agents/fixer.py",
                "devagents/tests/test_agents_fixer.py",
            ],
            "summary": "Review severity is still elevated",
            "instructions": [
                "Keep the change small and directly tied to the unresolved issue.",
                "Prefer updating generated docs and implementation proposal artifacts first.",
                "Confirm the issue no longer appears in review or test outputs",
            ],
        },
        {
            "proposal_id": "edit-2",
            "mode": "update",
            "targets": [
                "src/devagents/agents/fixer.py",
                "devagents/tests/test_agents_fixer.py",
            ],
            "summary": "Validation output needs another pass",
            "instructions": [
                "Keep the change small and directly tied to the unresolved issue.",
                "Prefer updating generated docs and implementation proposal artifacts first.",
                "Confirm the issue no longer appears in review or test outputs",
            ],
        },
    ]
    assert fix_plan["revalidation_plan"] == [
        "Re-run test_execution after applying the proposed fix slice",
        "Re-run review and compare severity and unresolved issues",
        "Confirm previously passed checks remain stable after the fix",
        "Verify each unresolved issue is either resolved or explicitly deferred",
        "Confirm requirement ambiguity is documented separately from implementation defects",
    ]

    assert result.next_actions == [
        "Persist docs/fix-report.md",
        "Apply the highest-priority fix slice",
        "Re-run test_execution",
        "Re-run review",
        "Track unresolved issues until severity becomes ok",
        "Escalate requirement ambiguity before broadening code changes",
    ]
    assert result.risks == [
        "レビューで warning または needs_follow_up が残っているため、完了判定は保留",
        "要件上の open questions が残っているため、修正方針が暫定になる",
    ]
    assert result.metrics == {
        "acceptance_criteria_count": 1,
        "constraint_count": 1,
        "unresolved_issue_count": 2,
        "recommendation_count": 2,
        "fix_slice_count": 2,
        "revalidation_step_count": 5,
    }

    report = result.outputs["fix_report"]
    assert "# Fix Report" in report
    assert "## Fix Needed" in report
    assert "- True" in report
    assert "- severity: needs_follow_up" in report
    assert "## Fix Slices" in report
    assert "`fix-1`" in report
    assert "## Edit Proposals" in report
    assert "`edit-2` [update]" in report
    assert "## Copilot Draft Notes" in report
    assert "Copilot suggested a narrow follow-up edit." in report


def test_fixer_run_without_fix_loop_uses_recommendation_and_completion_paths() -> None:
    agent = FixerAgent()
    state = _build_state("Ship the final workflow")
    task = _build_task(
        {
            "normalized_requirements": {
                "objective": "Ship the final workflow",
                "acceptance_criteria": ["Final checks pass"],
                "constraints": [],
                "open_questions": [],
            },
            "documentation_bundle": {},
            "implementation": {},
            "test_plan": {},
            "test_results": {},
            "review": {
                "severity": "ok",
                "unresolved_issues": [],
                "recommendations": ["Tighten generated artifacts"],
                "findings": [{"status": "ok", "summary": "Review is clean"}],
            },
            "copilot_response": "",
        }
    )

    result = asyncio.run(agent.run(task, state))

    assert result.is_success is True
    assert result.outputs["fix_needed"] is False

    fix_plan = result.outputs["fix_plan"]
    assert fix_plan["objective"] == "Ship the final workflow"
    assert fix_plan["severity"] == "ok"
    assert fix_plan["fix_strategy"] == [
        "Address review findings at the root cause instead of patching symptoms",
        "Keep the next change slice small and explicitly tied to unresolved issues",
        "Re-run validation after each meaningful fix proposal",
        "No blocking review severity detected; only targeted cleanup is needed",
    ]
    assert fix_plan["fix_slices"] == [
        {
            "slice_id": "recommendation-1",
            "goal": "Tighten generated artifacts",
            "targets": [],
            "depends_on": ["review"],
            "validation_focus": "Confirm the recommendation is reflected in regenerated artifacts",
        }
    ]
    assert fix_plan["edit_proposals"] == [
        {
            "proposal_id": "edit-1",
            "mode": "update",
            "targets": ["docs/fix-report.md"],
            "summary": "Tighten generated artifacts",
            "instructions": [
                "Keep the change small and directly tied to the unresolved issue.",
                "Prefer updating generated docs and implementation proposal artifacts first.",
                "Confirm the recommendation is reflected in regenerated artifacts",
            ],
        }
    ]
    assert fix_plan["revalidation_plan"] == [
        "Re-run test_execution after applying the proposed fix slice",
        "Re-run review and compare severity and unresolved issues",
    ]
    assert fix_plan["documentation_inputs"] == {
        "design_present": False,
        "runbook_present": False,
        "test_plan_present": False,
        "test_results_present": False,
    }
    assert fix_plan["copilot_response_excerpt"] == ""

    assert result.next_actions == [
        "Persist docs/fix-report.md",
        "No immediate fix loop is required",
        "Proceed to final completion checks",
    ]
    assert result.risks == [
        "既存の code change slices が不足しているため、修正対象の粒度が粗い"
    ]
    assert result.metrics == {
        "acceptance_criteria_count": 1,
        "constraint_count": 0,
        "unresolved_issue_count": 0,
        "recommendation_count": 1,
        "fix_slice_count": 1,
        "revalidation_step_count": 2,
    }

    report = result.outputs["fix_report"]
    assert "- severity: ok" in report
    assert "No additional Copilot draft content was provided." in report


def test_fixer_build_edit_proposals_falls_back_to_related_targets_and_docs() -> None:
    agent = FixerAgent()

    proposals = agent._build_edit_proposals(
        fix_slices=[],
        documentation_bundle={"design": "# Design\n", "runbook": "# Runbook\n"},
        implementation={
            "code_change_slices": [
                {"targets": ["src/devagents/agents/fixer.py", "docs/design.md"]},
                {"targets": ["docs/runbook.md", "src/devagents/agents/fixer.py"]},
            ]
        },
    )

    assert proposals == [
        {
            "proposal_id": "edit-fallback-1",
            "mode": "update",
            "targets": [
                "src/devagents/agents/fixer.py",
                "docs/design.md",
                "docs/runbook.md",
            ],
            "summary": "Tighten generated artifacts to address review feedback.",
            "instructions": [
                "Update the smallest set of files needed to resolve the review concern.",
                "Preserve existing workflow structure and artifact naming.",
                "Re-run test_execution and review after the edit.",
            ],
        }
    ]


def test_fixer_helpers_cover_fallback_and_rendering_branches() -> None:
    agent = FixerAgent()

    assert agent._build_fix_slices(
        unresolved_issues=[],
        recommendations=[],
        code_change_slices=[],
    ) == [
        {
            "slice_id": "fix-fallback-1",
            "goal": "Review outputs and tighten implementation proposal where needed",
            "targets": [],
            "depends_on": ["review"],
            "validation_focus": "Re-run review and confirm no unresolved issues remain",
        }
    ]

    assert agent._collect_related_targets(
        [
            {"targets": ["a.py", "b.py"]},
            {"targets": ["b.py", "c.py"]},
            {"targets": "skip"},
        ]
    ) == ["a.py", "b.py", "c.py"]

    assert agent._render_fix_slices([]) == ["- none"]
    assert agent._render_fix_slices(
        [
            {
                "slice_id": "fix-1",
                "goal": "Resolve issue",
                "targets": ["a.py"],
                "depends_on": ["review"],
                "validation_focus": "Re-run review",
            },
            "skip",
        ]
    ) == [
        "- `fix-1`: Resolve issue",
        "  - targets: a.py",
        "  - depends_on: review",
        "  - validation_focus: Re-run review",
    ]

    assert agent._render_edit_proposals([]) == ["- none"]
    assert agent._render_edit_proposals(
        [
            {
                "proposal_id": "edit-1",
                "mode": "update",
                "summary": "Apply fix",
                "targets": ["a.py"],
                "instructions": ["Do the smallest change"],
            },
            {
                "proposal_id": "edit-2",
                "mode": "update",
                "summary": "",
                "targets": [],
                "instructions": [],
            },
            "skip",
        ]
    ) == [
        "- `edit-1` [update]: Apply fix",
        "  - targets: a.py",
        "  - instruction: Do the smallest change",
        "- `edit-2` [update]: TBD",
        "  - targets: none",
        "  - instruction: none",
    ]

    assert agent._normalize_list([" alpha ", "", 2]) == ["alpha", "2"]
    assert agent._normalize_list("bad") == []
    assert agent._normalize_dict_list([{"ok": True}, "skip", {"x": 1}]) == [
        {"ok": True},
        {"x": 1},
    ]
    assert agent._normalize_dict_list(None) == []
    assert agent._render_bullets([]) == ["- none"]
    assert agent._render_bullets(["one", "two"]) == ["- one", "- two"]
    assert agent._as_dict({"ok": True}) == {"ok": True}
    assert agent._as_dict(["bad"]) == {}
