"""Shared agent interfaces for the devagents workflow."""

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
    ) -> AgentResult:
        return cls(
            status="failed",
            summary=summary,
            outputs=dict(outputs or {}),
            artifacts=list(artifacts or []),
            next_actions=list(next_actions or []),
            risks=list(risks or []),
            metrics=dict(metrics or {}),
        )


class BaseAgent(ABC):
    """Base contract implemented by all workflow agents."""

    agent_name = "base"

    @abstractmethod
    async def run(self, task: AgentTask, state: Any) -> AgentResult:
        """Execute the agent task and return a structured result."""
        raise NotImplementedError
