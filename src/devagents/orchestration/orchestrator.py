"""Core orchestrator for the devagents multi-agent workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from devagents.agents.base import AgentResult, AgentTask
from devagents.orchestration.workflow import (
    TaskStatus,
    WorkflowPhase,
    WorkflowState,
    create_workflow_state,
)

DEFAULT_MODEL = "gpt-5.4"


class Agent(Protocol):
    """Protocol for orchestrator-managed agents."""

    agent_name: str

    async def run(self, task: AgentTask, state: WorkflowState) -> AgentResult:
        """Execute a task and return a structured result."""


class Orchestrator:
    """Coordinates the high-level multi-agent workflow."""

    def __init__(
        self,
        *,
        requirements_agent: Agent,
        planning_agent: Agent,
        implementation_agent: Agent | None = None,
        test_agent: Agent | None = None,
        review_agent: Agent | None = None,
        model: str = DEFAULT_MODEL,
        artifacts_dir: str | Path = "artifacts",
    ) -> None:
        self.requirements_agent = requirements_agent
        self.planning_agent = planning_agent
        self.implementation_agent = implementation_agent
        self.test_agent = test_agent
        self.review_agent = review_agent
        self.model = model
        self.artifacts_dir = Path(artifacts_dir)

    async def run(self, requirement: str) -> WorkflowState:
        """Run the minimal end-to-end workflow."""
        state = create_workflow_state(
            workflow_id=self._build_workflow_id(),
            requirement=requirement,
            model=self.model,
        )
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

        requirements_result = await self.dispatch(
            self.requirements_agent,
            AgentTask(
                name="requirements_analysis",
                objective="Normalize the incoming requirement",
                inputs={"requirement": requirement},
            ),
            state,
        )
        self._apply_result(
            state,
            phase=WorkflowPhase.REQUIREMENTS_ANALYZED,
            completed_step="requirements_analysis",
            result=requirements_result,
        )
        if not requirements_result.is_success:
            return state

        planning_result = await self.dispatch(
            self.planning_agent,
            AgentTask(
                name="planning",
                objective="Create an implementation plan",
                inputs={
                    "requirement": requirement,
                    "requirements_outputs": requirements_result.outputs,
                },
            ),
            state,
        )
        self._apply_result(
            state,
            phase=WorkflowPhase.PLANNED,
            completed_step="planning",
            result=planning_result,
        )
        if not planning_result.is_success:
            return state

        if self.implementation_agent is not None:
            implementation_result = await self.dispatch(
                self.implementation_agent,
                AgentTask(
                    name="implementation",
                    objective="Implement the approved plan",
                    inputs={
                        "requirement": requirement,
                        "plan": planning_result.outputs,
                    },
                ),
                state,
            )
            self._apply_result(
                state,
                phase=WorkflowPhase.IMPLEMENTING,
                completed_step="implementation",
                result=implementation_result,
            )
            if not implementation_result.is_success:
                return state
        else:
            state.update_task_status(
                "implementation",
                TaskStatus.SKIPPED,
                note="Implementation agent was not configured.",
            )

        if self.test_agent is not None:
            test_result = await self.dispatch(
                self.test_agent,
                AgentTask(
                    name="test_execution",
                    objective="Validate the implementation",
                    inputs={"requirement": requirement},
                ),
                state,
            )
            self._apply_result(
                state,
                phase=WorkflowPhase.TESTING,
                completed_step="test_execution",
                result=test_result,
            )
            if not test_result.is_success:
                return state
        else:
            state.update_task_status(
                "test_design",
                TaskStatus.SKIPPED,
                note="Test agent was not configured.",
            )
            state.update_task_status(
                "test_execution",
                TaskStatus.SKIPPED,
                note="Test agent was not configured.",
            )

        if self.review_agent is not None:
            review_result = await self.dispatch(
                self.review_agent,
                AgentTask(
                    name="review",
                    objective="Review the implementation and test results",
                    inputs={"requirement": requirement},
                ),
                state,
            )
            self._apply_result(
                state,
                phase=WorkflowPhase.REVIEWING,
                completed_step="review",
                result=review_result,
            )
            if not review_result.is_success:
                return state
        else:
            state.update_task_status(
                "review",
                TaskStatus.SKIPPED,
                note="Review agent was not configured.",
            )

        self._finalize_success(state)
        return state

    async def dispatch(
        self,
        agent: Agent,
        task: AgentTask,
        state: WorkflowState,
    ) -> AgentResult:
        """Dispatch a task to an agent."""
        return await agent.run(task, state)

    def collect_results(self, state: WorkflowState) -> dict[str, Any]:
        """Collect a compact workflow summary."""
        return {
            "workflow_id": state.workflow_id,
            "phase": state.phase.value,
            "model": state.model,
            "task_counts": {
                "pending": len(state.pending_tasks()),
                "in_progress": len(state.in_progress_tasks()),
                "blocked": len(state.blocked_tasks()),
                "completed": len(state.completed_tasks()),
                "failed": len(state.failed_tasks()),
            },
            "artifacts": list(state.artifacts),
            "notes": list(state.notes),
            "open_questions": list(state.open_questions),
            "risks": list(state.risks),
            "changed_files": list(state.changed_files),
        }

    def handle_failure(
        self,
        state: WorkflowState,
        *,
        step_name: str,
        reason: str,
    ) -> WorkflowState:
        """Mark the workflow as failed with a reason."""
        state.set_phase(WorkflowPhase.FAILED)
        state.update_task_status(step_name, TaskStatus.FAILED, note=reason)
        state.add_note(f"{step_name} failed: {reason}")
        return state

    def finalize(self, state: WorkflowState) -> dict[str, Any]:
        """Return the final workflow payload."""
        return self.collect_results(state)

    def _apply_result(
        self,
        state: WorkflowState,
        *,
        phase: WorkflowPhase,
        completed_step: str,
        result: AgentResult,
    ) -> None:
        task = state.require_task(completed_step)
        task.mark_in_progress(getattr(task, "owner", None))
        state.touch()

        if not result.is_success:
            self.handle_failure(
                state,
                step_name=completed_step,
                reason=result.summary or "unknown failure",
            )
            return

        task.mark_completed(outputs=result.outputs)
        state.touch()
        state.set_phase(phase)
        state.add_note(result.summary)
        for risk in result.risks:
            if risk:
                state.add_risk(str(risk))

        open_questions = result.outputs.get("open_questions", [])
        if isinstance(open_questions, list):
            for question in open_questions:
                if question:
                    state.add_open_question(str(question))

        changed_files = result.outputs.get("changed_files", [])
        if isinstance(changed_files, list):
            for changed_file in changed_files:
                if changed_file:
                    state.add_changed_file(str(changed_file))

        for artifact in result.artifacts:
            state.add_artifact(artifact)

    def _finalize_success(self, state: WorkflowState) -> None:
        for dependency_id in ("documentation", "review"):
            dependency_task = state.require_task(dependency_id)
            if dependency_task.status == TaskStatus.PENDING:
                dependency_task.mark_skipped(
                    "Dependency was not executed in the minimal orchestrator flow."
                )

        finalization_task = state.require_task("finalization")
        finalization_task.mark_completed(
            outputs={
                "next_actions": [
                    "Persist final workflow summary",
                    "Review generated artifacts",
                ]
            }
        )
        state.touch()
        state.set_phase(WorkflowPhase.COMPLETED)
        state.add_note("Workflow completed.")

    def _build_workflow_id(self) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        return f"wf-{timestamp}"
