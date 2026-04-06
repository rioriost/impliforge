"""Helpers for safe edit orchestration and structured code edit promotion."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from impliforge.agents.base import AgentResult
from impliforge.orchestration.artifact_writer import WorkflowArtifactWriter
from impliforge.orchestration.workflow import WorkflowState
from impliforge.runtime.code_editing import (
    CodeEditKind,
    CodeEditRequest,
    CodeEditRiskFlag,
    StructuredCodeEditor,
    proposal_consumability_is_structured,
)
from impliforge.runtime.code_editing import (
    proposal_policy_requires_explicit_approval as code_policy_requires_explicit_approval,
)
from impliforge.runtime.editor import (
    EditOperationKind,
    EditRequest,
    SafeEditor,
)
from impliforge.runtime.editor import (
    proposal_policy_requires_explicit_approval as file_policy_requires_explicit_approval,
)


class EditPhaseOrchestrator:
    """Coordinate safe edit and structured code edit phases."""

    def __init__(
        self,
        *,
        safe_editor: SafeEditor,
        code_editor: StructuredCodeEditor,
        artifact_writer: WorkflowArtifactWriter,
    ) -> None:
        self.safe_editor = safe_editor
        self.code_editor = code_editor
        self.artifact_writer = artifact_writer

    def apply_safe_edit_phase(
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
        """Apply allowlisted file edits and structured source edits."""
        operations = self.build_safe_edit_operations(
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
        safe_edit_results: list[dict[str, Any]] = []

        for request, result in zip(operations, results, strict=False):
            safe_edit_results.append(
                {
                    "proposal_id": request.proposal_id,
                    "relative_path": result.relative_path,
                    "operation": request.operation.value,
                    "approval_policy": request.approval_policy,
                    "consumability": request.consumability,
                    "ok": result.ok,
                    "changed": result.changed,
                    "message": result.message,
                }
            )
            if result.ok and result.changed:
                self._record_path(state, result.relative_path, applied_paths)
            elif not result.ok:
                denied_paths.append(f"{result.relative_path}: {result.message}")

        if safe_edit_results:
            state.merge_task_outputs(
                "implementation",
                {
                    "safe_edit_results": safe_edit_results,
                    "safe_edit_summary": {
                        "request_count": len(safe_edit_results),
                        "applied_count": len(applied_paths),
                        "denied_count": len(denied_paths),
                        "applied_paths": list(applied_paths),
                        "denied_paths": list(denied_paths),
                    },
                },
            )
            state.add_artifact(
                f"artifacts/workflows/{state.workflow_id}/safe-edit-results.json"
            )

        structured_edit_paths, structured_denied_paths = (
            self.apply_structured_code_edit_phase(
                state=state,
                implementation_result=implementation_result,
                fix_result=fix_result,
            )
        )
        for path in structured_edit_paths:
            self._record_path(state, path, applied_paths)
        denied_paths.extend(structured_denied_paths)

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

    def build_safe_edit_operations(
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
        """Build allowlisted file edit requests for docs and artifacts."""
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

        final_summary = self.artifact_writer.build_final_summary(
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
                content=self.artifact_writer.json_text(
                    {
                        "workflow": state.to_dict(),
                        "requirements_result": self.artifact_writer.result_to_dict(
                            requirements_result
                        ),
                        "planning_result": self.artifact_writer.result_to_dict(
                            planning_result
                        ),
                        "documentation_result": self.artifact_writer.result_to_dict(
                            documentation_result
                        ),
                        "implementation_result": self.artifact_writer.result_to_dict(
                            implementation_result
                        ),
                        "test_design_result": self.artifact_writer.result_to_dict(
                            test_design_result
                        ),
                        "test_execution_result": self.artifact_writer.result_to_dict(
                            test_execution_result
                        ),
                        "review_result": self.artifact_writer.result_to_dict(
                            review_result
                        ),
                        "fix_result": self.artifact_writer.result_to_dict(fix_result)
                        if fix_result
                        else None,
                    }
                ),
                reason="Persist workflow details through safe edit phase",
            )
        )

        return operations

    def apply_structured_code_edit_phase(
        self,
        *,
        state: WorkflowState,
        implementation_result: AgentResult,
        fix_result: AgentResult | None,
    ) -> tuple[list[str], list[str]]:
        """Apply structured source edits under `src/impliforge/`."""
        implementation = implementation_result.outputs.get("implementation", {})
        if not isinstance(implementation, dict):
            return [], []

        applied_paths: list[str] = []
        denied_paths: list[str] = []
        requests = self.build_structured_code_edit_requests(implementation)

        if fix_result is not None:
            fix_plan = fix_result.outputs.get("fix_plan", {})
            if isinstance(fix_plan, dict):
                requests.extend(self.build_structured_fix_code_edit_requests(fix_plan))

        execution_results: list[dict[str, Any]] = []
        for request in requests:
            result = self.code_editor.apply(request)
            execution_results.append(
                {
                    "proposal_id": request.proposal_id,
                    "relative_path": request.relative_path,
                    "kind": request.kind.value,
                    "approval_policy": request.approval_policy,
                    "consumability": request.consumability,
                    "ok": result.ok,
                    "changed": result.changed,
                    "message": getattr(result, "message", ""),
                }
            )
            if (
                result.ok
                and result.changed
                and request.relative_path not in applied_paths
            ):
                applied_paths.append(request.relative_path)
            elif not result.ok:
                message = (
                    getattr(result, "message", "") or "structured code edit denied"
                )
                denied_paths.append(f"{request.relative_path}: {message}")

        if execution_results:
            state.merge_task_outputs(
                "implementation",
                {
                    "structured_code_edit_results": execution_results,
                    "structured_code_edit_summary": {
                        "request_count": len(execution_results),
                        "applied_count": len(applied_paths),
                        "denied_count": len(denied_paths),
                        "applied_paths": list(applied_paths),
                        "denied_paths": list(denied_paths),
                    },
                },
            )
            state.add_artifact(
                f"artifacts/workflows/{state.workflow_id}/structured-code-edit-results.json"
            )

        if applied_paths:
            state.add_note(
                "structured code edit phase で src/impliforge 配下の更新を適用した。"
            )

        return applied_paths, denied_paths

    def build_structured_code_edit_requests(
        self,
        implementation: dict[str, Any],
    ) -> list[CodeEditRequest]:
        """Build structured code edit requests from implementation proposals."""
        requests: list[CodeEditRequest] = []
        edit_proposals = implementation.get("edit_proposals", [])
        if not isinstance(edit_proposals, list):
            return requests

        for item in edit_proposals:
            requests.extend(self.code_edit_requests_from_proposal(item))
        return requests

    def build_structured_fix_code_edit_requests(
        self,
        fix_plan: dict[str, Any],
    ) -> list[CodeEditRequest]:
        """Build structured code edit requests from fix proposals."""
        requests: list[CodeEditRequest] = []
        edit_proposals = fix_plan.get("edit_proposals", [])
        if not isinstance(edit_proposals, list):
            return requests

        for item in edit_proposals:
            requests.extend(self.code_edit_requests_from_proposal(item))
        return requests

    def code_edit_requests_from_proposal(
        self,
        proposal: Any,
    ) -> list[CodeEditRequest]:
        """Convert a proposal payload into structured code edit requests."""
        normalized = self._normalize_edit_proposal(proposal)
        if normalized is None:
            return []

        reason = (
            " | ".join(normalized["instructions"])
            or normalized["summary"]
            or "Apply structured code edit proposal"
        )
        risk_flags = self._extract_code_edit_risk_flags(normalized)

        requests: list[CodeEditRequest] = []
        for target_path in normalized["targets"]:
            if not target_path.startswith("src/impliforge/"):
                continue

            for edit in normalized["edits"]:
                request = self.code_edit_request_from_edit(
                    target_path=target_path,
                    edit=edit,
                    reason=reason,
                    risk_flags=risk_flags,
                    proposal_id=normalized["proposal_id"],
                    approval_policy=normalized["approval_policy"],
                    consumability=normalized["consumability"],
                )
                if request is not None:
                    requests.append(request)

        return requests

    def code_edit_request_from_edit(
        self,
        *,
        target_path: str,
        edit: Any,
        reason: str,
        risk_flags: tuple[CodeEditRiskFlag, ...] = (),
        proposal_id: str = "",
        approval_policy: str = "",
        consumability: str = "",
    ) -> CodeEditRequest | None:
        """Convert a single edit payload into a structured code edit request."""
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
        content = self.build_structured_replacement_content(
            target_path=target_path,
            target_symbol=target_symbol,
            request_reason=request_reason,
        )

        return CodeEditRequest(
            relative_path=target_path,
            kind=CodeEditKind.REPLACE_MARKED_BLOCK,
            reason=request_reason,
            risk_flags=risk_flags,
            proposal_id=proposal_id,
            approval_policy=approval_policy,
            consumability=consumability,
            begin_marker=begin_marker,
            end_marker=end_marker,
            content=content,
        )

    def _extract_code_edit_risk_flags(
        self,
        proposal: Any,
    ) -> tuple[CodeEditRiskFlag, ...]:
        """Extract structured risk flags from a proposal payload."""
        if not isinstance(proposal, dict):
            return ()

        raw_flags = proposal.get("risk_flags", [])
        if not isinstance(raw_flags, list):
            return ()

        normalized_flags: list[CodeEditRiskFlag] = []
        for item in raw_flags:
            value = str(item).strip()
            if not value:
                continue
            try:
                flag = CodeEditRiskFlag(value)
            except ValueError:
                continue
            if flag not in normalized_flags:
                normalized_flags.append(flag)

        return tuple(normalized_flags)

    def _normalize_edit_proposal(
        self,
        proposal: Any,
    ) -> dict[str, Any] | None:
        """Validate and normalize a structured edit proposal."""
        if not isinstance(proposal, dict):
            return None

        proposal_id = str(proposal.get("proposal_id", "")).strip()
        summary = str(proposal.get("summary", "")).strip()
        approval_policy = str(proposal.get("approval_policy", "")).strip()
        consumability = str(proposal.get("consumability", "")).strip()

        targets = proposal.get("targets", [])
        instructions = proposal.get("instructions", [])
        edits = proposal.get("edits", [])

        if not proposal_id or not summary:
            return None
        if not isinstance(targets, list) or not isinstance(instructions, list):
            return None
        if not isinstance(edits, list) or not edits:
            return None
        if not approval_policy or not consumability:
            return None
        if not proposal.get("safe_edit_ready", False):
            return None
        if not proposal_consumability_is_structured(consumability):
            return None
        if not code_policy_requires_explicit_approval(approval_policy):
            return None
        if not file_policy_requires_explicit_approval(approval_policy):
            return None

        normalized_targets = [
            str(item).strip() for item in targets if str(item).strip()
        ]
        normalized_instructions = [
            str(item).strip() for item in instructions if str(item).strip()
        ]
        normalized_edits = [item for item in edits if isinstance(item, dict)]

        if not normalized_targets or not normalized_edits:
            return None

        return {
            "proposal_id": proposal_id,
            "summary": summary,
            "targets": normalized_targets,
            "instructions": normalized_instructions,
            "edits": normalized_edits,
            "approval_policy": approval_policy,
            "consumability": consumability,
            "risk_flags": proposal.get("risk_flags", []),
        }

    def build_structured_replacement_content(
        self,
        *,
        target_path: str,
        target_symbol: str,
        request_reason: str,
    ) -> str:
        """Return replacement content for known structured edit targets."""
        if (
            target_path == "src/impliforge/runtime/editor.py"
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
)
""".lstrip("\n")

        if (
            target_path == "src/impliforge/agents/implementation.py"
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
            "path": "src/impliforge/agents/implementation.py",
            "purpose": "Generate implementation proposals and concrete code-change slices.",
        },
        {
            "path": "src/impliforge/agents/documentation.py",
            "purpose": "Generate design and operational documentation artifacts.",
        },
        {
            "path": "src/impliforge/runtime/copilot_client.py",
            "purpose": "Encapsulate Copilot SDK session lifecycle and request execution.",
        },
        {
            "path": "src/impliforge/orchestration/session_manager.py",
            "purpose": "Manage session rotation, snapshots, and resume prompts.",
        },
        {
            "path": "src/impliforge/orchestration/state_store.py",
            "purpose": "Persist workflow state, summaries, and session snapshots.",
        },
        {
            "path": "src/impliforge/runtime/editor.py",
            "purpose": "Apply allowlisted edits safely to docs, artifacts, and approved source files.",
        },
    ],
    "code_change_slices": [
        {
            "slice_id": "implementation-agent",
            "goal": "Add an implementation agent that turns plans into executable change proposals.",
            "targets": [
                "src/impliforge/agents/implementation.py",
            ],
            "depends_on": [
                "planning",
            ],
        },
        {
            "slice_id": "documentation-agent",
            "goal": "Add a documentation agent that produces design and runbook artifacts.",
            "targets": [
                "src/impliforge/agents/documentation.py",
            ],
            "depends_on": [
                "planning",
            ],
        },
        {
            "slice_id": "orchestrator-integration",
            "goal": "Wire documentation and implementation phases into the orchestrator.",
            "targets": [
                "src/impliforge/main.py",
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
            "goal": "Promote approved implementation proposals into structured source edits under src/impliforge/.",
            "targets": [
                "src/impliforge/main.py",
                "src/impliforge/runtime/editor.py",
                "src/impliforge/agents/implementation.py",
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
        "src/impliforge/**/*.py allowlisted edit proposals",
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
            "proposal_id": "src-structured-editor-update",
            "mode": "structured_update",
            "targets": [
                "src/impliforge/runtime/editor.py",
            ],
            "summary": "Extend the safe editor policy to support approved src/impliforge edits through structured updates.",
            "instructions": [
                "Restrict edits to src/impliforge/ and preserve protected roots.",
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
                "src/impliforge/agents/implementation.py",
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
    "Promote structured src/impliforge edit proposals into the safe edit phase",
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
)
""".lstrip("\n")

        return (
            f"\n# Structured edit intent: {request_reason}\n"
            f'raise NotImplementedError("No concrete structured replacement is defined for '
            f'{target_symbol} in {target_path}.")\n'
        )

    def _record_path(
        self,
        state: WorkflowState,
        path: str,
        applied_paths: list[str],
    ) -> None:
        normalized = Path(path).as_posix()
        if normalized not in applied_paths:
            applied_paths.append(normalized)
        state.add_artifact(normalized)
        state.add_changed_file(normalized)
