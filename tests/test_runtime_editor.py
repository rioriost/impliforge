from __future__ import annotations

from pathlib import Path

import pytest

from devagents.runtime.editor import (
    ApprovalDecision,
    ApprovalResult,
    EditOperationKind,
    EditorError,
    EditorPolicy,
    EditRequest,
    EditRiskFlag,
    SafeEditor,
    approve_docs_and_artifacts_only,
    approve_docs_artifacts_and_src_devagents,
)


def test_editor_policy_handles_allowlist_and_protected_src_paths() -> None:
    policy = EditorPolicy(
        allowed_roots=("docs", "artifacts"),
        protected_roots=(".git", ".venv"),
        src_allowed_prefixes=("src/devagents",),
    )

    assert policy.is_allowed_root("docs/design.md") is True
    assert policy.is_allowed_root("artifacts/run/output.json") is True
    assert policy.is_allowed_root("src/devagents/runtime/editor.py") is True
    assert policy.is_allowed_root("src/other/module.py") is False
    assert policy.is_allowed_root("README.md") is False

    assert policy.is_protected_root(".git/config") is True
    assert policy.is_protected_root(".venv/bin/python") is True
    assert policy.is_protected_root("src/other/module.py") is True
    assert policy.is_protected_root("src/devagents/runtime/editor.py") is False

    assert policy.requires_src_approval("src") is True
    assert policy.requires_src_approval("src/devagents/runtime/editor.py") is True
    assert policy.requires_src_approval("docs/design.md") is False


def test_apply_rejects_paths_outside_allowed_roots(tmp_path: Path) -> None:
    editor = SafeEditor(tmp_path)

    result = editor.apply(
        EditRequest(
            relative_path="README.md",
            operation=EditOperationKind.WRITE,
            content="hello\n",
        )
    )

    assert result.ok is False
    assert result.changed is False
    assert "outside allowed roots" in result.message


def test_apply_rejects_protected_src_path_even_if_src_root_is_allowed(
    tmp_path: Path,
) -> None:
    editor = SafeEditor(
        tmp_path,
        allowed_roots=["docs", "artifacts", "src"],
        src_allowed_prefixes=["src/devagents"],
    )

    result = editor.apply(
        EditRequest(
            relative_path="src/other/module.py",
            operation=EditOperationKind.WRITE,
            content="print('blocked')\n",
        )
    )

    assert result.ok is False
    assert result.changed is False
    assert "protected root" in result.message


def test_write_append_delete_and_ensure_directory_paths(tmp_path: Path) -> None:
    editor = SafeEditor(
        tmp_path,
        approval_hook=lambda request, path: ApprovalResult(
            decision=ApprovalDecision.APPROVED,
            reason="approved for test",
        ),
    )

    ensure_result = editor.apply(
        EditRequest(
            relative_path="artifacts/reports",
            operation=EditOperationKind.ENSURE_DIRECTORY,
        )
    )
    assert ensure_result.ok is True
    assert ensure_result.changed is True
    assert (tmp_path / "artifacts" / "reports").is_dir()

    write_result = editor.apply(
        EditRequest(
            relative_path="artifacts/reports/result.txt",
            operation=EditOperationKind.WRITE,
            content="alpha",
        )
    )
    assert write_result.ok is True
    assert write_result.changed is True
    assert (tmp_path / "artifacts" / "reports" / "result.txt").read_text(
        encoding="utf-8"
    ) == "alpha"

    append_result = editor.apply(
        EditRequest(
            relative_path="artifacts/reports/result.txt",
            operation=EditOperationKind.APPEND,
            content="beta",
        )
    )
    assert append_result.ok is True
    assert append_result.changed is True
    assert (tmp_path / "artifacts" / "reports" / "result.txt").read_text(
        encoding="utf-8"
    ) == "alphabeta"

    delete_result = editor.apply(
        EditRequest(
            relative_path="artifacts/reports/result.txt",
            operation=EditOperationKind.DELETE,
        )
    )
    assert delete_result.ok is True
    assert delete_result.changed is True
    assert not (tmp_path / "artifacts" / "reports" / "result.txt").exists()


def test_write_without_overwrite_fails_when_target_exists(tmp_path: Path) -> None:
    target = tmp_path / "docs" / "design.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("original\n", encoding="utf-8")

    editor = SafeEditor(tmp_path)

    result = editor.apply(
        EditRequest(
            relative_path="docs/design.md",
            operation=EditOperationKind.WRITE,
            content="replacement\n",
            overwrite=False,
        )
    )

    assert result.ok is False
    assert result.changed is False
    assert result.message == "Target exists and overwrite is disabled."
    assert target.read_text(encoding="utf-8") == "original\n"


def test_delete_without_approval_hook_is_denied(tmp_path: Path) -> None:
    target = tmp_path / "artifacts" / "old.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("stale\n", encoding="utf-8")

    editor = SafeEditor(tmp_path)

    result = editor.apply(
        EditRequest(
            relative_path="artifacts/old.txt",
            operation=EditOperationKind.DELETE,
        )
    )

    assert result.ok is False
    assert result.changed is False
    assert (
        result.message
        == "Edit denied: approval required but no approval hook is configured."
    )
    assert target.exists()


def test_overwrite_outside_docs_requires_approval_and_calls_hook(
    tmp_path: Path,
) -> None:
    target = tmp_path / "artifacts" / "report.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("old\n", encoding="utf-8")

    calls: list[tuple[EditRequest, Path]] = []

    def approval_hook(request: EditRequest, absolute_path: Path) -> ApprovalResult:
        calls.append((request, absolute_path))
        return ApprovalResult(
            decision=ApprovalDecision.APPROVED,
            reason="overwrite approved",
        )

    editor = SafeEditor(tmp_path, approval_hook=approval_hook)

    result = editor.apply(
        EditRequest(
            relative_path="artifacts/report.txt",
            operation=EditOperationKind.WRITE,
            content="new\n",
        )
    )

    assert result.ok is True
    assert target.read_text(encoding="utf-8") == "new\n"
    assert len(calls) == 1
    request, absolute_path = calls[0]
    assert request.relative_path == "artifacts/report.txt"
    assert request.operation == EditOperationKind.WRITE
    assert absolute_path == target.resolve()


def test_src_edit_requires_approval_and_denial_reason_is_propagated(
    tmp_path: Path,
) -> None:
    calls: list[tuple[EditRequest, Path]] = []

    def approval_hook(request: EditRequest, absolute_path: Path) -> ApprovalResult:
        calls.append((request, absolute_path))
        return ApprovalResult(
            decision=ApprovalDecision.DENIED,
            reason="src edits blocked",
        )

    editor = SafeEditor(tmp_path, approval_hook=approval_hook)

    result = editor.apply(
        EditRequest(
            relative_path="src/devagents/runtime/generated.py",
            operation=EditOperationKind.WRITE,
            content="value = 1\n",
        )
    )

    assert result.ok is False
    assert result.changed is False
    assert result.message == "Edit denied: src edits blocked."
    assert len(calls) == 1
    assert calls[0][0].relative_path == "src/devagents/runtime/generated.py"


def test_preview_and_dry_run_report_changes_without_mutating_filesystem(
    tmp_path: Path,
) -> None:
    target = tmp_path / "artifacts" / "preview.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("before\n", encoding="utf-8")

    editor = SafeEditor(
        tmp_path,
        approval_hook=lambda request, path: ApprovalResult(
            decision=ApprovalDecision.APPROVED,
            reason="approved for preview",
        ),
    )

    preview_result = editor.preview(
        EditRequest(
            relative_path="artifacts/preview.txt",
            operation=EditOperationKind.WRITE,
            content="after\n",
        )
    )

    assert preview_result.ok is True
    assert preview_result.dry_run is True
    assert preview_result.changed is True
    assert preview_result.message == "Dry-run write accepted."
    assert target.read_text(encoding="utf-8") == "before\n"

    dry_run_editor = SafeEditor(tmp_path, dry_run=True)
    ensure_result = dry_run_editor.apply(
        EditRequest(
            relative_path="artifacts/generated",
            operation=EditOperationKind.ENSURE_DIRECTORY,
        )
    )
    append_result = dry_run_editor.apply(
        EditRequest(
            relative_path="docs/notes.md",
            operation=EditOperationKind.APPEND,
            content="line\n",
        )
    )

    assert ensure_result.ok is True
    assert ensure_result.dry_run is True
    assert ensure_result.changed is True
    assert ensure_result.message == "Dry-run ensure_directory accepted."
    assert not (tmp_path / "artifacts" / "generated").exists()

    assert append_result.ok is True
    assert append_result.dry_run is True
    assert append_result.changed is True
    assert append_result.message == "Dry-run append accepted."
    assert not (tmp_path / "docs" / "notes.md").exists()


def test_apply_many_and_apply_operations_return_expected_results(
    tmp_path: Path,
) -> None:
    editor = SafeEditor(
        tmp_path,
        approval_hook=lambda request, path: ApprovalResult(
            decision=ApprovalDecision.APPROVED,
            reason="approved for batch",
        ),
    )

    requests = [
        EditRequest(
            relative_path="docs/guide.md",
            operation=EditOperationKind.WRITE,
            content="guide\n",
        ),
        EditRequest(
            relative_path="artifacts/log.txt",
            operation=EditOperationKind.APPEND,
            content="entry\n",
        ),
        EditRequest(
            relative_path="README.md",
            operation=EditOperationKind.WRITE,
            content="blocked\n",
        ),
    ]

    results = editor.apply_many(requests)
    changed_paths = editor.apply_operations(requests[:2])

    assert [result.ok for result in results] == [True, True, False]
    assert changed_paths == ["artifacts/log.txt"]


def test_validate_relative_path_rejects_empty_absolute_and_traversal_paths(
    tmp_path: Path,
) -> None:
    editor = SafeEditor(tmp_path)

    with pytest.raises(EditorError, match="relative_path must not be empty"):
        editor.apply(EditRequest(relative_path="", content="x"))

    with pytest.raises(EditorError, match="absolute paths are not allowed"):
        editor.apply(
            EditRequest(
                relative_path=(tmp_path / "docs" / "absolute.md").as_posix(),
                content="x",
            )
        )

    with pytest.raises(EditorError, match="path traversal is not allowed"):
        editor.apply(EditRequest(relative_path="../docs/escape.md", content="x"))


def test_conservative_approval_hook_only_allows_docs_and_artifacts_writes() -> None:
    docs_result = approve_docs_and_artifacts_only(
        EditRequest(
            relative_path="docs/design.md",
            operation=EditOperationKind.WRITE,
            content="# Design\n",
        ),
        Path("/tmp/docs/design.md"),
    )
    artifacts_result = approve_docs_and_artifacts_only(
        EditRequest(
            relative_path="artifacts/run.json",
            operation=EditOperationKind.APPEND,
            content="{}\n",
        ),
        Path("/tmp/artifacts/run.json"),
    )
    delete_result = approve_docs_and_artifacts_only(
        EditRequest(
            relative_path="docs/design.md",
            operation=EditOperationKind.DELETE,
        ),
        Path("/tmp/docs/design.md"),
    )
    outside_result = approve_docs_and_artifacts_only(
        EditRequest(
            relative_path="src/devagents/runtime/editor.py",
            operation=EditOperationKind.WRITE,
            content="x = 1\n",
        ),
        Path("/tmp/src/devagents/runtime/editor.py"),
    )

    assert docs_result.decision == ApprovalDecision.APPROVED
    assert artifacts_result.decision == ApprovalDecision.APPROVED
    assert delete_result.decision == ApprovalDecision.DENIED
    assert outside_result.decision == ApprovalDecision.DENIED


def test_scoped_src_approval_hook_allows_src_devagents_but_denies_delete() -> None:
    src_result = approve_docs_artifacts_and_src_devagents(
        EditRequest(
            relative_path="src/devagents/runtime/editor.py",
            operation=EditOperationKind.WRITE,
            content="x = 1\n",
        ),
        Path("/tmp/src/devagents/runtime/editor.py"),
    )
    docs_result = approve_docs_artifacts_and_src_devagents(
        EditRequest(
            relative_path="docs/design.md",
            operation=EditOperationKind.APPEND,
            content="note\n",
        ),
        Path("/tmp/docs/design.md"),
    )
    delete_result = approve_docs_artifacts_and_src_devagents(
        EditRequest(
            relative_path="src/devagents/runtime/editor.py",
            operation=EditOperationKind.DELETE,
        ),
        Path("/tmp/src/devagents/runtime/editor.py"),
    )
    outside_result = approve_docs_artifacts_and_src_devagents(
        EditRequest(
            relative_path="src/other/module.py",
            operation=EditOperationKind.WRITE,
            content="x = 1\n",
        ),
        Path("/tmp/src/other/module.py"),
    )

    assert src_result.decision == ApprovalDecision.APPROVED
    assert src_result.reason == "allowed by src/devagents scoped approval policy"
    assert docs_result.decision == ApprovalDecision.APPROVED
    assert delete_result.decision == ApprovalDecision.DENIED
    assert delete_result.reason == "delete operations require explicit custom approval"
    assert outside_result.decision == ApprovalDecision.DENIED
    assert (
        outside_result.reason
        == "target is outside approved src/devagents/docs/artifacts scope"
    )


def test_conservative_approval_hook_denies_secret_like_content() -> None:
    result = approve_docs_and_artifacts_only(
        EditRequest(
            relative_path="docs/design.md",
            operation=EditOperationKind.WRITE,
            content='api_key = "super-secret-value"\n',
        ),
        Path("/tmp/docs/design.md"),
    )

    assert result.decision == ApprovalDecision.DENIED
    assert (
        result.reason
        == "secret-like content detected; explicit human approval is required"
    )


def test_scoped_src_approval_hook_denies_secret_like_content() -> None:
    result = approve_docs_artifacts_and_src_devagents(
        EditRequest(
            relative_path="src/devagents/runtime/editor.py",
            operation=EditOperationKind.WRITE,
            content='password = "super-secret-value"\n',
        ),
        Path("/tmp/src/devagents/runtime/editor.py"),
    )

    assert result.decision == ApprovalDecision.DENIED
    assert (
        result.reason
        == "secret-like content detected; explicit human approval is required"
    )


def test_conservative_approval_hook_denies_structured_secret_risk_flag() -> None:
    result = approve_docs_and_artifacts_only(
        EditRequest(
            relative_path="docs/design.md",
            operation=EditOperationKind.WRITE,
            content="# Design\n",
            risk_flags=(EditRiskFlag.SECRET_MATERIAL,),
        ),
        Path("/tmp/docs/design.md"),
    )

    assert result.decision == ApprovalDecision.DENIED
    assert (
        result.reason
        == "secret-like content detected; explicit human approval is required"
    )


def test_scoped_src_approval_hook_denies_structured_secret_risk_flag() -> None:
    result = approve_docs_artifacts_and_src_devagents(
        EditRequest(
            relative_path="src/devagents/runtime/editor.py",
            operation=EditOperationKind.WRITE,
            content="value = 1\n",
            risk_flags=(EditRiskFlag.SECRET_MATERIAL,),
        ),
        Path("/tmp/src/devagents/runtime/editor.py"),
    )

    assert result.decision == ApprovalDecision.DENIED
    assert (
        result.reason
        == "secret-like content detected; explicit human approval is required"
    )
