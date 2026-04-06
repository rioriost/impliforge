"""Persistent state storage for devagents workflow artifacts and snapshots."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from devagents.orchestration.workflow import SessionSnapshot, WorkflowState


class StateStore:
    """File-backed store for workflow state, session snapshots, and summaries."""

    def __init__(self, root_dir: str | Path = "artifacts") -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def ensure_layout(self) -> None:
        """Create the expected storage layout if it does not exist."""
        self.workflow_dir.mkdir(parents=True, exist_ok=True)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.summary_dir.mkdir(parents=True, exist_ok=True)

    @property
    def workflow_dir(self) -> Path:
        return self.root_dir / "workflows"

    @property
    def session_dir(self) -> Path:
        return self.root_dir / "sessions"

    @property
    def summary_dir(self) -> Path:
        return self.root_dir / "summaries"

    def save_workflow_state(
        self,
        state: WorkflowState,
        *,
        file_name: str = "workflow-state.json",
    ) -> Path:
        """Persist a workflow state under its workflow-specific directory."""
        self.ensure_layout()
        target_dir = self.workflow_dir / state.workflow_id
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / file_name
        payload = {
            "saved_at": self._timestamp(),
            "workflow": state.to_dict(),
            "summary": state.summary(),
        }
        self._write_json(path, payload)
        return path

    def load_workflow_state(
        self,
        workflow_id: str,
        *,
        file_name: str = "workflow-state.json",
    ) -> dict[str, Any]:
        """Load a previously persisted workflow state payload."""
        path = self.workflow_dir / workflow_id / file_name
        return self._read_json(path)

    def save_session_snapshot(
        self,
        snapshot: SessionSnapshot,
        *,
        file_name: str | None = None,
    ) -> Path:
        """Persist a session snapshot for resumability."""
        self.ensure_layout()
        target_dir = self.session_dir / snapshot.session_id
        target_dir.mkdir(parents=True, exist_ok=True)
        resolved_name = file_name or "session-snapshot.json"
        path = target_dir / resolved_name
        payload = {
            "saved_at": self._timestamp(),
            "snapshot": self._to_dict(snapshot),
        }
        self._write_json(path, payload)
        return path

    def load_session_snapshot(
        self,
        session_id: str,
        *,
        file_name: str = "session-snapshot.json",
    ) -> dict[str, Any]:
        """Load a previously persisted session snapshot payload."""
        path = self.session_dir / session_id / file_name
        return self._read_json(path)

    def save_run_summary(
        self,
        workflow_id: str,
        summary: dict[str, Any],
        *,
        file_name: str = "run-summary.json",
    ) -> Path:
        """Persist a compact run summary for quick inspection."""
        self.ensure_layout()
        target_dir = self.summary_dir / workflow_id
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / file_name
        payload = {
            "saved_at": self._timestamp(),
            "workflow_id": workflow_id,
            "summary": summary,
        }
        self._write_json(path, payload)
        return path

    def load_run_summary(
        self,
        workflow_id: str,
        *,
        file_name: str = "run-summary.json",
    ) -> dict[str, Any]:
        """Load a previously persisted run summary payload."""
        path = self.summary_dir / workflow_id / file_name
        return self._read_json(path)

    def save_named_payload(
        self,
        relative_path: str | Path,
        payload: dict[str, Any],
    ) -> Path:
        """Persist an arbitrary JSON payload under the store root."""
        self.ensure_layout()
        path = self.root_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        wrapped_payload = {
            "saved_at": self._timestamp(),
            "payload": payload,
        }
        self._write_json(path, wrapped_payload)
        return path

    def load_named_payload(self, relative_path: str | Path) -> dict[str, Any]:
        """Load an arbitrary JSON payload from the store root."""
        path = self.root_dir / relative_path
        return self._read_json(path)

    def list_workflow_ids(self) -> list[str]:
        """Return known workflow ids sorted alphabetically."""
        self.ensure_layout()
        return sorted(
            path.name for path in self.workflow_dir.iterdir() if path.is_dir()
        )

    def list_session_ids(self) -> list[str]:
        """Return known session ids sorted alphabetically."""
        self.ensure_layout()
        return sorted(path.name for path in self.session_dir.iterdir() if path.is_dir())

    def workflow_exists(
        self,
        workflow_id: str,
        *,
        file_name: str = "workflow-state.json",
    ) -> bool:
        """Check whether a workflow state file exists."""
        return (self.workflow_dir / workflow_id / file_name).exists()

    def session_exists(
        self,
        session_id: str,
        *,
        file_name: str = "session-snapshot.json",
    ) -> bool:
        """Check whether a session snapshot file exists."""
        return (self.session_dir / session_id / file_name).exists()

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"State file not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _to_dict(self, value: Any) -> dict[str, Any]:
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, dict):
            return value
        raise TypeError(f"Unsupported value type for serialization: {type(value)!r}")

    def _timestamp(self) -> str:
        return datetime.now(UTC).isoformat()
