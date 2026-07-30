"""Offline unit tests for the isolated SUE cold-reader runner."""

from __future__ import annotations

import importlib.util
import json
import stat
import sys
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
    assert invocation.argv == [
        "codex", "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox", "read-only",
        "--ignore-user-config",
        "--ignore-rules",
        "--model", "gpt-5.6-luna",
        "-c", 'model_reasoning_effort="low"',
        "--output-schema", str(tmp_path / "output-schema.json"),
        "--json",
        "--output-last-message", str(tmp_path / "final.json"),
        "-",
    ]
    assert invocation.stdin_text == "PROMPT"
    assert invocation.argv[-1] == "-"
    assert "PROMPT" not in invocation.argv


def test_scientific_codex_request_rejects_missing_model():
    with pytest.raises(runner.RunnerConfigurationError):
        _codex_request(model=None, scientific=True)


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


def _make_fake_codex(tmp_path: Path, body: str) -> str:
    executable = tmp_path / "fake-codex"
    executable.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return str(executable)


def test_fake_codex_runner_captures_final_output_and_usage(tmp_path):
    fake = _make_fake_codex(
        tmp_path,
        """import json, pathlib, sys
args = sys.argv[1:]
assert args[:2] == ['exec', '--ephemeral']
assert sys.stdin.read() == 'PROMPT'
pathlib.Path(args[args.index('--output-last-message') + 1]).write_text('{\"questions\": []}')
print(json.dumps({'type': 'thread.started', 'thread_id': 'thread-1'}))
print(json.dumps({'type': 'turn.completed', 'model': 'gpt-5.6-luna', 'usage': {'input_tokens': 12}}))
""",
    )
    result = runner.run_cold_reader(_codex_request(fake))
    assert result.status == "success"
    assert json.loads(result.final_output) == {"questions": []}
    assert result.usage["input_tokens"] == 12
    assert result.model_requested == "gpt-5.6-luna"
    assert result.argv_redacted[-1] == "-"
    assert "PROMPT" not in result.argv_redacted
    assert result.raw_output_digest
    assert result.final_output_digest


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
