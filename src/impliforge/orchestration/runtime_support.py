"""Runtime support helpers for approval policy and session rotation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from impliforge.models.routing import RoutingMode
from impliforge.orchestration.state_store import StateStore
from impliforge.orchestration.workflow import WorkflowState
from impliforge.runtime.editor import (
    ApprovalDecision,
    ApprovalResult,
    EditOperationKind,
    EditRequest,
    EditRiskFlag,
    approve_docs_and_artifacts_only,
    has_edit_risk_flag,
)

BUDGET_DEGRADED_TOKEN_USAGE_RATIO = 0.9


class SessionManagerLike(Protocol):
    """Protocol for the subset of session manager behavior used here."""

    def rotate_session(
        self,
        state: WorkflowState,
        *,
        token_usage_ratio: float,
        next_action: str,
        last_checkpoint: str,
        persistent_context: dict[str, Any],
    ) -> tuple[Any, Any]:
        """Rotate the current session when thresholds require it."""


@dataclass(slots=True)
class RuntimeSupport:
    """Shared runtime helpers extracted from the main orchestrator."""

    state_store: StateStore
    session_manager: SessionManagerLike

    def rotate_session_if_needed(
        self,
        state: WorkflowState,
        *,
        token_usage_ratio: float,
        next_action: str,
        last_checkpoint: str,
        persistent_context: dict[str, Any],
    ) -> None:
        """Rotate the session and persist the pre-rotation snapshot when needed."""
        decision, snapshot = self.session_manager.rotate_session(
            state,
            token_usage_ratio=token_usage_ratio,
            next_action=next_action,
            last_checkpoint=last_checkpoint,
            persistent_context=persistent_context,
        )
        if not getattr(decision, "should_rotate", False):
            return

        previous_session_id = snapshot.session_id
        previous_snapshot_path = self.state_store.save_session_snapshot(snapshot)
        state.add_note(
            "mid-run session rotation を実行し、後続フェーズを新 session で継続する。"
        )
        state.add_artifact(previous_snapshot_path.as_posix())
        state.add_note(
            f"pre-rotation session snapshot を保存した: {previous_session_id}"
        )

    def degraded_routing_mode(
        self,
        state: WorkflowState,
        *,
        routing_mode: RoutingMode,
    ) -> RoutingMode:
        """Downgrade routing mode when budget-like session pressure is high."""
        if routing_mode is RoutingMode.COST_SAVER:
            return routing_mode

        session_snapshot = getattr(state, "session_snapshot", None)
        if session_snapshot is None:
            return routing_mode

        token_usage_ratio = getattr(session_snapshot, "token_usage_ratio", None)
        if not isinstance(token_usage_ratio, int | float):
            return routing_mode

        if token_usage_ratio < BUDGET_DEGRADED_TOKEN_USAGE_RATIO:
            return routing_mode

        state.add_note(
            "budget-like token usage signal exceeded threshold; routing degraded to cost_saver mode."
        )
        state.add_risk(
            "High token usage triggered degraded routing mode; output quality may be reduced until budget pressure clears."
        )
        return RoutingMode.COST_SAVER

    def approval_hook(
        self,
        request: EditRequest,
        absolute_path: Path,
    ) -> ApprovalResult:
        """Apply the repository approval policy for safe editor requests."""
        relative_path = request.normalized_relative_path()

        if relative_path.startswith("docs/") or relative_path.startswith("artifacts/"):
            return approve_docs_and_artifacts_only(request, absolute_path)

        if relative_path.startswith("src/impliforge/"):
            if request.operation == EditOperationKind.DELETE:
                return ApprovalResult(
                    decision=ApprovalDecision.DENIED,
                    reason=(
                        "delete operations under src/impliforge require explicit human approval"
                    ),
                )

            if request.operation in {
                EditOperationKind.WRITE,
                EditOperationKind.APPEND,
            }:
                if self._requires_human_escalation(request):
                    return ApprovalResult(
                        decision=ApprovalDecision.DENIED,
                        reason=(
                            "dependency additions, environment changes, and security-impacting src/impliforge edits require explicit human approval"
                        ),
                    )
                return ApprovalResult(
                    decision=ApprovalDecision.APPROVED,
                    reason=(
                        "src/impliforge allowlist permits controlled write/append edits"
                    ),
                )

        return ApprovalResult(
            decision=ApprovalDecision.DENIED,
            reason=(
                "target is outside the allowed docs/artifacts/src/impliforge approval scope"
            ),
        )

    def _requires_human_escalation(self, request: EditRequest) -> bool:
        """Detect risky src edit intents that must not be auto-approved."""
        return has_edit_risk_flag(
            request,
            EditRiskFlag.DEPENDENCY_CHANGE,
            EditRiskFlag.ENVIRONMENT_CHANGE,
            EditRiskFlag.SECURITY_IMPACT,
            EditRiskFlag.SECRET_MATERIAL,
            EditRiskFlag.DESTRUCTIVE,
            EditRiskFlag.BROAD_OVERWRITE,
        )
