"""GitHub Copilot SDK client wrapper for devagents.

This module adapts the public preview Python SDK to a small, stable interface
used by the rest of this repository.

Key design choices:
- depend on the real SDK package surface (`copilot`, not `github_copilot_sdk`)
- keep SDK-specific details isolated in this file
- support session creation and resumption
- support infinite sessions through the SDK's built-in session management
- provide a dry-run fallback when the SDK or CLI is unavailable
- expose structured request/response objects for orchestration code
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

DEFAULT_MODEL = "gpt-5.4"


class CopilotTaskType(StrEnum):
    """High-level task categories used for routing and observability."""

    GENERAL = "general"
    REQUIREMENTS = "requirements"
    PLANNING = "planning"
    DOCUMENTATION = "documentation"
    IMPLEMENTATION = "implementation"
    TEST_DESIGN = "test_design"
    TEST_EXECUTION = "test_execution"
    REVIEW = "review"
    FIX = "fix"
    SUMMARY = "summary"


@dataclass(slots=True)
class CopilotClientConfig:
    """Runtime configuration for the Copilot client wrapper."""

    default_model: str = DEFAULT_MODEL
    timeout_seconds: float = 120.0
    max_retries: int = 1
    enable_sdk: bool = True
    dry_run_fallback: bool = True
    application_name: str = "devagents"
    user_agent_suffix: str = "skeleton"
    working_directory: str | None = None
    config_dir: str | None = None
    cli_path: str | None = None
    cli_args: list[str] = field(default_factory=list)
    use_stdio: bool = True
    port: int = 0
    log_level: str = "info"
    env: dict[str, str] | None = None
    github_token: str | None = None
    use_logged_in_user: bool | None = None
    streaming: bool = False
    infinite_sessions_enabled: bool = True
    background_compaction_threshold: float = 0.80
    buffer_exhaustion_threshold: float = 0.95


@dataclass(slots=True)
class CopilotRequest:
    """Normalized request payload passed to the Copilot client."""

    prompt: str
    system_prompt: str | None = None
    model: str | None = None
    task_type: CopilotTaskType = CopilotTaskType.GENERAL
    session_id: str | None = None
    workflow_id: str | None = None
    persistent_context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    temperature: float | None = None
    max_output_tokens: int | None = None
    reasoning_effort: str | None = None

    def resolved_model(self, default_model: str) -> str:
        """Return the effective model for this request."""
        return self.model or default_model


@dataclass(slots=True)
class CopilotUsage:
    """Token and cost-adjacent usage metadata."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    token_usage_ratio: float | None = None


@dataclass(slots=True)
class CopilotResponse:
    """Structured response returned by the Copilot client."""

    content: str
    model: str
    task_type: CopilotTaskType
    session_id: str | None = None
    workflow_id: str | None = None
    finish_reason: str | None = None
    usage: CopilotUsage = field(default_factory=CopilotUsage)
    raw: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def is_dry_run(self) -> bool:
        """Return whether this response came from the dry-run fallback."""
        return bool(self.metadata.get("dry_run", False))


class CopilotClientError(RuntimeError):
    """Raised when the Copilot client cannot fulfill a request."""


class CopilotClient:
    """Thin wrapper around the GitHub Copilot Python SDK."""

    def __init__(self, config: CopilotClientConfig | None = None) -> None:
        self.config = config or CopilotClientConfig()

    async def generate(self, request: CopilotRequest) -> CopilotResponse:
        """Generate a response for a normalized Copilot request."""
        resolved_model = request.resolved_model(self.config.default_model)

        if not self.config.enable_sdk:
            return self._build_dry_run_response(
                request,
                resolved_model=resolved_model,
                reason="sdk_disabled",
            )

        try:
            sdk_result = await self._invoke_sdk(request, resolved_model)
            return self._normalize_sdk_response(
                request=request,
                resolved_model=resolved_model,
                sdk_result=sdk_result,
            )
        except Exception as exc:
            if self.config.dry_run_fallback:
                return self._build_dry_run_response(
                    request,
                    resolved_model=resolved_model,
                    reason=f"sdk_error:{type(exc).__name__}",
                    error_message=str(exc),
                )
            raise CopilotClientError(str(exc)) from exc

    async def generate_text(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        model: str | None = None,
        task_type: CopilotTaskType = CopilotTaskType.GENERAL,
        session_id: str | None = None,
        workflow_id: str | None = None,
        persistent_context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        reasoning_effort: str | None = None,
    ) -> CopilotResponse:
        """Convenience helper for simple text generation calls."""
        request = CopilotRequest(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            task_type=task_type,
            session_id=session_id,
            workflow_id=workflow_id,
            persistent_context=dict(persistent_context or {}),
            metadata=dict(metadata or {}),
            reasoning_effort=reasoning_effort,
        )
        return await self.generate(request)

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
        """Build a request intended for resumed execution in a new session."""
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
            metadata={
                "resume": True,
                **dict(metadata or {}),
            },
            reasoning_effort=reasoning_effort,
        )

    async def list_models(self) -> list[dict[str, Any]]:
        """Return available models from the SDK when possible."""
        if not self.config.enable_sdk:
            return self._default_model_list()

        try:
            client_module = self._import_sdk_client_module()
            client = self._build_sdk_client(client_module)
            async with client:
                models = await client.list_models()
            return [self._model_info_to_dict(model) for model in models]
        except Exception:
            if self.config.dry_run_fallback:
                return self._default_model_list()
            raise

    async def _invoke_sdk(
        self,
        request: CopilotRequest,
        resolved_model: str,
    ) -> dict[str, Any]:
        """Invoke the real Copilot SDK and return a normalized intermediate payload."""
        client_module = self._import_sdk_client_module()
        session_module = self._import_sdk_session_module()

        client = self._build_sdk_client(client_module)
        permission_handler = session_module.PermissionHandler.approve_all

        session_kwargs = self._build_session_kwargs(
            request=request,
            resolved_model=resolved_model,
            permission_handler=permission_handler,
        )

        async with client:
            session = await self._open_session(client, request, session_kwargs)
            async with session:
                event_result = await session.send_and_wait(
                    request.prompt,
                    timeout=self.config.timeout_seconds,
                )
                messages = await session.get_messages()

                content = self._extract_content_from_event(event_result)
                if not content:
                    content = self._extract_content_from_messages(messages)

                usage = self._extract_usage_from_messages(messages)
                finish_reason = self._extract_finish_reason_from_messages(messages)

                return {
                    "content": content,
                    "model": resolved_model,
                    "session_id": getattr(session, "session_id", request.session_id),
                    "workflow_id": request.workflow_id,
                    "finish_reason": finish_reason,
                    "usage": usage,
                    "message_count": len(messages),
                    "workspace_path": str(getattr(session, "workspace_path", "") or ""),
                    "raw_messages": [self._event_to_dict(event) for event in messages],
                }

    def _build_sdk_client(self, client_module: Any) -> Any:
        """Construct the SDK client using subprocess configuration."""
        subprocess_config = client_module.SubprocessConfig(
            cli_path=self.config.cli_path,
            cli_args=list(self.config.cli_args),
            cwd=self.config.working_directory,
            use_stdio=self.config.use_stdio,
            port=self.config.port,
            log_level=self.config.log_level,
            env=self.config.env,
            github_token=self.config.github_token,
            use_logged_in_user=self.config.use_logged_in_user,
        )
        return client_module.CopilotClient(subprocess_config)

    def _build_session_kwargs(
        self,
        *,
        request: CopilotRequest,
        resolved_model: str,
        permission_handler: Any,
    ) -> dict[str, Any]:
        """Translate a normalized request into SDK session kwargs."""
        session_kwargs: dict[str, Any] = {
            "on_permission_request": permission_handler,
            "model": resolved_model,
            "streaming": self.config.streaming,
            "working_directory": self.config.working_directory,
            "config_dir": self.config.config_dir,
            "client_name": (
                f"{self.config.application_name}/{self.config.user_agent_suffix}"
            ),
            "infinite_sessions": {
                "enabled": self.config.infinite_sessions_enabled,
                "background_compaction_threshold": (
                    self.config.background_compaction_threshold
                ),
                "buffer_exhaustion_threshold": (
                    self.config.buffer_exhaustion_threshold
                ),
            },
        }

        if request.reasoning_effort:
            session_kwargs["reasoning_effort"] = request.reasoning_effort

        if request.system_prompt:
            session_kwargs["system_message"] = {
                "mode": "append",
                "content": request.system_prompt,
            }

        return session_kwargs

    async def _open_session(
        self,
        client: Any,
        request: CopilotRequest,
        session_kwargs: dict[str, Any],
    ) -> Any:
        """Create or resume an SDK session."""
        if request.session_id:
            return await client.resume_session(
                request.session_id,
                **session_kwargs,
            )
        return await client.create_session(**session_kwargs)

    def _normalize_sdk_response(
        self,
        *,
        request: CopilotRequest,
        resolved_model: str,
        sdk_result: dict[str, Any],
    ) -> CopilotResponse:
        """Normalize an SDK result into the repository's response shape."""
        usage_payload = sdk_result.get("usage", {})
        usage = CopilotUsage(
            input_tokens=self._coerce_int(usage_payload.get("input_tokens")),
            output_tokens=self._coerce_int(usage_payload.get("output_tokens")),
            total_tokens=self._coerce_int(usage_payload.get("total_tokens")),
            token_usage_ratio=self._coerce_float(
                usage_payload.get("token_usage_ratio")
            ),
        )

        return CopilotResponse(
            content=str(sdk_result.get("content") or ""),
            model=str(sdk_result.get("model") or resolved_model),
            task_type=request.task_type,
            session_id=self._coerce_optional_str(
                sdk_result.get("session_id") or request.session_id
            ),
            workflow_id=request.workflow_id,
            finish_reason=self._coerce_optional_str(sdk_result.get("finish_reason")),
            usage=usage,
            raw=dict(sdk_result),
            metadata={
                "dry_run": False,
                "sdk_invoked": True,
                "request_metadata": dict(request.metadata),
                "message_count": sdk_result.get("message_count"),
                "workspace_path": sdk_result.get("workspace_path"),
            },
        )

    def _build_dry_run_response(
        self,
        request: CopilotRequest,
        *,
        resolved_model: str,
        reason: str,
        error_message: str | None = None,
    ) -> CopilotResponse:
        """Return a deterministic fallback response when SDK execution is absent."""
        content = self._build_dry_run_content(request, resolved_model, reason)
        metadata: dict[str, Any] = {
            "dry_run": True,
            "sdk_invoked": False,
            "reason": reason,
            "request_metadata": dict(request.metadata),
        }
        if error_message:
            metadata["error_message"] = error_message

        return CopilotResponse(
            content=content,
            model=resolved_model,
            task_type=request.task_type,
            session_id=request.session_id,
            workflow_id=request.workflow_id,
            finish_reason="dry_run",
            usage=CopilotUsage(),
            raw={},
            metadata=metadata,
        )

    def _build_dry_run_content(
        self,
        request: CopilotRequest,
        resolved_model: str,
        reason: str,
    ) -> str:
        """Build a compact placeholder response for local skeleton execution."""
        lines = [
            "[dry-run] Copilot SDK response placeholder",
            f"model: {resolved_model}",
            f"task_type: {request.task_type.value}",
            f"reason: {reason}",
        ]
        if request.session_id:
            lines.append(f"session_id: {request.session_id}")
        if request.workflow_id:
            lines.append(f"workflow_id: {request.workflow_id}")
        if request.persistent_context:
            lines.append(
                "persistent_context_keys: "
                + ", ".join(sorted(request.persistent_context.keys()))
            )
        lines.append("prompt_preview:")
        lines.append(request.prompt[:400].strip())
        return "\n".join(lines)

    def _extract_content_from_event(self, event: Any) -> str:
        """Extract assistant content from send_and_wait result."""
        if event is None:
            return ""
        data = getattr(event, "data", None)
        if data is None:
            return ""
        content = getattr(data, "content", None)
        if content is None:
            return ""
        return str(content)

    def _extract_content_from_messages(self, messages: list[Any]) -> str:
        """Extract the latest assistant message content from session history."""
        for event in reversed(messages):
            event_type = getattr(getattr(event, "type", None), "value", None)
            if event_type == "assistant.message":
                data = getattr(event, "data", None)
                content = getattr(data, "content", None)
                if content:
                    return str(content)
        return ""

    def _extract_usage_from_messages(self, messages: list[Any]) -> dict[str, Any]:
        """Best-effort extraction of usage metadata from session events."""
        usage: dict[str, Any] = {}
        for event in reversed(messages):
            data = getattr(event, "data", None)
            if data is None:
                continue

            for attr_name in (
                "usage",
                "token_usage",
                "tokenUsage",
            ):
                value = getattr(data, attr_name, None)
                if value is not None:
                    usage = self._object_to_dict(value)
                    break

            if usage:
                break

        normalized: dict[str, Any] = {
            "input_tokens": self._coerce_int(
                usage.get("input_tokens") or usage.get("inputTokens")
            ),
            "output_tokens": self._coerce_int(
                usage.get("output_tokens") or usage.get("outputTokens")
            ),
            "total_tokens": self._coerce_int(
                usage.get("total_tokens") or usage.get("totalTokens")
            ),
            "token_usage_ratio": self._coerce_float(
                usage.get("token_usage_ratio") or usage.get("tokenUsageRatio")
            ),
        }
        return normalized

    def _extract_finish_reason_from_messages(self, messages: list[Any]) -> str | None:
        """Best-effort extraction of finish reason from session events."""
        for event in reversed(messages):
            data = getattr(event, "data", None)
            if data is None:
                continue
            for attr_name in ("finish_reason", "finishReason", "reason"):
                value = getattr(data, attr_name, None)
                if value is not None:
                    text = str(value)
                    if text:
                        return text
        return None

    def _event_to_dict(self, event: Any) -> dict[str, Any]:
        """Convert an SDK event object into a plain dict."""
        event_type = getattr(getattr(event, "type", None), "value", None)
        data = getattr(event, "data", None)
        return {
            "type": event_type,
            "data": self._object_to_dict(data),
        }

    def _object_to_dict(self, value: Any) -> dict[str, Any]:
        """Convert a generic SDK object into a dict when possible."""
        if value is None:
            return {}
        if isinstance(value, dict):
            return dict(value)
        if hasattr(value, "to_dict") and callable(value.to_dict):
            result = value.to_dict()
            if isinstance(result, dict):
                return result
        if hasattr(value, "__dict__"):
            return {
                key: val for key, val in vars(value).items() if not key.startswith("_")
            }
        return {}

    def _model_info_to_dict(self, model: Any) -> dict[str, Any]:
        """Convert SDK model info into a plain dict."""
        if hasattr(model, "to_dict") and callable(model.to_dict):
            result = model.to_dict()
            if isinstance(result, dict):
                return result
        return self._object_to_dict(model)

    def _default_model_list(self) -> list[dict[str, Any]]:
        """Return a conservative fallback model list."""
        return [
            {
                "id": "gpt-5.4",
                "name": "gpt-5.4",
                "capabilities": {
                    "supports": {
                        "vision": True,
                        "reasoningEffort": True,
                    },
                    "limits": {
                        "max_context_window_tokens": 128000,
                    },
                },
            },
            {
                "id": "gpt-5.4-mini",
                "name": "gpt-5.4-mini",
                "capabilities": {
                    "supports": {
                        "vision": False,
                        "reasoningEffort": True,
                    },
                    "limits": {
                        "max_context_window_tokens": 64000,
                    },
                },
            },
            {
                "id": "gpt-5.4-nano",
                "name": "gpt-5.4-nano",
                "capabilities": {
                    "supports": {
                        "vision": False,
                        "reasoningEffort": False,
                    },
                    "limits": {
                        "max_context_window_tokens": 32000,
                    },
                },
            },
        ]

    def _import_sdk_client_module(self) -> Any:
        """Import the public SDK client module."""
        try:
            import copilot as client_module
            from copilot import CopilotClient as _CopilotClient  # noqa: F401
            from copilot import SubprocessConfig as _SubprocessConfig  # noqa: F401

            return client_module
        except ImportError as exc:
            raise CopilotClientError(
                "The GitHub Copilot Python SDK is not importable. "
                "Install the package that exposes the `copilot` module."
            ) from exc

    def _import_sdk_session_module(self) -> Any:
        """Import the public SDK session module."""
        try:
            import copilot.session as session_module

            return session_module
        except ImportError as exc:
            raise CopilotClientError(
                "The GitHub Copilot Python SDK session module is not importable."
            ) from exc

    def _coerce_int(self, value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except TypeError, ValueError:
            return None

    def _coerce_float(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except TypeError, ValueError:
            return None

    def _coerce_optional_str(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value)
        return text or None


async def _demo() -> None:
    """Small manual demo for local verification."""
    client = CopilotClient()
    response = await client.generate_text(
        "What is 2+2?",
        task_type=CopilotTaskType.SUMMARY,
    )
    print(response.content)


if __name__ == "__main__":
    asyncio.run(_demo())
