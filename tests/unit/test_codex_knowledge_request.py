from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from harness.ai_cli_backend import CliRunRequest
from harness.ai_cli_backends.codex import CodexCliBackend
from harness.config import HarnessConfig, LlmConfig
from harness.llm_tool_policy import LlmToolPolicy


_POLICY_PREFIX = """## Effective Host Tool Policy

- File boundary: workspace
- Network boundary: harness_allowlist
- Unsafe host execution bypass: disabled
- Deterministic enforcement: unsafe CLI permission-bypass flags are only added when explicitly approved in harness config.
- Remaining scope: file/network/tool limits beyond CLI permission flags depend on the selected AI CLI runtime.
"""


def _backend(*, inherit_user_config: bool = True, unsafe: bool = False) -> CodexCliBackend:
    policy = LlmToolPolicy(
        allow_unsafe_host_execution=unsafe,
        approval_reason="synthetic fixture" if unsafe else None,
    )
    return CodexCliBackend(
        HarnessConfig(
            target_repo=".",
            target_default_branch="main",
            provider="docker",
            llm=LlmConfig(
                cli="codex",
                codex_inherit_user_config=inherit_user_config,
                tool_policy=policy,
            ),
        )
    )


def _request(cwd: Path, prompt: str = "Synthetic knowledge request.", **changes):
    request = CliRunRequest(
        cwd=str(cwd),
        prompt=prompt,
        env={},
        timeout_s=2,
    )
    return replace(request, **changes)


def _wire(answer: str = "done", *, usage: dict[str, int] | None = None) -> bytes:
    events: list[object] = [
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": answer},
        },
        {"type": "turn.completed", "usage": usage},
    ]
    return b"".join(
        json.dumps(event, separators=(",", ":")).encode() + b"\n"
        for event in events
    )


def _invoke_with_local_process(
    tmp_path: Path,
    monkeypatch,
    *,
    request: CliRunRequest | None = None,
    script: str | None = None,
    screen=None,
    max_input_bytes: int = 64 * 1024,
    max_capture_bytes: int = 64 * 1024,
    backend: CodexCliBackend | None = None,
):
    captured: dict[str, object] = {}
    real_popen = subprocess.Popen
    wire = _wire(usage={"input_tokens": 7, "output_tokens": 4})
    fixture = script or f"import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write({wire!r})"

    def launch(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs.get("env")
        process = real_popen([sys.executable, "-c", fixture], **kwargs)
        captured["process"] = process
        return process

    monkeypatch.setattr("harness.ai_cli_backends.codex.subprocess.Popen", launch)
    result = (backend or _backend()).run_constrained_prompt(
        request or _request(tmp_path),
        model="safe-model",
        screen_output=screen or (lambda value: value),
        max_input_bytes=max_input_bytes,
        max_capture_bytes=max_capture_bytes,
    )
    return result, captured


def _config_values(command: list[str]) -> set[str]:
    return {
        command[index + 1]
        for index, value in enumerate(command[:-1])
        if value == "-c"
    }


def test_knowledge_prompt_is_screened_in_full_and_delivered_only_through_stdin(
    tmp_path, monkeypatch
) -> None:
    raw_prompt = "Synthetic payload π."
    expected = (_POLICY_PREFIX + raw_prompt).encode()
    seen: list[bytes] = []
    fixture = (
        "import json,sys; data=sys.stdin.buffer.read().decode(); "
        "print(json.dumps({'type':'item.completed','item':"
        "{'type':'agent_message','text':data}})); "
        "print(json.dumps({'type':'turn.completed','usage':"
        "{'input_tokens':3,'output_tokens':2}}))"
    )

    result, captured = _invoke_with_local_process(
        tmp_path,
        monkeypatch,
        request=_request(tmp_path, raw_prompt),
        script=fixture,
        screen=lambda value: seen.append(value) or value,
    )

    assert result.exit_code == 0
    assert result.stdout.encode() == expected
    command = captured["command"]
    assert isinstance(command, list)
    assert command[-1] == "-"
    assert all(raw_prompt not in argument for argument in command)
    assert expected in seen


def test_knowledge_prompt_rejects_wrapper_inclusive_input_overflow_before_spawn(
    tmp_path, monkeypatch
) -> None:
    request = _request(tmp_path, "x")
    spawned = False

    def forbidden_spawn(*_args, **_kwargs):
        nonlocal spawned
        spawned = True
        raise AssertionError("must reject before spawn")

    monkeypatch.setattr("harness.ai_cli_backends.codex.subprocess.Popen", forbidden_spawn)
    result = _backend().run_constrained_prompt(
        request,
        model="safe-model",
        screen_output=lambda value: value,
        max_input_bytes=len(request.prompt.encode()),
        max_capture_bytes=4096,
    )

    assert result.metadata == {"failure_reason": "input_overflow"}
    assert not spawned


@pytest.mark.parametrize(
    "changes",
    [
        {"prompt": ""},
        {"prompt": "bad\ud800"},
        {"timeout_s": 0},
        {"timeout_s": float("nan")},
        {"env": {"VALID": object()}},
        {"metadata": {"allow_unsafe_host_execution": True}},
        {"metadata": {"prompt_metadata": {"tool_read_roots": ["."]}}},
    ],
)
def test_knowledge_prompt_rejects_malformed_or_caller_scoped_request_before_spawn(
    tmp_path, monkeypatch, changes
) -> None:
    request = _request(tmp_path, **changes)
    spawned = False

    def forbidden_spawn(*_args, **_kwargs):
        nonlocal spawned
        spawned = True
        raise AssertionError("must reject before spawn")

    monkeypatch.setattr("harness.ai_cli_backends.codex.subprocess.Popen", forbidden_spawn)
    result = _backend().run_constrained_prompt(
        request,
        model="safe-model",
        screen_output=lambda value: value,
        max_input_bytes=4096,
        max_capture_bytes=4096,
    )

    assert result.metadata == {"failure_reason": "invalid_request"}
    assert not spawned


@pytest.mark.parametrize("model", ["", "  ", "safe\nmodel", None, 7])
def test_knowledge_prompt_requires_explicit_nonempty_model_before_spawn(
    tmp_path, monkeypatch, model
) -> None:
    monkeypatch.setattr(
        "harness.ai_cli_backends.codex.subprocess.Popen",
        lambda *_args, **_kwargs: pytest.fail("must reject before spawn"),
    )
    result = _backend().run_constrained_prompt(
        _request(tmp_path),
        model=model,
        screen_output=lambda value: value,
        max_input_bytes=4096,
        max_capture_bytes=4096,
    )

    assert result.metadata == {"failure_reason": "invalid_request"}


@pytest.mark.parametrize("state", ["nonempty", "symlink", "missing", "file"])
def test_knowledge_prompt_requires_fresh_empty_nonsymlink_directory_before_spawn(
    tmp_path, monkeypatch, state
) -> None:
    cwd = tmp_path / "cwd"
    if state == "nonempty":
        cwd.mkdir()
        (cwd / ".hidden").write_text("occupied")
    elif state == "symlink":
        target = tmp_path / "target"
        target.mkdir()
        cwd.symlink_to(target, target_is_directory=True)
    elif state == "file":
        cwd.write_text("not a directory")

    monkeypatch.setattr(
        "harness.ai_cli_backends.codex.subprocess.Popen",
        lambda *_args, **_kwargs: pytest.fail("must reject before spawn"),
    )
    result = _backend().run_constrained_prompt(
        _request(cwd),
        model="safe-model",
        screen_output=lambda value: value,
        max_input_bytes=4096,
        max_capture_bytes=4096,
    )

    assert result.metadata == {"failure_reason": "invalid_request"}


def test_knowledge_command_pins_model_refuses_config_inheritance_and_disables_tools(
    tmp_path, monkeypatch
) -> None:
    result, captured = _invoke_with_local_process(
        tmp_path,
        monkeypatch,
        request=_request(
            tmp_path,
            metadata={"prompt_metadata": {"model_tier": "strong"}},
            env={
                "CODEX_HOME": "/synthetic/auth-home",
                "OPENAI_API_KEY": "synthetic-auth-route",
                "RUST_LOG": "trace",
                "CODEX_LOG": "trace",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "https://telemetry.invalid",
                "TRACEPARENT": "synthetic-trace",
            },
        ),
        backend=_backend(inherit_user_config=True, unsafe=True),
    )

    assert result.exit_code == 0
    command = captured["command"]
    assert isinstance(command, list)
    assert command[command.index("--model") + 1] == "safe-model"
    assert "gpt-5.6-sol" not in command
    for flag in (
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "--json",
        "--skip-git-repo-check",
    ):
        assert flag in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--ask-for-approval") + 1] == "never"
    assert "--dangerously-bypass-approvals-and-sandbox" not in command

    config = _config_values(command)
    for required in {
        "features.shell_tool=false",
        "features.unified_exec=false",
        "experimental_use_unified_exec_tool=false",
        "features.apply_patch_freeform=false",
        'web_search="disabled"',
        "features.view_image=false",
        "features.image_generation=false",
        "features.browser_use=false",
        "features.computer_use=false",
        "features.apps=false",
        "features.connectors=false",
        "features.enable_mcp_apps=false",
        "mcp_servers={}",
        "features.plugins=false",
        "plugins={}",
        "agents.enabled=false",
        "features.multi_agent=false",
        "features.memories=false",
        "memories.use_memories=false",
        "features.hooks=false",
        "hooks={}",
        "skills.include_instructions=false",
        "skills.bundled.enabled=false",
        "project_doc_max_bytes=0",
        "analytics.enabled=false",
        'otel.exporter="none"',
        "otel.log_user_prompt=false",
        'history.persistence="none"',
    }:
        assert required in config

    env = captured["env"]
    assert isinstance(env, dict)
    assert env["CODEX_HOME"] == "/synthetic/auth-home"
    assert env["OPENAI_API_KEY"] == "synthetic-auth-route"
    assert not ({"RUST_LOG", "CODEX_LOG", "TRACEPARENT"} & env.keys())
    assert not any(key.startswith("OTEL_") for key in env)


@pytest.mark.parametrize("limit_name,bad", [
    ("max_input_bytes", 0),
    ("max_input_bytes", True),
    ("max_input_bytes", 1.5),
    ("max_capture_bytes", 0),
    ("max_capture_bytes", True),
    ("max_capture_bytes", 1.5),
])
def test_knowledge_prompt_rejects_invalid_finite_limits_before_spawn(
    tmp_path, monkeypatch, limit_name, bad
) -> None:
    kwargs = {"max_input_bytes": 4096, "max_capture_bytes": 4096}
    kwargs[limit_name] = bad
    monkeypatch.setattr(
        "harness.ai_cli_backends.codex.subprocess.Popen",
        lambda *_args, **_kwargs: pytest.fail("must reject before spawn"),
    )

    result = _backend().run_constrained_prompt(
        _request(tmp_path),
        model="safe-model",
        screen_output=lambda value: value,
        **kwargs,
    )

    assert result.metadata == {"failure_reason": "invalid_request"}


def test_knowledge_capture_writes_large_input_while_draining_large_output(
    tmp_path, monkeypatch
) -> None:
    prompt = "p" * 200_000
    fixture = (
        "import json,sys; sys.stderr.buffer.write(b'e'*100000); "
        "sys.stderr.buffer.flush(); data=sys.stdin.buffer.read(); "
        "print(json.dumps({'type':'item.completed','item':"
        "{'type':'agent_message','text':str(len(data))}})); "
        "print(json.dumps({'type':'turn.completed','usage':"
        "{'input_tokens':9,'output_tokens':2}}))"
    )

    result, _captured = _invoke_with_local_process(
        tmp_path,
        monkeypatch,
        request=_request(tmp_path, prompt),
        script=fixture,
        max_input_bytes=300_000,
        max_capture_bytes=120_000,
    )

    assert result.exit_code == 0
    assert result.stdout == str(len((_POLICY_PREFIX + prompt).encode()))


def test_knowledge_capture_times_out_child_that_never_reads_stdin_without_feeder_thread(
    tmp_path, monkeypatch
) -> None:
    request = replace(_request(tmp_path, "p" * 200_000), timeout_s=0.15)
    started = time.monotonic()
    result, captured = _invoke_with_local_process(
        tmp_path,
        monkeypatch,
        request=request,
        script="import time; time.sleep(2)",
        max_input_bytes=300_000,
    )

    assert time.monotonic() - started < 0.8
    assert result.timed_out is True
    assert result.metadata == {"failure_reason": "timeout"}
    process = captured["process"]
    assert hasattr(process, "poll")
    assert process.poll() is not None


def test_knowledge_capture_handles_child_exit_before_reading_stdin(
    tmp_path, monkeypatch
) -> None:
    result, captured = _invoke_with_local_process(
        tmp_path,
        monkeypatch,
        request=_request(tmp_path, "p" * 200_000),
        script="raise SystemExit(7)",
        max_input_bytes=300_000,
    )

    assert result.metadata == {"failure_reason": "provider_exit"}
    process = captured["process"]
    assert hasattr(process, "poll")
    assert process.poll() is not None


def test_screened_capture_aggregates_modern_turn_usage(tmp_path, monkeypatch) -> None:
    wire = b"".join(
        [
            _wire("first", usage={"input_tokens": 10, "output_tokens": 2}),
            _wire("second", usage={"input_tokens": 6, "output_tokens": 3}),
        ]
    )
    result, _captured = _invoke_with_local_process(
        tmp_path,
        monkeypatch,
        script=f"import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write({wire!r})",
    )

    assert result.exit_code == 0
    assert result.stdout == "second"
    assert result.token_usage == 21
    assert result.metadata["token_usage_details"] == {
        "input_tokens": 16,
        "output_tokens": 5,
        "total_tokens": 21,
    }


@pytest.mark.parametrize("legacy_first", [True, False])
@pytest.mark.parametrize("usages,want_total", [
    ([{"input_tokens": 100_001}], 100_001),
    ([{"input_tokens": 90_000, "output_tokens": 10_001, "total_tokens": 15}], 100_001),
    ([{"output_tokens": 100_001, "input_tokens": True}], 100_001),
    ([{"input_tokens": 90_000, "output_tokens": 10_001, "total_tokens": -1}], 100_001),
    ([{"input_tokens": 60_000}], 60_000),
    ([{"input_tokens": 45_000, "output_tokens": 15_000, "total_tokens": 15}], 60_000),
    ([{"input_tokens": 3}], 23),
    ([None], 23),
    ([{"total_tokens": 100_002}], 100_002),
    ([{"input_tokens": 40_000, "output_tokens": 10_000},
      {"input_tokens": 40_000, "output_tokens": 10_000}], 100_000),
])
def test_mixed_capture_retains_component_lower_bound_without_double_counting(
    tmp_path, monkeypatch, legacy_first, usages, want_total,
) -> None:
    legacy = json.dumps({"type": "event_msg", "payload": {
        "type": "token_count", "info": {"total_token_usage": {
            "input_tokens": 16, "cached_input_tokens": 0,
            "output_tokens": 7, "reasoning_output_tokens": 0,
        }},
    }}).encode() + b"\n"
    modern = b"".join(_wire(usage=usage) for usage in usages)
    wire = legacy + modern if legacy_first else modern + legacy

    result, _captured = _invoke_with_local_process(
        tmp_path, monkeypatch,
        script=f"import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write({wire!r})",
    )

    assert result.exit_code == 0
    assert result.stdout == "done"
    assert result.token_usage == want_total
    assert result.metadata["token_usage_status"] == "untrusted"


@pytest.mark.parametrize("legacy_first", [True, False])
@pytest.mark.parametrize("legacy_usages,modern_usages,want_total", [
    ([{"input_tokens": 100_001}], [{"input_tokens": 10, "output_tokens": 5}], 100_001),
    ([{"input_tokens": 90_000, "output_tokens": 10_001, "total_tokens": 15}],
     [{"input_tokens": 10, "output_tokens": 5}], 100_001),
    ([{"input_tokens": 100_001}, {"input_tokens": 10, "output_tokens": 5}],
     [{"input_tokens": 10, "output_tokens": 5}], 100_001),
    ([{"input_tokens": 10, "output_tokens": 5}, {"input_tokens": 100_001}],
     [{"input_tokens": 10, "output_tokens": 5}], 100_001),
    ([{"input_tokens": 90_000, "output_tokens": 10_001, "total_tokens": 15}, {}],
     [{"input_tokens": 10, "output_tokens": 5}], 100_001),
    ([{"input_tokens": 100_001}, {"total_tokens": 20}], [{"input_tokens": 100_003}], 100_003),
    ([{"output_tokens": 100_001, "input_tokens": True}], [None], 100_001),
    ([{"input_tokens": 90_000, "output_tokens": 10_001, "total_tokens": -1}],
     [{"total_tokens": 100_003}], 100_003),
    ([{"total_tokens": 100_002}, {"input_tokens": 100_001}], [{"input_tokens": 3}], 100_002),
    ([{"input_tokens": 60_000}, {"output_tokens": 60_000}], [{"input_tokens": 60_000}], 60_000),
    ([{"input_tokens": 45_000, "output_tokens": 15_000, "total_tokens": 15}],
     [{"input_tokens": 60_000}], 60_000),
    ([{"input_tokens": 100_000, "cached_input_tokens": 100_000,
       "reasoning_output_tokens": 100_000, "cache_write_input_tokens": 100_000}],
     [{"input_tokens": 60_000}], 100_000),
    ([{"input_tokens": 100_001}], [{"total_tokens": 60_000}, {"input_tokens": 60_000}], 120_000),
    ([{"input_tokens": 100_001}], [
        {"input_tokens": 10, "output_tokens": 5, "total_tokens": 60_000},
        {"input_tokens": 60_000, "total_tokens": 15}], 120_000),
])
def test_mixed_capture_preserves_each_legacy_snapshot_and_modern_turn_bound(
    tmp_path, monkeypatch, legacy_first, legacy_usages, modern_usages, want_total,
) -> None:
    legacy = b"".join(json.dumps({"type": "event_msg", "payload": {
        "type": "token_count", "info": {"total_token_usage": usage},
    }}).encode() + b"\n" for usage in legacy_usages)
    modern = b"".join(_wire(usage=usage) for usage in modern_usages)
    wire = legacy + modern if legacy_first else modern + legacy
    result, _captured = _invoke_with_local_process(
        tmp_path, monkeypatch,
        script=f"import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write({wire!r})",
    )

    assert result.exit_code == 0
    assert result.stdout == "done"
    assert result.token_usage == want_total
    assert result.metadata["token_usage_status"] == "untrusted"


def test_screened_capture_preserves_safe_usage_when_later_provider_event_fails(
    tmp_path, monkeypatch
) -> None:
    wire = _wire("candidate", usage={"input_tokens": 11, "output_tokens": 4}) + (
        b'{"type":"turn.failed","error":{"message":"synthetic failure"}}\n'
    )
    result, _captured = _invoke_with_local_process(
        tmp_path,
        monkeypatch,
        script=f"import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write({wire!r})",
    )

    assert result.metadata["failure_reason"] == "provider_event_failure"
    assert result.token_usage == 15
    assert result.metadata["token_usage_details"]["total_tokens"] == 15


def test_failed_modern_turn_makes_retained_completed_subtotal_untrusted(
    tmp_path, monkeypatch
) -> None:
    wire = _wire(
        "earlier",
        usage={
            "input_tokens": 11,
            "cached_input_tokens": 2,
            "output_tokens": 4,
            "reasoning_output_tokens": 1,
        },
    ) + (
        b'{"type":"turn.started"}\n'
        b'{"type":"turn.failed","error":{"message":"synthetic"}}\n'
    )
    result, _captured = _invoke_with_local_process(
        tmp_path,
        monkeypatch,
        script=f"import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write({wire!r})",
    )

    assert result.metadata["failure_reason"] == "provider_event_failure"
    assert result.token_usage == 15
    assert result.metadata["token_usage_status"] == "untrusted"


def test_unfinished_later_turn_cannot_reuse_prior_final_answer(
    tmp_path, monkeypatch
) -> None:
    wire = _wire(
        "stale earlier answer",
        usage={
            "input_tokens": 11,
            "cached_input_tokens": 2,
            "output_tokens": 4,
            "reasoning_output_tokens": 1,
        },
    ) + b'{"type":"turn.started"}\n'
    result, _captured = _invoke_with_local_process(
        tmp_path,
        monkeypatch,
        script=f"import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write({wire!r})",
    )

    assert result.metadata["failure_reason"] == "missing_final_answer"
    assert result.stdout == ""
    assert result.token_usage == 15
    assert result.metadata["token_usage_status"] == "untrusted"


def test_incomplete_legacy_snapshot_cannot_erase_known_cumulative_overspend(
    tmp_path, monkeypatch
) -> None:
    known = {
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": 90_000,
                    "cached_input_tokens": 0,
                    "output_tokens": 10_001,
                    "reasoning_output_tokens": 0,
                }
            },
        },
    }
    missing = {
        "type": "event_msg",
        "payload": {"type": "token_count", "info": None},
    }
    complete = {
        "type": "event_msg",
        "payload": {"type": "task_complete", "last_agent_message": "done"},
    }
    wire = b"".join(
        json.dumps(row, separators=(",", ":")).encode() + b"\n"
        for row in (known, missing, complete)
    )
    result, _captured = _invoke_with_local_process(
        tmp_path,
        monkeypatch,
        script=f"import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write({wire!r})",
    )

    assert result.exit_code == 0
    assert result.token_usage == 100_001
    assert result.metadata["token_usage_status"] == "untrusted"
    assert result.metadata["token_usage_details"]["total_tokens"] == 100_001


def test_screened_capture_preserves_safe_usage_when_later_output_is_rejected(
    tmp_path, monkeypatch
) -> None:
    wire = _wire(
        "candidate",
        usage={
            "input_tokens": 11,
            "cached_input_tokens": 2,
            "output_tokens": 4,
            "reasoning_output_tokens": 1,
        },
    ) + b'{"type":"diagnostic","message":"C\\u0041NARY"}\n'

    def screen(value: bytes) -> bytes:
        if b"CANARY" in value:
            raise ValueError("private scanner detail")
        return value

    result, _captured = _invoke_with_local_process(
        tmp_path,
        monkeypatch,
        script=f"import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write({wire!r})",
        screen=screen,
    )

    assert result.metadata["failure_reason"] == "screen_rejected"
    assert result.token_usage == 15
    assert result.metadata["token_usage_status"] == "untrusted"
    assert "private scanner detail" not in repr(result)


def test_screened_capture_does_not_mark_missing_or_ambiguous_usage_exact(
    tmp_path, monkeypatch
) -> None:
    wire = _wire("candidate", usage={"input_tokens": 11})
    result, _captured = _invoke_with_local_process(
        tmp_path,
        monkeypatch,
        script=f"import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write({wire!r})",
    )

    assert result.token_usage is None
    assert result.metadata["token_usage_details"] == {"input_tokens": 11}
    assert result.metadata.get("token_usage_status") == "untrusted"


def test_screened_capture_marks_prefix_usage_untrusted_after_malformed_record(
    tmp_path, monkeypatch
) -> None:
    wire = _wire(
        "candidate",
        usage={
            "input_tokens": 11,
            "cached_input_tokens": 2,
            "output_tokens": 4,
            "reasoning_output_tokens": 1,
        },
    ) + b"not-json\n"
    result, _captured = _invoke_with_local_process(
        tmp_path,
        monkeypatch,
        script=f"import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write({wire!r})",
    )

    assert result.metadata["failure_reason"] == "malformed_capture"
    assert result.token_usage == 15
    assert result.metadata["token_usage_status"] == "untrusted"


def test_screened_capture_preserves_usage_when_final_answer_is_missing(
    tmp_path, monkeypatch
) -> None:
    wire = (
        b'{"type":"turn.completed","usage":{"input_tokens":11,'
        b'"cached_input_tokens":2,"output_tokens":4,'
        b'"reasoning_output_tokens":1}}\n'
    )
    result, _captured = _invoke_with_local_process(
        tmp_path,
        monkeypatch,
        script=f"import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write({wire!r})",
    )

    assert result.metadata["failure_reason"] == "missing_final_answer"
    assert result.token_usage == 15
    assert result.metadata["token_usage_status"] == "trusted_exact"


def test_screened_capture_preserves_usage_when_final_answer_screen_is_rejected(
    tmp_path, monkeypatch
) -> None:
    wire = _wire(
        "reject-this-final-only",
        usage={
            "input_tokens": 11,
            "cached_input_tokens": 2,
            "output_tokens": 4,
            "reasoning_output_tokens": 1,
        },
    )

    def screen(value: bytes) -> bytes:
        if value == b"reject-this-final-only":
            raise ValueError("private final scanner detail")
        return value

    result, _captured = _invoke_with_local_process(
        tmp_path,
        monkeypatch,
        script=f"import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write({wire!r})",
        screen=screen,
    )

    assert result.metadata["failure_reason"] == "screen_rejected"
    assert result.token_usage == 15
    assert result.metadata["token_usage_status"] == "trusted_exact"
    assert "private final scanner detail" not in repr(result)


def test_ordinary_codex_execution_keeps_prompt_in_argv_and_stdin_unowned(
    tmp_path, monkeypatch
) -> None:
    captured: dict[str, object] = {}
    real_popen = subprocess.Popen

    def launch(command, **kwargs):
        captured["command"] = command
        captured["stdin"] = kwargs.get("stdin")
        return real_popen(
            [sys.executable, "-c", "import sys; raise SystemExit(0)"], **kwargs
        )

    monkeypatch.setattr("harness.ai_cli_backends.codex.subprocess.Popen", launch)
    result = _backend().run_prompt(
        _request(tmp_path, "Ordinary prompt.", metadata={"allow_non_git_cwd": True})
    )

    assert result.exit_code == 0
    command = captured["command"]
    assert isinstance(command, list)
    assert command[-1].endswith("Ordinary prompt.")
    assert captured["stdin"] is None
