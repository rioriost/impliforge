"""Workflow state models for the devagents orchestration layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class WorkflowPhase(StrEnum):
    """High-level workflow phases."""

    INITIALIZED = "initialized"
    REQUIREMENTS_ANALYZED = "requirements_analyzed"
    PLANNED = "planned"
    DESIGN_GENERATED = "design_generated"
    IMPLEMENTING = "implementing"
    TESTING = "testing"
    REVIEWING = "reviewing"
    FIXING = "fixing"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_HUMAN_INPUT = "needs_human_input"


class TaskStatus(StrEnum):
    """Execution status for a workflow task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(slots=True)
class WorkflowTask:
    """A unit of work tracked by the orchestrator."""

    task_id: str
    name: str
    objective: str
    status: TaskStatus = TaskStatus.PENDING
    owner: str | None = None
    depends_on: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)

    def mark_in_progress(self, owner: str | None = None) -> None:
        self.status = TaskStatus.IN_PROGRESS
        if owner:
            self.owner = owner

    def mark_completed(self, outputs: dict[str, Any] | None = None) -> None:
        self.status = TaskStatus.COMPLETED
        if outputs:
            self.outputs.update(outputs)

    def mark_blocked(self, reason: str) -> None:
        self.status = TaskStatus.BLOCKED
        self.notes.append(reason)

    def mark_failed(self, reason: str) -> None:
        self.status = TaskStatus.FAILED
        self.notes.append(reason)

    def mark_skipped(self, reason: str) -> None:
        self.status = TaskStatus.SKIPPED
        self.notes.append(reason)

    def add_note(self, note: str) -> None:
        self.notes.append(note)


@dataclass(slots=True)
class SessionSnapshot:
    """Minimal resumable session context."""

    session_id: str
    parent_session_id: str | None = None
    token_usage_ratio: float = 0.0
    last_checkpoint: str | None = None
    next_action: str | None = None
    persistent_context: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass(slots=True)
class WorkflowState:
    """Canonical in-memory workflow state for orchestration."""

    workflow_id: str
    requirement: str
    model: str = "gpt-5.4"
    phase: WorkflowPhase = WorkflowPhase.INITIALIZED
    session_id: str | None = None
    parent_session_id: str | None = None
    tasks: list[WorkflowTask] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    retry_counters: dict[str, int] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def set_phase(self, phase: WorkflowPhase) -> None:
        self.phase = phase
        self.touch()

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC).isoformat()

    def add_task(self, task: WorkflowTask) -> None:
        if self.get_task(task.task_id) is not None:
            raise ValueError(f"Task already exists: {task.task_id}")
        self.tasks.append(task)
        self.touch()

    def get_task(self, task_id: str) -> WorkflowTask | None:
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        return None

    def require_task(self, task_id: str) -> WorkflowTask:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(f"Unknown task: {task_id}")
        return task

    def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        note: str | None = None,
        outputs: dict[str, Any] | None = None,
    ) -> None:
        task = self.require_task(task_id)
        task.status = status
        if note:
            task.add_note(note)
        if outputs:
            task.outputs.update(outputs)
        self.touch()

    def pending_tasks(self) -> list[WorkflowTask]:
        return [task for task in self.tasks if task.status == TaskStatus.PENDING]

    def in_progress_tasks(self) -> list[WorkflowTask]:
        return [task for task in self.tasks if task.status == TaskStatus.IN_PROGRESS]

    def blocked_tasks(self) -> list[WorkflowTask]:
        return [task for task in self.tasks if task.status == TaskStatus.BLOCKED]

    def completed_tasks(self) -> list[WorkflowTask]:
        return [task for task in self.tasks if task.status == TaskStatus.COMPLETED]

    def failed_tasks(self) -> list[WorkflowTask]:
        return [task for task in self.tasks if task.status == TaskStatus.FAILED]

    def add_artifact(self, path: str) -> None:
        if path not in self.artifacts:
            self.artifacts.append(path)
            self.touch()

    def add_changed_file(self, path: str) -> None:
        if path not in self.changed_files:
            self.changed_files.append(path)
            self.touch()

    def add_note(self, note: str) -> None:
        self.notes.append(note)
        self.touch()

    def add_risk(self, risk: str) -> None:
        if risk not in self.risks:
            self.risks.append(risk)
            self.touch()

    def add_open_question(self, question: str) -> None:
        if question not in self.open_questions:
            self.open_questions.append(question)
            self.touch()

    def resolve_open_question(self, question: str) -> None:
        if question in self.open_questions:
            self.open_questions.remove(question)
            self.touch()

    def increment_retry(self, key: str) -> int:
        current = self.retry_counters.get(key, 0) + 1
        self.retry_counters[key] = current
        self.touch()
        return current

    def set_session(
        self,
        session_id: str,
        parent_session_id: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.parent_session_id = parent_session_id
        self.touch()

    def can_finalize(self) -> bool:
        if self.open_questions:
            return False
        if any(
            task.status
            in {TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED}
            for task in self.tasks
        ):
            return False
        if any(task.status == TaskStatus.FAILED for task in self.tasks):
            return False
        return True

    def summary(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "phase": self.phase.value,
            "model": self.model,
            "session_id": self.session_id,
            "task_counts": {
                "pending": len(self.pending_tasks()),
                "in_progress": len(self.in_progress_tasks()),
                "blocked": len(self.blocked_tasks()),
                "completed": len(self.completed_tasks()),
                "failed": len(self.failed_tasks()),
            },
            "artifacts": list(self.artifacts),
            "changed_files": list(self.changed_files),
            "open_questions": list(self.open_questions),
            "risks": list(self.risks),
            "updated_at": self.updated_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_default_tasks() -> list[WorkflowTask]:
    """Return the default task graph for the initial workflow."""

    return [
        WorkflowTask(
            task_id="requirements_analysis",
            name="Requirements Analysis",
            objective="Normalize the incoming requirement and extract constraints.",
        ),
        WorkflowTask(
            task_id="planning",
            name="Implementation Planning",
            objective="Create an implementation plan and task breakdown.",
            depends_on=["requirements_analysis"],
        ),
        WorkflowTask(
            task_id="documentation",
            name="Documentation",
            objective="Generate or update design and workflow documentation.",
            depends_on=["planning"],
        ),
        WorkflowTask(
            task_id="implementation",
            name="Implementation",
            objective="Implement the required code changes.",
            depends_on=["planning"],
        ),
        WorkflowTask(
            task_id="test_design",
            name="Test Design",
            objective="Define test cases and validation strategy.",
            depends_on=["planning"],
        ),
        WorkflowTask(
            task_id="test_execution",
            name="Test Execution",
            objective="Run tests and collect validation results.",
            depends_on=["implementation", "test_design"],
        ),
        WorkflowTask(
            task_id="review",
            name="Review",
            objective="Review implementation quality, risks, and acceptance coverage.",
            depends_on=["implementation", "test_execution"],
        ),
        WorkflowTask(
            task_id="finalization",
            name="Finalization",
            objective="Prepare final summary and completion artifacts.",
            depends_on=["documentation", "review"],
        ),
    ]


def create_workflow_state(
    workflow_id: str,
    requirement: str,
    model: str = "gpt-5.4",
) -> WorkflowState:
    """Create a workflow state preloaded with the default task graph."""

    state = WorkflowState(
        workflow_id=workflow_id,
        requirement=requirement,
        model=model,
    )
    for task in build_default_tasks():
        state.add_task(task)
    return state
