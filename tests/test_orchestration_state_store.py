from __future__ import annotations

import json
from pathlib import Path

import pytest

from impliforge.orchestration.state_store import StateStore
from impliforge.orchestration.workflow import SessionSnapshot, create_workflow_state


def build_state():
    state = create_workflow_state(
        workflow_id="wf-state-store-001",
        requirement="Add focused state store tests",
        model="gpt-5.4",
    )
    state.set_session("sess-store-001", parent_session_id="sess-parent-001")
    state.add_note("workflow note")
    state.add_risk("workflow risk")
    state.add_open_question("workflow question")
    state.add_artifact("artifacts/design.md")
    state.add_changed_file("src/impliforge/orchestration/state_store.py")
    state.update_task_status(
        "requirements_analysis",
        state.require_task("requirements_analysis").status.COMPLETED,
        note="requirements complete",
    )
    return state


def test_ensure_layout_and_directory_properties(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "artifacts")

    store.ensure_layout()

    assert store.workflow_dir == tmp_path / "artifacts" / "workflows"
    assert store.session_dir == tmp_path / "artifacts" / "sessions"
    assert store.summary_dir == tmp_path / "artifacts" / "summaries"
    assert store.workflow_dir.is_dir()
    assert store.session_dir.is_dir()
    assert store.summary_dir.is_dir()


def test_save_and_load_workflow_state_with_custom_file_name(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "artifacts")
    state = build_state()

    path = store.save_workflow_state(state, file_name="custom-workflow.json")

    assert path == (
        tmp_path
        / "artifacts"
        / "workflows"
        / state.workflow_id
        / "custom-workflow.json"
    )
    assert path.exists()

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "saved_at" in payload
    assert payload["workflow"]["workflow_id"] == state.workflow_id
    assert payload["workflow"]["session_id"] == "sess-store-001"
    assert (
        payload["workflow"]["execution_trace"][0]["event_type"]
        == "workflow_initialized"
    )
    assert payload["workflow"]["execution_trace"][-1]["event_type"] == "session_bound"
    assert payload["summary"]["workflow_id"] == state.workflow_id
    assert payload["summary"]["session_id"] == "sess-store-001"
    assert payload["summary"]["task_counts"]["completed"] == 1

    loaded = store.load_workflow_state(
        state.workflow_id, file_name="custom-workflow.json"
    )
    assert loaded == payload


def test_save_and_load_session_snapshot_uses_default_and_custom_names(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "artifacts")
    snapshot = SessionSnapshot(
        session_id="sess-snapshot-001",
        parent_session_id="sess-parent-001",
        token_usage_ratio=0.72,
        last_checkpoint="planning",
        next_action="Resume implementation",
        persistent_context={"workflow_id": "wf-state-store-001"},
    )

    default_path = store.save_session_snapshot(snapshot)
    custom_path = store.save_session_snapshot(snapshot, file_name="snapshot-alt.json")

    assert default_path == (
        tmp_path
        / "artifacts"
        / "sessions"
        / "sess-snapshot-001"
        / "session-snapshot.json"
    )
    assert custom_path == (
        tmp_path / "artifacts" / "sessions" / "sess-snapshot-001" / "snapshot-alt.json"
    )

    default_payload = store.load_session_snapshot("sess-snapshot-001")
    custom_payload = store.load_session_snapshot(
        "sess-snapshot-001",
        file_name="snapshot-alt.json",
    )

    assert default_payload["snapshot"]["session_id"] == "sess-snapshot-001"
    assert default_payload["snapshot"]["parent_session_id"] == "sess-parent-001"
    assert default_payload["snapshot"]["token_usage_ratio"] == 0.72
    assert default_payload["snapshot"]["last_checkpoint"] == "planning"
    assert default_payload["snapshot"]["next_action"] == "Resume implementation"
    assert default_payload["snapshot"]["persistent_context"] == {
        "workflow_id": "wf-state-store-001"
    }
    assert "created_at" in default_payload["snapshot"]
    assert custom_payload["snapshot"]["session_id"] == "sess-snapshot-001"


def test_save_and_load_run_summary_and_named_payload(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "artifacts")

    summary_path = store.save_run_summary(
        "wf-summary-001",
        {"status": "ok", "artifacts": ["artifacts/design.md"]},
        file_name="summary-alt.json",
    )
    payload_path = store.save_named_payload(
        Path("custom/nested/payload.json"),
        {"message": "hello", "count": 2},
    )

    assert summary_path == (
        tmp_path / "artifacts" / "summaries" / "wf-summary-001" / "summary-alt.json"
    )
    assert payload_path == (
        tmp_path / "artifacts" / "custom" / "nested" / "payload.json"
    )

    loaded_summary = store.load_run_summary(
        "wf-summary-001",
        file_name="summary-alt.json",
    )
    loaded_payload = store.load_named_payload("custom/nested/payload.json")

    assert loaded_summary["workflow_id"] == "wf-summary-001"
    assert loaded_summary["summary"] == {
        "status": "ok",
        "artifacts": ["artifacts/design.md"],
    }
    assert "saved_at" in loaded_summary

    assert loaded_payload["payload"] == {"message": "hello", "count": 2}
    assert "saved_at" in loaded_payload


def test_list_ids_and_exists_checks_reflect_saved_content(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "artifacts")

    state_a = build_state()
    state_b = create_workflow_state(
        workflow_id="wf-state-store-002",
        requirement="Another workflow",
        model="gpt-5.4",
    )
    snapshot_a = SessionSnapshot(session_id="sess-b")
    snapshot_b = SessionSnapshot(session_id="sess-a")

    store.save_workflow_state(state_b)
    store.save_workflow_state(state_a)
    store.save_session_snapshot(snapshot_a)
    store.save_session_snapshot(snapshot_b)

    assert store.list_workflow_ids() == ["wf-state-store-001", "wf-state-store-002"]
    assert store.list_session_ids() == ["sess-a", "sess-b"]

    assert store.workflow_exists("wf-state-store-001") is True
    assert store.workflow_exists("missing-workflow") is False
    assert store.session_exists("sess-a") is True
    assert store.session_exists("missing-session") is False


def test_load_methods_raise_file_not_found_for_missing_files(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "artifacts")

    with pytest.raises(FileNotFoundError, match="State file not found"):
        store.load_workflow_state("missing-workflow")

    with pytest.raises(FileNotFoundError, match="State file not found"):
        store.load_session_snapshot("missing-session")

    with pytest.raises(FileNotFoundError, match="State file not found"):
        store.load_run_summary("missing-workflow")

    with pytest.raises(FileNotFoundError, match="State file not found"):
        store.load_named_payload("missing/payload.json")


def test_to_dict_accepts_dataclass_and_dict_and_rejects_other_types(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "artifacts")
    snapshot = SessionSnapshot(session_id="sess-serialize")

    dataclass_payload = store._to_dict(snapshot)
    dict_payload = store._to_dict({"ok": True})

    assert dataclass_payload["session_id"] == "sess-serialize"
    assert dict_payload == {"ok": True}

    with pytest.raises(TypeError, match="Unsupported value type for serialization"):
        store._to_dict(["bad"])
