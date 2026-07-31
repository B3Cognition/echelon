"""Offline unit tests for the isolated SUE cold-reader runner."""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import shlex
import stat
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "sue_runner.py"


def _load_module(name: str = "sue_runner"):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


runner = _load_module()

EXPECTED_DISABLED_FEATURES = (
    "apps",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "chronicle",
    "code_mode",
    "code_mode_buffered_exec",
    "code_mode_host",
    "code_mode_only",
    "computer_use",
    "deferred_executor",
    "enable_mcp_apps",
    "external_agent_memory_import",
    "hooks",
    "in_app_browser",
    "memories",
    "multi_agent",
    "multi_agent_v2",
    "plugin_sharing",
    "plugins",
    "remote_plugin",
    "shell_snapshot",
    "shell_tool",
    "shell_zsh_fork",
    "skill_mcp_dependency_install",
    "skill_search",
    "standalone_web_search",
    "tool_suggest",
    "unified_exec",
    "unified_exec_zsh_fork",
)


def _codex_request(command: str = "codex", **overrides):
    values = {
        "run_id": "run-1",
        "provider": "codex",
        "command": command,
        "model": "gpt-5.6-luna",
        "reasoning_effort": "low",
        "prompt": "PROMPT",
        "timeout_seconds": 30,
        "output_schema": {"type": "object"},
    }
    values.update(overrides)
    return runner.ColdReaderRequest(**values)


def test_codex_invocation_is_cold_and_explicit(tmp_path):
    invocation = runner.build_model_invocation(_codex_request(), tmp_path)
    expected = [
        "codex", "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox", "read-only",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "-c", "shell_environment_policy.inherit=none",
        "-c", 'tools.web_search="disabled"',
        "-c", "mcp_servers={}",
    ]
    for feature in EXPECTED_DISABLED_FEATURES:
        expected.extend(["--disable", feature])
    expected.extend([
        "--model", "gpt-5.6-luna",
        "-c", 'model_reasoning_effort="low"',
        "--output-schema", str(tmp_path / "output-schema.json"),
        "--json",
        "--output-last-message", str(tmp_path / "final.json"),
        "-",
    ])
    assert invocation.argv == expected
    assert invocation.stdin_text == "PROMPT"
    assert invocation.argv[-1] == "-"
    assert "PROMPT" not in invocation.argv
    assert set(runner.build_subprocess_environment()) <= set(
        runner.COLD_READER_ENV_ALLOWLIST
    )


def test_scientific_codex_request_rejects_missing_model():
    with pytest.raises(runner.RunnerConfigurationError):
        _codex_request(model=None, scientific=True)


def test_scientific_codex_request_rejects_missing_reasoning_effort():
    with pytest.raises(runner.RunnerConfigurationError, match="reasoning effort"):
        _codex_request(reasoning_effort=None, scientific=True)


def test_scientific_codex_request_rejects_secret_bearing_command_wrapper():
    secret = "sue-sentinel-secret"
    with pytest.raises(
        runner.RunnerConfigurationError, match="single executable"
    ) as error:
        _codex_request(
            command=f"env OPENAI_API_KEY={secret} codex",
            scientific=True,
        )
    assert secret not in str(error.value)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"provider": "claude"}, "unsupported provider"),
        ({"reasoning_effort": "maximum"}, "reasoning effort"),
        ({"output_schema": None, "scientific": True}, "output schema"),
        ({"prompt": ""}, "prompt"),
    ],
)
def test_request_rejects_invalid_configuration(overrides, match):
    with pytest.raises(runner.RunnerConfigurationError, match=match):
        _codex_request(**overrides)


def test_invocation_rejects_unparseable_command(tmp_path):
    request = _codex_request(command='codex "')
    with pytest.raises(runner.RunnerConfigurationError, match="shell-parseable"):
        runner.build_model_invocation(request, tmp_path)


def test_parse_codex_jsonl_extracts_usage_and_reported_model():
    raw = "\n".join([
        json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
        json.dumps({
            "type": "turn.completed",
            "model": "gpt-5.6-luna",
            "usage": {
                "input_tokens": 100,
                "cached_input_tokens": 20,
                "output_tokens": 30,
                "reasoning_output_tokens": 5,
            },
        }),
    ])
    metadata, usage = runner.parse_codex_jsonl(raw)
    assert metadata["thread_id"] == "thread-1"
    assert metadata["model_reported"] == "gpt-5.6-luna"
    assert usage["input_tokens"] == 100


@pytest.mark.parametrize(
    "raw",
    [
        json.dumps({
            "type": "turn.completed",
            "model": "gpt-5.6-luna",
            "usage": {},
        }),
        "\n".join([
            json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
            json.dumps({"type": "turn.completed", "usage": {}}),
        ]),
    ],
)
def test_parse_codex_jsonl_requires_thread_and_reported_model(raw):
    with pytest.raises(ValueError, match="thread_id and model"):
        runner.parse_codex_jsonl(raw)


def test_request_rejects_non_json_serializable_output_schema():
    with pytest.raises(runner.RunnerConfigurationError, match="JSON-serializable"):
        _codex_request(output_schema={"invalid": object()})


def _make_fake_codex(tmp_path: Path, body: str) -> str:
    executable = tmp_path / "fake-codex"
    executable.write_text(
        """#!/usr/bin/env python3
import sys
if sys.argv[1:] == ["--version"]:
    print("codex-cli 0.146.0-test")
    raise SystemExit(0)
"""
        + body,
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return str(executable)


def test_fake_codex_runner_captures_final_output_and_usage(tmp_path, monkeypatch):
    repository_sentinel = REPO_ROOT / "AGENTS.md"
    assert repository_sentinel.exists()
    monkeypatch.setenv("SUE_SENTINEL_CREDENTIAL", "must-not-leak")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("CODEX_THREAD_ID", "must-not-leak")
    monkeypatch.setenv("CODEX_CI", "must-not-leak")
    monkeypatch.setenv("ECHELON_LLM", "must-not-leak")
    fake = _make_fake_codex(
        tmp_path,
        f"""import json, os, pathlib, sys
args = sys.argv[1:]
expected = [
    'exec', '--ephemeral', '--skip-git-repo-check',
    '--sandbox', 'read-only', '--ignore-user-config', '--ignore-rules',
    '--strict-config',
    '-c', 'shell_environment_policy.inherit=none',
    '-c', 'tools.web_search="disabled"',
    '-c', 'mcp_servers={{}}',
]
for feature in {EXPECTED_DISABLED_FEATURES!r}:
    expected.extend(['--disable', feature])
expected.extend([
    '--model', 'gpt-5.6-luna',
    '-c', 'model_reasoning_effort="low"',
    '--output-schema', args[args.index('--output-schema') + 1],
    '--json',
    '--output-last-message', args[args.index('--output-last-message') + 1],
    '-',
])
assert args == expected, (args, expected)
assert pathlib.Path(args[args.index('--output-schema') + 1]).resolve().parent == pathlib.Path.cwd().resolve()
assert pathlib.Path(args[args.index('--output-last-message') + 1]).resolve().parent == pathlib.Path.cwd().resolve()
assert sys.stdin.read() == 'PROMPT'
assert not (pathlib.Path.cwd() / {repository_sentinel.name!r}).exists()
assert not (pathlib.Path.cwd() / '.git').exists()
for forbidden in (
    'SUE_SENTINEL_CREDENTIAL', 'OPENAI_API_KEY', 'CODEX_THREAD_ID',
    'CODEX_CI', 'ECHELON_LLM',
):
    assert forbidden not in os.environ
pathlib.Path(args[args.index('--output-last-message') + 1]).write_text(
    json.dumps({{'questions': [], 'env_keys': sorted(os.environ)}})
)
print(json.dumps({{'type': 'thread.started', 'thread_id': 'thread-1'}}))
print(json.dumps({{
    'type': 'turn.completed',
    'model': 'gpt-5.6-luna',
    'usage': {{'input_tokens': 12}},
}}))
""",
    )
    result = runner.run_cold_reader(_codex_request(fake))
    assert result.status == "success", result.stderr
    final = json.loads(result.final_output)
    assert final["questions"] == []
    assert set(final["env_keys"]) <= set(runner.COLD_READER_ENV_ALLOWLIST)
    assert result.usage["input_tokens"] == 12
    assert result.model_requested == "gpt-5.6-luna"
    assert result.argv_redacted[-1] == "-"
    assert "PROMPT" not in result.argv_redacted
    assert result.raw_output_digest
    assert result.final_output_digest


def test_non_scientific_wrapper_secret_is_redacted_from_evidence(tmp_path):
    secret = "sue-sentinel-secret"
    fake = _make_fake_codex(
        tmp_path,
        """import json, pathlib, sys
args = sys.argv[1:]
pathlib.Path(args[args.index('--output-last-message') + 1]).write_text('{}')
print(json.dumps({'type': 'thread.started', 'thread_id': 'thread-1'}))
print(json.dumps({'type': 'turn.completed', 'model': 'gpt-5.6-luna', 'usage': {}}))
""",
    )
    command = f"env OPENAI_API_KEY={secret} {shlex.quote(fake)}"
    result = runner.run_cold_reader(_codex_request(command))
    assert result.status == "success"
    assert all(secret not in token for token in result.argv_redacted)
    assert "OPENAI_API_KEY=<redacted>" in result.argv_redacted


def test_success_result_captures_complete_immutable_execution_metadata(tmp_path):
    fake = _make_fake_codex(
        tmp_path,
        """import json, pathlib, sys
args = sys.argv[1:]
pathlib.Path(args[args.index('--output-last-message') + 1]).write_text('{}')
print(json.dumps({'type': 'thread.started', 'thread_id': 'thread-1'}))
print(json.dumps({'type': 'turn.completed', 'model': 'gpt-5.6-luna', 'usage': {}}))
""",
    )
    request = _codex_request(fake, prompt="EXACT PROMPT", timeout_seconds=17)
    result = runner.run_cold_reader(request)
    assert result.status == "success"
    assert datetime.fromisoformat(result.started_at_utc.replace("Z", "+00:00")).tzinfo
    assert result.timeout_seconds == 17
    assert result.provider_cli_version == "codex-cli 0.146.0-test"
    assert result.provider_cli_version_status == "reported"
    assert result.prompt_digest == hashlib.sha256(b"EXACT PROMPT").hexdigest()
    canonical_schema = json.dumps(
        request.output_schema,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    assert result.schema_digest == hashlib.sha256(canonical_schema.encode()).hexdigest()
    assert result.stderr_digest == hashlib.sha256(result.stderr.encode()).hexdigest()
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.timeout_seconds = 99


@pytest.mark.parametrize(
    ("body", "timeout_seconds", "expected_status"),
    [
        ("import time\ntime.sleep(5)\n", 0.05, "timeout"),
        ("print('not json')\n", 2, "unusable_output"),
        ("import sys\nsys.exit(7)\n", 2, "transport_error"),
    ],
)
def test_runner_classifies_fake_process_failures(tmp_path, body, timeout_seconds, expected_status):
    fake = _make_fake_codex(tmp_path, body)
    result = runner.run_cold_reader(_codex_request(fake, timeout_seconds=timeout_seconds))
    assert result.status == expected_status


def test_runner_reports_missing_executable():
    result = runner.run_cold_reader(_codex_request("/missing/sue-codex"))
    assert result.status == "launch_missing"


def test_runner_requires_final_output_file(tmp_path):
    fake = _make_fake_codex(
        tmp_path,
        """import json
print(json.dumps({'type': 'thread.started', 'thread_id': 'thread-1'}))
print(json.dumps({'type': 'turn.completed', 'model': 'gpt-5.6-luna', 'usage': {}}))
""",
    )
    result = runner.run_cold_reader(_codex_request(fake))
    assert result.status == "unusable_output"


def test_runner_preserves_final_output_when_jsonl_is_unusable(tmp_path):
    fake = _make_fake_codex(
        tmp_path,
        """import pathlib, sys
args = sys.argv[1:]
pathlib.Path(args[args.index('--output-last-message') + 1]).write_text('{\"questions\": []}')
print('not json')
""",
    )
    result = runner.run_cold_reader(_codex_request(fake))
    assert result.status == "unusable_output"
    assert result.final_output == '{"questions": []}'
    assert result.final_output_digest == hashlib.sha256(
        result.final_output.encode("utf-8")
    ).hexdigest()


def test_runner_uses_neutral_temporary_workdir(tmp_path):
    fake = _make_fake_codex(
        tmp_path,
        """import json, pathlib, sys
args = sys.argv[1:]
assert pathlib.Path.cwd().name.startswith('sue-reader-')
assert pathlib.Path.cwd() != pathlib.Path(sys.argv[0]).parent
pathlib.Path(args[args.index('--output-last-message') + 1]).write_text('{}')
print(json.dumps({'type': 'thread.started', 'thread_id': 'thread-1'}))
print(json.dumps({'type': 'turn.completed', 'model': 'gpt-5.6-luna', 'usage': {}}))
""",
    )
    assert runner.run_cold_reader(_codex_request(fake)).status == "success"


def test_timeout_kills_descendant_holding_output_pipes(tmp_path):
    fake = _make_fake_codex(
        tmp_path,
        """import subprocess, sys, time
subprocess.Popen(
    [sys.executable, '-c', 'import time; time.sleep(60)'],
    stdout=sys.stdout,
    stderr=sys.stderr,
)
time.sleep(60)
""",
    )
    started = time.monotonic()
    result = runner.run_cold_reader(_codex_request(fake, timeout_seconds=0.1))
    assert result.status == "timeout"
    assert time.monotonic() - started < 3
