from __future__ import annotations

import io
import json
import subprocess
from unittest.mock import patch

import pytest

from harness.ai_cli_backend import CliRunRequest, CliRunResult, create_ai_cli_backend
from harness.ai_cli_backends.claude import ClaudeCliBackend
from harness.ai_cli_backends.codex import CodexCliBackend
from harness.ai_cli_backends.plain import PlainCliBackend
from harness.config import HarnessConfig, LlmConfig


def _config(cli: str) -> HarnessConfig:
    return HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli=cli),
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
        ("copilot", "PlainCliBackend"),
        ("opencode", "PlainCliBackend"),
    ],
)
def test_backend_factory_returns_concrete_backend(cli: str, class_name: str) -> None:
    backend = create_ai_cli_backend(_config(cli))

    assert backend.__class__.__name__ == class_name
    assert backend.name == cli


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
