"""Neutral delivery scopes must be enforced by the real Claude adapter."""

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.ai_cli_backends.claude import ClaudeCliBackend
from harness.config import HarnessConfig
from tests.unit.test_delivery_slice_runner import slice_project


pytestmark = pytest.mark.unit


def _request(root, *, exclusive=True, write_paths=(), forbidden=()):
    return CliRunRequest(
        cwd=str(root), prompt="Inspect the assigned source and tests.", env={}, timeout_s=10,
        metadata={"prompt_metadata": {
            "tool_read_roots": [str(root)],
            "tool_write_paths": [str(path) for path in write_paths],
            "tool_forbidden_roots": [str(path) for path in forbidden],
            "tool_write_scope_exclusive": exclusive,
        }},
    )


def _command(request, *, unsafe=False):
    config = HarnessConfig()
    config.llm.cli = "claude"
    config.llm.tool_policy = replace(
        config.llm.tool_policy, allow_unsafe_host_execution=unsafe,
        approval_reason="test host policy" if unsafe else None,
    )
    backend = ClaudeCliBackend(config)
    with patch.object(backend, "_run_stream_json", return_value=CliRunResult(0, "", "")) as run:
        with patch("harness.ai_cli_backends.claude._sandbox_exec_path", return_value="/usr/bin/sandbox-exec"):
            result = backend.run_agent(request)
    assert result.exit_code == 0, result.stderr
    return run.call_args.args[0]


@pytest.mark.parametrize("unsafe", [False, True])
def test_exclusive_review_disables_writing_tools_and_unsafe_bypass(tmp_path, unsafe):
    command = _command(_request(tmp_path.resolve()), unsafe=unsafe)
    assert command[:2] == ["/usr/bin/sandbox-exec", "-p"]
    tools = set(command[command.index("--tools") + 1].split(","))
    assert tools == {"Read", "Glob", "Grep"}
    assert "--dangerously-skip-permissions" not in command
    assert "--safe-mode" in command  # Preserves normal auth, disables customizations.
    assert command[command.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in command
    assert "--disable-slash-commands" in command


def test_exclusive_review_without_host_boundary_never_dispatches(tmp_path):
    backend = ClaudeCliBackend(HarnessConfig())
    with patch.object(backend, "_run_stream_json", return_value=CliRunResult(0, "", "")) as run:
        with patch("harness.ai_cli_backends.claude._sandbox_exec_path", return_value=None):
            result = backend.run_agent(_request(tmp_path.resolve()))
    assert result.exit_code == 125
    assert result.metadata == {"workspace_synthesis_boundary": "unavailable"}
    assert not run.called


@pytest.mark.parametrize("unsafe", [False, True])
def test_nonexclusive_implementation_approves_scoped_edits_and_preserves_shell_policy(tmp_path, unsafe):
    root = tmp_path.resolve()
    command = _command(_request(
        root, exclusive=False, write_paths=[root / ".echelon/runnability.yml"],
        forbidden=[root / ".echelon"],
    ), unsafe=unsafe)
    assert command[:2] == ["/usr/bin/sandbox-exec", "-p"]
    assert "--tools" not in command  # No output-only restriction on implementation.
    rules = set(command[command.index("--allowedTools") + 1].split(","))
    assert rules == {
        f"Read({root}/**)", f"Write({root}/**)", f"Edit({root}/**)",
        f"Read({root}/.echelon/runnability.yml)",
        f"Write({root}/.echelon/runnability.yml)",
        f"Edit({root}/.echelon/runnability.yml)",
    }
    assert ("--dangerously-skip-permissions" in command) is unsafe
    assert "--permission-mode" not in command


@pytest.mark.parametrize("component", ["unsafe,name", "pattern[abc]"])
@pytest.mark.parametrize("exclusive", [False, True])
def test_unrepresentable_tool_scope_is_rejected(tmp_path, component, exclusive):
    backend = ClaudeCliBackend(HarnessConfig())
    with patch.object(backend, "_run_stream_json", return_value=CliRunResult(0, "", "")) as run:
        result = backend.run_agent(_request(tmp_path / component, exclusive=exclusive))
    assert result.exit_code == 125
    assert not run.called


def test_exclusive_scope_cannot_bypass_boundary_through_triage_profile(tmp_path):
    backend = ClaudeCliBackend(HarnessConfig())
    request = _request(tmp_path.resolve())
    request.metadata["execution_profile"] = "review_triage_v1"
    with patch.object(backend, "_run_stream_json", return_value=CliRunResult(0, "", "")) as run:
        result = backend.run_agent(request)
    assert result.exit_code == 125
    assert result.metadata == {"exclusive_write_scope": "invalid"}
    assert not run.called


@pytest.mark.skipif(
    sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file(),
    reason="requires the enforced macOS host boundary",
)
@pytest.mark.parametrize("allow_report", [False, True])
@pytest.mark.parametrize("exclusive", [False, True])
def test_real_host_boundary_enforces_declared_scope_and_nested_control_paths(tmp_path, allow_report, exclusive):
    root = (tmp_path / "candidate").resolve()
    root.mkdir()
    source = root / "app.py"
    source.write_text("source")
    control = root / ".echelon"
    control.mkdir()
    secret = control / "config.yml"
    secret.write_text("control")
    report = root / "review.json"
    report_temp = root / ".review.json.tmp"
    other = root / "other.json"
    other_temp = root / ".other.json.tmp"
    alias = tmp_path / "source-alias"
    alias.symlink_to(source)
    command = _command(_request(
        root, exclusive=exclusive,
        write_paths=[report] if allow_report else [], forbidden=[control],
    ))
    probe = '''
import json, pathlib, sys
result = {}
for key, path, action in json.loads(sys.argv[1]):
    try:
        if action == "read": pathlib.Path(path).read_text()
        else: pathlib.Path(path).write_text("changed")
        result[key] = True
    except PermissionError:
        result[key] = False
print(json.dumps(result))
'''
    operations = [
        ("source_read", str(source), "read"),
        ("source_write", str(source), "write"),
        ("alias_write", str(alias), "write"),
        ("control_read", str(secret), "read"),
        ("control_write", str(secret), "write"),
        ("report_write", str(report), "write"),
        ("report_temp_write", str(report_temp), "write"),
        ("other_write", str(other), "write"),
        ("other_temp_write", str(other_temp), "write"),
    ]
    result = subprocess.run(
        [*command[:3], sys.executable, "-c", probe, json.dumps(operations)],
        cwd=root, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "source_read": True, "source_write": not exclusive, "alias_write": not exclusive,
        "control_read": False, "control_write": False,
        "report_write": allow_report or not exclusive,
        "report_temp_write": allow_report or not exclusive,
        "other_write": not exclusive,
        "other_temp_write": not exclusive,
    }
    assert source.read_text() == ("source" if exclusive else "changed")
    assert secret.read_text() == "control"
    assert other.exists() is not exclusive


@pytest.mark.skipif(
    sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file(),
    reason="requires the enforced macOS host boundary",
)
@pytest.mark.parametrize("reject", [False, True])
def test_claude_delivery_runs_real_adapter_stream_and_host_boundary(slice_project, monkeypatch, reject):
    from harness.llm_provider import AICodingCliProvider
    from tests.unit.test_delivery_slice_runner import _run

    config = HarnessConfig()
    config.llm.cli = "claude"
    provider = AICodingCliProvider(config)
    backend = provider._backend
    real_stream = backend._run_stream_json
    seen = []
    # Replace only the external model process, retaining the generated sandbox,
    # real stream parser, provider facade, role loading and delivery controller.
    probe = '''
import json, pathlib, sys
assignment = json.loads(sys.argv[1])
source = pathlib.Path("app.py")
if assignment["step"] == "implementer":
    source.write_text("def hello(): return 'hello'\\n")
else:
    assert "hello" in source.read_text()
    try: source.write_text("tampered")
    except PermissionError: pass
    else: raise AssertionError("reviewer wrote source")
verdict = {"implementer": "DONE", "spec_guard": "PASS",
           "code_reviewer": "APPROVED", "test_guardian": "PASS"}[assignment["step"]]
findings = []
if sys.argv[2] == "reject" and assignment["step"] == "spec_guard":
    verdict, findings = "FAIL", ["app.py:1 deliberately rejected by test reviewer"]
payload = dict(assignment, verdict=verdict, summary="Inspected actual candidate", findings=findings)
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": json.dumps(payload)}]}}))
print(json.dumps({"type": "result", "usage": {"input_tokens": 3, "output_tokens": 4}}))
'''

    def local_process(command, request):
        assignment = request.metadata["delivery_assignment"]
        seen.append(assignment["step"])
        assert command[:2] == ["/usr/bin/sandbox-exec", "-p"]
        if assignment["step"] != "implementer":
            assert command[command.index("--tools") + 1] == "Read,Glob,Grep"
        else:
            assert "--tools" not in command
        return real_stream(
            [*command[:3], sys.executable, "-c", probe, json.dumps(assignment),
             "reject" if reject else "accept"], request,
        )

    monkeypatch.setattr(backend, "_run_stream_json", local_process)
    result = _run(slice_project, provider)
    if reject:
        assert not result.succeeded
        assert "repair_limit" in result.reason
        assert seen == ["implementer", "spec_guard"] * 3
        assert result.token_usage == 42
    else:
        assert result.succeeded, result.reason
        assert result.task_ids == ["T-001"]
        assert seen == ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
        assert result.token_usage == 28
    assert "- [ ] T-001" in (slice_project[1] / "tasks.md").read_text()
