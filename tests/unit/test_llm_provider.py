"""Tests for ClaudeCliProvider."""
from __future__ import annotations
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from harness.llm_provider import ClaudeCliProvider
from harness.config import HarnessConfig, LlmConfig
from harness.build_result import BuildResult


def _config(config_dir=None, timeout_ms=1_200_000):
    return HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(config_dir=config_dir, timeout_ms=timeout_ms),
    )


def _completed_process(returncode=0, stdout="done", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


@pytest.mark.unit
class TestClaudeCliProvider:

    def test_exec_build_calls_claude_p(self, tmp_path):
        status_file = tmp_path / "status.json"
        status_file.write_text('{"status": "done"}')

        with patch("harness.llm_provider.subprocess.run",
                   return_value=_completed_process()) as mock_run, \
             patch("harness.llm_provider.ClaudeCliProvider._status_file_path",
                   return_value=status_file), \
             patch("harness.llm_provider.shutil.which", return_value="claude"):
            provider = ClaudeCliProvider(_config())
            result = provider.exec_build("/wt/001", "build this")

        args = mock_run.call_args
        assert args[0][0][0] == "claude"
        assert args[0][0][1] == "-p"
        assert result.succeeded is True

    def test_exec_build_sets_status_file_env(self, tmp_path):
        status_file = tmp_path / "status.json"
        status_file.write_text('{"status": "done"}')
        captured_env = {}

        def fake_run(cmd, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return _completed_process()

        with patch("harness.llm_provider.subprocess.run", side_effect=fake_run), \
             patch("harness.llm_provider.ClaudeCliProvider._status_file_path",
                   return_value=status_file):
            ClaudeCliProvider(_config()).exec_build("/wt/001", "build this")

        assert "HARNESS_BUILD_STATUS_FILE" in captured_env

    def test_exec_build_sets_claude_config_dir_when_configured(self, tmp_path):
        status_file = tmp_path / "status.json"
        status_file.write_text('{"status": "done"}')
        captured_env = {}

        def fake_run(cmd, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return _completed_process()

        with patch("harness.llm_provider.subprocess.run", side_effect=fake_run), \
             patch("harness.llm_provider.ClaudeCliProvider._status_file_path",
                   return_value=status_file):
            ClaudeCliProvider(_config(config_dir="/home/user/.config/claude-work"))\
                .exec_build("/wt/001", "build this")

        assert captured_env.get("CLAUDE_CONFIG_DIR") == "/home/user/.config/claude-work"

    def test_exec_build_no_config_dir_when_not_set(self, tmp_path):
        status_file = tmp_path / "status.json"
        status_file.write_text('{"status": "done"}')
        captured_env = {}

        def fake_run(cmd, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return _completed_process()

        with patch("harness.llm_provider.subprocess.run", side_effect=fake_run), \
             patch("harness.llm_provider.ClaudeCliProvider._status_file_path",
                   return_value=status_file):
            ClaudeCliProvider(_config()).exec_build("/wt/001", "build this")

        assert "CLAUDE_CONFIG_DIR" not in captured_env

    def test_exec_build_returns_impasse_from_status_file(self, tmp_path):
        status_file = tmp_path / "status.json"
        status_file.write_text('{"status": "impasse", "impasse_file": "codegen-impasse.md"}')

        with patch("harness.llm_provider.subprocess.run",
                   return_value=_completed_process()), \
             patch("harness.llm_provider.ClaudeCliProvider._status_file_path",
                   return_value=status_file):
            result = ClaudeCliProvider(_config()).exec_build("/wt/001", "build this")

        assert result.is_impasse is True
        assert result.impasse_file == "codegen-impasse.md"

    def test_exec_build_returns_unknown_when_status_file_missing(self, tmp_path):
        missing = tmp_path / "missing.json"

        with patch("harness.llm_provider.subprocess.run",
                   return_value=_completed_process()), \
             patch("harness.llm_provider.ClaudeCliProvider._status_file_path",
                   return_value=missing):
            result = ClaudeCliProvider(_config()).exec_build("/wt/001", "build this")

        assert result.status == "unknown"

    def test_exec_build_uses_worktree_as_cwd(self, tmp_path):
        status_file = tmp_path / "status.json"
        status_file.write_text('{"status": "done"}')
        captured_cwd = []

        def fake_run(cmd, **kwargs):
            captured_cwd.append(kwargs.get("cwd"))
            return _completed_process()

        with patch("harness.llm_provider.subprocess.run", side_effect=fake_run), \
             patch("harness.llm_provider.ClaudeCliProvider._status_file_path",
                   return_value=status_file):
            ClaudeCliProvider(_config()).exec_build("/wt/001", "build this")

        assert captured_cwd[0] == "/wt/001"

    def test_exec_feedback_delegates_to_exec_build(self, tmp_path):
        status_file = tmp_path / "status.json"
        status_file.write_text('{"status": "done"}')

        with patch("harness.llm_provider.subprocess.run",
                   return_value=_completed_process()) as mock_run, \
             patch("harness.llm_provider.ClaudeCliProvider._status_file_path",
                   return_value=status_file), \
             patch("harness.llm_provider.shutil.which", return_value="claude"):
            result = ClaudeCliProvider(_config()).exec_feedback("/wt/001", "fix this")

        args = mock_run.call_args
        assert args[0][0][0] == "claude"
        assert args[0][0][1] == "-p"
        assert result.succeeded is True

    def test_exec_build_returns_timeout_result_on_timeout(self):
        import subprocess as sp
        with patch("harness.llm_provider.subprocess.run",
                   side_effect=sp.TimeoutExpired(cmd=["claude"], timeout=1.0)):
            result = ClaudeCliProvider(_config()).exec_build("/wt/001", "build this")
        assert result.status == "timeout"
        assert result.exit_code == -1
