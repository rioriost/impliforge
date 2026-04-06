from __future__ import annotations

import asyncio
from pathlib import Path
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


class DummyAsyncContextManager:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


class DummySession:
    def __init__(
        self,
        *,
        session_id: str = "sdk-session",
        workspace_path: str = "/tmp/workspace",
        event_result=None,
        messages=None,
    ) -> None:
        self.session_id = session_id
        self.workspace_path = workspace_path
        self.event_result = event_result
        self.messages = list(messages or [])
        self.send_calls: list[dict[str, object]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def send_and_wait(self, prompt: str, *, timeout: float):
        self.send_calls.append({"prompt": prompt, "timeout": timeout})
        return self.event_result

    async def get_messages(self):
        return list(self.messages)


class DummySdkClient:
    def __init__(self, session):
        self.session = session
        self.resume_calls: list[tuple[str, dict[str, object]]] = []
        self.create_calls: list[dict[str, object]] = []
        self.list_models_result = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def resume_session(self, session_id: str, **kwargs):
        self.resume_calls.append((session_id, kwargs))
        return self.session

    async def create_session(self, **kwargs):
        self.create_calls.append(kwargs)
        return self.session

    async def list_models(self):
        return list(self.list_models_result)


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


def test_validate_environment_accepts_existing_directories(tmp_path: Path) -> None:
    working_directory = tmp_path / "workspace"
    config_dir = tmp_path / "config"
    working_directory.mkdir()
    config_dir.mkdir()

    client = CopilotClient(
        CopilotClientConfig(
            working_directory=str(working_directory),
            config_dir=str(config_dir),
        )
    )

    validation = client.validate_environment()

    assert validation.ok is True
    assert validation.issues == ()


def test_validate_environment_reports_missing_working_directory(
    tmp_path: Path,
) -> None:
    missing_directory = tmp_path / "missing-workspace"
    client = CopilotClient(
        CopilotClientConfig(working_directory=str(missing_directory))
    )

    validation = client.validate_environment()

    assert validation.ok is False
    assert [issue.code for issue in validation.issues] == ["working_directory_missing"]
    assert validation.issues[0].message == (
        f"configured working directory does not exist: {missing_directory}"
    )


def test_validate_environment_reports_non_directory_config_path(
    tmp_path: Path,
) -> None:
    config_file = tmp_path / "copilot-config.json"
    config_file.write_text("{}", encoding="utf-8")
    client = CopilotClient(CopilotClientConfig(config_dir=str(config_file)))

    validation = client.validate_environment()

    assert validation.ok is False
    assert [issue.code for issue in validation.issues] == ["config_dir_not_directory"]
    assert validation.issues[0].message == (
        f"configured config directory is not a directory: {config_file}"
    )


def test_generate_uses_dry_run_fallback_when_environment_preflight_fails(
    tmp_path: Path,
) -> None:
    missing_directory = tmp_path / "missing-workspace"
    client = CopilotClient(
        CopilotClientConfig(
            default_model="gpt-default",
            working_directory=str(missing_directory),
        )
    )

    response = run(
        client.generate(
            CopilotRequest(
                prompt="Need output",
                task_type=CopilotTaskType.REVIEW,
            )
        )
    )

    assert response.is_dry_run is True
    assert response.metadata["reason"] == "sdk_error:CopilotClientError"
    assert "Copilot SDK preflight failed:" in response.metadata["error_message"]
    assert str(missing_directory) in response.metadata["error_message"]


def test_list_models_raises_client_error_when_environment_preflight_fails_and_fallback_disabled(
    tmp_path: Path,
) -> None:
    missing_directory = tmp_path / "missing-workspace"
    client = CopilotClient(
        CopilotClientConfig(
            working_directory=str(missing_directory),
            dry_run_fallback=False,
        )
    )

    try:
        run(client.list_models())
    except CopilotClientError as exc:
        assert "Copilot SDK preflight failed:" in str(exc)
        assert str(missing_directory) in str(exc)
    else:
        raise AssertionError("Expected CopilotClientError")


def test_validate_environment_allows_default_environment_assumptions() -> None:
    client = CopilotClient(CopilotClientConfig())

    validation = client.validate_environment()

    assert validation.ok is True
    assert validation.issues == ()


def test_validate_environment_ignores_unset_paths_when_other_path_is_valid(
    tmp_path: Path,
) -> None:
    working_directory = tmp_path / "workspace"
    working_directory.mkdir()
    client = CopilotClient(
        CopilotClientConfig(
            working_directory=str(working_directory),
            config_dir=None,
        )
    )

    validation = client.validate_environment()

    assert validation.ok is True
    assert validation.issues == ()


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
    assert models[2]["capabilities"]["supports"]["reasoningEffort"] is False


def test_invoke_sdk_uses_event_content_when_available() -> None:
    client = CopilotClient(CopilotClientConfig(timeout_seconds=12.5))
    event = make_event(
        "assistant.message",
        content="event content",
        usage={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
        finish_reason="stop",
    )
    messages = [
        make_event(
            "assistant.message",
            content="message content",
            usage={"input_tokens": 4, "output_tokens": 5, "total_tokens": 9},
            finish_reason="done",
        )
    ]
    session = DummySession(event_result=event, messages=messages)
    sdk_client = DummySdkClient(session)

    client._import_sdk_client_module = lambda: SimpleNamespace()  # type: ignore[method-assign]
    client._import_sdk_session_module = lambda: SimpleNamespace(  # type: ignore[method-assign]
        PermissionHandler=SimpleNamespace(approve_all="approve-all")
    )
    client._build_sdk_client = lambda module: sdk_client  # type: ignore[method-assign]

    result = run(
        client._invoke_sdk(
            CopilotRequest(
                prompt="hello",
                task_type=CopilotTaskType.GENERAL,
                workflow_id="wf-1",
            ),
            "gpt-5.4",
        )
    )

    assert result["content"] == "event content"
    assert result["model"] == "gpt-5.4"
    assert result["session_id"] == "sdk-session"
    assert result["workflow_id"] == "wf-1"
    assert result["finish_reason"] == "done"
    assert result["usage"]["input_tokens"] == 4
    assert result["message_count"] == 1
    assert session.send_calls == [{"prompt": "hello", "timeout": 12.5}]
    assert sdk_client.create_calls


def test_invoke_sdk_falls_back_to_message_content_when_event_has_none() -> None:
    client = CopilotClient()
    event = make_event("assistant.message")
    messages = [
        make_event(
            "assistant.message",
            content="message fallback",
            usage={"inputTokens": 7, "outputTokens": 8, "totalTokens": 15},
            finishReason="completed",
        )
    ]
    session = DummySession(event_result=event, messages=messages)
    sdk_client = DummySdkClient(session)

    client._import_sdk_client_module = lambda: SimpleNamespace()  # type: ignore[method-assign]
    client._import_sdk_session_module = lambda: SimpleNamespace(  # type: ignore[method-assign]
        PermissionHandler=SimpleNamespace(approve_all="approve-all")
    )
    client._build_sdk_client = lambda module: sdk_client  # type: ignore[method-assign]

    result = run(
        client._invoke_sdk(
            CopilotRequest(
                prompt="hello",
                session_id="resume-me",
                task_type=CopilotTaskType.REVIEW,
            ),
            "gpt-5.4-mini",
        )
    )

    assert result["content"] == "message fallback"
    assert result["finish_reason"] == "completed"
    assert result["usage"]["input_tokens"] == 7
    assert sdk_client.resume_calls[0][0] == "resume-me"


def test_list_models_uses_sdk_when_available() -> None:
    client = CopilotClient()
    sdk_client = DummySdkClient(session=None)
    sdk_client.list_models_result = [
        SimpleNamespace(to_dict=lambda: {"id": "sdk-model-1"}),
        SimpleNamespace(name="sdk-model-2"),
    ]

    client._import_sdk_client_module = lambda: SimpleNamespace()  # type: ignore[method-assign]
    client._build_sdk_client = lambda module: sdk_client  # type: ignore[method-assign]

    models = run(client.list_models())

    assert models == [
        {"id": "sdk-model-1"},
        {"name": "sdk-model-2"},
    ]


def test_extract_content_from_messages_returns_empty_when_no_assistant_message() -> (
    None
):
    client = CopilotClient()

    messages = [
        make_event("user.message", content="user"),
        make_event("system.message", content="system"),
    ]

    assert client._extract_content_from_messages(messages) == ""


def test_extract_usage_from_messages_returns_none_fields_when_missing() -> None:
    client = CopilotClient()

    usage = client._extract_usage_from_messages([make_event("assistant.message")])

    assert usage == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "token_usage_ratio": None,
    }


def test_extract_finish_reason_from_messages_returns_none_when_missing() -> None:
    client = CopilotClient()

    assert (
        client._extract_finish_reason_from_messages([make_event("assistant.message")])
        is None
    )


def test_event_to_dict_handles_missing_type_and_data() -> None:
    client = CopilotClient()

    payload = client._event_to_dict(SimpleNamespace(type=None, data=None))

    assert payload == {"type": None, "data": {}}


def test_model_info_to_dict_falls_back_to_object_dict() -> None:
    client = CopilotClient()

    payload = client._model_info_to_dict(SimpleNamespace(name="model-a", version="1"))

    assert payload == {"name": "model-a", "version": "1"}


def test_import_sdk_session_module_raises_client_error_when_missing(
    monkeypatch,
) -> None:
    client = CopilotClient()

    original_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "copilot.session":
            raise ImportError("missing session module")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    try:
        client._import_sdk_session_module()
    except CopilotClientError as exc:
        assert "session module is not importable" in str(exc)
    else:
        raise AssertionError("Expected CopilotClientError")


def test_demo_runs_generate_text_and_prints_content(monkeypatch) -> None:
    client = CopilotClient()
    captured: list[str] = []

    async def fake_generate_text(*args, **kwargs):
        return CopilotResponse(
            content="demo output",
            model="gpt-5.4",
            task_type=CopilotTaskType.SUMMARY,
        )

    monkeypatch.setattr(
        "devagents.runtime.copilot_client.CopilotClient", lambda: client
    )
    monkeypatch.setattr(client, "generate_text", fake_generate_text)
    monkeypatch.setattr("builtins.print", lambda value: captured.append(str(value)))

    from devagents.runtime import copilot_client as copilot_client_module

    run(copilot_client_module._demo())

    assert captured == ["demo output"]


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
