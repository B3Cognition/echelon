"""ClaudeCliProvider — invokes an LLM CLI (claude, copilot, or opencode) via subprocess."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from harness.build_result import BuildResult
from harness.config import HarnessConfig


class ClaudeCliProvider:
    """Runs LLM build and feedback steps via subprocess.

    Supports claude (default), copilot, and opencode. Configured via config.llm.cli
    or the ECHELON_LLM env var (env var takes precedence).

    Not a SandboxProvider — has its own interface because it operates
    without a sandbox lifecycle (no create/destroy).
    """

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config
        self._timeout_s = config.llm.timeout_ms / 1000.0
        self._config_dir = config.llm.config_dir
        self._cli = os.environ.get("ECHELON_LLM", config.llm.cli)
        # Resolve full path so subprocess inherits our shell's PATH, not a stripped one.
        self._bin = shutil.which(self._cli) or self._cli

    def _build_cmd(self, prompt: str) -> list:
        if self._cli == "opencode":
            return [self._bin, "run", "--dangerously-skip-permissions", prompt]
        cmd = [self._bin, "-p", prompt, "--dangerously-skip-permissions"]
        if self._cli == "copilot":
            cmd += ["--allow-all-tools"]
        return cmd

    def exec_build(self, worktree_path: str, prompt: str) -> BuildResult:
        """Run `<cli> -p <prompt>` in worktree_path, return BuildResult."""
        status_file = self._status_file_path(worktree_path)
        env = self._build_env(str(status_file))

        start = time.monotonic()
        try:
            result = subprocess.run(
                self._build_cmd(prompt),
                cwd=worktree_path,
                env=env,
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
            )
        except subprocess.TimeoutExpired:
            duration_ms = int((time.monotonic() - start) * 1000)
            return BuildResult(
                exit_code=-1,
                status="timeout",
                impasse_file=None,
                stdout="",
                stderr="",
                duration_ms=duration_ms,
            )
        duration_ms = int((time.monotonic() - start) * 1000)

        return BuildResult.from_status_file(
            status_file,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=duration_ms,
        )

    def exec_feedback(self, worktree_path: str, prompt: str) -> BuildResult:
        """Run `<cli> -p <prompt>` for a targeted fix. Same mechanics as exec_build."""
        return self.exec_build(worktree_path, prompt)

    # === Private ===

    def _status_file_path(self, worktree_path: str) -> Path:
        """Status file lives inside the worktree to avoid collisions."""
        return Path(worktree_path) / ".harness-build-status.json"

    def _build_env(self, status_file: str) -> dict:
        """Build environment with HARNESS_BUILD_STATUS_FILE; CLAUDE_CONFIG_DIR if claude only."""
        env = {**os.environ, "HARNESS_BUILD_STATUS_FILE": status_file}
        if self._config_dir and self._cli == "claude":
            env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(self._config_dir)
        return env
