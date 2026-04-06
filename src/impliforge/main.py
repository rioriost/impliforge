"""CLI entrypoint wired to separated agents, model routing, session persistence,
documentation generation, implementation proposal flow, test planning/execution,
review reporting, and a safe edit phase.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from impliforge.agents.base import AgentResult, AgentTask
from impliforge.agents.documentation import DocumentationAgent
from impliforge.agents.fixer import FixerAgent
from impliforge.agents.implementation import ImplementationAgent
from impliforge.agents.planner import PlanningAgent
from impliforge.agents.requirements import RequirementsAgent
from impliforge.agents.reviewer import ReviewAgent
from impliforge.agents.test_design import TestDesignAgent
from impliforge.agents.test_execution import TestExecutionAgent
from impliforge.models.routing import ModelRouter, RoutingMode
from impliforge.orchestration.artifact_writer import WorkflowArtifactWriter
from impliforge.orchestration.edit_phase import EditPhaseOrchestrator
from impliforge.orchestration.runtime_support import RuntimeSupport
from impliforge.orchestration.session_manager import SessionManager
from impliforge.orchestration.state_store import StateStore
from impliforge.orchestration.workflow import (
    TaskStatus,
    WorkflowPhase,
    WorkflowState,
    create_workflow_state,
)
from impliforge.runtime.code_editing import (
    StructuredCodeEditor,
    approve_src_impliforge_only,
)
from impliforge.runtime.copilot_client import (
    CopilotClient,
    CopilotRequest,
    CopilotTaskType,
)
from impliforge.runtime.editor import EditorPolicy, SafeEditor

ARTIFACTS_DIR = Path("artifacts")
DOCS_DIR = Path("docs")
DEFAULT_MODEL = "gpt-5.4"
FIX_LOOP_RETRY_LIMIT = 2


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
            approval_hook=None,
        )
        self.code_editor = StructuredCodeEditor(
            workspace_root=Path.cwd(),
            approval_hook=approve_src_impliforge_only,
        )
        self.runtime_support = RuntimeSupport(
            state_store=self.state_store,
            session_manager=self.session_manager,
        )
        self.safe_editor.approval_hook = self.runtime_support.approval_hook
        self.edit_phase = EditPhaseOrchestrator(
            safe_editor=self.safe_editor,
            code_editor=self.code_editor,
            artifact_writer=self.artifact_writer,
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

        self.runtime_support.rotate_session_if_needed(
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

        effective_implementation_result = implementation_result
        effective_test_execution_result = test_execution_result
        effective_review_result = review_result
        if fix_result is not None:
            effective_implementation_result = self._merge_agent_results(
                implementation_result,
                fix_result,
                summary=fix_result.summary,
            )
            effective_test_execution_result = self._result_from_task_state(
                state=state,
                task_id="test_execution",
                fallback_result=test_execution_result,
            )
            effective_review_result = self._result_from_task_state(
                state=state,
                task_id="review",
                fallback_result=review_result,
            )

        self.edit_phase.apply_safe_edit_phase(
            state=state,
            requirement=requirement,
            requirements_result=requirements_result,
            planning_result=planning_result,
            documentation_result=documentation_result,
            implementation_result=effective_implementation_result,
            test_design_result=test_design_result,
            test_execution_result=effective_test_execution_result,
            review_result=effective_review_result,
            fix_result=fix_result,
        )

        snapshot = self.session_manager.snapshot_context(
            state,
            token_usage_ratio=token_usage_ratio,
            next_action="Promote safe edit outputs into concrete code generation and session resume flow",
            last_checkpoint=state.phase.value,
        )

        implementation_task_outputs = state.require_task("implementation").outputs
        safe_edit_summary = (
            implementation_task_outputs.get("safe_edit_summary", {})
            if isinstance(implementation_task_outputs, dict)
            else {}
        )
        structured_code_edit_summary = (
            implementation_task_outputs.get("structured_code_edit_summary", {})
            if isinstance(implementation_task_outputs, dict)
            else {}
        )

        effective_implementation_result = self._merge_agent_results(
            effective_implementation_result,
            AgentResult.success(
                "safe edit execution summaries captured",
                outputs={
                    "safe_edit_summary": safe_edit_summary,
                    "structured_code_edit_summary": structured_code_edit_summary,
                },
            ),
        )

        self.artifact_writer.write_workflow_artifacts(
            state=state,
            requirement=requirement,
            requirements_result=requirements_result,
            planning_result=planning_result,
            documentation_result=documentation_result,
            implementation_result=effective_implementation_result,
            test_design_result=test_design_result,
            test_execution_result=effective_test_execution_result,
            review_result=effective_review_result,
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

        fix_loop_attempt = state.increment_retry("fix_loop")
        if fix_loop_attempt > FIX_LOOP_RETRY_LIMIT:
            state.set_phase(WorkflowPhase.NEEDS_HUMAN_INPUT)
            state.add_risk(
                "fix loop retry limit に達したため、自動修正を停止して人手エスカレーションが必要"
            )
            state.add_note(
                "fix loop retry limit を超えたため、自動 fix loop を停止し、人手エスカレーションに切り替える。"
            )
            state.require_task("review").mark_blocked(
                "fix loop retry limit exceeded; human escalation required"
            )
            state.require_task("implementation").mark_blocked(
                "fix loop retry limit exceeded; human escalation required"
            )
            return AgentResult.failure(
                "fix loop retry limit exceeded",
                outputs={
                    "review": {
                        **review,
                        "fix_loop_required": True,
                        "fix_loop_attempt": fix_loop_attempt,
                        "fix_loop_retry_limit": FIX_LOOP_RETRY_LIMIT,
                        "escalation_required": True,
                    }
                },
                risks=[
                    "fix loop retry limit に達したため、自動修正を停止して人手エスカレーションが必要"
                ],
                next_actions=[
                    "Escalate to a human reviewer",
                    "Resolve the blocking review findings manually",
                    "Re-run fix loop only after human guidance is recorded",
                ],
                failure_category="fix_loop_retry_limit",
                failure_cause="automatic fix loop exceeded retry limit",
            )

        task = state.require_task("implementation")
        task.add_note(
            f"fix loop を開始した。attempt={fix_loop_attempt}/{FIX_LOOP_RETRY_LIMIT}"
        )

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

        rerun_implementation_result = self._merge_agent_results(
            implementation_result,
            fix_result,
            summary=fix_result.summary,
        )

        rerun_test_execution_result = await self._run_test_execution_phase(
            state,
            requirements_result,
            planning_result,
            rerun_implementation_result,
            test_design_result,
        )
        if not rerun_test_execution_result.is_success:
            state.add_note(
                "fix loop の rerun test_execution が失敗したため、追加修正またはエスカレーションが必要。"
            )
            return rerun_test_execution_result

        rerun_review_result = await self._run_review_phase(
            state,
            requirements_result,
            planning_result,
            documentation_result,
            rerun_implementation_result,
            test_design_result,
            rerun_test_execution_result,
        )
        if not rerun_review_result.is_success:
            state.add_note(
                "fix loop の rerun review が失敗したため、追加修正またはエスカレーションが必要。"
            )
            return rerun_review_result

        state.add_note(
            f"fix loop を {fix_loop_attempt} 回目として実行し、test_execution と review を再実行した。"
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
            mode=self.runtime_support.degraded_routing_mode(
                state,
                routing_mode=self.routing_mode,
            ),
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

        phase_inputs = build_inputs(routing_payload, copilot_response)
        result = await agent.run(
            AgentTask(
                name=task.task_id,
                objective=task.objective,
                inputs={
                    **phase_inputs,
                    "routing_decision": routing_payload,
                },
                metadata={
                    "selected_model": routing_decision.selected_model,
                    "fallback_model": routing_decision.fallback_model,
                    "copilot_dry_run": copilot_response.is_dry_run,
                    "phase": phase.value,
                    "task_type": task_type.value,
                    "input_keys": sorted(phase_inputs.keys()),
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
        state.record_event(
            "phase_completed",
            task_id=task.task_id,
            agent_name=getattr(agent, "agent_name", None),
            status=result.status,
            summary=result.summary,
            details={
                "phase": phase.value,
                "task_type": task_type.value,
                "input_keys": sorted(phase_inputs.keys()),
                "output_keys": sorted(result.outputs.keys()),
                "artifact_count": len(result.artifacts),
                "risk_count": len(result.risks),
                "next_action_count": len(result.next_actions),
            },
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
        normalized_summary = (
            result.summary.strip()
            if isinstance(result.summary, str) and result.summary.strip()
            else "No summary provided."
        )
        normalized_outputs = (
            dict(result.outputs) if isinstance(result.outputs, Mapping) else {}
        )
        normalized_artifacts = self._normalize_unique_strings(result.artifacts)
        normalized_risks = self._normalize_unique_strings(result.risks)
        normalized_open_questions = self._normalize_unique_strings(
            normalized_outputs.get("open_questions", [])
            if isinstance(normalized_outputs.get("open_questions"), list)
            else []
        )
        normalized_changed_files = self._normalize_unique_strings(
            normalized_outputs.get("changed_files", [])
            if isinstance(normalized_outputs.get("changed_files"), list)
            else []
        )
        normalized_next_actions = self._normalize_unique_strings(result.next_actions)

        if result.is_success:
            success_outputs = self._merge_dicts(
                state.require_task(task_id).outputs,
                normalized_outputs,
            )
            if normalized_next_actions:
                success_outputs["next_actions"] = normalized_next_actions
            if result.metrics:
                success_outputs["metrics"] = dict(result.metrics)
            state.update_task_status(
                task_id,
                TaskStatus.COMPLETED,
                note=normalized_summary,
                outputs=success_outputs,
            )
            state.set_phase(phase)
        else:
            state.increment_retry(task_id)
            failure_category = (
                result.failure_category.strip()
                if isinstance(result.failure_category, str)
                and result.failure_category.strip()
                else "implementation_failure"
            )
            failure_cause = (
                result.failure_cause.strip()
                if isinstance(result.failure_cause, str)
                and result.failure_cause.strip()
                else normalized_summary
            )
            failure_outputs = self._merge_dicts(
                state.require_task(task_id).outputs,
                normalized_outputs,
            )
            failure_outputs["failure_category"] = failure_category
            failure_outputs["failure_cause"] = failure_cause
            failure_outputs["next_actions"] = normalized_next_actions
            if result.metrics:
                failure_outputs["metrics"] = dict(result.metrics)
            state.update_task_status(
                task_id,
                TaskStatus.FAILED,
                note=normalized_summary,
                outputs=failure_outputs,
            )
            state.require_task(task_id).add_note(
                f"[failure_category={failure_category}; failure_cause={failure_cause}]"
            )
            state.set_phase(WorkflowPhase.FAILED)
            state.add_note(
                f"{task_id} failed: category={failure_category}; cause={failure_cause}"
            )
            if normalized_next_actions:
                state.add_note(
                    f"{task_id} next actions: {' | '.join(normalized_next_actions)}"
                )

        for artifact in normalized_artifacts:
            state.add_artifact(artifact)
        for risk in normalized_risks:
            state.add_risk(risk)
        for question in normalized_open_questions:
            state.add_open_question(question)
        for changed_file in normalized_changed_files:
            state.add_changed_file(changed_file)

    def _merge_agent_results(
        self,
        base_result: AgentResult,
        override_result: AgentResult,
        *,
        summary: str | None = None,
    ) -> AgentResult:
        merged_outputs = self._merge_dicts(base_result.outputs, override_result.outputs)
        merged_artifacts = self._merge_unique_lists(
            base_result.artifacts,
            override_result.artifacts,
        )
        merged_risks = self._merge_unique_lists(
            base_result.risks,
            override_result.risks,
        )
        merged_next_actions = self._merge_unique_lists(
            base_result.next_actions,
            override_result.next_actions,
        )
        merged_metrics = self._merge_dicts(base_result.metrics, override_result.metrics)
        merged_summary = (
            summary.strip()
            if isinstance(summary, str) and summary.strip()
            else override_result.summary
            if isinstance(override_result.summary, str)
            and override_result.summary.strip()
            else base_result.summary
        )
        return AgentResult.success(
            merged_summary,
            outputs=merged_outputs,
            artifacts=merged_artifacts,
            risks=merged_risks,
            next_actions=merged_next_actions,
            metrics=merged_metrics,
        )

    def _result_from_task_state(
        self,
        *,
        state: WorkflowState,
        task_id: str,
        fallback_result: AgentResult,
    ) -> AgentResult:
        task = state.require_task(task_id)
        outputs = self._merge_dicts(fallback_result.outputs, task.outputs)
        artifacts = self._merge_unique_lists(
            fallback_result.artifacts,
            outputs.get("artifacts", [])
            if isinstance(outputs.get("artifacts"), list)
            else [],
        )
        risks = self._merge_unique_lists(
            fallback_result.risks,
            outputs.get("risks", []) if isinstance(outputs.get("risks"), list) else [],
        )
        next_actions = self._merge_unique_lists(
            fallback_result.next_actions,
            outputs.get("next_actions", [])
            if isinstance(outputs.get("next_actions"), list)
            else [],
        )
        metrics = self._merge_dicts(
            fallback_result.metrics,
            outputs.get("metrics", {})
            if isinstance(outputs.get("metrics"), Mapping)
            else {},
        )
        summary = task.notes[-1] if task.notes else fallback_result.summary
        return AgentResult.success(
            summary,
            outputs=outputs,
            artifacts=artifacts,
            risks=risks,
            next_actions=next_actions,
            metrics=metrics,
        )

    def _merge_unique_lists(
        self,
        base_values: Iterable[Any],
        override_values: Iterable[Any],
    ) -> list[str]:
        merged: list[str] = []
        for value in [*base_values, *override_values]:
            text = str(value).strip()
            if text and text not in merged:
                merged.append(text)
        return merged

    def _normalize_unique_strings(self, values: Iterable[Any]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            text = str(value).strip()
            if text and text not in normalized:
                normalized.append(text)
        return normalized

    def _merge_dicts(
        self,
        base: Mapping[str, Any],
        override: Mapping[str, Any],
    ) -> dict[str, Any]:
        merged = dict(base)
        for key, value in override.items():
            existing = merged.get(key)
            if isinstance(existing, Mapping) and isinstance(value, Mapping):
                merged[key] = self._merge_dicts(existing, value)
            elif isinstance(existing, list) and isinstance(value, list):
                merged[key] = self._merge_unique_lists(existing, value)
            else:
                merged[key] = value
        return merged

    def _build_workflow_id(self) -> str:
        from datetime import UTC, datetime

        return f"wf-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="impliforge",
        description="Run the impliforge multi-agent workflow.",
    )
    parser.add_argument(
        "requirement_file",
        help="Path to a file containing the requirement text to process.",
    )
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
    requirement_file: str,
    model: str,
    artifacts_dir: str,
    docs_dir: str,
    token_usage_ratio: float,
    routing_mode: str,
) -> int:
    requirement_path = Path(requirement_file)

    try:
        requirement = requirement_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        print(f"error: requirement file not found: {requirement_path}")
        return 1
    except OSError as exc:
        print(f"error: failed to read requirement file {requirement_path}: {exc}")
        return 1

    if not requirement:
        print(f"error: requirement file is empty: {requirement_path}")
        return 1

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
    print(f"requirement_file: {requirement_path}")
    print("task_summary:")
    for task in state.tasks:
        print(f"  - {task.task_id}: {task.status.value}")
    print(f"session_id: {state.session_id}")
    print(f"rotate_session: {rotation_decision.should_rotate}")
    if rotation_decision.reason:
        print(f"rotation_reason: {rotation_decision.reason}")
    implementation_outputs = state.require_task("implementation").outputs
    safe_edit_summary = (
        implementation_outputs.get("safe_edit_summary", {})
        if isinstance(implementation_outputs, dict)
        else {}
    )
    structured_code_edit_summary = (
        implementation_outputs.get("structured_code_edit_summary", {})
        if isinstance(implementation_outputs, dict)
        else {}
    )

    print("artifacts:")
    for artifact in state.artifacts:
        print(f"  - {artifact}")

    print("safe_edit_summary:")
    print(f"  - request_count: {safe_edit_summary.get('request_count', 0)}")
    print(f"  - applied_count: {safe_edit_summary.get('applied_count', 0)}")
    print(f"  - denied_count: {safe_edit_summary.get('denied_count', 0)}")
    print(
        "  - applied_paths: "
        + (
            ", ".join(safe_edit_summary.get("applied_paths", []))
            if isinstance(safe_edit_summary.get("applied_paths"), list)
            and safe_edit_summary.get("applied_paths")
            else "none"
        )
    )
    print(
        "  - denied_paths: "
        + (
            ", ".join(safe_edit_summary.get("denied_paths", []))
            if isinstance(safe_edit_summary.get("denied_paths"), list)
            and safe_edit_summary.get("denied_paths")
            else "none"
        )
    )

    print("structured_code_edit_summary:")
    print(f"  - request_count: {structured_code_edit_summary.get('request_count', 0)}")
    print(f"  - applied_count: {structured_code_edit_summary.get('applied_count', 0)}")
    print(f"  - denied_count: {structured_code_edit_summary.get('denied_count', 0)}")
    print(
        "  - applied_paths: "
        + (
            ", ".join(structured_code_edit_summary.get("applied_paths", []))
            if isinstance(structured_code_edit_summary.get("applied_paths"), list)
            and structured_code_edit_summary.get("applied_paths")
            else "none"
        )
    )
    print(
        "  - denied_paths: "
        + (
            ", ".join(structured_code_edit_summary.get("denied_paths", []))
            if isinstance(structured_code_edit_summary.get("denied_paths"), list)
            and structured_code_edit_summary.get("denied_paths")
            else "none"
        )
    )

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return asyncio.run(
        _run_cli(
            requirement_file=args.requirement_file,
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
# Proposed implementation slice: Promote approved implementation proposals into allowlisted source edits under src/impliforge/.

# SAFE-EDIT-FIX-NOTE
# Proposed fix slice: 未解決の open questions が残っているため、実装前に確認が必要。

# SAFE-EDIT-FIX-NOTE
# Proposed fix slice: テスト結果が `needs_review` のため、追加確認または修正が必要。
