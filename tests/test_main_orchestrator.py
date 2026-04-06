from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

main_module = importlib.import_module("devagents.main")
from devagents.agents.base import AgentResult, AgentTask
from devagents.main import SkeletonOrchestrator, _run_cli, build_parser, main
from devagents.models.routing import RoutingMode
from devagents.orchestration.workflow import (
    TaskStatus,
    WorkflowPhase,
    create_workflow_state,
)
from devagents.runtime.copilot_client import (
    CopilotRequest,
    CopilotResponse,
    CopilotTaskType,
    CopilotUsage,
)


class DummyRoutingDecision:
    def __init__(
        self,
        *,
        selected_model: str = "gpt-5.4-mini",
        fallback_model: str = "gpt-5.4",
        reason: str = "balanced route",
        task_kind: str = "planning",
        mode: str = "balanced",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.selected_model = selected_model
        self.fallback_model = fallback_model
        self.reason = reason
        self.task_kind = task_kind
        self.mode = mode
        self.metadata = metadata or {
            "required_tags": ["analysis", "reasoning"],
            "estimated_input_tokens": 21,
            "retry_count": 0,
            "fallback_reason": "alternate_available",
            "fallback_triggered": False,
            "retry_aware_selection": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_model": self.selected_model,
            "fallback_model": self.fallback_model,
            "reason": self.reason,
            "task_kind": self.task_kind,
            "mode": self.mode,
            "metadata": self.metadata,
        }


class DummyModelRouter:
    def __init__(self, decision: DummyRoutingDecision | None = None) -> None:
        self.decision = decision or DummyRoutingDecision()
        self.calls: list[dict[str, Any]] = []

    def route_task(
        self,
        task_id: str,
        *,
        difficulty: int,
        mode: RoutingMode,
        retry_count: int,
        estimated_input_tokens: int,
    ) -> DummyRoutingDecision:
        self.calls.append(
            {
                "task_id": task_id,
                "difficulty": difficulty,
                "mode": mode,
                "retry_count": retry_count,
                "estimated_input_tokens": estimated_input_tokens,
            }
        )
        return self.decision


class DummyCopilotClient:
    def __init__(self, response: CopilotResponse | None = None) -> None:
        self.response = response or CopilotResponse(
            content="copilot draft",
            model="gpt-5.4-mini",
            task_type=CopilotTaskType.GENERAL,
            session_id="sess-copilot",
            workflow_id="wf-copilot",
            usage=CopilotUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )
        self.generate_calls: list[CopilotRequest] = []
        self.resume_calls: list[dict[str, Any]] = []

    async def generate(self, request: CopilotRequest) -> CopilotResponse:
        self.generate_calls.append(request)
        return self.response

    def build_resume_request(
        self,
        *,
        prompt: str,
        resume_prompt: str,
        task_type: CopilotTaskType,
        session_id: str | None,
        workflow_id: str | None,
        persistent_context: dict[str, Any] | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
        reasoning_effort: str | None = None,
    ) -> CopilotRequest:
        payload = {
            "prompt": prompt,
            "resume_prompt": resume_prompt,
            "task_type": task_type,
            "session_id": session_id,
            "workflow_id": workflow_id,
            "persistent_context": dict(persistent_context or {}),
            "model": model,
            "metadata": dict(metadata or {}),
            "reasoning_effort": reasoning_effort,
        }
        self.resume_calls.append(payload)
        merged_prompt = "\n\n".join(
            part for part in [resume_prompt.strip(), prompt.strip()] if part
        )
        return CopilotRequest(
            prompt=merged_prompt,
            model=model,
            task_type=task_type,
            session_id=session_id,
            workflow_id=workflow_id,
            persistent_context=dict(persistent_context or {}),
            metadata={"resume": True, **dict(metadata or {})},
            reasoning_effort=reasoning_effort,
        )


class DummySessionSnapshot:
    def __init__(self, session_id: str, token_usage_ratio: float = 0.5) -> None:
        self.session_id = session_id
        self.token_usage_ratio = token_usage_ratio


class DummySessionManager:
    def __init__(self, *, should_rotate: bool = False) -> None:
        self.should_rotate = should_rotate
        self.start_calls: list[Any] = []
        self.snapshot_calls: list[dict[str, Any]] = []
        self.resume_prompt_calls: list[DummySessionSnapshot] = []
        self.rotate_calls: list[dict[str, Any]] = []
        self.should_rotate_calls: list[dict[str, Any]] = []

    def start_session(self, state: Any) -> None:
        self.start_calls.append(state)
        state.set_session("sess-started", parent_session_id=state.parent_session_id)

    def snapshot_context(
        self,
        state: Any,
        *,
        token_usage_ratio: float = 0.0,
        next_action: str,
        last_checkpoint: str,
        persistent_context: dict[str, Any] | None = None,
    ) -> DummySessionSnapshot:
        call = {
            "state": state,
            "token_usage_ratio": token_usage_ratio,
            "next_action": next_action,
            "last_checkpoint": last_checkpoint,
            "persistent_context": dict(persistent_context or {}),
        }
        self.snapshot_calls.append(call)
        return DummySessionSnapshot(
            session_id=state.session_id or "sess-snapshot",
            token_usage_ratio=token_usage_ratio,
        )

    def build_resume_prompt(self, snapshot: DummySessionSnapshot) -> str:
        self.resume_prompt_calls.append(snapshot)
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
                "persistent_context": dict(persistent_context),
            }
        )

        class Decision:
            def __init__(self, should_rotate: bool) -> None:
                self.should_rotate = should_rotate

        return Decision(self.should_rotate), DummySessionSnapshot(
            session_id=state.session_id or "sess-rotated",
            token_usage_ratio=token_usage_ratio,
        )

    def should_rotate_session(
        self,
        *,
        token_usage_ratio: float,
        current_session_id: str | None,
    ) -> Any:
        self.should_rotate_calls.append(
            {
                "token_usage_ratio": token_usage_ratio,
                "current_session_id": current_session_id,
            }
        )

        class Decision:
            def __init__(self, should_rotate: bool) -> None:
                self.should_rotate = should_rotate
                self.reason = "threshold exceeded" if should_rotate else ""

        return Decision(self.should_rotate)


class DummyArtifactWriter:
    def __init__(self) -> None:
        self.documentation_calls: list[dict[str, Any]] = []
        self.text_calls: list[dict[str, Any]] = []
        self.workflow_calls: list[dict[str, Any]] = []

    def persist_documentation_outputs(self, *, state: Any, result: AgentResult) -> None:
        self.documentation_calls.append({"state": state, "result": result})

    def persist_text_output(
        self,
        *,
        state: Any,
        result: AgentResult,
        output_key: str,
        target_name: str,
    ) -> None:
        self.text_calls.append(
            {
                "state": state,
                "result": result,
                "output_key": output_key,
                "target_name": target_name,
            }
        )

    def write_workflow_artifacts(self, **kwargs: Any) -> None:
        self.workflow_calls.append(kwargs)


class DummyRuntimeSupport:
    def __init__(self) -> None:
        self.rotate_calls: list[dict[str, Any]] = []
        self.approval_hook = object()

    def rotate_session_if_needed(
        self,
        state: Any,
        *,
        token_usage_ratio: float,
        next_action: str,
        last_checkpoint: str,
        persistent_context: dict[str, Any],
    ) -> None:
        self.rotate_calls.append(
            {
                "state": state,
                "token_usage_ratio": token_usage_ratio,
                "next_action": next_action,
                "last_checkpoint": last_checkpoint,
                "persistent_context": dict(persistent_context),
            }
        )

    def degraded_routing_mode(
        self,
        state: Any,
        *,
        routing_mode: RoutingMode,
    ) -> RoutingMode:
        session_snapshot = getattr(state, "session_snapshot", None)
        token_usage_ratio = getattr(session_snapshot, "token_usage_ratio", None)

        if routing_mode is RoutingMode.COST_SAVER:
            return routing_mode
        if not isinstance(token_usage_ratio, int | float):
            return routing_mode
        if token_usage_ratio < 0.9:
            return routing_mode

        state.add_note(
            "budget-like token usage signal exceeded threshold; routing degraded to cost_saver mode."
        )
        state.add_risk(
            "High token usage triggered degraded routing mode; output quality may be reduced until budget pressure clears."
        )
        return RoutingMode.COST_SAVER


class DummyEditPhase:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def apply_safe_edit_phase(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


class DummyAgent:
    def __init__(self, agent_name: str, result: AgentResult) -> None:
        self.agent_name = agent_name
        self.result = result
        self.calls: list[AgentTask] = []

    async def run(self, task: AgentTask, state: Any) -> AgentResult:
        self.calls.append(task)
        return self.result


def make_result(
    *,
    summary: str = "ok",
    outputs: dict[str, Any] | None = None,
    artifacts: list[str] | None = None,
    risks: list[str] | None = None,
) -> AgentResult:
    return AgentResult.success(
        summary,
        outputs=outputs or {},
        artifacts=artifacts or [],
        risks=risks or [],
    )


def make_failure(
    *,
    summary: str = "failed",
    outputs: dict[str, Any] | None = None,
    artifacts: list[str] | None = None,
    risks: list[str] | None = None,
    next_actions: list[str] | None = None,
    failure_category: str | None = None,
    failure_cause: str | None = None,
) -> AgentResult:
    return AgentResult.failure(
        summary,
        outputs=outputs or {},
        artifacts=artifacts or [],
        risks=risks or [],
        next_actions=next_actions or [],
        failure_category=failure_category,
        failure_cause=failure_cause,
    )


def make_state() -> Any:
    state = create_workflow_state(
        workflow_id="wf-test-main",
        requirement="Build a multi-agent workflow",
        model="gpt-5.4",
    )
    state.set_session("sess-main")
    return state


def make_orchestrator(
    tmp_path: Path,
    *,
    routing_mode: RoutingMode = RoutingMode.BALANCED,
) -> SkeletonOrchestrator:
    orchestrator = SkeletonOrchestrator(
        model="gpt-5.4",
        artifacts_dir=tmp_path / "artifacts",
        docs_dir=tmp_path / "docs",
        routing_mode=routing_mode,
    )
    orchestrator.model_router = DummyModelRouter()
    orchestrator.copilot_client = DummyCopilotClient()
    orchestrator.session_manager = DummySessionManager()
    orchestrator.artifact_writer = DummyArtifactWriter()
    orchestrator.runtime_support = DummyRuntimeSupport()
    orchestrator.safe_editor.approval_hook = orchestrator.runtime_support.approval_hook
    orchestrator.edit_phase = DummyEditPhase()
    return orchestrator


def test_build_parser_parses_defaults_and_overrides() -> None:
    parser = build_parser()

    defaults = parser.parse_args(["ship feature"])
    assert defaults.requirement == "ship feature"
    assert defaults.model == "gpt-5.4"
    assert defaults.artifacts_dir == "artifacts"
    assert defaults.docs_dir == "docs"
    assert defaults.token_usage_ratio == 0.35
    assert defaults.routing_mode == RoutingMode.BALANCED.value

    custom = parser.parse_args(
        [
            "ship feature",
            "--model",
            "gpt-5.4-mini",
            "--artifacts-dir",
            "tmp-artifacts",
            "--docs-dir",
            "tmp-docs",
            "--token-usage-ratio",
            "0.8",
            "--routing-mode",
            RoutingMode.COST_SAVER.value,
        ]
    )
    assert custom.model == "gpt-5.4-mini"
    assert custom.artifacts_dir == "tmp-artifacts"
    assert custom.docs_dir == "tmp-docs"
    assert custom.token_usage_ratio == 0.8
    assert custom.routing_mode == RoutingMode.COST_SAVER.value


def test_build_copilot_request_returns_plain_request_without_parent_session(
    tmp_path: Path,
) -> None:
    orchestrator = make_orchestrator(tmp_path)
    state = make_state()

    request = orchestrator._build_copilot_request(
        state=state,
        prompt="implement this",
        system_prompt="system guidance",
        model="gpt-5.4-mini",
        task_type=CopilotTaskType.IMPLEMENTATION,
        persistent_context={"phase": "implementing"},
        metadata={"task_id": "implementation"},
    )

    assert isinstance(request, CopilotRequest)
    assert request.prompt == "implement this"
    assert request.system_prompt == "system guidance"
    assert request.model == "gpt-5.4-mini"
    assert request.task_type is CopilotTaskType.IMPLEMENTATION
    assert request.session_id == "sess-main"
    assert request.workflow_id == "wf-test-main"
    assert request.persistent_context == {"phase": "implementing"}
    assert request.metadata == {"task_id": "implementation"}
    assert orchestrator.session_manager.snapshot_calls == []
    assert orchestrator.copilot_client.resume_calls == []


def test_build_copilot_request_uses_resume_request_when_parent_session_exists(
    tmp_path: Path,
) -> None:
    orchestrator = make_orchestrator(tmp_path)
    state = make_state()
    state.set_session("sess-child", parent_session_id="sess-parent")

    request = orchestrator._build_copilot_request(
        state=state,
        prompt="review this",
        system_prompt="ignored for resume",
        model="gpt-5.4",
        task_type=CopilotTaskType.REVIEW,
        persistent_context={"phase": "reviewing", "workflow_id": state.workflow_id},
        metadata={"task_id": "review"},
    )

    assert request.metadata["resume"] is True
    assert request.metadata["task_id"] == "review"
    assert request.prompt == "resume:sess-child\n\nreview this"
    assert request.system_prompt is None
    assert len(orchestrator.session_manager.snapshot_calls) == 1
    snapshot_call = orchestrator.session_manager.snapshot_calls[0]
    assert snapshot_call["next_action"] == "Resume review"
    assert snapshot_call["last_checkpoint"] == state.phase.value
    assert snapshot_call["persistent_context"] == {
        "phase": "reviewing",
        "workflow_id": state.workflow_id,
    }
    assert len(orchestrator.copilot_client.resume_calls) == 1
    resume_call = orchestrator.copilot_client.resume_calls[0]
    assert resume_call["resume_prompt"] == "resume:sess-child"
    assert resume_call["session_id"] == "sess-child"
    assert resume_call["workflow_id"] == "wf-test-main"


def test_apply_result_marks_success_and_collects_outputs() -> None:
    orchestrator = SkeletonOrchestrator.__new__(SkeletonOrchestrator)
    state = make_state()
    result = make_result(
        summary="planning complete",
        outputs={"plan": {"steps": ["a"]}, "open_questions": ["what next?", ""]},
        artifacts=["artifacts/plan.md"],
        risks=["timeline risk"],
    )

    orchestrator._apply_result(
        state=state,
        task_id="planning",
        phase=WorkflowPhase.PLANNED,
        result=result,
    )

    task = state.require_task("planning")
    assert task.status is TaskStatus.COMPLETED
    assert task.outputs["plan"] == {"steps": ["a"]}
    assert "planning complete" in task.notes
    assert state.phase is WorkflowPhase.PLANNED
    assert state.artifacts == ["artifacts/plan.md"]
    assert state.risks == ["timeline risk"]
    assert state.open_questions == ["what next?"]
    assert state.retry_counters == {}


def test_apply_result_marks_failure_and_increments_retry() -> None:
    orchestrator = SkeletonOrchestrator.__new__(SkeletonOrchestrator)
    state = make_state()
    result = make_failure(
        summary="tests failed",
        outputs={"open_questions": ["fix flaky test"]},
        artifacts=["artifacts/test-results.md"],
        risks=["coverage gap"],
    )

    orchestrator._apply_result(
        state=state,
        task_id="test_execution",
        phase=WorkflowPhase.TESTING,
        result=result,
    )

    task = state.require_task("test_execution")
    assert task.status is TaskStatus.FAILED
    assert "tests failed" in task.notes
    assert state.phase is WorkflowPhase.FAILED
    assert state.retry_counters["test_execution"] == 1
    assert state.artifacts == ["artifacts/test-results.md"]
    assert state.risks == ["coverage gap"]
    assert state.open_questions == ["fix flaky test"]


def test_execute_phase_routes_builds_agent_task_and_updates_state(
    tmp_path: Path,
) -> None:
    orchestrator = make_orchestrator(tmp_path)
    state = make_state()
    agent = DummyAgent(
        "planner",
        make_result(
            summary="plan ready",
            outputs={"plan": {"phases": ["requirements", "planning"]}},
            artifacts=["artifacts/plan.md"],
            risks=["scope drift"],
        ),
    )

    result = asyncio.run(
        orchestrator._execute_phase(
            state=state,
            task_id="planning",
            agent=agent,
            difficulty=4,
            phase=WorkflowPhase.PLANNED,
            task_type=CopilotTaskType.PLANNING,
            prompt="normalized requirements",
            system_prompt="create a plan",
            estimated_input_tokens=21,
            persistent_context={
                "workflow_id": state.workflow_id,
                "phase": state.phase.value,
            },
            build_inputs=lambda routing, copilot_response: {
                "copilot_response": copilot_response.content,
                "selected_model": routing["selected_model"],
            },
        )
    )

    assert result.is_success is True
    assert len(orchestrator.model_router.calls) == 1
    route_call = orchestrator.model_router.calls[0]
    assert route_call["task_id"] == "planning"
    assert route_call["difficulty"] == 4
    assert route_call["mode"] == RoutingMode.BALANCED
    assert route_call["retry_count"] == 0
    assert route_call["estimated_input_tokens"] == 21

    assert len(orchestrator.copilot_client.generate_calls) == 1
    request = orchestrator.copilot_client.generate_calls[0]
    assert request.prompt == "normalized requirements"
    assert request.system_prompt == "create a plan"
    assert request.task_type is CopilotTaskType.PLANNING
    assert request.metadata["task_id"] == "planning"
    assert request.metadata["routing_decision"]["selected_model"] == "gpt-5.4-mini"
    assert request.metadata["routing_decision"]["task_kind"] == "planning"
    assert request.metadata["routing_decision"]["mode"] == "balanced"
    assert request.metadata["routing_decision"]["metadata"] == {
        "required_tags": ["analysis", "reasoning"],
        "estimated_input_tokens": 21,
        "retry_count": 0,
        "fallback_reason": "alternate_available",
        "fallback_triggered": False,
        "retry_aware_selection": False,
    }

    assert len(agent.calls) == 1
    task = agent.calls[0]
    assert task.name == "planning"
    assert task.inputs["copilot_response"] == "copilot draft"
    assert task.inputs["selected_model"] == "gpt-5.4-mini"
    assert task.inputs["routing_decision"]["fallback_model"] == "gpt-5.4"
    assert task.inputs["routing_decision"]["task_kind"] == "planning"
    assert (
        task.inputs["routing_decision"]["metadata"]["fallback_reason"]
        == "alternate_available"
    )
    assert task.metadata == {
        "selected_model": "gpt-5.4-mini",
        "fallback_model": "gpt-5.4",
        "copilot_dry_run": False,
    }

    planning_task = state.require_task("planning")
    assert planning_task.status is TaskStatus.COMPLETED
    assert "selected_model=gpt-5.4-mini" in planning_task.notes
    assert "routing_reason=balanced route" in planning_task.notes
    assert "plan ready" in planning_task.notes
    assert state.phase is WorkflowPhase.PLANNED
    assert state.model == "gpt-5.4-mini"
    assert state.artifacts == ["artifacts/plan.md"]
    assert state.risks == ["scope drift"]


def test_run_fix_loop_returns_none_when_review_is_not_dict(tmp_path: Path) -> None:
    orchestrator = make_orchestrator(tmp_path)
    state = make_state()

    result = asyncio.run(
        orchestrator._run_fix_loop(
            state,
            requirements_result=make_result(outputs={"normalized_requirements": {}}),
            planning_result=make_result(outputs={"plan": {}}),
            documentation_result=make_result(outputs={"documentation_bundle": {}}),
            implementation_result=make_result(outputs={"implementation": {}}),
            test_design_result=make_result(outputs={"test_plan": {}}),
            test_execution_result=make_result(outputs={"test_results": {}}),
            review_result=make_result(outputs={"review": "not-a-dict"}),
        )
    )

    assert result is None


def test_run_fix_loop_skips_when_review_has_no_blocking_issue(tmp_path: Path) -> None:
    orchestrator = make_orchestrator(tmp_path)
    state = make_state()

    result = asyncio.run(
        orchestrator._run_fix_loop(
            state,
            requirements_result=make_result(outputs={"normalized_requirements": {}}),
            planning_result=make_result(outputs={"plan": {}}),
            documentation_result=make_result(outputs={"documentation_bundle": {}}),
            implementation_result=make_result(outputs={"implementation": {}}),
            test_design_result=make_result(outputs={"test_plan": {}}),
            test_execution_result=make_result(outputs={"test_results": {}}),
            review_result=make_result(outputs={"review": {"fix_loop_required": False}}),
        )
    )

    assert result is None
    assert any("fix loop は不要" in note for note in state.notes)


def test_run_fix_loop_runs_fix_and_reruns_validation(tmp_path: Path) -> None:
    orchestrator = make_orchestrator(tmp_path)
    state = make_state()

    fix_result = make_result(
        summary="fix ready",
        outputs={"implementation": {"changes": ["patch"]}},
    )
    rerun_test_result = make_result(
        summary="tests rerun",
        outputs={"test_results": {"status": "passed"}},
    )
    rerun_review_result = make_result(
        summary="review rerun",
        outputs={"review": {"fix_loop_required": False}},
    )

    fix_calls: list[dict[str, Any]] = []
    test_calls: list[dict[str, Any]] = []
    review_calls: list[dict[str, Any]] = []

    async def fake_fix_phase(state_arg: Any, **kwargs: Any) -> AgentResult:
        fix_calls.append({"state": state_arg, **kwargs})
        return fix_result

    async def fake_test_execution(
        state_arg: Any,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
    ) -> AgentResult:
        test_calls.append(
            {
                "state": state_arg,
                "requirements_result": requirements_result,
                "planning_result": planning_result,
                "implementation_result": implementation_result,
                "test_design_result": test_design_result,
            }
        )
        return rerun_test_result

    async def fake_review_phase(
        state_arg: Any,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        documentation_result: AgentResult,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
        test_execution_result: AgentResult,
    ) -> AgentResult:
        review_calls.append(
            {
                "state": state_arg,
                "requirements_result": requirements_result,
                "planning_result": planning_result,
                "documentation_result": documentation_result,
                "implementation_result": implementation_result,
                "test_design_result": test_design_result,
                "test_execution_result": test_execution_result,
            }
        )
        return rerun_review_result

    orchestrator._run_fix_phase = fake_fix_phase
    orchestrator._run_test_execution_phase = fake_test_execution
    orchestrator._run_review_phase = fake_review_phase

    requirements_result = make_result(
        outputs={"normalized_requirements": {"objective": "x"}}
    )
    planning_result = make_result(outputs={"plan": {"steps": ["a"]}})
    documentation_result = make_result(outputs={"documentation_bundle": {"doc": "x"}})
    implementation_result = make_result(
        outputs={"implementation": {"changes": ["base"]}}
    )
    test_design_result = make_result(outputs={"test_plan": {"cases": ["c1"]}})
    test_execution_result = make_result(outputs={"test_results": {"status": "failed"}})
    review_result = make_result(outputs={"review": {"fix_loop_required": True}})

    result = asyncio.run(
        orchestrator._run_fix_loop(
            state,
            requirements_result=requirements_result,
            planning_result=planning_result,
            documentation_result=documentation_result,
            implementation_result=implementation_result,
            test_design_result=test_design_result,
            test_execution_result=test_execution_result,
            review_result=review_result,
        )
    )

    assert result is fix_result
    assert len(fix_calls) == 1
    assert len(test_calls) == 1
    assert len(review_calls) == 1
    assert test_calls[0]["implementation_result"].outputs["implementation"] == {
        "changes": ["patch"]
    }
    assert review_calls[0]["test_execution_result"] is rerun_test_result
    assert any(
        "fix loop を開始した。attempt=1/2" in note
        for note in state.require_task("implementation").notes
    )
    assert any("fix loop を 1 回目として実行" in note for note in state.notes)


def test_run_completes_full_flow_and_writes_artifacts(tmp_path: Path) -> None:
    orchestrator = make_orchestrator(tmp_path)
    orchestrator.requirements_agent = DummyAgent(
        "requirements",
        make_result(
            summary="requirements done",
            outputs={"normalized_requirements": {"objective": "Build workflow"}},
        ),
    )
    orchestrator.planning_agent = DummyAgent(
        "planner",
        make_result(summary="planning done", outputs={"plan": {"phases": ["plan"]}}),
    )
    orchestrator.documentation_agent = DummyAgent(
        "documentation",
        make_result(
            summary="documentation done",
            outputs={"documentation_bundle": {"design_doc": "doc text"}},
        ),
    )
    orchestrator.implementation_agent = DummyAgent(
        "implementation",
        make_result(
            summary="implementation done",
            outputs={"implementation": {"changes": ["src/devagents/main.py"]}},
        ),
    )
    orchestrator.test_design_agent = DummyAgent(
        "test-design",
        make_result(
            summary="test design done",
            outputs={
                "test_plan": {"cases": ["parser", "orchestrator"]},
                "test_plan_document": "# test plan",
            },
        ),
    )
    orchestrator.test_execution_agent = DummyAgent(
        "test-execution",
        make_result(
            summary="test execution done",
            outputs={
                "test_results": {"status": "passed"},
                "test_results_document": "# test results",
            },
        ),
    )
    orchestrator.review_agent = DummyAgent(
        "review",
        make_result(
            summary="review done",
            outputs={
                "review": {"fix_loop_required": False},
                "review_report": "# review report",
            },
        ),
    )
    orchestrator.fixer_agent = DummyAgent(
        "fixer",
        make_result(summary="fix done", outputs={"implementation": {"changes": []}}),
    )

    state = asyncio.run(
        orchestrator.run(
            "Build a multi-agent workflow",
            token_usage_ratio=0.61,
        )
    )

    assert state.phase is WorkflowPhase.COMPLETED
    assert state.session_id == "sess-started"
    assert state.require_task("requirements_analysis").status is TaskStatus.COMPLETED
    assert state.require_task("planning").status is TaskStatus.COMPLETED
    assert state.require_task("documentation").status is TaskStatus.COMPLETED
    assert state.require_task("implementation").status is TaskStatus.COMPLETED
    assert state.require_task("test_design").status is TaskStatus.COMPLETED
    assert state.require_task("test_execution").status is TaskStatus.COMPLETED
    assert state.require_task("review").status is TaskStatus.COMPLETED
    assert any("fix loop は不要" in note for note in state.notes)
    assert any("safe edit phase" in note for note in state.notes)

    assert (tmp_path / "artifacts").exists()
    assert (tmp_path / "docs").exists()

    assert len(orchestrator.runtime_support.rotate_calls) == 1
    rotate_call = orchestrator.runtime_support.rotate_calls[0]
    assert rotate_call["token_usage_ratio"] == 0.61
    assert rotate_call["next_action"] == "Resume review after test_execution"
    assert rotate_call["last_checkpoint"] == WorkflowPhase.TESTING.value
    assert rotate_call["persistent_context"]["test_results"] == {"status": "passed"}

    assert len(orchestrator.model_router.calls) == 7
    assert all(
        call["mode"] is RoutingMode.BALANCED for call in orchestrator.model_router.calls
    )

    assert len(orchestrator.edit_phase.calls) == 1
    edit_call = orchestrator.edit_phase.calls[0]
    assert edit_call["requirement"] == "Build a multi-agent workflow"
    assert edit_call["review_result"].outputs["review"]["fix_loop_required"] is False
    assert edit_call["fix_result"] is None

    assert len(orchestrator.artifact_writer.documentation_calls) == 1
    assert len(orchestrator.artifact_writer.text_calls) == 3
    assert {
        call["target_name"] for call in orchestrator.artifact_writer.text_calls
    } == {
        "test-plan.md",
        "test-results.md",
        "review-report.md",
    }
    assert len(orchestrator.artifact_writer.workflow_calls) == 1
    workflow_call = orchestrator.artifact_writer.workflow_calls[0]
    assert workflow_call["state"] is state
    assert workflow_call["requirement"] == "Build a multi-agent workflow"
    assert workflow_call["requirements_result"].outputs["normalized_requirements"] == {
        "objective": "Build workflow"
    }
    assert workflow_call["planning_result"].outputs["plan"] == {"phases": ["plan"]}
    assert workflow_call["documentation_result"].outputs["documentation_bundle"] == {
        "design_doc": "doc text"
    }
    assert workflow_call["implementation_result"].outputs["implementation"] == {
        "changes": ["src/devagents/main.py"]
    }
    assert workflow_call["test_design_result"].outputs["test_plan"] == {
        "cases": ["parser", "orchestrator"]
    }
    assert workflow_call["test_execution_result"].outputs["test_results"] == {
        "status": "passed"
    }
    assert workflow_call["review_result"].outputs["review"] == {
        "fix_loop_required": False
    }
    assert workflow_call["fix_result"] is None
    assert workflow_call["session_snapshot"].session_id == "sess-started"

    assert len(orchestrator.session_manager.start_calls) == 1
    assert len(orchestrator.session_manager.snapshot_calls) == 1
    snapshot_call = orchestrator.session_manager.snapshot_calls[0]
    assert snapshot_call["token_usage_ratio"] == 0.61
    assert snapshot_call["last_checkpoint"] == WorkflowPhase.REVIEWING.value
    assert "Promote safe edit outputs" in snapshot_call["next_action"]


def test_run_degrades_routing_to_cost_saver_when_budget_signal_is_high(
    tmp_path: Path,
) -> None:
    orchestrator = make_orchestrator(tmp_path)
    orchestrator.requirements_agent = DummyAgent(
        "requirements",
        make_result(
            summary="requirements done",
            outputs={"normalized_requirements": {"objective": "Build workflow"}},
        ),
    )
    orchestrator.planning_agent = DummyAgent(
        "planner",
        make_result(summary="planning done", outputs={"plan": {"phases": ["plan"]}}),
    )
    orchestrator.documentation_agent = DummyAgent(
        "documentation",
        make_result(
            summary="documentation done",
            outputs={"documentation_bundle": {"design_doc": "doc text"}},
        ),
    )
    orchestrator.implementation_agent = DummyAgent(
        "implementation",
        make_result(
            summary="implementation done",
            outputs={"implementation": {"changes": ["src/devagents/main.py"]}},
        ),
    )
    orchestrator.test_design_agent = DummyAgent(
        "test-design",
        make_result(
            summary="test design done",
            outputs={
                "test_plan": {"cases": ["parser", "orchestrator"]},
                "test_plan_document": "# test plan",
            },
        ),
    )
    orchestrator.test_execution_agent = DummyAgent(
        "test-execution",
        make_result(
            summary="test execution done",
            outputs={
                "test_results": {"status": "passed"},
                "test_results_document": "# test results",
            },
        ),
    )
    orchestrator.review_agent = DummyAgent(
        "review",
        make_result(
            summary="review done",
            outputs={
                "review": {"fix_loop_required": False},
                "review_report": "# review report",
            },
        ),
    )
    orchestrator.fixer_agent = DummyAgent(
        "fixer",
        make_result(summary="fix done", outputs={"implementation": {"changes": []}}),
    )

    state = asyncio.run(
        orchestrator.run(
            "Build a multi-agent workflow",
            token_usage_ratio=0.97,
        )
    )

    assert state.phase is WorkflowPhase.COMPLETED
    assert len(orchestrator.model_router.calls) == 7
    assert all(
        call["mode"] is RoutingMode.BALANCED for call in orchestrator.model_router.calls
    )
    assert not any(
        "routing degraded to cost_saver mode" in note for note in state.notes
    )
    assert not any(
        "High token usage triggered degraded routing mode" in risk
        for risk in state.risks
    )


def test_run_does_not_duplicate_budget_degraded_note_when_already_cost_saver(
    tmp_path: Path,
) -> None:
    orchestrator = make_orchestrator(tmp_path, routing_mode=RoutingMode.COST_SAVER)
    orchestrator.requirements_agent = DummyAgent(
        "requirements",
        make_result(
            summary="requirements done",
            outputs={"normalized_requirements": {"objective": "Build workflow"}},
        ),
    )
    orchestrator.planning_agent = DummyAgent(
        "planner",
        make_result(summary="planning done", outputs={"plan": {"phases": ["plan"]}}),
    )
    orchestrator.documentation_agent = DummyAgent(
        "documentation",
        make_result(
            summary="documentation done",
            outputs={"documentation_bundle": {"design_doc": "doc text"}},
        ),
    )
    orchestrator.implementation_agent = DummyAgent(
        "implementation",
        make_result(
            summary="implementation done",
            outputs={"implementation": {"changes": ["src/devagents/main.py"]}},
        ),
    )
    orchestrator.test_design_agent = DummyAgent(
        "test-design",
        make_result(
            summary="test design done",
            outputs={
                "test_plan": {"cases": ["parser", "orchestrator"]},
                "test_plan_document": "# test plan",
            },
        ),
    )
    orchestrator.test_execution_agent = DummyAgent(
        "test-execution",
        make_result(
            summary="test execution done",
            outputs={
                "test_results": {"status": "passed"},
                "test_results_document": "# test results",
            },
        ),
    )
    orchestrator.review_agent = DummyAgent(
        "review",
        make_result(
            summary="review done",
            outputs={
                "review": {"fix_loop_required": False},
                "review_report": "# review report",
            },
        ),
    )
    orchestrator.fixer_agent = DummyAgent(
        "fixer",
        make_result(summary="fix done", outputs={"implementation": {"changes": []}}),
    )

    state = asyncio.run(
        orchestrator.run(
            "Build a multi-agent workflow",
            token_usage_ratio=0.97,
        )
    )

    assert state.phase is WorkflowPhase.COMPLETED
    assert len(orchestrator.model_router.calls) == 7
    assert all(
        call["mode"] is RoutingMode.COST_SAVER
        for call in orchestrator.model_router.calls
    )
    assert not any(
        "routing degraded to cost_saver mode" in note for note in state.notes
    )
    assert not any(
        "High token usage triggered degraded routing mode" in risk
        for risk in state.risks
    )


def test_run_rotates_session_and_persists_artifacts_across_fix_loop(
    tmp_path: Path,
) -> None:
    orchestrator = make_orchestrator(tmp_path)
    orchestrator.requirements_agent = DummyAgent(
        "requirements",
        make_result(
            summary="requirements done",
            outputs={"normalized_requirements": {"objective": "Build workflow"}},
        ),
    )
    orchestrator.planning_agent = DummyAgent(
        "planner",
        make_result(summary="planning done", outputs={"plan": {"phases": ["plan"]}}),
    )
    orchestrator.documentation_agent = DummyAgent(
        "documentation",
        make_result(
            summary="documentation done",
            outputs={"documentation_bundle": {"design_doc": "doc text"}},
        ),
    )
    orchestrator.implementation_agent = DummyAgent(
        "implementation",
        make_result(
            summary="implementation done",
            outputs={"implementation": {"changes": ["src/devagents/main.py"]}},
        ),
    )
    orchestrator.test_design_agent = DummyAgent(
        "test-design",
        make_result(
            summary="test design done",
            outputs={
                "test_plan": {"cases": ["parser", "orchestrator"]},
                "test_plan_document": "# test plan",
            },
        ),
    )
    orchestrator.test_execution_agent = DummyAgent(
        "test-execution",
        make_result(
            summary="test execution done",
            outputs={
                "test_results": {"status": "failed", "failures": ["review issue"]},
                "test_results_document": "# test results",
            },
        ),
    )
    orchestrator.review_agent = DummyAgent(
        "review",
        make_result(
            summary="review done",
            outputs={
                "review": {"fix_loop_required": True, "blocking_issues": ["issue"]},
                "review_report": "# review report",
            },
        ),
    )
    orchestrator.fixer_agent = DummyAgent(
        "fixer",
        make_result(
            summary="fix prepared",
            outputs={
                "fix_report": "# fix report",
                "implementation": {
                    "changes": [
                        "src/devagents/main.py",
                        "tests/test_main_orchestrator.py",
                    ]
                },
            },
        ),
    )

    original_test_execution_phase = orchestrator._run_test_execution_phase
    original_review_phase = orchestrator._run_review_phase

    rerun_test_result = make_result(
        summary="tests rerun",
        outputs={
            "test_results": {"status": "passed"},
            "test_results_document": "# rerun test results",
        },
    )
    rerun_review_result = make_result(
        summary="review rerun",
        outputs={
            "review": {"fix_loop_required": False},
            "review_report": "# rerun review report",
        },
    )

    test_execution_calls: list[dict[str, Any]] = []
    review_calls: list[dict[str, Any]] = []

    async def fake_test_execution(
        state_arg: Any,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
    ) -> AgentResult:
        test_execution_calls.append(
            {
                "state": state_arg,
                "requirements_result": requirements_result,
                "planning_result": planning_result,
                "implementation_result": implementation_result,
                "test_design_result": test_design_result,
            }
        )
        if len(test_execution_calls) == 1:
            return await original_test_execution_phase(
                state_arg,
                requirements_result,
                planning_result,
                implementation_result,
                test_design_result,
            )
        state_arg.update_task_status(
            "test_execution",
            TaskStatus.COMPLETED,
            note=rerun_test_result.summary,
            outputs=rerun_test_result.outputs,
        )
        state_arg.set_phase(WorkflowPhase.TESTING)
        orchestrator.artifact_writer.persist_text_output(
            state=state_arg,
            result=rerun_test_result,
            output_key="test_results_document",
            target_name="test-results.md",
        )
        return rerun_test_result

    async def fake_review_phase(
        state_arg: Any,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        documentation_result: AgentResult,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
        test_execution_result: AgentResult,
    ) -> AgentResult:
        review_calls.append(
            {
                "state": state_arg,
                "requirements_result": requirements_result,
                "planning_result": planning_result,
                "documentation_result": documentation_result,
                "implementation_result": implementation_result,
                "test_design_result": test_design_result,
                "test_execution_result": test_execution_result,
            }
        )
        if len(review_calls) == 1:
            return await original_review_phase(
                state_arg,
                requirements_result,
                planning_result,
                documentation_result,
                implementation_result,
                test_design_result,
                test_execution_result,
            )
        state_arg.update_task_status(
            "review",
            TaskStatus.COMPLETED,
            note=rerun_review_result.summary,
            outputs=rerun_review_result.outputs,
        )
        state_arg.set_phase(WorkflowPhase.REVIEWING)
        orchestrator.artifact_writer.persist_text_output(
            state=state_arg,
            result=rerun_review_result,
            output_key="review_report",
            target_name="review-report.md",
        )
        return rerun_review_result

    orchestrator._run_test_execution_phase = fake_test_execution
    orchestrator._run_review_phase = fake_review_phase

    state = asyncio.run(
        orchestrator.run(
            "Build a multi-agent workflow",
            token_usage_ratio=0.82,
        )
    )

    workflow_call = orchestrator.artifact_writer.workflow_calls[0]
    edit_call = orchestrator.edit_phase.calls[0]

    assert state.phase is WorkflowPhase.COMPLETED
    assert len(orchestrator.runtime_support.rotate_calls) == 1
    rotate_call = orchestrator.runtime_support.rotate_calls[0]
    assert rotate_call["token_usage_ratio"] == 0.82
    assert rotate_call["next_action"] == "Resume review after test_execution"
    assert rotate_call["last_checkpoint"] == WorkflowPhase.TESTING.value
    assert rotate_call["persistent_context"]["test_results"] == {
        "status": "failed",
        "failures": ["review issue"],
    }

    assert len(test_execution_calls) == 2
    assert len(review_calls) == 2
    assert review_calls[1]["test_execution_result"] is rerun_test_result

    assert len(orchestrator.artifact_writer.text_calls) == 6
    assert [
        call["target_name"] for call in orchestrator.artifact_writer.text_calls
    ] == [
        "test-plan.md",
        "test-results.md",
        "review-report.md",
        "fix-report.md",
        "test-results.md",
        "review-report.md",
    ]
    assert len(orchestrator.artifact_writer.workflow_calls) == 1
    assert workflow_call["state"] is state
    assert workflow_call["requirements_result"].outputs["normalized_requirements"] == {
        "objective": "Build workflow"
    }
    assert workflow_call["planning_result"].outputs["plan"] == {"phases": ["plan"]}
    assert workflow_call["documentation_result"].outputs["documentation_bundle"] == {
        "design_doc": "doc text"
    }
    assert workflow_call["implementation_result"].outputs["implementation"] == {
        "changes": [
            "src/devagents/main.py",
            "tests/test_main_orchestrator.py",
        ]
    }
    assert workflow_call["test_design_result"].outputs["test_plan"] == {
        "cases": ["parser", "orchestrator"]
    }
    assert workflow_call["test_execution_result"].outputs["test_results"] == {
        "status": "passed"
    }
    assert workflow_call["review_result"].outputs["review"] == {
        "fix_loop_required": False
    }
    assert workflow_call["implementation_result"].outputs["implementation"] == {
        "changes": [
            "src/devagents/main.py",
            "tests/test_main_orchestrator.py",
        ]
    }
    assert workflow_call["fix_result"].outputs["implementation"]["changes"] == [
        "src/devagents/main.py",
        "tests/test_main_orchestrator.py",
    ]
    assert len(orchestrator.edit_phase.calls) == 1
    assert edit_call["implementation_result"].outputs["implementation"] == {
        "changes": [
            "src/devagents/main.py",
            "tests/test_main_orchestrator.py",
        ]
    }
    assert edit_call["test_execution_result"].outputs["test_results"] == {
        "status": "passed"
    }
    assert edit_call["review_result"].outputs["review"] == {"fix_loop_required": False}

    assert len(orchestrator.session_manager.snapshot_calls) == 1
    snapshot_call = orchestrator.session_manager.snapshot_calls[0]
    assert snapshot_call["token_usage_ratio"] == 0.82
    assert snapshot_call["last_checkpoint"] == WorkflowPhase.REVIEWING.value
    assert "Promote safe edit outputs" in snapshot_call["next_action"]

    assert any("fix loop を 1 回目として実行" in note for note in state.notes)
    assert any("fix proposal を生成した。" in note for note in state.notes)


def test_run_stops_after_failed_phase_and_skips_later_work(tmp_path: Path) -> None:
    orchestrator = make_orchestrator(tmp_path)
    orchestrator.requirements_agent = DummyAgent(
        "requirements",
        make_result(
            summary="requirements done",
            outputs={"normalized_requirements": {"objective": "Build workflow"}},
        ),
    )
    orchestrator.planning_agent = DummyAgent(
        "planner",
        make_failure(
            summary="planning failed",
            outputs={"open_questions": ["missing architecture choice"]},
        ),
    )
    orchestrator.documentation_agent = DummyAgent(
        "documentation",
        make_result(
            summary="documentation done",
            outputs={"documentation_bundle": {"design_doc": "doc text"}},
        ),
    )

    state = asyncio.run(orchestrator.run("Build a multi-agent workflow"))

    assert state.phase is WorkflowPhase.FAILED
    assert state.require_task("requirements_analysis").status is TaskStatus.COMPLETED
    assert state.require_task("planning").status is TaskStatus.FAILED
    assert state.require_task("documentation").status is TaskStatus.PENDING
    assert state.open_questions == ["missing architecture choice"]
    assert orchestrator.documentation_agent.calls == []
    assert orchestrator.runtime_support.rotate_calls == []
    assert orchestrator.edit_phase.calls == []
    assert orchestrator.artifact_writer.workflow_calls == []
    assert len(orchestrator.session_manager.snapshot_calls) == 0


def test_run_fix_loop_returns_failed_fix_result_without_reruns(tmp_path: Path) -> None:
    orchestrator = make_orchestrator(tmp_path)
    state = make_state()

    failed_fix_result = make_failure(
        summary="fix failed",
        outputs={"review": {"remaining": ["issue"]}},
    )
    rerun_calls: list[str] = []

    async def fake_fix_phase(state_arg: Any, **kwargs: Any) -> AgentResult:
        assert state_arg is state
        return failed_fix_result

    async def fake_test_execution(*args: Any, **kwargs: Any) -> AgentResult:
        rerun_calls.append("test_execution")
        return make_result()

    async def fake_review_phase(*args: Any, **kwargs: Any) -> AgentResult:
        rerun_calls.append("review")
        return make_result()

    orchestrator._run_fix_phase = fake_fix_phase
    orchestrator._run_test_execution_phase = fake_test_execution
    orchestrator._run_review_phase = fake_review_phase

    result = asyncio.run(
        orchestrator._run_fix_loop(
            state,
            requirements_result=make_result(outputs={"normalized_requirements": {}}),
            planning_result=make_result(outputs={"plan": {}}),
            documentation_result=make_result(outputs={"documentation_bundle": {}}),
            implementation_result=make_result(outputs={"implementation": {}}),
            test_design_result=make_result(outputs={"test_plan": {}}),
            test_execution_result=make_result(outputs={"test_results": {}}),
            review_result=make_result(outputs={"review": {"fix_loop_required": True}}),
        )
    )

    assert result is failed_fix_result
    assert rerun_calls == []


def test_apply_result_records_failure_classification_and_next_actions(
    tmp_path: Path,
) -> None:
    orchestrator = make_orchestrator(tmp_path)
    state = make_state()

    failed_result = make_failure(
        summary="planning failed",
        outputs={"open_questions": ["missing architecture choice"]},
        next_actions=[
            "Clarify the architecture decision",
            "Retry planning with the chosen direction",
        ],
        failure_category="design_inconsistency",
        failure_cause="architecture decision is still unresolved",
    )

    orchestrator._apply_result(
        state=state,
        task_id="planning",
        phase=WorkflowPhase.PLANNED,
        result=failed_result,
    )

    planning_task = state.require_task("planning")
    assert state.phase is WorkflowPhase.FAILED
    assert planning_task.status is TaskStatus.FAILED
    assert planning_task.outputs["failure_category"] == "design_inconsistency"
    assert (
        planning_task.outputs["failure_cause"]
        == "architecture decision is still unresolved"
    )
    assert planning_task.outputs["next_actions"] == [
        "Clarify the architecture decision",
        "Retry planning with the chosen direction",
    ]
    assert "failure_category=design_inconsistency" in planning_task.notes[-1]
    assert any(
        note
        == (
            "planning failed: category=design_inconsistency; "
            "cause=architecture decision is still unresolved"
        )
        for note in state.notes
    )
    assert any(
        note
        == "planning next actions: Clarify the architecture decision | Retry planning with the chosen direction"
        for note in state.notes
    )
    assert state.open_questions == ["missing architecture choice"]


def test_run_fix_loop_returns_failed_rerun_test_result(tmp_path: Path) -> None:
    orchestrator = make_orchestrator(tmp_path)
    state = make_state()

    failed_rerun_test_result = make_failure(
        summary="rerun tests failed",
        outputs={"test_results": {"status": "failed"}},
    )
    review_calls: list[str] = []

    async def fake_fix_phase(state_arg: Any, **kwargs: Any) -> AgentResult:
        assert state_arg is state
        return make_result(summary="fix ready")

    async def fake_test_execution(*args: Any, **kwargs: Any) -> AgentResult:
        return failed_rerun_test_result

    async def fake_review_phase(*args: Any, **kwargs: Any) -> AgentResult:
        review_calls.append("review")
        return make_result()

    orchestrator._run_fix_phase = fake_fix_phase
    orchestrator._run_test_execution_phase = fake_test_execution
    orchestrator._run_review_phase = fake_review_phase

    result = asyncio.run(
        orchestrator._run_fix_loop(
            state,
            requirements_result=make_result(outputs={"normalized_requirements": {}}),
            planning_result=make_result(outputs={"plan": {}}),
            documentation_result=make_result(outputs={"documentation_bundle": {}}),
            implementation_result=make_result(outputs={"implementation": {}}),
            test_design_result=make_result(outputs={"test_plan": {}}),
            test_execution_result=make_result(outputs={"test_results": {}}),
            review_result=make_result(outputs={"review": {"fix_loop_required": True}}),
        )
    )

    assert result is failed_rerun_test_result
    assert review_calls == []


def test_run_fix_loop_returns_failed_rerun_review_result(tmp_path: Path) -> None:
    orchestrator = make_orchestrator(tmp_path)
    state = make_state()

    failed_rerun_review_result = make_failure(
        summary="rerun review failed",
        outputs={"review": {"fix_loop_required": True}},
    )

    async def fake_fix_phase(state_arg: Any, **kwargs: Any) -> AgentResult:
        assert state_arg is state
        return make_result(summary="fix ready")

    async def fake_test_execution(*args: Any, **kwargs: Any) -> AgentResult:
        return make_result(summary="tests rerun")

    async def fake_review_phase(*args: Any, **kwargs: Any) -> AgentResult:
        return failed_rerun_review_result

    orchestrator._run_fix_phase = fake_fix_phase
    orchestrator._run_test_execution_phase = fake_test_execution
    orchestrator._run_review_phase = fake_review_phase

    result = asyncio.run(
        orchestrator._run_fix_loop(
            state,
            requirements_result=make_result(outputs={"normalized_requirements": {}}),
            planning_result=make_result(outputs={"plan": {}}),
            documentation_result=make_result(outputs={"documentation_bundle": {}}),
            implementation_result=make_result(outputs={"implementation": {}}),
            test_design_result=make_result(outputs={"test_plan": {}}),
            test_execution_result=make_result(outputs={"test_results": {}}),
            review_result=make_result(outputs={"review": {"fix_loop_required": True}}),
        )
    )

    assert result is failed_rerun_review_result


def test_run_fix_loop_records_escalation_note_when_rerun_test_execution_fails(
    tmp_path: Path,
) -> None:
    orchestrator = make_orchestrator(tmp_path)
    state = make_state()

    fix_result = make_result(
        summary="fix ready",
        outputs={"implementation": {"changes": ["patch"]}},
    )
    rerun_test_result = make_failure(
        summary="rerun tests failed",
        outputs={"test_results": {"status": "failed"}},
    )

    async def fake_fix_phase(state_arg: Any, **kwargs: Any) -> AgentResult:
        return fix_result

    async def fake_test_execution(
        state_arg: Any,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
    ) -> AgentResult:
        return rerun_test_result

    async def fake_review_phase(
        state_arg: Any,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        documentation_result: AgentResult,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
        test_execution_result: AgentResult,
    ) -> AgentResult:
        raise AssertionError("review rerun should not execute after failed rerun tests")

    orchestrator._run_fix_phase = fake_fix_phase
    orchestrator._run_test_execution_phase = fake_test_execution
    orchestrator._run_review_phase = fake_review_phase

    result = asyncio.run(
        orchestrator._run_fix_loop(
            state,
            requirements_result=make_result(
                outputs={"normalized_requirements": {"objective": "x"}}
            ),
            planning_result=make_result(outputs={"plan": {"steps": ["a"]}}),
            documentation_result=make_result(
                outputs={"documentation_bundle": {"doc": "x"}}
            ),
            implementation_result=make_result(
                outputs={"implementation": {"changes": ["base"]}}
            ),
            test_design_result=make_result(outputs={"test_plan": {"cases": ["c1"]}}),
            test_execution_result=make_result(
                outputs={"test_results": {"status": "failed"}}
            ),
            review_result=make_result(outputs={"review": {"fix_loop_required": True}}),
        )
    )

    assert result is rerun_test_result
    assert any(
        "fix loop を開始した。attempt=1/2" in note
        for note in state.require_task("implementation").notes
    )


def test_run_fix_loop_escalates_after_retry_limit(tmp_path: Path) -> None:
    orchestrator = make_orchestrator(tmp_path)
    state = make_state()
    state.retry_counters["fix_loop"] = 2

    async def fake_fix_phase(state_arg: Any, **kwargs: Any) -> AgentResult:
        raise AssertionError(
            "fix phase should not execute after retry limit escalation"
        )

    async def fake_test_execution(
        state_arg: Any,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
    ) -> AgentResult:
        raise AssertionError(
            "test execution rerun should not execute after retry limit escalation"
        )

    async def fake_review_phase(
        state_arg: Any,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        documentation_result: AgentResult,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
        test_execution_result: AgentResult,
    ) -> AgentResult:
        raise AssertionError(
            "review rerun should not execute after retry limit escalation"
        )

    orchestrator._run_fix_phase = fake_fix_phase
    orchestrator._run_test_execution_phase = fake_test_execution
    orchestrator._run_review_phase = fake_review_phase

    result = asyncio.run(
        orchestrator._run_fix_loop(
            state,
            requirements_result=make_result(
                outputs={"normalized_requirements": {"objective": "x"}}
            ),
            planning_result=make_result(outputs={"plan": {"steps": ["a"]}}),
            documentation_result=make_result(
                outputs={"documentation_bundle": {"doc": "x"}}
            ),
            implementation_result=make_result(
                outputs={"implementation": {"changes": ["base"]}}
            ),
            test_design_result=make_result(outputs={"test_plan": {"cases": ["c1"]}}),
            test_execution_result=make_result(
                outputs={"test_results": {"status": "failed"}}
            ),
            review_result=make_result(outputs={"review": {"fix_loop_required": True}}),
        )
    )

    assert result.is_success is False
    assert result.failure_category == "fix_loop_retry_limit"
    assert result.outputs["review"]["fix_loop_attempt"] == 3
    assert result.outputs["review"]["fix_loop_retry_limit"] == 2
    assert result.outputs["review"]["escalation_required"] is True
    assert result.next_actions == [
        "Escalate to a human reviewer",
        "Resolve the blocking review findings manually",
        "Re-run fix loop only after human guidance is recorded",
    ]
    assert state.phase is WorkflowPhase.NEEDS_HUMAN_INPUT
    assert state.retry_counters["fix_loop"] == 3
    assert any("retry limit" in risk for risk in state.risks)
    assert any("人手エスカレーション" in note for note in state.notes)
    assert state.require_task("review").status is TaskStatus.BLOCKED
    assert state.require_task("implementation").status is TaskStatus.BLOCKED
    assert any(
        "escalation" in note or "エスカレーション" in note for note in state.notes
    )


def test_run_fix_loop_uses_fix_outputs_for_repeated_rerun_inputs(
    tmp_path: Path,
) -> None:
    orchestrator = make_orchestrator(tmp_path)
    state = make_state()

    fix_result = make_result(
        summary="fix ready",
        outputs={
            "implementation": {"changes": ["patched-file"]},
            "fix_report": "# fix report",
        },
    )
    rerun_test_result = make_result(
        summary="tests rerun",
        outputs={"test_results": {"status": "passed"}},
    )
    rerun_review_result = make_result(
        summary="review rerun",
        outputs={"review": {"fix_loop_required": False}},
    )

    rerun_inputs: list[dict[str, Any]] = []

    async def fake_fix_phase(state_arg: Any, **kwargs: Any) -> AgentResult:
        return fix_result

    async def fake_test_execution(
        state_arg: Any,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
    ) -> AgentResult:
        rerun_inputs.append(
            {
                "state": state_arg,
                "implementation_result": implementation_result,
            }
        )
        return rerun_test_result

    async def fake_review_phase(
        state_arg: Any,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        documentation_result: AgentResult,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
        test_execution_result: AgentResult,
    ) -> AgentResult:
        assert implementation_result.outputs["implementation"] == {
            "changes": ["patched-file"]
        }
        return rerun_review_result

    orchestrator._run_fix_phase = fake_fix_phase
    orchestrator._run_test_execution_phase = fake_test_execution
    orchestrator._run_review_phase = fake_review_phase

    result = asyncio.run(
        orchestrator._run_fix_loop(
            state,
            requirements_result=make_result(
                outputs={"normalized_requirements": {"objective": "x"}}
            ),
            planning_result=make_result(outputs={"plan": {"steps": ["a"]}}),
            documentation_result=make_result(
                outputs={"documentation_bundle": {"doc": "x"}}
            ),
            implementation_result=make_result(
                outputs={"implementation": {"changes": ["base"]}}
            ),
            test_design_result=make_result(outputs={"test_plan": {"cases": ["c1"]}}),
            test_execution_result=make_result(
                outputs={"test_results": {"status": "failed"}}
            ),
            review_result=make_result(outputs={"review": {"fix_loop_required": True}}),
        )
    )

    assert result is fix_result
    assert len(rerun_inputs) == 1
    assert rerun_inputs[0]["state"] is state
    assert rerun_inputs[0]["implementation_result"].outputs["implementation"] == {
        "changes": ["patched-file"]
    }
    assert rerun_inputs[0]["implementation_result"].outputs["fix_report"] == (
        "# fix report"
    )


def test_run_fix_loop_records_escalation_note_when_rerun_review_fails(
    tmp_path: Path,
) -> None:
    orchestrator = make_orchestrator(tmp_path)
    state = make_state()

    fix_result = make_result(
        summary="fix ready",
        outputs={"implementation": {"changes": ["patch"]}},
    )
    rerun_test_result = make_result(
        summary="tests rerun",
        outputs={"test_results": {"status": "passed"}},
    )
    rerun_review_result = make_failure(
        summary="rerun review failed",
        outputs={"review": {"fix_loop_required": True}},
    )

    async def fake_fix_phase(state_arg: Any, **kwargs: Any) -> AgentResult:
        return fix_result

    async def fake_test_execution(
        state_arg: Any,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
    ) -> AgentResult:
        return rerun_test_result

    async def fake_review_phase(
        state_arg: Any,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        documentation_result: AgentResult,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
        test_execution_result: AgentResult,
    ) -> AgentResult:
        return rerun_review_result

    orchestrator._run_fix_phase = fake_fix_phase
    orchestrator._run_test_execution_phase = fake_test_execution
    orchestrator._run_review_phase = fake_review_phase

    result = asyncio.run(
        orchestrator._run_fix_loop(
            state,
            requirements_result=make_result(
                outputs={"normalized_requirements": {"objective": "x"}}
            ),
            planning_result=make_result(outputs={"plan": {"steps": ["a"]}}),
            documentation_result=make_result(
                outputs={"documentation_bundle": {"doc": "x"}}
            ),
            implementation_result=make_result(
                outputs={"implementation": {"changes": ["base"]}}
            ),
            test_design_result=make_result(outputs={"test_plan": {"cases": ["c1"]}}),
            test_execution_result=make_result(
                outputs={"test_results": {"status": "failed"}}
            ),
            review_result=make_result(outputs={"review": {"fix_loop_required": True}}),
        )
    )

    assert result is rerun_review_result
    assert any(
        "fix loop を開始した。" in note
        for note in state.require_task("implementation").notes
    )
    assert any(
        "escalation" in note or "エスカレーション" in note for note in state.notes
    )


def test_run_fix_phase_persists_fix_report_and_note(tmp_path: Path) -> None:
    orchestrator = make_orchestrator(tmp_path)
    state = make_state()
    orchestrator.fixer_agent = DummyAgent(
        "fixer",
        make_result(
            summary="fix prepared",
            outputs={
                "fix_report": "# fix report",
                "implementation": {"changes": ["x"]},
            },
        ),
    )

    requirements_result = make_result(
        outputs={"normalized_requirements": {"objective": "x"}}
    )
    planning_result = make_result(outputs={"plan": {"steps": ["a"]}})
    documentation_result = make_result(
        outputs={"documentation_bundle": {"design_doc": "doc"}}
    )
    implementation_result = make_result(
        outputs={"implementation": {"changes": ["base"]}}
    )
    test_design_result = make_result(outputs={"test_plan": {"cases": ["c1"]}})
    test_execution_result = make_result(outputs={"test_results": {"status": "failed"}})
    review_result = make_result(outputs={"review": {"fix_loop_required": True}})

    result = asyncio.run(
        orchestrator._run_fix_phase(
            state,
            requirements_result=requirements_result,
            planning_result=planning_result,
            documentation_result=documentation_result,
            implementation_result=implementation_result,
            test_design_result=test_design_result,
            test_execution_result=test_execution_result,
            review_result=review_result,
        )
    )

    assert result.is_success is True
    assert len(orchestrator.artifact_writer.text_calls) == 1
    assert orchestrator.artifact_writer.text_calls[0]["output_key"] == "fix_report"
    assert orchestrator.artifact_writer.text_calls[0]["target_name"] == "fix-report.md"
    assert any("fix proposal を生成した。" in note for note in state.notes)

    task = orchestrator.fixer_agent.calls[0]
    assert task.name == "implementation"
    assert task.inputs["normalized_requirements"] == {"objective": "x"}
    assert task.inputs["plan"] == {"steps": ["a"]}
    assert task.inputs["documentation_bundle"] == {"design_doc": "doc"}
    assert task.inputs["implementation"] == {"changes": ["base"]}
    assert task.inputs["test_plan"] == {"cases": ["c1"]}
    assert task.inputs["test_results"] == {"status": "failed"}
    assert task.inputs["review"] == {"fix_loop_required": True}
    assert task.inputs["copilot_response"] == "copilot draft"


def test_run_fix_phase_does_not_persist_report_on_failure(tmp_path: Path) -> None:
    orchestrator = make_orchestrator(tmp_path)
    state = make_state()
    orchestrator.fixer_agent = DummyAgent(
        "fixer",
        make_failure(summary="fix failed", outputs={"fix_report": "# failed"}),
    )

    result = asyncio.run(
        orchestrator._run_fix_phase(
            state,
            requirements_result=make_result(outputs={"normalized_requirements": {}}),
            planning_result=make_result(outputs={"plan": {}}),
            documentation_result=make_result(outputs={"documentation_bundle": {}}),
            implementation_result=make_result(outputs={"implementation": {}}),
            test_design_result=make_result(outputs={"test_plan": {}}),
            test_execution_result=make_result(outputs={"test_results": {}}),
            review_result=make_result(outputs={"review": {"fix_loop_required": True}}),
        )
    )

    assert result.is_success is False
    assert orchestrator.artifact_writer.text_calls == []
    assert not any("fix proposal を生成した。" in note for note in state.notes)


def test_run_cli_prints_summary_and_rotation_reason(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    state = make_state()
    state.set_phase(WorkflowPhase.REVIEWING)
    state.model = "gpt-5.4-mini"
    state.add_artifact("artifacts/review-report.md")
    state.update_task_status("requirements_analysis", TaskStatus.COMPLETED)
    state.update_task_status("planning", TaskStatus.FAILED)

    created: list[Any] = []

    class FakeOrchestrator:
        def __init__(
            self,
            *,
            model: str,
            artifacts_dir: Path,
            docs_dir: Path,
            routing_mode: RoutingMode,
        ) -> None:
            self.model = model
            self.artifacts_dir = artifacts_dir
            self.docs_dir = docs_dir
            self.routing_mode = routing_mode
            self.session_manager = DummySessionManager(should_rotate=True)
            self.run_calls: list[dict[str, Any]] = []
            created.append(self)

        async def run(
            self,
            requirement: str,
            *,
            token_usage_ratio: float = 0.35,
        ) -> Any:
            self.run_calls.append(
                {
                    "requirement": requirement,
                    "token_usage_ratio": token_usage_ratio,
                }
            )
            return state

    monkeypatch.setattr(main_module, "SkeletonOrchestrator", FakeOrchestrator)

    exit_code = asyncio.run(
        _run_cli(
            requirement="Build a multi-agent workflow",
            model="gpt-5.4",
            artifacts_dir=str(tmp_path / "artifacts"),
            docs_dir=str(tmp_path / "docs"),
            token_usage_ratio=0.72,
            routing_mode=RoutingMode.COST_SAVER.value,
        )
    )

    captured = capsys.readouterr().out

    assert exit_code == 0
    assert len(created) == 1
    fake = created[0]
    assert fake.run_calls == [
        {
            "requirement": "Build a multi-agent workflow",
            "token_usage_ratio": 0.72,
        }
    ]
    assert fake.session_manager.should_rotate_calls == [
        {
            "token_usage_ratio": 0.72,
            "current_session_id": state.session_id,
        }
    ]
    assert "workflow_id: wf-test-main" in captured
    assert "phase: reviewing" in captured
    assert "model: gpt-5.4-mini" in captured
    assert "routing_mode: cost_saver" in captured
    assert "task_summary:" in captured
    assert "  - requirements_analysis: completed" in captured
    assert "  - planning: failed" in captured
    assert "session_id: sess-main" in captured
    assert "rotate_session: True" in captured
    assert "rotation_reason: threshold exceeded" in captured
    assert "artifacts:" in captured
    assert "  - artifacts/review-report.md" in captured


def test_run_cli_omits_rotation_reason_when_empty(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    state = make_state()

    class FakeOrchestrator:
        def __init__(
            self,
            *,
            model: str,
            artifacts_dir: Path,
            docs_dir: Path,
            routing_mode: RoutingMode,
        ) -> None:
            self.session_manager = DummySessionManager(should_rotate=False)

        async def run(
            self,
            requirement: str,
            *,
            token_usage_ratio: float = 0.35,
        ) -> Any:
            return state

    monkeypatch.setattr(main_module, "SkeletonOrchestrator", FakeOrchestrator)

    exit_code = asyncio.run(
        _run_cli(
            requirement="Build a multi-agent workflow",
            model="gpt-5.4",
            artifacts_dir=str(tmp_path / "artifacts"),
            docs_dir=str(tmp_path / "docs"),
            token_usage_ratio=0.2,
            routing_mode=RoutingMode.BALANCED.value,
        )
    )

    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "rotate_session: False" in captured
    assert "rotation_reason:" not in captured


def test_run_cli_e2e_style_flow_surfaces_multi_phase_artifacts_and_summary(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    state = make_state()
    state.set_phase(WorkflowPhase.COMPLETED)
    state.model = "gpt-5.4-mini"
    state.set_session("sess-e2e", parent_session_id="sess-parent")
    state.update_task_status("requirements_analysis", TaskStatus.COMPLETED)
    state.update_task_status("planning", TaskStatus.COMPLETED)
    state.update_task_status("documentation", TaskStatus.COMPLETED)
    state.update_task_status("implementation", TaskStatus.COMPLETED)
    state.update_task_status("test_design", TaskStatus.COMPLETED)
    state.update_task_status("test_execution", TaskStatus.COMPLETED)
    state.update_task_status("review", TaskStatus.COMPLETED)
    state.update_task_status("finalization", TaskStatus.BLOCKED)
    state.add_artifact("docs/design.md")
    state.add_artifact("docs/runbook.md")
    state.add_artifact("docs/test-plan.md")
    state.add_artifact("docs/test-results.md")
    state.add_artifact("docs/review-report.md")
    state.add_artifact("docs/fix-report.md")
    state.add_artifact("artifacts/summaries/wf-test-main/run-summary.json")
    state.add_artifact("docs/final-summary.md")

    created: list[Any] = []

    class FakeOrchestrator:
        def __init__(
            self,
            *,
            model: str,
            artifacts_dir: Path,
            docs_dir: Path,
            routing_mode: RoutingMode,
        ) -> None:
            self.model = model
            self.artifacts_dir = artifacts_dir
            self.docs_dir = docs_dir
            self.routing_mode = routing_mode
            self.session_manager = DummySessionManager(should_rotate=True)
            self.run_calls: list[dict[str, Any]] = []
            created.append(self)

        async def run(
            self,
            requirement: str,
            *,
            token_usage_ratio: float = 0.35,
        ) -> Any:
            self.run_calls.append(
                {
                    "requirement": requirement,
                    "token_usage_ratio": token_usage_ratio,
                }
            )
            return state

    monkeypatch.setattr(main_module, "SkeletonOrchestrator", FakeOrchestrator)

    exit_code = asyncio.run(
        _run_cli(
            requirement="Build a multi-agent workflow",
            model="gpt-5.4",
            artifacts_dir=str(tmp_path / "artifacts"),
            docs_dir=str(tmp_path / "docs"),
            token_usage_ratio=0.88,
            routing_mode=RoutingMode.BALANCED.value,
        )
    )

    captured = capsys.readouterr().out

    assert exit_code == 0
    assert len(created) == 1
    fake = created[0]
    assert fake.run_calls == [
        {
            "requirement": "Build a multi-agent workflow",
            "token_usage_ratio": 0.88,
        }
    ]
    assert fake.session_manager.should_rotate_calls == [
        {
            "token_usage_ratio": 0.88,
            "current_session_id": "sess-e2e",
        }
    ]
    assert "workflow_id: wf-test-main" in captured
    assert "phase: completed" in captured
    assert "model: gpt-5.4-mini" in captured
    assert "routing_mode: balanced" in captured
    assert "task_summary:" in captured
    assert "  - requirements_analysis: completed" in captured
    assert "  - documentation: completed" in captured
    assert "  - implementation: completed" in captured
    assert "  - test_design: completed" in captured
    assert "  - test_execution: completed" in captured
    assert "  - review: completed" in captured
    assert "  - finalization: blocked" in captured
    assert "session_id: sess-e2e" in captured
    assert "rotate_session: True" in captured
    assert "rotation_reason: threshold exceeded" in captured
    assert "artifacts:" in captured
    assert "  - docs/design.md" in captured
    assert "  - docs/runbook.md" in captured
    assert "  - docs/test-plan.md" in captured
    assert "  - docs/test-results.md" in captured
    assert "  - docs/review-report.md" in captured
    assert "  - docs/fix-report.md" in captured
    assert "  - artifacts/summaries/wf-test-main/run-summary.json" in captured
    assert "  - docs/final-summary.md" in captured


def test_run_cli_e2e_style_flow_handles_long_requirement_input(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    long_requirement = "Build a multi-agent workflow with durable context. " * 80

    state = make_state()
    state.set_phase(WorkflowPhase.COMPLETED)
    state.model = "gpt-5.4-mini"
    state.set_session("sess-long-input", parent_session_id="sess-parent")
    state.update_task_status("requirements_analysis", TaskStatus.COMPLETED)
    state.update_task_status("planning", TaskStatus.COMPLETED)
    state.update_task_status("documentation", TaskStatus.COMPLETED)
    state.update_task_status("implementation", TaskStatus.COMPLETED)
    state.update_task_status("test_design", TaskStatus.COMPLETED)
    state.update_task_status("test_execution", TaskStatus.COMPLETED)
    state.update_task_status("review", TaskStatus.COMPLETED)
    state.add_artifact("docs/design.md")
    state.add_artifact("artifacts/summaries/wf-test-main/run-summary.json")

    created: list[Any] = []

    class FakeOrchestrator:
        def __init__(
            self,
            *,
            model: str,
            artifacts_dir: Path,
            docs_dir: Path,
            routing_mode: RoutingMode,
        ) -> None:
            self.model = model
            self.artifacts_dir = artifacts_dir
            self.docs_dir = docs_dir
            self.routing_mode = routing_mode
            self.session_manager = DummySessionManager(should_rotate=True)
            self.run_calls: list[dict[str, Any]] = []
            created.append(self)

        async def run(
            self,
            requirement: str,
            *,
            token_usage_ratio: float = 0.35,
        ) -> Any:
            self.run_calls.append(
                {
                    "requirement": requirement,
                    "token_usage_ratio": token_usage_ratio,
                }
            )
            return state

    monkeypatch.setattr(main_module, "SkeletonOrchestrator", FakeOrchestrator)

    exit_code = asyncio.run(
        _run_cli(
            requirement=long_requirement,
            model="gpt-5.4",
            artifacts_dir=str(tmp_path / "artifacts"),
            docs_dir=str(tmp_path / "docs"),
            token_usage_ratio=0.9,
            routing_mode=RoutingMode.QUALITY.value,
        )
    )

    captured = capsys.readouterr().out

    assert exit_code == 0
    assert len(created) == 1
    fake = created[0]
    assert fake.run_calls == [
        {
            "requirement": long_requirement,
            "token_usage_ratio": 0.9,
        }
    ]
    assert fake.session_manager.should_rotate_calls == [
        {
            "token_usage_ratio": 0.9,
            "current_session_id": "sess-long-input",
        }
    ]
    assert "workflow_id: wf-test-main" in captured
    assert "phase: completed" in captured
    assert "routing_mode: quality" in captured
    assert "rotate_session: True" in captured
    assert "rotation_reason: threshold exceeded" in captured
    assert "  - docs/design.md" in captured
    assert "  - artifacts/summaries/wf-test-main/run-summary.json" in captured


def test_main_parses_args_and_runs_cli(monkeypatch: Any) -> None:
    parser_args = SimpleNamespace(
        requirement="Ship feature",
        model="gpt-5.4-mini",
        artifacts_dir="custom-artifacts",
        docs_dir="custom-docs",
        token_usage_ratio=0.44,
        routing_mode=RoutingMode.BALANCED.value,
    )
    run_cli_calls: list[dict[str, Any]] = []

    class FakeParser:
        def parse_args(self) -> Any:
            return parser_args

    async def fake_run_cli(**kwargs: Any) -> int:
        run_cli_calls.append(kwargs)
        return 7

    monkeypatch.setattr(main_module, "build_parser", lambda: FakeParser())
    monkeypatch.setattr(main_module, "_run_cli", fake_run_cli)
    original_asyncio_run = asyncio.run
    monkeypatch.setattr(
        main_module.asyncio, "run", lambda coro: original_asyncio_run(coro)
    )

    exit_code = main()

    assert exit_code == 7
    assert run_cli_calls == [
        {
            "requirement": "Ship feature",
            "model": "gpt-5.4-mini",
            "artifacts_dir": "custom-artifacts",
            "docs_dir": "custom-docs",
            "token_usage_ratio": 0.44,
            "routing_mode": RoutingMode.BALANCED.value,
        }
    ]
