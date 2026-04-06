"""Model routing policies for the impliforge workflow."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

DEFAULT_MODEL = "gpt-5.4"


class TaskKind(StrEnum):
    """High-level task categories used for model selection."""

    REQUIREMENTS = "requirements"
    PLANNING = "planning"
    DOCUMENTATION = "documentation"
    IMPLEMENTATION = "implementation"
    TEST_DESIGN = "test_design"
    TEST_EXECUTION = "test_execution"
    REVIEW = "review"
    FIX = "fix"
    SESSION_MANAGEMENT = "session_management"
    SUMMARIZATION = "summarization"
    UNKNOWN = "unknown"


class RoutingMode(StrEnum):
    """Top-level routing mode."""

    BALANCED = "balanced"
    QUALITY = "quality"
    COST_SAVER = "cost_saver"


@dataclass(slots=True)
class ModelCandidate:
    """A model option that can be selected by the router."""

    name: str
    quality_score: int
    cost_score: int
    latency_score: int
    max_context_tokens: int | None = None
    tags: set[str] = field(default_factory=set)

    def supports(self, required_tags: set[str]) -> bool:
        return required_tags.issubset(self.tags)


@dataclass(slots=True)
class RoutingRequest:
    """Structured input for model routing."""

    task_kind: TaskKind
    difficulty: int = 3
    mode: RoutingMode = RoutingMode.BALANCED
    requires_long_context: bool = False
    requires_high_reasoning: bool = False
    latency_sensitive: bool = False
    retry_count: int = 0
    estimated_input_tokens: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalized_difficulty(self) -> int:
        if self.difficulty < 1:
            return 1
        if self.difficulty > 5:
            return 5
        return self.difficulty


@dataclass(slots=True)
class RoutingDecision:
    """Result of model routing."""

    selected_model: str
    fallback_model: str | None
    reason: str
    task_kind: TaskKind
    mode: RoutingMode
    score_breakdown: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["task_kind"] = self.task_kind.value
        payload["mode"] = self.mode.value
        return payload


class ModelRouter:
    """Simple policy-based model router."""

    def __init__(
        self,
        *,
        default_model: str = DEFAULT_MODEL,
        candidates: list[ModelCandidate] | None = None,
    ) -> None:
        self.default_model = default_model
        self.candidates = candidates or self._default_candidates()

    def route(self, request: RoutingRequest) -> RoutingDecision:
        """Select the best model for the given request."""
        required_tags = self._required_tags(request)
        scored_candidates: list[tuple[int, ModelCandidate, dict[str, int]]] = []

        for candidate in self.candidates:
            if not candidate.supports(required_tags):
                continue
            if (
                request.requires_long_context
                and candidate.max_context_tokens is not None
                and candidate.max_context_tokens < request.estimated_input_tokens
            ):
                continue

            score_breakdown = self._score_candidate(candidate, request)
            total_score = sum(score_breakdown.values())
            scored_candidates.append((total_score, candidate, score_breakdown))

        if not scored_candidates:
            return RoutingDecision(
                selected_model=self.default_model,
                fallback_model=None,
                reason="No candidate matched the routing constraints; default model selected.",
                task_kind=request.task_kind,
                mode=request.mode,
                score_breakdown={"default_fallback": 1},
                metadata={
                    "required_tags": sorted(required_tags),
                    "estimated_input_tokens": request.estimated_input_tokens,
                    "retry_count": request.retry_count,
                    "fallback_reason": "no_candidate_matched",
                    "fallback_triggered": True,
                    "retry_aware_selection": request.retry_count > 0,
                },
            )

        scored_candidates.sort(
            key=lambda item: (
                item[0],
                item[1].quality_score,
                item[1].max_context_tokens or 0,
            ),
            reverse=True,
        )

        best_score, best_candidate, best_breakdown = scored_candidates[0]
        fallback_model = (
            scored_candidates[1][1].name if len(scored_candidates) > 1 else None
        )

        fallback_reason: str | None = None
        if fallback_model is not None and request.retry_count > 0:
            fallback_reason = "retry_alternate_available"
        elif fallback_model is not None:
            fallback_reason = "alternate_available"

        return RoutingDecision(
            selected_model=best_candidate.name,
            fallback_model=fallback_model,
            reason=self._build_reason(best_candidate, request, best_score),
            task_kind=request.task_kind,
            mode=request.mode,
            score_breakdown=best_breakdown,
            metadata={
                "required_tags": sorted(required_tags),
                "estimated_input_tokens": request.estimated_input_tokens,
                "retry_count": request.retry_count,
                "fallback_reason": fallback_reason,
                "fallback_triggered": False,
                "retry_aware_selection": request.retry_count > 0,
            },
        )

    def route_task(
        self,
        task_name: str,
        *,
        difficulty: int = 3,
        mode: RoutingMode = RoutingMode.BALANCED,
        retry_count: int = 0,
        estimated_input_tokens: int = 0,
    ) -> RoutingDecision:
        """Convenience wrapper that infers task kind from a task name."""
        request = RoutingRequest(
            task_kind=infer_task_kind(task_name),
            difficulty=difficulty,
            mode=mode,
            retry_count=retry_count,
            estimated_input_tokens=estimated_input_tokens,
            requires_high_reasoning=difficulty >= 4,
            requires_long_context=estimated_input_tokens >= 16_000,
        )
        return self.route(request)

    def _score_candidate(
        self,
        candidate: ModelCandidate,
        request: RoutingRequest,
    ) -> dict[str, int]:
        difficulty = request.normalized_difficulty()
        breakdown: dict[str, int] = {}

        if request.mode == RoutingMode.QUALITY:
            breakdown["quality_weight"] = candidate.quality_score * 4
            breakdown["cost_weight"] = -candidate.cost_score
            breakdown["latency_weight"] = candidate.latency_score
        elif request.mode == RoutingMode.COST_SAVER:
            breakdown["quality_weight"] = candidate.quality_score * 2
            breakdown["cost_weight"] = -candidate.cost_score * 3
            breakdown["latency_weight"] = candidate.latency_score * 2
        else:
            breakdown["quality_weight"] = candidate.quality_score * 3
            breakdown["cost_weight"] = -candidate.cost_score * 2
            breakdown["latency_weight"] = candidate.latency_score * 2

        breakdown["difficulty_bonus"] = difficulty * candidate.quality_score

        if request.requires_high_reasoning and "reasoning" in candidate.tags:
            breakdown["reasoning_bonus"] = 12
        else:
            breakdown["reasoning_bonus"] = 0

        if request.requires_long_context and "long_context" in candidate.tags:
            breakdown["context_bonus"] = 10
        else:
            breakdown["context_bonus"] = 0

        if request.latency_sensitive:
            breakdown["latency_sensitivity_bonus"] = candidate.latency_score * 2
        else:
            breakdown["latency_sensitivity_bonus"] = 0

        if request.retry_count > 0:
            breakdown["retry_bonus"] = request.retry_count * candidate.quality_score
        else:
            breakdown["retry_bonus"] = 0

        if request.task_kind in {
            TaskKind.REVIEW,
            TaskKind.REQUIREMENTS,
            TaskKind.PLANNING,
        }:
            breakdown["analysis_bonus"] = candidate.quality_score * 2
        elif request.task_kind in {TaskKind.SUMMARIZATION, TaskKind.DOCUMENTATION}:
            breakdown["analysis_bonus"] = candidate.latency_score
        else:
            breakdown["analysis_bonus"] = 0

        return breakdown

    def _required_tags(self, request: RoutingRequest) -> set[str]:
        tags: set[str] = set()

        if request.requires_high_reasoning:
            tags.add("reasoning")
        if request.requires_long_context:
            tags.add("long_context")
        if request.task_kind in {
            TaskKind.REVIEW,
            TaskKind.REQUIREMENTS,
            TaskKind.PLANNING,
        }:
            tags.add("analysis")
        if request.task_kind in {TaskKind.IMPLEMENTATION, TaskKind.FIX}:
            tags.add("coding")
        if request.task_kind in {TaskKind.TEST_DESIGN, TaskKind.TEST_EXECUTION}:
            tags.add("testing")
        if request.task_kind in {TaskKind.DOCUMENTATION, TaskKind.SUMMARIZATION}:
            tags.add("writing")

        return tags

    def _build_reason(
        self,
        candidate: ModelCandidate,
        request: RoutingRequest,
        total_score: int,
    ) -> str:
        parts = [
            f"Selected {candidate.name}",
            f"for task_kind={request.task_kind.value}",
            f"mode={request.mode.value}",
            f"difficulty={request.normalized_difficulty()}",
            f"score={total_score}",
        ]
        if request.requires_high_reasoning:
            parts.append("high_reasoning=true")
        if request.requires_long_context:
            parts.append("long_context=true")
        if request.retry_count > 0:
            parts.append(f"retry_count={request.retry_count}")
        return ", ".join(parts) + "."

    def _default_candidates(self) -> list[ModelCandidate]:
        return [
            ModelCandidate(
                name="gpt-5.4",
                quality_score=10,
                cost_score=8,
                latency_score=6,
                max_context_tokens=128_000,
                tags={
                    "analysis",
                    "coding",
                    "testing",
                    "writing",
                    "reasoning",
                    "long_context",
                },
            ),
            ModelCandidate(
                name="gpt-5.4-mini",
                quality_score=7,
                cost_score=4,
                latency_score=8,
                max_context_tokens=64_000,
                tags={
                    "analysis",
                    "coding",
                    "testing",
                    "writing",
                    "reasoning",
                },
            ),
            ModelCandidate(
                name="gpt-5.4-nano",
                quality_score=5,
                cost_score=2,
                latency_score=10,
                max_context_tokens=32_000,
                tags={
                    "writing",
                    "summarization",
                    "analysis",
                },
            ),
        ]


def infer_task_kind(task_name: str) -> TaskKind:
    """Infer a task kind from a task name."""
    normalized = task_name.strip().lower()

    mapping = {
        "requirements": TaskKind.REQUIREMENTS,
        "requirements_analysis": TaskKind.REQUIREMENTS,
        "planning": TaskKind.PLANNING,
        "documentation": TaskKind.DOCUMENTATION,
        "implementation": TaskKind.IMPLEMENTATION,
        "test_design": TaskKind.TEST_DESIGN,
        "test_execution": TaskKind.TEST_EXECUTION,
        "review": TaskKind.REVIEW,
        "fix": TaskKind.FIX,
        "session_management": TaskKind.SESSION_MANAGEMENT,
        "summarization": TaskKind.SUMMARIZATION,
    }

    if normalized in mapping:
        return mapping[normalized]

    if "requirement" in normalized:
        return TaskKind.REQUIREMENTS
    if "plan" in normalized:
        return TaskKind.PLANNING
    if "doc" in normalized:
        return TaskKind.DOCUMENTATION
    if "implement" in normalized or "code" in normalized:
        return TaskKind.IMPLEMENTATION
    if "test" in normalized and "design" in normalized:
        return TaskKind.TEST_DESIGN
    if "test" in normalized or "validate" in normalized:
        return TaskKind.TEST_EXECUTION
    if "review" in normalized:
        return TaskKind.REVIEW
    if "fix" in normalized or "repair" in normalized:
        return TaskKind.FIX
    if "session" in normalized:
        return TaskKind.SESSION_MANAGEMENT
    if "summary" in normalized or "summarize" in normalized:
        return TaskKind.SUMMARIZATION

    return TaskKind.UNKNOWN
