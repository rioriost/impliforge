"""Safe editing runtime for impliforge.

This module provides a minimal, file-system based editing layer that can be used
by the orchestrator before connecting to richer code-editing capabilities.

Design goals:
- keep writes explicit and auditable
- restrict edits to an allowlist
- support approval hooks for risky operations
- make dry-run behavior easy for orchestration and testing
- avoid hidden side effects

This runtime is intentionally conservative. It is suitable for:
- writing generated docs under `docs/`
- writing workflow artifacts under `artifacts/`
- preparing a future bridge to source-code editing with stronger controls
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Callable

DEFAULT_ALLOWED_ROOTS = ("docs", "artifacts")
DEFAULT_PROTECTED_ROOTS = (".git", ".venv")
DEFAULT_SRC_ALLOWED_PREFIXES = ("src/impliforge",)
SECRET_DETECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)\s*=\s*['\"][^'\"]+['\"]"
    ),
    re.compile(r"(?i)(password|passwd|pwd)\s*=\s*['\"][^'\"]+['\"]"),
    re.compile(r"(?i)-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
    re.compile(r"(?i)ghp_[A-Za-z0-9]{20,}"),
)


class EditOperationKind(StrEnum):
    """Supported edit operation kinds."""

    WRITE = "write"
    APPEND = "append"
    DELETE = "delete"
    ENSURE_DIRECTORY = "ensure_directory"


class ApprovalDecision(StrEnum):
    """Approval outcomes for a requested edit."""

    APPROVED = "approved"
    DENIED = "denied"


class EditRiskFlag(StrEnum):
    """Structured risk flags carried with edit requests."""

    DESTRUCTIVE = "destructive"
    BROAD_OVERWRITE = "broad_overwrite"
    DEPENDENCY_CHANGE = "dependency_change"
    ENVIRONMENT_CHANGE = "environment_change"
    SECURITY_IMPACT = "security_impact"
    SECRET_MATERIAL = "secret_material"
    UNSUPPORTED_CONSUMABILITY = "unsupported_consumability"
    POLICY_MISMATCH = "policy_mismatch"


@dataclass(slots=True)
class EditRequest:
    """A single requested file-system change."""

    relative_path: str
    operation: EditOperationKind = EditOperationKind.WRITE
    content: str | None = None
    reason: str = ""
    risk_flags: tuple[EditRiskFlag, ...] = ()
    proposal_id: str = ""
    approval_policy: str = ""
    consumability: str = ""
    create_parents: bool = True
    overwrite: bool = True

    def normalized_relative_path(self) -> str:
        return self.relative_path.strip().replace("\\", "/")


@dataclass(slots=True)
class ApprovalResult:
    """Result returned by an approval hook."""

    decision: ApprovalDecision
    reason: str = ""


@dataclass(slots=True)
class EditResult:
    """Structured result of an attempted edit."""

    ok: bool
    operation: EditOperationKind
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
        operation: EditOperationKind,
        relative_path: str,
        absolute_path: Path,
        changed: bool,
        dry_run: bool,
        message: str,
    ) -> EditResult:
        return cls(
            ok=True,
            operation=operation,
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
        operation: EditOperationKind,
        relative_path: str,
        absolute_path: Path,
        dry_run: bool,
        message: str,
    ) -> EditResult:
        return cls(
            ok=False,
            operation=operation,
            relative_path=relative_path,
            absolute_path=absolute_path.as_posix(),
            changed=False,
            dry_run=dry_run,
            message=message,
        )


ApprovalHook = Callable[[EditRequest, Path], ApprovalResult]


@dataclass(slots=True)
class EditorPolicy:
    """Policy controlling what the editor may touch."""

    allowed_roots: tuple[str, ...] = DEFAULT_ALLOWED_ROOTS
    protected_roots: tuple[str, ...] = DEFAULT_PROTECTED_ROOTS
    src_allowed_prefixes: tuple[str, ...] = DEFAULT_SRC_ALLOWED_PREFIXES
    require_approval_for_delete: bool = True
    require_approval_for_overwrite_outside_docs: bool = True
    require_approval_for_src_edits: bool = True
    allow_absolute_paths: bool = False

    def is_allowed_root(self, relative_path: str) -> bool:
        parts = self._parts(relative_path)
        if not parts:
            return False

        root = parts[0]
        if root in self.allowed_roots:
            return True

        if root == "src":
            return any(
                relative_path == prefix or relative_path.startswith(f"{prefix}/")
                for prefix in self.src_allowed_prefixes
            )

        return False

    def is_protected_root(self, relative_path: str) -> bool:
        parts = self._parts(relative_path)
        if not parts:
            return False

        root = parts[0]
        if root in self.protected_roots:
            return True

        if root == "src":
            return not any(
                relative_path == prefix or relative_path.startswith(f"{prefix}/")
                for prefix in self.src_allowed_prefixes
            )

        return False

    def requires_src_approval(self, relative_path: str) -> bool:
        return relative_path == "src" or relative_path.startswith("src/")

    def approval_policy_allows(self, approval_policy: str, relative_path: str) -> bool:
        if not approval_policy:
            return True

        if approval_policy == "docs_artifacts_only":
            return relative_path.startswith("docs/") or relative_path.startswith(
                "artifacts/"
            )

        if approval_policy == "src_impliforge_structured_only":
            return relative_path == "src/impliforge" or relative_path.startswith(
                "src/impliforge/"
            )

        return False

    def supports_consumability(self, consumability: str, relative_path: str) -> bool:
        if not consumability:
            return True

        if consumability == "safe_editor":
            return self.is_allowed_root(relative_path)

        if consumability == "structured_code_editor":
            return relative_path == "src/impliforge" or relative_path.startswith(
                "src/impliforge/"
            )

        return False

    def _parts(self, relative_path: str) -> tuple[str, ...]:
        return tuple(part for part in relative_path.split("/") if part)


class EditorError(RuntimeError):
    """Raised when an edit request is invalid or unsafe."""


class SafeEditor:
    """Safe file editing runtime with allowlist and approval support."""

    def __init__(
        self,
        workspace_root: str | Path = ".",
        *,
        policy: EditorPolicy | None = None,
        approval_hook: ApprovalHook | None = None,
        dry_run: bool = False,
        allowed_roots: list[str | Path] | None = None,
        src_allowed_prefixes: list[str | Path] | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        resolved_policy = policy or EditorPolicy()
        if allowed_roots is not None or src_allowed_prefixes is not None:
            resolved_policy = EditorPolicy(
                allowed_roots=(
                    tuple(
                        Path(root).as_posix().strip("/").split("/")[0]
                        for root in allowed_roots
                    )
                    if allowed_roots is not None
                    else resolved_policy.allowed_roots
                ),
                protected_roots=resolved_policy.protected_roots,
                src_allowed_prefixes=(
                    tuple(
                        Path(prefix).as_posix().strip("/")
                        for prefix in src_allowed_prefixes
                    )
                    if src_allowed_prefixes is not None
                    else resolved_policy.src_allowed_prefixes
                ),
                require_approval_for_delete=resolved_policy.require_approval_for_delete,
                require_approval_for_overwrite_outside_docs=resolved_policy.require_approval_for_overwrite_outside_docs,
                require_approval_for_src_edits=resolved_policy.require_approval_for_src_edits,
                allow_absolute_paths=resolved_policy.allow_absolute_paths,
            )
        self.policy = resolved_policy
        self.approval_hook = approval_hook
        self.dry_run = dry_run

    def apply(self, request: EditRequest) -> EditResult:
        # BEGIN STRUCTURED EDIT: SafeEditor.apply
        """Apply a single edit request."""
        relative_path = self._validate_relative_path(request.normalized_relative_path())
        absolute_path = self._resolve_path(relative_path)

        policy_error = self._check_policy(request, relative_path)
        if policy_error is not None:
            return EditResult.failure(
                operation=request.operation,
                relative_path=relative_path,
                absolute_path=absolute_path,
                dry_run=self.dry_run,
                message=policy_error,
            )

        approval_error = self._check_approval(request, absolute_path, relative_path)
        if approval_error is not None:
            return EditResult.failure(
                operation=request.operation,
                relative_path=relative_path,
                absolute_path=absolute_path,
                dry_run=self.dry_run,
                message=approval_error,
            )

        if request.operation == EditOperationKind.ENSURE_DIRECTORY:
            return self._ensure_directory(relative_path, absolute_path)

        if request.operation == EditOperationKind.DELETE:
            return self._delete(relative_path, absolute_path)

        if request.operation == EditOperationKind.WRITE:
            return self._write(relative_path, absolute_path, request)

        if request.operation == EditOperationKind.APPEND:
            return self._append(relative_path, absolute_path, request)

        return EditResult.failure(
            operation=request.operation,
            relative_path=relative_path,
            absolute_path=absolute_path,
            dry_run=self.dry_run,
            message=f"Unsupported operation: {request.operation.value}",
        )  # END STRUCTURED EDIT: SafeEditor.apply

    def apply_many(self, requests: list[EditRequest]) -> list[EditResult]:
        """Apply multiple edit requests in order."""
        return [self.apply(request) for request in requests]

    def apply_operations(self, requests: list[EditRequest]) -> list[str]:
        """Apply multiple edit requests and return changed relative paths."""
        results = self.apply_many(requests)
        return [
            result.relative_path for result in results if result.ok and result.changed
        ]

    def preview(self, request: EditRequest) -> EditResult:
        """Preview a request without mutating the file system."""
        preview_editor = SafeEditor(
            self.workspace_root,
            policy=self.policy,
            approval_hook=self.approval_hook,
            dry_run=True,
        )
        return preview_editor.apply(request)

    def _write(
        self,
        relative_path: str,
        absolute_path: Path,
        request: EditRequest,
    ) -> EditResult:
        if request.content is None:
            return EditResult.failure(
                operation=request.operation,
                relative_path=relative_path,
                absolute_path=absolute_path,
                dry_run=self.dry_run,
                message="Write operation requires content.",
            )

        existing = (
            absolute_path.read_text(encoding="utf-8")
            if absolute_path.exists()
            else None
        )
        if existing is not None and not request.overwrite:
            return EditResult.failure(
                operation=request.operation,
                relative_path=relative_path,
                absolute_path=absolute_path,
                dry_run=self.dry_run,
                message="Target exists and overwrite is disabled.",
            )

        changed = existing != request.content
        if self.dry_run:
            return EditResult.success(
                operation=request.operation,
                relative_path=relative_path,
                absolute_path=absolute_path,
                changed=changed,
                dry_run=True,
                message="Dry-run write accepted.",
            )

        if request.create_parents:
            absolute_path.parent.mkdir(parents=True, exist_ok=True)
        absolute_path.write_text(request.content, encoding="utf-8")
        return EditResult.success(
            operation=request.operation,
            relative_path=relative_path,
            absolute_path=absolute_path,
            changed=changed,
            dry_run=False,
            message="File written.",
        )

    def _append(
        self,
        relative_path: str,
        absolute_path: Path,
        request: EditRequest,
    ) -> EditResult:
        if request.content is None:
            return EditResult.failure(
                operation=request.operation,
                relative_path=relative_path,
                absolute_path=absolute_path,
                dry_run=self.dry_run,
                message="Append operation requires content.",
            )

        existing = (
            absolute_path.read_text(encoding="utf-8") if absolute_path.exists() else ""
        )
        new_content = existing + request.content
        changed = request.content != ""

        if self.dry_run:
            return EditResult.success(
                operation=request.operation,
                relative_path=relative_path,
                absolute_path=absolute_path,
                changed=changed,
                dry_run=True,
                message="Dry-run append accepted.",
            )

        if request.create_parents:
            absolute_path.parent.mkdir(parents=True, exist_ok=True)
        absolute_path.write_text(new_content, encoding="utf-8")
        return EditResult.success(
            operation=request.operation,
            relative_path=relative_path,
            absolute_path=absolute_path,
            changed=changed,
            dry_run=False,
            message="Content appended.",
        )

    def _delete(self, relative_path: str, absolute_path: Path) -> EditResult:
        if not absolute_path.exists():
            return EditResult.success(
                operation=EditOperationKind.DELETE,
                relative_path=relative_path,
                absolute_path=absolute_path,
                changed=False,
                dry_run=self.dry_run,
                message="Target does not exist; nothing to delete.",
            )

        if absolute_path.is_dir():
            return EditResult.failure(
                operation=EditOperationKind.DELETE,
                relative_path=relative_path,
                absolute_path=absolute_path,
                dry_run=self.dry_run,
                message="Directory deletion is not supported by this runtime.",
            )

        if self.dry_run:
            return EditResult.success(
                operation=EditOperationKind.DELETE,
                relative_path=relative_path,
                absolute_path=absolute_path,
                changed=True,
                dry_run=True,
                message="Dry-run delete accepted.",
            )

        absolute_path.unlink()
        return EditResult.success(
            operation=EditOperationKind.DELETE,
            relative_path=relative_path,
            absolute_path=absolute_path,
            changed=True,
            dry_run=False,
            message="File deleted.",
        )

    def _ensure_directory(self, relative_path: str, absolute_path: Path) -> EditResult:
        changed = not absolute_path.exists()
        if self.dry_run:
            return EditResult.success(
                operation=EditOperationKind.ENSURE_DIRECTORY,
                relative_path=relative_path,
                absolute_path=absolute_path,
                changed=changed,
                dry_run=True,
                message="Dry-run ensure_directory accepted.",
            )

        absolute_path.mkdir(parents=True, exist_ok=True)
        return EditResult.success(
            operation=EditOperationKind.ENSURE_DIRECTORY,
            relative_path=relative_path,
            absolute_path=absolute_path,
            changed=changed,
            dry_run=False,
            message="Directory ensured.",
        )

    def _check_policy(self, request: EditRequest, relative_path: str) -> str | None:
        if not self.policy.is_allowed_root(relative_path):
            return (
                "Edit denied: target is outside allowed roots "
                f"{', '.join(self.policy.allowed_roots)}."
            )

        if self.policy.is_protected_root(relative_path):
            return (
                "Edit denied: target is under a protected root "
                f"{', '.join(self.policy.protected_roots)}."
            )

        if not self.policy.approval_policy_allows(
            request.approval_policy, relative_path
        ):
            return (
                "Edit denied: proposal approval policy does not allow target "
                f"{relative_path}."
            )

        if not self.policy.supports_consumability(request.consumability, relative_path):
            return (
                "Edit denied: proposal consumability is not supported for target "
                f"{relative_path}."
            )

        return None

    def _check_approval(
        self,
        request: EditRequest,
        absolute_path: Path,
        relative_path: str,
    ) -> str | None:
        needs_approval = False

        if (
            request.operation == EditOperationKind.DELETE
            and self.policy.require_approval_for_delete
        ):
            needs_approval = True

        if (
            request.operation == EditOperationKind.WRITE
            and absolute_path.exists()
            and self.policy.require_approval_for_overwrite_outside_docs
            and not relative_path.startswith("docs/")
        ):
            needs_approval = True

        if (
            self.policy.require_approval_for_src_edits
            and self.policy.requires_src_approval(relative_path)
        ):
            needs_approval = True

        if not needs_approval:
            return None

        if self.approval_hook is None:
            return "Edit denied: approval required but no approval hook is configured."

        result = self.approval_hook(request, absolute_path)
        if result.decision != ApprovalDecision.APPROVED:
            reason = result.reason or "approval hook denied the request"
            return f"Edit denied: {reason}."
        return None

    def _validate_relative_path(self, relative_path: str) -> str:
        if not relative_path:
            raise EditorError("relative_path must not be empty")

        path = Path(relative_path)

        if path.is_absolute() and not self.policy.allow_absolute_paths:
            raise EditorError("absolute paths are not allowed")

        normalized = path.as_posix()

        if normalized.startswith("../") or "/../" in normalized or normalized == "..":
            raise EditorError("path traversal is not allowed")

        if normalized.startswith("./"):
            normalized = normalized[2:]

        return normalized

    def _resolve_path(self, relative_path: str) -> Path:
        absolute_path = (self.workspace_root / relative_path).resolve()
        try:
            absolute_path.relative_to(self.workspace_root)
        except ValueError as exc:
            raise EditorError("resolved path escapes workspace root") from exc
        return absolute_path


def _find_secret_like_content(request: EditRequest) -> str | None:
    candidates = [request.content]
    for candidate in candidates:
        if not candidate:
            continue
        for pattern in SECRET_DETECTION_PATTERNS:
            if pattern.search(candidate):
                return (
                    "secret-like content detected; explicit human approval is required"
                )
    return None


def has_edit_risk_flag(request: EditRequest, *flags: EditRiskFlag) -> bool:
    """Return whether the request carries any of the given structured risk flags."""
    request_flags = set(request.risk_flags)
    return any(flag in request_flags for flag in flags)


def proposal_policy_requires_explicit_approval(approval_policy: str) -> bool:
    """Return whether a proposal policy should require explicit approval."""
    return approval_policy in {
        "docs_artifacts_only",
        "src_impliforge_structured_only",
    }


def proposal_consumability_is_structured(consumability: str) -> bool:
    """Return whether a proposal consumability expects structured editing."""
    return consumability == "structured_code_editor"


def approve_docs_and_artifacts_only(
    request: EditRequest, absolute_path: Path
) -> ApprovalResult:
    """Default conservative approval hook.

    Approves only:
    - writes/appends under `docs/`
    - writes/appends under `artifacts/`
    Denies deletes and anything else.
    """
    relative_path = request.normalized_relative_path()

    if request.operation == EditOperationKind.DELETE:
        return ApprovalResult(
            decision=ApprovalDecision.DENIED,
            reason="delete operations require explicit custom approval",
        )

    if relative_path.startswith("docs/") or relative_path.startswith("artifacts/"):
        secret_detection_reason = _find_secret_like_content(request)
        if secret_detection_reason is not None or has_edit_risk_flag(
            request, EditRiskFlag.SECRET_MATERIAL
        ):
            return ApprovalResult(
                decision=ApprovalDecision.DENIED,
                reason=(
                    secret_detection_reason
                    or "secret-like content detected; explicit human approval is required"
                ),
            )
        return ApprovalResult(
            decision=ApprovalDecision.APPROVED,
            reason="allowed by conservative docs/artifacts policy",
        )

    return ApprovalResult(
        decision=ApprovalDecision.DENIED,
        reason="target is outside conservative approval scope",
    )


def approve_docs_artifacts_and_src_impliforge(
    request: EditRequest, absolute_path: Path
) -> ApprovalResult:
    """Approval hook that also allows limited edits under `src/impliforge/`.

    Rules:
    - deny deletes by default
    - allow writes/appends under `docs/` and `artifacts/`
    - allow writes/appends under `src/impliforge/`
    - deny everything else
    """
    relative_path = request.normalized_relative_path()

    if request.operation == EditOperationKind.DELETE:
        return ApprovalResult(
            decision=ApprovalDecision.DENIED,
            reason="delete operations require explicit custom approval",
        )

    if relative_path.startswith("docs/") or relative_path.startswith("artifacts/"):
        secret_detection_reason = _find_secret_like_content(request)
        if secret_detection_reason is not None:
            return ApprovalResult(
                decision=ApprovalDecision.DENIED,
                reason=secret_detection_reason,
            )
        return ApprovalResult(
            decision=ApprovalDecision.APPROVED,
            reason="allowed by docs/artifacts policy",
        )

    if relative_path == "src/impliforge" or relative_path.startswith("src/impliforge/"):
        secret_detection_reason = _find_secret_like_content(request)
        if secret_detection_reason is not None or has_edit_risk_flag(
            request, EditRiskFlag.SECRET_MATERIAL
        ):
            return ApprovalResult(
                decision=ApprovalDecision.DENIED,
                reason=(
                    secret_detection_reason
                    or "secret-like content detected; explicit human approval is required"
                ),
            )
        return ApprovalResult(
            decision=ApprovalDecision.APPROVED,
            reason="allowed by src/impliforge scoped approval policy",
        )

    return ApprovalResult(
        decision=ApprovalDecision.DENIED,
        reason="target is outside approved src/impliforge/docs/artifacts scope",
    )


# SAFE-EDIT-NOTE
# Proposed implementation slice: Promote approved implementation proposals into allowlisted source edits under src/impliforge/.

# SAFE-EDIT-FIX-NOTE
# Proposed fix slice: 未解決の open questions が残っているため、実装前に確認が必要。

# SAFE-EDIT-FIX-NOTE
# Proposed fix slice: テスト結果が `needs_review` のため、追加確認または修正が必要。
