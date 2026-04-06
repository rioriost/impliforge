"""Requirements analysis agent for the devagents workflow."""

from __future__ import annotations

from typing import Any

from devagents.agents.base import AgentResult, AgentTask, BaseAgent


class RequirementsAgent(BaseAgent):
    """Normalize incoming requirements into a structured form."""

    agent_name = "requirements"

    async def run(self, task: AgentTask, state: Any) -> AgentResult:
        requirement = str(task.inputs.get("requirement", "")).strip()
        if not requirement:
            return AgentResult.failure(
                "要件が空のため、要件分析を実行できない。",
                outputs={
                    "open_questions": ["実装対象となる要件本文を指定する必要がある。"]
                },
                next_actions=["要件本文を入力して再実行する"],
                risks=["要件未入力のため後続フェーズに進めない"],
            )

        normalized = self._normalize_requirement(requirement)
        return AgentResult.success(
            "要件を正規化し、初期の受け入れ条件と確認事項を抽出した。",
            outputs={"normalized_requirements": normalized},
            next_actions=[
                "implementation-plan を生成する",
                "open_questions があれば解消方針を決める",
            ],
            risks=normalized["risks"],
            metrics={
                "acceptance_criteria_count": len(normalized["acceptance_criteria"]),
                "open_question_count": len(normalized["open_questions"]),
                "constraint_count": len(normalized["constraints"]),
            },
        )

    def _normalize_requirement(self, requirement: str) -> dict[str, Any]:
        lower_requirement = requirement.lower()

        constraints = [
            "Use GitHub Copilot SDK as the orchestration foundation",
            "Default model is GPT-5.4 with task-aware routing",
            "Development workflow is managed with uv",
        ]

        acceptance_criteria = [
            "A multi-agent workflow exists with an orchestrator",
            "Session rotation can preserve context through persistence",
            "Planning, implementation, testing, and review are represented",
        ]

        inferred_capabilities = [
            "requirements_analysis",
            "planning",
            "documentation",
            "implementation",
            "test_design",
            "test_execution",
            "review",
        ]

        open_questions: list[str] = []
        risks = [
            "未確定の SDK API 差分は実装時に吸収が必要",
        ]

        if (
            "copilot sdk" in lower_requirement
            or "github copilot sdk" in lower_requirement
        ):
            constraints.append(
                "Copilot SDK integration points must be isolated behind a client layer"
            )

        if "session" in lower_requirement or "セッション" in requirement:
            acceptance_criteria.append(
                "Session state can be snapshotted and restored across runs"
            )

        if "model" in lower_requirement or "gpt" in lower_requirement:
            acceptance_criteria.append(
                "Model routing selects an appropriate model for each task type"
            )

        if "test" in lower_requirement or "テスト" in requirement:
            acceptance_criteria.append(
                "The workflow can define and execute validation steps"
            )

        if "persistent" not in lower_requirement and "永続" not in requirement:
            open_questions.append(
                "persistent context の保存先と復元粒度をどこまで保証するか未確定。"
            )

        if "approval" not in lower_requirement and "承認" not in requirement:
            open_questions.append("破壊的変更や依存追加時の承認フロー要否が未確定。")

        if "cost" not in lower_requirement and "コスト" not in requirement:
            risks.append(
                "モデル切替戦略にコスト上限が未定義のため、運用時に費用が増える可能性がある"
            )

        return {
            "objective": requirement,
            "summary": "要件をマルチエージェント実装向けに構造化した。",
            "constraints": constraints,
            "acceptance_criteria": acceptance_criteria,
            "inferred_capabilities": inferred_capabilities,
            "out_of_scope": [
                "Web UI",
                "複数リポジトリ同時対応",
                "高度な分散スケジューリング",
            ],
            "open_questions": open_questions,
            "risks": risks,
        }
