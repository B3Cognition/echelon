"""Tests for CLI host-side LLM tool policy wiring."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest

from echelon import cli
from harness.config import HarnessConfig, LlmConfig
from harness.llm_tool_policy import LlmToolPolicy


@pytest.mark.unit
def test_run_claude_streaming_uses_default_tool_policy_without_dangerous_bypass(tmp_path: Path) -> None:
    captured_cmd: list[str] = []

    class FakeProcess:
        stdin = io.BytesIO()
        stdout = io.BytesIO(b'{"type":"result","is_error":false,"num_turns":0,"duration_ms":0}\n')
        returncode = 0

        def wait(self) -> int:
            return self.returncode

    def fake_popen(cmd, **kwargs):
        captured_cmd.extend(cmd)
        return FakeProcess()

    with patch("echelon.cli.subprocess.Popen", side_effect=fake_popen), pytest.raises(SystemExit) as exc:
        cli._run_claude_streaming(
            "claude",
            "Do the work.",
            tmp_path,
            tool_policy=LlmToolPolicy(),
        )

    assert exc.value.code == 0
    assert "--dangerously-skip-permissions" not in captured_cmd
    assert "--output-format" in captured_cmd


@pytest.mark.unit
def test_dispatch_skill_command_routes_codex_through_ai_cli_provider(
    monkeypatch,
    tmp_path: Path,
) -> None:
    skill_dir = tmp_path / ".claude" / "skills" / "speckit-echelon-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.md").write_text(
        "---\nname: echelon.review\n---\nreview $ARGUMENTS\n",
        encoding="utf-8",
    )
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="codex"),
    )
    calls = []

    class FakeProvider:
        def __init__(self, loaded_config):
            assert loaded_config is config

        def exec_prompt(self, worktree_path, prompt):
            calls.append((worktree_path, prompt))
            return 0

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ECHELON_LLM", "codex")
    monkeypatch.setattr("echelon.cli.load_config", lambda project_dir, squad_only=True: config)
    monkeypatch.setattr("echelon.cli.AICodingCliProvider", FakeProvider)

    with pytest.raises(SystemExit) as exc:
        cli._dispatch_skill_command("review", ["005", "pr_url=https://github.com/org/repo/pull/1"])

    assert exc.value.code == 0
    assert calls
    assert calls[0][0] == str(tmp_path)
    assert "review 005 pr_url=https://github.com/org/repo/pull/1" in calls[0][1]


@pytest.mark.unit
def test_dispatch_skill_command_routes_copilot_through_ai_cli_provider(monkeypatch, tmp_path: Path) -> None:
    skill_dir = tmp_path / ".github" / "agents"
    skill_dir.mkdir(parents=True)
    (skill_dir / "speckit.echelon.review.agent.md").write_text(
        "---\nname: speckit.echelon.review\n---\nreview $ARGUMENTS\n",
        encoding="utf-8",
    )
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="copilot"),
    )
    calls = []

    class FakeProvider:
        def __init__(self, loaded_config):
            assert loaded_config is config

        def exec_prompt(self, worktree_path, prompt):
            calls.append((worktree_path, prompt))
            return 0

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ECHELON_LLM", "copilot")
    monkeypatch.setattr("echelon.cli.load_config", lambda project_dir, squad_only=True: config)
    monkeypatch.setattr("echelon.cli.AICodingCliProvider", FakeProvider)

    with pytest.raises(SystemExit) as exc:
        cli._dispatch_skill_command("review", ["005", "pr_url=https://github.com/org/repo/pull/1"])

    assert exc.value.code == 0
    assert calls
    assert "review 005 pr_url=https://github.com/org/repo/pull/1" in calls[0][1]
