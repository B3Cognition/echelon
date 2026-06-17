"""AICodingCliProvider — invokes an LLM CLI via subprocess."""
from __future__ import annotations

import json as _json
import os
import shutil
import subprocess
import threading
import time
from typing import Mapping

from harness.config import HarnessConfig
from harness.skill_loader import StreamEventPrinter


class AICodingCliProvider:
    """Runs prompts through an AI coding CLI subprocess.

    Supports claude (default), copilot, opencode, and codex. Configured via
    config.llm.cli or the ECHELON_LLM env var (env var takes precedence).

    Not a SandboxProvider: it only owns CLI selection, command construction,
    environment setup, timeout handling, and stream/plain subprocess execution.
    """

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config
        self._timeout_s = config.llm.timeout_ms / 1000.0
        self._config_dir = config.llm.config_dir
        self._cli = os.environ.get("ECHELON_LLM", config.llm.cli)
        # Resolve full path so subprocess inherits our shell's PATH, not a stripped one.
        self._bin = shutil.which(self._cli) or self._cli
        self.last_stdout = ""
        self.last_stderr = ""
        self.last_token_usage = 0

    @property
    def cli(self) -> str:
        return self._cli

    def _build_cmd(self, prompt: str) -> list:
        if self._cli == "opencode":
            return [self._bin, "run", "--dangerously-skip-permissions", prompt]
        if self._cli == "codex":
            return [
                self._bin,
                "exec",
                "--dangerously-bypass-approvals-and-sandbox",
                prompt,
            ]
        if self._cli == "claude":
            return [
                self._bin, "-p", prompt,
                "--dangerously-skip-permissions",
                "--disallowedTools", "TaskCreate,TaskUpdate",
                "--output-format", "stream-json",
                "--verbose",
            ]
        cmd = [self._bin, "-p", prompt, "--dangerously-skip-permissions"]
        if self._cli == "copilot":
            cmd += ["--allow-all-tools"]
        return cmd

    def exec_prompt(
        self,
        worktree_path: str,
        prompt: str,
        *,
        extra_env: Mapping[str, str] | None = None,
    ) -> int:
        """Run a prompt with the configured LLM CLI and return its process exit code."""
        self.last_stdout = ""
        self.last_stderr = ""
        self.last_token_usage = 0
        env = self._build_env(extra_env)
        start = time.monotonic()
        if self._cli == "claude":
            exit_code = self._run_streaming(self._build_cmd(prompt), worktree_path, env, start)
        else:
            exit_code = self._run_plain(self._build_cmd(prompt), worktree_path, env, start)
        return -1 if exit_code is None else int(exit_code)

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
        captured_lines: list[str] = []
        token_usage = 0

        def _kill():
            nonlocal timed_out
            timed_out = True
            proc.kill()

        def _capture(text: object) -> None:
            line = str(text or "").strip()
            if not line:
                return
            captured_lines.append(line)
            total = 0
            bounded: list[str] = []
            for item in reversed(captured_lines):
                total += len(item) + 1
                if total > 20_000:
                    break
                bounded.append(item)
            captured_lines[:] = list(reversed(bounded))

        timer = threading.Timer(self._timeout_s, _kill)
        try:
            timer.start()
            for raw in proc.stdout:  # type: ignore[union-attr]
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = _json.loads(line)
                    if event.get("type") == "result" and event.get("is_error"):
                        _capture(event.get("result", ""))
                    if event.get("type") == "result":
                        token_usage = _extract_token_usage(event)
                    printer(event)
                except _json.JSONDecodeError:
                    _capture(line)
                    print(line, flush=True)
            proc.stdout.close()  # type: ignore[union-attr]
            proc.wait()
        finally:
            timer.cancel()

        self.last_stdout = "\n".join(captured_lines)
        self.last_token_usage = token_usage
        return None if timed_out else proc.returncode

    def _run_plain(self, cmd: list, cwd: str, env: dict, start: float):
        """Run non-claude CLIs without streaming. Returns exit code or None on timeout."""
        try:
            result = subprocess.run(cmd, cwd=cwd, env=env, timeout=self._timeout_s)
            return result.returncode
        except subprocess.TimeoutExpired:
            return None

    def _build_env(self, extra_env: Mapping[str, str] | None = None) -> dict:
        env = {**os.environ}
        if extra_env:
            env.update(extra_env)
        if self._config_dir and self._cli == "claude":
            env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(self._config_dir)
        return env


def _extract_token_usage(event: Mapping[str, object]) -> int:
    usage = event.get("usage")
    if isinstance(usage, Mapping):
        total = 0
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        ):
            try:
                total += int(usage.get(key) or 0)
            except (TypeError, ValueError):
                continue
        if total > 0:
            return total

    total = 0
    for key in (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ):
        try:
            total += int(event.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return total
