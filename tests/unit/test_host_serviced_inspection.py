"""Compose real no-tools adapters and host reads, not a fulfillment workflow."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from harness.inspection_io import BoundedReadChannel, InspectionReadError
from harness.llm_provider import AICodingCliProvider
from tests.unit.test_inspection_turn import (
    FRONTMATTER, supported_host, install_scripted_process, assert_no_tools_command,
)
from tests.unit.test_review_triage_provider import _config, _codex_wire, _claude_wire

_REAL_POPEN = subprocess.Popen


@pytest.fixture
def inspection_roots(tmp_path):
    roots = {name: tmp_path / name for name in ("worktree", "spec", "evidence")}
    for path in roots.values():
        path.mkdir()
    (roots["worktree"] / "app.py").write_text("def hello(): return 'hello'\n")
    (roots["spec"] / "spec.md").write_text("FR-001: preserve legacy identity.\n")
    (roots["evidence"] / "audit.md").write_text("FR-001\nFR-000001 FR-1000000\n")
    return roots


def _snapshot(roots):
    return {str(path): path.read_bytes() for root in roots.values()
            for path in root.rglob("*") if path.is_file()}


def _turn(provider, tmp_path, number, prompt):
    cwd = tmp_path / f"invocation-{number}"
    cwd.mkdir()
    return provider.run_inspection_turn(str(cwd), prompt, frontmatter=FRONTMATTER, timeout_ms=1000)


@pytest.mark.parametrize("cli", ["claude", "codex"])
@pytest.mark.parametrize("denied", [False, True])
def test_real_adapters_request_host_evidence_and_consume_only_admitted_read(
    tmp_path, monkeypatch, inspection_roots, cli, denied,
):
    roots = inspection_roots
    before = _snapshot(roots)
    request = {"action": "read", "request": {"op": "read_file", "root": "evidence",
               "path": "audit.md", "start_line": 1, "line_count": 2}}
    wire = _codex_wire(json.dumps(request)) if cli == "codex" else _claude_wire(json.dumps(request))
    launches = install_scripted_process(monkeypatch, cli, wire=wire)
    provider = AICodingCliProvider(_config(cli, unsafe=True))
    first = _turn(provider, tmp_path, 1, "Inspect assigned evidence through host reads.")
    assert first.exit_code == 0, first.stderr
    assert json.loads(first.stdout) == request
    assert len(launches) == 1
    assert_no_tools_command(cli, launches[0]["command"])
    forbidden = (roots["evidence"] / "audit.md",) if denied else ()
    with BoundedReadChannel(roots, forbidden_paths=forbidden) as channel:
        if denied:
            with pytest.raises(InspectionReadError):
                channel.request(request["request"])
            assert _snapshot(roots) == before
            return  # Denied read authorizes no second turn.
        evidence = channel.request(request["request"])
    assert evidence == {"status": "ok", "text": "FR-001\nFR-000001 FR-1000000\n",
                        "start_line": 1, "total_lines": 2}
    expected_answer = '{"action":"result","summary":"Inspected all three exact IDs"}'
    final_wire = _codex_wire(expected_answer) if cli == "codex" else _claude_wire(expected_answer)
    needle = '"text": "FR-001\\nFR-000001 FR-1000000\\n"'
    script = ("import sys; prompt=sys.stdin.buffer.read().decode(); "
              f"assert {needle!r} in prompt, prompt; sys.stdout.buffer.write({final_wire!r})")
    second_launches = install_scripted_process(monkeypatch, cli, script=script)
    second = _turn(provider, tmp_path, 2, json.dumps({"untrusted_read_result": evidence}))
    assert second.exit_code == 0, second.stderr
    assert second.stdout == expected_answer
    assert len(second_launches) == 1
    assert_no_tools_command(cli, second_launches[0]["command"])
    assert first.token_usage == second.token_usage == (11 if cli == "codex" else 13)
    assert _snapshot(roots) == before


@pytest.mark.parametrize("cli", ["claude", "codex"])
@pytest.mark.parametrize("fault", ["isolation", "tool", "malformed", "timeout", "overflow"])
def test_provider_failure_cannot_supply_host_read_authority(
    tmp_path, monkeypatch, inspection_roots, cli, fault,
):
    wire = b"invalid\n" if fault == "malformed" else (
        _codex_wire(item_type="command_execution") if cli == "codex" else
        b'{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash"}]}}\n' + _claude_wire())
    script = ("import sys; sys.stdin.buffer.read(); sys.stdout.write('x'*300000)" if fault == "overflow"
              else "import time; time.sleep(10)" if fault == "timeout" else None)
    launches = install_scripted_process(monkeypatch, cli, wire=wire, script=script)
    if fault == "isolation":
        monkeypatch.setattr("harness.ai_cli_backends.claude.host_workspace_synthesis_boundary_available", lambda: False)
    config = _config(cli)
    if fault == "timeout":
        config.llm.timeout_ms = 50
    provider = AICodingCliProvider(config)
    before = _snapshot(inspection_roots)
    result = _turn(provider, tmp_path, 1, "Inspect assigned evidence.")
    assert result.exit_code != 0
    assert result.stdout == ""
    assert len(launches) == (0 if fault == "isolation" else 1)
    assert _snapshot(inspection_roots) == before
    if fault == "tool":
        assert result.token_usage == provider.last_token_usage == (11 if cli == "codex" else 13)


@pytest.mark.skipif(sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file(),
                    reason="requires real macOS sandbox-exec")
def test_inspection_facade_claude_profile_denies_direct_source_access(
    tmp_path, monkeypatch, inspection_roots,
):
    """Execute the emitted OS profile, substituting a shell probe for the model."""
    provider = AICodingCliProvider(_config("claude"))
    provider._backend._bin = "/bin/sh"
    secret = inspection_roots["worktree"] / "app.py"
    output = inspection_roots["worktree"] / "forbidden-write"
    wire = _claude_wire("host boundary enforced").decode()
    probe = '''
IFS= read -r prompt
if IFS= read -r value < "$1"; then exit 91; fi
if printf changed > "$2"; then exit 92; fi
printf '%s' "$3"
'''
    commands = []
    def launch(command, **kwargs):
        commands.append(command)
        return _REAL_POPEN([*command[:3], "/bin/sh", "-c", probe, "sh", str(secret), str(output), wire], **kwargs)
    monkeypatch.setattr("subprocess.Popen", launch)
    before = _snapshot(inspection_roots)
    result = _turn(provider, tmp_path, 1, "inspect")
    assert result.exit_code == 0, result.stderr
    assert result.stdout == "host boundary enforced"
    assert_no_tools_command("claude", commands[0])
    assert _snapshot(inspection_roots) == before
