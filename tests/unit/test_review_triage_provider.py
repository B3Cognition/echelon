"""Provider boundary tests for isolated, no-tools PR-triage turns."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from harness.ai_cli_backend import CliRunRequest, CliRunResult, ReviewTriageBackend
from harness.ai_cli_backends.claude import ClaudeCliBackend
from harness.ai_cli_backends.claude_triage import prepare_claude_triage_request
from harness.ai_cli_backends.codex import CodexCliBackend
from harness.config import HarnessConfig, LlmConfig
from harness.llm_provider import AICodingCliProvider
from harness.llm_tool_policy import LlmToolPolicy


_INPUT_CAP = 1024 * 1024
_CAPTURE_CAP = 256 * 1024
_REAL_POPEN = subprocess.Popen


def _config(cli: str, *, unsafe: bool = False) -> HarnessConfig:
    return HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(
            cli=cli,
            timeout_ms=5_000,
            tool_policy=LlmToolPolicy(
                allow_unsafe_host_execution=unsafe,
                approval_reason="test fixture" if unsafe else None,
            ),
        ),
    )


def _request(
    cwd: Path,
    *,
    prompt: str = "triage input",
    tier: object = "strong",
    effort: object = "medium",
    timeout_s: object = 2.0,
    metadata: dict[str, object] | None = None,
) -> CliRunRequest:
    return CliRunRequest(
        cwd=str(cwd),
        prompt=prompt,
        env={},
        timeout_s=timeout_s,
        metadata=(
            metadata
            if metadata is not None
            else {"prompt_metadata": {"model_tier": tier, "effort": effort}}
        ),
    )


def _codex_wire(
    answer: str = "triaged",
    *,
    item_type: str = "agent_message",
    usage: dict[str, int] | None = None,
) -> bytes:
    events = [
        {
            "type": "item.completed",
            "item": {"type": item_type, "text": answer},
        },
        {
            "type": "turn.completed",
            "usage": usage or {"input_tokens": 7, "output_tokens": 4},
        },
    ]
    return b"".join(
        json.dumps(event, separators=(",", ":")).encode() + b"\n"
        for event in events
    )


def _claude_wire(
    answer: object = "triaged",
    *,
    is_error: bool = False,
    usage: dict[str, int] | None = None,
) -> bytes:
    event = {
        "type": "result",
        "subtype": "error" if is_error else "success",
        "is_error": is_error,
        "result": answer,
        "total_cost_usd": 0.125,
        "usage": (
            {"input_tokens": 8, "output_tokens": 5}
            if usage is None
            else usage
        ),
    }
    return json.dumps(event, separators=(",", ":")).encode() + b"\n"


def _run_scripted_backend(backend, request, monkeypatch, wire: bytes, *, script=None):
    captured: dict[str, object] = {}
    fixture = script or (
        f"import sys; data=sys.stdin.buffer.read(); "
        f"sys.stdout.buffer.write({wire!r})"
    )

    def launch(command, **kwargs):
        captured["command"] = list(command)
        captured["env"] = kwargs.get("env")
        process = _REAL_POPEN([sys.executable, "-c", fixture], **kwargs)
        captured["process"] = process
        return process

    module = (
        "harness.ai_cli_backends.codex.subprocess.Popen"
        if isinstance(backend, CodexCliBackend)
        else "harness.ai_cli_backends.claude_triage.subprocess.Popen"
    )
    monkeypatch.setattr(module, launch)
    if isinstance(backend, ClaudeCliBackend):
        monkeypatch.setattr(
            "harness.ai_cli_backends.claude_triage._sandbox_exec_path",
            lambda: "/usr/bin/sandbox-exec",
        )
        monkeypatch.setattr(
            "harness.ai_cli_backends.claude_triage.sys.platform", "darwin"
        )
    result = backend.run_review_triage_turn(request)
    return result, captured


def _config_values(command: list[str]) -> set[str]:
    return {
        command[index + 1]
        for index, value in enumerate(command[:-1])
        if value in {"-c", "--config"}
    }


def test_review_triage_protocol_is_optional_and_runtime_checkable() -> None:
    assert isinstance(CodexCliBackend(_config("codex")), ReviewTriageBackend)
    assert isinstance(ClaudeCliBackend(_config("claude")), ReviewTriageBackend)


def test_facade_rejects_unsupported_backend_before_generic_launch(tmp_path) -> None:
    provider = AICodingCliProvider(_config("copilot", unsafe=True))

    with patch.object(provider._backend, "run_prompt") as generic_prompt, patch.object(
        provider._backend, "run_agent"
    ) as generic_agent:
        result = provider.run_review_triage_turn(
            str(tmp_path),
            "triage input",
            frontmatter={"model_tier": "strong", "effort": "medium"},
            timeout_ms=1_000,
        )

    assert result.exit_code == 125
    assert result.metadata == {
        "failure_reason": "review-triage-unsupported",
        "provider": "copilot",
    }
    generic_prompt.assert_not_called()
    generic_agent.assert_not_called()


def test_facade_passes_only_neutral_frontmatter_and_bounded_timeout(tmp_path) -> None:
    provider = AICodingCliProvider(_config("codex"))
    frontmatter = {"name": "echelon.review-debugger", "model_tier": "fast", "effort": "low"}

    with patch.object(
        provider._backend,
        "run_review_triage_turn",
        return_value=CliRunResult(0, "done", ""),
    ) as run:
        result = provider.run_review_triage_turn(
            str(tmp_path), "triage input", frontmatter=frontmatter, timeout_ms=9_000
        )

    assert result.exit_code == 0
    request = run.call_args.args[0]
    assert request.cwd == str(tmp_path)
    assert request.prompt == "triage input"
    assert request.timeout_s == 5.0
    assert request.metadata == {"prompt_metadata": frontmatter}


def test_claude_triage_requires_macos_isolation_before_launch_even_when_unsafe(
    tmp_path, monkeypatch
) -> None:
    provider = AICodingCliProvider(_config("claude", unsafe=True))
    monkeypatch.setattr(
        "harness.ai_cli_backends.claude_triage._sandbox_exec_path", lambda: None
    )

    with patch("harness.ai_cli_backends.claude_triage.subprocess.Popen") as popen:
        result = provider.run_review_triage_turn(
            str(tmp_path),
            "triage input",
            frontmatter={"model_tier": "strong", "effort": "medium"},
            timeout_ms=1_000,
        )

    assert result.exit_code == 125
    assert result.metadata == {"failure_reason": "isolation_unavailable"}
    popen.assert_not_called()


def test_codex_triage_maps_neutral_metadata_and_reuses_strict_no_tools_capture(
    tmp_path, monkeypatch
) -> None:
    backend = CodexCliBackend(_config("codex", unsafe=True))
    result, captured = _run_scripted_backend(
        backend, _request(tmp_path), monkeypatch, _codex_wire()
    )

    assert result.exit_code == 0
    assert result.stdout == "triaged"
    assert result.token_usage == 11
    command = captured["command"]
    assert isinstance(command, list)
    assert command[command.index("--model") + 1] == "gpt-5.6-sol"
    assert 'model_reasoning_effort="medium"' in _config_values(command)
    assert command[-1] == "-"
    assert all("triage input" not in argument for argument in command)
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--ask-for-approval") + 1] == "never"
    assert "--dangerously-bypass-approvals-and-sandbox" not in command
    assert {
        "features.shell_tool=false",
        "features.unified_exec=false",
        "features.apply_patch_freeform=false",
        'web_search="disabled"',
        "mcp_servers={}",
        "plugins={}",
        "agents.enabled=false",
        "features.multi_agent=false",
        "features.hooks=false",
        "hooks={}",
        "skills.include_instructions=false",
        "project_doc_max_bytes=0",
        'history.persistence="none"',
    } <= _config_values(command)


def test_claude_triage_uses_stdin_and_verified_native_isolation_controls(
    tmp_path, monkeypatch
) -> None:
    backend = ClaudeCliBackend(_config("claude", unsafe=True))
    request = _request(tmp_path, prompt="triage input π")
    result, captured = _run_scripted_backend(
        backend, request, monkeypatch, _claude_wire(),
    )

    assert result.exit_code == 0
    assert result.stdout == "triaged"
    assert result.token_usage == 13
    assert result.cost_usd == 0.125
    command = captured["command"]
    assert isinstance(command, list)
    assert command[:2] == ["/usr/bin/sandbox-exec", "-p"]
    assert "--safe-mode" in command
    assert "--bare" not in command
    assert command[command.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in command
    assert json.loads(command[command.index("--mcp-config") + 1]) == {
        "mcpServers": {}
    }
    assert command[command.index("--permission-mode") + 1] == "dontAsk"
    assert command[command.index("--tools") + 1] == ""
    assert command[command.index("--model") + 1] == "opus"
    assert command[command.index("--effort") + 1] == "medium"
    assert "--disable-slash-commands" in command
    assert "--no-session-persistence" in command
    assert "--no-chrome" in command
    assert "--agents" not in command
    assert "--plugin-dir" not in command
    assert "--dangerously-skip-permissions" not in command
    assert all("triage input" not in argument for argument in command)


@pytest.mark.parametrize(
    ("tier", "effort", "claude_model", "codex_model"),
    [
        ("fast", "low", "haiku", "gpt-5.6-luna"),
        ("balanced", "medium", "sonnet", "gpt-5.6-terra"),
        ("strong", "high", "opus", "gpt-5.6-sol"),
    ],
)
def test_triage_adapters_map_each_neutral_model_and_effort_without_fallback(
    tmp_path, monkeypatch, tier, effort, claude_model, codex_model
) -> None:
    codex_result, codex_capture = _run_scripted_backend(
        CodexCliBackend(_config("codex")),
        _request(tmp_path, tier=tier, effort=effort),
        monkeypatch,
        _codex_wire(),
    )
    claude_result, claude_capture = _run_scripted_backend(
        ClaudeCliBackend(_config("claude")),
        _request(tmp_path, tier=tier, effort=effort),
        monkeypatch,
        _claude_wire(),
    )

    assert codex_result.exit_code == claude_result.exit_code == 0
    codex_command = codex_capture["command"]
    claude_command = claude_capture["command"]
    assert codex_command[codex_command.index("--model") + 1] == codex_model
    assert f'model_reasoning_effort="{effort}"' in _config_values(codex_command)
    assert claude_command[claude_command.index("--model") + 1] == claude_model
    assert claude_command[claude_command.index("--effort") + 1] == effort


@pytest.mark.parametrize(
    "changes",
    [
        {"tier": "ultra"},
        {"tier": ""},
        {"tier": 7},
        {"effort": "max"},
        {"effort": ""},
        {"effort": False},
        {"metadata": {"execution_profile": "review_triage_v1", "prompt_metadata": {"model_tier": "strong", "effort": "medium"}}},
        {"metadata": {"prompt_metadata": {"model_tier": "strong", "effort": "medium", "model": "provider-model"}}},
        {"metadata": {"prompt_metadata": {"model_tier": "strong", "effort": "medium", "tool_read_roots": ["/"]}}},
    ],
)
@pytest.mark.parametrize("cli", ["claude", "codex"])
def test_triage_invalid_or_provider_specific_metadata_fails_before_launch(
    tmp_path, monkeypatch, cli, changes
) -> None:
    backend = ClaudeCliBackend(_config(cli)) if cli == "claude" else CodexCliBackend(_config(cli))
    request = _request(tmp_path, **changes)
    if cli == "claude":
        monkeypatch.setattr(
            "harness.ai_cli_backends.claude_triage._sandbox_exec_path",
            lambda: "/usr/bin/sandbox-exec",
        )
        monkeypatch.setattr(
            "harness.ai_cli_backends.claude_triage.sys.platform", "darwin"
        )
        target = "harness.ai_cli_backends.claude_triage.subprocess.Popen"
    else:
        target = "harness.ai_cli_backends.codex.subprocess.Popen"

    with patch(target) as popen:
        result = backend.run_review_triage_turn(request)

    assert result.exit_code == 125
    assert result.metadata == {"failure_reason": "invalid_request"}
    popen.assert_not_called()


@pytest.mark.parametrize("cli", ["claude", "codex"])
def test_triage_rejects_wrapper_inclusive_input_overflow_before_launch(
    tmp_path, monkeypatch, cli
) -> None:
    backend = ClaudeCliBackend(_config(cli)) if cli == "claude" else CodexCliBackend(_config(cli))
    request = _request(tmp_path, prompt="x" * _INPUT_CAP)
    if cli == "claude":
        monkeypatch.setattr(
            "harness.ai_cli_backends.claude_triage._sandbox_exec_path",
            lambda: "/usr/bin/sandbox-exec",
        )
        monkeypatch.setattr(
            "harness.ai_cli_backends.claude_triage.sys.platform", "darwin"
        )
        target = "harness.ai_cli_backends.claude_triage.subprocess.Popen"
    else:
        target = "harness.ai_cli_backends.codex.subprocess.Popen"

    with patch(target) as popen:
        result = backend.run_review_triage_turn(request)

    assert result.exit_code == 125
    assert result.metadata == {"failure_reason": "input_overflow"}
    popen.assert_not_called()


@pytest.mark.parametrize(
    ("cli", "wire"),
    [
        ("codex", _codex_wire(item_type="command_execution")),
        (
            "claude",
            (
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [
                                {"type": "tool_use", "name": "Read", "input": {}}
                            ]
                        },
                    }
                ).encode()
                + b"\n"
                + _claude_wire()
            ),
        ),
    ],
)
def test_triage_rejects_unexpected_tool_events(
    tmp_path, monkeypatch, cli, wire
) -> None:
    backend = ClaudeCliBackend(_config(cli)) if cli == "claude" else CodexCliBackend(_config(cli))
    result, _captured = _run_scripted_backend(
        backend, _request(tmp_path), monkeypatch, wire
    )

    assert result.exit_code == 125
    assert result.stdout == ""
    assert result.metadata["failure_reason"] == "tool_event"


@pytest.mark.parametrize("wire", [b"not-json\n", b"[]\n", b'{"type":"result","type":"result"}\n'])
def test_claude_triage_rejects_malformed_output_without_raising(
    tmp_path, monkeypatch, wire
) -> None:
    result, _captured = _run_scripted_backend(
        ClaudeCliBackend(_config("claude")),
        _request(tmp_path),
        monkeypatch,
        wire,
    )

    assert result.exit_code == 125
    assert result.stdout == ""
    assert result.metadata == {"failure_reason": "malformed_capture"}


@pytest.mark.parametrize(
    ("cli", "wire"),
    [
        ("codex", b"not-json\n"),
        ("codex", json.dumps({"type": "turn.completed"}).encode() + b"\n"),
        ("claude", json.dumps({"type": "system", "subtype": "init", "tools": []}).encode() + b"\n"),
        ("claude", _claude_wire(answer=None)),
    ],
)
def test_triage_rejects_malformed_or_missing_final_records(
    tmp_path, monkeypatch, cli, wire
) -> None:
    backend = ClaudeCliBackend(_config(cli)) if cli == "claude" else CodexCliBackend(_config(cli))
    result, _captured = _run_scripted_backend(
        backend, _request(tmp_path), monkeypatch, wire
    )

    assert result.exit_code == 125
    assert result.stdout == ""
    assert result.metadata["failure_reason"] in {
        "malformed_capture",
        "missing_final_answer",
    }


@pytest.mark.parametrize(
    ("cli", "wire", "expected_usage"),
    [
        (
            "codex",
            b'{"type":"turn.failed","usage":'
            b'{"input_tokens":9,"output_tokens":3}}\n',
            12,
        ),
        (
            "claude",
            _claude_wire(
                answer="provider failed",
                is_error=True,
                usage={"input_tokens": 9, "output_tokens": 3},
            ),
            12,
        ),
    ],
)
def test_failed_triage_turn_retains_observed_usage(
    tmp_path, monkeypatch, cli, wire, expected_usage
) -> None:
    backend = ClaudeCliBackend(_config(cli)) if cli == "claude" else CodexCliBackend(_config(cli))
    result, _captured = _run_scripted_backend(
        backend, _request(tmp_path), monkeypatch, wire
    )

    assert result.exit_code == 125
    assert result.stdout == ""
    assert result.token_usage == expected_usage
    assert result.metadata["failure_reason"] == "provider_event_failure"
    assert result.metadata["token_usage_status"] == "untrusted"


@pytest.mark.parametrize("cli", ["claude", "codex"])
def test_triage_capture_timeout_kills_and_reaps_scripted_process(
    tmp_path, monkeypatch, cli
) -> None:
    backend = ClaudeCliBackend(_config(cli)) if cli == "claude" else CodexCliBackend(_config(cli))
    request = replace(_request(tmp_path), timeout_s=0.1)
    started = time.monotonic()
    result, captured = _run_scripted_backend(
        backend,
        request,
        monkeypatch,
        b"",
        script="import time; time.sleep(2)",
    )

    assert time.monotonic() - started < 0.6
    assert result.exit_code == 124
    assert result.timed_out is True
    assert result.metadata == {"failure_reason": "timeout"}
    assert captured["process"].poll() is not None


@pytest.mark.parametrize("cli", ["claude", "codex"])
def test_triage_capture_rejects_combined_output_overflow(
    tmp_path, monkeypatch, cli
) -> None:
    backend = ClaudeCliBackend(_config(cli)) if cli == "claude" else CodexCliBackend(_config(cli))
    result, _captured = _run_scripted_backend(
        backend,
        _request(tmp_path),
        monkeypatch,
        b"",
        script=f"import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write(b'x'*{_CAPTURE_CAP + 1})",
    )

    assert result.exit_code == 125
    assert result.stdout == ""
    assert result.metadata == {"failure_reason": "capture_overflow"}


def test_codex_triage_normalizes_the_final_answer_only(tmp_path, monkeypatch) -> None:
    result, _captured = _run_scripted_backend(
        CodexCliBackend(_config("codex")),
        _request(tmp_path),
        monkeypatch,
        _codex_wire("  triaged\n"),
    )

    assert result.exit_code == 0
    assert result.stdout == "triaged"


def test_claude_triage_rejects_server_tool_event_variants(
    tmp_path, monkeypatch
) -> None:
    wire = (
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "server_tool_use", "name": "web_search"}
                    ]
                },
            }
        ).encode()
        + b"\n"
        + _claude_wire()
    )
    result, _captured = _run_scripted_backend(
        ClaudeCliBackend(_config("claude")),
        _request(tmp_path),
        monkeypatch,
        wire,
    )

    assert result.exit_code == 125
    assert result.metadata["failure_reason"] == "tool_event"


def test_failed_claude_triage_retains_usage_reported_before_error_result(
    tmp_path, monkeypatch
) -> None:
    wire = (
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "partial"}],
                    "usage": {"input_tokens": 11, "output_tokens": 2},
                },
            }
        ).encode()
        + b"\n"
        + _claude_wire(answer="failed", is_error=True, usage={})
    )
    result, _captured = _run_scripted_backend(
        ClaudeCliBackend(_config("claude")),
        _request(tmp_path),
        monkeypatch,
        wire,
    )

    assert result.exit_code == 125
    assert result.token_usage == 13
    assert result.metadata["token_usage_status"] == "untrusted"


@pytest.mark.skipif(
    sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file(),
    reason="requires macOS sandbox-exec",
)
def test_claude_triage_real_sandbox_allows_only_private_runtime_and_auth_reads(
    tmp_path,
) -> None:
    invocation = tmp_path / "invocation"
    invocation.mkdir()
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir()
    (auth_dir / ".credentials.json").write_text("synthetic credential\n")
    product = tmp_path / "product"
    product.mkdir()
    product_secret = product / "source.py"
    product_secret.write_text("sensitive product source\n")
    product_write = product / "model-write.txt"
    request = replace(
        _request(invocation),
        env={"CLAUDE_CONFIG_DIR": str(auth_dir), "PATH": "/usr/bin:/bin"},
    )
    prepared = prepare_claude_triage_request(
        "/bin/sh", request, tool_policy=LlmToolPolicy()
    )
    profile = prepared.command[2]
    probe = """
if IFS= read -r value < "$1"; then auth=1; else auth=0; fi
if IFS= read -r value < "$2"; then product=1; else product=0; fi
if IFS= read -r value < /etc/passwd; then host=1; else host=0; fi
if printf changed > "$3"; then write=1; else write=0; fi
printf '%s%s%s%s' "$auth" "$product" "$host" "$write"
"""

    result = subprocess.run(
        [
            "/usr/bin/sandbox-exec",
            "-p",
            profile,
            "/bin/sh",
            "-c",
            probe,
            "sh",
            str(auth_dir / ".credentials.json"),
            str(product_secret),
            str(product_write),
        ],
        cwd=invocation,
        env=prepared.env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "1000"
    assert not product_write.exists()


def test_codex_lone_failed_turn_retains_its_usage_as_untrusted(
    tmp_path, monkeypatch
) -> None:
    wire = (
        b'{"type":"turn.failed","error":{"message":"synthetic"},'
        b'"usage":{"input_tokens":9,"output_tokens":3}}\n'
    )
    result, _captured = _run_scripted_backend(
        CodexCliBackend(_config("codex")),
        _request(tmp_path),
        monkeypatch,
        wire,
    )

    assert result.exit_code == 125
    assert result.token_usage == 12
    assert result.metadata["token_usage_details"] == {
        "input_tokens": 9,
        "output_tokens": 3,
        "total_tokens": 12,
    }
    assert result.metadata["token_usage_status"] == "untrusted"
