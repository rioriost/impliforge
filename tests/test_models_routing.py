from __future__ import annotations

from impliforge.models.routing import (
    DEFAULT_MODEL,
    ModelCandidate,
    ModelRouter,
    RoutingMode,
    RoutingRequest,
    TaskKind,
    infer_task_kind,
)


def build_router() -> ModelRouter:
    return ModelRouter(
        default_model="default-model",
        candidates=[
            ModelCandidate(
                name="high-quality",
                quality_score=10,
                cost_score=9,
                latency_score=4,
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
                name="fast-cheap",
                quality_score=6,
                cost_score=1,
                latency_score=10,
                max_context_tokens=32_000,
                tags={
                    "analysis",
                    "coding",
                    "testing",
                    "writing",
                },
            ),
            ModelCandidate(
                name="reasoning-specialist",
                quality_score=8,
                cost_score=5,
                latency_score=6,
                max_context_tokens=64_000,
                tags={
                    "analysis",
                    "reasoning",
                    "writing",
                },
            ),
        ],
    )


def test_infer_task_kind_matches_exact_and_keyword_cases() -> None:
    assert infer_task_kind("requirements") is TaskKind.REQUIREMENTS
    assert infer_task_kind("requirements_analysis") is TaskKind.REQUIREMENTS
    assert infer_task_kind("Plan next sprint") is TaskKind.PLANNING
    assert infer_task_kind("docs refresh") is TaskKind.DOCUMENTATION
    assert infer_task_kind("implement feature flag") is TaskKind.IMPLEMENTATION
    assert infer_task_kind("test design for router") is TaskKind.TEST_DESIGN
    assert infer_task_kind("validate release candidate") is TaskKind.TEST_EXECUTION
    assert infer_task_kind("review patch") is TaskKind.REVIEW
    assert infer_task_kind("repair flaky issue") is TaskKind.FIX
    assert infer_task_kind("session rollover") is TaskKind.SESSION_MANAGEMENT
    assert infer_task_kind("summarization") is TaskKind.SUMMARIZATION
    assert infer_task_kind("summary for latest run") is TaskKind.TEST_EXECUTION
    assert infer_task_kind("totally unrelated task") is TaskKind.UNKNOWN


def test_route_task_infers_flags_from_inputs() -> None:
    router = build_router()

    decision = router.route_task(
        "requirements_analysis",
        difficulty=4,
        mode=RoutingMode.QUALITY,
        retry_count=2,
        estimated_input_tokens=20_000,
    )

    assert decision.task_kind is TaskKind.REQUIREMENTS
    assert decision.mode is RoutingMode.QUALITY
    assert decision.selected_model == "high-quality"
    assert decision.fallback_model is None
    assert "task_kind=requirements" in decision.reason
    assert "mode=quality" in decision.reason
    assert "difficulty=4" in decision.reason
    assert "high_reasoning=true" in decision.reason
    assert "long_context=true" in decision.reason
    assert "retry_count=2" in decision.reason
    assert decision.metadata["estimated_input_tokens"] == 20_000
    assert decision.metadata["retry_count"] == 2
    assert decision.metadata["required_tags"] == [
        "analysis",
        "long_context",
        "reasoning",
    ]


def test_route_returns_default_when_no_candidate_matches_required_tags() -> None:
    router = ModelRouter(
        default_model="fallback-default",
        candidates=[
            ModelCandidate(
                name="writer-only",
                quality_score=5,
                cost_score=1,
                latency_score=8,
                max_context_tokens=8_000,
                tags={"writing"},
            )
        ],
    )

    decision = router.route(
        RoutingRequest(
            task_kind=TaskKind.IMPLEMENTATION,
            requires_high_reasoning=True,
            requires_long_context=True,
            estimated_input_tokens=32_000,
        )
    )

    assert decision.selected_model == "fallback-default"
    assert decision.fallback_model is None
    assert decision.reason == (
        "No candidate matched the routing constraints; default model selected."
    )
    assert decision.score_breakdown == {"default_fallback": 1}
    assert decision.metadata["required_tags"] == [
        "coding",
        "long_context",
        "reasoning",
    ]
    assert decision.metadata["estimated_input_tokens"] == 32_000
    assert decision.metadata["retry_count"] == 0
    assert decision.metadata["fallback_reason"] == "no_candidate_matched"
    assert decision.metadata["fallback_triggered"] is True
    assert decision.metadata["retry_aware_selection"] is False


def test_route_skips_candidates_with_insufficient_context_capacity() -> None:
    router = ModelRouter(
        default_model=DEFAULT_MODEL,
        candidates=[
            ModelCandidate(
                name="small-context",
                quality_score=9,
                cost_score=2,
                latency_score=7,
                max_context_tokens=8_000,
                tags={"analysis", "reasoning", "long_context"},
            ),
            ModelCandidate(
                name="large-context",
                quality_score=7,
                cost_score=4,
                latency_score=6,
                max_context_tokens=64_000,
                tags={"analysis", "reasoning", "long_context"},
            ),
        ],
    )

    decision = router.route(
        RoutingRequest(
            task_kind=TaskKind.PLANNING,
            requires_high_reasoning=True,
            requires_long_context=True,
            estimated_input_tokens=16_000,
        )
    )

    assert decision.selected_model == "large-context"
    assert decision.fallback_model is None
    assert decision.metadata["required_tags"] == [
        "analysis",
        "long_context",
        "reasoning",
    ]


def test_route_prefers_quality_candidate_in_quality_mode() -> None:
    router = build_router()

    decision = router.route(
        RoutingRequest(
            task_kind=TaskKind.REVIEW,
            difficulty=5,
            mode=RoutingMode.QUALITY,
            requires_high_reasoning=True,
        )
    )

    assert decision.selected_model == "high-quality"
    assert decision.fallback_model == "reasoning-specialist"
    assert decision.score_breakdown["quality_weight"] == 40
    assert decision.score_breakdown["cost_weight"] == -9
    assert decision.score_breakdown["latency_weight"] == 4
    assert decision.score_breakdown["difficulty_bonus"] == 50
    assert decision.score_breakdown["reasoning_bonus"] == 12
    assert decision.score_breakdown["context_bonus"] == 0
    assert decision.score_breakdown["latency_sensitivity_bonus"] == 0
    assert decision.score_breakdown["retry_bonus"] == 0
    assert decision.score_breakdown["analysis_bonus"] == 20
    assert decision.metadata["fallback_reason"] == "alternate_available"
    assert decision.metadata["fallback_triggered"] is False
    assert decision.metadata["retry_aware_selection"] is False


def test_route_prefers_fast_candidate_in_cost_saver_mode_when_scores_favor_it() -> None:
    router = build_router()

    decision = router.route(
        RoutingRequest(
            task_kind=TaskKind.DOCUMENTATION,
            difficulty=2,
            mode=RoutingMode.COST_SAVER,
            latency_sensitive=True,
        )
    )

    assert decision.selected_model == "fast-cheap"
    assert decision.fallback_model == "reasoning-specialist"
    assert decision.score_breakdown["quality_weight"] == 12
    assert decision.score_breakdown["cost_weight"] == -3
    assert decision.score_breakdown["latency_weight"] == 20
    assert decision.score_breakdown["difficulty_bonus"] == 12
    assert decision.score_breakdown["latency_sensitivity_bonus"] == 20
    assert decision.score_breakdown["analysis_bonus"] == 10
    assert decision.metadata["fallback_reason"] == "alternate_available"
    assert decision.metadata["fallback_triggered"] is False
    assert decision.metadata["retry_aware_selection"] is False


def test_route_uses_context_tokens_as_tiebreaker_when_scores_and_quality_match() -> (
    None
):
    router = ModelRouter(
        candidates=[
            ModelCandidate(
                name="less-context",
                quality_score=8,
                cost_score=5,
                latency_score=6,
                max_context_tokens=64_000,
                tags={"writing"},
            ),
            ModelCandidate(
                name="more-context",
                quality_score=8,
                cost_score=5,
                latency_score=6,
                max_context_tokens=128_000,
                tags={"writing"},
            ),
        ]
    )

    decision = router.route(
        RoutingRequest(
            task_kind=TaskKind.SUMMARIZATION,
            difficulty=1,
            mode=RoutingMode.BALANCED,
        )
    )

    assert decision.selected_model == "more-context"
    assert decision.fallback_model == "less-context"
    assert decision.metadata["fallback_reason"] == "alternate_available"
    assert decision.metadata["fallback_triggered"] is False
    assert decision.metadata["retry_aware_selection"] is False


def test_routing_request_normalized_difficulty_clamps_bounds() -> None:
    assert (
        RoutingRequest(
            task_kind=TaskKind.UNKNOWN, difficulty=-3
        ).normalized_difficulty()
        == 1
    )
    assert (
        RoutingRequest(task_kind=TaskKind.UNKNOWN, difficulty=3).normalized_difficulty()
        == 3
    )
    assert (
        RoutingRequest(
            task_kind=TaskKind.UNKNOWN, difficulty=99
        ).normalized_difficulty()
        == 5
    )


def test_required_tags_cover_task_specific_branches() -> None:
    router = build_router()

    assert router._required_tags(
        RoutingRequest(task_kind=TaskKind.REVIEW, requires_high_reasoning=True)
    ) == {"analysis", "reasoning"}
    assert router._required_tags(RoutingRequest(task_kind=TaskKind.IMPLEMENTATION)) == {
        "coding"
    }
    assert router._required_tags(RoutingRequest(task_kind=TaskKind.TEST_EXECUTION)) == {
        "testing"
    }
    assert router._required_tags(
        RoutingRequest(task_kind=TaskKind.SUMMARIZATION, requires_long_context=True)
    ) == {"writing", "long_context"}


def test_routing_decision_to_dict_serializes_enums() -> None:
    router = build_router()

    decision = router.route(
        RoutingRequest(
            task_kind=TaskKind.DOCUMENTATION,
            mode=RoutingMode.BALANCED,
        )
    )

    payload = decision.to_dict()

    assert payload["task_kind"] == "documentation"
    assert payload["mode"] == "balanced"
    assert payload["selected_model"] == decision.selected_model
    assert payload["fallback_model"] == decision.fallback_model
    assert payload["metadata"] == decision.metadata


def test_route_marks_retry_aware_alternate_fallback_metadata() -> None:
    router = build_router()

    decision = router.route(
        RoutingRequest(
            task_kind=TaskKind.REVIEW,
            difficulty=5,
            mode=RoutingMode.QUALITY,
            requires_high_reasoning=True,
            retry_count=2,
        )
    )

    assert decision.selected_model == "high-quality"
    assert decision.fallback_model == "reasoning-specialist"
    assert decision.metadata["retry_count"] == 2
    assert decision.metadata["fallback_reason"] == "retry_alternate_available"
    assert decision.metadata["fallback_triggered"] is False
    assert decision.metadata["retry_aware_selection"] is True
