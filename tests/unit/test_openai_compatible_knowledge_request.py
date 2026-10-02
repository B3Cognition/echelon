from __future__ import annotations

from dataclasses import replace
import io
import json
import socket
import urllib.error
import pytest

from harness.ai_cli_backend import ConstrainedPromptBackend
from harness.ai_cli_backend import CliRunRequest
from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend
from harness.config import HarnessConfig, LlmConfig
from harness.llm_provider import AICodingCliProvider
from harness.llm_tool_policy import LlmToolPolicy, inject_llm_tool_policy_preamble
from harness.re_v2.knowledge_llm import KnowledgeLLMBackend
from harness.re_v2.protocol_22.provider import DispatchReservationV1


def _config(*, model: str = "local-model", unsafe: bool = False) -> HarnessConfig:
    return HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(
            cli="openai-compatible",
            base_url="http://127.0.0.1:8000/v1",
            model=model,
            api_key_env="LOCAL_LLM_API_KEY",
            temperature=0.2,
            max_tokens=256,
            tool_policy=LlmToolPolicy(
                allow_unsafe_host_execution=unsafe,
                approval_reason="ordinary execution approved" if unsafe else None,
            ),
        ),
    )


def _request(tmp_path, **changes) -> CliRunRequest:
    return replace(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return one JSON object.",
            env={},
            timeout_s=12.5,
        ),
        **changes,
    )


class _FakeResponse:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, payload: object | bytes) -> None:
        self.payload = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload, separators=(",", ":")).encode()
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, limit: int = -1) -> bytes:
        return self.payload[:limit]


def _call(tmp_path, *, screen_output=lambda value: value, **changes):
    kwargs = {
        "model": "configured-model",
        "screen_output": screen_output,
        "max_input_bytes": 64 * 1024,
        "max_capture_bytes": 64 * 1024,
    }
    kwargs.update(changes)
    return OpenAICompatibleBackend(_config()).run_constrained_prompt(
        _request(tmp_path),
        **kwargs,
    )


def test_openai_compatible_backend_advertises_constrained_execution() -> None:
    backend = OpenAICompatibleBackend(_config())

    assert isinstance(backend, ConstrainedPromptBackend)
    assert (
        backend.constrained_execution_contract_id
        == "openai-compatible-constrained-prompt-v1"
    )


@pytest.mark.parametrize("tier", ["fast", "balanced", "strong", "ultra"])
def test_openai_compatible_constrained_tiers_use_configured_model(tier: str) -> None:
    backend = OpenAICompatibleBackend(_config(model="one-configured-model"))

    assert backend.model_for_tier(tier) == "one-configured-model"


def test_openai_compatible_rejects_unknown_constrained_tier() -> None:
    backend = OpenAICompatibleBackend(_config())

    assert backend.model_for_tier("unknown") is None
    assert backend.model_for_tier(1) is None  # type: ignore[arg-type]


def test_openai_compatible_capability_is_visible_through_provider_facade() -> None:
    provider = AICodingCliProvider(_config(model="configured-model"))

    assert provider.provider_id == "openai-compatible"
    assert (
        provider.constrained_execution_contract_id
        == "openai-compatible-constrained-prompt-v1"
    )
    assert provider.constrained_model_for_tier("ultra") == "configured-model"


def test_openai_compatible_constrained_request_is_bounded_tool_free_and_accounted(
    tmp_path, monkeypatch
) -> None:
    captured: dict[str, object] = {}
    config = _config(model="configured-model")
    config.llm.features = {"streaming": True, "tool_calls": True}
    expected_prompt = inject_llm_tool_policy_preamble(
        "Return one JSON object.", config.llm.tool_policy
    )

    class FakeResponse:
        status = 200
        headers = {"Content-Type": "application/json", "X-Request-ID": "req_123"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, limit: int = -1) -> bytes:
            captured["read_limit"] = limit
            return json.dumps(
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": '{"ok":true}'},
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 7,
                        "completion_tokens": 5,
                        "total_tokens": 12,
                        "prompt_tokens_details": {"cached_tokens": 2},
                        "completion_tokens_details": {"reasoning_tokens": 3},
                    },
                },
                separators=(",", ":"),
            ).encode()[:limit]

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode())
        return FakeResponse()

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )
    seen: list[bytes] = []

    def screen_input(value: bytes) -> bytes:
        seen.append(value)
        return value if value == expected_prompt.encode() else b""

    result = OpenAICompatibleBackend(config).run_constrained_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return one JSON object.",
            env={"LOCAL_LLM_API_KEY": "secret-token"},
            timeout_s=12.5,
        ),
        model="configured-model",
        screen_output=lambda value: seen.append(value) or value,
        screen_input=screen_input,
        max_input_bytes=64 * 1024,
        max_capture_bytes=64 * 1024,
    )

    assert result.exit_code == 0
    assert result.stdout == '{"ok":true}'
    assert result.stderr == ""
    assert result.token_usage == 12
    assert result.metadata["request_model"] == "configured-model"
    assert result.metadata["token_usage_status"] == "trusted_exact"
    assert result.metadata["token_usage_details"] == {
        "input_tokens": 7,
        "cached_input_tokens": 2,
        "output_tokens": 5,
        "reasoning_output_tokens": 3,
        "total_tokens": 12,
    }
    assert expected_prompt.encode() in seen
    assert b'{"ok":true}' in seen
    assert captured["url"] == "http://127.0.0.1:8000/v1/chat/completions"
    assert captured["timeout"] == 12.5
    assert captured["read_limit"] == 64 * 1024 + 1
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["payload"] == {
        "model": "configured-model",
        "messages": [{"role": "user", "content": expected_prompt}],
        "temperature": 0.2,
        "max_tokens": 256,
        "stream": False,
    }


@pytest.mark.parametrize(
    ("request_changes", "call_changes", "reason"),
    [
        ({"prompt": ""}, {}, "invalid_request"),
        ({"prompt": "bad\ud800"}, {}, "invalid_request"),
        ({"timeout_s": 0}, {}, "invalid_request"),
        ({"metadata": {"tool_read_roots": ["."]}}, {}, "invalid_request"),
        ({}, {"model": "bad model"}, "invalid_request"),
        ({}, {"max_input_bytes": 0}, "invalid_request"),
        ({}, {"max_capture_bytes": 0}, "invalid_request"),
        ({}, {"screen_input": "invalid"}, "invalid_request"),
    ],
)
def test_openai_compatible_constrained_request_rejects_invalid_scope_before_http(
    tmp_path, monkeypatch, request_changes, call_changes, reason
) -> None:
    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda *_args, **_kwargs: pytest.fail("must reject before HTTP"),
    )
    kwargs = {
        "model": "configured-model",
        "screen_output": lambda value: value,
        "max_input_bytes": 64 * 1024,
        "max_capture_bytes": 64 * 1024,
    }
    kwargs.update(call_changes)

    result = OpenAICompatibleBackend(_config()).run_constrained_prompt(
        _request(tmp_path, **request_changes),
        **kwargs,
    )

    assert result.exit_code == 125
    assert result.stdout == ""
    assert result.metadata["failure_reason"] == reason


def test_openai_compatible_constrained_request_rejects_nonempty_cwd_before_http(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "unexpected.txt").write_text("not empty", encoding="utf-8")
    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda *_args, **_kwargs: pytest.fail("must reject before HTTP"),
    )

    result = OpenAICompatibleBackend(_config()).run_constrained_prompt(
        _request(tmp_path),
        model="configured-model",
        screen_output=lambda value: value,
        max_input_bytes=64 * 1024,
        max_capture_bytes=64 * 1024,
    )

    assert result.metadata["failure_reason"] == "invalid_request"


def test_openai_compatible_constrained_request_distinguishes_input_overflow(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda *_args, **_kwargs: pytest.fail("must reject before HTTP"),
    )

    result = OpenAICompatibleBackend(_config()).run_constrained_prompt(
        _request(tmp_path),
        model="configured-model",
        screen_output=lambda value: value,
        max_input_bytes=1,
        max_capture_bytes=64 * 1024,
    )

    assert result.metadata["failure_reason"] == "input_overflow"


def test_openai_compatible_constrained_request_rejects_input_screen_change(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda *_args, **_kwargs: pytest.fail("must reject before HTTP"),
    )

    result = OpenAICompatibleBackend(_config()).run_constrained_prompt(
        _request(tmp_path),
        model="configured-model",
        screen_output=lambda value: value,
        screen_input=lambda _value: b"changed",
        max_input_bytes=64 * 1024,
        max_capture_bytes=64 * 1024,
    )

    assert result.metadata["failure_reason"] == "screen_rejected"


def test_openai_compatible_constrained_request_rejects_response_body_overflow(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(b"x" * 65),
    )

    result = _call(tmp_path, max_capture_bytes=64)

    assert result.metadata["failure_reason"] == "capture_overflow"


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (
            {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [{"id": "call_1"}],
                        },
                    }
                ]
            },
            "tool_event",
        ),
        (
            {
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"role": "assistant", "content": "partial"},
                    }
                ]
            },
            "incomplete_response",
        ),
        (
            {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "one"}},
                    {"finish_reason": "stop", "message": {"content": "two"}},
                ]
            },
            "malformed_response",
        ),
        (
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": ["not text"]},
                    }
                ]
            },
            "malformed_response",
        ),
        (b"\xff", "malformed_response"),
    ],
)
def test_openai_compatible_constrained_request_rejects_unsafe_response_shapes(
    tmp_path, monkeypatch, payload, reason
) -> None:
    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(payload),
    )

    result = _call(tmp_path)

    assert result.exit_code == 125
    assert result.stdout == ""
    assert result.metadata["failure_reason"] == reason


def test_openai_compatible_constrained_request_rejects_changed_output(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "answer"},
                    }
                ]
            }
        ),
    )

    result = _call(tmp_path, screen_output=lambda _value: b"changed")

    assert result.metadata["failure_reason"] == "screen_rejected"


def test_openai_compatible_constrained_timeout_is_generic_and_durable(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(socket.timeout("secret")),
    )

    result = _call(tmp_path)

    assert result.exit_code == 124
    assert result.timed_out is True
    assert result.stderr == "screened OpenAI-compatible request failed"
    assert "secret" not in result.stderr
    assert result.metadata["failure_reason"] == "timeout"


def test_openai_compatible_constrained_http_error_does_not_expose_body(
    tmp_path, monkeypatch
) -> None:
    error = urllib.error.HTTPError(
        "http://127.0.0.1:8000/v1/chat/completions",
        500,
        "failure",
        {},
        io.BytesIO(b"source secret"),
    )
    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    result = _call(tmp_path)

    assert result.metadata["failure_reason"] == "transport_error"
    assert "source secret" not in result.stderr


@pytest.mark.parametrize(
    ("usage", "expected_total", "expected_status"),
    [
        (None, None, "unavailable"),
        (
            {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 99},
            99,
            "untrusted",
        ),
        (
            {
                "prompt_tokens": 7,
                "completion_tokens": 5,
                "total_tokens": 12,
                "unexpected_class": 1,
            },
            12,
            "untrusted",
        ),
    ],
)
def test_openai_compatible_constrained_usage_fails_closed_without_rejecting_answer(
    tmp_path, monkeypatch, usage, expected_total, expected_status
) -> None:
    payload = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "answer"},
            }
        ]
    }
    if usage is not None:
        payload["usage"] = usage
    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(payload),
    )

    result = _call(tmp_path)

    assert result.exit_code == 0
    assert result.stdout == "answer"
    assert result.token_usage == expected_total
    assert result.metadata["token_usage_status"] == expected_status
    if expected_status != "trusted_exact":
        assert result.metadata["token_usage_details"] == {}


def test_openai_compatible_runs_complete_re_bridge_with_safe_authenticated_input(
    monkeypatch
) -> None:
    captured: dict[str, object] = {}
    answer = (
        '{"result":"ok"}'
        "\nechelon_result:\n  verdict: DONE\n  state_updates: {}\n"
    )

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return _FakeResponse(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": answer},
                    }
                ],
                "usage": {
                    "prompt_tokens": 8,
                    "completion_tokens": 4,
                    "total_tokens": 12,
                },
            }
        )

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )
    backend = KnowledgeLLMBackend(
        _config(model="one-model", unsafe=True),
        model_tier="ultra",
        screen_output=lambda value: value,
        max_capture_bytes=64 * 1024,
    )

    reply = backend(
        b"Neutral RE role.",
        b'{"frozen":"context"}',
        DispatchReservationV1(64 * 1024, 64 * 1024, 10_000),
    )

    assert reply.reason_code is None
    assert reply.output == b'{"result":"ok"}'
    assert reply.usage.status == "trusted_exact"
    assert backend.contract.provider_id == "openai-compatible"
    assert backend.contract.model_id == "one-model"
    assert captured["timeout"] == 10.0
    prompt = captured["payload"]["messages"][0]["content"]
    assert "Unsafe host execution bypass: disabled" in prompt
    assert "ordinary execution approved" not in prompt


def test_openai_compatible_constrained_request_ignores_known_reasoning_extension(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "answer",
                            "reasoning_content": "private notes",
                        },
                    }
                ]
            }
        ),
    )

    result = _call(tmp_path)

    assert result.exit_code == 0
    assert result.stdout == "answer"
    assert "private notes" not in result.stdout


def test_openai_compatible_constrained_request_rejects_legacy_function_call(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(
            {
                "choices": [
                    {
                        "finish_reason": "function_call",
                        "message": {
                            "role": "assistant",
                            "content": "answer",
                            "function_call": {
                                "name": "read_file",
                                "arguments": '{"path":"secret"}',
                            },
                        },
                    }
                ]
            }
        ),
    )

    result = _call(tmp_path)

    assert result.exit_code == 125
    assert result.metadata["failure_reason"] == "tool_event"
