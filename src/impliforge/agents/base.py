"""Shared agent interfaces for the impliforge workflow."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(slots=True)
class AgentTask:
    """Structured input passed from the orchestrator to an agent."""

    name: str
    objective: str
    inputs: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentResult:
    """Structured output returned by an agent."""

    status: str
    summary: str
    outputs: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    failure_category: str | None = None
    failure_cause: str | None = None

    def __post_init__(self) -> None:
        self.status = str(self.status).strip()
        self.summary = self._normalize_summary(self.summary)
        self.outputs = self._normalize_mapping(self.outputs)
        self.artifacts = self._normalize_string_list(self.artifacts)
        self.next_actions = self._normalize_string_list(self.next_actions)
        self.risks = self._normalize_string_list(self.risks)
        self.metrics = self._normalize_mapping(self.metrics)
        self.failure_category = self._normalize_optional_string(self.failure_category)
        self.failure_cause = self._normalize_optional_string(self.failure_cause)

        if self.status == "failed":
            if self.failure_category is None:
                self.failure_category = "unknown_failure"
            if self.failure_cause is None:
                self.failure_cause = "No failure cause provided."

    @property
    def is_success(self) -> bool:
        return self.status in {"completed", "success"}

    @classmethod
    def success(
        cls,
        summary: str,
        *,
        outputs: Mapping[str, Any] | None = None,
        artifacts: list[str] | None = None,
        next_actions: list[str] | None = None,
        risks: list[str] | None = None,
        metrics: Mapping[str, Any] | None = None,
    ) -> AgentResult:
        return cls(
            status="completed",
            summary=summary,
            outputs=dict(outputs or {}),
            artifacts=list(artifacts or []),
            next_actions=list(next_actions or []),
            risks=list(risks or []),
            metrics=dict(metrics or {}),
            failure_category=None,
            failure_cause=None,
        )

    @classmethod
    def failure(
        cls,
        summary: str,
        *,
        outputs: Mapping[str, Any] | None = None,
        artifacts: list[str] | None = None,
        next_actions: list[str] | None = None,
        risks: list[str] | None = None,
        metrics: Mapping[str, Any] | None = None,
        failure_category: str | None = None,
        failure_cause: str | None = None,
    ) -> AgentResult:
        return cls(
            status="failed",
            summary=summary,
            outputs=dict(outputs or {}),
            artifacts=list(artifacts or []),
            next_actions=list(next_actions or []),
            risks=list(risks or []),
            metrics=dict(metrics or {}),
            failure_category=failure_category,
            failure_cause=failure_cause,
        )

    @staticmethod
    def _normalize_summary(value: Any) -> str:
        summary = str(value).strip()
        return summary or "No summary provided."

    @staticmethod
    def _normalize_mapping(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, Mapping) else {}

    @staticmethod
    def _normalize_string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _normalize_optional_string(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None


class BaseAgent(ABC):
    """Base contract implemented by all workflow agents."""

    agent_name = "base"

    @abstractmethod
    async def run(self, task: AgentTask, state: Any) -> AgentResult:
        """Execute the agent task and return a structured result."""
        raise NotImplementedError
