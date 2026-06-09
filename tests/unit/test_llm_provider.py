"""Tests for AICodingCliProvider (formerly ClaudeCliProvider)."""
from __future__ import annotations
from unittest.mock import patch
import pytest
from harness.llm_provider import AICodingCliProvider
from harness.config import HarnessConfig, LlmConfig


def _config(config_dir=None, timeout_ms=1_200_000, cli="claude"):
    return HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(config_dir=config_dir, timeout_ms=timeout_ms, cli=cli),
    )


def _mock_streaming(returncode=0):
    return patch(
        "harness.llm_provider.AICodingCliProvider._run_streaming",
        return_value=returncode,
    )


def _mock_plain(returncode=0):
    return patch(
        "harness.llm_provider.AICodingCliProvider._run_plain",
        return_value=returncode,
    )


@pytest.mark.unit
class TestAICodingCliProvider:

    def test_provider_has_no_verify_spec_orchestration_method(self):
        assert not hasattr(AICodingCliProvider, "exec_verify_spec")

    def test_provider_has_no_build_or_feedback_orchestration_methods(self):
        assert not hasattr(AICodingCliProvider, "exec_build")
        assert not hasattr(AICodingCliProvider, "exec_feedback")

    def test_exec_prompt_runs_generic_prompt_without_build_status_file(self, tmp_path):
        captured_env = {}

        def fake_streaming(cmd, cwd, env, start):
            captured_env.update(env)
            return 0

        with patch("harness.llm_provider.AICodingCliProvider._run_streaming",
                   side_effect=fake_streaming) as mock_stream:
            result = AICodingCliProvider(_config()).exec_prompt(
                str(tmp_path), "run generic prompt"
            )

        assert result == 0
        cmd_passed = mock_stream.call_args[0][0]
        assert "-p" in cmd_passed
        assert "run generic prompt" in cmd_passed
        assert "HARNESS_BUILD_STATUS_FILE" not in captured_env

    def test_exec_prompt_calls_claude_p(self, tmp_path):
        with _mock_streaming() as mock_stream, \
             patch("harness.llm_provider.shutil.which", return_value="claude"):
            provider = AICodingCliProvider(_config())
            result = provider.exec_prompt(str(tmp_path), "build this")

        cmd_passed = mock_stream.call_args[0][0]
        assert cmd_passed[0] == "claude"
        assert "-p" in cmd_passed
        assert result == 0

    def test_exec_prompt_uses_stream_json_for_claude(self, tmp_path):
        with _mock_streaming() as mock_stream:
            AICodingCliProvider(_config()).exec_prompt(str(tmp_path), "build this")

        cmd_passed = mock_stream.call_args[0][0]
        assert "--output-format" in cmd_passed
        assert "stream-json" in cmd_passed

    def test_exec_prompt_sets_claude_config_dir_when_configured(self, tmp_path):
        captured_env = {}

        def fake_streaming(cmd, cwd, env, start):
            captured_env.update(env)
            return 0

        with patch("harness.llm_provider.AICodingCliProvider._run_streaming",
                   side_effect=fake_streaming):
            AICodingCliProvider(_config(config_dir="/home/user/.config/claude-work"))\
                .exec_prompt(str(tmp_path), "build this")

        assert captured_env.get("CLAUDE_CONFIG_DIR") == "/home/user/.config/claude-work"

    def test_exec_prompt_no_config_dir_when_not_set(self, tmp_path):
        captured_env = {}

        def fake_streaming(cmd, cwd, env, start):
            captured_env.update(env)
            return 0

        with patch("harness.llm_provider.AICodingCliProvider._run_streaming",
                   side_effect=fake_streaming):
            AICodingCliProvider(_config()).exec_prompt(str(tmp_path), "build this")

        assert "CLAUDE_CONFIG_DIR" not in captured_env

    def test_exec_prompt_uses_worktree_as_cwd(self, tmp_path):
        captured_cwd = []

        def fake_streaming(cmd, cwd, env, start):
            captured_cwd.append(cwd)
            return 0

        with patch("harness.llm_provider.AICodingCliProvider._run_streaming",
                   side_effect=fake_streaming):
            AICodingCliProvider(_config()).exec_prompt("/wt/001", "build this")

        assert captured_cwd[0] == "/wt/001"

    def test_exec_prompt_returns_minus_one_on_timeout(self, tmp_path):
        with patch("harness.llm_provider.AICodingCliProvider._run_streaming",
                   return_value=None):
            result = AICodingCliProvider(_config()).exec_prompt(str(tmp_path), "build this")

        assert result == -1

    def test_non_claude_cli_uses_plain_run(self, tmp_path):
        """copilot/opencode/codex use _run_plain, not _run_streaming."""
        with _mock_plain() as mock_plain, \
             patch("harness.llm_provider.AICodingCliProvider._run_streaming") as mock_stream:
            AICodingCliProvider(_config(cli="copilot")).exec_prompt(str(tmp_path), "build this")

        mock_stream.assert_not_called()
        mock_plain.assert_called_once()

    def test_codex_cli_uses_codex_exec(self, tmp_path):
        with _mock_plain() as mock_plain, \
             patch("harness.llm_provider.shutil.which", return_value="codex"):
            AICodingCliProvider(_config(cli="codex")).exec_prompt(str(tmp_path), "build this")

        cmd_passed = mock_plain.call_args[0][0]
        assert cmd_passed == [
            "codex",
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "build this",
        ]
