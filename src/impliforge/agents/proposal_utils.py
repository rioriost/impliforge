"""Shared proposal-building utilities for workflow agents."""

from __future__ import annotations

from typing import Any


def normalize_string_list(value: Any) -> list[str]:
    """Return a trimmed list of non-empty string values."""
    if not isinstance(value, list):
        return []

    normalized: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            normalized.append(text)
    return normalized


def normalize_edit_payloads(value: Any) -> list[dict[str, str]]:
    """Normalize structured edit payloads for proposal emission."""
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue

        edit_kind = str(item.get("edit_kind", "")).strip()
        target_symbol = str(item.get("target_symbol", "")).strip()
        intent = str(item.get("intent", "")).strip()

        if not edit_kind or not target_symbol or not intent:
            continue

        normalized.append(
            {
                "edit_kind": edit_kind,
                "target_symbol": target_symbol,
                "intent": intent,
            }
        )

    return normalized


def build_structured_edit_proposal(
    *,
    proposal_id: str,
    summary: str,
    targets: list[str],
    instructions: list[str],
    approval_policy: str,
    safe_edit_scope: str,
    consumability: str,
    edits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a normalized structured edit proposal payload.

    This helper is intended to be shared by agents that emit proposal objects
    consumed by the safe edit phase or structured code editing phase.
    """
    normalized_targets = normalize_string_list(targets)
    normalized_instructions = normalize_string_list(instructions)
    normalized_edits = normalize_edit_payloads(edits or [])

    return {
        "proposal_id": str(proposal_id).strip(),
        "mode": "structured_update",
        "summary": str(summary).strip(),
        "targets": normalized_targets,
        "instructions": normalized_instructions,
        "edits": normalized_edits,
        "approval_policy": str(approval_policy).strip(),
        "safe_edit_scope": str(safe_edit_scope).strip(),
        "consumability": str(consumability).strip(),
        "requires_explicit_approval": str(approval_policy).strip()
        != "docs_artifacts_only",
        "safe_edit_ready": bool(
            normalized_targets
            and (normalized_edits or str(consumability).strip() == "safe_editor")
        ),
    }
