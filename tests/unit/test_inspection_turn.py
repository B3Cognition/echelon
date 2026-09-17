"""The inspection facade must expose only the existing no-tools boundary."""
from dataclasses import replace
import json
import subprocess
import sys

import pytest

from harness.llm_provider import AICodingCliProvider
from tests.unit.test_review_triage_provider import _config, _request, _codex_wire, _claude_wire, _config_values

_REAL_POPEN = subprocess.Popen
FRONTMATTER = {"model_tier": "strong", "effort": "medium"}


@pytest.fixture(autouse=True)
def supported_host(monkeypatch):
    monkeypatch.setattr("harness.ai_cli_backends.claude.host_workspace_synthesis_boundary_available", lambda: True)
    monkeypatch.setattr("harness.ai_cli_backends.claude_triage._sandbox_exec_path", lambda: "/usr/bin/sandbox-exec")
    monkeypatch.setattr("harness.ai_cli_backends.claude_triage.sys.platform", "darwin")


def _no_launch(*args, **kwargs):
    pytest.fail("invalid inspection launched a process")


def install_scripted_process(monkeypatch, cli, *, wire=None, script=None):
    """Replace only external model execution; retain real request/capture code."""
    wire = wire if wire is not None else (_codex_wire("inspected") if cli == "codex" else _claude_wire("inspected"))
    script = script or f"import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write({wire!r})"
    launches = []
    def launch(command, **kwargs):
        process = _REAL_POPEN([sys.executable, "-c", script], **kwargs)
        launches.append({"command": command, "process": process, "env": kwargs["env"]})
        return process
    monkeypatch.setattr("subprocess.Popen", launch)
    return launches


def _run(provider, cwd, **kwargs):
    return provider.run_inspection_turn(str(cwd), kwargs.pop("prompt", "Inspect supplied evidence."),
                                       frontmatter=kwargs.pop("frontmatter", FRONTMATTER),
                                       timeout_ms=kwargs.pop("timeout_ms", 1000), **kwargs)


def test_unsupported_inspection_never_falls_back(tmp_path, monkeypatch):
    provider = AICodingCliProvider(_config("copilot", unsafe=True))
    monkeypatch.setattr("subprocess.Popen", _no_launch)
    assert provider.supports_inspection_turn is False
    result = _run(provider, tmp_path)
    assert result.exit_code == 125
    assert result.metadata["failure_reason"] == "inspection-unsupported"


@pytest.mark.parametrize("cli", ["claude", "codex"])
def test_host_unavailable_blocks_facade_and_direct_adapter(tmp_path, monkeypatch, cli):
    monkeypatch.setattr("harness.ai_cli_backends.claude.host_workspace_synthesis_boundary_available", lambda: False)
    monkeypatch.setattr("subprocess.Popen", _no_launch)
    provider = AICodingCliProvider(_config(cli, unsafe=True))
    assert provider.supports_inspection_turn is False
    for result in (_run(provider, tmp_path), provider._backend.run_inspection_turn(_request(tmp_path))):
        assert result.exit_code == 125
        assert result.metadata["failure_reason"] == "isolation_unavailable"


@pytest.mark.parametrize("cli", ["claude", "codex"])
@pytest.mark.parametrize("kwargs", [
    {"timeout_ms": True}, {"timeout_ms": 0}, {"timeout_ms": -1},
    {"timeout_ms": float("inf")}, {"prompt": ""}, {"prompt": None},
    {"frontmatter": None}, {"frontmatter": {}},
    *[{"frontmatter": {**FRONTMATTER, key: "unsafe"}} for key in
      ("name", "provider", "model", "tool_read_roots", "execution_profile", "source_root")],
    {"frontmatter": {"model_tier": "unknown", "effort": "medium"}},
    {"frontmatter": {"model_tier": "strong", "effort": "unknown"}},
])
def test_invalid_facade_inputs_never_launch(tmp_path, monkeypatch, cli, kwargs):
    monkeypatch.setattr("subprocess.Popen", _no_launch)
    provider = AICodingCliProvider(_config(cli))
    provider.last_stdout, provider.last_stderr, provider.last_token_usage = "old", "old", 99
    result = _run(provider, tmp_path, **kwargs)
    assert result.exit_code == 125
    assert result.metadata["failure_reason"] == "invalid_request"
    assert provider.last_stdout == ""
    assert provider.last_token_usage == result.token_usage


@pytest.mark.parametrize("cli", ["claude", "codex"])
@pytest.mark.parametrize("kind", ["missing", "nonempty", "symlink"])
def test_private_cwd_is_required(tmp_path, monkeypatch, cli, kind):
    cwd = tmp_path / "private"
    if kind == "nonempty":
        cwd.mkdir()
        (cwd / "source.py").write_text("source")
    elif kind == "symlink":
        target = tmp_path / "target"
        target.mkdir()
        cwd.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr("subprocess.Popen", _no_launch)
    provider = AICodingCliProvider(_config(cli))
    assert _run(provider, cwd).metadata["failure_reason"] == "invalid_request"
    assert provider._backend.run_inspection_turn(_request(cwd)).metadata["failure_reason"] == "invalid_request"


@pytest.mark.parametrize("cli", ["claude", "codex"])
@pytest.mark.parametrize("updates", [
    {"timeout_s": True}, {"timeout_s": float("nan")}, {"timeout_s": -1},
    {"metadata": {"prompt_metadata": FRONTMATTER, "execution_profile": "review_triage_v1"}},
    {"metadata": {"prompt_metadata": {**FRONTMATTER, "tool_write_paths": []}}},
])
def test_direct_adapter_cannot_bypass_admission(tmp_path, monkeypatch, cli, updates):
    monkeypatch.setattr("subprocess.Popen", _no_launch)
    backend = AICodingCliProvider(_config(cli))._backend
    result = backend.run_inspection_turn(replace(_request(tmp_path), **updates))
    assert result.exit_code == 125
    assert result.metadata["failure_reason"] == "invalid_request"


def assert_no_tools_command(cli, command):
    if cli == "codex":
        assert {"features.shell_tool=false", "features.unified_exec=false", "agents.enabled=false",
                "features.multi_agent=false", "features.apply_patch_freeform=false",
                'web_search="disabled"', "mcp_servers={}", "plugins={}", "hooks={}",
                "project_doc_max_bytes=0", "skills.include_instructions=false"} <= _config_values(command)
        assert command[command.index("--sandbox") + 1] == "read-only"
        assert "--strict-config" in command and "--ignore-user-config" in command
        assert "--dangerously-bypass-approvals-and-sandbox" not in command
    else:
        assert command[:2] == ["/usr/bin/sandbox-exec", "-p"]
        assert command[command.index("--tools") + 1] == ""
        assert json.loads(command[command.index("--mcp-config") + 1]) == {"mcpServers": {}}
        assert "--safe-mode" in command and "--strict-mcp-config" in command
        assert "--disable-slash-commands" in command
        assert "--dangerously-skip-permissions" not in command


@pytest.mark.parametrize("cli,usage,model", [("claude", 13, "opus"), ("codex", 11, "gpt-5.6-sol")])
def test_facade_uses_real_no_tools_adapter_and_capture(tmp_path, monkeypatch, cli, usage, model):
    launches = install_scripted_process(monkeypatch, cli)
    provider = AICodingCliProvider(_config(cli, unsafe=True))
    assert provider.supports_inspection_turn is True
    result = _run(provider, tmp_path)
    assert result.exit_code == 0, result.stderr
    assert result.stdout == provider.last_stdout == "inspected"
    assert result.token_usage == provider.last_token_usage == usage
    assert len(launches) == 1
    command = launches[0]["command"]
    assert_no_tools_command(cli, command)
    assert command[command.index("--model") + 1] == model


@pytest.mark.parametrize("cli", ["claude", "codex"])
@pytest.mark.parametrize("fault", ["tool", "malformed", "overflow", "timeout", "input_overflow"])
def test_bad_provider_outcome_never_becomes_inspection_success(tmp_path, monkeypatch, cli, fault):
    wire = b"invalid JSON\n" if fault == "malformed" else (
        _codex_wire(item_type="command_execution") if cli == "codex" else
        b'{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash"}]}}\n' + _claude_wire())
    script = None
    if fault == "overflow":
        script = "import sys; sys.stdin.buffer.read(); sys.stdout.write('x' * 300000)"
    elif fault == "timeout":
        script = "import time; time.sleep(10)"
    launches = install_scripted_process(monkeypatch, cli, wire=wire, script=script)
    provider = AICodingCliProvider(_config(cli))
    result = _run(provider, tmp_path, prompt="x" * 1048576 if fault == "input_overflow" else "inspect",
                  timeout_ms=50 if fault == "timeout" else 1000)
    assert result.exit_code != 0
    assert result.stdout == ""
    if fault == "input_overflow":
        assert launches == []
    else:
        assert len(launches) == 1
        assert launches[0]["process"].poll() is not None
    if fault == "tool":
        assert result.token_usage == (11 if cli == "codex" else 13)
