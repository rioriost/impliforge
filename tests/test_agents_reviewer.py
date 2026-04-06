from __future__ import annotations

import asyncio

from impliforge.agents.base import AgentTask
from impliforge.agents.reviewer import ReviewAgent
from impliforge.orchestration.workflow import WorkflowState


def _build_state(requirement: str = "Ship the reviewed workflow") -> WorkflowState:
    return WorkflowState(workflow_id="wf-reviewer-test", requirement=requirement)


def _build_task(inputs: dict) -> AgentTask:
    return AgentTask(
        name="review",
        objective="Review generated artifacts",
        inputs=inputs,
    )


def test_reviewer_run_success_path_without_fix_loop() -> None:
    agent = ReviewAgent()
    state = _build_state("Deliver a documented implementation")
    task = _build_task(
        {
            "normalized_requirements": {
                "objective": "Deliver a documented implementation",
                "acceptance_criteria": [
                    "Design is documented",
                    "Validation is defined",
                ],
                "constraints": ["Keep changes focused"],
                "open_questions": [],
                "resolved_decisions": ["Use the existing workflow structure"],
            },
            "plan": {
                "task_breakdown": [
                    {"task": "design"},
                    {"task": "implementation"},
                ]
            },
            "documentation_bundle": {
                "design": "# Design\n",
                "runbook": "# Runbook\n",
            },
            "implementation": {
                "strategy": "Update the implementation in small slices.",
                "code_change_slices": [
                    {"targets": ["src/impliforge/agents/reviewer.py"]}
                ],
            },
            "test_plan": {
                "test_cases": ["review success path", "report rendering"],
            },
            "test_results": {
                "status": "provisional_passed",
            },
            "copilot_response": "Draft notes from Copilot.",
        }
    )

    result = asyncio.run(agent.run(task, state))

    assert result.is_success is True
    assert (
        result.summary == "レビュー報告を生成し、未解決事項と次アクションを整理した。"
    )
    assert result.artifacts == ["docs/review-report.md"]
    assert result.risks == []

    review = result.outputs["review"]
    assert review["objective"] == "Deliver a documented implementation"
    assert review["severity"] == "ok"
    assert review["fix_loop_required"] is False
    assert review["unresolved_issues"] == []
    assert review["fix_targets"] == [
        {
            "target_id": "recommendation-1",
            "source": "recommendation",
            "summary": "文書化した persistent context policy と approval policy を前提に実コード変更を進める",
            "action": "Convert the recommendation into a concrete fix slice.",
        },
        {
            "target_id": "recommendation-2",
            "source": "recommendation",
            "summary": "implementation strategy を基に test_design フェーズへ進む",
            "action": "Convert the recommendation into a concrete fix slice.",
        },
    ]

    assert result.outputs["open_questions"] == []
    assert result.outputs["resolved_decisions"] == [
        "Use the existing workflow structure"
    ]
    assert result.next_actions == [
        "文書化した persistent context policy と approval policy を前提に実コード変更を進める",
        "implementation strategy を基に test_design フェーズへ進む",
    ]
    assert result.metrics == {
        "acceptance_criteria_count": 2,
        "constraint_count": 1,
        "finding_count": 10,
        "unresolved_issue_count": 0,
        "recommendation_count": 2,
        "fix_target_count": 2,
    }

    report = result.outputs["review_report"]
    assert "# Review Report" in report
    assert "## Objective" in report
    assert "Deliver a documented implementation" in report
    assert "## Resolved Decisions" in report
    assert "- Use the existing workflow structure" in report
    assert "## Fix Loop" in report
    assert "- required: no" in report
    assert "## Copilot Draft Notes" in report
    assert "Draft notes from Copilot." in report


def test_reviewer_run_marks_fix_loop_and_collects_unresolved_issues() -> None:
    agent = ReviewAgent()
    state = _build_state("Fallback objective from workflow state")
    task = _build_task(
        {
            "normalized_requirements": {
                "acceptance_criteria": [],
                "constraints": [],
                "open_questions": ["Should this be gated?"],
                "resolved_decisions": [],
            },
            "plan": {"task_breakdown": []},
            "documentation_bundle": {},
            "implementation": {},
            "test_plan": {},
            "test_results": {
                "status": "failed",
            },
            "copilot_response": "",
        }
    )

    result = asyncio.run(agent.run(task, state))

    assert result.is_success is True

    review = result.outputs["review"]
    assert review["objective"] == "Fallback objective from workflow state"
    assert review["severity"] == "needs_follow_up"
    assert review["fix_loop_required"] is True
    assert review["unresolved_issues"] == [
        "設計文書が不足しており、実装提案の妥当性確認が難しい。",
        "運用手順書が不足しており、運用時の確認手順が曖昧。",
        "タスク分解が不足しており、後続フェーズの追跡が難しい。",
        "実装提案に具体的な code change slices が不足している。",
        "受け入れ条件が不足しており、完了判定が曖昧。",
        "制約条件が不足しており、設計判断の前提が弱い。",
        "未解決の open questions が残っているため、実装前に確認が必要。",
        "実装戦略の記述が不足しており、変更方針が不明瞭。",
        "テスト計画に具体的な test cases が不足している。",
        "テスト結果が `failed` のため、追加確認または修正が必要。",
    ]
    assert review["fix_targets"][0] == {
        "target_id": "issue-1",
        "source": "review",
        "summary": "設計文書が不足しており、実装提案の妥当性確認が難しい。",
        "action": "Generate a focused fix proposal and re-run validation.",
    }
    assert review["fix_targets"][-1] == {
        "target_id": "issue-10",
        "source": "review",
        "summary": "テスト結果が `failed` のため、追加確認または修正が必要。",
        "action": "Generate a focused fix proposal and re-run validation.",
    }

    assert result.outputs["open_questions"] == ["Should this be gated?"]
    assert result.outputs["resolved_decisions"] == []
    assert result.next_actions == [
        "open questions を解消してから実コード変更に進む",
        "docs/design.md を補強して設計判断を明文化する",
        "docs/runbook.md を補強して運用手順を明文化する",
        "implementation proposal に具体的な code change slices を追加する",
        "implementation strategy を補強してから test_design に進む",
        "test_plan に具体的な test cases を追加して検証観点を補強する",
        "test_results の未解決項目を fix loop に送り、再テストする",
    ]
    assert result.risks == [
        "レビューで未解決事項が残っているため、実装完了判定は保留",
        "要件上の open questions が残っており、対応方針も未確定のため、レビュー結果は暫定",
        "warning 以上のレビュー結果のため、fix loop が必要",
    ]
    assert result.metrics == {
        "acceptance_criteria_count": 0,
        "constraint_count": 0,
        "finding_count": 10,
        "unresolved_issue_count": 10,
        "recommendation_count": 7,
        "fix_target_count": 10,
    }

    report = result.outputs["review_report"]
    assert "Fallback objective from workflow state" in report
    assert "## Open Questions" in report
    assert "- Should this be gated?" in report
    assert "## Recommendations" in report
    assert "- open questions を解消してから実コード変更に進む" in report
    assert "- test_results の未解決項目を fix loop に送り、再テストする" in report
    assert "## Risks" in report
    assert "- レビューで未解決事項が残っているため、実装完了判定は保留" in report
    assert "- warning 以上のレビュー結果のため、fix loop が必要" in report
    assert "- required: yes" in report
    assert "## Fix Targets" in report
    assert "`issue-1` [review]" in report
    assert "No additional Copilot draft content was provided." in report


def test_reviewer_run_failure_reporting_keeps_recommendations_and_risks_visible() -> (
    None
):
    agent = ReviewAgent()
    state = _build_state("Review failure visibility")
    task = _build_task(
        {
            "normalized_requirements": {
                "objective": "Review failure visibility",
                "acceptance_criteria": ["Failure causes are visible"],
                "constraints": ["Keep reporting concise"],
                "open_questions": ["Who approves the retry?"],
                "resolved_decisions": [],
            },
            "plan": {
                "task_breakdown": [
                    {"task": "review"},
                    {"task": "fix"},
                ]
            },
            "documentation_bundle": {
                "design": "# Design\n",
            },
            "implementation": {
                "strategy": "Keep failure reporting explicit.",
                "code_change_slices": [],
            },
            "test_plan": {
                "test_cases": ["failure reporting path"],
            },
            "test_results": {
                "status": "failed",
            },
            "copilot_response": "Highlight the blocking issues and next actions.",
        }
    )

    result = asyncio.run(agent.run(task, state))

    assert result.is_success is True
    assert result.outputs["review"]["fix_loop_required"] is True
    assert result.outputs["review"]["severity"] == "needs_follow_up"
    assert result.next_actions[0] == "open questions を解消してから実コード変更に進む"
    assert (
        "test_results の未解決項目を fix loop に送り、再テストする"
        in result.next_actions
    )
    assert "warning 以上のレビュー結果のため、fix loop が必要" in result.risks

    report = result.outputs["review_report"]
    assert "## Recommendations" in report
    assert "- open questions を解消してから実コード変更に進む" in report
    assert "- test_results の未解決項目を fix loop に送り、再テストする" in report
    assert "## Risks" in report
    assert "- warning 以上のレビュー結果のため、fix loop が必要" in report
    assert "## Copilot Draft Notes" in report
    assert "Highlight the blocking issues and next actions." in report


def test_reviewer_build_fix_targets_falls_back_to_warning_findings() -> None:
    agent = ReviewAgent()

    targets = agent._build_fix_targets(
        findings=[
            {"status": "ok", "summary": "all good"},
            {"status": "warning", "summary": "missing design"},
            {"status": "needs_follow_up", "summary": "re-run tests"},
        ],
        unresolved_issues=[],
        recommendations=[],
    )

    assert targets == [
        {
            "target_id": "finding-2",
            "source": "warning",
            "summary": "missing design",
            "action": "Address the finding and re-run test_execution and review.",
        },
        {
            "target_id": "finding-3",
            "source": "needs_follow_up",
            "summary": "re-run tests",
            "action": "Address the finding and re-run test_execution and review.",
        },
    ]


def test_reviewer_normalizers_filter_invalid_values() -> None:
    agent = ReviewAgent()

    assert agent._normalize_list([" alpha ", "", "  ", 3]) == ["alpha", "3"]
    assert agent._normalize_list("not-a-list") == []

    assert agent._normalize_task_breakdown(
        [{"task": "one"}, "skip", 1, {"task": "two"}]
    ) == [{"task": "one"}, {"task": "two"}]
    assert agent._normalize_task_breakdown(None) == []

    assert agent._normalize_code_change_slices(
        [{"targets": ["a.py"]}, "skip", {"targets": ["b.py"]}]
    ) == [{"targets": ["a.py"]}, {"targets": ["b.py"]}]
    assert agent._normalize_code_change_slices("bad") == []

    assert agent._as_dict({"ok": True}) == {"ok": True}
    assert agent._as_dict(["not", "a", "dict"]) == {}
