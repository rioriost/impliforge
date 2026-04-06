"""CLI entrypoint wired to separated agents, model routing, session persistence,
documentation generation, implementation proposal flow, test planning/execution,
review reporting, and a safe edit phase.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from devagents.agents.base import AgentResult, AgentTask
from devagents.agents.documentation import DocumentationAgent
from devagents.agents.fixer import FixerAgent
from devagents.agents.implementation import ImplementationAgent
from devagents.agents.planner import PlanningAgent
from devagents.agents.requirements import RequirementsAgent
from devagents.agents.reviewer import ReviewAgent
from devagents.agents.test_design import TestDesignAgent
from devagents.agents.test_execution import TestExecutionAgent
from devagents.models.routing import ModelRouter, RoutingMode
from devagents.orchestration.artifact_writer import WorkflowArtifactWriter
from devagents.orchestration.edit_phase import EditPhaseOrchestrator
from devagents.orchestration.session_manager import SessionManager
from devagents.orchestration.state_store import StateStore
from devagents.orchestration.workflow import (
    TaskStatus,
    WorkflowPhase,
    WorkflowState,
    create_workflow_state,
)
from devagents.runtime.code_editing import (
    CodeEditKind,
    CodeEditRequest,
    StructuredCodeEditor,
    approve_src_devagents_only,
)
from devagents.runtime.copilot_client import (
    CopilotClient,
    CopilotRequest,
    CopilotTaskType,
)
from devagents.runtime.editor import (
    EditOperationKind,
    EditorPolicy,
    EditRequest,
    SafeEditor,
    approve_docs_and_artifacts_only,
)

ARTIFACTS_DIR = Path("artifacts")
DOCS_DIR = Path("docs")
DEFAULT_MODEL = "gpt-5.4"


class SkeletonOrchestrator:
    """Small orchestrator connected to separated agents and model routing."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        artifacts_dir: Path = ARTIFACTS_DIR,
        docs_dir: Path = DOCS_DIR,
        routing_mode: RoutingMode = RoutingMode.BALANCED,
    ) -> None:
        self.model = model
        self.artifacts_dir = artifacts_dir
        self.docs_dir = docs_dir
        self.routing_mode = routing_mode

        self.requirements_agent = RequirementsAgent()
        self.planning_agent = PlanningAgent()
        self.documentation_agent = DocumentationAgent()
        self.implementation_agent = ImplementationAgent()
        self.test_design_agent = TestDesignAgent()
        self.test_execution_agent = TestExecutionAgent()
        self.review_agent = ReviewAgent()
        self.fixer_agent = FixerAgent()

        self.state_store = StateStore(root_dir=self.artifacts_dir)
        self.session_manager = SessionManager()
        self.artifact_writer = WorkflowArtifactWriter(
            docs_dir=self.docs_dir,
            state_store=self.state_store,
            session_manager=self.session_manager,
        )
        self.edit_phase = EditPhaseOrchestrator(
            safe_editor=self.safe_editor,
            code_editor=self.code_editor,
            artifact_writer=self.artifact_writer,
        )
        self.model_router = ModelRouter(default_model=model)
        self.copilot_client = CopilotClient()
        self.safe_editor = SafeEditor(
            workspace_root=Path.cwd(),
            policy=EditorPolicy(
                allowed_roots=("docs", "artifacts", "src"),
                protected_roots=(".git", ".venv"),
                require_approval_for_delete=True,
                require_approval_for_overwrite_outside_docs=True,
                allow_absolute_paths=False,
            ),
            approval_hook=self._approval_hook,
        )
        self.code_editor = StructuredCodeEditor(
            workspace_root=Path.cwd(),
            approval_hook=approve_src_devagents_only,
        )

    async def run(
        self,
        requirement: str,
        *,
        token_usage_ratio: float = 0.35,
    ) -> WorkflowState:
        state = create_workflow_state(
            workflow_id=self._build_workflow_id(),
            requirement=requirement,
            model=self.model,
        )
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.session_manager.start_session(state)

        requirements_result = await self._run_requirements_phase(state, requirement)
        if not requirements_result.is_success:
            return state

        planning_result = await self._run_planning_phase(state, requirements_result)
        if not planning_result.is_success:
            return state

        documentation_result = await self._run_documentation_phase(
            state,
            requirements_result,
            planning_result,
        )
        if not documentation_result.is_success:
            return state

        implementation_result = await self._run_implementation_phase(
            state,
            requirements_result,
            planning_result,
            documentation_result,
        )
        if not implementation_result.is_success:
            return state

        test_design_result = await self._run_test_design_phase(
            state,
            requirements_result,
            planning_result,
            documentation_result,
            implementation_result,
        )
        if not test_design_result.is_success:
            return state

        test_execution_result = await self._run_test_execution_phase(
            state,
            requirements_result,
            planning_result,
            implementation_result,
            test_design_result,
        )
        if not test_execution_result.is_success:
            return state

        self._rotate_session_if_needed(
            state,
            token_usage_ratio=token_usage_ratio,
            next_action="Resume review after test_execution",
            last_checkpoint=WorkflowPhase.TESTING.value,
            persistent_context={
                "workflow_id": state.workflow_id,
                "phase": state.phase.value,
                "requirement": state.requirement,
                "normalized_requirements": requirements_result.outputs.get(
                    "normalized_requirements",
                    {},
                ),
                "plan": planning_result.outputs.get("plan", {}),
                "documentation_bundle": documentation_result.outputs.get(
                    "documentation_bundle",
                    {},
                ),
                "implementation": implementation_result.outputs.get(
                    "implementation",
                    {},
                ),
                "test_plan": test_design_result.outputs.get("test_plan", {}),
                "test_results": test_execution_result.outputs.get("test_results", {}),
            },
        )

        review_result = await self._run_review_phase(
            state,
            requirements_result,
            planning_result,
            documentation_result,
            implementation_result,
            test_design_result,
            test_execution_result,
        )
        if not review_result.is_success:
            return state

        fix_result = await self._run_fix_loop(
            state,
            requirements_result=requirements_result,
            planning_result=planning_result,
            documentation_result=documentation_result,
            implementation_result=implementation_result,
            test_design_result=test_design_result,
            test_execution_result=test_execution_result,
            review_result=review_result,
        )
        if fix_result is not None and not fix_result.is_success:
            return state

        self.edit_phase.apply_safe_edit_phase(
            state=state,
            requirement=requirement,
            requirements_result=requirements_result,
            planning_result=planning_result,
            documentation_result=documentation_result,
            implementation_result=implementation_result,
            test_design_result=test_design_result,
            test_execution_result=test_execution_result,
            review_result=review_result,
            fix_result=fix_result,
        )

        snapshot = self.session_manager.snapshot_context(
            state,
            token_usage_ratio=token_usage_ratio,
            next_action="Promote safe edit outputs into concrete code generation and session resume flow",
            last_checkpoint=state.phase.value,
        )

        self.artifact_writer.write_workflow_artifacts(
            state=state,
            requirement=requirement,
            requirements_result=requirements_result,
            planning_result=planning_result,
            documentation_result=documentation_result,
            implementation_result=implementation_result,
            test_design_result=test_design_result,
            test_execution_result=test_execution_result,
            review_result=review_result,
            fix_result=fix_result,
            session_snapshot=snapshot,
        )
        state.set_phase(WorkflowPhase.COMPLETED)
        state.add_note(
            "テスト設計・実行・レビュー・fix loop・safe edit phase を含む実行フローが完了した。"
        )
        return state

    async def _run_requirements_phase(
        self,
        state: WorkflowState,
        requirement: str,
    ) -> AgentResult:
        return await self._execute_phase(
            state=state,
            task_id="requirements_analysis",
            agent=self.requirements_agent,
            difficulty=4,
            phase=WorkflowPhase.REQUIREMENTS_ANALYZED,
            task_type=CopilotTaskType.REQUIREMENTS,
            prompt=requirement,
            system_prompt=(
                "Analyze the requirement, identify constraints, acceptance criteria, "
                "and open questions for a multi-agent implementation workflow."
            ),
            estimated_input_tokens=len(requirement),
            persistent_context={
                "workflow_id": state.workflow_id,
                "phase": state.phase.value,
                "requirement": state.requirement,
            },
            build_inputs=lambda _routing_decision, copilot_response: {
                "requirement": requirement,
                "copilot_response": copilot_response.content,
            },
        )

    async def _run_planning_phase(
        self,
        state: WorkflowState,
        requirements_result: AgentResult,
    ) -> AgentResult:
        normalized_requirements = requirements_result.outputs.get(
            "normalized_requirements",
            {},
        )
        return await self._execute_phase(
            state=state,
            task_id="planning",
            agent=self.planning_agent,
            difficulty=4,
            phase=WorkflowPhase.PLANNED,
            task_type=CopilotTaskType.PLANNING,
            prompt=str(normalized_requirements),
            system_prompt=(
                "Create an implementation plan, task breakdown, and next actions "
                "for the provided normalized requirements."
            ),
            estimated_input_tokens=len(str(normalized_requirements)),
            persistent_context={
                "workflow_id": state.workflow_id,
                "phase": state.phase.value,
                "requirement": state.requirement,
                "normalized_requirements": normalized_requirements,
            },
            build_inputs=lambda _routing_decision, copilot_response: {
                "normalized_requirements": normalized_requirements,
                "copilot_response": copilot_response.content,
            },
        )

    async def _run_documentation_phase(
        self,
        state: WorkflowState,
        requirements_result: AgentResult,
        planning_result: AgentResult,
    ) -> AgentResult:
        normalized_requirements = requirements_result.outputs.get(
            "normalized_requirements",
            {},
        )
        plan = planning_result.outputs.get("plan", {})
        result = await self._execute_phase(
            state=state,
            task_id="documentation",
            agent=self.documentation_agent,
            difficulty=3,
            phase=WorkflowPhase.DESIGN_GENERATED,
            task_type=CopilotTaskType.DOCUMENTATION,
            prompt=f"{normalized_requirements}\n\n{plan}",
            system_prompt=(
                "Generate a concise design document and runbook draft for the "
                "provided workflow requirements and implementation plan."
            ),
            estimated_input_tokens=len(str(normalized_requirements)) + len(str(plan)),
            persistent_context={
                "workflow_id": state.workflow_id,
                "phase": state.phase.value,
                "requirement": state.requirement,
                "normalized_requirements": normalized_requirements,
                "plan": plan,
            },
            build_inputs=lambda _routing_decision, copilot_response: {
                "normalized_requirements": normalized_requirements,
                "plan": plan,
                "copilot_response": copilot_response.content,
            },
        )

        if result.is_success:
            self.artifact_writer.persist_documentation_outputs(
                state=state,
                result=result,
            )
        return result

    async def _run_implementation_phase(
        self,
        state: WorkflowState,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        documentation_result: AgentResult,
    ) -> AgentResult:
        normalized_requirements = requirements_result.outputs.get(
            "normalized_requirements",
            {},
        )
        plan = planning_result.outputs.get("plan", {})
        documentation_bundle = documentation_result.outputs.get(
            "documentation_bundle",
            {},
        )
        return await self._execute_phase(
            state=state,
            task_id="implementation",
            agent=self.implementation_agent,
            difficulty=4,
            phase=WorkflowPhase.IMPLEMENTING,
            task_type=CopilotTaskType.IMPLEMENTATION,
            prompt=f"{normalized_requirements}\n\n{plan}\n\n{documentation_bundle}",
            system_prompt=(
                "Generate an implementation proposal with concrete change slices, "
                "target modules, and next actions for the provided workflow context."
            ),
            estimated_input_tokens=(
                len(str(normalized_requirements))
                + len(str(plan))
                + len(str(documentation_bundle))
            ),
            persistent_context={
                "workflow_id": state.workflow_id,
                "phase": state.phase.value,
                "requirement": state.requirement,
                "normalized_requirements": normalized_requirements,
                "plan": plan,
                "documentation_bundle": documentation_bundle,
            },
            build_inputs=lambda _routing_decision, copilot_response: {
                "normalized_requirements": normalized_requirements,
                "plan": plan,
                "documentation_bundle": documentation_bundle,
                "copilot_response": copilot_response.content,
            },
        )

    async def _run_test_design_phase(
        self,
        state: WorkflowState,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        documentation_result: AgentResult,
        implementation_result: AgentResult,
    ) -> AgentResult:
        normalized_requirements = requirements_result.outputs.get(
            "normalized_requirements",
            {},
        )
        plan = planning_result.outputs.get("plan", {})
        documentation_bundle = documentation_result.outputs.get(
            "documentation_bundle",
            {},
        )
        implementation = implementation_result.outputs.get("implementation", {})
        result = await self._execute_phase(
            state=state,
            task_id="test_design",
            agent=self.test_design_agent,
            difficulty=3,
            phase=WorkflowPhase.TESTING,
            task_type=CopilotTaskType.TEST_DESIGN,
            prompt=(
                f"{normalized_requirements}\n\n{plan}\n\n"
                f"{documentation_bundle}\n\n{implementation}"
            ),
            system_prompt=(
                "Generate a focused test plan with validation scenarios, test levels, "
                "and acceptance criteria coverage for the provided workflow context."
            ),
            estimated_input_tokens=(
                len(str(normalized_requirements))
                + len(str(plan))
                + len(str(documentation_bundle))
                + len(str(implementation))
            ),
            persistent_context={
                "workflow_id": state.workflow_id,
                "phase": state.phase.value,
                "requirement": state.requirement,
                "normalized_requirements": normalized_requirements,
                "plan": plan,
                "documentation_bundle": documentation_bundle,
                "implementation": implementation,
            },
            build_inputs=lambda _routing_decision, copilot_response: {
                "normalized_requirements": normalized_requirements,
                "plan": plan,
                "documentation_bundle": documentation_bundle,
                "implementation": implementation,
                "copilot_response": copilot_response.content,
            },
        )

        if result.is_success:
            self.artifact_writer.persist_text_output(
                state=state,
                result=result,
                output_key="test_plan_document",
                target_name="test-plan.md",
            )
        return result

    async def _run_test_execution_phase(
        self,
        state: WorkflowState,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
    ) -> AgentResult:
        normalized_requirements = requirements_result.outputs.get(
            "normalized_requirements",
            {},
        )
        plan = planning_result.outputs.get("plan", {})
        implementation = implementation_result.outputs.get("implementation", {})
        test_plan = test_design_result.outputs.get("test_plan", {})
        result = await self._execute_phase(
            state=state,
            task_id="test_execution",
            agent=self.test_execution_agent,
            difficulty=3,
            phase=WorkflowPhase.TESTING,
            task_type=CopilotTaskType.TEST_EXECUTION,
            prompt=f"{normalized_requirements}\n\n{plan}\n\n{implementation}\n\n{test_plan}",
            system_prompt=(
                "Generate a concise test execution report, including executed checks, "
                "provisional status, and unresolved validation concerns."
            ),
            estimated_input_tokens=(
                len(str(normalized_requirements))
                + len(str(plan))
                + len(str(implementation))
                + len(str(test_plan))
            ),
            persistent_context={
                "workflow_id": state.workflow_id,
                "phase": state.phase.value,
                "requirement": state.requirement,
                "normalized_requirements": normalized_requirements,
                "plan": plan,
                "implementation": implementation,
                "test_plan": test_plan,
            },
            build_inputs=lambda _routing_decision, copilot_response: {
                "normalized_requirements": normalized_requirements,
                "plan": plan,
                "implementation": implementation,
                "test_plan": test_plan,
                "copilot_response": copilot_response.content,
            },
        )

        if result.is_success:
            self.artifact_writer.persist_text_output(
                state=state,
                result=result,
                output_key="test_results_document",
                target_name="test-results.md",
            )
        return result

    async def _run_review_phase(
        self,
        state: WorkflowState,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        documentation_result: AgentResult,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
        test_execution_result: AgentResult,
    ) -> AgentResult:
        normalized_requirements = requirements_result.outputs.get(
            "normalized_requirements",
            {},
        )
        plan = planning_result.outputs.get("plan", {})
        documentation_bundle = documentation_result.outputs.get(
            "documentation_bundle",
            {},
        )
        implementation = implementation_result.outputs.get("implementation", {})
        test_plan = test_design_result.outputs.get("test_plan", {})
        test_results = test_execution_result.outputs.get("test_results", {})
        result = await self._execute_phase(
            state=state,
            task_id="review",
            agent=self.review_agent,
            difficulty=4,
            phase=WorkflowPhase.REVIEWING,
            task_type=CopilotTaskType.REVIEW,
            prompt=(
                f"{normalized_requirements}\n\n{plan}\n\n{documentation_bundle}\n\n"
                f"{implementation}\n\n{test_plan}\n\n{test_results}"
            ),
            system_prompt=(
                "Review the generated workflow outputs, identify unresolved issues, "
                "and produce a concise review report with recommendations."
            ),
            estimated_input_tokens=(
                len(str(normalized_requirements))
                + len(str(plan))
                + len(str(documentation_bundle))
                + len(str(implementation))
                + len(str(test_plan))
                + len(str(test_results))
            ),
            persistent_context={
                "workflow_id": state.workflow_id,
                "phase": state.phase.value,
                "requirement": state.requirement,
                "normalized_requirements": normalized_requirements,
                "plan": plan,
                "documentation_bundle": documentation_bundle,
                "implementation": implementation,
                "test_plan": test_plan,
                "test_results": test_results,
            },
            build_inputs=lambda _routing_decision, copilot_response: {
                "normalized_requirements": normalized_requirements,
                "plan": plan,
                "documentation_bundle": documentation_bundle,
                "implementation": implementation,
                "test_plan": test_plan,
                "test_results": test_results,
                "copilot_response": copilot_response.content,
            },
        )

        if result.is_success:
            self.artifact_writer.persist_text_output(
                state=state,
                result=result,
                output_key="review_report",
                target_name="review-report.md",
            )
        return result

    async def _run_fix_loop(
        self,
        state: WorkflowState,
        *,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        documentation_result: AgentResult,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
        test_execution_result: AgentResult,
        review_result: AgentResult,
    ) -> AgentResult | None:
        review = review_result.outputs.get("review", {})
        if not isinstance(review, dict):
            return None

        fix_loop_required = bool(review.get("fix_loop_required"))
        if not fix_loop_required:
            state.add_note("review 結果に blocking issue がないため fix loop は不要。")
            return None

        task = state.require_task("implementation")
        task.add_note("fix loop を開始した。")

        fix_result = await self._run_fix_phase(
            state,
            requirements_result=requirements_result,
            planning_result=planning_result,
            documentation_result=documentation_result,
            implementation_result=implementation_result,
            test_design_result=test_design_result,
            test_execution_result=test_execution_result,
            review_result=review_result,
        )
        if not fix_result.is_success:
            return fix_result

        rerun_test_execution_result = await self._run_test_execution_phase(
            state,
            requirements_result,
            planning_result,
            implementation_result,
            test_design_result,
        )
        if not rerun_test_execution_result.is_success:
            return rerun_test_execution_result

        rerun_review_result = await self._run_review_phase(
            state,
            requirements_result,
            planning_result,
            documentation_result,
            implementation_result,
            test_design_result,
            rerun_test_execution_result,
        )
        if not rerun_review_result.is_success:
            return rerun_review_result

        state.add_note(
            "fix loop を 1 回実行し、test_execution と review を再実行した。"
        )
        return fix_result

    async def _run_fix_phase(
        self,
        state: WorkflowState,
        *,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        documentation_result: AgentResult,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
        test_execution_result: AgentResult,
        review_result: AgentResult,
    ) -> AgentResult:
        normalized_requirements = requirements_result.outputs.get(
            "normalized_requirements",
            {},
        )
        plan = planning_result.outputs.get("plan", {})
        documentation_bundle = documentation_result.outputs.get(
            "documentation_bundle",
            {},
        )
        implementation = implementation_result.outputs.get("implementation", {})
        test_plan = test_design_result.outputs.get("test_plan", {})
        test_results = test_execution_result.outputs.get("test_results", {})
        review = review_result.outputs.get("review", {})

        result = await self._execute_phase(
            state=state,
            task_id="implementation",
            agent=self.fixer_agent,
            difficulty=4,
            phase=WorkflowPhase.IMPLEMENTING,
            task_type=CopilotTaskType.FIX,
            prompt=(
                f"{normalized_requirements}\n\n{plan}\n\n{documentation_bundle}\n\n"
                f"{implementation}\n\n{test_plan}\n\n{test_results}\n\n{review}"
            ),
            system_prompt=(
                "Generate a focused fix proposal from the review findings and test "
                "results. Keep the fix slices small and include revalidation steps."
            ),
            estimated_input_tokens=(
                len(str(normalized_requirements))
                + len(str(plan))
                + len(str(documentation_bundle))
                + len(str(implementation))
                + len(str(test_plan))
                + len(str(test_results))
                + len(str(review))
            ),
            persistent_context={
                "workflow_id": state.workflow_id,
                "phase": state.phase.value,
                "requirement": state.requirement,
                "normalized_requirements": normalized_requirements,
                "plan": plan,
                "documentation_bundle": documentation_bundle,
                "implementation": implementation,
                "test_plan": test_plan,
                "test_results": test_results,
                "review": review,
            },
            build_inputs=lambda _routing_decision, copilot_response: {
                "normalized_requirements": normalized_requirements,
                "plan": plan,
                "documentation_bundle": documentation_bundle,
                "implementation": implementation,
                "test_plan": test_plan,
                "test_results": test_results,
                "review": review,
                "copilot_response": copilot_response.content,
            },
        )

        if result.is_success:
            self.artifact_writer.persist_text_output(
                state=state,
                result=result,
                output_key="fix_report",
                target_name="fix-report.md",
            )
            state.add_note("fix proposal を生成した。")

        return result

    def _rotate_session_if_needed(
        self,
        state: WorkflowState,
        *,
        token_usage_ratio: float,
        next_action: str,
        last_checkpoint: str,
        persistent_context: dict[str, Any],
    ) -> None:
        decision, snapshot = self.session_manager.rotate_session(
            state,
            token_usage_ratio=token_usage_ratio,
            next_action=next_action,
            last_checkpoint=last_checkpoint,
            persistent_context=persistent_context,
        )
        if decision.should_rotate:
            previous_session_id = snapshot.session_id
            previous_snapshot_path = self.state_store.save_session_snapshot(snapshot)
            state.add_note(
                "mid-run session rotation を実行し、後続フェーズを新 session で継続する。"
            )
            state.add_artifact(previous_snapshot_path.as_posix())
            state.add_note(
                f"pre-rotation session snapshot を保存した: {previous_session_id}"
            )

    async def _execute_phase(
        self,
        *,
        state: WorkflowState,
        task_id: str,
        agent: Any,
        difficulty: int,
        phase: WorkflowPhase,
        task_type: CopilotTaskType,
        prompt: str,
        system_prompt: str,
        estimated_input_tokens: int,
        persistent_context: dict[str, Any],
        build_inputs: Callable[[dict[str, Any], Any], dict[str, Any]],
    ) -> AgentResult:
        task = state.require_task(task_id)
        task.mark_in_progress(agent.agent_name)

        routing_decision = self.model_router.route_task(
            task.task_id,
            difficulty=difficulty,
            mode=self.routing_mode,
            retry_count=state.retry_counters.get(task.task_id, 0),
            estimated_input_tokens=estimated_input_tokens,
        )
        routing_payload = routing_decision.to_dict()
        state.model = routing_decision.selected_model
        task.add_note(f"selected_model={routing_decision.selected_model}")
        task.add_note(f"routing_reason={routing_decision.reason}")

        copilot_response = await self._generate_phase_copilot_response(
            state=state,
            task_id=task.task_id,
            prompt=prompt,
            system_prompt=system_prompt,
            model=routing_decision.selected_model,
            task_type=task_type,
            persistent_context=persistent_context,
            routing_payload=routing_payload,
        )

        result = await agent.run(
            AgentTask(
                name=task.task_id,
                objective=task.objective,
                inputs={
                    **build_inputs(routing_payload, copilot_response),
                    "routing_decision": routing_payload,
                },
                metadata={
                    "selected_model": routing_decision.selected_model,
                    "fallback_model": routing_decision.fallback_model,
                    "copilot_dry_run": copilot_response.is_dry_run,
                },
            ),
            state,
        )

        self._apply_result(
            state=state,
            task_id=task.task_id,
            phase=phase,
            result=result,
        )
        return result

    async def _generate_phase_copilot_response(
        self,
        *,
        state: WorkflowState,
        task_id: str,
        prompt: str,
        system_prompt: str,
        model: str,
        task_type: CopilotTaskType,
        persistent_context: dict[str, Any],
        routing_payload: dict[str, Any],
    ) -> Any:
        metadata = {
            "task_id": task_id,
            "routing_decision": routing_payload,
        }
        request = self._build_copilot_request(
            state=state,
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            task_type=task_type,
            persistent_context=persistent_context,
            metadata=metadata,
        )
        return await self.copilot_client.generate(request)

    def _build_copilot_request(
        self,
        *,
        state: WorkflowState,
        prompt: str,
        system_prompt: str,
        model: str,
        task_type: CopilotTaskType,
        persistent_context: dict[str, Any],
        metadata: dict[str, Any],
    ) -> CopilotRequest:
        if state.parent_session_id:
            snapshot = self.session_manager.snapshot_context(
                state,
                next_action=f"Resume {task_type.value}",
                last_checkpoint=state.phase.value,
                persistent_context=persistent_context,
            )
            resume_prompt = self.session_manager.build_resume_prompt(snapshot)
            return self.copilot_client.build_resume_request(
                prompt=prompt,
                resume_prompt=resume_prompt,
                task_type=task_type,
                session_id=state.session_id,
                workflow_id=state.workflow_id,
                persistent_context=persistent_context,
                model=model,
                metadata=metadata,
            )

        return CopilotRequest(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            task_type=task_type,
            session_id=state.session_id,
            workflow_id=state.workflow_id,
            persistent_context=dict(persistent_context),
            metadata=dict(metadata),
        )

    def _apply_result(
        self,
        *,
        state: WorkflowState,
        task_id: str,
        phase: WorkflowPhase,
        result: AgentResult,
    ) -> None:
        if result.is_success:
            state.update_task_status(
                task_id,
                TaskStatus.COMPLETED,
                note=result.summary,
                outputs=result.outputs,
            )
            state.set_phase(phase)
        else:
            state.increment_retry(task_id)
            state.update_task_status(
                task_id,
                TaskStatus.FAILED,
                note=result.summary,
                outputs=result.outputs,
            )
            state.set_phase(WorkflowPhase.FAILED)

        for artifact in result.artifacts:
            state.add_artifact(artifact)
        for risk in result.risks:
            state.add_risk(risk)

        open_questions = result.outputs.get("open_questions", [])
        if isinstance(open_questions, list):
            for question in open_questions:
                if question:
                    state.add_open_question(str(question))

    def _approval_hook(
        self,
        request: EditRequest,
        absolute_path: Path,
    ):
        relative_path = request.normalized_relative_path()

        if relative_path.startswith("docs/") or relative_path.startswith("artifacts/"):
            return approve_docs_and_artifacts_only(request, absolute_path)

        if relative_path.startswith("src/devagents/"):
            if request.operation == EditOperationKind.DELETE:
                from devagents.runtime.editor import ApprovalDecision, ApprovalResult

                return ApprovalResult(
                    decision=ApprovalDecision.DENIED,
                    reason="delete operations under src/devagents are not allowed",
                )

            if request.operation in {
                EditOperationKind.WRITE,
                EditOperationKind.APPEND,
            }:
                from devagents.runtime.editor import ApprovalDecision, ApprovalResult

                return ApprovalResult(
                    decision=ApprovalDecision.APPROVED,
                    reason="src/devagents allowlist permits controlled edits",
                )

        from devagents.runtime.editor import ApprovalDecision, ApprovalResult

        return ApprovalResult(
            decision=ApprovalDecision.DENIED,
            reason="target is outside configured approval scope",
        )

    def _build_workflow_id(self) -> str:
        from datetime import UTC, datetime

        return f"wf-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devagents",
        description="Run the devagents multi-agent workflow.",
    )
    parser.add_argument("requirement", help="Requirement text to process.")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Default model name. Defaults to {DEFAULT_MODEL}.",
    )
    parser.add_argument(
        "--artifacts-dir",
        default=str(ARTIFACTS_DIR),
        help="Directory where workflow artifacts are written.",
    )
    parser.add_argument(
        "--docs-dir",
        default=str(DOCS_DIR),
        help="Directory where generated documentation is written.",
    )
    parser.add_argument(
        "--token-usage-ratio",
        type=float,
        default=0.35,
        help="Estimated token usage ratio for the current session.",
    )
    parser.add_argument(
        "--routing-mode",
        choices=[mode.value for mode in RoutingMode],
        default=RoutingMode.BALANCED.value,
        help="Model routing mode.",
    )
    return parser


async def _run_cli(
    requirement: str,
    model: str,
    artifacts_dir: str,
    docs_dir: str,
    token_usage_ratio: float,
    routing_mode: str,
) -> int:
    orchestrator = SkeletonOrchestrator(
        model=model,
        artifacts_dir=Path(artifacts_dir),
        docs_dir=Path(docs_dir),
        routing_mode=RoutingMode(routing_mode),
    )
    state = await orchestrator.run(
        requirement,
        token_usage_ratio=token_usage_ratio,
    )
    rotation_decision = orchestrator.session_manager.should_rotate_session(
        token_usage_ratio=token_usage_ratio,
        current_session_id=state.session_id,
    )

    print(f"workflow_id: {state.workflow_id}")
    print(f"phase: {state.phase.value}")
    print(f"model: {state.model}")
    print(f"routing_mode: {routing_mode}")
    print("task_summary:")
    for task in state.tasks:
        print(f"  - {task.task_id}: {task.status.value}")
    print(f"session_id: {state.session_id}")
    print(f"rotate_session: {rotation_decision.should_rotate}")
    if rotation_decision.reason:
        print(f"rotation_reason: {rotation_decision.reason}")
    print("artifacts:")
    for artifact in state.artifacts:
        print(f"  - {artifact}")

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return asyncio.run(
        _run_cli(
            requirement=args.requirement,
            model=args.model,
            artifacts_dir=args.artifacts_dir,
            docs_dir=args.docs_dir,
            token_usage_ratio=args.token_usage_ratio,
            routing_mode=args.routing_mode,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())

# SAFE-EDIT-NOTE
# Proposed implementation slice: Wire documentation and implementation phases into the orchestrator.

# SAFE-EDIT-NOTE
# Proposed implementation slice: Promote approved implementation proposals into allowlisted source edits under src/devagents/.

# SAFE-EDIT-FIX-NOTE
# Proposed fix slice: 未解決の open questions が残っているため、実装前に確認が必要。

# SAFE-EDIT-FIX-NOTE
# Proposed fix slice: テスト結果が `needs_review` のため、追加確認または修正が必要。
