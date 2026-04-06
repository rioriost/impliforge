"""Structured code editing runtime for impliforge.

This module provides a conservative, template-based editing layer for approved
source files under `src/impliforge/`. It is intended to replace the earlier
"append a note" path with a safer mechanism that performs explicit,
structure-aware updates.

Design goals:
- only operate on allowlisted source files
- avoid arbitrary free-form rewriting
- support small, auditable edit intents
- preserve resumability by returning structured edit results
- make dry-run and approval behavior explicit

This runtime is intentionally narrow. It currently supports:
- replacing a marked block delimited by begin/end markers
- inserting content after a marker
- inserting content before a marker
- replacing an exact snippet once
- ensuring a snippet exists once

It does not attempt AST parsing. Instead, it relies on stable markers and
bounded string operations so behavior remains predictable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Callable

DEFAULT_ALLOWED_PREFIXES = ("src/impliforge",)
DEFAULT_PROTECTED_PREFIXES = (".git", ".venv")
DEFAULT_ALLOWED_EXTENSIONS = (".py",)
SECRET_DETECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)\s*=\s*['\"][^'\"]+['\"]"
    ),
    re.compile(r"(?i)(password|passwd|pwd)\s*=\s*['\"][^'\"]+['\"]"),
    re.compile(r"(?i)-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
    re.compile(r"(?i)ghp_[A-Za-z0-9]{20,}"),
)


class CodeEditKind(StrEnum):
    """Supported structured code edit kinds."""

    REPLACE_MARKED_BLOCK = "replace_marked_block"
    INSERT_AFTER_MARKER = "insert_after_marker"
    INSERT_BEFORE_MARKER = "insert_before_marker"
    REPLACE_SNIPPET = "replace_snippet"
    ENSURE_SNIPPET = "ensure_snippet"


class CodeApprovalDecision(StrEnum):
    """Approval outcomes for a code edit request."""

    APPROVED = "approved"
    DENIED = "denied"


class CodeEditRiskFlag(StrEnum):
    """Structured risk flags carried with code edit requests."""

    DESTRUCTIVE = "destructive"
    BROAD_REWRITE = "broad_rewrite"
    DEPENDENCY_CHANGE = "dependency_change"
    ENVIRONMENT_CHANGE = "environment_change"
    SECURITY_IMPACT = "security_impact"
    SECRET_MATERIAL = "secret_material"


@dataclass(slots=True)
class CodeEditRequest:
    """A single structured code edit request."""

    relative_path: str
    kind: CodeEditKind
    reason: str
    risk_flags: tuple[CodeEditRiskFlag, ...] = ()
    content: str | None = None
    marker: str | None = None
    begin_marker: str | None = None
    end_marker: str | None = None
    old_snippet: str | None = None
    new_snippet: str | None = None
    ensure_trailing_newline: bool = True

    def normalized_relative_path(self) -> str:
        return self.relative_path.strip().replace("\\", "/")


@dataclass(slots=True)
class CodeApprovalResult:
    """Result returned by a code edit approval hook."""

    decision: CodeApprovalDecision
    reason: str = ""


@dataclass(slots=True)
class CodeEditResult:
    """Structured result of an attempted code edit."""

    ok: bool
    kind: CodeEditKind
    relative_path: str
    absolute_path: str
    changed: bool
    dry_run: bool
    message: str
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def success(
        cls,
        *,
        kind: CodeEditKind,
        relative_path: str,
        absolute_path: Path,
        changed: bool,
        dry_run: bool,
        message: str,
    ) -> CodeEditResult:
        return cls(
            ok=True,
            kind=kind,
            relative_path=relative_path,
            absolute_path=absolute_path.as_posix(),
            changed=changed,
            dry_run=dry_run,
            message=message,
        )

    @classmethod
    def failure(
        cls,
        *,
        kind: CodeEditKind,
        relative_path: str,
        absolute_path: Path,
        dry_run: bool,
        message: str,
    ) -> CodeEditResult:
        return cls(
            ok=False,
            kind=kind,
            relative_path=relative_path,
            absolute_path=absolute_path.as_posix(),
            changed=False,
            dry_run=dry_run,
            message=message,
        )


CodeApprovalHook = Callable[[CodeEditRequest, Path], CodeApprovalResult]


@dataclass(slots=True)
class CodeEditingPolicy:
    """Policy controlling what source files may be edited."""

    allowed_prefixes: tuple[str, ...] = DEFAULT_ALLOWED_PREFIXES
    protected_prefixes: tuple[str, ...] = DEFAULT_PROTECTED_PREFIXES
    allowed_extensions: tuple[str, ...] = DEFAULT_ALLOWED_EXTENSIONS
    require_approval: bool = True
    allow_create: bool = False
    allow_delete: bool = False
    allow_absolute_paths: bool = False

    def is_allowed_path(self, relative_path: str) -> bool:
        if not any(
            relative_path == prefix or relative_path.startswith(f"{prefix}/")
            for prefix in self.allowed_prefixes
        ):
            return False

        if any(
            relative_path == prefix or relative_path.startswith(f"{prefix}/")
            for prefix in self.protected_prefixes
        ):
            return False

        suffix = Path(relative_path).suffix
        return suffix in self.allowed_extensions

    def is_protected_path(self, relative_path: str) -> bool:
        return any(
            relative_path == prefix or relative_path.startswith(f"{prefix}/")
            for prefix in self.protected_prefixes
        )


class CodeEditingError(RuntimeError):
    """Raised when a code edit request is invalid or unsafe."""


class StructuredCodeEditor:
    """Structured, allowlisted code editor for approved source files."""

    def __init__(
        self,
        workspace_root: str | Path = ".",
        *,
        policy: CodeEditingPolicy | None = None,
        approval_hook: CodeApprovalHook | None = None,
        dry_run: bool = False,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.policy = policy or CodeEditingPolicy()
        self.approval_hook = approval_hook
        self.dry_run = dry_run

    def apply(self, request: CodeEditRequest) -> CodeEditResult:
        """Apply a single structured code edit request."""
        relative_path = self._validate_relative_path(request.normalized_relative_path())
        absolute_path = self._resolve_path(relative_path)

        policy_error = self._check_policy(relative_path, absolute_path)
        if policy_error is not None:
            return CodeEditResult.failure(
                kind=request.kind,
                relative_path=relative_path,
                absolute_path=absolute_path,
                dry_run=self.dry_run,
                message=policy_error,
            )

        approval_error = self._check_approval(request, absolute_path)
        if approval_error is not None:
            return CodeEditResult.failure(
                kind=request.kind,
                relative_path=relative_path,
                absolute_path=absolute_path,
                dry_run=self.dry_run,
                message=approval_error,
            )

        if not absolute_path.exists():
            return CodeEditResult.failure(
                kind=request.kind,
                relative_path=relative_path,
                absolute_path=absolute_path,
                dry_run=self.dry_run,
                message="Target file does not exist.",
            )

        original = absolute_path.read_text(encoding="utf-8")
        try:
            updated = self._apply_to_text(original, request)
        except CodeEditingError as exc:
            return CodeEditResult.failure(
                kind=request.kind,
                relative_path=relative_path,
                absolute_path=absolute_path,
                dry_run=self.dry_run,
                message=str(exc),
            )

        if request.ensure_trailing_newline and updated and not updated.endswith("\n"):
            updated += "\n"

        changed = updated != original
        if self.dry_run:
            return CodeEditResult.success(
                kind=request.kind,
                relative_path=relative_path,
                absolute_path=absolute_path,
                changed=changed,
                dry_run=True,
                message="Dry-run structured code edit accepted.",
            )

        if changed:
            absolute_path.write_text(updated, encoding="utf-8")

        return CodeEditResult.success(
            kind=request.kind,
            relative_path=relative_path,
            absolute_path=absolute_path,
            changed=changed,
            dry_run=False,
            message="Structured code edit applied.",
        )

    def apply_many(self, requests: list[CodeEditRequest]) -> list[CodeEditResult]:
        """Apply multiple structured code edit requests in order."""
        return [self.apply(request) for request in requests]

    def preview(self, request: CodeEditRequest) -> CodeEditResult:
        """Preview a structured code edit without mutating the file system."""
        preview_editor = StructuredCodeEditor(
            self.workspace_root,
            policy=self.policy,
            approval_hook=self.approval_hook,
            dry_run=True,
        )
        return preview_editor.apply(request)

    def _apply_to_text(self, original: str, request: CodeEditRequest) -> str:
        if request.kind == CodeEditKind.REPLACE_MARKED_BLOCK:
            return self._replace_marked_block(original, request)

        if request.kind == CodeEditKind.INSERT_AFTER_MARKER:
            return self._insert_after_marker(original, request)

        if request.kind == CodeEditKind.INSERT_BEFORE_MARKER:
            return self._insert_before_marker(original, request)

        if request.kind == CodeEditKind.REPLACE_SNIPPET:
            return self._replace_snippet(original, request)

        if request.kind == CodeEditKind.ENSURE_SNIPPET:
            return self._ensure_snippet(original, request)

        raise CodeEditingError(f"Unsupported code edit kind: {request.kind.value}")

    def _replace_marked_block(self, original: str, request: CodeEditRequest) -> str:
        begin_marker = request.begin_marker
        end_marker = request.end_marker
        content = request.content

        if not begin_marker or not end_marker:
            raise CodeEditingError(
                "replace_marked_block requires begin_marker and end_marker."
            )
        if content is None:
            raise CodeEditingError("replace_marked_block requires content.")

        begin_index = original.find(begin_marker)
        if begin_index < 0:
            raise CodeEditingError(f"Begin marker not found: {begin_marker!r}")

        end_index = original.find(end_marker, begin_index + len(begin_marker))
        if end_index < 0:
            raise CodeEditingError(f"End marker not found: {end_marker!r}")

        block_start = begin_index + len(begin_marker)
        replacement = self._normalize_inserted_content(content)
        return original[:block_start] + replacement + original[end_index:]

    def _insert_after_marker(self, original: str, request: CodeEditRequest) -> str:
        marker = request.marker
        content = request.content

        if not marker:
            raise CodeEditingError("insert_after_marker requires marker.")
        if content is None:
            raise CodeEditingError("insert_after_marker requires content.")

        marker_index = original.find(marker)
        if marker_index < 0:
            raise CodeEditingError(f"Marker not found: {marker!r}")

        insert_at = marker_index + len(marker)
        insertion = self._normalize_inserted_content(content)
        return original[:insert_at] + insertion + original[insert_at:]

    def _insert_before_marker(self, original: str, request: CodeEditRequest) -> str:
        marker = request.marker
        content = request.content

        if not marker:
            raise CodeEditingError("insert_before_marker requires marker.")
        if content is None:
            raise CodeEditingError("insert_before_marker requires content.")

        marker_index = original.find(marker)
        if marker_index < 0:
            raise CodeEditingError(f"Marker not found: {marker!r}")

        insertion = self._normalize_inserted_content(content)
        return original[:marker_index] + insertion + original[marker_index:]

    def _replace_snippet(self, original: str, request: CodeEditRequest) -> str:
        old_snippet = request.old_snippet
        new_snippet = request.new_snippet

        if old_snippet is None or new_snippet is None:
            raise CodeEditingError(
                "replace_snippet requires old_snippet and new_snippet."
            )

        occurrences = original.count(old_snippet)
        if occurrences == 0:
            raise CodeEditingError("Old snippet not found.")
        if occurrences > 1:
            raise CodeEditingError(
                "Old snippet matched multiple locations; refusing ambiguous replacement."
            )

        return original.replace(old_snippet, new_snippet, 1)

    def _ensure_snippet(self, original: str, request: CodeEditRequest) -> str:
        content = request.content
        marker = request.marker

        if content is None:
            raise CodeEditingError("ensure_snippet requires content.")

        if content in original:
            return original

        insertion = self._normalize_inserted_content(content)
        if marker:
            marker_index = original.find(marker)
            if marker_index < 0:
                raise CodeEditingError(f"Marker not found: {marker!r}")
            insert_at = marker_index + len(marker)
            return original[:insert_at] + insertion + original[insert_at:]

        if original and not original.endswith("\n"):
            return original + "\n" + content
        return original + content

    def _normalize_inserted_content(self, content: str) -> str:
        if not content:
            return ""
        if content.startswith("\n"):
            return content
        return "\n" + content

    def _check_policy(self, relative_path: str, absolute_path: Path) -> str | None:
        if not self.policy.is_allowed_path(relative_path):
            return (
                "Structured code edit denied: target is outside allowed prefixes "
                f"{', '.join(self.policy.allowed_prefixes)}."
            )

        if self.policy.is_protected_path(relative_path):
            return "Structured code edit denied: target is under a protected prefix."

        if not absolute_path.exists() and not self.policy.allow_create:
            return "Structured code edit denied: creating new source files is disabled."

        return None

    def _check_approval(
        self,
        request: CodeEditRequest,
        absolute_path: Path,
    ) -> str | None:
        if not self.policy.require_approval:
            return None

        if self.approval_hook is None:
            return "Structured code edit denied: approval required but no approval hook is configured."

        result = self.approval_hook(request, absolute_path)
        if result.decision != CodeApprovalDecision.APPROVED:
            reason = result.reason or "approval hook denied the request"
            return f"Structured code edit denied: {reason}."
        return None

    def _validate_relative_path(self, relative_path: str) -> str:
        if not relative_path:
            raise CodeEditingError("relative_path must not be empty")

        path = Path(relative_path)

        if path.is_absolute() and not self.policy.allow_absolute_paths:
            raise CodeEditingError("absolute paths are not allowed")

        normalized = path.as_posix()

        if normalized.startswith("../") or "/../" in normalized or normalized == "..":
            raise CodeEditingError("path traversal is not allowed")

        if normalized.startswith("./"):
            normalized = normalized[2:]

        return normalized

    def _resolve_path(self, relative_path: str) -> Path:
        absolute_path = (self.workspace_root / relative_path).resolve()
        try:
            absolute_path.relative_to(self.workspace_root)
        except ValueError as exc:
            raise CodeEditingError("resolved path escapes workspace root") from exc
        return absolute_path


def _find_secret_like_content(request: CodeEditRequest) -> str | None:
    candidates = [
        request.content,
        request.new_snippet,
    ]
    for candidate in candidates:
        if not candidate:
            continue
        for pattern in SECRET_DETECTION_PATTERNS:
            if pattern.search(candidate):
                return (
                    "secret-like content detected; explicit human approval is required"
                )
    return None


def has_code_edit_risk_flag(request: CodeEditRequest, *flags: CodeEditRiskFlag) -> bool:
    """Return whether the request carries any of the given structured risk flags."""
    request_flags = set(request.risk_flags)
    return any(flag in request_flags for flag in flags)


def approve_src_impliforge_only(
    request: CodeEditRequest,
    absolute_path: Path,
) -> CodeApprovalResult:
    """Conservative approval hook for `src/impliforge/` edits.

    Rules:
    - allow only files under `src/impliforge/`
    - deny edits outside `.py` files
    - deny edits that appear to introduce secrets or credentials
    - deny requests that look like broad free-form rewrites
    - allow only the supported structured edit kinds
    """
    relative_path = request.normalized_relative_path()

    if not (
        relative_path == "src/impliforge" or relative_path.startswith("src/impliforge/")
    ):
        return CodeApprovalResult(
            decision=CodeApprovalDecision.DENIED,
            reason="target is outside src/impliforge approval scope",
        )

    if Path(relative_path).suffix not in DEFAULT_ALLOWED_EXTENSIONS:
        return CodeApprovalResult(
            decision=CodeApprovalDecision.DENIED,
            reason="only Python source files are approved",
        )

    if request.kind not in {
        CodeEditKind.REPLACE_MARKED_BLOCK,
        CodeEditKind.INSERT_AFTER_MARKER,
        CodeEditKind.INSERT_BEFORE_MARKER,
        CodeEditKind.REPLACE_SNIPPET,
        CodeEditKind.ENSURE_SNIPPET,
    }:
        return CodeApprovalResult(
            decision=CodeApprovalDecision.DENIED,
            reason="unsupported structured edit kind",
        )

    secret_detection_reason = _find_secret_like_content(request)
    if secret_detection_reason is not None or has_code_edit_risk_flag(
        request, CodeEditRiskFlag.SECRET_MATERIAL
    ):
        return CodeApprovalResult(
            decision=CodeApprovalDecision.DENIED,
            reason=(
                secret_detection_reason
                or "secret-like content detected; explicit human approval is required"
            ),
        )

    if has_code_edit_risk_flag(
        request,
        CodeEditRiskFlag.DESTRUCTIVE,
        CodeEditRiskFlag.DEPENDENCY_CHANGE,
        CodeEditRiskFlag.ENVIRONMENT_CHANGE,
        CodeEditRiskFlag.SECURITY_IMPACT,
        CodeEditRiskFlag.BROAD_REWRITE,
    ):
        return CodeApprovalResult(
            decision=CodeApprovalDecision.DENIED,
            reason="structured risk flags require explicit human approval",
        )

    if request.kind == CodeEditKind.REPLACE_MARKED_BLOCK:
        content = request.content or ""
        if len(content) > 4000 or content.count("\n") > 120:
            return CodeApprovalResult(
                decision=CodeApprovalDecision.DENIED,
                reason="broad marked-block rewrites require explicit human approval",
            )

    return CodeApprovalResult(
        decision=CodeApprovalDecision.APPROVED,
        reason="approved by src/impliforge structured editing policy",
    )
