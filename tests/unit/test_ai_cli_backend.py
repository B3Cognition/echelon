from __future__ import annotations

import io
import json
import socket
import subprocess
import sys
import time
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
        headers = {"Content-Type": "text/event-stream"}

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
    assert captured["payload"]["stream"] is True
    assert captured["payload"]["stream_options"] == {"include_usage": True}
    assert captured["timeout"] == 12.5
    assert result.metadata["streamed"] is True
    assert result.metadata["finish_reason"] == "stop"
    assert result.metadata["reasoning_content_observed"] is True


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
