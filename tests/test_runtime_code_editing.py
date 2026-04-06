from __future__ import annotations

from pathlib import Path

import pytest

from devagents.orchestration.workflow import (
    TaskStatus,
    WorkflowPhase,
    WorkflowTask,
    build_default_tasks,
    create_workflow_state,
)
from devagents.runtime.code_editing import (
    CodeApprovalDecision,
    CodeApprovalResult,
    CodeEditingError,
    CodeEditingPolicy,
    CodeEditKind,
    CodeEditRequest,
    StructuredCodeEditor,
    approve_src_devagents_only,
)


def _write_source(root: Path, relative_path: str, content: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_validate_relative_path_rejects_empty_absolute_and_traversal(
    tmp_path: Path,
) -> None:
    editor = StructuredCodeEditor(tmp_path)

    with pytest.raises(CodeEditingError, match="relative_path must not be empty"):
        editor.apply(
            CodeEditRequest(
                relative_path="",
                kind=CodeEditKind.REPLACE_SNIPPET,
                reason="invalid",
                old_snippet="a",
                new_snippet="b",
            )
        )

    absolute_target = (tmp_path / "src/devagents/runtime/code_editing.py").resolve()
    with pytest.raises(CodeEditingError, match="absolute paths are not allowed"):
        editor.apply(
            CodeEditRequest(
                relative_path=absolute_target.as_posix(),
                kind=CodeEditKind.REPLACE_SNIPPET,
                reason="invalid",
                old_snippet="a",
                new_snippet="b",
            )
        )

    with pytest.raises(CodeEditingError, match="path traversal is not allowed"):
        editor.apply(
            CodeEditRequest(
                relative_path="../src/devagents/runtime/code_editing.py",
                kind=CodeEditKind.REPLACE_SNIPPET,
                reason="invalid",
                old_snippet="a",
                new_snippet="b",
            )
        )


def test_policy_allowlist_and_protected_prefix_behavior() -> None:
    policy = CodeEditingPolicy(
        allowed_prefixes=("src/devagents", ".git"),
        protected_prefixes=(".git", ".venv"),
        allowed_extensions=(".py",),
    )

    assert policy.is_allowed_path("src/devagents/runtime/code_editing.py") is True
    assert policy.is_allowed_path("docs/design.md") is False
    assert policy.is_allowed_path("src/devagents/runtime/code_editing.md") is False
    assert policy.is_allowed_path(".git/hooks/pre-commit.py") is False
    assert policy.is_protected_path(".git/config") is True
    assert policy.is_protected_path("src/devagents/runtime/code_editing.py") is False


def test_apply_denies_missing_file_when_creation_disabled(tmp_path: Path) -> None:
    editor = StructuredCodeEditor(
        tmp_path,
        policy=CodeEditingPolicy(require_approval=False),
    )

    result = editor.apply(
        CodeEditRequest(
            relative_path="src/devagents/runtime/new_module.py",
            kind=CodeEditKind.ENSURE_SNIPPET,
            reason="create denied",
            content="print('x')",
        )
    )

    assert result.ok is False
    assert result.changed is False
    assert "creating new source files is disabled" in result.message


def test_replace_marked_block_updates_only_marked_region(tmp_path: Path) -> None:
    target = _write_source(
        tmp_path,
        "src/devagents/runtime/sample.py",
        "before\n# BEGIN BLOCK\nold value\n# END BLOCK\nafter\n",
    )
    editor = StructuredCodeEditor(
        tmp_path,
        policy=CodeEditingPolicy(require_approval=False),
    )

    result = editor.apply(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.REPLACE_MARKED_BLOCK,
            reason="refresh block",
            begin_marker="# BEGIN BLOCK",
            end_marker="# END BLOCK",
            content="new value",
        )
    )

    assert result.ok is True
    assert result.changed is True
    assert target.read_text(encoding="utf-8") == (
        "before\n# BEGIN BLOCK\nnew value# END BLOCK\nafter\n"
    )


def test_replace_marked_block_requires_markers_and_content(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "src/devagents/runtime/sample.py",
        "# BEGIN BLOCK\nold\n# END BLOCK\n",
    )
    editor = StructuredCodeEditor(
        tmp_path,
        policy=CodeEditingPolicy(require_approval=False),
    )

    missing_marker = editor.apply(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.REPLACE_MARKED_BLOCK,
            reason="invalid",
            end_marker="# END BLOCK",
            content="new",
        )
    )
    missing_content = editor.apply(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.REPLACE_MARKED_BLOCK,
            reason="invalid",
            begin_marker="# BEGIN BLOCK",
            end_marker="# END BLOCK",
        )
    )

    assert missing_marker.ok is False
    assert "requires begin_marker and end_marker" in missing_marker.message
    assert missing_content.ok is False
    assert "requires content" in missing_content.message


def test_replace_snippet_rejects_ambiguous_match(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "src/devagents/runtime/sample.py",
        "value = 1\nvalue = 1\n",
    )
    editor = StructuredCodeEditor(
        tmp_path,
        policy=CodeEditingPolicy(require_approval=False),
    )

    result = editor.apply(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.REPLACE_SNIPPET,
            reason="ambiguous",
            old_snippet="value = 1",
            new_snippet="value = 2",
        )
    )

    assert result.ok is False
    assert "matched multiple locations" in result.message


def test_ensure_snippet_inserts_after_marker_and_is_idempotent(tmp_path: Path) -> None:
    target = _write_source(
        tmp_path,
        "src/devagents/runtime/sample.py",
        "header\nMARKER\nfooter\n",
    )
    editor = StructuredCodeEditor(
        tmp_path,
        policy=CodeEditingPolicy(require_approval=False),
    )
    request = CodeEditRequest(
        relative_path="src/devagents/runtime/sample.py",
        kind=CodeEditKind.ENSURE_SNIPPET,
        reason="ensure helper",
        marker="MARKER",
        content="inserted = True",
    )

    first = editor.apply(request)
    second = editor.apply(request)

    assert first.ok is True
    assert first.changed is True
    assert second.ok is True
    assert second.changed is False
    assert target.read_text(encoding="utf-8") == (
        "header\nMARKER\ninserted = True\nfooter\n"
    )


def test_apply_uses_approval_hook_and_returns_denial_reason(tmp_path: Path) -> None:
    target = _write_source(
        tmp_path,
        "src/devagents/runtime/sample.py",
        "value = 1\n",
    )
    calls: list[tuple[str, str]] = []

    def deny_hook(request: CodeEditRequest, absolute_path: Path) -> CodeApprovalResult:
        calls.append((request.relative_path, absolute_path.as_posix()))
        return CodeApprovalResult(
            decision=CodeApprovalDecision.DENIED,
            reason="manual review required",
        )

    editor = StructuredCodeEditor(
        tmp_path,
        approval_hook=deny_hook,
    )

    result = editor.apply(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.REPLACE_SNIPPET,
            reason="needs approval",
            old_snippet="value = 1",
            new_snippet="value = 2",
        )
    )

    assert calls == [("src/devagents/runtime/sample.py", target.as_posix())]
    assert result.ok is False
    assert result.changed is False
    assert "manual review required" in result.message
    assert target.read_text(encoding="utf-8") == "value = 1\n"


def test_apply_requires_approval_hook_when_policy_demands_it(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "src/devagents/runtime/sample.py",
        "value = 1\n",
    )
    editor = StructuredCodeEditor(tmp_path)

    result = editor.apply(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.REPLACE_SNIPPET,
            reason="missing hook",
            old_snippet="value = 1",
            new_snippet="value = 2",
        )
    )

    assert result.ok is False
    assert "approval required but no approval hook is configured" in result.message


def test_preview_and_dry_run_report_change_without_writing(tmp_path: Path) -> None:
    target = _write_source(
        tmp_path,
        "src/devagents/runtime/sample.py",
        "value = 1\n",
    )
    editor = StructuredCodeEditor(
        tmp_path,
        policy=CodeEditingPolicy(require_approval=False),
    )

    preview = editor.preview(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.REPLACE_SNIPPET,
            reason="preview",
            old_snippet="value = 1",
            new_snippet="value = 2",
        )
    )

    dry_run_editor = StructuredCodeEditor(
        tmp_path,
        policy=CodeEditingPolicy(require_approval=False),
        dry_run=True,
    )
    dry_run = dry_run_editor.apply(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.REPLACE_SNIPPET,
            reason="dry-run",
            old_snippet="value = 1",
            new_snippet="value = 3",
        )
    )

    assert preview.ok is True
    assert preview.changed is True
    assert preview.dry_run is True
    assert dry_run.ok is True
    assert dry_run.changed is True
    assert dry_run.dry_run is True
    assert target.read_text(encoding="utf-8") == "value = 1\n"


def test_approve_src_devagents_only_allows_python_and_denies_outside_scope() -> None:
    approved = approve_src_devagents_only(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.INSERT_AFTER_MARKER,
            reason="ok",
            marker="x",
            content="y",
        ),
        Path("/tmp/src/devagents/runtime/sample.py"),
    )
    denied = approve_src_devagents_only(
        CodeEditRequest(
            relative_path="docs/design.md",
            kind=CodeEditKind.INSERT_AFTER_MARKER,
            reason="nope",
            marker="x",
            content="y",
        ),
        Path("/tmp/docs/design.md"),
    )

    assert approved.decision is CodeApprovalDecision.APPROVED
    assert denied.decision is CodeApprovalDecision.DENIED
    assert "outside src/devagents approval scope" in denied.reason


def test_insert_after_and_before_marker_require_inputs_and_marker_presence(
    tmp_path: Path,
) -> None:
    _write_source(
        tmp_path,
        "src/devagents/runtime/sample.py",
        "alpha\nMARKER\nomega\n",
    )
    editor = StructuredCodeEditor(
        tmp_path,
        policy=CodeEditingPolicy(require_approval=False),
    )

    missing_after_marker = editor.apply(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.INSERT_AFTER_MARKER,
            reason="invalid",
            content="x",
        )
    )
    missing_after_content = editor.apply(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.INSERT_AFTER_MARKER,
            reason="invalid",
            marker="MARKER",
        )
    )
    missing_before_marker = editor.apply(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.INSERT_BEFORE_MARKER,
            reason="invalid",
            content="x",
        )
    )
    missing_before_content = editor.apply(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.INSERT_BEFORE_MARKER,
            reason="invalid",
            marker="MARKER",
        )
    )
    marker_not_found = editor.apply(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.INSERT_BEFORE_MARKER,
            reason="invalid",
            marker="MISSING",
            content="x",
        )
    )

    assert "insert_after_marker requires marker" in missing_after_marker.message
    assert "insert_after_marker requires content" in missing_after_content.message
    assert "insert_before_marker requires marker" in missing_before_marker.message
    assert "insert_before_marker requires content" in missing_before_content.message
    assert "Marker not found" in marker_not_found.message


def test_insert_before_marker_and_replace_snippet_success_paths(tmp_path: Path) -> None:
    target = _write_source(
        tmp_path,
        "src/devagents/runtime/sample.py",
        "alpha\nMARKER\nvalue = 1\n",
    )
    editor = StructuredCodeEditor(
        tmp_path,
        policy=CodeEditingPolicy(require_approval=False),
    )

    inserted = editor.apply(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.INSERT_BEFORE_MARKER,
            reason="insert before",
            marker="MARKER",
            content="before",
        )
    )
    replaced = editor.apply(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.REPLACE_SNIPPET,
            reason="replace",
            old_snippet="value = 1",
            new_snippet="value = 2",
        )
    )

    assert inserted.ok is True
    assert inserted.changed is True
    assert replaced.ok is True
    assert replaced.changed is True
    assert target.read_text(encoding="utf-8") == "alpha\n\nbeforeMARKER\nvalue = 2\n"


def test_replace_snippet_requires_both_snippets_and_existing_match(
    tmp_path: Path,
) -> None:
    _write_source(
        tmp_path,
        "src/devagents/runtime/sample.py",
        "value = 1\n",
    )
    editor = StructuredCodeEditor(
        tmp_path,
        policy=CodeEditingPolicy(require_approval=False),
    )

    missing_new = editor.apply(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.REPLACE_SNIPPET,
            reason="invalid",
            old_snippet="value = 1",
        )
    )
    missing_old = editor.apply(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.REPLACE_SNIPPET,
            reason="invalid",
            new_snippet="value = 2",
        )
    )
    not_found = editor.apply(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.REPLACE_SNIPPET,
            reason="invalid",
            old_snippet="missing",
            new_snippet="value = 2",
        )
    )

    assert "requires old_snippet and new_snippet" in missing_new.message
    assert "requires old_snippet and new_snippet" in missing_old.message
    assert "Old snippet not found" in not_found.message


def test_ensure_snippet_requires_content_and_missing_marker_fails(
    tmp_path: Path,
) -> None:
    _write_source(
        tmp_path,
        "src/devagents/runtime/sample.py",
        "header\nbody\n",
    )
    editor = StructuredCodeEditor(
        tmp_path,
        policy=CodeEditingPolicy(require_approval=False),
    )

    missing_content = editor.apply(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.ENSURE_SNIPPET,
            reason="invalid",
        )
    )
    missing_marker = editor.apply(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.ENSURE_SNIPPET,
            reason="invalid",
            marker="MISSING",
            content="inserted = True",
        )
    )

    assert "ensure_snippet requires content" in missing_content.message
    assert "Marker not found" in missing_marker.message


def test_ensure_snippet_appends_without_extra_newline_when_disabled(
    tmp_path: Path,
) -> None:
    target = _write_source(
        tmp_path,
        "src/devagents/runtime/sample.py",
        "value = 1",
    )
    editor = StructuredCodeEditor(
        tmp_path,
        policy=CodeEditingPolicy(require_approval=False),
    )

    result = editor.apply(
        CodeEditRequest(
            relative_path="src/devagents/runtime/sample.py",
            kind=CodeEditKind.ENSURE_SNIPPET,
            reason="append",
            content="value = 2",
            ensure_trailing_newline=False,
        )
    )

    assert result.ok is True
    assert result.changed is True
    assert target.read_text(encoding="utf-8") == "value = 1\nvalue = 2"


def test_apply_many_returns_results_in_order(tmp_path: Path) -> None:
    target = _write_source(
        tmp_path,
        "src/devagents/runtime/sample.py",
        "first = 1\nsecond = 2\n",
    )
    editor = StructuredCodeEditor(
        tmp_path,
        policy=CodeEditingPolicy(require_approval=False),
    )

    results = editor.apply_many(
        [
            CodeEditRequest(
                relative_path="src/devagents/runtime/sample.py",
                kind=CodeEditKind.REPLACE_SNIPPET,
                reason="first",
                old_snippet="first = 1",
                new_snippet="first = 10",
            ),
            CodeEditRequest(
                relative_path="src/devagents/runtime/sample.py",
                kind=CodeEditKind.REPLACE_SNIPPET,
                reason="second",
                old_snippet="second = 2",
                new_snippet="second = 20",
            ),
        ]
    )

    assert [item.ok for item in results] == [True, True]
    assert target.read_text(encoding="utf-8") == "first = 10\nsecond = 20\n"


def test_validate_relative_path_normalizes_dot_prefix_and_backslashes(
    tmp_path: Path,
) -> None:
    target = _write_source(
        tmp_path,
        "src/devagents/runtime/sample.py",
        "value = 1\n",
    )
    editor = StructuredCodeEditor(
        tmp_path,
        policy=CodeEditingPolicy(require_approval=False),
    )

    result = editor.apply(
        CodeEditRequest(
            relative_path=r".\src\devagents\runtime\sample.py",
            kind=CodeEditKind.REPLACE_SNIPPET,
            reason="normalize",
            old_snippet="value = 1",
            new_snippet="value = 2",
        )
    )

    assert result.ok is True
    assert result.relative_path == "src/devagents/runtime/sample.py"
    assert target.read_text(encoding="utf-8") == "value = 2\n"


def test_absolute_paths_still_require_allowed_prefix_match(tmp_path: Path) -> None:
    target = _write_source(
        tmp_path,
        "src/devagents/runtime/sample.py",
        "value = 1\n",
    )
    editor = StructuredCodeEditor(
        tmp_path,
        policy=CodeEditingPolicy(
            require_approval=False,
            allow_absolute_paths=True,
        ),
    )

    result = editor.apply(
        CodeEditRequest(
            relative_path=target.as_posix(),
            kind=CodeEditKind.REPLACE_SNIPPET,
            reason="absolute allowed",
            old_snippet="value = 1",
            new_snippet="value = 2",
        )
    )

    assert result.ok is False
    assert "outside allowed prefixes" in result.message
    assert target.read_text(encoding="utf-8") == "value = 1\n"


def test_workflow_state_helpers_cover_finalize_summary_and_retries() -> None:
    state = create_workflow_state(
        workflow_id="wf-runtime-001",
        requirement="Exercise workflow helpers",
        model="gpt-5.4",
    )

    assert len(build_default_tasks()) == 8
    assert state.can_finalize() is False

    state.set_phase(WorkflowPhase.PLANNED)
    state.add_note("note-1")
    state.add_risk("risk-1")
    state.add_risk("risk-1")
    state.add_open_question("question-1")
    assert state.can_finalize() is False

    state.resolve_open_question("question-1")
    assert state.increment_retry("review") == 1
    assert state.increment_retry("review") == 2

    state.update_task_status(
        "requirements_analysis",
        TaskStatus.COMPLETED,
        outputs={"normalized": True},
    )
    state.update_task_status("planning", TaskStatus.COMPLETED)
    state.update_task_status("documentation", TaskStatus.COMPLETED)
    state.update_task_status("implementation", TaskStatus.COMPLETED)
    state.update_task_status("test_design", TaskStatus.COMPLETED)
    state.update_task_status("test_execution", TaskStatus.COMPLETED)
    state.update_task_status("review", TaskStatus.COMPLETED)
    state.update_task_status("finalization", TaskStatus.COMPLETED)

    summary = state.summary()
    as_dict = state.to_dict()

    assert state.can_finalize() is True
    assert summary["phase"] == "planned"
    assert summary["task_counts"]["completed"] == 8
    assert summary["task_counts"]["failed"] == 0
    assert summary["risks"] == ["risk-1"]
    assert as_dict["retry_counters"]["review"] == 2
    assert as_dict["tasks"][0]["outputs"]["normalized"] is True


def test_workflow_state_duplicate_and_missing_task_paths() -> None:
    state = create_workflow_state(
        workflow_id="wf-runtime-002",
        requirement="Exercise task errors",
        model="gpt-5.4",
    )

    with pytest.raises(ValueError, match="Task already exists"):
        state.add_task(
            WorkflowTask(
                task_id="planning",
                name="Duplicate Planning",
                objective="duplicate",
            )
        )

    with pytest.raises(KeyError, match="Unknown task"):
        state.require_task("missing-task")


def test_workflow_state_failed_and_blocked_tasks_prevent_finalization() -> None:
    state = create_workflow_state(
        workflow_id="wf-runtime-003",
        requirement="Exercise finalize guards",
        model="gpt-5.4",
    )

    for task_id in [
        "requirements_analysis",
        "planning",
        "documentation",
        "implementation",
        "test_design",
        "test_execution",
        "review",
        "finalization",
    ]:
        state.update_task_status(task_id, TaskStatus.COMPLETED)

    assert state.can_finalize() is True

    state.update_task_status("review", TaskStatus.FAILED, note="review failed")
    assert state.can_finalize() is False

    state.update_task_status("review", TaskStatus.COMPLETED)
    state.update_task_status("finalization", TaskStatus.BLOCKED, note="waiting")
    assert state.can_finalize() is False
