"""Core orchestrator for the impliforge multi-agent workflow."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from impliforge.agents.base import AgentResult, AgentTask
from impliforge.orchestration.workflow import (
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
        state.record_event(
            "task_dispatched",
            task_id=task.name,
            agent_name=agent.agent_name,
            status="in_progress",
            summary=f"Dispatching {task.name} to {agent.agent_name}.",
            details={
                "objective": task.objective,
                "input_keys": sorted(task.inputs.keys()),
                "constraint_keys": sorted(task.constraints.keys()),
                "metadata_keys": sorted(task.metadata.keys()),
            },
        )
        result = await agent.run(task, state)
        return AgentResult(
            status=result.status,
            summary=result.summary,
            outputs=result.outputs,
            artifacts=result.artifacts,
            next_actions=result.next_actions,
            risks=result.risks,
            metrics=result.metrics,
            failure_category=result.failure_category,
            failure_cause=result.failure_cause,
        )

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
            "execution_trace": [event.to_dict() for event in state.execution_trace],
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
        state.record_event(
            "task_failed",
            task_id=step_name,
            status=TaskStatus.FAILED.value,
            summary=f"{step_name} failed.",
            details={"reason": reason},
        )
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

        normalized_summary = (
            result.summary.strip()
            if isinstance(result.summary, str) and result.summary.strip()
            else "No summary provided."
        )
        normalized_outputs = (
            dict(result.outputs) if isinstance(result.outputs, Mapping) else {}
        )
        normalized_artifacts = self._normalize_unique_strings(result.artifacts)
        normalized_risks = self._normalize_unique_strings(result.risks)
        normalized_next_actions = self._normalize_unique_strings(result.next_actions)
        open_questions = self._normalize_unique_strings(
            normalized_outputs.get("open_questions", [])
            if isinstance(normalized_outputs.get("open_questions", []), list)
            else []
        )
        changed_files = self._normalize_unique_strings(
            normalized_outputs.get("changed_files", [])
            if isinstance(normalized_outputs.get("changed_files", []), list)
            else []
        )

        if not result.is_success:
            failure_reason = normalized_summary
            self.handle_failure(
                state,
                step_name=completed_step,
                reason=failure_reason,
            )
            task = state.require_task(completed_step)
            failure_outputs = dict(normalized_outputs)
            if normalized_next_actions:
                failure_outputs["next_actions"] = normalized_next_actions
            if result.metrics:
                failure_outputs["metrics"] = dict(result.metrics)
            task.outputs.update(failure_outputs)
            for artifact in normalized_artifacts:
                state.add_artifact(artifact)
            for risk in normalized_risks:
                state.add_risk(risk)
            for question in open_questions:
                state.add_open_question(question)
            for changed_file in changed_files:
                state.add_changed_file(changed_file)
            state.record_event(
                "task_completed",
                task_id=completed_step,
                status=task.status.value,
                summary=failure_reason,
                details={
                    "phase_after": state.phase.value,
                    "artifact_count": len(normalized_artifacts),
                    "risk_count": len(normalized_risks),
                    "open_question_count": len(open_questions),
                    "changed_file_count": len(changed_files),
                    "output_keys": sorted(failure_outputs.keys()),
                    "next_action_count": len(normalized_next_actions),
                    "metric_keys": sorted(result.metrics.keys()),
                    "result_status": result.status,
                },
            )
            return

        merged_outputs = self._merge_outputs(task.outputs, normalized_outputs)
        task.mark_completed(outputs=merged_outputs)
        state.touch()
        state.set_phase(phase)
        state.add_note(normalized_summary)
        for risk in normalized_risks:
            state.add_risk(risk)
        for question in open_questions:
            state.add_open_question(question)
        for changed_file in changed_files:
            state.add_changed_file(changed_file)
        for artifact in normalized_artifacts:
            state.add_artifact(artifact)

        if normalized_next_actions:
            task.outputs["next_actions"] = normalized_next_actions
        if result.metrics:
            task.outputs["metrics"] = dict(result.metrics)

        state.record_event(
            "task_completed",
            task_id=completed_step,
            status=task.status.value,
            summary=normalized_summary,
            details={
                "phase_after": phase.value,
                "artifact_count": len(normalized_artifacts),
                "risk_count": len(normalized_risks),
                "open_question_count": len(open_questions),
                "changed_file_count": len(changed_files),
                "output_keys": sorted(task.outputs.keys()),
                "next_action_count": len(normalized_next_actions),
                "metric_keys": sorted(result.metrics.keys()),
                "result_status": result.status,
            },
        )

    def _finalize_success(self, state: WorkflowState) -> None:
        skipped_dependencies: list[str] = []
        for dependency_id in ("documentation", "review"):
            dependency_task = state.require_task(dependency_id)
            if dependency_task.status == TaskStatus.PENDING:
                dependency_task.mark_skipped(
                    "Dependency was not executed in the minimal orchestrator flow."
                )
                skipped_dependencies.append(dependency_id)

        finalization_task = state.require_task("finalization")
        incomplete_tasks = [
            task.task_id
            for task in state.tasks
            if task.task_id != "finalization"
            and task.status in {TaskStatus.PENDING, TaskStatus.IN_PROGRESS}
        ]
        blocking_open_questions = bool(state.open_questions)
        blocking_tasks = [
            task.task_id
            for task in state.tasks
            if task.task_id != "finalization"
            and task.status in {TaskStatus.BLOCKED, TaskStatus.FAILED}
        ]
        acceptance_ready = (
            not blocking_open_questions and not blocking_tasks and not incomplete_tasks
        )
        failed_checks: list[str] = []
        if blocking_open_questions:
            failed_checks.append("open_questions_resolved")
        if blocking_tasks:
            failed_checks.append("blocking_work_resolved")
        if incomplete_tasks:
            failed_checks.append("workflow_execution_completed")

        finalization_outputs = {
            "acceptance_gate": {
                "ready_for_completion": acceptance_ready,
                "failed_checks": failed_checks,
                "blocking_open_questions": blocking_open_questions,
                "blocking_tasks": blocking_tasks,
                "incomplete_tasks": incomplete_tasks,
            },
            "next_actions": (
                [
                    "Persist final workflow summary",
                    "Review generated artifacts",
                ]
                if acceptance_ready
                else [
                    "Resolve open questions and blocked workflow tasks before declaring completion",
                    "Complete any remaining in-progress workflow tasks",
                ]
            ),
        }

        if acceptance_ready:
            finalization_task.mark_completed(outputs=finalization_outputs)
            state.touch()
            state.set_phase(WorkflowPhase.COMPLETED)
            state.add_note("Workflow completed.")
            event_status = finalization_task.status.value
            event_summary = "Workflow completed."
        else:
            finalization_task.mark_blocked(
                "Minimal orchestrator completion is blocked until acceptance readiness is satisfied."
            )
            finalization_task.outputs.update(finalization_outputs)
            state.touch()
            state.add_note("Workflow completion blocked pending acceptance readiness.")
            event_status = finalization_task.status.value
            event_summary = "Workflow completion blocked."

        state.record_event(
            "workflow_completed",
            task_id="finalization",
            status=event_status,
            summary=event_summary,
            details={
                "skipped_dependencies": skipped_dependencies,
                "final_artifact_count": len(state.artifacts),
                "final_changed_file_count": len(state.changed_files),
                "open_question_count": len(state.open_questions),
                "risk_count": len(state.risks),
                "acceptance_ready": acceptance_ready,
                "blocking_open_questions": blocking_open_questions,
                "blocking_tasks": blocking_tasks,
                "incomplete_tasks": incomplete_tasks,
            },
        )

    def _normalize_unique_strings(self, values: Iterable[Any]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            text = str(value).strip()
            if text and text not in normalized:
                normalized.append(text)
        return normalized

    def _merge_outputs(
        self,
        base: Mapping[str, Any],
        incoming: Mapping[str, Any],
    ) -> dict[str, Any]:
        merged = dict(base)
        for key, value in incoming.items():
            existing = merged.get(key)
            if isinstance(existing, Mapping) and isinstance(value, Mapping):
                merged[key] = self._merge_outputs(existing, value)
            elif isinstance(existing, list) and isinstance(value, list):
                merged_list = list(existing)
                for item in value:
                    if item not in merged_list:
                        merged_list.append(item)
                merged[key] = merged_list
            else:
                merged[key] = value
        return merged

    def _build_workflow_id(self) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        return f"wf-{timestamp}"
