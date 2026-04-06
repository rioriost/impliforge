"""Session lifecycle management for the impliforge orchestration layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from impliforge.orchestration.workflow import SessionSnapshot, WorkflowState


@dataclass(slots=True)
class SessionRotationDecision:
    """Decision payload returned by session rotation checks."""

    should_rotate: bool
    reason: str | None = None
    token_usage_ratio: float = 0.0
    threshold: float = 0.85
    current_session_id: str | None = None
    next_session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SessionManagerConfig:
    """Configuration for session lifecycle behavior."""

    rotation_threshold: float = 0.85
    hard_limit_threshold: float = 0.95
    max_context_items: int = 50
    session_id_prefix: str = "sess"
    snapshot_version: str = "1"

    def __post_init__(self) -> None:
        if not 0.0 <= self.rotation_threshold <= 1.0:
            raise ValueError("rotation_threshold must be between 0.0 and 1.0")
        if not 0.0 <= self.hard_limit_threshold <= 1.0:
            raise ValueError("hard_limit_threshold must be between 0.0 and 1.0")
        if self.rotation_threshold > self.hard_limit_threshold:
            raise ValueError(
                "rotation_threshold must be less than or equal to hard_limit_threshold"
            )
        if self.max_context_items < 1:
            raise ValueError("max_context_items must be at least 1")


@dataclass(slots=True)
class SessionContext:
    """In-memory representation of the active session chain."""

    current_session_id: str
    parent_session_id: str | None = None
    token_usage_ratio: float = 0.0
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    rotation_count: int = 0

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SessionManager:
    """Manage session creation, snapshotting, and rotation decisions."""

    def __init__(self, config: SessionManagerConfig | None = None) -> None:
        self.config = config or SessionManagerConfig()

    def start_session(
        self,
        state: WorkflowState,
        *,
        parent_session_id: str | None = None,
        session_id: str | None = None,
    ) -> SessionContext:
        """Start a new session and attach it to the workflow state."""
        new_session_id = session_id or self._build_session_id()
        state.set_session(
            session_id=new_session_id,
            parent_session_id=parent_session_id,
        )
        state.add_note(f"Session started: {new_session_id}")
        return SessionContext(
            current_session_id=new_session_id,
            parent_session_id=parent_session_id,
        )

    def should_rotate_session(
        self,
        *,
        token_usage_ratio: float,
        current_session_id: str | None,
        force: bool = False,
    ) -> SessionRotationDecision:
        """Return whether the current session should be rotated."""
        normalized_ratio = self._normalize_ratio(token_usage_ratio)

        if force:
            return SessionRotationDecision(
                should_rotate=True,
                reason="forced",
                token_usage_ratio=normalized_ratio,
                threshold=self.config.rotation_threshold,
                current_session_id=current_session_id,
                next_session_id=self._build_session_id(),
            )

        if normalized_ratio >= self.config.hard_limit_threshold:
            return SessionRotationDecision(
                should_rotate=True,
                reason="hard_limit_threshold_reached",
                token_usage_ratio=normalized_ratio,
                threshold=self.config.hard_limit_threshold,
                current_session_id=current_session_id,
                next_session_id=self._build_session_id(),
            )

        if normalized_ratio >= self.config.rotation_threshold:
            return SessionRotationDecision(
                should_rotate=True,
                reason="rotation_threshold_reached",
                token_usage_ratio=normalized_ratio,
                threshold=self.config.rotation_threshold,
                current_session_id=current_session_id,
                next_session_id=self._build_session_id(),
            )

        return SessionRotationDecision(
            should_rotate=False,
            reason=None,
            token_usage_ratio=normalized_ratio,
            threshold=self.config.rotation_threshold,
            current_session_id=current_session_id,
            next_session_id=None,
        )

    def snapshot_context(
        self,
        state: WorkflowState,
        *,
        token_usage_ratio: float = 0.0,
        next_action: str | None = None,
        last_checkpoint: str | None = None,
        persistent_context: dict[str, Any] | None = None,
    ) -> SessionSnapshot:
        """Build a resumable snapshot from the current workflow state."""
        context = persistent_context or self._build_persistent_context(
            state,
            next_action=next_action,
        )
        return SessionSnapshot(
            session_id=state.session_id or self._build_session_id(),
            parent_session_id=state.parent_session_id,
            token_usage_ratio=self._normalize_ratio(token_usage_ratio),
            last_checkpoint=last_checkpoint or state.phase.value,
            next_action=next_action,
            persistent_context=context,
        )

    def restore_context(
        self,
        state: WorkflowState,
        snapshot: SessionSnapshot,
    ) -> WorkflowState:
        """Restore workflow session metadata and selected context from a snapshot."""
        persistent_context = snapshot.persistent_context
        self._validate_restore_context(persistent_context)

        state.set_session(
            session_id=snapshot.session_id,
            parent_session_id=snapshot.parent_session_id,
        )

        for note in persistent_context.get("notes", []):
            if note not in state.notes:
                state.add_note(str(note))

        for risk in persistent_context.get("risks", []):
            if risk not in state.risks:
                state.add_risk(str(risk))

        for question in persistent_context.get("open_questions", []):
            if question not in state.open_questions:
                state.add_open_question(str(question))

        for artifact in persistent_context.get("artifacts", []):
            if artifact not in state.artifacts:
                state.add_artifact(str(artifact))

        for changed_file in persistent_context.get("changed_files", []):
            if changed_file not in state.changed_files:
                state.add_changed_file(str(changed_file))

        self._restore_task_statuses(state, persistent_context)

        state.add_note(f"Session restored from snapshot: {snapshot.session_id}")
        return state

    def rotate_session(
        self,
        state: WorkflowState,
        *,
        token_usage_ratio: float,
        next_action: str | None = None,
        last_checkpoint: str | None = None,
        persistent_context: dict[str, Any] | None = None,
        force: bool = False,
    ) -> tuple[SessionRotationDecision, SessionSnapshot]:
        """Rotate the current session if thresholds require it."""
        decision = self.should_rotate_session(
            token_usage_ratio=token_usage_ratio,
            current_session_id=state.session_id,
            force=force,
        )
        snapshot = self.snapshot_context(
            state,
            token_usage_ratio=token_usage_ratio,
            next_action=next_action,
            last_checkpoint=last_checkpoint,
            persistent_context=persistent_context,
        )

        if decision.should_rotate:
            previous_session_id = state.session_id
            state.set_session(
                session_id=decision.next_session_id or self._build_session_id(),
                parent_session_id=previous_session_id,
            )
            state.add_note(
                "Session rotated: "
                f"{previous_session_id or 'none'} -> {state.session_id}"
            )

        return decision, snapshot

    def build_resume_prompt(
        self,
        snapshot: SessionSnapshot,
    ) -> str:
        """Build a compact resume prompt from a session snapshot."""
        context = snapshot.persistent_context
        lines = [
            "Resume the workflow using the persisted context below.",
            f"session_id: {snapshot.session_id}",
            f"parent_session_id: {snapshot.parent_session_id or 'none'}",
            f"last_checkpoint: {snapshot.last_checkpoint or 'unknown'}",
            f"next_action: {snapshot.next_action or 'unspecified'}",
            "current_objective:",
            str(context.get("requirement", "")),
            "completed_tasks:",
        ]

        completed_tasks = context.get("completed_tasks", [])
        if completed_tasks:
            lines.extend(f"- {task}" for task in completed_tasks)
        else:
            lines.append("- none")

        lines.append("open_questions:")
        open_questions = context.get("open_questions", [])
        if open_questions:
            lines.extend(f"- {question}" for question in open_questions)
        else:
            lines.append("- none")

        lines.append("artifacts:")
        artifacts = context.get("artifacts", [])
        if artifacts:
            lines.extend(f"- {artifact}" for artifact in artifacts)
        else:
            lines.append("- none")

        return "\n".join(lines)

    def _build_persistent_context(
        self,
        state: WorkflowState,
        *,
        next_action: str | None = None,
    ) -> dict[str, Any]:
        """Build the default persistent context payload from workflow state."""
        completed_tasks = [task.task_id for task in state.completed_tasks()]
        pending_tasks = [task.task_id for task in state.pending_tasks()]
        blocked_tasks = [task.task_id for task in state.blocked_tasks()]
        failed_tasks = [task.task_id for task in state.failed_tasks()]

        notes = state.notes[-self.config.max_context_items :]
        risks = state.risks[-self.config.max_context_items :]
        open_questions = state.open_questions[-self.config.max_context_items :]
        artifacts = state.artifacts[-self.config.max_context_items :]
        changed_files = state.changed_files[-self.config.max_context_items :]

        return {
            "snapshot_version": self.config.snapshot_version,
            "workflow_id": state.workflow_id,
            "requirement": state.requirement,
            "phase": state.phase.value,
            "model": state.model,
            "session_id": state.session_id,
            "parent_session_id": state.parent_session_id,
            "completed_tasks": completed_tasks,
            "pending_tasks": pending_tasks,
            "blocked_tasks": blocked_tasks,
            "failed_tasks": failed_tasks,
            "notes": notes,
            "risks": risks,
            "open_questions": open_questions,
            "artifacts": artifacts,
            "changed_files": changed_files,
            "next_action": next_action,
            "updated_at": state.updated_at,
        }

    def _build_session_id(self) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        return f"{self.config.session_id_prefix}-{timestamp}"

    def _validate_restore_context(self, persistent_context: dict[str, Any]) -> None:
        required_keys = (
            "workflow_id",
            "requirement",
            "phase",
            "session_id",
            "completed_tasks",
            "pending_tasks",
            "next_action",
        )
        missing_keys = [
            key
            for key in required_keys
            if key not in persistent_context or persistent_context.get(key) is None
        ]
        if missing_keys:
            missing = ", ".join(missing_keys)
            raise ValueError(
                "Session snapshot is incomplete; resume from the latest consistent "
                f"checkpoint instead. Missing keys: {missing}"
            )

    def _restore_task_statuses(
        self,
        state: WorkflowState,
        persistent_context: dict[str, Any],
    ) -> None:
        status_map = {
            "completed_tasks": "COMPLETED",
            "pending_tasks": "PENDING",
            "blocked_tasks": "BLOCKED",
            "failed_tasks": "FAILED",
        }

        for context_key, status_name in status_map.items():
            task_ids = persistent_context.get(context_key, [])
            if not isinstance(task_ids, list):
                continue

            for task_id in task_ids:
                task = state.get_task(str(task_id))
                if task is None:
                    continue
                task.status = task.status.__class__[status_name]

        state.touch()

    def _normalize_ratio(self, value: float) -> float:
        if value < 0.0:
            return 0.0
        if value > 1.0:
            return 1.0
        return value
