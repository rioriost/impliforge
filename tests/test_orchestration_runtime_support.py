from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from orchestration_test_helpers import DummySessionManager, DummyStateStore, build_state

from impliforge.models.routing import RoutingMode
from impliforge.orchestration.runtime_support import RuntimeSupport
from impliforge.runtime.editor import (
    ApprovalDecision,
    EditOperationKind,
    EditRequest,
    EditRiskFlag,
)


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
        relative_path="src/impliforge/main.py",
        operation=EditOperationKind.WRITE,
        content="print('ok')\n",
    )
    src_write_result = runtime_support.approval_hook(
        src_write_request,
        tmp_path / "src" / "impliforge" / "main.py",
    )
    assert src_write_result.decision == ApprovalDecision.APPROVED
    assert (
        src_write_result.reason
        == "src/impliforge allowlist permits controlled write/append edits"
    )

    src_delete_request = EditRequest(
        relative_path="src/impliforge/main.py",
        operation=EditOperationKind.DELETE,
    )
    src_delete_result = runtime_support.approval_hook(
        src_delete_request,
        tmp_path / "src" / "impliforge" / "main.py",
    )
    assert src_delete_result.decision == ApprovalDecision.DENIED
    assert (
        src_delete_result.reason
        == "delete operations under src/impliforge require explicit human approval"
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
    assert (
        outside_result.reason
        == "target is outside the allowed docs/artifacts/src/impliforge approval scope"
    )


def test_runtime_support_approval_hook_denies_protected_src_root(
    tmp_path: Path,
) -> None:
    runtime_support = RuntimeSupport(
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )

    request = EditRequest(
        relative_path="src/other/module.py",
        operation=EditOperationKind.WRITE,
        content="print('blocked')\n",
    )

    result = runtime_support.approval_hook(
        request,
        tmp_path / "src" / "other" / "module.py",
    )

    assert result.decision == ApprovalDecision.DENIED
    assert (
        result.reason
        == "target is outside the allowed docs/artifacts/src/impliforge approval scope"
    )


def test_runtime_support_approval_hook_denies_broad_overwrite_intent(
    tmp_path: Path,
) -> None:
    runtime_support = RuntimeSupport(
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )

    request = EditRequest(
        relative_path="src/impliforge/main.py",
        operation=EditOperationKind.WRITE,
        content="print('ok')\n",
        reason="Replace large implementation block with regenerated content",
        risk_flags=(EditRiskFlag.BROAD_OVERWRITE,),
    )

    result = runtime_support.approval_hook(
        request,
        tmp_path / "src" / "impliforge" / "main.py",
    )

    assert result.decision == ApprovalDecision.DENIED
    assert (
        result.reason
        == "dependency additions, environment changes, and security-impacting src/impliforge edits require explicit human approval"
    )


def test_runtime_support_approval_hook_denies_dependency_addition_intent(
    tmp_path: Path,
) -> None:
    runtime_support = RuntimeSupport(
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )

    request = EditRequest(
        relative_path="src/impliforge/main.py",
        operation=EditOperationKind.WRITE,
        content="print('ok')\n",
        reason="Add dependency wiring for new package install flow",
        risk_flags=(EditRiskFlag.DEPENDENCY_CHANGE,),
    )

    result = runtime_support.approval_hook(
        request,
        tmp_path / "src" / "impliforge" / "main.py",
    )

    assert result.decision == ApprovalDecision.DENIED
    assert (
        result.reason
        == "dependency additions, environment changes, and security-impacting src/impliforge edits require explicit human approval"
    )


def test_runtime_support_approval_hook_denies_environment_change_intent(
    tmp_path: Path,
) -> None:
    runtime_support = RuntimeSupport(
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )

    request = EditRequest(
        relative_path="src/impliforge/main.py",
        operation=EditOperationKind.APPEND,
        content="print('ok')\n",
        reason="Update environment bootstrap and venv handling",
        risk_flags=(EditRiskFlag.ENVIRONMENT_CHANGE,),
    )

    result = runtime_support.approval_hook(
        request,
        tmp_path / "src" / "impliforge" / "main.py",
    )

    assert result.decision == ApprovalDecision.DENIED
    assert (
        result.reason
        == "dependency additions, environment changes, and security-impacting src/impliforge edits require explicit human approval"
    )


def test_runtime_support_approval_hook_denies_security_impacting_intent(
    tmp_path: Path,
) -> None:
    runtime_support = RuntimeSupport(
        state_store=DummyStateStore(tmp_path / "artifacts"),
        session_manager=DummySessionManager(),
    )

    request = EditRequest(
        relative_path="src/impliforge/main.py",
        operation=EditOperationKind.WRITE,
        content="print('ok')\n",
        reason="Adjust token permission checks for auth flow",
        risk_flags=(EditRiskFlag.SECURITY_IMPACT,),
    )

    result = runtime_support.approval_hook(
        request,
        tmp_path / "src" / "impliforge" / "main.py",
    )

    assert result.decision == ApprovalDecision.DENIED
    assert (
        result.reason
        == "dependency additions, environment changes, and security-impacting src/impliforge edits require explicit human approval"
    )


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


def test_runtime_support_repeated_rotations_persist_each_pre_rotation_snapshot(
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
    first_snapshot_path = (
        tmp_path / "artifacts" / "sessions" / "sess-test-001" / "session-snapshot.json"
    )

    state.set_session("sess-test-002", parent_session_id="sess-test-001")

    runtime_support.rotate_session_if_needed(
        state,
        token_usage_ratio=0.93,
        next_action="Resume finalization",
        last_checkpoint="review",
        persistent_context={"workflow_id": state.workflow_id},
    )
    second_snapshot_path = (
        tmp_path / "artifacts" / "sessions" / "sess-test-002" / "session-snapshot.json"
    )

    assert first_snapshot_path.exists()
    assert second_snapshot_path.exists()
    assert first_snapshot_path != second_snapshot_path
    assert first_snapshot_path.as_posix() in state.artifacts
    assert second_snapshot_path.as_posix() in state.artifacts
    assert len(session_manager.rotate_calls) == 2
    assert (
        sum(1 for note in state.notes if "pre-rotation session snapshot" in note) == 2
    )


def test_runtime_support_budget_degradation_switches_to_cost_saver() -> None:
    state = SimpleNamespace(
        session_snapshot=SimpleNamespace(token_usage_ratio=0.91),
        notes=[],
        risks=[],
    )
    state.add_note = state.notes.append
    state.add_risk = state.risks.append
    runtime_support = RuntimeSupport(
        state_store=DummyStateStore(Path("artifacts")),
        session_manager=DummySessionManager(),
    )

    effective_mode = runtime_support.degraded_routing_mode(
        state,
        routing_mode=RoutingMode.BALANCED,
    )

    assert effective_mode is RoutingMode.COST_SAVER
    assert any("routing degraded to cost_saver mode" in note for note in state.notes)
    assert any(
        "High token usage triggered degraded routing mode" in risk
        for risk in state.risks
    )


def test_runtime_support_budget_degradation_keeps_existing_cost_saver_mode() -> None:
    state = SimpleNamespace(
        session_snapshot=SimpleNamespace(token_usage_ratio=0.97),
        notes=[],
        risks=[],
    )
    state.add_note = state.notes.append
    state.add_risk = state.risks.append
    runtime_support = RuntimeSupport(
        state_store=DummyStateStore(Path("artifacts")),
        session_manager=DummySessionManager(),
    )

    effective_mode = runtime_support.degraded_routing_mode(
        state,
        routing_mode=RoutingMode.COST_SAVER,
    )

    assert effective_mode is RoutingMode.COST_SAVER
    assert not any(
        "routing degraded to cost_saver mode" in note for note in state.notes
    )
    assert not any(
        "High token usage triggered degraded routing mode" in risk
        for risk in state.risks
    )


def test_runtime_support_budget_degradation_ignores_missing_budget_signal() -> None:
    state = build_state()
    runtime_support = RuntimeSupport(
        state_store=DummyStateStore(Path("artifacts")),
        session_manager=DummySessionManager(),
    )

    effective_mode = runtime_support.degraded_routing_mode(
        state,
        routing_mode=RoutingMode.BALANCED,
    )

    assert effective_mode is RoutingMode.BALANCED
    assert not any(
        "routing degraded to cost_saver mode" in note for note in state.notes
    )
    assert not any(
        "High token usage triggered degraded routing mode" in risk
        for risk in state.risks
    )
