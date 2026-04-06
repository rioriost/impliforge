from __future__ import annotations

import asyncio
from types import SimpleNamespace

from devagents.runtime.copilot_client import (
    CopilotClient,
    CopilotClientConfig,
    CopilotClientError,
    CopilotRequest,
    CopilotResponse,
    CopilotTaskType,
)


def run(coro):
    return asyncio.run(coro)


def make_event(
    event_type: str | None = None,
    *,
    content: object | None = None,
    usage: object | None = None,
    token_usage: object | None = None,
    finish_reason: object | None = None,
    finishReason: object | None = None,
    reason: object | None = None,
) -> SimpleNamespace:
    data = SimpleNamespace()
    if content is not None:
        data.content = content
    if usage is not None:
        data.usage = usage
    if token_usage is not None:
        data.token_usage = token_usage
    if finish_reason is not None:
        data.finish_reason = finish_reason
    if finishReason is not None:
        data.finishReason = finishReason
    if reason is not None:
        data.reason = reason

    return SimpleNamespace(
        type=SimpleNamespace(value=event_type) if event_type is not None else None,
        data=data,
    )


def test_request_resolved_model_prefers_explicit_model() -> None:
    request = CopilotRequest(prompt="hello", model="gpt-explicit")

    assert request.resolved_model("gpt-default") == "gpt-explicit"


def test_request_resolved_model_falls_back_to_default() -> None:
    request = CopilotRequest(prompt="hello")

    assert request.resolved_model("gpt-default") == "gpt-default"


def test_generate_returns_dry_run_when_sdk_disabled() -> None:
    client = CopilotClient(
        CopilotClientConfig(enable_sdk=False, default_model="gpt-default")
    )
    request = CopilotRequest(
        prompt="Implement feature",
        task_type=CopilotTaskType.IMPLEMENTATION,
        session_id="session-1",
        workflow_id="workflow-1",
        persistent_context={"repo": "devagents", "branch": "main"},
        metadata={"source": "test"},
    )

    response = run(client.generate(request))

    assert response.is_dry_run is True
    assert response.model == "gpt-default"
    assert response.finish_reason == "dry_run"
    assert response.session_id == "session-1"
    assert response.workflow_id == "workflow-1"
    assert response.metadata["reason"] == "sdk_disabled"
    assert response.metadata["sdk_invoked"] is False
    assert response.metadata["request_metadata"] == {"source": "test"}
    assert "model: gpt-default" in response.content
    assert "task_type: implementation" in response.content
    assert "session_id: session-1" in response.content
    assert "workflow_id: workflow-1" in response.content
    assert "persistent_context_keys: branch, repo" in response.content
    assert "prompt_preview:" in response.content


def test_generate_uses_dry_run_fallback_on_sdk_error() -> None:
    client = CopilotClient(CopilotClientConfig(default_model="gpt-default"))

    async def failing_invoke(
        request: CopilotRequest,
        resolved_model: str,
    ) -> dict[str, object]:
        raise RuntimeError("sdk exploded")

    client._invoke_sdk = failing_invoke  # type: ignore[method-assign]

    response = run(
        client.generate(
            CopilotRequest(
                prompt="Need output",
                task_type=CopilotTaskType.REVIEW,
                metadata={"attempt": 1},
            )
        )
    )

    assert response.is_dry_run is True
    assert response.model == "gpt-default"
    assert response.metadata["reason"] == "sdk_error:RuntimeError"
    assert response.metadata["error_message"] == "sdk exploded"
    assert response.metadata["request_metadata"] == {"attempt": 1}
    assert "reason: sdk_error:RuntimeError" in response.content


def test_generate_raises_client_error_when_fallback_disabled() -> None:
    client = CopilotClient(CopilotClientConfig(dry_run_fallback=False))

    async def failing_invoke(
        request: CopilotRequest,
        resolved_model: str,
    ) -> dict[str, object]:
        raise ValueError("bad sdk state")

    client._invoke_sdk = failing_invoke  # type: ignore[method-assign]

    try:
        run(client.generate(CopilotRequest(prompt="hello")))
    except CopilotClientError as exc:
        assert str(exc) == "bad sdk state"
    else:
        raise AssertionError("Expected CopilotClientError")


def test_generate_text_builds_request_and_preserves_optional_fields() -> None:
    client = CopilotClient(CopilotClientConfig(default_model="gpt-default"))
    captured: dict[str, object] = {}

    async def fake_generate(request: CopilotRequest) -> CopilotResponse:
        captured["request"] = request
        return CopilotResponse(
            content="ok",
            model=request.resolved_model("gpt-default"),
            task_type=request.task_type,
            session_id=request.session_id,
            workflow_id=request.workflow_id,
        )

    client.generate = fake_generate  # type: ignore[method-assign]

    response = run(
        client.generate_text(
            "Prompt body",
            system_prompt="System body",
            model="gpt-custom",
            task_type=CopilotTaskType.SUMMARY,
            session_id="session-9",
            workflow_id="workflow-9",
            persistent_context={"ticket": "123"},
            metadata={"origin": "unit"},
            reasoning_effort="high",
        )
    )

    request = captured["request"]
    assert isinstance(request, CopilotRequest)
    assert request.prompt == "Prompt body"
    assert request.system_prompt == "System body"
    assert request.model == "gpt-custom"
    assert request.task_type == CopilotTaskType.SUMMARY
    assert request.session_id == "session-9"
    assert request.workflow_id == "workflow-9"
    assert request.persistent_context == {"ticket": "123"}
    assert request.metadata == {"origin": "unit"}
    assert request.reasoning_effort == "high"
    assert response.model == "gpt-custom"


def test_build_resume_request_merges_prompts_and_sets_resume_metadata() -> None:
    client = CopilotClient()

    request = client.build_resume_request(
        prompt="Continue with implementation details.",
        resume_prompt="You are resuming prior work.",
        task_type=CopilotTaskType.IMPLEMENTATION,
        session_id="session-2",
        workflow_id="workflow-2",
        persistent_context={"repo": "devagents"},
        model="gpt-resume",
        metadata={"source": "resume"},
        reasoning_effort="medium",
    )

    assert request.prompt == (
        "You are resuming prior work.\n\nContinue with implementation details."
    )
    assert request.task_type == CopilotTaskType.IMPLEMENTATION
    assert request.session_id == "session-2"
    assert request.workflow_id == "workflow-2"
    assert request.persistent_context == {"repo": "devagents"}
    assert request.model == "gpt-resume"
    assert request.reasoning_effort == "medium"
    assert request.metadata == {"resume": True, "source": "resume"}


def test_build_resume_request_ignores_blank_prompt_parts() -> None:
    client = CopilotClient()

    request = client.build_resume_request(
        prompt="  final prompt  ",
        resume_prompt="   ",
        task_type=CopilotTaskType.GENERAL,
        session_id=None,
        workflow_id=None,
    )

    assert request.prompt == "final prompt"
    assert request.metadata == {"resume": True}


def test_build_session_kwargs_includes_optional_fields_when_present() -> None:
    client = CopilotClient(
        CopilotClientConfig(
            streaming=True,
            working_directory="/tmp/work",
            config_dir="/tmp/config",
            application_name="devagents",
            user_agent_suffix="tests",
            infinite_sessions_enabled=True,
            background_compaction_threshold=0.7,
            buffer_exhaustion_threshold=0.9,
        )
    )
    request = CopilotRequest(
        prompt="hello",
        system_prompt="system",
        reasoning_effort="high",
    )

    kwargs = client._build_session_kwargs(
        request=request,
        resolved_model="gpt-5.4",
        permission_handler="approve-all",
    )

    assert kwargs["on_permission_request"] == "approve-all"
    assert kwargs["model"] == "gpt-5.4"
    assert kwargs["streaming"] is True
    assert kwargs["working_directory"] == "/tmp/work"
    assert kwargs["config_dir"] == "/tmp/config"
    assert kwargs["client_name"] == "devagents/tests"
    assert kwargs["reasoning_effort"] == "high"
    assert kwargs["system_message"] == {"mode": "append", "content": "system"}
    assert kwargs["infinite_sessions"] == {
        "enabled": True,
        "background_compaction_threshold": 0.7,
        "buffer_exhaustion_threshold": 0.9,
    }


def test_build_session_kwargs_omits_optional_fields_when_absent() -> None:
    client = CopilotClient(CopilotClientConfig())
    request = CopilotRequest(prompt="hello")

    kwargs = client._build_session_kwargs(
        request=request,
        resolved_model="gpt-5.4",
        permission_handler="approve-all",
    )

    assert "reasoning_effort" not in kwargs
    assert "system_message" not in kwargs


def test_open_session_uses_resume_when_session_id_present() -> None:
    client = CopilotClient()
    calls: list[tuple[str, object, dict[str, object]]] = []

    class FakeClient:
        async def resume_session(self, session_id: str, **kwargs):
            calls.append(("resume", session_id, kwargs))
            return "resumed"

        async def create_session(self, **kwargs):
            calls.append(("create", None, kwargs))
            return "created"

    result = run(
        client._open_session(
            FakeClient(),
            CopilotRequest(prompt="hello", session_id="session-3"),
            {"model": "gpt"},
        )
    )

    assert result == "resumed"
    assert calls == [("resume", "session-3", {"model": "gpt"})]


def test_open_session_creates_new_session_without_session_id() -> None:
    client = CopilotClient()
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeClient:
        async def resume_session(self, session_id: str, **kwargs):
            raise AssertionError("resume_session should not be called")

        async def create_session(self, **kwargs):
            calls.append(("create", kwargs))
            return "created"

    result = run(
        client._open_session(
            FakeClient(),
            CopilotRequest(prompt="hello"),
            {"model": "gpt"},
        )
    )

    assert result == "created"
    assert calls == [("create", {"model": "gpt"})]


def test_normalize_sdk_response_coerces_usage_and_metadata() -> None:
    client = CopilotClient()
    request = CopilotRequest(
        prompt="hello",
        task_type=CopilotTaskType.TEST_EXECUTION,
        session_id="request-session",
        workflow_id="workflow-7",
        metadata={"origin": "test"},
    )

    response = client._normalize_sdk_response(
        request=request,
        resolved_model="gpt-default",
        sdk_result={
            "content": "assistant output",
            "model": "gpt-actual",
            "session_id": 123,
            "finish_reason": "stop",
            "usage": {
                "input_tokens": "10",
                "output_tokens": 5.0,
                "total_tokens": "15",
                "token_usage_ratio": "0.25",
            },
            "message_count": 4,
            "workspace_path": "/tmp/workspace",
        },
    )

    assert response.content == "assistant output"
    assert response.model == "gpt-actual"
    assert response.task_type == CopilotTaskType.TEST_EXECUTION
    assert response.session_id == "123"
    assert response.workflow_id == "workflow-7"
    assert response.finish_reason == "stop"
    assert response.usage.input_tokens == 10
    assert response.usage.output_tokens == 5
    assert response.usage.total_tokens == 15
    assert response.usage.token_usage_ratio == 0.25
    assert response.metadata == {
        "dry_run": False,
        "sdk_invoked": True,
        "request_metadata": {"origin": "test"},
        "message_count": 4,
        "workspace_path": "/tmp/workspace",
    }


def test_extract_helpers_cover_event_message_usage_and_finish_reason() -> None:
    client = CopilotClient()
    usage_obj = SimpleNamespace(
        inputTokens="11",
        outputTokens="7",
        totalTokens="18",
        tokenUsageRatio="0.5",
    )
    messages = [
        make_event("assistant.message", content="first"),
        make_event("assistant.message", content="latest"),
        make_event("other", usage=usage_obj, finishReason="length"),
    ]

    assert (
        client._extract_content_from_event(make_event(content="event text"))
        == "event text"
    )
    assert client._extract_content_from_event(None) == ""
    assert client._extract_content_from_messages(messages) == "latest"
    assert client._extract_usage_from_messages(messages) == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
        "token_usage_ratio": 0.5,
    }
    assert client._extract_finish_reason_from_messages(messages) == "length"


def test_object_and_event_normalization_helpers_handle_common_shapes() -> None:
    client = CopilotClient()

    class WithToDict:
        def to_dict(self) -> dict[str, object]:
            return {"alpha": 1}

    class WithVars:
        def __init__(self) -> None:
            self.visible = "yes"
            self._hidden = "no"

    event = make_event("assistant.message", content="hello")

    assert client._object_to_dict(None) == {}
    assert client._object_to_dict({"x": 1}) == {"x": 1}
    assert client._object_to_dict(WithToDict()) == {"alpha": 1}
    assert client._object_to_dict(WithVars()) == {"visible": "yes"}
    assert client._model_info_to_dict(WithToDict()) == {"alpha": 1}
    assert client._event_to_dict(event) == {
        "type": "assistant.message",
        "data": {"content": "hello"},
    }


def test_default_model_list_contains_expected_models_and_capabilities() -> None:
    client = CopilotClient()

    models = client._default_model_list()

    assert [model["id"] for model in models] == [
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
    ]
    assert models[0]["capabilities"]["supports"]["vision"] is True
    assert models[1]["capabilities"]["supports"]["reasoningEffort"] is True
    assert models[2]["capabilities"]["supports"]["reasoningEffort"] is False


def test_list_models_returns_default_models_when_sdk_disabled() -> None:
    client = CopilotClient(CopilotClientConfig(enable_sdk=False))

    models = run(client.list_models())

    assert models == client._default_model_list()


def test_list_models_returns_default_models_on_sdk_failure_when_fallback_enabled() -> (
    None
):
    client = CopilotClient(CopilotClientConfig(dry_run_fallback=True))

    def fail_import():
        raise RuntimeError("sdk unavailable")

    client._import_sdk_client_module = fail_import  # type: ignore[method-assign]

    models = run(client.list_models())

    assert models == client._default_model_list()


def test_list_models_raises_when_sdk_failure_and_fallback_disabled() -> None:
    client = CopilotClient(CopilotClientConfig(dry_run_fallback=False))

    def fail_import():
        raise RuntimeError("sdk unavailable")

    client._import_sdk_client_module = fail_import  # type: ignore[method-assign]

    try:
        run(client.list_models())
    except RuntimeError as exc:
        assert str(exc) == "sdk unavailable"
    else:
        raise AssertionError("Expected RuntimeError")


def test_normalization_coercion_helpers_handle_invalid_values() -> None:
    client = CopilotClient()

    assert client._coerce_int("12") == 12
    assert client._coerce_int("bad") is None
    assert client._coerce_float("1.5") == 1.5
    assert client._coerce_float("bad") is None
    assert client._coerce_optional_str(None) is None
    assert client._coerce_optional_str("") is None
    assert client._coerce_optional_str(42) == "42"
