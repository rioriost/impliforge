from __future__ import annotations

from impliforge.agents.proposal_utils import (
    build_structured_edit_proposal,
    normalize_edit_payloads,
    normalize_string_list,
)


def test_normalize_string_list_trims_and_filters_values() -> None:
    assert normalize_string_list([" a ", "", "b", "   ", 3, None]) == [
        "a",
        "b",
        "3",
        "None",
    ]
    assert normalize_string_list("not-a-list") == []


def test_normalize_edit_payloads_filters_invalid_items() -> None:
    assert normalize_edit_payloads(
        [
            {
                "edit_kind": "replace_block",
                "target_symbol": "SafeEditor.apply",
                "intent": "Update safe editor apply flow",
            },
            {
                "edit_kind": "replace_block",
                "target_symbol": "",
                "intent": "missing symbol",
            },
            {
                "edit_kind": "",
                "target_symbol": "ImplementationAgent.run",
                "intent": "missing kind",
            },
            "skip",
        ]
    ) == [
        {
            "edit_kind": "replace_block",
            "target_symbol": "SafeEditor.apply",
            "intent": "Update safe editor apply flow",
        }
    ]
    assert normalize_edit_payloads("not-a-list") == []


def test_build_structured_edit_proposal_for_structured_code_editor() -> None:
    proposal = build_structured_edit_proposal(
        proposal_id="proposal-1",
        summary="Structured update",
        targets=["src/impliforge/runtime/editor.py", ""],
        instructions=[" keep scope small ", ""],
        edits=[
            {
                "edit_kind": "replace_block",
                "target_symbol": "SafeEditor.apply",
                "intent": "Update safe editor apply flow",
            },
            {
                "edit_kind": "",
                "target_symbol": "ignored",
                "intent": "ignored",
            },
        ],
        approval_policy="src_impliforge_structured_only",
        safe_edit_scope="src",
        consumability="structured_code_editor",
    )

    assert proposal == {
        "proposal_id": "proposal-1",
        "mode": "structured_update",
        "summary": "Structured update",
        "targets": ["src/impliforge/runtime/editor.py"],
        "instructions": ["keep scope small"],
        "edits": [
            {
                "edit_kind": "replace_block",
                "target_symbol": "SafeEditor.apply",
                "intent": "Update safe editor apply flow",
            }
        ],
        "approval_policy": "src_impliforge_structured_only",
        "safe_edit_scope": "src",
        "consumability": "structured_code_editor",
        "requires_explicit_approval": True,
        "safe_edit_ready": True,
    }


def test_build_structured_edit_proposal_for_safe_editor_without_edits() -> None:
    proposal = build_structured_edit_proposal(
        proposal_id="edit-1",
        summary="Tighten generated artifacts",
        targets=["docs/fix-report.md", ""],
        instructions=[
            " Keep the change small and directly tied to the unresolved issue. ",
            "",
        ],
        edits=[],
        approval_policy="docs_artifacts_only",
        safe_edit_scope="docs_artifacts",
        consumability="safe_editor",
    )

    assert proposal == {
        "proposal_id": "edit-1",
        "mode": "structured_update",
        "summary": "Tighten generated artifacts",
        "targets": ["docs/fix-report.md"],
        "instructions": [
            "Keep the change small and directly tied to the unresolved issue."
        ],
        "edits": [],
        "approval_policy": "docs_artifacts_only",
        "safe_edit_scope": "docs_artifacts",
        "consumability": "safe_editor",
        "requires_explicit_approval": False,
        "safe_edit_ready": True,
    }


def test_build_structured_edit_proposal_marks_not_ready_without_targets() -> None:
    proposal = build_structured_edit_proposal(
        proposal_id="proposal-empty",
        summary="No targets",
        targets=["", "   "],
        instructions=["Do nothing"],
        edits=[],
        approval_policy="docs_artifacts_only",
        safe_edit_scope="docs_artifacts",
        consumability="safe_editor",
    )

    assert proposal["targets"] == []
    assert proposal["safe_edit_ready"] is False
