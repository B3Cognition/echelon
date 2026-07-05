from __future__ import annotations

import json
import shutil
import subprocess

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.config import HarnessConfig
from harness.llm_tool_policy import build_llm_cli_command


class OpenCodeCliBackend:
    name = "opencode"

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config
        self._bin = shutil.which(self.name) or self.name

    def run_prompt(self, request: CliRunRequest) -> CliRunResult:
        cmd = build_llm_cli_command(
            self.name,
            self._bin,
            request.prompt,
            self._config.llm.tool_policy,
            opencode_json=True,
        )
        return self._run(cmd, request)

    def run_agent(self, request: CliRunRequest) -> CliRunResult:
        return self.run_prompt(request)

    def _run(self, cmd: list[str], request: CliRunRequest) -> CliRunResult:
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=request.cwd,
                env=dict(request.env),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                stdout_parts.append(_extract_opencode_text(line))
            stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
            if stderr:
                stderr_parts.append(stderr)
            exit_code = proc.wait()
        except subprocess.TimeoutExpired as exc:
            return CliRunResult(
                exit_code=-1,
                stdout=(exc.stdout or b"").decode("utf-8", errors="replace"),
                stderr=(exc.stderr or b"").decode("utf-8", errors="replace"),
                timed_out=True,
            )
        stdout = "\n".join(part for part in stdout_parts if part)
        stderr = "\n".join(part for part in stderr_parts if part)
        if stdout:
            print(stdout, flush=True)
        if stderr:
            print(stderr, flush=True)
        return CliRunResult(exit_code=int(exit_code), stdout=stdout, stderr=stderr)


def _extract_opencode_text(line: str) -> str:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return line
    for key in ("content", "output", "result", "text", "message"):
        value = event.get(key)
        if isinstance(value, str):
            return value
    return line
