from __future__ import annotations

import shutil
import subprocess

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.config import HarnessConfig
from harness.llm_tool_policy import build_llm_cli_command


class PlainCliBackend:
    def __init__(self, config: HarnessConfig) -> None:
        self._config = config
        self.name = config.llm.cli
        self._bin = shutil.which(self.name) or self.name

    def run_prompt(self, request: CliRunRequest) -> CliRunResult:
        cmd = build_llm_cli_command(
            self.name,
            self._bin,
            request.prompt,
            self._config.llm.tool_policy,
        )
        try:
            result = subprocess.run(
                cmd,
                cwd=request.cwd,
                env=dict(request.env),
                timeout=request.timeout_s,
                capture_output=True,
            )
            stdout = result.stdout.decode("utf-8", errors="replace")
            stderr = result.stderr.decode("utf-8", errors="replace")
            if stdout:
                print(stdout, flush=True)
            if stderr:
                print(stderr, flush=True)
            return CliRunResult(
                exit_code=int(result.returncode),
                stdout=stdout,
                stderr=stderr,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or b"").decode("utf-8", errors="replace")
            stderr = (exc.stderr or b"").decode("utf-8", errors="replace")
            return CliRunResult(
                exit_code=-1,
                stdout=stdout,
                stderr=stderr,
                timed_out=True,
            )

    def run_agent(self, request: CliRunRequest) -> CliRunResult:
        return self.run_prompt(request)
