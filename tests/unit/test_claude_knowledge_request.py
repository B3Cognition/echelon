from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from harness.ai_cli_backend import CliRunRequest, ConstrainedPromptBackend
from harness.ai_cli_backends.claude import ClaudeCliBackend
from harness.config import HarnessConfig, LlmConfig
from harness.llm_provider import AICodingCliProvider
from harness.llm_tool_policy import LlmToolPolicy


_POLICY_PREFIX = """## Effective Host Tool Policy

- File boundary: workspace
- Network boundary: harness_allowlist
- Unsafe host execution bypass: disabled
- Deterministic enforcement: unsafe CLI permission-bypass flags are only added when explicitly approved in harness config.
- Remaining scope: file/network/tool limits beyond CLI permission flags depend on the selected AI CLI runtime.
"""


def _backend(*, unsafe: bool = False) -> ClaudeCliBackend:
    return ClaudeCliBackend(
        HarnessConfig(
            target_repo=".",
            target_default_branch="main",
            provider="docker",
            llm=LlmConfig(
                cli="claude",
                tool_policy=LlmToolPolicy(
                    allow_unsafe_host_execution=unsafe,
                    approval_reason="ordinary execution fixture" if unsafe else None,
                ),
            ),
        )
    )


def _request(cwd: Path, prompt: str = "Synthetic knowledge request.") -> CliRunRequest:
    return CliRunRequest(
        cwd=str(cwd),
        prompt=prompt,
        env={},
        timeout_s=2,
    )


def _invoke(
    tmp_path: Path,
    monkeypatch,
    *,
    wire: bytes,
    screen=None,
    request: CliRunRequest | None = None,
    max_capture_bytes: int = 64 * 1024,
    script: str | None = None,
):
    real_popen = subprocess.Popen
    fixture = script or (
        "import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write(" + repr(wire) + ")"
    )

    def launch(_command, **kwargs):
        return real_popen([sys.executable, "-c", fixture], **kwargs)

    monkeypatch.setattr("harness.ai_cli_backends.claude.subprocess.Popen", launch)
    return _backend().run_constrained_prompt(
        request or _request(tmp_path),
        model="safe-model",
        screen_output=screen or (lambda value: value),
        max_input_bytes=64 * 1024,
        max_capture_bytes=max_capture_bytes,
    )


def _wire(*events: object) -> bytes:
    return b"".join(
        json.dumps(event, separators=(",", ":")).encode() + b"\n"
        for event in events
    )


def _init(**changes: object) -> dict[str, object]:
    event: dict[str, object] = {
        "type": "system",
        "subtype": "init",
        "tools": [],
        "mcp_servers": [],
        "slash_commands": [],
        "skills": [],
        "plugins": [],
        "permissionMode": "dontAsk",
    }
    event.update(changes)
    return event


def test_claude_backend_advertises_its_constrained_execution_contract() -> None:
    assert (
        getattr(_backend(), "constrained_execution_contract_id", None)
        == "claude-constrained-prompt-v1"
    )


def test_claude_backend_resolves_neutral_model_tiers_for_constrained_calls() -> None:
    backend = _backend()

    assert getattr(backend, "model_for_tier", lambda _tier: None)("fast") == "haiku"
    assert getattr(backend, "model_for_tier", lambda _tier: None)("balanced") == "sonnet"
    assert getattr(backend, "model_for_tier", lambda _tier: None)("strong") == "opus"
    assert getattr(backend, "model_for_tier", lambda _tier: None)("unknown") is None


def test_claude_backend_satisfies_the_constrained_prompt_protocol() -> None:
    assert isinstance(_backend(), ConstrainedPromptBackend)


def test_claude_capability_is_visible_through_the_configured_provider_facade() -> None:
    provider = AICodingCliProvider(_backend()._config)

    assert provider.provider_id == "claude"
    assert provider.constrained_execution_contract_id == "claude-constrained-prompt-v1"
    assert provider.constrained_model_for_tier("balanced") == "sonnet"


def test_claude_knowledge_prompt_uses_restricted_stateless_stdin_execution(
    tmp_path: Path, monkeypatch
) -> None:
    raw_prompt = "Synthetic payload π."
    expected = _POLICY_PREFIX + raw_prompt
    captured: dict[str, object] = {}
    real_popen = subprocess.Popen
    fixture = (
        "import json,sys; data=sys.stdin.buffer.read().decode(); "
        "print(json.dumps({'type':'system','subtype':'init','tools':[],"
        "'mcp_servers':[],'slash_commands':[],'skills':[],'plugins':[],"
        "'permissionMode':'dontAsk'})); "
        "print(json.dumps({'type':'assistant','message':{'content':"
        "[{'type':'text','text':data}]}})); "
        "print(json.dumps({'type':'result','subtype':'success','is_error':False,"
        "'result':data,'usage':{'input_tokens':3,'output_tokens':2,"
        "'cache_creation_input_tokens':0,'cache_read_input_tokens':0,"
        "'output_tokens_details':{'thinking_tokens':0}}}))"
    )

    def launch(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs.get("env")
        return real_popen([sys.executable, "-c", fixture], **kwargs)

    monkeypatch.setattr("harness.ai_cli_backends.claude.subprocess.Popen", launch)
    seen: list[bytes] = []
    result = _backend(unsafe=True).run_constrained_prompt(
        _request(tmp_path, raw_prompt),
        model="safe-model",
        screen_output=lambda value: seen.append(value) or value,
        max_input_bytes=64 * 1024,
        max_capture_bytes=64 * 1024,
    )

    assert result.exit_code == 0
    assert result.stdout == expected
    assert result.stderr == ""
    assert result.token_usage == 5
    assert result.metadata["token_usage_details"] == {
        "input_tokens": 3,
        "cached_input_tokens": 0,
        "output_tokens": 2,
        "reasoning_output_tokens": 0,
        "total_tokens": 5,
    }
    assert expected.encode() in seen

    command = captured["command"]
    assert isinstance(command, list)
    assert command[0:2] == [_backend()._bin, "-p"]
    assert raw_prompt not in command
    assert "--dangerously-skip-permissions" not in command
    assert "--restricted" in command
    # Claude 2.1.270 drops an existing OAuth session under --safe-mode/--bare.
    # --restricted supplies the customization boundary while preserving auth.
    assert "--safe-mode" not in command
    assert "--bare" not in command
    assert "--setting-sources" not in command
    assert "--no-session-persistence" in command
    assert command[command.index("--tools") + 1] == ""
    assert command[command.index("--permission-prompts") + 1] == "none"
    assert command[command.index("--output-format") + 1] == "stream-json"
    assert command[command.index("--model") + 1] == "safe-model"


@pytest.mark.parametrize(
    "changes, reason",
    [
        ({"prompt": ""}, "invalid_request"),
        ({"prompt": "bad\ud800"}, "invalid_request"),
        ({"timeout_s": 0}, "invalid_request"),
        ({"metadata": {"tool_read_roots": ["."]}}, "invalid_request"),
        ({"metadata": {"source_scope": "repo"}}, "invalid_request"),
    ],
)
def test_claude_constrained_request_rejects_invalid_scope_before_spawn(
    tmp_path: Path, monkeypatch, changes, reason
) -> None:
    monkeypatch.setattr(
        "harness.ai_cli_backends.claude.subprocess.Popen",
        lambda *_args, **_kwargs: pytest.fail("must reject before process spawn"),
    )
    result = _backend().run_constrained_prompt(
        replace(_request(tmp_path), **changes),
        model="safe-model",
        screen_output=lambda value: value,
        max_input_bytes=64 * 1024,
        max_capture_bytes=64 * 1024,
    )

    assert result.metadata == {"failure_reason": reason}


def test_claude_constrained_request_rejects_tool_use_events(
    tmp_path: Path, monkeypatch
) -> None:
    result = _invoke(
        tmp_path,
        monkeypatch,
        wire=_wire(
            _init(),
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Read", "input": {"path": "/tmp"}}
                    ]
                },
            },
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "unsafe",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        ),
    )

    assert result.exit_code == 125
    assert result.stdout == ""
    assert result.metadata == {"failure_reason": "tool_event"}


@pytest.mark.parametrize(
    "result_fields",
    [
        {"permission_denials": [{"tool_name": "Read"}]},
        {"subagent_stats": {"spawned": 1}},
        {"usage": {"server_tool_use": {"web_search_requests": 1}}},
    ],
)
def test_claude_constrained_request_rejects_hidden_tool_activity(
    tmp_path: Path, monkeypatch, result_fields
) -> None:
    result_event = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "unsafe",
        "usage": {
            "input_tokens": 1,
            "output_tokens": 1,
            "output_tokens_details": {"thinking_tokens": 0},
        },
        **result_fields,
    }
    result = _invoke(
        tmp_path,
        monkeypatch,
        wire=_wire(_init(), result_event),
    )

    assert result.exit_code == 125
    assert result.stdout == ""
    assert result.metadata == {"failure_reason": "tool_event"}


def test_claude_constrained_request_accepts_native_thinking_before_final_text(
    tmp_path: Path, monkeypatch
) -> None:
    result = _invoke(
        tmp_path,
        monkeypatch,
        wire=_wire(
            _init(),
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "thinking", "thinking": "", "signature": "signed"}
                    ]
                },
            },
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "OK"}]},
            },
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "OK",
                "usage": {
                    "input_tokens": 3,
                    "output_tokens": 2,
                    "output_tokens_details": {"thinking_tokens": 0},
                },
            },
        ),
    )

    assert result.exit_code == 0
    assert result.stdout == "OK"


@pytest.mark.parametrize(
    "events",
    [
        (
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "OK",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        ),
        (
            _init(plugins=[{"name": "unexpected"}]),
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "OK",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        ),
    ],
)
def test_claude_constrained_request_requires_native_boundary_attestation(
    tmp_path: Path, monkeypatch, events
) -> None:
    result = _invoke(tmp_path, monkeypatch, wire=_wire(*events))

    assert result.exit_code == 125
    assert result.stdout == ""
    assert result.metadata == {"failure_reason": "boundary_not_attested"}


def test_claude_constrained_request_fails_closed_when_output_screen_rejects(
    tmp_path: Path, monkeypatch
) -> None:
    wire = _wire(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "secret",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )
    result = _invoke(
        tmp_path,
        monkeypatch,
        wire=wire,
        screen=lambda value: b"" if b"secret" in value else value,
    )

    assert result.exit_code == 125
    assert result.stdout == ""
    assert result.stderr == "screened Claude capture failed"
    assert result.metadata == {"failure_reason": "screen_rejected"}


def test_claude_constrained_request_bounds_aggregate_provider_output(
    tmp_path: Path, monkeypatch
) -> None:
    result = _invoke(
        tmp_path,
        monkeypatch,
        wire=b"x" * 4097,
        max_capture_bytes=4096,
    )

    assert result.exit_code == 125
    assert result.stdout == ""
    assert result.metadata == {"failure_reason": "capture_overflow"}


def test_claude_constrained_request_kills_and_reaps_on_timeout(
    tmp_path: Path, monkeypatch
) -> None:
    request = replace(_request(tmp_path), timeout_s=0.2)
    started = time.monotonic()
    result = _invoke(
        tmp_path,
        monkeypatch,
        request=request,
        wire=b"",
        script="import sys,time; sys.stdin.buffer.read(); time.sleep(5)",
    )

    assert time.monotonic() - started < 2
    assert result.exit_code == 124
    assert result.timed_out is True
    assert result.metadata == {"failure_reason": "timeout"}
