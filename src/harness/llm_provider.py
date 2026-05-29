"""AICodingCliProvider — invokes an LLM CLI (claude, copilot, or opencode) via subprocess."""
from __future__ import annotations

import json as _json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from harness.build_result import BuildResult
from harness.config import HarnessConfig
from harness.skill_loader import StreamEventPrinter


class AICodingCliProvider:
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
        if self._cli == "claude":
            return [
                self._bin, "-p", prompt,
                "--dangerously-skip-permissions",
                "--output-format", "stream-json",
                "--verbose",
            ]
        cmd = [self._bin, "-p", prompt, "--dangerously-skip-permissions"]
        if self._cli == "copilot":
            cmd += ["--allow-all-tools"]
        return cmd

    def exec_build(self, worktree_path: str, prompt: str) -> BuildResult:
        """Run `<cli> -p <prompt>` in worktree_path, return BuildResult."""
        status_file = self._status_file_path(worktree_path)
        env = self._build_env(str(status_file))
        start = time.monotonic()

        if self._cli == "claude":
            exit_code = self._run_streaming(self._build_cmd(prompt), worktree_path, env, start)
        else:
            exit_code = self._run_plain(self._build_cmd(prompt), worktree_path, env, start)

        if exit_code is None:  # timeout
            duration_ms = int((time.monotonic() - start) * 1000)
            return BuildResult(
                exit_code=-1, status="timeout", impasse_file=None,
                stdout="", stderr="", duration_ms=duration_ms,
            )

        duration_ms = int((time.monotonic() - start) * 1000)
        return BuildResult.from_status_file(
            status_file, exit_code=exit_code, stdout="", stderr="", duration_ms=duration_ms,
        )

    def exec_feedback(self, worktree_path: str, prompt: str) -> BuildResult:
        """Run `<cli> -p <prompt>` for a targeted fix. Same mechanics as exec_build."""
        return self.exec_build(worktree_path, prompt)

    # === Private ===

    def _run_streaming(self, cmd: list, cwd: str, env: dict, start: float):
        """Run claude with stream-json, printing live tool-call events. Returns exit code or None on timeout."""
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=None,  # inherit so errors are visible
        )

        timed_out = False
        printer = StreamEventPrinter()

        def _kill():
            nonlocal timed_out
            timed_out = True
            proc.kill()

        timer = threading.Timer(self._timeout_s, _kill)
        try:
            timer.start()
            for raw in proc.stdout:  # type: ignore[union-attr]
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    printer(_json.loads(line))
                except _json.JSONDecodeError:
                    print(line, flush=True)
            proc.stdout.close()  # type: ignore[union-attr]
            proc.wait()
        finally:
            timer.cancel()

        return None if timed_out else proc.returncode

    def _run_plain(self, cmd: list, cwd: str, env: dict, start: float):
        """Run non-claude CLIs without streaming. Returns exit code or None on timeout."""
        try:
            result = subprocess.run(cmd, cwd=cwd, env=env, timeout=self._timeout_s)
            return result.returncode
        except subprocess.TimeoutExpired:
            return None

    def _status_file_path(self, worktree_path: str) -> Path:
        return Path(worktree_path) / ".harness-build-status.json"

    def _build_env(self, status_file: str) -> dict:
        env = {**os.environ, "HARNESS_BUILD_STATUS_FILE": status_file}
        if self._config_dir and self._cli == "claude":
            env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(self._config_dir)
        # Let agents navigate directly to harness source for debugging/fix sessions
        # rather than spending turns on filesystem searches.
        env["HARNESS_SOURCE_DIR"] = str(Path(__file__).parent)
        return env
