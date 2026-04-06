from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from impliforge.agents.base import AgentResult, AgentTask
from impliforge.orchestration.workflow import create_workflow_state
from impliforge.runtime.code_editing import CodeEditRequest
from impliforge.runtime.editor import EditRequest


@dataclass
class DummySessionSnapshot:
    session_id: str
    token_usage_ratio: float = 0.5


class DummySessionManager:
    def __init__(self, *, should_rotate: bool = False) -> None:
        self.should_rotate = should_rotate
        self.rotate_calls: list[dict[str, Any]] = []

    def build_resume_prompt(self, snapshot: DummySessionSnapshot) -> str:
        return f"resume:{snapshot.session_id}"

    def rotate_session(
        self,
        state: Any,
        *,
        token_usage_ratio: float,
        next_action: str,
        last_checkpoint: str,
        persistent_context: dict[str, Any],
    ) -> tuple[Any, DummySessionSnapshot]:
        self.rotate_calls.append(
            {
                "state": state,
                "token_usage_ratio": token_usage_ratio,
                "next_action": next_action,
                "last_checkpoint": last_checkpoint,
                "persistent_context": persistent_context,
            }
        )

        class Decision:
            def __init__(self, should_rotate: bool) -> None:
                self.should_rotate = should_rotate

        return (
            Decision(self.should_rotate),
            DummySessionSnapshot(session_id=state.session_id or "sess-rotated"),
        )


class DummyStateStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir

    def save_workflow_state(self, state: Any) -> Path:
        path = self.root_dir / "workflows" / state.workflow_id / "workflow-state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        return path

    def save_session_snapshot(self, snapshot: Any) -> Path:
        path = (
            self.root_dir / "sessions" / snapshot.session_id / "session-snapshot.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        return path

    def save_run_summary(self, workflow_id: str, summary: dict[str, Any]) -> Path:
        path = self.root_dir / "summaries" / workflow_id / "run-summary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(summary), encoding="utf-8")
        return path

    def save_named_payload(
        self, relative_path: str | Path, payload: dict[str, Any]
    ) -> Path:
        path = self.root_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(payload), encoding="utf-8")
        return path


class DummySafeEditResult:
    def __init__(
        self,
        *,
        ok: bool,
        changed: bool,
        relative_path: str,
        message: str = "",
    ) -> None:
        self.ok = ok
        self.changed = changed
        self.relative_path = relative_path
        self.message = message


class DummySafeEditor:
    def __init__(self, results: list[DummySafeEditResult] | None = None) -> None:
        self.results = results or []
        self.requests: list[EditRequest] = []

    def apply_many(self, requests: list[EditRequest]) -> list[DummySafeEditResult]:
        self.requests.extend(requests)
        return list(self.results)


class DummyCodeEditResult:
    def __init__(self, *, ok: bool, changed: bool) -> None:
        self.ok = ok
        self.changed = changed


class DummyCodeEditor:
    def __init__(self) -> None:
        self.requests: list[CodeEditRequest] = []

    def apply(self, request: CodeEditRequest) -> DummyCodeEditResult:
        self.requests.append(request)
        return DummyCodeEditResult(ok=True, changed=True)


class DummyAgent:
    def __init__(self, agent_name: str, result: AgentResult) -> None:
        self.agent_name = agent_name
        self.result = result
        self.calls: list[AgentTask] = []

    async def run(self, task: AgentTask, state: Any) -> AgentResult:
        self.calls.append(task)
        return self.result


def build_state() -> Any:
    state = create_workflow_state(
        workflow_id="wf-test-001",
        requirement="Build a multi-agent workflow",
        model="gpt-5.4",
    )
    state.set_session("sess-test-001")
    state.update_task_status(
        "requirements_analysis",
        state.require_task("requirements_analysis").status.COMPLETED,
        note="requirements done",
    )
    state.update_task_status(
        "planning",
        state.require_task("planning").status.COMPLETED,
        note="planning done",
    )
    state.update_task_status(
        "documentation",
        state.require_task("documentation").status.COMPLETED,
        note="documentation done",
    )
    state.update_task_status(
        "implementation",
        state.require_task("implementation").status.COMPLETED,
        note="implementation done",
    )
    state.update_task_status(
        "test_design",
        state.require_task("test_design").status.COMPLETED,
        note="test design done",
    )
    state.update_task_status(
        "test_execution",
        state.require_task("test_execution").status.COMPLETED,
        note="test execution done",
    )
    state.update_task_status(
        "review",
        state.require_task("review").status.COMPLETED,
        note="review done",
    )
    return state


def result(
    *,
    outputs: dict[str, Any] | None = None,
    artifacts: list[str] | None = None,
    next_actions: list[str] | None = None,
) -> AgentResult:
    return AgentResult.success(
        "ok",
        outputs=outputs or {},
        artifacts=artifacts or [],
        next_actions=next_actions or [],
    )
