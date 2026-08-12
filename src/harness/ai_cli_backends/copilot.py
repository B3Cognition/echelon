from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.config import HarnessConfig
from harness.llm_tool_policy import build_llm_cli_command


class CopilotCliBackend:
    name = "copilot"

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config
        self._bin = shutil.which(self.name) or self.name

    def run_prompt(self, request: CliRunRequest) -> CliRunResult:
        cmd = build_llm_cli_command(
            self.name,
            self._bin,
            request.prompt,
            self._config.llm.tool_policy,
            copilot_json=True,
        )
        return self._run(cmd, request)

    def run_agent(self, request: CliRunRequest) -> CliRunResult:
        return self.run_prompt(request)

    def _run(self, cmd: list[str], request: CliRunRequest) -> CliRunResult:
        proc = subprocess.Popen(
            cmd,
            cwd=request.cwd,
            env=dict(request.env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        timed_out = False

        def read_stderr() -> None:
            if proc.stderr is None:
                return
            stderr = proc.stderr.read().decode("utf-8", errors="replace")
            if stderr:
                stderr_parts.append(stderr)

        def kill() -> None:
            nonlocal timed_out
            timed_out = True
            proc.kill()

        timer = threading.Timer(request.timeout_s, kill)
        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        try:
            timer.start()
            stderr_thread.start()
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                stdout_parts.append(_extract_copilot_text(line))
            exit_code = proc.wait()
            stderr_thread.join(timeout=1)
        finally:
            timer.cancel()

        stdout = "\n".join(part for part in stdout_parts if part)
        stderr = "\n".join(part for part in stderr_parts if part)
        if stdout:
            print(stdout, flush=True)
        if stderr:
            print(stderr, file=sys.stderr, flush=True)
        return CliRunResult(
            exit_code=-1 if timed_out else int(exit_code),
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
        )


def _extract_copilot_text(line: str) -> str:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return line

    for key in ("content", "message", "output", "result", "text"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value

    data = event.get("data")
    if isinstance(data, dict):
        for key in ("content", "message", "output", "result", "text"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value

    if "type" in event:
        return ""
    return line
