"""CLI entrypoint wired to separated agents, model routing, session persistence,
documentation generation, implementation proposal flow, test planning/execution,
review reporting, and a safe edit phase.
"""

from __future__ import annotations

import argparse
import asyncio
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
from devagents.runtime.copilot_client import CopilotClient, CopilotTaskType
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

        self._apply_safe_edit_phase(
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

        self._write_workflow_artifacts(
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

        finalization_task = state.require_task("finalization")
        finalization_task.mark_completed(
            outputs={
                "next_actions": [
                    "Expand safe edit phase from docs/artifacts into source-code allowlists",
                    "Add session resume flow using resume_session",
                    "Promote fix loop outputs into concrete code edits when needed",
                ]
            }
        )
        state.update_task_status(
            "finalization",
            TaskStatus.COMPLETED,
            note="成果物保存と次アクション整理を完了した。",
            outputs=finalization_task.outputs,
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
        task = state.require_task("requirements_analysis")
        task.mark_in_progress(self.requirements_agent.agent_name)

        routing_decision = self.model_router.route_task(
            task.task_id,
            difficulty=4,
            mode=self.routing_mode,
            estimated_input_tokens=len(requirement),
        )
        state.model = routing_decision.selected_model
        task.add_note(f"selected_model={routing_decision.selected_model}")
        task.add_note(f"routing_reason={routing_decision.reason}")

        copilot_response = await self.copilot_client.generate_text(
            prompt=requirement,
            system_prompt=(
                "Analyze the requirement, identify constraints, acceptance criteria, "
                "and open questions for a multi-agent implementation workflow."
            ),
            model=routing_decision.selected_model,
            task_type=CopilotTaskType.REQUIREMENTS,
            session_id=state.session_id,
            workflow_id=state.workflow_id,
            persistent_context={
                "workflow_id": state.workflow_id,
                "phase": state.phase.value,
                "requirement": state.requirement,
            },
            metadata={
                "task_id": task.task_id,
                "routing_decision": routing_decision.to_dict(),
            },
        )

        result = await self.requirements_agent.run(
            AgentTask(
                name=task.task_id,
                objective=task.objective,
                inputs={
                    "requirement": requirement,
                    "copilot_response": copilot_response.content,
                    "routing_decision": routing_decision.to_dict(),
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
            phase=WorkflowPhase.REQUIREMENTS_ANALYZED,
            result=result,
        )
        return result

    async def _run_planning_phase(
        self,
        state: WorkflowState,
        requirements_result: AgentResult,
    ) -> AgentResult:
        task = state.require_task("planning")
        task.mark_in_progress(self.planning_agent.agent_name)

        normalized_requirements = requirements_result.outputs.get(
            "normalized_requirements",
            {},
        )
        estimated_input_tokens = len(str(normalized_requirements))

        routing_decision = self.model_router.route_task(
            task.task_id,
            difficulty=4,
            mode=self.routing_mode,
            retry_count=state.retry_counters.get(task.task_id, 0),
            estimated_input_tokens=estimated_input_tokens,
        )
        state.model = routing_decision.selected_model
        task.add_note(f"selected_model={routing_decision.selected_model}")
        task.add_note(f"routing_reason={routing_decision.reason}")

        copilot_response = await self.copilot_client.generate_text(
            prompt=str(normalized_requirements),
            system_prompt=(
                "Create an implementation plan, task breakdown, and next actions "
                "for the provided normalized requirements."
            ),
            model=routing_decision.selected_model,
            task_type=CopilotTaskType.PLANNING,
            session_id=state.session_id,
            workflow_id=state.workflow_id,
            persistent_context={
                "workflow_id": state.workflow_id,
                "phase": state.phase.value,
                "requirement": state.requirement,
                "normalized_requirements": normalized_requirements,
            },
            metadata={
                "task_id": task.task_id,
                "routing_decision": routing_decision.to_dict(),
            },
        )

        result = await self.planning_agent.run(
            AgentTask(
                name=task.task_id,
                objective=task.objective,
                inputs={
                    "normalized_requirements": normalized_requirements,
                    "copilot_response": copilot_response.content,
                    "routing_decision": routing_decision.to_dict(),
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
            phase=WorkflowPhase.PLANNED,
            result=result,
        )
        return result

    async def _run_documentation_phase(
        self,
        state: WorkflowState,
        requirements_result: AgentResult,
        planning_result: AgentResult,
    ) -> AgentResult:
        task = state.require_task("documentation")
        task.mark_in_progress(self.documentation_agent.agent_name)

        normalized_requirements = requirements_result.outputs.get(
            "normalized_requirements",
            {},
        )
        plan = planning_result.outputs.get("plan", {})
        estimated_input_tokens = len(str(normalized_requirements)) + len(str(plan))

        routing_decision = self.model_router.route_task(
            task.task_id,
            difficulty=3,
            mode=self.routing_mode,
            retry_count=state.retry_counters.get(task.task_id, 0),
            estimated_input_tokens=estimated_input_tokens,
        )
        state.model = routing_decision.selected_model
        task.add_note(f"selected_model={routing_decision.selected_model}")
        task.add_note(f"routing_reason={routing_decision.reason}")

        copilot_response = await self.copilot_client.generate_text(
            prompt=f"{normalized_requirements}\n\n{plan}",
            system_prompt=(
                "Generate a concise design document and runbook draft for the "
                "provided workflow requirements and implementation plan."
            ),
            model=routing_decision.selected_model,
            task_type=CopilotTaskType.DOCUMENTATION,
            session_id=state.session_id,
            workflow_id=state.workflow_id,
            persistent_context={
                "workflow_id": state.workflow_id,
                "phase": state.phase.value,
                "requirement": state.requirement,
                "normalized_requirements": normalized_requirements,
                "plan": plan,
            },
            metadata={
                "task_id": task.task_id,
                "routing_decision": routing_decision.to_dict(),
            },
        )

        result = await self.documentation_agent.run(
            AgentTask(
                name=task.task_id,
                objective=task.objective,
                inputs={
                    "normalized_requirements": normalized_requirements,
                    "plan": plan,
                    "copilot_response": copilot_response.content,
                    "routing_decision": routing_decision.to_dict(),
                },
                metadata={
                    "selected_model": routing_decision.selected_model,
                    "fallback_model": routing_decision.fallback_model,
                    "copilot_dry_run": copilot_response.is_dry_run,
                },
            ),
            state,
        )

        if result.is_success:
            self._persist_documentation_outputs(state, result)

        self._apply_result(
            state=state,
            task_id=task.task_id,
            phase=WorkflowPhase.DESIGN_GENERATED,
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
        task = state.require_task("implementation")
        task.mark_in_progress(self.implementation_agent.agent_name)

        normalized_requirements = requirements_result.outputs.get(
            "normalized_requirements",
            {},
        )
        plan = planning_result.outputs.get("plan", {})
        documentation_bundle = documentation_result.outputs.get(
            "documentation_bundle",
            {},
        )
        estimated_input_tokens = (
            len(str(normalized_requirements))
            + len(str(plan))
            + len(str(documentation_bundle))
        )

        routing_decision = self.model_router.route_task(
            task.task_id,
            difficulty=4,
            mode=self.routing_mode,
            retry_count=state.retry_counters.get(task.task_id, 0),
            estimated_input_tokens=estimated_input_tokens,
        )
        state.model = routing_decision.selected_model
        task.add_note(f"selected_model={routing_decision.selected_model}")
        task.add_note(f"routing_reason={routing_decision.reason}")

        copilot_response = await self.copilot_client.generate_text(
            prompt=f"{normalized_requirements}\n\n{plan}\n\n{documentation_bundle}",
            system_prompt=(
                "Generate an implementation proposal with concrete change slices, "
                "target modules, and next actions for the provided workflow context."
            ),
            model=routing_decision.selected_model,
            task_type=CopilotTaskType.IMPLEMENTATION,
            session_id=state.session_id,
            workflow_id=state.workflow_id,
            persistent_context={
                "workflow_id": state.workflow_id,
                "phase": state.phase.value,
                "requirement": state.requirement,
                "normalized_requirements": normalized_requirements,
                "plan": plan,
                "documentation_bundle": documentation_bundle,
            },
            metadata={
                "task_id": task.task_id,
                "routing_decision": routing_decision.to_dict(),
            },
        )

        result = await self.implementation_agent.run(
            AgentTask(
                name=task.task_id,
                objective=task.objective,
                inputs={
                    "normalized_requirements": normalized_requirements,
                    "plan": plan,
                    "documentation_bundle": documentation_bundle,
                    "copilot_response": copilot_response.content,
                    "routing_decision": routing_decision.to_dict(),
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
            phase=WorkflowPhase.IMPLEMENTING,
            result=result,
        )
        return result

    async def _run_test_design_phase(
        self,
        state: WorkflowState,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        documentation_result: AgentResult,
        implementation_result: AgentResult,
    ) -> AgentResult:
        task = state.require_task("test_design")
        task.mark_in_progress(self.test_design_agent.agent_name)

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
        estimated_input_tokens = (
            len(str(normalized_requirements))
            + len(str(plan))
            + len(str(documentation_bundle))
            + len(str(implementation))
        )

        routing_decision = self.model_router.route_task(
            task.task_id,
            difficulty=3,
            mode=self.routing_mode,
            retry_count=state.retry_counters.get(task.task_id, 0),
            estimated_input_tokens=estimated_input_tokens,
        )
        state.model = routing_decision.selected_model
        task.add_note(f"selected_model={routing_decision.selected_model}")
        task.add_note(f"routing_reason={routing_decision.reason}")

        copilot_response = await self.copilot_client.generate_text(
            prompt=(
                f"{normalized_requirements}\n\n{plan}\n\n"
                f"{documentation_bundle}\n\n{implementation}"
            ),
            system_prompt=(
                "Generate a focused test plan with validation scenarios, test levels, "
                "and acceptance criteria coverage for the provided workflow context."
            ),
            model=routing_decision.selected_model,
            task_type=CopilotTaskType.TEST_DESIGN,
            session_id=state.session_id,
            workflow_id=state.workflow_id,
            persistent_context={
                "workflow_id": state.workflow_id,
                "phase": state.phase.value,
                "requirement": state.requirement,
                "normalized_requirements": normalized_requirements,
                "plan": plan,
                "documentation_bundle": documentation_bundle,
                "implementation": implementation,
            },
            metadata={
                "task_id": task.task_id,
                "routing_decision": routing_decision.to_dict(),
            },
        )

        result = await self.test_design_agent.run(
            AgentTask(
                name=task.task_id,
                objective=task.objective,
                inputs={
                    "normalized_requirements": normalized_requirements,
                    "plan": plan,
                    "documentation_bundle": documentation_bundle,
                    "implementation": implementation,
                    "copilot_response": copilot_response.content,
                    "routing_decision": routing_decision.to_dict(),
                },
                metadata={
                    "selected_model": routing_decision.selected_model,
                    "fallback_model": routing_decision.fallback_model,
                    "copilot_dry_run": copilot_response.is_dry_run,
                },
            ),
            state,
        )

        if result.is_success:
            self._persist_text_output(
                state=state,
                result=result,
                output_key="test_plan_document",
                target_name="test-plan.md",
            )

        self._apply_result(
            state=state,
            task_id=task.task_id,
            phase=WorkflowPhase.TESTING,
            result=result,
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
        task = state.require_task("test_execution")
        task.mark_in_progress(self.test_execution_agent.agent_name)

        normalized_requirements = requirements_result.outputs.get(
            "normalized_requirements",
            {},
        )
        plan = planning_result.outputs.get("plan", {})
        implementation = implementation_result.outputs.get("implementation", {})
        test_plan = test_design_result.outputs.get("test_plan", {})
        estimated_input_tokens = (
            len(str(normalized_requirements))
            + len(str(plan))
            + len(str(implementation))
            + len(str(test_plan))
        )

        routing_decision = self.model_router.route_task(
            task.task_id,
            difficulty=3,
            mode=self.routing_mode,
            retry_count=state.retry_counters.get(task.task_id, 0),
            estimated_input_tokens=estimated_input_tokens,
        )
        state.model = routing_decision.selected_model
        task.add_note(f"selected_model={routing_decision.selected_model}")
        task.add_note(f"routing_reason={routing_decision.reason}")

        copilot_response = await self.copilot_client.generate_text(
            prompt=f"{normalized_requirements}\n\n{plan}\n\n{implementation}\n\n{test_plan}",
            system_prompt=(
                "Generate a concise test execution report, including executed checks, "
                "provisional status, and unresolved validation concerns."
            ),
            model=routing_decision.selected_model,
            task_type=CopilotTaskType.TEST_EXECUTION,
            session_id=state.session_id,
            workflow_id=state.workflow_id,
            persistent_context={
                "workflow_id": state.workflow_id,
                "phase": state.phase.value,
                "requirement": state.requirement,
                "normalized_requirements": normalized_requirements,
                "plan": plan,
                "implementation": implementation,
                "test_plan": test_plan,
            },
            metadata={
                "task_id": task.task_id,
                "routing_decision": routing_decision.to_dict(),
            },
        )

        result = await self.test_execution_agent.run(
            AgentTask(
                name=task.task_id,
                objective=task.objective,
                inputs={
                    "normalized_requirements": normalized_requirements,
                    "plan": plan,
                    "implementation": implementation,
                    "test_plan": test_plan,
                    "copilot_response": copilot_response.content,
                    "routing_decision": routing_decision.to_dict(),
                },
                metadata={
                    "selected_model": routing_decision.selected_model,
                    "fallback_model": routing_decision.fallback_model,
                    "copilot_dry_run": copilot_response.is_dry_run,
                },
            ),
            state,
        )

        if result.is_success:
            self._persist_text_output(
                state=state,
                result=result,
                output_key="test_results_document",
                target_name="test-results.md",
            )

        self._apply_result(
            state=state,
            task_id=task.task_id,
            phase=WorkflowPhase.TESTING,
            result=result,
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
        task = state.require_task("review")
        task.mark_in_progress(self.review_agent.agent_name)

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
        estimated_input_tokens = (
            len(str(normalized_requirements))
            + len(str(plan))
            + len(str(documentation_bundle))
            + len(str(implementation))
            + len(str(test_plan))
            + len(str(test_results))
        )

        routing_decision = self.model_router.route_task(
            task.task_id,
            difficulty=4,
            mode=self.routing_mode,
            retry_count=state.retry_counters.get(task.task_id, 0),
            estimated_input_tokens=estimated_input_tokens,
        )
        state.model = routing_decision.selected_model
        task.add_note(f"selected_model={routing_decision.selected_model}")
        task.add_note(f"routing_reason={routing_decision.reason}")

        copilot_response = await self.copilot_client.generate_text(
            prompt=(
                f"{normalized_requirements}\n\n{plan}\n\n{documentation_bundle}\n\n"
                f"{implementation}\n\n{test_plan}\n\n{test_results}"
            ),
            system_prompt=(
                "Review the generated workflow outputs, identify unresolved issues, "
                "and produce a concise review report with recommendations."
            ),
            model=routing_decision.selected_model,
            task_type=CopilotTaskType.REVIEW,
            session_id=state.session_id,
            workflow_id=state.workflow_id,
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
            metadata={
                "task_id": task.task_id,
                "routing_decision": routing_decision.to_dict(),
            },
        )

        result = await self.review_agent.run(
            AgentTask(
                name=task.task_id,
                objective=task.objective,
                inputs={
                    "normalized_requirements": normalized_requirements,
                    "plan": plan,
                    "documentation_bundle": documentation_bundle,
                    "implementation": implementation,
                    "test_plan": test_plan,
                    "test_results": test_results,
                    "copilot_response": copilot_response.content,
                    "routing_decision": routing_decision.to_dict(),
                },
                metadata={
                    "selected_model": routing_decision.selected_model,
                    "fallback_model": routing_decision.fallback_model,
                    "copilot_dry_run": copilot_response.is_dry_run,
                },
            ),
            state,
        )

        if result.is_success:
            self._persist_text_output(
                state=state,
                result=result,
                output_key="review_report",
                target_name="review-report.md",
            )

        self._apply_result(
            state=state,
            task_id=task.task_id,
            phase=WorkflowPhase.REVIEWING,
            result=result,
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

        estimated_input_tokens = (
            len(str(normalized_requirements))
            + len(str(plan))
            + len(str(documentation_bundle))
            + len(str(implementation))
            + len(str(test_plan))
            + len(str(test_results))
            + len(str(review))
        )

        routing_decision = self.model_router.route_task(
            "fix",
            difficulty=4,
            mode=self.routing_mode,
            retry_count=state.retry_counters.get("fix", 0),
            estimated_input_tokens=estimated_input_tokens,
        )
        state.model = routing_decision.selected_model

        copilot_response = await self.copilot_client.generate_text(
            prompt=(
                f"{normalized_requirements}\n\n{plan}\n\n{documentation_bundle}\n\n"
                f"{implementation}\n\n{test_plan}\n\n{test_results}\n\n{review}"
            ),
            system_prompt=(
                "Generate a focused fix proposal from the review findings and test "
                "results. Keep the fix slices small and include revalidation steps."
            ),
            model=routing_decision.selected_model,
            task_type=CopilotTaskType.FIX,
            session_id=state.session_id,
            workflow_id=state.workflow_id,
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
            metadata={
                "task_id": "fix",
                "routing_decision": routing_decision.to_dict(),
            },
        )

        result = await self.fixer_agent.run(
            AgentTask(
                name="fix",
                objective="Generate a focused fix proposal from review and validation outputs",
                inputs={
                    "normalized_requirements": normalized_requirements,
                    "plan": plan,
                    "documentation_bundle": documentation_bundle,
                    "implementation": implementation,
                    "test_plan": test_plan,
                    "test_results": test_results,
                    "review": review,
                    "copilot_response": copilot_response.content,
                    "routing_decision": routing_decision.to_dict(),
                },
                metadata={
                    "selected_model": routing_decision.selected_model,
                    "fallback_model": routing_decision.fallback_model,
                    "copilot_dry_run": copilot_response.is_dry_run,
                },
            ),
            state,
        )

        if result.is_success:
            self._persist_text_output(
                state=state,
                result=result,
                output_key="fix_report",
                target_name="fix-report.md",
            )
            state.add_note("fix proposal を生成した。")

        return result

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

    def _persist_documentation_outputs(
        self,
        state: WorkflowState,
        result: AgentResult,
    ) -> None:
        design_document = result.outputs.get("design_document")
        runbook_document = result.outputs.get("runbook_document")

        if isinstance(design_document, str) and design_document.strip():
            design_path = self.docs_dir / "design.md"
            design_path.write_text(design_document, encoding="utf-8")
            state.add_artifact(design_path.as_posix())
            state.add_changed_file(design_path.as_posix())

        if isinstance(runbook_document, str) and runbook_document.strip():
            runbook_path = self.docs_dir / "runbook.md"
            runbook_path.write_text(runbook_document, encoding="utf-8")
            state.add_artifact(runbook_path.as_posix())
            state.add_changed_file(runbook_path.as_posix())

    def _persist_text_output(
        self,
        *,
        state: WorkflowState,
        result: AgentResult,
        output_key: str,
        target_name: str,
    ) -> None:
        content = result.outputs.get(output_key)
        if not isinstance(content, str) or not content.strip():
            return

        target_path = self.docs_dir / target_name
        target_path.write_text(content, encoding="utf-8")
        state.add_artifact(target_path.as_posix())
        state.add_changed_file(target_path.as_posix())

    def _apply_safe_edit_phase(
        self,
        *,
        state: WorkflowState,
        requirement: str,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        documentation_result: AgentResult,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
        test_execution_result: AgentResult,
        review_result: AgentResult,
        fix_result: AgentResult | None,
    ) -> None:
        operations = self._build_safe_edit_operations(
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

        if not operations:
            state.add_note("safe edit phase で適用対象はなかった。")
            return

        results = self.safe_editor.apply_many(operations)
        applied_paths: list[str] = []
        denied_paths: list[str] = []

        for result in results:
            if result.ok and result.changed:
                applied_paths.append(result.relative_path)
                state.add_artifact(result.relative_path)
                state.add_changed_file(result.relative_path)
            elif not result.ok:
                denied_paths.append(f"{result.relative_path}: {result.message}")

        structured_edit_paths = self._apply_structured_code_edit_phase(
            state=state,
            implementation_result=implementation_result,
            fix_result=fix_result,
        )
        for path in structured_edit_paths:
            if path not in applied_paths:
                applied_paths.append(path)
                state.add_artifact(path)
                state.add_changed_file(path)

        if applied_paths:
            state.add_note(
                f"safe edit phase で {len(applied_paths)} 件の allowlist 対象ファイルを更新した。"
            )
        else:
            state.add_note("safe edit phase で更新されたファイルはなかった。")

        if denied_paths:
            state.add_note(
                "safe edit phase で承認または allowlist により拒否された対象がある: "
                + " | ".join(denied_paths)
            )

    def _build_safe_edit_operations(
        self,
        *,
        state: WorkflowState,
        requirement: str,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        documentation_result: AgentResult,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
        test_execution_result: AgentResult,
        review_result: AgentResult,
        fix_result: AgentResult | None,
    ) -> list[EditRequest]:
        # BEGIN STRUCTURED EDIT: SkeletonOrchestrator._build_safe_edit_operations
        operations: list[EditRequest] = []

        design_document = documentation_result.outputs.get("design_document")
        if isinstance(design_document, str) and design_document.strip():
            operations.append(
                EditRequest(
                    relative_path="docs/design.md",
                    operation=EditOperationKind.WRITE,
                    content=design_document,
                    reason="Persist generated design document through safe edit phase",
                )
            )

        runbook_document = documentation_result.outputs.get("runbook_document")
        if isinstance(runbook_document, str) and runbook_document.strip():
            operations.append(
                EditRequest(
                    relative_path="docs/runbook.md",
                    operation=EditOperationKind.WRITE,
                    content=runbook_document,
                    reason="Persist generated runbook through safe edit phase",
                )
            )

        test_plan_document = test_design_result.outputs.get("test_plan_document")
        if isinstance(test_plan_document, str) and test_plan_document.strip():
            operations.append(
                EditRequest(
                    relative_path="docs/test-plan.md",
                    operation=EditOperationKind.WRITE,
                    content=test_plan_document,
                    reason="Persist generated test plan through safe edit phase",
                )
            )

        test_results_document = test_execution_result.outputs.get(
            "test_results_document"
        )
        if isinstance(test_results_document, str) and test_results_document.strip():
            operations.append(
                EditRequest(
                    relative_path="docs/test-results.md",
                    operation=EditOperationKind.WRITE,
                    content=test_results_document,
                    reason="Persist generated test results through safe edit phase",
                )
            )

        review_report = review_result.outputs.get("review_report")
        if isinstance(review_report, str) and review_report.strip():
            operations.append(
                EditRequest(
                    relative_path="docs/review-report.md",
                    operation=EditOperationKind.WRITE,
                    content=review_report,
                    reason="Persist generated review report through safe edit phase",
                )
            )

        if fix_result is not None:
            fix_report = fix_result.outputs.get("fix_report")
            if isinstance(fix_report, str) and fix_report.strip():
                operations.append(
                    EditRequest(
                        relative_path="docs/fix-report.md",
                        operation=EditOperationKind.WRITE,
                        content=fix_report,
                        reason="Persist generated fix report through safe edit phase",
                    )
                )

        final_summary = self._build_final_summary(
            state=state,
            requirement=requirement,
            implementation_result=implementation_result,
            test_design_result=test_design_result,
            test_execution_result=test_execution_result,
            review_result=review_result,
            fix_result=fix_result,
        )
        operations.append(
            EditRequest(
                relative_path="docs/final-summary.md",
                operation=EditOperationKind.WRITE,
                content=final_summary,
                reason="Persist final summary through safe edit phase",
            )
        )

        operations.append(
            EditRequest(
                relative_path=f"artifacts/workflows/{state.workflow_id}/workflow-details.json",
                operation=EditOperationKind.WRITE,
                content=self._json_text(
                    {
                        "workflow": state.to_dict(),
                        "requirements_result": self._result_to_dict(
                            requirements_result
                        ),
                        "planning_result": self._result_to_dict(planning_result),
                        "documentation_result": self._result_to_dict(
                            documentation_result
                        ),
                        "implementation_result": self._result_to_dict(
                            implementation_result
                        ),
                        "test_design_result": self._result_to_dict(test_design_result),
                        "test_execution_result": self._result_to_dict(
                            test_execution_result
                        ),
                        "review_result": self._result_to_dict(review_result),
                        "fix_result": self._result_to_dict(fix_result)
                        if fix_result
                        else None,
                    }
                ),
                reason="Persist workflow details through safe edit phase",
            )
        )# END STRUCTURED EDIT: SkeletonOrchestrator._build_safe_edit_operations

        return operations

    def _apply_structured_code_edit_phase(
        self,
        *,
        state: WorkflowState,
        implementation_result: AgentResult,
        fix_result: AgentResult | None,
    ) -> list[str]:
        implementation = implementation_result.outputs.get("implementation", {})
        if not isinstance(implementation, dict):
            return []

        applied_paths: list[str] = []
        requests = self._build_structured_code_edit_requests(implementation)

        if fix_result is not None:
            fix_plan = fix_result.outputs.get("fix_plan", {})
            if isinstance(fix_plan, dict):
                requests.extend(self._build_structured_fix_code_edit_requests(fix_plan))

        for request in requests:
            result = self.code_editor.apply(request)
            if (
                result.ok
                and result.changed
                and request.relative_path not in applied_paths
            ):
                applied_paths.append(request.relative_path)

        if applied_paths:
            state.add_note(
                "structured code edit phase で src/devagents 配下の更新を適用した。"
            )

        return applied_paths

    def _build_structured_code_edit_requests(
        self,
        implementation: dict[str, Any],
    ) -> list[CodeEditRequest]:
        requests: list[CodeEditRequest] = []
        edit_proposals = implementation.get("edit_proposals", [])
        if not isinstance(edit_proposals, list):
            return requests

        for item in edit_proposals:
            requests.extend(self._code_edit_requests_from_proposal(item))
        return requests

    def _build_structured_fix_code_edit_requests(
        self,
        fix_plan: dict[str, Any],
    ) -> list[CodeEditRequest]:
        requests: list[CodeEditRequest] = []
        edit_proposals = fix_plan.get("edit_proposals", [])
        if not isinstance(edit_proposals, list):
            return requests

        for item in edit_proposals:
            requests.extend(self._code_edit_requests_from_proposal(item))
        return requests

    def _code_edit_requests_from_proposal(
        self,
        proposal: Any,
    ) -> list[CodeEditRequest]:
        if not isinstance(proposal, dict):
            return []

        targets = proposal.get("targets", [])
        edits = proposal.get("edits", [])
        instructions = proposal.get("instructions", [])

        if not isinstance(targets, list) or not isinstance(edits, list):
            return []

        normalized_instructions = [
            str(item).strip() for item in instructions if str(item).strip()
        ]
        reason = (
            " | ".join(normalized_instructions)
            or str(
                proposal.get("summary", "Apply structured code edit proposal")
            ).strip()
        )

        requests: list[CodeEditRequest] = []
        for target in targets:
            target_path = str(target).strip()
            if not target_path.startswith("src/devagents/"):
                continue

            for edit in edits:
                request = self._code_edit_request_from_edit(
                    target_path=target_path,
                    edit=edit,
                    reason=reason,
                )
                if request is not None:
                    requests.append(request)

        return requests

    def _code_edit_request_from_edit(
        self,
        *,
        target_path: str,
        edit: Any,
        reason: str,
    ) -> CodeEditRequest | None:
        if not isinstance(edit, dict):
            return None

        edit_kind = str(edit.get("edit_kind", "")).strip()
        target_symbol = str(edit.get("target_symbol", "")).strip()
        intent = str(edit.get("intent", "")).strip()
        request_reason = intent or reason or "Apply structured code edit proposal"

        if edit_kind != "replace_block" or not target_symbol:
            return None

        begin_marker = f"# BEGIN STRUCTURED EDIT: {target_symbol}"
        end_marker = f"# END STRUCTURED EDIT: {target_symbol}"
        content = self._build_structured_replacement_content(
            target_path=target_path,
            target_symbol=target_symbol,
            request_reason=request_reason,
        )

        return CodeEditRequest(
            relative_path=target_path,
            kind=CodeEditKind.REPLACE_MARKED_BLOCK,
            reason=request_reason,
            begin_marker=begin_marker,
            end_marker=end_marker,
            content=content,
        )

    def _build_structured_replacement_content(
        self,
        *,
        target_path: str,
        target_symbol: str,
        request_reason: str,
    ) -> str:
        if (
            target_path == "src/devagents/main.py"
            and target_symbol == "SkeletonOrchestrator._build_safe_edit_operations"
        ):
            return """
        operations: list[EditRequest] = []

        design_document = documentation_result.outputs.get("design_document")
        if isinstance(design_document, str) and design_document.strip():
            operations.append(
                EditRequest(
                    relative_path="docs/design.md",
                    operation=EditOperationKind.WRITE,
                    content=design_document,
                    reason="Persist generated design document through safe edit phase",
                )
            )

        runbook_document = documentation_result.outputs.get("runbook_document")
        if isinstance(runbook_document, str) and runbook_document.strip():
            operations.append(
                EditRequest(
                    relative_path="docs/runbook.md",
                    operation=EditOperationKind.WRITE,
                    content=runbook_document,
                    reason="Persist generated runbook through safe edit phase",
                )
            )

        test_plan_document = test_design_result.outputs.get("test_plan_document")
        if isinstance(test_plan_document, str) and test_plan_document.strip():
            operations.append(
                EditRequest(
                    relative_path="docs/test-plan.md",
                    operation=EditOperationKind.WRITE,
                    content=test_plan_document,
                    reason="Persist generated test plan through safe edit phase",
                )
            )

        test_results_document = test_execution_result.outputs.get(
            "test_results_document"
        )
        if isinstance(test_results_document, str) and test_results_document.strip():
            operations.append(
                EditRequest(
                    relative_path="docs/test-results.md",
                    operation=EditOperationKind.WRITE,
                    content=test_results_document,
                    reason="Persist generated test results through safe edit phase",
                )
            )

        review_report = review_result.outputs.get("review_report")
        if isinstance(review_report, str) and review_report.strip():
            operations.append(
                EditRequest(
                    relative_path="docs/review-report.md",
                    operation=EditOperationKind.WRITE,
                    content=review_report,
                    reason="Persist generated review report through safe edit phase",
                )
            )

        if fix_result is not None:
            fix_report = fix_result.outputs.get("fix_report")
            if isinstance(fix_report, str) and fix_report.strip():
                operations.append(
                    EditRequest(
                        relative_path="docs/fix-report.md",
                        operation=EditOperationKind.WRITE,
                        content=fix_report,
                        reason="Persist generated fix report through safe edit phase",
                    )
                )

        final_summary = self._build_final_summary(
            state=state,
            requirement=requirement,
            implementation_result=implementation_result,
            test_design_result=test_design_result,
            test_execution_result=test_execution_result,
            review_result=review_result,
            fix_result=fix_result,
        )
        operations.append(
            EditRequest(
                relative_path="docs/final-summary.md",
                operation=EditOperationKind.WRITE,
                content=final_summary,
                reason="Persist final summary through safe edit phase",
            )
        )

        operations.append(
            EditRequest(
                relative_path=f"artifacts/workflows/{state.workflow_id}/workflow-details.json",
                operation=EditOperationKind.WRITE,
                content=self._json_text(
                    {
                        "workflow": state.to_dict(),
                        "requirements_result": self._result_to_dict(
                            requirements_result
                        ),
                        "planning_result": self._result_to_dict(planning_result),
                        "documentation_result": self._result_to_dict(
                            documentation_result
                        ),
                        "implementation_result": self._result_to_dict(
                            implementation_result
                        ),
                        "test_design_result": self._result_to_dict(test_design_result),
                        "test_execution_result": self._result_to_dict(
                            test_execution_result
                        ),
                        "review_result": self._result_to_dict(review_result),
                        "fix_result": self._result_to_dict(fix_result)
                        if fix_result
                        else None,
                    }
                ),
                reason="Persist workflow details through safe edit phase",
            )
        )""".lstrip("\n")

        if (
            target_path == "src/devagents/runtime/editor.py"
            and target_symbol == "SafeEditor.apply"
        ):
            return """
        \"\"\"Apply a single edit request.\"\"\"
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
        )""".lstrip("\n")

        if (
            target_path == "src/devagents/agents/implementation.py"
            and target_symbol == "ImplementationAgent.run"
        ):
            return """
        normalized_requirements = self._as_dict(
            task.inputs.get("normalized_requirements", {})
        )
        plan = self._as_dict(task.inputs.get("plan", {}))
        copilot_response = str(task.inputs.get("copilot_response", "")).strip()

        objective = str(
            normalized_requirements.get("objective") or state.requirement
        ).strip()
        constraints = self._normalize_list(normalized_requirements.get("constraints"))
        acceptance_criteria = self._normalize_list(
            normalized_requirements.get("acceptance_criteria")
        )
        open_questions = self._normalize_list(
            normalized_requirements.get("open_questions")
        )
        plan_phases = self._normalize_list(plan.get("phases"))
        task_breakdown = self._normalize_task_breakdown(plan.get("task_breakdown"))

        implementation = {
            "objective": objective,
            "summary": "実装フェーズで着手すべき変更案を整理した。",
            "strategy": [
                "Keep changes small and align with the existing repository structure",
                "Isolate Copilot SDK integration behind runtime/copilot_client.py",
                "Persist workflow and session state before and after meaningful milestones",
                "Prefer explicit workflow state transitions over implicit behavior",
                "Prefer structured code edits over free-form append-only source mutations",
            ],
            "proposed_modules": [
                {
                    "path": "src/devagents/agents/implementation.py",
                    "purpose": "Generate implementation proposals and concrete code-change slices.",
                },
                {
                    "path": "src/devagents/agents/documentation.py",
                    "purpose": "Generate design and operational documentation artifacts.",
                },
                {
                    "path": "src/devagents/runtime/copilot_client.py",
                    "purpose": "Encapsulate Copilot SDK session lifecycle and request execution.",
                },
                {
                    "path": "src/devagents/orchestration/session_manager.py",
                    "purpose": "Manage session rotation, snapshots, and resume prompts.",
                },
                {
                    "path": "src/devagents/orchestration/state_store.py",
                    "purpose": "Persist workflow state, summaries, and session snapshots.",
                },
                {
                    "path": "src/devagents/runtime/editor.py",
                    "purpose": "Apply allowlisted edits safely to docs, artifacts, and approved source files.",
                },
            ],
            "code_change_slices": [
                {
                    "slice_id": "implementation-agent",
                    "goal": "Add an implementation agent that turns plans into executable change proposals.",
                    "targets": [
                        "src/devagents/agents/implementation.py",
                    ],
                    "depends_on": [
                        "planning",
                    ],
                },
                {
                    "slice_id": "documentation-agent",
                    "goal": "Add a documentation agent that produces design and runbook artifacts.",
                    "targets": [
                        "src/devagents/agents/documentation.py",
                    ],
                    "depends_on": [
                        "planning",
                    ],
                },
                {
                    "slice_id": "orchestrator-integration",
                    "goal": "Wire documentation and implementation phases into the orchestrator.",
                    "targets": [
                        "src/devagents/main.py",
                    ],
                    "depends_on": [
                        "implementation-agent",
                        "documentation-agent",
                    ],
                },
                {
                    "slice_id": "artifact-persistence",
                    "goal": "Persist implementation and documentation outputs into docs/ and artifacts/.",
                    "targets": [
                        "docs/design.md",
                        "artifacts/workflows/<workflow_id>/workflow-details.json",
                        "artifacts/summaries/<workflow_id>/run-summary.json",
                    ],
                    "depends_on": [
                        "orchestrator-integration",
                    ],
                },
                {
                    "slice_id": "src-allowlisted-edit-phase",
                    "goal": "Promote approved implementation proposals into structured source edits under src/devagents/.",
                    "targets": [
                        "src/devagents/main.py",
                        "src/devagents/runtime/editor.py",
                        "src/devagents/agents/implementation.py",
                    ],
                    "depends_on": [
                        "orchestrator-integration",
                        "artifact-persistence",
                    ],
                },
            ],
            "deliverables": [
                "docs/design.md",
                "docs/final-summary.md",
                "artifacts/workflows/<workflow_id>/workflow-details.json",
                "artifacts/summaries/<workflow_id>/run-summary.json",
                "src/devagents/**/*.py allowlisted edit proposals",
            ],
            "acceptance_criteria": acceptance_criteria,
            "constraints": constraints,
            "plan_phases": plan_phases,
            "task_breakdown": task_breakdown,
            "open_questions": open_questions,
            "copilot_response_excerpt": copilot_response[:500]
            if copilot_response
            else "",
            "edit_proposals": [
                {
                    "proposal_id": "src-structured-main-update",
                    "mode": "structured_update",
                    "targets": [
                        "src/devagents/main.py",
                    ],
                    "summary": "Wire implementation outputs into the orchestrator through a structured source edit path.",
                    "instructions": [
                        "Keep the change small and limited to orchestration flow integration.",
                        "Do not edit files outside src/devagents/ without an explicit policy update.",
                        "Re-run test_execution and review after applying the source edit.",
                    ],
                    "edits": [
                        {
                            "edit_kind": "replace_block",
                            "target_symbol": "SkeletonOrchestrator._build_safe_edit_operations",
                            "intent": "Replace append-only SAFE-EDIT source mutations with structured source edit requests.",
                        },
                    ],
                },
                {
                    "proposal_id": "src-structured-editor-update",
                    "mode": "structured_update",
                    "targets": [
                        "src/devagents/runtime/editor.py",
                    ],
                    "summary": "Extend the safe editor policy to support approved src/devagents edits through structured updates.",
                    "instructions": [
                        "Restrict edits to src/devagents/ and preserve protected roots.",
                        "Require approval for overwrite and delete operations.",
                        "Record edited files in workflow artifacts after the change.",
                    ],
                    "edits": [
                        {
                            "edit_kind": "replace_block",
                            "target_symbol": "SafeEditor.apply",
                            "intent": "Route approved source edits through structured update handling instead of append-only notes.",
                        },
                    ],
                },
                {
                    "proposal_id": "src-structured-implementation-update",
                    "mode": "structured_update",
                    "targets": [
                        "src/devagents/agents/implementation.py",
                    ],
                    "summary": "Promote implementation proposals into structured code-edit payloads for approved source files.",
                    "instructions": [
                        "Emit structured edit payloads with explicit target symbols or blocks.",
                        "Avoid free-form append-only source mutations.",
                        "Keep each edit proposal scoped to one behavior change.",
                    ],
                    "edits": [
                        {
                            "edit_kind": "replace_block",
                            "target_symbol": "ImplementationAgent.run",
                            "intent": "Emit structured edit proposals that can be consumed by a code editing runtime.",
                        },
                    ],
                },
            ],
        }

        next_actions = [
            "Add documentation and implementation agents to the orchestrator",
            "Persist generated design and implementation proposal artifacts",
            "Extend the workflow into test_design, test_execution, and review phases",
            "Promote structured src/devagents edit proposals into the safe edit phase",
        ]

        risks = [
            "実コード変更前に承認フローが未確定だと、破壊的変更の扱いが曖昧になる",
            "実装提案と既存アーキテクチャの整合確認が不足すると差分が広がる可能性がある",
        ]
        if open_questions:
            risks.append(
                "未解決の open questions が残っているため、実装着手前に確認が必要"
            )

        return AgentResult.success(
            "実装提案を生成し、次のコード変更スライスを整理した。",
            outputs={
                "implementation": implementation,
                "open_questions": open_questions,
            },
            next_actions=next_actions,
            risks=risks,
            metrics={
                "constraint_count": len(constraints),
                "acceptance_criteria_count": len(acceptance_criteria),
                "task_breakdown_count": len(task_breakdown),
                "code_change_slice_count": len(implementation["code_change_slices"]),
                "open_question_count": len(open_questions),
            },
        )""".lstrip("\n")

        return (
            f"\n        # Structured edit intent: {request_reason}\n"
            f"        raise NotImplementedError("
            f'"No concrete structured replacement is defined for {target_symbol} in {target_path}."'
            f")\n"
        )

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

    def _json_text(self, payload: dict[str, Any]) -> str:
        import json

        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    def _write_workflow_artifacts(
        self,
        *,
        state: WorkflowState,
        requirement: str,
        requirements_result: AgentResult,
        planning_result: AgentResult,
        documentation_result: AgentResult,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
        test_execution_result: AgentResult,
        review_result: AgentResult,
        fix_result: AgentResult | None,
        session_snapshot: Any,
    ) -> None:

        workflow_state_path = self.state_store.save_workflow_state(state)
        state.add_artifact(workflow_state_path.as_posix())

        session_snapshot_path = self.state_store.save_session_snapshot(session_snapshot)
        state.add_artifact(session_snapshot_path.as_posix())

        run_summary_payload = {
            "workflow_id": state.workflow_id,
            "model": state.model,
            "phase": state.phase.value,
            "requirement": requirement,
            "summary": state.summary(),
            "session": {
                "session_id": state.session_id,
                "parent_session_id": state.parent_session_id,
                "token_usage_ratio": session_snapshot.token_usage_ratio,
                "resume_prompt": self.session_manager.build_resume_prompt(
                    session_snapshot
                ),
            },
            "next_actions": [
                "Expand safe edit phase from docs/artifacts into source-code allowlists",
                "Add session resume flow using resume_session",
                "Promote fix loop outputs into concrete code edits when needed",
            ],
        }
        run_summary_path = self.state_store.save_run_summary(
            state.workflow_id,
            run_summary_payload,
        )
        state.add_artifact(run_summary_path.as_posix())

    def _result_to_dict(self, result: AgentResult) -> dict[str, Any]:
        return {
            "status": result.status,
            "summary": result.summary,
            "outputs": result.outputs,
            "artifacts": result.artifacts,
            "next_actions": result.next_actions,
            "risks": result.risks,
            "metrics": result.metrics,
        }

    def _build_final_summary(
        self,
        *,
        state: WorkflowState,
        requirement: str,
        implementation_result: AgentResult,
        test_design_result: AgentResult,
        test_execution_result: AgentResult,
        review_result: AgentResult,
        fix_result: AgentResult | None,
    ) -> str:
        implementation = implementation_result.outputs.get("implementation", {})
        code_change_slices = implementation.get("code_change_slices", [])
        test_plan = test_design_result.outputs.get("test_plan", {})
        test_results = test_execution_result.outputs.get("test_results", {})
        review = review_result.outputs.get("review", {})
        fix_plan = fix_result.outputs.get("fix_plan", {}) if fix_result else {}
        next_actions = (
            fix_result.next_actions
            if fix_result and fix_result.next_actions
            else review_result.next_actions or implementation_result.next_actions
        )

        lines = [
            "# Final Summary",
            "",
            "## Requirement",
            requirement,
            "",
            "## Workflow Status",
            f"- workflow_id: {state.workflow_id}",
            f"- phase: {state.phase.value}",
            f"- model: {state.model}",
            f"- session_id: {state.session_id or 'none'}",
            "",
            "## Completed Tasks",
        ]
        lines.extend(f"- {task.task_id}" for task in state.completed_tasks())
        lines.extend(
            [
                "",
                "## Proposed Code Change Slices",
            ]
        )

        if isinstance(code_change_slices, list) and code_change_slices:
            for item in code_change_slices:
                if not isinstance(item, dict):
                    continue
                slice_id = str(item.get("slice_id", "unknown")).strip()
                goal = str(item.get("goal", "")).strip()
                lines.append(f"- {slice_id}: {goal or 'TBD'}")
        else:
            lines.append("- none")

        lines.extend(
            [
                "",
                "## Test Summary",
                f"- test_case_count: {len(test_plan.get('test_cases', [])) if isinstance(test_plan, dict) else 0}",
                f"- executed_check_count: {len(test_results.get('executed_checks', [])) if isinstance(test_results, dict) else 0}",
                f"- test_status: {test_results.get('status', 'unknown') if isinstance(test_results, dict) else 'unknown'}",
                "",
                "## Review Summary",
                f"- severity: {review.get('severity', 'unknown') if isinstance(review, dict) else 'unknown'}",
            ]
        )

        unresolved_issues = (
            review.get("unresolved_issues", []) if isinstance(review, dict) else []
        )
        if isinstance(unresolved_issues, list) and unresolved_issues:
            lines.append("- unresolved_issues:")
            lines.extend(f"  - {item}" for item in unresolved_issues)
        else:
            lines.append("- unresolved_issues: none")

        lines.extend(
            [
                "",
                "## Fix Summary",
                f"- fix_needed: {fix_plan.get('fix_needed', False) if isinstance(fix_plan, dict) else False}",
                f"- fix_severity: {fix_plan.get('severity', 'none') if isinstance(fix_plan, dict) else 'none'}",
                f"- fix_slice_count: {len(fix_plan.get('fix_slices', [])) if isinstance(fix_plan, dict) else 0}",
                "",
                "## Next Actions",
            ]
        )
        if next_actions:
            lines.extend(f"- {item}" for item in next_actions)
        else:
            lines.append("- none")

        return "\n".join(lines).strip() + "\n"

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
