from __future__ import annotations

from impliforge.orchestration.session_manager import (
    SessionManager,
    SessionManagerConfig,
)
from impliforge.orchestration.workflow import SessionSnapshot, create_workflow_state


def build_state():
    state = create_workflow_state(
        workflow_id="wf-session-001",
        requirement="Add focused session manager tests",
        model="gpt-5.4",
    )
    state.set_session("sess-current", parent_session_id="sess-parent")
    state.add_note("note-1")
    state.add_note("note-2")
    state.add_risk("risk-1")
    state.add_open_question("question-1")
    state.add_artifact("artifacts/design.md")
    state.add_changed_file("src/impliforge/orchestration/session_manager.py")
    state.update_task_status(
        "requirements_analysis",
        state.require_task("requirements_analysis").status.COMPLETED,
        note="requirements complete",
    )
    state.update_task_status(
        "planning",
        state.require_task("planning").status.BLOCKED,
        note="waiting on review",
    )
    state.update_task_status(
        "implementation",
        state.require_task("implementation").status.FAILED,
        note="implementation failed once",
    )
    return state


def test_session_manager_config_validates_thresholds_and_limits() -> None:
    try:
        SessionManagerConfig(rotation_threshold=-0.1)
    except ValueError as exc:
        assert "rotation_threshold" in str(exc)
    else:
        raise AssertionError("expected invalid rotation_threshold to fail")

    try:
        SessionManagerConfig(hard_limit_threshold=1.1)
    except ValueError as exc:
        assert "hard_limit_threshold" in str(exc)
    else:
        raise AssertionError("expected invalid hard_limit_threshold to fail")

    try:
        SessionManagerConfig(rotation_threshold=0.9, hard_limit_threshold=0.8)
    except ValueError as exc:
        assert "less than or equal" in str(exc)
    else:
        raise AssertionError("expected inverted thresholds to fail")

    try:
        SessionManagerConfig(max_context_items=0)
    except ValueError as exc:
        assert "at least 1" in str(exc)
    else:
        raise AssertionError("expected invalid max_context_items to fail")


def test_start_session_sets_state_and_returns_context() -> None:
    state = create_workflow_state(
        workflow_id="wf-start-001",
        requirement="Start a session",
        model="gpt-5.4",
    )
    manager = SessionManager()

    context = manager.start_session(
        state,
        parent_session_id="sess-parent",
        session_id="sess-explicit",
    )

    assert context.current_session_id == "sess-explicit"
    assert context.parent_session_id == "sess-parent"
    assert state.session_id == "sess-explicit"
    assert state.parent_session_id == "sess-parent"
    assert any("Session started: sess-explicit" == note for note in state.notes)


def test_should_rotate_session_handles_force_thresholds_and_normalization() -> None:
    manager = SessionManager(
        SessionManagerConfig(
            rotation_threshold=0.5,
            hard_limit_threshold=0.8,
            session_id_prefix="sess",
        )
    )

    forced = manager.should_rotate_session(
        token_usage_ratio=-1.0,
        current_session_id="sess-current",
        force=True,
    )
    assert forced.should_rotate is True
    assert forced.reason == "forced"
    assert forced.token_usage_ratio == 0.0
    assert forced.current_session_id == "sess-current"
    assert forced.next_session_id is not None
    assert forced.next_session_id.startswith("sess-")

    hard_limit = manager.should_rotate_session(
        token_usage_ratio=1.5,
        current_session_id="sess-current",
    )
    assert hard_limit.should_rotate is True
    assert hard_limit.reason == "hard_limit_threshold_reached"
    assert hard_limit.token_usage_ratio == 1.0
    assert hard_limit.threshold == 0.8

    rotation = manager.should_rotate_session(
        token_usage_ratio=0.6,
        current_session_id="sess-current",
    )
    assert rotation.should_rotate is True
    assert rotation.reason == "rotation_threshold_reached"
    assert rotation.threshold == 0.5

    no_rotation = manager.should_rotate_session(
        token_usage_ratio=0.2,
        current_session_id="sess-current",
    )
    assert no_rotation.should_rotate is False
    assert no_rotation.reason is None
    assert no_rotation.next_session_id is None
    assert no_rotation.threshold == 0.5


def test_snapshot_context_builds_trimmed_persistent_context_and_resume_prompt() -> None:
    state = build_state()
    state.add_note("note-3")
    state.add_risk("risk-2")
    state.add_open_question("question-2")
    state.add_artifact("artifacts/tests.md")
    state.add_changed_file("src/impliforge/orchestration/state_store.py")

    manager = SessionManager(
        SessionManagerConfig(max_context_items=2, snapshot_version="v-test")
    )

    snapshot = manager.snapshot_context(
        state,
        token_usage_ratio=1.2,
        next_action="Resume planning",
    )

    assert snapshot.session_id == "sess-current"
    assert snapshot.parent_session_id == "sess-parent"
    assert snapshot.token_usage_ratio == 1.0
    assert snapshot.last_checkpoint == state.phase.value
    assert snapshot.next_action == "Resume planning"

    context = snapshot.persistent_context
    assert context["snapshot_version"] == "v-test"
    assert context["workflow_id"] == state.workflow_id
    assert context["requirement"] == state.requirement
    assert context["phase"] == state.phase.value
    assert context["session_id"] == "sess-current"
    assert context["parent_session_id"] == "sess-parent"
    assert context["completed_tasks"] == ["requirements_analysis"]
    assert context["blocked_tasks"] == ["planning"]
    assert context["failed_tasks"] == ["implementation"]
    assert context["notes"] == ["note-2", "note-3"]
    assert context["risks"] == ["risk-1", "risk-2"]
    assert context["open_questions"] == ["question-1", "question-2"]
    assert context["artifacts"] == ["artifacts/design.md", "artifacts/tests.md"]
    assert context["changed_files"] == [
        "src/impliforge/orchestration/session_manager.py",
        "src/impliforge/orchestration/state_store.py",
    ]
    assert context["next_action"] == "Resume planning"

    prompt = manager.build_resume_prompt(snapshot)
    assert "session_id: sess-current" in prompt
    assert "parent_session_id: sess-parent" in prompt
    assert f"last_checkpoint: {state.phase.value}" in prompt
    assert "next_action: Resume planning" in prompt
    assert "current_objective:" in prompt
    assert state.requirement in prompt
    assert "- requirements_analysis" in prompt
    assert "- question-1" in prompt
    assert "- question-2" in prompt
    assert "- artifacts/design.md" in prompt
    assert "- artifacts/tests.md" in prompt


def test_build_resume_prompt_uses_none_placeholders_when_lists_are_empty() -> None:
    manager = SessionManager()
    snapshot = SessionSnapshot(
        session_id="sess-empty",
        parent_session_id=None,
        last_checkpoint=None,
        next_action=None,
        persistent_context={
            "requirement": "",
            "completed_tasks": [],
            "open_questions": [],
            "artifacts": [],
        },
    )

    prompt = manager.build_resume_prompt(snapshot)

    assert "parent_session_id: none" in prompt
    assert "last_checkpoint: unknown" in prompt
    assert "next_action: unspecified" in prompt
    assert prompt.count("- none") == 3


def test_restore_context_merges_unique_items_and_adds_restore_note() -> None:
    state = create_workflow_state(
        workflow_id="wf-restore-001",
        requirement="Restore a session",
        model="gpt-5.4",
    )
    state.add_note("existing-note")
    state.add_risk("existing-risk")
    state.add_open_question("existing-question")
    state.add_artifact("existing-artifact")
    state.add_changed_file("existing-file.py")

    snapshot = SessionSnapshot(
        session_id="sess-restored",
        parent_session_id="sess-previous",
        persistent_context={
            "workflow_id": "wf-restore-001",
            "requirement": "Restore a session",
            "phase": state.phase.value,
            "session_id": "sess-restored",
            "completed_tasks": [],
            "pending_tasks": [],
            "next_action": "Resume implementation",
            "notes": ["existing-note", "new-note"],
            "risks": ["existing-risk", "new-risk"],
            "open_questions": ["existing-question", "new-question"],
            "artifacts": ["existing-artifact", "new-artifact"],
            "changed_files": ["existing-file.py", "new-file.py"],
        },
    )

    manager = SessionManager()
    restored = manager.restore_context(state, snapshot)

    assert restored is state
    assert state.session_id == "sess-restored"
    assert state.parent_session_id == "sess-previous"
    assert state.notes.count("existing-note") == 1
    assert "new-note" in state.notes
    assert state.risks == ["existing-risk", "new-risk"]
    assert state.open_questions == ["existing-question", "new-question"]
    assert state.artifacts == ["existing-artifact", "new-artifact"]
    assert state.changed_files == ["existing-file.py", "new-file.py"]
    assert any(
        note == "Session restored from snapshot: sess-restored" for note in state.notes
    )


def test_restore_context_rejects_incomplete_persistent_context() -> None:
    state = create_workflow_state(
        workflow_id="wf-restore-invalid",
        requirement="Reject incomplete restore context",
        model="gpt-5.4",
    )
    snapshot = SessionSnapshot(
        session_id="sess-invalid",
        parent_session_id="sess-parent",
        persistent_context={
            "workflow_id": "wf-restore-invalid",
            "requirement": "Reject incomplete restore context",
            "phase": state.phase.value,
            "session_id": "sess-invalid",
            "completed_tasks": [],
        },
    )

    manager = SessionManager()

    try:
        manager.restore_context(state, snapshot)
    except ValueError as exc:
        assert "latest consistent checkpoint" in str(exc)
        assert "pending_tasks" in str(exc)
        assert "next_action" in str(exc)
    else:
        raise AssertionError("expected incomplete restore context to fail")


def test_restore_context_recovers_task_statuses_from_persistent_context() -> None:
    state = create_workflow_state(
        workflow_id="wf-restore-tasks",
        requirement="Recover task statuses from snapshot",
        model="gpt-5.4",
    )
    snapshot = SessionSnapshot(
        session_id="sess-task-restore",
        parent_session_id="sess-parent",
        persistent_context={
            "workflow_id": "wf-restore-tasks",
            "requirement": "Recover task statuses from snapshot",
            "phase": state.phase.value,
            "session_id": "sess-task-restore",
            "completed_tasks": ["requirements_analysis"],
            "pending_tasks": ["documentation", "finalization"],
            "blocked_tasks": ["planning"],
            "failed_tasks": ["implementation"],
            "next_action": "Resume planning",
        },
    )

    manager = SessionManager()
    manager.restore_context(state, snapshot)

    assert state.require_task("requirements_analysis").status.value == "completed"
    assert state.require_task("planning").status.value == "blocked"
    assert state.require_task("implementation").status.value == "failed"
    assert state.require_task("documentation").status.value == "pending"
    assert state.require_task("finalization").status.value == "pending"


def test_restore_context_accepts_persisted_resume_summary_and_prompt_fields() -> None:
    state = create_workflow_state(
        workflow_id="wf-restore-summary",
        requirement="Recover persisted resume summary and prompt fields",
        model="gpt-5.4",
    )
    snapshot = SessionSnapshot(
        session_id="sess-summary-restore",
        parent_session_id="sess-parent",
        persistent_context={
            "workflow_id": "wf-restore-summary",
            "requirement": "Recover persisted resume summary and prompt fields",
            "phase": state.phase.value,
            "session_id": "sess-summary-restore",
            "completed_tasks": ["requirements_analysis"],
            "pending_tasks": ["planning"],
            "next_action": "Resume planning",
            "latest_summary": "Requirements normalized and ready for planning.",
            "resume_prompt": "Resume planning with the persisted context.",
        },
    )

    manager = SessionManager()
    restored = manager.restore_context(state, snapshot)

    assert restored is state
    assert state.session_id == "sess-summary-restore"
    assert state.parent_session_id == "sess-parent"
    assert state.require_task("requirements_analysis").status.value == "completed"
    assert state.require_task("planning").status.value == "pending"
    assert any(
        note == "Session restored from snapshot: sess-summary-restore"
        for note in state.notes
    )


def test_rotate_session_returns_snapshot_and_updates_state_when_rotation_occurs() -> (
    None
):
    state = build_state()
    manager = SessionManager(
        SessionManagerConfig(
            rotation_threshold=0.5,
            hard_limit_threshold=0.9,
            max_context_items=5,
        )
    )

    decision, snapshot = manager.rotate_session(
        state,
        token_usage_ratio=0.7,
        next_action="Continue implementation",
        last_checkpoint="planning",
    )

    assert decision.should_rotate is True
    assert decision.reason == "rotation_threshold_reached"
    assert snapshot.session_id == "sess-current"
    assert snapshot.parent_session_id == "sess-parent"
    assert snapshot.last_checkpoint == "planning"
    assert snapshot.next_action == "Continue implementation"
    assert state.parent_session_id == "sess-current"
    assert state.session_id == decision.next_session_id
    assert state.session_id is not None
    assert any("Session rotated: sess-current -> " in note for note in state.notes)


def test_rotate_session_without_rotation_keeps_current_session() -> None:
    state = build_state()
    manager = SessionManager(
        SessionManagerConfig(rotation_threshold=0.9, hard_limit_threshold=0.95)
    )

    decision, snapshot = manager.rotate_session(
        state,
        token_usage_ratio=0.2,
        next_action="Keep going",
        last_checkpoint="requirements",
    )

    assert decision.should_rotate is False
    assert snapshot.session_id == "sess-current"
    assert snapshot.last_checkpoint == "requirements"
    assert state.session_id == "sess-current"
    assert state.parent_session_id == "sess-parent"
    assert not any("Session rotated:" in note for note in state.notes)


def test_rotate_session_preserves_resumable_chain_across_repeated_rotations() -> None:
    state = build_state()
    manager = SessionManager(
        SessionManagerConfig(
            rotation_threshold=0.5,
            hard_limit_threshold=0.9,
            max_context_items=5,
        )
    )

    first_decision, first_snapshot = manager.rotate_session(
        state,
        token_usage_ratio=0.7,
        next_action="Resume implementation",
        last_checkpoint="implementation",
    )

    first_rotated_session_id = state.session_id
    assert first_decision.should_rotate is True
    assert first_rotated_session_id is not None

    state.add_note("post-rotation-note")
    state.add_open_question("post-rotation-question")
    state.add_artifact("artifacts/post-rotation.md")
    state.add_changed_file("src/impliforge/main.py")

    second_decision, second_snapshot = manager.rotate_session(
        state,
        token_usage_ratio=0.8,
        next_action="Resume review",
        last_checkpoint="reviewing",
    )

    assert second_decision.should_rotate is True
    assert first_snapshot.session_id == "sess-current"
    assert first_snapshot.parent_session_id == "sess-parent"
    assert first_snapshot.last_checkpoint == "implementation"
    assert first_snapshot.next_action == "Resume implementation"

    assert second_snapshot.session_id == first_rotated_session_id
    assert second_snapshot.parent_session_id == "sess-current"
    assert second_snapshot.last_checkpoint == "reviewing"
    assert second_snapshot.next_action == "Resume review"
    assert second_snapshot.persistent_context["session_id"] == first_rotated_session_id
    assert second_snapshot.persistent_context["parent_session_id"] == "sess-current"
    assert "post-rotation-note" in second_snapshot.persistent_context["notes"]
    assert (
        "post-rotation-question" in second_snapshot.persistent_context["open_questions"]
    )
    assert (
        "artifacts/post-rotation.md" in second_snapshot.persistent_context["artifacts"]
    )
    assert (
        "src/impliforge/main.py" in second_snapshot.persistent_context["changed_files"]
    )

    assert state.parent_session_id == first_rotated_session_id
    assert state.session_id == second_decision.next_session_id
    assert state.session_id is not None
    assert state.session_id != "sess-current"
    assert second_snapshot.session_id == state.parent_session_id
    assert sum(1 for note in state.notes if note.startswith("Session rotated:")) == 2
