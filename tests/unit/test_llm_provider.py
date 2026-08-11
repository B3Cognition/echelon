"""Tests for AICodingCliProvider facade."""
from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest

from harness.ai_cli_backend import CliRunResult
from harness.config import HarnessConfig, LlmConfig
from harness.llm_provider import AICodingCliProvider
from harness.llm_tool_policy import LlmToolPolicy


def _config(config_dir=None, timeout_ms=1_200_000, cli="claude", tool_policy=None):
    llm_kwargs = {}
    if cli == "openai-compatible":
        llm_kwargs.update(
            base_url="http://127.0.0.1:8000/v1",
            model="local-model",
        )
    return HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(
            config_dir=config_dir,
            timeout_ms=timeout_ms,
            cli=cli,
            tool_policy=tool_policy or LlmToolPolicy(),
            **llm_kwargs,
        ),
    )


class _FakeStreamProcess:
    def __init__(self, lines: list[dict] | None = None, returncode: int = 0) -> None:
        payload = ""
        for line in lines or []:
            payload += json.dumps(line) + "\n"
        self.stdout = io.BytesIO(payload.encode())
        self.returncode = returncode
        self.killed = False

    def kill(self):
        self.killed = True

    def wait(self):
        return self.returncode


def _patch_claude_popen(lines: list[dict] | None = None, returncode: int = 0):
    return patch(
        "harness.ai_cli_backends.claude.subprocess.Popen",
        return_value=_FakeStreamProcess(lines, returncode),
    )


@pytest.mark.unit
class TestAICodingCliProvider:

    def test_provider_retains_normalized_invocation_metadata(self, tmp_path):
        provider = AICodingCliProvider(_config(cli="codex"))
        backend_result = CliRunResult(
            exit_code=0,
            stdout="done",
            stderr="",
            token_usage=0,
            metadata={"request_model": "gpt-5.6-luna"},
        )

        with patch.object(provider._backend, "run_prompt", return_value=backend_result):
            provider.run_prompt_result(
                str(tmp_path),
                "build this",
                request_metadata={
                    "prompt_metadata": {
                        "model_tier": "fast",
                        "effort": "low",
                    }
                },
            )

        assert provider.last_invocation_metadata == {
            "provider": "codex",
            "model": "gpt-5.6-luna",
            "profile": "fast",
            "effort": "low",
        }

    @pytest.mark.parametrize(
        "cli",
        ("codex", "copilot", "opencode", "openai-compatible", "plain-cli"),
    )
    @pytest.mark.parametrize("method", ("run_prompt_result", "run_agent_result"))
    def test_review_triage_execution_profile_rejects_non_claude_backends(
        self, tmp_path, cli, method
    ):
        provider = AICodingCliProvider(_config(cli=cli))
        backend_method = "run_agent" if method == "run_agent_result" else "run_prompt"

        with patch.object(provider._backend, backend_method) as run_backend:
            result = getattr(provider, method)(
                str(tmp_path),
                "triage review comments",
                request_metadata={"execution_profile": "review_triage_v1"},
            )

        assert result.exit_code == 125
        assert result.stdout == ""
        assert result.stderr == (
            "execution profile review_triage_v1 requires claude; "
            f"configured provider is {cli}"
        )
        assert result.metadata == {"unsupported_execution_profile": "review_triage_v1"}
        run_backend.assert_not_called()

    @pytest.mark.parametrize("method", ("run_prompt_result", "run_agent_result"))
    def test_execution_profile_rejects_unknown_profiles_before_backend_launch(
        self, tmp_path, method
    ):
        provider = AICodingCliProvider(_config(cli="claude"))
        backend_method = "run_agent" if method == "run_agent_result" else "run_prompt"

        with patch.object(provider._backend, backend_method) as run_backend:
            result = getattr(provider, method)(
                str(tmp_path),
                "do not launch",
                request_metadata={"execution_profile": "unrecognized_profile"},
            )

        assert result.exit_code == 125
        assert result.metadata == {
            "unsupported_execution_profile": "unrecognized_profile"
        }
        run_backend.assert_not_called()

    @pytest.mark.parametrize("method", ("run_prompt_result", "run_agent_result"))
    @pytest.mark.parametrize("profile", (False, 0, [], {}))
    def test_execution_profile_rejects_non_string_values_before_backend_launch(
        self, tmp_path, method, profile
    ):
        provider = AICodingCliProvider(_config(cli="claude"))
        backend_method = "run_agent" if method == "run_agent_result" else "run_prompt"

        with patch.object(provider._backend, backend_method) as run_backend:
            result = getattr(provider, method)(
                str(tmp_path),
                "do not launch",
                request_metadata={"execution_profile": profile},
            )

        assert result.exit_code == 125
        assert "execution profile must be a string" in result.stderr
        run_backend.assert_not_called()

    @pytest.mark.parametrize(
        ("cli", "expected"),
        [
            ("claude", True),
            ("openai-compatible", True),
            ("codex", False),
            ("copilot", False),
            ("opencode", False),
        ],
    )
    def test_provider_reports_workspace_synthesis_boundary(self, cli, expected):
        with patch(
            "harness.llm_provider.host_workspace_synthesis_boundary_available",
            return_value=True,
        ):
            provider = AICodingCliProvider(_config(cli=cli))

        assert provider.enforces_workspace_synthesis_boundary is expected

    def test_unsafe_claude_provider_keeps_host_workspace_boundary(self):
        with patch(
            "harness.llm_provider.host_workspace_synthesis_boundary_available",
            return_value=True,
        ):
            provider = AICodingCliProvider(
                _config(
                    cli="claude",
                    tool_policy=LlmToolPolicy(
                        allow_unsafe_host_execution=True,
                        approval_reason="approved test bypass",
                    ),
                )
            )

            assert provider.enforces_workspace_synthesis_boundary is True

    def test_claude_provider_requires_host_workspace_boundary(self):
        with patch(
            "harness.llm_provider.host_workspace_synthesis_boundary_available",
            return_value=False,
        ):
            provider = AICodingCliProvider(_config(cli="claude"))
            assert provider.enforces_workspace_synthesis_boundary is False

    def test_provider_has_no_verify_spec_orchestration_method(self):
        assert not hasattr(AICodingCliProvider, "exec_verify_spec")

    def test_provider_has_no_build_or_feedback_orchestration_methods(self):
        assert not hasattr(AICodingCliProvider, "exec_build")
        assert not hasattr(AICodingCliProvider, "exec_feedback")

    def test_provider_exposes_default_cli_build_and_artifact_capabilities(self):
        from harness.provider_capability import ProviderCapability

        provider = AICodingCliProvider(_config(cli="claude"))

        assert provider.capabilities == frozenset(
            {ProviderCapability.ARTIFACT, ProviderCapability.BUILD}
        )

    def test_openai_compatible_provider_is_artifact_only(self):
        from harness.provider_capability import ProviderCapability

        provider = AICodingCliProvider(
            _config(
                cli="openai-compatible",
                timeout_ms=600_000,
            )
        )

        assert provider.capabilities == frozenset({ProviderCapability.ARTIFACT})

    def test_exec_prompt_runs_generic_prompt_without_build_status_file(self, tmp_path):
        with _patch_claude_popen() as popen:
            result = AICodingCliProvider(_config()).exec_prompt(
                str(tmp_path), "run generic prompt"
            )

        assert result == 0
        cmd_passed = popen.call_args.args[0]
        env_passed = popen.call_args.kwargs["env"]
        assert "-p" in cmd_passed
        assert "run generic prompt" in cmd_passed[cmd_passed.index("-p") + 1]
        assert "HARNESS_BUILD_STATUS_FILE" not in env_passed

    def test_exec_prompt_injects_effective_tool_policy_preamble(self, tmp_path):
        with _patch_claude_popen() as popen:
            AICodingCliProvider(_config()).exec_prompt(str(tmp_path), "build this")

        cmd_passed = popen.call_args.args[0]
        prompt = cmd_passed[cmd_passed.index("-p") + 1]
        assert prompt.startswith("## Effective Host Tool Policy")
        assert "Unsafe host execution bypass: disabled" in prompt
        assert "build this" in prompt

    def test_exec_prompt_calls_claude_p(self, tmp_path):
        with _patch_claude_popen() as popen, \
             patch("harness.ai_cli_backends.claude.shutil.which", return_value="claude"):
            provider = AICodingCliProvider(_config())
            result = provider.exec_prompt(str(tmp_path), "build this")

        cmd_passed = popen.call_args.args[0]
        assert cmd_passed[0] == "claude"
        assert "-p" in cmd_passed
        assert result == 0

    def test_run_agent_result_passes_prompt_metadata_to_backend(self, tmp_path):
        with _patch_claude_popen() as popen:
            provider = AICodingCliProvider(_config())
            result = provider.run_agent_result(
                str(tmp_path),
                "build this",
                request_metadata={
                    "prompt_metadata": {
                        "model": "claude-opus-4-1",
                    }
                },
            )

        assert result.exit_code == 0
        cmd_passed = popen.call_args.args[0]
        assert "--model" in cmd_passed
        model_index = cmd_passed.index("--model")
        assert cmd_passed[model_index + 1] == "claude-opus-4-1"

    def test_exec_prompt_uses_stream_json_for_claude(self, tmp_path):
        with _patch_claude_popen() as popen:
            AICodingCliProvider(_config()).exec_prompt(str(tmp_path), "build this")

        cmd_passed = popen.call_args.args[0]
        assert "--output-format" in cmd_passed
        assert "stream-json" in cmd_passed

    def test_exec_prompt_does_not_use_dangerous_claude_permissions_by_default(self, tmp_path):
        with _patch_claude_popen() as popen:
            AICodingCliProvider(_config()).exec_prompt(str(tmp_path), "build this")

        cmd_passed = popen.call_args.args[0]
        assert "--dangerously-skip-permissions" not in cmd_passed

    def test_exec_prompt_uses_dangerous_claude_permissions_when_approved(self, tmp_path):
        policy = LlmToolPolicy(
            allow_unsafe_host_execution=True,
            approval_reason="Operator approved disposable worktree after sandbox review.",
        )

        with _patch_claude_popen() as popen:
            AICodingCliProvider(_config(tool_policy=policy)).exec_prompt(str(tmp_path), "build this")

        cmd_passed = popen.call_args.args[0]
        assert "--dangerously-skip-permissions" in cmd_passed

    def test_exec_prompt_allows_claude_native_task_planning_tools(self, tmp_path):
        with _patch_claude_popen() as popen:
            AICodingCliProvider(_config()).exec_prompt(str(tmp_path), "build this")

        cmd_passed = popen.call_args.args[0]
        assert "--disallowedTools" not in cmd_passed

    def test_run_agent_result_disallows_claude_task_tools_for_canonical_execution(self, tmp_path):
        with _patch_claude_popen() as popen:
            result = AICodingCliProvider(_config()).run_agent_result(
                str(tmp_path),
                "build this",
                request_metadata={"canonical_task_execution": True},
            )

        assert result.exit_code == 0
        cmd_passed = popen.call_args.args[0]
        assert "--disallowedTools" in cmd_passed
        disallowed = cmd_passed[cmd_passed.index("--disallowedTools") + 1]
        assert "TaskCreate" in disallowed
        assert "TaskUpdate" in disallowed

    def test_exec_prompt_sets_claude_config_dir_when_configured(self, tmp_path):
        with _patch_claude_popen() as popen:
            AICodingCliProvider(_config(config_dir="/home/user/.config/claude-work"))\
                .exec_prompt(str(tmp_path), "build this")

        env_passed = popen.call_args.kwargs["env"]
        assert env_passed.get("CLAUDE_CONFIG_DIR") == "/home/user/.config/claude-work"

    def test_exec_prompt_no_config_dir_when_not_set(self, tmp_path):
        with _patch_claude_popen() as popen:
            AICodingCliProvider(_config()).exec_prompt(str(tmp_path), "build this")

        env_passed = popen.call_args.kwargs["env"]
        assert "CLAUDE_CONFIG_DIR" not in env_passed

    def test_exec_prompt_uses_worktree_as_cwd(self, tmp_path):
        with _patch_claude_popen() as popen:
            AICodingCliProvider(_config()).exec_prompt("/wt/001", "build this")

        assert popen.call_args.kwargs["cwd"] == "/wt/001"

    def test_exec_prompt_returns_minus_one_on_timeout(self, tmp_path):
        provider = AICodingCliProvider(_config())

        with patch.object(
            provider._backend,
            "run_prompt",
            return_value=CliRunResult(exit_code=-1, stdout="", stderr="", timed_out=True),
        ):
            result = provider.exec_prompt(str(tmp_path), "build this")

        assert result == -1

    def test_exec_prompt_puts_containment_roots_in_backend_metadata(self, tmp_path):
        provider = AICodingCliProvider(_config())

        with patch.object(
            provider._backend,
            "run_prompt",
            return_value=CliRunResult(exit_code=0, stdout="", stderr=""),
        ) as run_prompt:
            provider.exec_prompt(
                str(tmp_path),
                "build this",
                extra_env={
                    "ECHELON_ALLOWED_ROOTS_JSON": json.dumps([str(tmp_path)]),
                    "ECHELON_FORBIDDEN_ROOTS_JSON": '["/workspace/sources/ruler"]',
                    "ECHELON_FORBIDDEN_ROOT_ALIASES_JSON": '["sources/ruler"]',
                },
            )

        request = run_prompt.call_args.args[0]
        assert request.metadata["containment"] == {
            "allowed_roots": [str(tmp_path)],
            "forbidden_roots": ["/workspace/sources/ruler"],
            "forbidden_root_aliases": ["sources/ruler"],
        }

    def test_exec_prompt_blocks_cwd_outside_allowed_containment_roots(self, tmp_path):
        provider = AICodingCliProvider(_config())
        allowed = tmp_path / "sources" / "prosaic"
        forbidden = tmp_path / "sources" / "ruler"
        forbidden.mkdir(parents=True)

        with patch.object(
            provider._backend,
            "run_prompt",
            return_value=CliRunResult(exit_code=0, stdout="", stderr=""),
        ) as run_prompt:
            result = provider.run_prompt_result(
                str(forbidden),
                "build this",
                extra_env={
                    "ECHELON_ALLOWED_ROOTS_JSON": json.dumps([str(allowed)]),
                    "ECHELON_FORBIDDEN_ROOTS_JSON": json.dumps([str(forbidden)]),
                },
            )

        assert result.exit_code != 0
        assert result.metadata["containment_violation"] is True
        assert str(forbidden) in result.stderr
        run_prompt.assert_not_called()

    def test_exec_prompt_blocks_malformed_containment_roots(self, tmp_path):
        provider = AICodingCliProvider(_config())

        with patch.object(
            provider._backend,
            "run_prompt",
            return_value=CliRunResult(exit_code=0, stdout="", stderr=""),
        ) as run_prompt:
            result = provider.run_prompt_result(
                str(tmp_path),
                "build this",
                extra_env={
                    "ECHELON_ALLOWED_ROOTS_JSON": "[not-json",
                },
            )

        assert result.exit_code != 0
        assert result.metadata["containment_violation"] is True
        assert "malformed containment root metadata" in result.stderr
        run_prompt.assert_not_called()

    def test_provider_debug_env_prints_effective_backend(self, monkeypatch, capsys):
        monkeypatch.setenv("ECHELON_DEBUG_LLM", "1")

        AICodingCliProvider(_config(cli="codex"))

        captured = capsys.readouterr()
        assert "[llm] provider=codex" in captured.err
        assert "backend=CodexCliBackend" in captured.err

    def test_streaming_captures_result_error_text(self, tmp_path):
        provider = AICodingCliProvider(_config())
        lines = [
            {
                "type": "result",
                "is_error": True,
                "result": "You've hit your session limit - resets 9:10pm",
                "num_turns": 1,
                "duration_ms": 0,
            }
        ]

        with _patch_claude_popen(lines=lines, returncode=1):
            result = provider.exec_prompt(str(tmp_path), "build this")

        assert result == 1
        assert "session limit" in provider.last_stdout
        assert "resets 9:10pm" in provider.last_stdout

    def test_streaming_captures_token_usage_from_result_event(self, tmp_path):
        provider = AICodingCliProvider(_config())
        lines = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "building slice"}
                    ]
                },
            },
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
            },
        ]

        with _patch_claude_popen(lines=lines):
            result = provider.exec_prompt(str(tmp_path), "build this")

        assert result == 0
        assert provider.last_token_usage == 1575
