from __future__ import annotations

import hashlib
import io
import json
import socket
import subprocess
import sys
import time
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.ai_cli_backend import CliRunRequest, CliRunResult, create_ai_cli_backend
from harness.ai_cli_backends.claude import ClaudeCliBackend
from harness.ai_cli_backends.codex import CodexCliBackend
from harness.ai_cli_backends.copilot import CopilotCliBackend
from harness.ai_cli_backends.opencode import OpenCodeCliBackend
from harness.ai_cli_backends.plain import PlainCliBackend
from harness.config import HarnessConfig, LlmConfig


def _config(cli: str) -> HarnessConfig:
    return HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli=cli),
    )


def _openai_config(features: dict[str, object] | None = None) -> HarnessConfig:
    return HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(
            cli="openai-compatible",
            base_url="http://127.0.0.1:8000/v1",
            model="local-model",
            api_key_env="LOCAL_LLM_API_KEY",
            temperature=0.2,
            max_tokens=256,
            features=features or {},
        ),
    )


def _registry_tool_payload(registry, name: str, args: dict[str, object]) -> dict[str, object]:
    message = registry.execute_message({
        "id": f"call_{name}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    })
    content = message.get("content")
    assert isinstance(content, str)
    parsed = json.loads(content)
    assert isinstance(parsed, dict)
    return parsed


def test_cli_run_result_defaults() -> None:
    result = CliRunResult(exit_code=0, stdout="ok", stderr="")

    assert result.exit_code == 0
    assert result.stdout == "ok"
    assert result.stderr == ""
    assert result.token_usage == 0
    assert result.cost_usd == 0.0
    assert result.timed_out is False


def test_cli_run_request_carries_prompt_and_timeout(tmp_path) -> None:
    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Do work.",
        env={"A": "B"},
        timeout_s=12.5,
    )

    assert request.cwd == str(tmp_path)
    assert request.prompt == "Do work."
    assert request.env == {"A": "B"}
    assert request.timeout_s == 12.5


@pytest.mark.parametrize(
    ("cli", "class_name"),
    [
        ("claude", "ClaudeCliBackend"),
        ("codex", "CodexCliBackend"),
        ("copilot", "CopilotCliBackend"),
        ("opencode", "OpenCodeCliBackend"),
    ],
)
def test_backend_factory_returns_concrete_backend(cli: str, class_name: str) -> None:
    backend = create_ai_cli_backend(_config(cli))

    assert backend.__class__.__name__ == class_name
    assert backend.name == cli


def test_backend_factory_returns_openai_compatible_backend() -> None:
    backend = create_ai_cli_backend(_openai_config())

    assert backend.__class__.__name__ == "OpenAICompatibleBackend"
    assert backend.name == "openai-compatible"


def test_openai_compatible_backend_posts_chat_completion(tmp_path, monkeypatch) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    captured = {}
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "secret-token")

    class FakeResponse:
        status = 200
        headers = {
            "Content-Type": "application/json",
            "X-Request-ID": "req_123",
            "Set-Cookie": "session=secret",
        }

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "choices": [
                    {"message": {"content": "echelon_result:\n  verdict: DONE\n"}}
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 5},
            }).encode()

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
    backend = OpenAICompatibleBackend(_openai_config(features={"streaming": False}))
    result = backend.run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert result.stdout == "echelon_result:\n  verdict: DONE\n"
    assert result.token_usage == 12
    assert result.metadata["token_usage_details"] == {
        "prompt_tokens": 7,
        "completion_tokens": 5,
        "total_tokens": 12,
    }
    assert result.metadata["http_status"] == 200
    assert result.metadata["raw_response_headers"] == {
        "content-type": "application/json",
        "x-request-id": "req_123",
    }
    assert captured["url"] == "http://127.0.0.1:8000/v1/chat/completions"
    assert captured["timeout"] == 12.5
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["payload"]["model"] == "local-model"
    assert captured["payload"]["messages"] == [
        {"role": "user", "content": "Return a result."}
    ]
    assert captured["payload"]["temperature"] == 0.2
    assert captured["payload"]["max_tokens"] == 256
    assert "stream" not in captured["payload"]


def test_openai_compatible_backend_can_request_json_mode(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": "{\"ok\": true}"}}],
            }).encode()

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode())
        return FakeResponse()

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = OpenAICompatibleBackend(
        _openai_config(features={"streaming": False, "json_mode": True})
    ).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return JSON.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert captured["payload"]["response_format"] == {"type": "json_object"}


def test_openai_compatible_backend_can_request_reasoning_effort(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": "ok"}}],
            }).encode()

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode())
        return FakeResponse()

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = OpenAICompatibleBackend(
        _openai_config(features={"streaming": False, "reasoning_effort": "high"})
    ).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert captured["payload"]["reasoning_effort"] == "high"


def test_openai_compatible_backend_uses_prompt_metadata_overrides(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": "ok"}}],
            }).encode()

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode())
        return FakeResponse()

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = OpenAICompatibleBackend(
        _openai_config(features={"streaming": False, "reasoning_effort": "low"})
    ).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
            metadata={
                "prompt_metadata": {
                    "model": "frontmatter-model",
                    "effort": "high",
                    "temperature": 0.4,
                    "max_tokens": 1024,
                }
            },
        )
    )

    assert result.exit_code == 0
    assert captured["payload"]["model"] == "frontmatter-model"
    assert captured["payload"]["reasoning_effort"] == "high"
    assert captured["payload"]["temperature"] == 0.4
    assert captured["payload"]["max_tokens"] == 1024


def test_openai_compatible_backend_records_http_error_response_headers(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            {
                "Content-Type": "application/json",
                "OpenAI-Request-ID": "req_error",
                "Set-Cookie": "session=secret",
            },
            io.BytesIO(b'{"error":"rate limit"}'),
        )

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = OpenAICompatibleBackend(
        _openai_config(features={"streaming": False})
    ).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 429
    assert result.metadata["provider_error_code"] == "http_error"
    assert result.metadata["http_status"] == 429
    assert result.metadata["raw_response_headers"] == {
        "content-type": "application/json",
        "openai-request-id": "req_error",
    }


def test_openai_compatible_backend_reads_nonstreaming_content_blocks(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"type": "text", "text": "echelon_result:\n"},
                                {"type": "text", "text": "  verdict: PASS\n"},
                            ],
                        },
                    }
                ],
                "usage": {"total_tokens": 11},
            }).encode()

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(),
    )

    result = OpenAICompatibleBackend(_openai_config(features={"streaming": False})).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert result.stdout == "echelon_result:\n  verdict: PASS\n"
    assert result.token_usage == 11


def test_openai_compatible_backend_records_nonstreaming_response_metadata(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "id": "chatcmpl-123",
                "object": "chat.completion",
                "created": 1_725_000_000,
                "model": "local-model",
                "system_fingerprint": "fp_local",
                "choices": [{"message": {"content": "ok"}}],
            }).encode()

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(),
    )

    result = OpenAICompatibleBackend(_openai_config(features={"streaming": False})).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert result.metadata["raw_response_metadata"] == {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1_725_000_000,
        "model": "local-model",
        "system_fingerprint": "fp_local",
    }


def test_openai_compatible_backend_rejects_nonstreaming_truncation(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "choices": [
                    {
                        "message": {"content": "echelon_result:\n  verdict:"},
                        "finish_reason": "length",
                    }
                ],
                "usage": {"total_tokens": 31},
            }).encode()

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(),
    )

    result = OpenAICompatibleBackend(_openai_config(features={"streaming": False})).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 1
    assert result.stdout == "echelon_result:\n  verdict:"
    assert result.token_usage == 31
    assert "finish_reason=length" in result.stderr
    assert result.metadata["finish_reason"] == "length"
    assert result.metadata["provider_error_code"] == "incomplete_generation"


def test_openai_compatible_backend_prefers_request_env_api_key(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    captured = {}
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "process-token")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": "ok"}}],
            }).encode()

    def fake_urlopen(request, timeout):
        captured["headers"] = dict(request.header_items())
        return FakeResponse()

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = OpenAICompatibleBackend(_openai_config(features={"streaming": False})).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={"LOCAL_LLM_API_KEY": "request-token"},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert captured["headers"]["Authorization"] == "Bearer request-token"


def test_openai_compatible_backend_reads_api_key_file(tmp_path, monkeypatch) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    captured = {}
    token_file = tmp_path / ".omlx_token"
    token_file.write_text("file-token\n", encoding="utf-8")
    config = _openai_config(features={"streaming": False})
    config.llm.api_key_env = None
    config.llm.api_key_file = str(token_file)

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": "ok"}}],
            }).encode()

    def fake_urlopen(request, timeout):
        captured["headers"] = dict(request.header_items())
        return FakeResponse()

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = OpenAICompatibleBackend(config).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert captured["headers"]["Authorization"] == "Bearer file-token"


def test_openai_compatible_backend_rejects_missing_api_key_file(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    config = _openai_config(features={"streaming": False})
    config.llm.api_key_env = None
    config.llm.api_key_file = str(tmp_path / "missing-token")

    def fail_urlopen(request, timeout):
        raise AssertionError("request should be blocked before HTTP")

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fail_urlopen,
    )

    result = OpenAICompatibleBackend(config).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 1
    assert "API key file" in result.stderr
    assert "missing-token" in result.stderr
    assert result.metadata["provider_error_code"] == "api_key_file_error"


def test_openai_compatible_backend_rejects_empty_api_key_file(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    token_file = tmp_path / ".omlx_token"
    token_file.write_text("\n", encoding="utf-8")
    config = _openai_config(features={"streaming": False})
    config.llm.api_key_env = None
    config.llm.api_key_file = str(token_file)

    def fail_urlopen(request, timeout):
        raise AssertionError("request should be blocked before HTTP")

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fail_urlopen,
    )

    result = OpenAICompatibleBackend(config).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 1
    assert "API key file is empty" in result.stderr
    assert result.metadata["provider_error_code"] == "api_key_file_error"


def test_openai_compatible_backend_streams_sse_and_excludes_reasoning(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    captured = {}

    class FakeResponse:
        status = 200
        headers = {
            "Content-Type": "text/event-stream",
            "X-Request-ID": "req_stream",
        }

        def __init__(self) -> None:
            self._lines = iter([
                b'data: {"choices":[{"delta":{"reasoning_content":"private notes"}}]}\n',
                b'data: {"choices":[{"delta":{"content":"echelon_result:\\n"}}]}\n',
                b'data: {"choices":[{"delta":{"content":"  verdict: PASS\\n"},"finish_reason":"stop"}],"usage":{"total_tokens":42}}\n',
                b"data: [DONE]\n",
            ])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            return next(self._lines, b"")

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )
    backend = OpenAICompatibleBackend(_openai_config())
    result = backend.run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert result.stdout == "echelon_result:\n  verdict: PASS\n"
    assert "private notes" not in result.stdout
    assert result.token_usage == 42
    assert result.metadata["token_usage_details"] == {"total_tokens": 42}
    assert captured["payload"]["stream"] is True
    assert captured["payload"]["stream_options"] == {"include_usage": True}
    assert captured["timeout"] == 12.5
    assert result.metadata["http_status"] == 200
    assert result.metadata["raw_response_headers"] == {
        "content-type": "text/event-stream",
        "x-request-id": "req_stream",
    }
    assert result.metadata["streamed"] is True
    assert result.metadata["finish_reason"] == "stop"
    assert result.metadata["reasoning_content_observed"] is True


def test_openai_compatible_backend_can_omit_stream_options(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    captured = {}

    class FakeResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self) -> None:
            self._lines = iter([
                b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}],"usage":{"total_tokens":1}}\n',
                b"data: [DONE]\n",
            ])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            return next(self._lines, b"")

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode())
        return FakeResponse()

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = OpenAICompatibleBackend(
        _openai_config(features={"stream_options": False})
    ).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert captured["payload"]["stream"] is True
    assert "stream_options" not in captured["payload"]


def test_openai_compatible_backend_reports_reasoning_content_policy(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    class FakeResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self) -> None:
            self._lines = iter([
                b'data: {"choices":[{"delta":{"content":"echelon_result:\\n"},"finish_reason":"stop"}]}\n',
                b"data: [DONE]\n",
            ])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            return next(self._lines, b"")

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(),
    )

    result = OpenAICompatibleBackend(
        _openai_config(features={"reasoning_content": "merged"})
    ).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert result.metadata["reasoning_content_policy"] == "merged"
    assert result.metadata["reasoning_content_observed"] is False


def test_openai_compatible_backend_streams_content_blocks(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    class FakeResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self) -> None:
            self._lines = iter([
                b'data: {"choices":[{"delta":{"content":[{"type":"text","text":"echelon_result:\\n"}]}}]}\n',
                b'data: {"choices":[{"delta":{"content":[{"type":"text","text":"  verdict: PASS\\n"}]},"finish_reason":"stop"}],"usage":{"total_tokens":13}}\n',
                b"data: [DONE]\n",
            ])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            return next(self._lines, b"")

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(),
    )

    result = OpenAICompatibleBackend(_openai_config()).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert result.stdout == "echelon_result:\n  verdict: PASS\n"
    assert result.token_usage == 13


def test_openai_compatible_backend_streams_message_content_chunks(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    class FakeResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self) -> None:
            self._lines = iter([
                b'data: {"choices":[{"message":{"content":"echelon_result:\\n"}}]}\n',
                b'data: {"choices":[{"message":{"content":"  verdict: PASS\\n"},"finish_reason":"stop"}],"usage":{"total_tokens":23}}\n',
                b"data: [DONE]\n",
            ])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            return next(self._lines, b"")

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(),
    )

    result = OpenAICompatibleBackend(_openai_config()).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert result.stdout == "echelon_result:\n  verdict: PASS\n"
    assert result.token_usage == 23


def test_openai_compatible_backend_streams_choice_text_chunks(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    class FakeResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self) -> None:
            self._lines = iter([
                b'data: {"choices":[{"text":"echelon_result:\\n"}]}\n',
                b'data: {"choices":[{"text":"  verdict: PASS\\n","finish_reason":"stop"}],"usage":{"total_tokens":29}}\n',
                b"data: [DONE]\n",
            ])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            return next(self._lines, b"")

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(),
    )

    result = OpenAICompatibleBackend(_openai_config()).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert result.stdout == "echelon_result:\n  verdict: PASS\n"
    assert result.token_usage == 29


def test_openai_compatible_backend_observes_streaming_reasoning_aliases(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    class FakeResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self) -> None:
            self._lines = iter([
                b'data: {"choices":[{"delta":{"reasoning":"private notes"}}]}\n',
                b'data: {"choices":[{"delta":{"reasoning_text":"more private notes"}}]}\n',
                b'data: {"choices":[{"delta":{"content":"echelon_result:\\n  verdict: PASS\\n"},"finish_reason":"stop"}],"usage":{"total_tokens":31}}\n',
                b"data: [DONE]\n",
            ])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            return next(self._lines, b"")

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(),
    )

    result = OpenAICompatibleBackend(_openai_config()).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert result.stdout == "echelon_result:\n  verdict: PASS\n"
    assert "private notes" not in result.stdout
    assert result.metadata["reasoning_content_observed"] is True


def test_openai_compatible_backend_ignores_empty_stream_data_events(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    class FakeResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self) -> None:
            self._lines = iter([
                b"data:\n",
                b"\n",
                b'data: {"choices":[{"delta":{"content":"echelon_result:\\n"}}]}\n',
                b'data: {"choices":[{"delta":{"content":"  verdict: PASS\\n"},"finish_reason":"stop"}],"usage":{"total_tokens":33}}\n',
                b"data: [DONE]\n",
            ])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            return next(self._lines, b"")

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(),
    )

    result = OpenAICompatibleBackend(_openai_config()).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert result.stdout == "echelon_result:\n  verdict: PASS\n"
    assert result.token_usage == 33


def test_openai_compatible_backend_accepts_indented_sse_data_lines(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    class FakeResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self) -> None:
            self._lines = iter([
                b'  data: {"choices":[{"delta":{"content":"echelon_result:\\n"}}]}\n',
                b'  data: {"choices":[{"delta":{"content":"  verdict: PASS\\n"},"finish_reason":"stop"}],"usage":{"total_tokens":35}}\n',
                b"  data: [DONE]\n",
            ])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            return next(self._lines, b"")

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(),
    )

    result = OpenAICompatibleBackend(_openai_config()).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert result.stdout == "echelon_result:\n  verdict: PASS\n"
    assert result.token_usage == 35


def test_openai_compatible_backend_accepts_case_insensitive_done_marker(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    class FakeResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self) -> None:
            self._lines = iter([
                b'data: {"choices":[{"delta":{"content":"echelon_result:\\n  verdict: PASS\\n"},"finish_reason":"stop"}],"usage":{"total_tokens":37}}\n',
                b"data: [Done]\n",
            ])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            return next(self._lines, b"")

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(),
    )

    result = OpenAICompatibleBackend(_openai_config()).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert result.stdout == "echelon_result:\n  verdict: PASS\n"
    assert result.token_usage == 37


def test_openai_compatible_backend_records_streaming_response_metadata(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    class FakeResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self) -> None:
            self._lines = iter([
                b'data: {"id":"chatcmpl-stream","object":"chat.completion.chunk","created":1725000001,"model":"local-model","system_fingerprint":"fp_stream","choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n',
                b"data: [DONE]\n",
            ])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            return next(self._lines, b"")

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(),
    )

    result = OpenAICompatibleBackend(_openai_config()).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert result.metadata["raw_response_metadata"] == {
        "id": "chatcmpl-stream",
        "object": "chat.completion.chunk",
        "created": 1_725_000_001,
        "model": "local-model",
        "system_fingerprint": "fp_stream",
    }


def test_openai_compatible_backend_rejects_streaming_truncation(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    class FakeResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self) -> None:
            self._lines = iter([
                b'data: {"choices":[{"delta":{"content":"echelon_result:\\n  verdict:"},"finish_reason":"length"}],"usage":{"total_tokens":37}}\n',
                b"data: [DONE]\n",
            ])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            return next(self._lines, b"")

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(),
    )

    result = OpenAICompatibleBackend(_openai_config()).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 1
    assert result.stdout == "echelon_result:\n  verdict:"
    assert result.token_usage == 37
    assert "finish_reason=length" in result.stderr
    assert result.metadata["streamed"] is True
    assert result.metadata["provider_error_code"] == "incomplete_generation"


def test_openai_compatible_backend_parses_unlabeled_sse_body(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    class FakeResponse:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return (
                b'data: {"choices":[{"delta":{"content":"echelon_result:\\n"}}]}\n\n'
                b'data: {"choices":[{"delta":{"content":"  verdict: PASS\\n"},"finish_reason":"stop"}],"usage":{"total_tokens":17}}\n\n'
                b"data: [DONE]\n\n"
            )

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(),
    )

    result = OpenAICompatibleBackend(_openai_config()).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert result.stdout == "echelon_result:\n  verdict: PASS\n"
    assert result.token_usage == 17
    assert result.metadata["streamed"] is True


def test_openai_compatible_backend_streams_multiline_sse_events(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    class FakeResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self) -> None:
            self._lines = iter([
                b'data: {"choices":[\n',
                b'data: {"delta":{"content":"echelon_result:\\n"}}\n',
                b"data: ]}\n",
                b"\n",
                b'data: {"choices":[{"delta":{"content":"  verdict: PASS\\n"},"finish_reason":"stop"}],"usage":{"total_tokens":19}}\n',
                b"data: [DONE]\n",
            ])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            return next(self._lines, b"")

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(),
    )

    result = OpenAICompatibleBackend(_openai_config()).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert result.stdout == "echelon_result:\n  verdict: PASS\n"
    assert result.token_usage == 19


def test_openai_compatible_backend_rejects_streamed_tool_calls(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    class FakeResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self) -> None:
            self._lines = iter([
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"write_file","arguments":"{}"}}]}}]}\n',
            ])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            return next(self._lines, b"")

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(),
    )
    backend = OpenAICompatibleBackend(_openai_config())
    result = backend.run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 1
    assert "tool_calls are not supported" in result.stderr
    assert result.metadata["provider_error_code"] == "unsupported_tool_calls"


def test_openai_compatible_backend_sends_tool_registry_when_enabled(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            }).encode()

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode())
        return FakeResponse()

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = OpenAICompatibleBackend(
        _openai_config(features={"streaming": False, "tool_calls": True})
    ).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Write an artifact.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert captured["payload"]["messages"][0]["role"] == "system"
    assert "Prefer bulk context tools first" in captured["payload"]["messages"][0]["content"]
    assert "Use sha256_file" in captured["payload"]["messages"][0]["content"]
    assert captured["payload"]["messages"][1] == {
        "role": "user",
        "content": "Write an artifact.",
    }
    tool_names = [
        tool["function"]["name"]
        for tool in captured["payload"]["tools"]
    ]
    assert "read_file" in tool_names
    assert "sha256_file" in tool_names
    assert "write_file" in tool_names
    assert "grep_files" in tool_names
    assert "list_files" in tool_names
    assert "read_many_files" in tool_names
    assert "list_tree_with_sizes" in tool_names
    assert "grep_context" in tool_names
    assert "read_domain_pack" in tool_names
    assert "read_re_analysis_pack" in tool_names
    assert "codegraph_context" in tool_names
    assert "perlgraph_context" in tool_names
    assert captured["payload"]["tool_choice"] == "auto"


def test_openai_compatible_registry_hashes_file_inside_read_scope(tmp_path) -> None:
    from harness.ai_cli_backends.openai_compatible import _OpenAIToolRegistry

    source = tmp_path / "spec.md"
    source.write_text("# Spec\n", encoding="utf-8")
    registry = _OpenAIToolRegistry(
        tmp_path,
        {},
        {"tool_read_roots": [str(source)]},
    )

    result = _registry_tool_payload(registry, "sha256_file", {"path": "spec.md"})

    assert result == {
        "status": "ok",
        "path": "spec.md",
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "bytes": len(source.read_bytes()),
    }


def test_openai_compatible_registry_executes_bulk_context_tools(tmp_path) -> None:
    from harness.ai_cli_backends.openai_compatible import _OpenAIToolRegistry

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "alpha.py").write_text(
        "one\nneedle here\nthree\n", encoding="utf-8"
    )
    (tmp_path / "src" / "beta.py").write_text("beta\n", encoding="utf-8")
    source_root = tmp_path / "sources" / "source-a"
    domain_root = source_root / "domain"
    domain_root.mkdir(parents=True)
    (domain_root / "main.pl").write_text("print 'needle';\n", encoding="utf-8")
    run_re = tmp_path / "runs" / "re-1" / "re"
    (run_re / "sources" / "source-a" / "specs" / "001-re-domain").mkdir(
        parents=True
    )
    (run_re / "sources" / "source-a" / "domain-manifest.json").write_text(
        json.dumps({
            "source_id": "source-a",
            "domains": [{
                "domain_id": "001-re-domain",
                "root": "domain",
                "source_file_count": 1,
            }],
        }),
        encoding="utf-8",
    )
    (run_re / "sources" / "source-a" / "analysis.json").write_text(
        json.dumps({"summary": "analysis"}),
        encoding="utf-8",
    )
    (run_re / "sources" / "source-a" / "codegraph-summary.json").write_text(
        json.dumps({"symbols": ["main"]}),
        encoding="utf-8",
    )
    (run_re / "sources" / "source-a" / "perlgraph-summary.json").write_text(
        json.dumps({"packages": ["Source::A"]}),
        encoding="utf-8",
    )
    (run_re / "re-source-index.json").write_text(
        json.dumps({
            "sources": [{
                "id": "source-a",
                "absolute_path": str(source_root),
                "path": "sources/source-a",
            }]
        }),
        encoding="utf-8",
    )
    (run_re / "re-execution-plan.json").write_text(
        json.dumps({"profile": "balanced"}),
        encoding="utf-8",
    )
    (run_re / "workspace").mkdir()
    (run_re / "workspace" / "domain-catalog.md").write_text(
        "| source-a | 001-re-domain | domain |\n",
        encoding="utf-8",
    )
    (run_re / "sources" / "source-a" / "specs" / "001-re-domain" / "spec.md").write_text(
        "# Existing spec\n",
        encoding="utf-8",
    )

    registry = _OpenAIToolRegistry(tmp_path, {})

    many = _registry_tool_payload(
        registry,
        "read_many_files",
        {"paths": ["src/alpha.py", "src/beta.py"], "limit_per_file": 10},
    )
    assert many["status"] == "ok"
    assert [item["path"] for item in many["files"]] == ["src/alpha.py", "src/beta.py"]
    assert "needle here" in many["files"][0]["content"]

    tree = _registry_tool_payload(
        registry,
        "list_tree_with_sizes",
        {"path": "src", "max_entries": 10},
    )
    assert tree["status"] == "ok"
    assert {"path": "src/alpha.py", "type": "file", "size": 22} in tree["entries"]

    grep = _registry_tool_payload(
        registry,
        "grep_context",
        {"pattern": "needle", "path": "src", "before": 1, "after": 1},
    )
    assert grep["status"] == "ok"
    assert grep["matches"][0]["path"] == "src/alpha.py"
    assert "one" in grep["matches"][0]["context"]
    assert "three" in grep["matches"][0]["context"]

    analysis_pack = _registry_tool_payload(
        registry,
        "read_re_analysis_pack",
        {"run_dir": "runs/re-1/re"},
    )
    assert analysis_pack["status"] == "ok"
    assert "re-execution-plan.json" in analysis_pack["files"]
    assert "workspace/domain-catalog.md" in analysis_pack["files"]

    domain_pack = _registry_tool_payload(
        registry,
        "read_domain_pack",
        {
            "run_dir": "runs/re-1/re",
            "source_id": "source-a",
            "domain_id": "001-re-domain",
        },
    )
    assert domain_pack["status"] == "ok"
    assert domain_pack["owned_root"] == "domain"
    assert domain_pack["source_files"][0]["path"] == "sources/source-a/domain/main.pl"
    assert "# Existing spec" in domain_pack["target_spec"]["content"]

    codegraph = _registry_tool_payload(
        registry,
        "codegraph_context",
        {"run_dir": "runs/re-1/re", "source_id": "source-a"},
    )
    assert codegraph["status"] == "ok"
    assert "codegraph-summary.json" in codegraph["files"]

    perlgraph = _registry_tool_payload(
        registry,
        "perlgraph_context",
        {"run_dir": "runs/re-1/re", "source_id": "source-a"},
    )
    assert perlgraph["status"] == "ok"
    assert "perlgraph-summary.json" in perlgraph["files"]


def test_openai_compatible_registry_enforces_dispatch_read_scope(tmp_path) -> None:
    from harness.ai_cli_backends.openai_compatible import _OpenAIToolRegistry

    run_root = tmp_path / "runs" / "re-1" / "re"
    domain_root = tmp_path / "sources" / "source-a" / "src" / "domain"
    sibling_root = tmp_path / "sources" / "source-a" / "src" / "sibling"
    run_root.mkdir(parents=True)
    domain_root.mkdir(parents=True)
    sibling_root.mkdir(parents=True)
    (run_root / "analysis.json").write_text("{}\n", encoding="utf-8")
    (domain_root / "owned.py").write_text("owned = True\n", encoding="utf-8")
    (sibling_root / "outside.py").write_text("outside = True\n", encoding="utf-8")

    registry = _OpenAIToolRegistry(
        tmp_path,
        {},
        {
            "tool_read_roots": [str(run_root), str(domain_root)],
            "tool_write_paths": [str(run_root / "target.md")],
        },
    )

    assert _registry_tool_payload(
        registry, "read_file", {"path": str(run_root / "analysis.json")}
    )["status"] == "ok"
    assert _registry_tool_payload(
        registry, "read_file", {"path": str(domain_root / "owned.py")}
    )["status"] == "ok"
    outside = _registry_tool_payload(
        registry, "read_file", {"path": str(sibling_root / "outside.py")}
    )
    assert outside["status"] == "error"
    assert "outside dispatch read scope" in outside["error"]

    listed = _registry_tool_payload(
        registry, "list_tree_with_sizes", {"path": str(tmp_path / "sources")}
    )
    assert listed["status"] == "error"
    assert "outside dispatch read scope" in listed["error"]

    denied_write = _registry_tool_payload(
        registry,
        "write_file",
        {"path": str(run_root / "other.md"), "content": "no\n"},
    )
    assert denied_write["status"] == "error"
    assert "outside dispatch write scope" in denied_write["error"]
    assert _registry_tool_payload(
        registry,
        "write_file",
        {"path": str(run_root / "target.md"), "content": "ok\n"},
    )["status"] == "ok"


def test_openai_compatible_registry_corrects_echelon_result_tool_call(tmp_path) -> None:
    from harness.ai_cli_backends.openai_compatible import _OpenAIToolRegistry

    result = _registry_tool_payload(
        _OpenAIToolRegistry(tmp_path, {}),
        "echelon_result",
        {},
    )

    assert result["status"] == "retry"
    assert result["code"] == "result_contract_not_tool"
    assert "final YAML" in result["instruction"]
    assert "Do not call more tools" in result["instruction"]


def test_openai_compatible_registry_filters_noisy_default_paths(tmp_path) -> None:
    from harness.ai_cli_backends.openai_compatible import _OpenAIToolRegistry

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "src" / "__pycache__").mkdir()
    (tmp_path / "src" / "__pycache__" / "main.cpython-314.pyc").write_bytes(
        b"\x00\x01compiled needle"
    )
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text(
        "needle\n",
        encoding="utf-8",
    )
    (tmp_path / "archive.zip").write_bytes(b"PK\x03\x04needle")

    registry = _OpenAIToolRegistry(tmp_path, {})

    listed = _registry_tool_payload(
        registry,
        "list_files",
        {"pattern": "**/*", "limit": 50},
    )
    assert listed["status"] == "ok"
    assert listed["matches"] == ["src/main.py"]

    tree = _registry_tool_payload(
        registry,
        "list_tree_with_sizes",
        {"path": ".", "max_entries": 50},
    )
    tree_paths = [entry["path"] for entry in tree["entries"]]
    assert "src/main.py" in tree_paths
    assert "archive.zip" not in tree_paths
    assert "src/__pycache__/main.cpython-314.pyc" not in tree_paths
    assert "node_modules/pkg/index.js" not in tree_paths

    grep = _registry_tool_payload(
        registry,
        "grep_context",
        {"pattern": "needle", "path": ".", "max_matches": 10},
    )
    assert [match["path"] for match in grep["matches"]] == ["src/main.py"]

    many = _registry_tool_payload(
        registry,
        "read_many_files",
        {"paths": ["src/main.py", "archive.zip", "src/__pycache__/main.cpython-314.pyc"]},
    )
    assert [item["status"] for item in many["files"]] == ["ok", "skipped", "skipped"]
    assert "ignored by provider filter" in many["files"][1]["error"]

    read_zip = _registry_tool_payload(
        registry,
        "read_file",
        {"path": "archive.zip"},
    )
    assert read_zip["status"] == "error"
    assert "ignored by provider filter" in read_zip["error"]


def test_openai_compatible_registry_applies_custom_ignore_config(tmp_path) -> None:
    from harness.ai_cli_backends.openai_compatible import _OpenAIToolRegistry

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "keep.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "src" / "generated").mkdir()
    (tmp_path / "src" / "generated" / "noise.py").write_text(
        "needle\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "snapshot.lock").write_text("needle\n", encoding="utf-8")
    registry = _OpenAIToolRegistry(
        tmp_path,
        {
            "ignore_globs": ["**/generated/**"],
            "ignore_extensions": [".lock"],
        },
    )

    listed = _registry_tool_payload(
        registry,
        "list_files",
        {"pattern": "**/*", "limit": 50},
    )
    assert listed["matches"] == ["src/keep.py"]

    grep = _registry_tool_payload(
        registry,
        "grep_files",
        {"pattern": "needle", "file_pattern": "**/*", "max_matches": 10},
    )
    assert [match["path"] for match in grep["matches"]] == ["src/keep.py"]


def test_openai_compatible_tool_call_summary_includes_bulk_args() -> None:
    from harness.ai_cli_backends.openai_compatible import _tool_call_summary

    summary = _tool_call_summary({
        "type": "function",
        "function": {
            "name": "read_many_files",
            "arguments": json.dumps({
                "paths": [
                    "runs/re-1/re/re-execution-plan.json",
                    "runs/re-1/re/re-source-index.json",
                    "runs/re-1/re/workspace/domain-catalog.md",
                    "runs/re-1/re/workspace/architecture-map.json",
                ],
                "limit_per_file": 200,
            }),
        },
    })

    assert "paths=4" in summary
    assert "re-execution-plan.json" in summary
    assert "+1 more" in summary
    assert "limit_per_file=200" in summary


def test_openai_compatible_tool_result_summary_previews_bulk_results() -> None:
    from harness.ai_cli_backends.openai_compatible import _tool_result_status

    status = _tool_result_status({
        "role": "tool",
        "tool_call_id": "call_read_many_files",
        "content": json.dumps({
            "status": "ok",
            "files": [
                {"path": "runs/re-1/re/re-execution-plan.json"},
                {"path": "runs/re-1/re/re-source-index.json"},
                {"path": "runs/re-1/re/workspace/domain-catalog.md"},
                {"path": "runs/re-1/re/workspace/architecture-map.json"},
            ],
            "truncated": False,
        }),
    })

    assert "files=4" in status
    assert "re-execution-plan.json" in status
    assert "+1 more" in status
    assert "truncated=false" in status


def test_openai_compatible_backend_sends_web_tools_when_enabled(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            }).encode()

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode())
        return FakeResponse()

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = OpenAICompatibleBackend(
        _openai_config(
            features={"streaming": False, "tool_calls": True, "web_tools": True}
        )
    ).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Research something.",
            env={},
            timeout_s=12.5,
        )
    )

    tool_names = [
        tool["function"]["name"]
        for tool in captured["payload"]["tools"]
    ]
    assert result.exit_code == 0
    assert "web_search" in tool_names
    assert "fetch_url" in tool_names


def test_openai_compatible_backend_executes_nonstreaming_write_file_tool_call(
    tmp_path, monkeypatch, capsys
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    captured_payloads = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self._payload).encode()

    responses = iter([
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_write",
                                "type": "function",
                                "function": {
                                    "name": "write_file",
                                    "arguments": json.dumps({
                                        "path": "spec.md",
                                        "content": "# Spec\n\nDone.\n",
                                    }),
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"total_tokens": 10},
        },
        {
            "choices": [
                {
                    "message": {
                        "content": "echelon_result:\n  verdict: DONE\n",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"total_tokens": 7},
        },
    ])

    def fake_urlopen(request, timeout):
        captured_payloads.append(json.loads(request.data.decode()))
        return FakeResponse(next(responses))

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = OpenAICompatibleBackend(
        _openai_config(features={"streaming": False, "tool_calls": True})
    ).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Create spec.md.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert result.stdout == "echelon_result:\n  verdict: DONE\n"
    assert (tmp_path / "spec.md").read_text(encoding="utf-8") == "# Spec\n\nDone.\n"
    assert captured_payloads[1]["messages"][-1]["role"] == "tool"
    assert captured_payloads[1]["messages"][-1]["tool_call_id"] == "call_write"
    assert result.metadata["tool_call_count"] == 1
    assert result.token_usage == 17
    captured = capsys.readouterr()
    assert "[openai-compatible] turn 1: request" in captured.err
    assert "tool_rounds=0/24" in captured.err
    assert "messages=2" in captured.err
    assert "[openai-compatible] tool budget: rounds=1/24 calls_total=0" in captured.err
    assert "[openai-compatible] tool write_file: spec.md" in captured.err
    assert "[openai-compatible] tool write_file result: ok bytes=14 path=spec.md" in captured.err
    assert "[openai-compatible] turn 1 summary:" in captured.err
    assert "model_text=0 chars" in captured.err
    assert "tool_time=" in captured.err
    assert "tool_budget=1/24" in captured.err
    assert "[openai-compatible] turn 2: request" in captured.err
    assert "messages=4" in captured.err
    assert "  llm | echelon_result:" in captured.err
    assert "  llm |   verdict: DONE" in captured.err
    assert "[openai-compatible] turn 2 summary:" in captured.err
    assert "tool_budget=1/24" in captured.err
    assert "[openai-compatible] final: finish_reason=stop" in captured.err
    assert "elapsed=" in captured.err
    assert "[openai-compatible]" not in result.stdout


def test_openai_compatible_backend_writes_compact_transcript_for_run_dir(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    run_dir = tmp_path / "runs" / "re-1" / "re"
    run_dir.mkdir(parents=True)
    (run_dir / "re-execution-plan.json").write_text("{}", encoding="utf-8")
    captured_payloads = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self._payload).encode()

    responses = iter([
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_read",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": json.dumps({
                                        "path": "re-execution-plan.json",
                                    }),
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"total_tokens": 5},
        },
        {
            "choices": [
                {
                    "message": {"content": "echelon_result:\n  verdict: DONE\n"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"total_tokens": 6},
        },
    ])

    def fake_urlopen(request, timeout):
        captured_payloads.append(json.loads(request.data.decode()))
        return FakeResponse(next(responses))

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = OpenAICompatibleBackend(
        _openai_config(features={"streaming": False, "tool_calls": True})
    ).run_prompt(
        CliRunRequest(
            cwd=str(run_dir),
            prompt="Read the plan and finish.",
            env={},
            timeout_s=12.5,
        )
    )

    transcript_path = Path(str(result.metadata["provider_transcript_path"]))
    assert result.exit_code == 0
    assert transcript_path.is_file()
    assert transcript_path.parent == run_dir / "provider-transcripts"
    events = [
        json.loads(line)
        for line in transcript_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [event["event"] for event in events] == [
        "turn_response",
        "tool_call",
        "tool_result",
        "turn_summary",
        "turn_response",
        "turn_summary",
        "final",
    ]
    assert events[1]["tool_name"] == "read_file"
    assert events[2]["tool_result"].startswith("ok ")
    assert events[-1]["finish_reason"] == "stop"
    assert "messages" not in events[0]
    assert captured_payloads[0]["messages"][0]["role"] == "system"


def test_openai_compatible_backend_compacts_old_large_tool_results(
    tmp_path, monkeypatch, capsys
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    for index in range(4):
        (tmp_path / f"big-{index}.txt").write_text(
            f"header {index}\n" + ("x" * 600) + "\n",
            encoding="utf-8",
        )
    captured_payloads = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self._payload).encode()

    tool_responses = []
    for index in range(4):
        tool_responses.append({
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": f"call_read_{index}",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": json.dumps({
                                        "path": f"big-{index}.txt",
                                    }),
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"total_tokens": 3},
        })
    responses = iter([
        *tool_responses,
        {
            "choices": [
                {
                    "message": {"content": "echelon_result:\n  verdict: DONE\n"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"total_tokens": 4},
        },
    ])

    def fake_urlopen(request, timeout):
        captured_payloads.append(json.loads(request.data.decode()))
        return FakeResponse(next(responses))

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = OpenAICompatibleBackend(
        _openai_config(features={
            "streaming": False,
            "tool_calls": True,
            "tool_result_compaction": True,
            "compact_after_tool_results": 3,
            "keep_recent_tool_results": 1,
            "compact_tool_result_after_chars": 200,
            "compacted_result_chars": 80,
        })
    ).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Read the large files and finish.",
            env={},
            timeout_s=12.5,
        )
    )

    final_messages = captured_payloads[-1]["messages"]
    tool_messages = [
        message
        for message in final_messages
        if message.get("role") == "tool"
    ]
    compacted = json.loads(tool_messages[0]["content"])
    newest = json.loads(tool_messages[-1]["content"])
    assert result.exit_code == 0
    assert compacted["status"] == "compacted"
    assert compacted["tool_name"] == "read_file"
    assert compacted["original_status"] == "ok"
    assert compacted["original_chars"] > 200
    assert "big-0.txt" in compacted["summary"]
    assert "content" not in compacted
    assert newest["status"] == "ok"
    assert "x" * 120 in newest["content"]
    captured = capsys.readouterr()
    assert "[openai-compatible] compaction:" in captured.err
    assert "compacted=3" in captured.err
    assert result.metadata["tool_result_compactions"] >= 3


def test_openai_compatible_tool_round_limit_reports_last_context(
    tmp_path, monkeypatch, capsys
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "choices": [
                    {
                        "message": {
                            "content": "Need one more file before finalizing.",
                            "tool_calls": [
                                {
                                    "id": "call_read",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": json.dumps({"path": "missing.md"}),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"total_tokens": 11},
            }).encode()

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(),
    )

    result = OpenAICompatibleBackend(
        _openai_config(
            features={
                "streaming": False,
                "tool_calls": True,
                "max_tool_rounds": 0,
            }
        )
    ).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Read and finish.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 1
    assert result.metadata["provider_error_code"] == "tool_round_limit"
    assert result.metadata["last_tool_name"] == "read_file"
    assert result.metadata["last_tool_summary"] == "missing.md"
    assert result.metadata["last_model_preview"] == "Need one more file before finalizing."
    assert "last_tool=read_file missing.md" in result.stderr
    assert "last_model_preview=Need one more file before finalizing." in result.stderr
    captured = capsys.readouterr()
    assert "[openai-compatible] final: failed reason=tool_round_limit" in captured.err
    assert "last_tool=read_file missing.md" in captured.err
    assert "last_model_preview=Need one more file before finalizing." in captured.err


def test_openai_compatible_repeated_tool_calls_force_a_no_tools_final_turn(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    captured_payloads = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self._payload).encode()

    repeated = [
        {
            "choices": [{
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "id": f"call_list_{index}",
                        "type": "function",
                        "function": {
                            "name": "list_files",
                            "arguments": json.dumps({"pattern": "**/tests/**/*.py"}),
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"total_tokens": 3},
        }
        for index in range(2)
    ]
    responses = iter([
        *repeated,
        {
            "choices": [{
                "message": {"content": "echelon_result:\n  verdict: DONE\n"},
                "finish_reason": "stop",
            }],
            "usage": {"total_tokens": 4},
        },
    ])

    def fake_urlopen(request, timeout):
        captured_payloads.append(json.loads(request.data.decode()))
        return FakeResponse(next(responses))

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = OpenAICompatibleBackend(
        _openai_config(features={
            "streaming": False,
            "tool_calls": True,
            "max_identical_tool_rounds": 2,
        })
    ).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Inspect owned tests and finish.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert result.metadata["tool_no_progress_forced"] is True
    assert "tools" in captured_payloads[1]
    assert "tools" not in captured_payloads[2]
    assert captured_payloads[2]["messages"][-1]["role"] == "system"
    assert "Do not call more tools" in captured_payloads[2]["messages"][-1]["content"]


def test_openai_compatible_backend_executes_fetch_url_tool_call(
    tmp_path, monkeypatch, capsys
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    captured_payloads = []

    class FakeModelResponse:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self._payload).encode()

    class FakeWebResponse:
        status = 200
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"<html><title>Example</title><body>Hello web evidence.</body></html>"

    responses = iter([
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_fetch",
                                "type": "function",
                                "function": {
                                    "name": "fetch_url",
                                    "arguments": json.dumps({
                                        "url": "https://example.com/page",
                                        "max_chars": 20,
                                    }),
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {"content": "echelon_result:\n  verdict: DONE\n"},
                    "finish_reason": "stop",
                }
            ]
        },
    ])

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/chat/completions"):
            captured_payloads.append(json.loads(request.data.decode()))
            return FakeModelResponse(next(responses))
        assert request.full_url == "https://example.com/page"
        return FakeWebResponse()

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = OpenAICompatibleBackend(
        _openai_config(
            features={"streaming": False, "tool_calls": True, "web_tools": True}
        )
    ).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Fetch evidence.",
            env={},
            timeout_s=12.5,
        )
    )

    tool_payload = json.loads(captured_payloads[1]["messages"][-1]["content"])
    assert result.exit_code == 0
    assert tool_payload["status"] == "ok"
    assert tool_payload["url"] == "https://example.com/page"
    assert tool_payload["http_status"] == 200
    assert "Hello web ev" in tool_payload["content"]
    assert tool_payload["truncated"] is True
    captured = capsys.readouterr()
    assert "[openai-compatible] tool fetch_url: https://example.com/page" in captured.err
    assert "[openai-compatible] tool fetch_url result: ok http_status=200 chars=20 truncated=true" in captured.err


def test_openai_compatible_backend_executes_web_search_tool_call(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    captured_payloads = []

    class FakeModelResponse:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self._payload).encode()

    class FakeSearchResponse:
        status = 200
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return (
                b'<a class="result__a" href="https://example.com/a">Alpha</a>'
                b'<a class="result__a" href="https://example.com/b">Beta</a>'
            )

    responses = iter([
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_search",
                                "type": "function",
                                "function": {
                                    "name": "web_search",
                                    "arguments": json.dumps({
                                        "query": "alpha beta",
                                        "max_results": 2,
                                    }),
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {"content": "echelon_result:\n  verdict: DONE\n"},
                    "finish_reason": "stop",
                }
            ]
        },
    ])

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/chat/completions"):
            captured_payloads.append(json.loads(request.data.decode()))
            return FakeModelResponse(next(responses))
        assert request.full_url.startswith("https://duckduckgo.com/html/")
        return FakeSearchResponse()

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = OpenAICompatibleBackend(
        _openai_config(
            features={"streaming": False, "tool_calls": True, "web_tools": True}
        )
    ).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Search evidence.",
            env={},
            timeout_s=12.5,
        )
    )

    tool_payload = json.loads(captured_payloads[1]["messages"][-1]["content"])
    assert result.exit_code == 0
    assert tool_payload["status"] == "ok"
    assert tool_payload["query"] == "alpha beta"
    assert tool_payload["results"] == [
        {"title": "Alpha", "url": "https://example.com/a"},
        {"title": "Beta", "url": "https://example.com/b"},
    ]


def test_openai_compatible_backend_executes_streamed_tool_call_chunks(
    tmp_path, monkeypatch, capsys
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    captured_payloads = []

    class StreamingToolResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self) -> None:
            self._lines = iter([
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_write","type":"function","function":{"name":"write_file","arguments":"{\\"path\\": "}}]}}]}\n',
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"notes.md\\", \\"content\\": \\"hello"}}]}}]}\n',
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":" world\\\\n\\"}"}}]},"finish_reason":"tool_calls"}],"usage":{"total_tokens":11}}\n',
                b"data: [DONE]\n",
            ])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            return next(self._lines, b"")

    class FinalResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self) -> None:
            self._lines = iter([
                b'data: {"choices":[{"delta":{"content":"echelon_"}}]}\n',
                b'data: {"choices":[{"delta":{"content":"result:\\n  verdict"}}]}\n',
                b'data: {"choices":[{"delta":{"content":": DONE\\n"},"finish_reason":"stop"}],"usage":{"total_tokens":5}}\n',
                b"data: [DONE]\n",
            ])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            return next(self._lines, b"")

    responses = iter([StreamingToolResponse(), FinalResponse()])

    def fake_urlopen(request, timeout):
        captured_payloads.append(json.loads(request.data.decode()))
        return next(responses)

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = OpenAICompatibleBackend(
        _openai_config(features={"streaming": True, "tool_calls": True})
    ).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Create notes.md.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert result.stdout == "echelon_result:\n  verdict: DONE\n"
    assert (tmp_path / "notes.md").read_text(encoding="utf-8") == "hello world\n"
    assert captured_payloads[1]["messages"][-1]["role"] == "tool"
    assert result.metadata["streamed"] is True
    assert result.metadata["tool_call_count"] == 1
    assert result.token_usage == 16
    captured = capsys.readouterr()
    assert "[openai-compatible] stream: tool_call_delta" not in captured.err
    assert "[openai-compatible] stream: content_delta chars=" not in captured.err
    assert "  llm | echelon_result:" in captured.err
    assert "  llm |   verdict: DONE" in captured.err
    assert "  llm | echelon_" not in captured.err.splitlines()
    assert "[openai-compatible] tool write_file result: ok bytes=12 path=notes.md" in captured.err


def test_openai_compatible_backend_debug_progress_keeps_stream_delta_counters(
    tmp_path, monkeypatch, capsys
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    class StreamingResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self) -> None:
            self._lines = iter([
                b'data: {"choices":[{"delta":{"content":"echelon_"}}]}\n',
                b'data: {"choices":[{"delta":{"content":"result:\\n"}}],"usage":{"total_tokens":5}}\n',
                b"data: [DONE]\n",
            ])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            return next(self._lines, b"")

    def fake_urlopen(request, timeout):
        return StreamingResponse()

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = OpenAICompatibleBackend(
        _openai_config(
            features={
                "streaming": True,
                "tool_calls": False,
                "progress_detail": "debug",
            }
        )
    ).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == 0
    assert result.stdout == "echelon_result:\n"
    captured = capsys.readouterr()
    assert "[openai-compatible] stream: content_delta chars=8 total_chars=8" in captured.err
    assert "[openai-compatible] stream: content_delta chars=8 total_chars=16" in captured.err
    assert "  llm | echelon_result:" in captured.err


def test_openai_stream_preview_is_bounded_and_marks_truncation_once(capsys) -> None:
    from harness.ai_cli_backends.openai_compatible_progress import OpenAIStreamPreview

    preview = OpenAIStreamPreview(max_chars=11, max_lines=4)
    preview.append("hello\n\nworld\nagain\nmore\n")
    preview.flush()

    lines = capsys.readouterr().err.splitlines()
    assert lines == [
        "  llm | hello",
        "  llm | world",
        "  llm | ... preview truncated ...",
    ]
    assert preview.emitted is True
    assert preview.truncated is True


def test_openai_stream_preview_respects_line_ceiling(capsys) -> None:
    from harness.ai_cli_backends.openai_compatible_progress import OpenAIStreamPreview

    preview = OpenAIStreamPreview(max_chars=100, max_lines=2)
    preview.append("one\ntwo\nthree\nfour\n")
    preview.flush()

    lines = capsys.readouterr().err.splitlines()
    assert lines == [
        "  llm | one",
        "  llm | two",
        "  llm | ... preview truncated ...",
    ]


def test_openai_stream_preview_preserves_stdout_without_terminal_replay(
    tmp_path, monkeypatch, capsys
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    class StreamingResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self) -> None:
            self._lines = iter([
                b'data: {"choices":[{"delta":{"content":"echelon_result:\\n  verdict: DONE\\n"},"finish_reason":"stop"}],"usage":{"total_tokens":5}}\n',
                b"data: [DONE]\n",
            ])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            return next(self._lines, b"")

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: StreamingResponse(),
    )
    result = OpenAICompatibleBackend(
        _openai_config(features={"streaming": True, "tool_calls": False})
    ).run_prompt(
        CliRunRequest(cwd=str(tmp_path), prompt="Return result.", env={}, timeout_s=10)
    )

    captured = capsys.readouterr()
    assert result.stdout == "echelon_result:\n  verdict: DONE\n"
    assert captured.out == ""
    assert captured.err.count("echelon_result:") == 1


def test_openai_stream_preview_can_be_disabled_without_losing_terminal_output(
    tmp_path, monkeypatch, capsys
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    class StreamingResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self) -> None:
            self._lines = iter([
                b'data: {"choices":[{"delta":{"content":"complete response"},"finish_reason":"stop"}]}\n',
                b"data: [DONE]\n",
            ])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            return next(self._lines, b"")

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: StreamingResponse(),
    )
    result = OpenAICompatibleBackend(
        _openai_config(
            features={
                "streaming": True,
                "tool_calls": False,
                "stream_preview": False,
            }
        )
    ).run_prompt(
        CliRunRequest(cwd=str(tmp_path), prompt="Return result.", env={}, timeout_s=10)
    )

    captured = capsys.readouterr()
    assert result.stdout == "complete response"
    assert captured.out == "complete response\n"
    assert "  llm |" not in captured.err


def test_openai_compatible_backend_tool_rejects_path_escape(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    captured_payloads = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self._payload).encode()

    responses = iter([
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_escape",
                                "type": "function",
                                "function": {
                                    "name": "write_file",
                                    "arguments": json.dumps({
                                        "path": "../outside.md",
                                        "content": "nope",
                                    }),
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {"content": "echelon_result:\n  verdict: BLOCKED\n"},
                    "finish_reason": "stop",
                }
            ]
        },
    ])

    def fake_urlopen(request, timeout):
        captured_payloads.append(json.loads(request.data.decode()))
        return FakeResponse(next(responses))

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = OpenAICompatibleBackend(
        _openai_config(features={"streaming": False, "tool_calls": True})
    ).run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Try a bad write.",
            env={},
            timeout_s=12.5,
        )
    )

    tool_payload = json.loads(captured_payloads[1]["messages"][-1]["content"])
    assert result.exit_code == 0
    assert tool_payload["status"] == "error"
    assert "escapes provider root" in tool_payload["error"]
    assert not (tmp_path.parent / "outside.md").exists()


def test_openai_compatible_backend_stream_read_timeout_returns_timed_out(
    tmp_path, monkeypatch
) -> None:
    from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend

    class FakeResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            raise socket.timeout("stream stalled")

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(),
    )
    backend = OpenAICompatibleBackend(_openai_config())
    result = backend.run_prompt(
        CliRunRequest(
            cwd=str(tmp_path),
            prompt="Return a result.",
            env={},
            timeout_s=12.5,
        )
    )

    assert result.exit_code == -1
    assert result.timed_out is True
    assert "stream stalled" in result.stderr
    assert result.metadata["provider_error_code"] == "timeout"


def test_claude_backend_streams_json_and_captures_result_error(tmp_path) -> None:
    backend = ClaudeCliBackend(_config("claude"))

    class FakeProcess:
        stdout = io.BytesIO(
            (
                json.dumps(
                    {
                        "type": "result",
                        "is_error": True,
                        "result": "session limit reached",
                        "usage": {"input_tokens": 10, "output_tokens": 2},
                    }
                )
                + "\n"
            ).encode()
        )
        returncode = 1

        def kill(self) -> None:
            return None

        def wait(self) -> int:
            return self.returncode

    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Build this.",
        env={},
        timeout_s=10,
    )

    with patch(
        "harness.ai_cli_backends.claude.subprocess.Popen",
        return_value=FakeProcess(),
        create=True,
    ):
        result = backend.run_prompt(request)

    assert result.exit_code == 1
    assert "session limit reached" in result.stdout
    assert result.token_usage == 12


def test_claude_backend_uses_prompt_metadata_model(tmp_path) -> None:
    backend = ClaudeCliBackend(_config("claude"))
    captured = {}

    class FakeProcess:
        stdout = io.BytesIO(
            (
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [{"type": "text", "text": "ok"}],
                        },
                    }
                )
                + "\n"
                + json.dumps({"type": "result", "usage": {"input_tokens": 1}})
                + "\n"
            ).encode()
        )
        returncode = 0

        def kill(self) -> None:
            return None

        def wait(self) -> int:
            return self.returncode

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeProcess()

    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Build this.",
        env={},
        timeout_s=10,
        metadata={"prompt_metadata": {"model": "claude-opus-4-1"}},
    )

    with patch("harness.ai_cli_backends.claude.subprocess.Popen", fake_popen):
        result = backend.run_prompt(request)

    assert result.exit_code == 0
    assert "--model" in captured["cmd"]
    model_index = captured["cmd"].index("--model")
    assert captured["cmd"][model_index + 1] == "claude-opus-4-1"


def test_claude_backend_preserves_response_model_from_stream(tmp_path) -> None:
    backend = ClaudeCliBackend(_config("claude"))

    class FakeProcess:
        stdout = io.BytesIO(
            (
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "model": "claude-sonnet-5",
                            "content": [{"type": "text", "text": "ok"}],
                        },
                    }
                )
                + "\n"
                + json.dumps({"type": "result", "usage": {"input_tokens": 1}})
                + "\n"
            ).encode()
        )
        returncode = 0

        def kill(self) -> None:
            return None

        def wait(self) -> int:
            return self.returncode

    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Build this.",
        env={},
        timeout_s=10,
    )

    with patch(
        "harness.ai_cli_backends.claude.subprocess.Popen",
        return_value=FakeProcess(),
    ):
        result = backend.run_prompt(request)

    assert result.metadata["response_model"] == "claude-sonnet-5"


def test_plain_backend_captures_stdout_and_stderr(tmp_path) -> None:
    backend = PlainCliBackend(_config("copilot"))
    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Build this.",
        env={},
        timeout_s=10,
    )
    completed = subprocess.CompletedProcess(
        args=["copilot"],
        returncode=3,
        stdout=b"plain stdout",
        stderr=b"plain stderr",
    )

    with patch("harness.ai_cli_backends.plain.subprocess.run", return_value=completed):
        result = backend.run_prompt(request)

    assert result.exit_code == 3
    assert result.stdout == "plain stdout"
    assert result.stderr == "plain stderr"


def test_codex_backend_parses_jsonl_and_final_message_file(tmp_path) -> None:
    backend = CodexCliBackend(_config("codex"))
    final_message = tmp_path / "last-message.txt"

    class FakeProcess:
        stdout = io.BytesIO(
            (
                json.dumps({"type": "message", "role": "assistant", "content": "working"})
                + "\n"
            ).encode()
        )
        stderr = io.BytesIO(b"")
        returncode = 0

        def kill(self) -> None:
            return None

        def wait(self) -> int:
            final_message.write_text("echelon_result:\n  verdict: PASS\n  state_updates: {}\n")
            return self.returncode

    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Do work.",
        env={},
        timeout_s=10,
    )

    with patch("harness.ai_cli_backends.codex.tempfile.NamedTemporaryFile") as named, patch(
        "harness.ai_cli_backends.codex.subprocess.Popen",
        return_value=FakeProcess(),
    ):
        named.return_value.__enter__.return_value.name = str(final_message)
        result = backend.run_agent(request)

    assert result.exit_code == 0
    assert "working" in result.stdout
    assert "echelon_result:" in result.stdout


def test_codex_backend_returns_on_task_complete_even_when_process_lingers(tmp_path) -> None:
    backend = CodexCliBackend(_config("codex"))
    final_message = tmp_path / "last-message.txt"

    class FakeProcess:
        stdout = io.BytesIO(
            (
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "total_token_usage": {
                                    "input_tokens": 10,
                                    "output_tokens": 5,
                                    "total_tokens": 15,
                                }
                            },
                        },
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "task_complete",
                            "last_agent_message": (
                                "echelon_result:\n"
                                "  verdict: COMPLETE\n"
                                "  state_updates: {}\n"
                                "  journal_entries: []\n"
                            ),
                        },
                    }
                )
                + "\n"
            ).encode()
        )
        stderr = io.BytesIO(b"codex diagnostic\n")
        returncode = None
        terminated = False

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = -15

        def kill(self) -> None:
            self.terminated = True
            self.returncode = -9

        def wait(self, timeout=None) -> int:
            if self.returncode is None and timeout is not None:
                raise subprocess.TimeoutExpired(["codex"], timeout)
            if self.returncode is None:
                self.returncode = 0
            return self.returncode

    fake_process = FakeProcess()
    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Do work.",
        env={},
        timeout_s=10,
    )

    with patch("harness.ai_cli_backends.codex.tempfile.NamedTemporaryFile") as named, patch(
        "harness.ai_cli_backends.codex.subprocess.Popen",
        return_value=fake_process,
    ):
        named.return_value.__enter__.return_value.name = str(final_message)
        result = backend.run_agent(request)

    assert result.exit_code == 0
    assert result.metadata["task_complete"] is True
    assert fake_process.terminated is True
    assert "echelon_result:" in result.stdout
    assert "codex diagnostic" in result.stderr
    assert result.token_usage == 15


def test_codex_backend_suppresses_successful_command_event_noise(tmp_path, capsys) -> None:
    backend = CodexCliBackend(_config("codex"))
    final_message = tmp_path / "last-message.txt"

    class FakeProcess:
        stdout = io.BytesIO(
            (
                json.dumps(
                    {
                        "type": "item.started",
                        "item": {
                            "id": "item_1",
                            "type": "command_execution",
                            "command": "/bin/zsh -lc 'sed -n 1,240p huge-file.md'",
                            "aggregated_output": "",
                            "status": "in_progress",
                        },
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "item_1",
                            "type": "command_execution",
                            "command": "/bin/zsh -lc 'sed -n 1,240p huge-file.md'",
                            "aggregated_output": "very noisy command output\n" * 100,
                            "exit_code": 0,
                            "status": "completed",
                        },
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "task_complete",
                            "last_agent_message": (
                                "echelon_result:\n"
                                "  verdict: COMPLETE\n"
                                "  state_updates: {}\n"
                                "  journal_entries: []\n"
                            ),
                        },
                    }
                )
                + "\n"
            ).encode()
        )
        stderr = io.BytesIO(b"")
        returncode = 0

        def kill(self) -> None:
            return None

        def wait(self, timeout=None) -> int:
            return self.returncode

    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Do work.",
        env={},
        timeout_s=10,
    )

    with patch("harness.ai_cli_backends.codex.tempfile.NamedTemporaryFile") as named, patch(
        "harness.ai_cli_backends.codex.subprocess.Popen",
        return_value=FakeProcess(),
    ):
        named.return_value.__enter__.return_value.name = str(final_message)
        result = backend.run_agent(request)

    captured = capsys.readouterr()
    assert "echelon_result:" in result.stdout
    assert "very noisy command output" not in result.stdout
    assert "aggregated_output" not in result.stdout
    assert '"type": "item.completed"' not in result.stdout
    assert "very noisy command output" not in captured.out
    assert "aggregated_output" not in captured.out
    assert '"type": "item.completed"' not in captured.out


def test_codex_backend_falls_back_to_plain_stdout(tmp_path) -> None:
    backend = CodexCliBackend(_config("codex"))

    class FakeProcess:
        stdout = io.BytesIO(b"plain codex output\n")
        stderr = io.BytesIO(b"")
        returncode = 0

        def kill(self) -> None:
            return None

        def wait(self) -> int:
            return self.returncode

    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Do work.",
        env={},
        timeout_s=10,
    )

    with patch("harness.ai_cli_backends.codex.subprocess.Popen", return_value=FakeProcess()):
        result = backend.run_prompt(request)

    assert result.exit_code == 0
    assert "plain codex output" in result.stdout


def test_opencode_backend_parses_json_events(tmp_path) -> None:
    backend = OpenCodeCliBackend(_config("opencode"))

    class FakeProcess:
        stdout = io.BytesIO(
            (
                json.dumps({"type": "message", "role": "assistant", "content": "working"})
                + "\n"
                + json.dumps({"type": "result", "output": "echelon_result:\\n  verdict: PASS\\n"})
                + "\n"
            ).encode()
        )
        stderr = io.BytesIO(b"")
        returncode = 0

        def kill(self) -> None:
            return None

        def wait(self) -> int:
            return self.returncode

    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Do work.",
        env={},
        timeout_s=10,
    )

    with patch("harness.ai_cli_backends.opencode.subprocess.Popen", return_value=FakeProcess()) as popen:
        result = backend.run_agent(request)

    assert result.exit_code == 0
    assert "working" in result.stdout
    assert "echelon_result:" in result.stdout
    cmd = popen.call_args.args[0]
    assert Path(cmd[0]).name == "opencode"
    assert cmd[1:4] == ["run", "--format", "json"]
    assert cmd[-1].startswith("## Effective Host Tool Policy")


def test_opencode_backend_parses_recorded_fixture_text(tmp_path) -> None:
    backend = OpenCodeCliBackend(_config("opencode"))
    fixture = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "ai_cli"
        / "opencode-run-json.jsonl"
    )

    class FakeProcess:
        stdout = io.BytesIO(fixture.read_bytes())
        stderr = io.BytesIO(b"")
        returncode = 0

        def kill(self) -> None:
            return None

        def wait(self) -> int:
            return self.returncode

    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Do work.",
        env={},
        timeout_s=10,
    )

    with patch("harness.ai_cli_backends.opencode.subprocess.Popen", return_value=FakeProcess()) as popen:
        result = backend.run_agent(request)

    assert result.exit_code == 0
    assert result.stdout == "Hello."
    cmd = popen.call_args.args[0]
    assert Path(cmd[0]).name == "opencode"
    assert cmd[1:4] == ["run", "--format", "json"]
    assert cmd[-1].startswith("## Effective Host Tool Policy")


def test_opencode_backend_enforces_timeout(tmp_path) -> None:
    backend = OpenCodeCliBackend(_config("opencode"))
    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Do work.",
        env={},
        timeout_s=0.05,
    )

    started = time.monotonic()
    result = backend._run(
        [sys.executable, "-c", "import time; time.sleep(0.3)"],
        request,
    )
    elapsed = time.monotonic() - started

    assert result.timed_out is True
    assert result.exit_code == -1
    assert elapsed < 0.25


@pytest.mark.parametrize(
    ("backend_cls", "cli"),
    [
        (OpenCodeCliBackend, "opencode"),
        (CopilotCliBackend, "copilot"),
    ],
)
def test_json_backends_drain_large_stderr_without_deadlock(
    tmp_path,
    capsys,
    backend_cls: type[OpenCodeCliBackend] | type[CopilotCliBackend],
    cli: str,
) -> None:
    backend = backend_cls(_config(cli))
    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Do work.",
        env={},
        timeout_s=2,
    )
    code = (
        "import sys\n"
        "sys.stderr.write('diagnostic-' + 'x' * 200000 + '\\n')\n"
        "sys.stderr.flush()\n"
        "sys.stdout.write('done\\n')\n"
        "sys.stdout.flush()\n"
    )

    result = backend._run([sys.executable, "-c", code], request)
    captured = capsys.readouterr()

    assert result.timed_out is False
    assert result.exit_code == 0
    assert result.stdout == "done"
    assert result.stderr.startswith("diagnostic-")
    assert "diagnostic-" not in captured.out
    assert "diagnostic-" in captured.err


def test_copilot_backend_parses_jsonl_response(tmp_path) -> None:
    backend = CopilotCliBackend(_config("copilot"))

    class FakeProcess:
        stdout = io.BytesIO(
            (
                json.dumps({"type": "assistant_message", "content": "working"})
                + "\n"
                + json.dumps({"type": "final", "message": "echelon_result:\\n  verdict: PASS\\n"})
                + "\n"
            ).encode()
        )
        stderr = io.BytesIO(b"")
        returncode = 0

        def kill(self) -> None:
            return None

        def wait(self) -> int:
            return self.returncode

    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Do work.",
        env={},
        timeout_s=10,
    )

    with patch("harness.ai_cli_backends.copilot.subprocess.Popen", return_value=FakeProcess()) as popen:
        result = backend.run_agent(request)

    assert result.exit_code == 0
    assert "working" in result.stdout
    assert "echelon_result:" in result.stdout
    cmd = popen.call_args.args[0]
    assert Path(cmd[0]).name == "copilot"
    assert cmd[1] == "-p"
    assert cmd[2].startswith("## Effective Host Tool Policy")
    assert cmd[-4:] == ["--output-format", "json", "--stream", "off"]


def test_copilot_backend_parses_recorded_fixture_text(tmp_path) -> None:
    backend = CopilotCliBackend(_config("copilot"))
    fixture = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "ai_cli"
        / "copilot-prompt-json.jsonl"
    )

    class FakeProcess:
        stdout = io.BytesIO(fixture.read_bytes())
        stderr = io.BytesIO(b"")
        returncode = 0

        def kill(self) -> None:
            return None

        def wait(self) -> int:
            return self.returncode

    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Do work.",
        env={},
        timeout_s=10,
    )

    with patch("harness.ai_cli_backends.copilot.subprocess.Popen", return_value=FakeProcess()) as popen:
        result = backend.run_agent(request)

    assert result.exit_code == 0
    assert result.stdout == "Hello! How can I help you today?"
    cmd = popen.call_args.args[0]
    assert Path(cmd[0]).name == "copilot"
    assert cmd[1] == "-p"
    assert cmd[2].startswith("## Effective Host Tool Policy")
    assert cmd[-4:] == ["--output-format", "json", "--stream", "off"]


def test_copilot_backend_enforces_timeout(tmp_path) -> None:
    backend = CopilotCliBackend(_config("copilot"))
    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Do work.",
        env={},
        timeout_s=0.05,
    )

    started = time.monotonic()
    result = backend._run(
        [sys.executable, "-c", "import time; time.sleep(0.3)"],
        request,
    )
    elapsed = time.monotonic() - started

    assert result.timed_out is True
    assert result.exit_code == -1
    assert elapsed < 0.25
