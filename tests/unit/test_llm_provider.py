"""Tests for AICodingCliProvider (formerly ClaudeCliProvider)."""
from __future__ import annotations
import io
import json
from unittest.mock import patch
import pytest
from harness.llm_provider import AICodingCliProvider
from harness.config import HarnessConfig, LlmConfig
from harness.llm_tool_policy import LlmToolPolicy


def _config(config_dir=None, timeout_ms=1_200_000, cli="claude", tool_policy=None):
    return HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(
            config_dir=config_dir,
            timeout_ms=timeout_ms,
            cli=cli,
            tool_policy=tool_policy or LlmToolPolicy(),
        ),
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
        assert "run generic prompt" in cmd_passed[cmd_passed.index("-p") + 1]
        assert "HARNESS_BUILD_STATUS_FILE" not in captured_env

    def test_exec_prompt_injects_effective_tool_policy_preamble(self, tmp_path):
        with _mock_streaming() as mock_stream:
            AICodingCliProvider(_config()).exec_prompt(str(tmp_path), "build this")

        cmd_passed = mock_stream.call_args[0][0]
        prompt = cmd_passed[cmd_passed.index("-p") + 1]
        assert prompt.startswith("## Effective Host Tool Policy")
        assert "Unsafe host execution bypass: disabled" in prompt
        assert "build this" in prompt

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

    def test_exec_prompt_does_not_use_dangerous_claude_permissions_by_default(self, tmp_path):
        with _mock_streaming() as mock_stream:
            AICodingCliProvider(_config()).exec_prompt(str(tmp_path), "build this")

        cmd_passed = mock_stream.call_args[0][0]
        assert "--dangerously-skip-permissions" not in cmd_passed

    def test_exec_prompt_uses_dangerous_claude_permissions_when_approved(self, tmp_path):
        policy = LlmToolPolicy(
            allow_unsafe_host_execution=True,
            approval_reason="Operator approved disposable worktree after sandbox review.",
        )

        with _mock_streaming() as mock_stream:
            AICodingCliProvider(_config(tool_policy=policy)).exec_prompt(str(tmp_path), "build this")

        cmd_passed = mock_stream.call_args[0][0]
        assert "--dangerously-skip-permissions" in cmd_passed

    def test_exec_prompt_disallows_claude_native_task_planning_tools(self, tmp_path):
        with _mock_streaming() as mock_stream:
            AICodingCliProvider(_config()).exec_prompt(str(tmp_path), "build this")

        cmd_passed = mock_stream.call_args[0][0]
        assert "--disallowedTools" in cmd_passed
        disallowed = cmd_passed[cmd_passed.index("--disallowedTools") + 1]
        assert "TaskCreate" in disallowed
        assert "TaskUpdate" in disallowed

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

    def test_streaming_captures_result_error_text(self, tmp_path):
        provider = AICodingCliProvider(_config())

        class FakeProcess:
            stdout = io.BytesIO(
                (
                    json.dumps(
                        {
                            "type": "result",
                            "is_error": True,
                            "result": "You've hit your session limit · resets 9:10pm",
                            "num_turns": 1,
                            "duration_ms": 0,
                        }
                    )
                    + "\n"
                ).encode()
            )
            returncode = 1

            def kill(self):
                return None

            def wait(self):
                return self.returncode

        with patch("harness.llm_provider.subprocess.Popen", return_value=FakeProcess()):
            result = provider.exec_prompt(str(tmp_path), "build this")

        assert result == 1
        assert "session limit" in provider.last_stdout
        assert "resets 9:10pm" in provider.last_stdout

    def test_streaming_captures_token_usage_from_result_event(self, tmp_path):
        provider = AICodingCliProvider(_config())

        class FakeProcess:
            stdout = io.BytesIO(
                (
                    json.dumps(
                        {
                            "type": "assistant",
                            "message": {
                                "content": [
                                    {"type": "text", "text": "building slice"}
                                ]
                            },
                        }
                    )
                    + "\n"
                    + json.dumps(
                        {
                            "type": "result",
                            "is_error": False,
                            "result": "ok",
                            "num_turns": 1,
                            "duration_ms": 0,
                            "usage": {
                                "input_tokens": 1200,
                                "output_tokens": 300,
                                "cache_creation_input_tokens": 50,
                                "cache_read_input_tokens": 25,
                            },
                        }
                    )
                    + "\n"
                ).encode()
            )
            returncode = 0

            def kill(self):
                return None

            def wait(self):
                return self.returncode

        with patch("harness.llm_provider.subprocess.Popen", return_value=FakeProcess()):
            result = provider.exec_prompt(str(tmp_path), "build this")

        assert result == 0
        assert provider.last_token_usage == 1575

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
        assert cmd_passed[:2] == ["codex", "exec"]
        assert "--dangerously-bypass-approvals-and-sandbox" not in cmd_passed
        assert "Effective Host Tool Policy" in cmd_passed[-1]
