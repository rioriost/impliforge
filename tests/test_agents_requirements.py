from __future__ import annotations

import asyncio

from impliforge.agents.base import AgentTask
from impliforge.agents.requirements import RequirementsAgent


def test_run_returns_failure_for_blank_requirement() -> None:
    agent = RequirementsAgent()
    task = AgentTask(
        name="requirements_analysis",
        objective="Normalize requirement",
        inputs={"requirement": "   "},
    )

    result = asyncio.run(agent.run(task, state=None))

    assert result.status == "failed"
    assert result.is_success is False
    assert "要件が空" in result.summary
    assert result.outputs["open_questions"] == [
        "実装対象となる要件本文を指定する必要がある。"
    ]
    assert result.next_actions == ["要件本文を入力して再実行する"]
    assert result.risks == ["要件未入力のため後続フェーズに進めない"]
    assert result.metrics == {}


def test_run_returns_normalized_requirements_and_metrics() -> None:
    agent = RequirementsAgent()
    requirement = (
        "Build a workflow with GitHub Copilot SDK, session restore, model routing, "
        "test execution, persistent context, approval flow, and cost controls."
    )
    task = AgentTask(
        name="requirements_analysis",
        objective="Normalize requirement",
        inputs={"requirement": requirement},
    )

    result = asyncio.run(agent.run(task, state=None))

    assert result.status == "completed"
    assert result.is_success is True
    assert "正規化" in result.summary
    assert result.next_actions == [
        "implementation-plan を生成する",
        "open_questions があれば解消方針を決める",
    ]

    normalized = result.outputs["normalized_requirements"]
    assert normalized["objective"] == requirement
    assert normalized["summary"] == "要件をマルチエージェント実装向けに構造化した。"
    assert "requirements_analysis" in normalized["inferred_capabilities"]
    assert "review" in normalized["inferred_capabilities"]
    assert "Web UI" in normalized["out_of_scope"]

    assert (
        "Copilot SDK integration points must be isolated behind a client layer"
        in normalized["constraints"]
    )
    assert (
        "Session state can be snapshotted and restored across runs"
        in normalized["acceptance_criteria"]
    )
    assert (
        "Model routing selects an appropriate model for each task type"
        in normalized["acceptance_criteria"]
    )
    assert (
        "The workflow can define and execute validation steps"
        in normalized["acceptance_criteria"]
    )

    assert normalized["open_questions"] == []
    assert normalized["resolved_decisions"] == []
    assert normalized["risks"] == ["未確定の SDK API 差分は実装時に吸収が必要"]

    assert result.outputs["requirements_targets"] == [
        "docs/requirements.normalized.md",
        "docs/acceptance-criteria.md",
        "docs/open-questions.md",
    ]
    assert result.artifacts == [
        "docs/requirements.normalized.md",
        "docs/acceptance-criteria.md",
        "docs/open-questions.md",
    ]
    assert result.outputs["requirements_artifacts"] == {
        "docs/requirements.normalized.md": result.outputs["requirements_document"],
        "docs/acceptance-criteria.md": result.outputs["acceptance_criteria_document"],
        "docs/open-questions.md": result.outputs["open_questions_document"],
    }
    assert "# Normalized Requirements" in result.outputs["requirements_document"]
    assert "## Objective" in result.outputs["requirements_document"]
    assert requirement in result.outputs["requirements_document"]
    assert (
        "- The workflow can define and execute validation steps"
        in result.outputs["acceptance_criteria_document"]
    )
    assert result.outputs["open_questions_document"] == "# Open Questions\n\n- None"

    assert result.risks == normalized["risks"]
    assert result.metrics == {
        "acceptance_criteria_count": len(normalized["acceptance_criteria"]),
        "open_question_count": 0,
        "resolved_decision_count": 0,
        "constraint_count": len(normalized["constraints"]),
    }


def test_normalize_requirement_adds_default_open_questions_and_decisions() -> None:
    agent = RequirementsAgent()

    normalized = agent._normalize_requirement("Build a multi-agent workflow")

    assert normalized["objective"] == "Build a multi-agent workflow"
    assert normalized["open_questions"] == [
        "persistent context の保存先と復元粒度をどこまで保証するか未確定。",
        "破壊的変更や依存追加時の承認フロー要否が未確定。",
    ]
    assert normalized["resolved_decisions"] == [
        "persistent context は `artifacts/workflow-state.json`、`artifacts/sessions/<session_id>/session-snapshot.json`、`artifacts/summaries/<workflow_id>/run-summary.json` に保存する。",
        "復元粒度は workflow/session 単位とし、`requirement`、`phase`、`workflow_id`、`session_id`、完了済みタスク、未完了タスク、直近要約、resume prompt を保証対象にする。",
        "delete 操作、広範囲 overwrite、依存追加、実行環境変更は human approval 必須とする。",
    ]
    assert normalized["risks"] == [
        "未確定の SDK API 差分は実装時に吸収が必要",
        "モデル切替戦略にコスト上限が未定義のため、運用時に費用が増える可能性がある",
    ]


def test_run_builds_open_questions_artifact_when_questions_remain() -> None:
    agent = RequirementsAgent()
    requirement = "Build a multi-agent workflow with session restore"
    task = AgentTask(
        name="requirements_analysis",
        objective="Normalize requirement",
        inputs={"requirement": requirement},
    )

    result = asyncio.run(agent.run(task, state=None))

    assert result.status == "completed"
    assert result.outputs["requirements_targets"] == [
        "docs/requirements.normalized.md",
        "docs/acceptance-criteria.md",
        "docs/open-questions.md",
    ]
    assert (
        "persistent context の保存先と復元粒度をどこまで保証するか未確定。"
        in result.outputs["open_questions_document"]
    )
    assert (
        "破壊的変更や依存追加時の承認フロー要否が未確定。"
        in result.outputs["open_questions_document"]
    )
    assert (
        result.outputs["requirements_artifacts"]["docs/open-questions.md"]
        == result.outputs["open_questions_document"]
    )


def test_normalize_requirement_handles_japanese_keywords() -> None:
    agent = RequirementsAgent()

    normalized = agent._normalize_requirement(
        "セッション管理とテストを含む要件。永続化は必要。承認フローも必要。"
    )

    assert (
        "Session state can be snapshotted and restored across runs"
        in normalized["acceptance_criteria"]
    )
    assert (
        "The workflow can define and execute validation steps"
        in normalized["acceptance_criteria"]
    )
    assert normalized["open_questions"] == []
    assert normalized["resolved_decisions"] == []
