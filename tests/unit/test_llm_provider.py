"""Tests for AICodingCliProvider (formerly ClaudeCliProvider)."""
from __future__ import annotations
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from harness.llm_provider import AICodingCliProvider
from harness.config import HarnessConfig, LlmConfig
from harness.build_result import BuildResult


def _config(config_dir=None, timeout_ms=1_200_000, cli="claude"):
    return HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(config_dir=config_dir, timeout_ms=timeout_ms, cli=cli),
    )


def _mock_streaming(returncode=0, status=None):
    """Patch _run_streaming to return immediately.

    If status is given (e.g. {"status": "done"}), write it to the
    HARNESS_BUILD_STATUS_FILE env var path — mirroring what build-8-finalize
    does in a real build. Tests that check result.succeeded must pass a status.
    """
    if status is None:
        return patch(
            "harness.llm_provider.AICodingCliProvider._run_streaming",
            return_value=returncode,
        )

    status_json = json.dumps(status)

    def _fake(cmd, cwd, env, start):
        path = env.get("HARNESS_BUILD_STATUS_FILE")
        if path:
            Path(path).write_text(status_json)
        return returncode

    return patch(
        "harness.llm_provider.AICodingCliProvider._run_streaming",
        side_effect=_fake,
    )


def _mock_plain(returncode=0, status=None):
    """Patch _run_plain to return immediately, optionally writing status."""
    if status is None:
        return patch(
            "harness.llm_provider.AICodingCliProvider._run_plain",
            return_value=returncode,
        )

    status_json = json.dumps(status)

    def _fake(cmd, cwd, env, start):
        path = env.get("HARNESS_BUILD_STATUS_FILE")
        if path:
            Path(path).write_text(status_json)
        return returncode

    return patch(
        "harness.llm_provider.AICodingCliProvider._run_plain",
        side_effect=_fake,
    )


@pytest.mark.unit
class TestAICodingCliProvider:

    def test_exec_build_calls_claude_p(self, tmp_path):
        with _mock_streaming(status={"status": "done"}) as mock_stream, \
             patch("harness.llm_provider.shutil.which", return_value="claude"):
            provider = AICodingCliProvider(_config())
            result = provider.exec_build(str(tmp_path), "build this")

        cmd_passed = mock_stream.call_args[0][0]
        assert cmd_passed[0] == "claude"
        assert "-p" in cmd_passed
        assert result.succeeded is True

    def test_exec_build_uses_stream_json_for_claude(self, tmp_path):
        with _mock_streaming() as mock_stream:
            AICodingCliProvider(_config()).exec_build(str(tmp_path), "build this")

        cmd_passed = mock_stream.call_args[0][0]
        assert "--output-format" in cmd_passed
        assert "stream-json" in cmd_passed

    def test_exec_build_sets_status_file_env(self, tmp_path):
        captured_env = {}

        def fake_streaming(cmd, cwd, env, start):
            captured_env.update(env)
            return 0

        with patch("harness.llm_provider.AICodingCliProvider._run_streaming",
                   side_effect=fake_streaming):
            AICodingCliProvider(_config()).exec_build(str(tmp_path), "build this")

        assert "HARNESS_BUILD_STATUS_FILE" in captured_env

    def test_exec_build_sets_claude_config_dir_when_configured(self, tmp_path):
        captured_env = {}

        def fake_streaming(cmd, cwd, env, start):
            captured_env.update(env)
            return 0

        with patch("harness.llm_provider.AICodingCliProvider._run_streaming",
                   side_effect=fake_streaming):
            AICodingCliProvider(_config(config_dir="/home/user/.config/claude-work"))\
                .exec_build(str(tmp_path), "build this")

        assert captured_env.get("CLAUDE_CONFIG_DIR") == "/home/user/.config/claude-work"

    def test_exec_build_no_config_dir_when_not_set(self, tmp_path):
        captured_env = {}

        def fake_streaming(cmd, cwd, env, start):
            captured_env.update(env)
            return 0

        with patch("harness.llm_provider.AICodingCliProvider._run_streaming",
                   side_effect=fake_streaming):
            AICodingCliProvider(_config()).exec_build(str(tmp_path), "build this")

        assert "CLAUDE_CONFIG_DIR" not in captured_env

    def test_exec_build_returns_impasse_from_status_file(self, tmp_path):
        with _mock_streaming(status={"status": "impasse", "impasse_file": "codegen-impasse.md"}):
            result = AICodingCliProvider(_config()).exec_build(str(tmp_path), "build this")

        assert result.is_impasse is True
        assert result.impasse_file == "codegen-impasse.md"

    def test_exec_build_returns_unknown_when_status_file_missing(self, tmp_path):
        # Mock writes nothing — simulates COMMANDER blocking before finalize
        with _mock_streaming():
            result = AICodingCliProvider(_config()).exec_build(str(tmp_path), "build this")

        assert result.status == "unknown"
        assert result.succeeded is False

    def test_exec_build_uses_worktree_as_cwd(self, tmp_path):
        captured_cwd = []

        def fake_streaming(cmd, cwd, env, start):
            captured_cwd.append(cwd)
            return 0

        with patch("harness.llm_provider.AICodingCliProvider._run_streaming",
                   side_effect=fake_streaming):
            AICodingCliProvider(_config()).exec_build("/wt/001", "build this")

        assert captured_cwd[0] == "/wt/001"

    def test_exec_feedback_delegates_to_exec_build(self, tmp_path):
        with _mock_streaming(status={"status": "done"}) as mock_stream, \
             patch("harness.llm_provider.shutil.which", return_value="claude"):
            result = AICodingCliProvider(_config()).exec_feedback(str(tmp_path), "fix this")

        cmd_passed = mock_stream.call_args[0][0]
        assert cmd_passed[0] == "claude"
        assert "-p" in cmd_passed
        assert result.succeeded is True

    def test_exec_build_returns_timeout_result_on_timeout(self, tmp_path):
        with patch("harness.llm_provider.AICodingCliProvider._run_streaming",
                   return_value=None):
            result = AICodingCliProvider(_config()).exec_build(str(tmp_path), "build this")

        assert result.status == "timeout"
        assert result.exit_code == -1

    def test_non_claude_cli_uses_plain_run(self, tmp_path):
        """copilot/opencode use _run_plain, not _run_streaming."""
        with _mock_plain(status={"status": "done"}) as mock_plain, \
             patch("harness.llm_provider.AICodingCliProvider._run_streaming") as mock_stream:
            AICodingCliProvider(_config(cli="copilot")).exec_build(str(tmp_path), "build this")

        mock_stream.assert_not_called()
        mock_plain.assert_called_once()
