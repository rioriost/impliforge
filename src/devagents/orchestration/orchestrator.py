"""Core orchestrator for the devagents multi-agent workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

DEFAULT_MODEL = "gpt-5.4"


@dataclass(slots=True)
class AgentTask:
    """Structured task passed to an agent."""

    name: str
    objective: str
    inputs: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentResult:
    """Structured result returned by an agent."""

    status: str
    summary: str
    outputs: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WorkflowState:
    """Minimal workflow state for orchestration."""

    requirement: str
    workflow_id: str
    model: str = DEFAULT_MODEL
    phase: str = "initialized"
    completed_steps: list[str] = field(default_factory=list)
    pending_steps: list[str] = field(
        default_factory=lambda: [
            "requirements_analysis",
            "planning",
            "implementation",
            "testing",
            "review",
            "finalization",
        ]
    )
    artifacts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    def advance(self, phase: str, completed_step: str | None = None) -> None:
        self.phase = phase
        if completed_step and completed_step not in self.completed_steps:
            self.completed_steps.append(completed_step)
        if completed_step and completed_step in self.pending_steps:
            self.pending_steps.remove(completed_step)

    def add_artifact(self, path: str | Path) -> None:
        artifact = Path(path).as_posix()
        if artifact not in self.artifacts:
            self.artifacts.append(artifact)

    def add_note(self, note: str) -> None:
        if note:
            self.notes.append(note)

    def add_risks(self, risks: list[str]) -> None:
        for risk in risks:
            if risk not in self.risks:
                self.risks.append(risk)

    def add_open_questions(self, questions: list[str]) -> None:
        for question in questions:
            if question not in self.open_questions:
                self.open_questions.append(question)


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
        state = WorkflowState(
            requirement=requirement,
            workflow_id=self._build_workflow_id(),
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
            phase="requirements_analyzed",
            completed_step="requirements_analysis",
            result=requirements_result,
        )

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
            phase="planned",
            completed_step="planning",
            result=planning_result,
        )

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
                phase="implementing",
                completed_step="implementation",
                result=implementation_result,
            )

        if self.test_agent is not None:
            test_result = await self.dispatch(
                self.test_agent,
                AgentTask(
                    name="testing",
                    objective="Validate the implementation",
                    inputs={"requirement": requirement},
                ),
                state,
            )
            self._apply_result(
                state,
                phase="testing",
                completed_step="testing",
                result=test_result,
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
                phase="reviewing",
                completed_step="review",
                result=review_result,
            )

        state.advance("completed", "finalization")
        state.add_note("Workflow completed.")
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
            "phase": state.phase,
            "model": state.model,
            "completed_steps": list(state.completed_steps),
            "pending_steps": list(state.pending_steps),
            "artifacts": list(state.artifacts),
            "notes": list(state.notes),
            "open_questions": list(state.open_questions),
            "risks": list(state.risks),
        }

    def handle_failure(
        self,
        state: WorkflowState,
        *,
        step_name: str,
        reason: str,
    ) -> WorkflowState:
        """Mark the workflow as failed with a reason."""
        state.phase = "failed"
        state.add_note(f"{step_name} failed: {reason}")
        return state

    def finalize(self, state: WorkflowState) -> dict[str, Any]:
        """Return the final workflow payload."""
        return self.collect_results(state)

    def _apply_result(
        self,
        state: WorkflowState,
        *,
        phase: str,
        completed_step: str,
        result: AgentResult,
    ) -> None:
        if result.status != "completed":
            self.handle_failure(
                state,
                step_name=completed_step,
                reason=result.summary or "unknown failure",
            )
            return

        state.advance(phase, completed_step)
        state.add_note(result.summary)
        state.add_risks(result.risks)

        open_questions = result.outputs.get("open_questions", [])
        if isinstance(open_questions, list):
            state.add_open_questions(
                [str(question) for question in open_questions if question]
            )

        for artifact in result.artifacts:
            state.add_artifact(artifact)

    def _build_workflow_id(self) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        return f"wf-{timestamp}"
