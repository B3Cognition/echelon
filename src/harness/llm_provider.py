"""AICodingCliProvider facade for host-side AI coding CLI backends."""
from __future__ import annotations

import os
import shutil
from dataclasses import replace
from typing import Mapping

from harness.ai_cli_backend import CliRunRequest, CliRunResult, create_ai_cli_backend
from harness.config import HarnessConfig
from harness.llm_tool_policy import build_llm_cli_command


class AICodingCliProvider:
    """Runs prompts through the configured AI coding CLI backend.

    Supports claude (default), copilot, opencode, and codex. Configured via
    config.llm.cli or the ECHELON_LLM env var (env var takes precedence).

    Not a SandboxProvider: it owns CLI backend selection, environment setup,
    timeout handling, and provider result bookkeeping.
    """

    def __init__(self, config: HarnessConfig) -> None:
        self._cli = os.environ.get("ECHELON_LLM", config.llm.cli)
        effective_config = config
        if self._cli != config.llm.cli:
            effective_config = replace(config, llm=replace(config.llm, cli=self._cli))

        self._config = effective_config
        self._timeout_s = effective_config.llm.timeout_ms / 1000.0
        self._config_dir = effective_config.llm.config_dir
        self._bin = shutil.which(self._cli) or self._cli
        self._backend = create_ai_cli_backend(effective_config)
        self.last_stdout = ""
        self.last_stderr = ""
        self.last_token_usage = 0

    @property
    def cli(self) -> str:
        return self._cli

    def _build_cmd(self, prompt: str) -> list[str]:
        """Compatibility helper for tests and call sites that inspect command shape."""
        return build_llm_cli_command(
            self._cli,
            self._bin,
            prompt,
            self._config.llm.tool_policy,
            stream_json=self._cli == "claude",
            disallow_claude_task_tools=self._cli == "claude",
        )

    def exec_prompt(
        self,
        worktree_path: str,
        prompt: str,
        *,
        extra_env: Mapping[str, str] | None = None,
    ) -> int:
        """Run a prompt with the configured AI coding CLI and return its exit code."""
        result = self.run_prompt_result(
            worktree_path,
            prompt,
            extra_env=extra_env,
        )
        return int(result.exit_code)

    def run_prompt_result(
        self,
        worktree_path: str,
        prompt: str,
        *,
        extra_env: Mapping[str, str] | None = None,
        timeout_ms: int | None = None,
    ) -> CliRunResult:
        self.last_stdout = ""
        self.last_stderr = ""
        self.last_token_usage = 0
        timeout_s = (timeout_ms / 1000.0) if timeout_ms else self._timeout_s
        result = self._backend.run_prompt(
            CliRunRequest(
                cwd=worktree_path,
                prompt=prompt,
                env=self._build_env(extra_env),
                timeout_s=timeout_s,
            )
        )
        self._record_result(result)
        return result

    def run_agent_result(
        self,
        project_root: str,
        prompt: str,
        *,
        timeout_ms: int | None = None,
        extra_env: Mapping[str, str] | None = None,
    ) -> CliRunResult:
        self.last_stdout = ""
        self.last_stderr = ""
        self.last_token_usage = 0
        timeout_s = (timeout_ms / 1000.0) if timeout_ms else self._timeout_s
        result = self._backend.run_agent(
            CliRunRequest(
                cwd=project_root,
                prompt=prompt,
                env=self._build_env(extra_env),
                timeout_s=timeout_s,
            )
        )
        self._record_result(result)
        return result

    def _record_result(self, result: CliRunResult) -> None:
        self.last_stdout = result.stdout
        self.last_stderr = result.stderr
        self.last_token_usage = result.token_usage

    def _build_env(self, extra_env: Mapping[str, str] | None = None) -> dict[str, str]:
        env = {**os.environ}
        if extra_env:
            env.update(extra_env)
        if self._config_dir and self._cli == "claude":
            env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(self._config_dir)
        return env
