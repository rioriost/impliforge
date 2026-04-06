from __future__ import annotations

from pathlib import Path

from orchestration_test_helpers import (
    DummySessionManager,
    DummyStateStore,
    build_state,
)

from devagents.orchestration.runtime_support import RuntimeSupport
from devagents.runtime.editor import ApprovalDecision, EditOperationKind, EditRequest


def test_runtime_support_approval_hook_applies_expected_policy(
    tmp_path: Path,
) -> None:
    runtime_support = RuntimeSupport(
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )

    docs_request = EditRequest(
        relative_path="docs/design.md",
        operation=EditOperationKind.WRITE,
        content="# Design\n",
    )
    docs_result = runtime_support.approval_hook(
        docs_request,
        tmp_path / "docs" / "design.md",
    )
    assert docs_result.decision == ApprovalDecision.APPROVED

    src_write_request = EditRequest(
        relative_path="src/devagents/main.py",
        operation=EditOperationKind.WRITE,
        content="print('ok')\n",
    )
    src_write_result = runtime_support.approval_hook(
        src_write_request,
        tmp_path / "src" / "devagents" / "main.py",
    )
    assert src_write_result.decision == ApprovalDecision.APPROVED
    assert src_write_result.reason == "src/devagents allowlist permits controlled edits"

    src_delete_request = EditRequest(
        relative_path="src/devagents/main.py",
        operation=EditOperationKind.DELETE,
    )
    src_delete_result = runtime_support.approval_hook(
        src_delete_request,
        tmp_path / "src" / "devagents" / "main.py",
    )
    assert src_delete_result.decision == ApprovalDecision.DENIED
    assert (
        src_delete_result.reason
        == "delete operations under src/devagents are not allowed"
    )

    outside_request = EditRequest(
        relative_path="README.md",
        operation=EditOperationKind.WRITE,
        content="updated\n",
    )
    outside_result = runtime_support.approval_hook(
        outside_request,
        tmp_path / "README.md",
    )
    assert outside_result.decision == ApprovalDecision.DENIED
    assert outside_result.reason == "target is outside configured approval scope"


def test_runtime_support_rotates_session_and_records_snapshot(
    tmp_path: Path,
) -> None:
    state = build_state()
    session_manager = DummySessionManager(should_rotate=True)
    state_store = DummyStateStore(tmp_path / "artifacts")
    runtime_support = RuntimeSupport(
        state_store=state_store,
        session_manager=session_manager,
    )

    runtime_support.rotate_session_if_needed(
        state,
        token_usage_ratio=0.91,
        next_action="Resume review after test_execution",
        last_checkpoint="testing",
        persistent_context={"workflow_id": state.workflow_id},
    )

    assert len(session_manager.rotate_calls) == 1
    assert any(path.endswith("session-snapshot.json") for path in state.artifacts)
    assert any("mid-run session rotation" in note for note in state.notes)
    assert any("pre-rotation session snapshot" in note for note in state.notes)
