from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.config import HarnessConfig
from harness.llm_tool_policy import build_llm_cli_command


class CodexCliBackend:
    name = "codex"

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config
        self._bin = shutil.which("codex") or "codex"

    def run_prompt(self, request: CliRunRequest) -> CliRunResult:
        return self._run_codex(request, use_final_message=True)

    def run_agent(self, request: CliRunRequest) -> CliRunResult:
        return self._run_codex(request, use_final_message=True)

    def _run_codex(
        self,
        request: CliRunRequest,
        *,
        use_final_message: bool,
    ) -> CliRunResult:
        final_path = ""
        if use_final_message:
            with tempfile.NamedTemporaryFile(
                prefix="echelon-codex-",
                suffix=".txt",
                delete=False,
            ) as temp_file:
                final_path = temp_file.name

        cmd = build_llm_cli_command(
            "codex",
            self._bin,
            request.prompt,
            self._config.llm.tool_policy,
            codex_json=True,
            output_last_message=final_path or None,
        )
        proc = subprocess.Popen(
            cmd,
            cwd=request.cwd,
            env=dict(request.env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        timed_out = False

        def kill() -> None:
            nonlocal timed_out
            timed_out = True
            proc.kill()

        timer = threading.Timer(request.timeout_s, kill)
        try:
            timer.start()
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                text = _codex_event_text(line)
                stdout_chunks.append(text)
                print(text, flush=True)
            if proc.stderr is not None:
                stderr_chunks.append(
                    proc.stderr.read().decode("utf-8", errors="replace")
                )
            proc.wait()
        finally:
            timer.cancel()

        if final_path and os.path.exists(final_path):
            with open(final_path, encoding="utf-8", errors="replace") as handle:
                final_text = handle.read()
            if final_text.strip() and final_text not in stdout_chunks:
                stdout_chunks.append(final_text)
            try:
                os.unlink(final_path)
            except OSError:
                pass

        return CliRunResult(
            exit_code=-1 if timed_out else int(proc.returncode),
            stdout="\n".join(chunk for chunk in stdout_chunks if chunk),
            stderr="\n".join(chunk for chunk in stderr_chunks if chunk),
            timed_out=timed_out,
        )


def _codex_event_text(line: str) -> str:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return line

    for key in ("content", "text", "message", "result"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value

    item = event.get("item")
    if isinstance(item, dict):
        for key in ("content", "text", "message"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value

    return line
