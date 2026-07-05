from __future__ import annotations

import json
import shutil
import subprocess
import threading
from collections.abc import Mapping

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.config import HarnessConfig
from harness.llm_tool_policy import build_llm_cli_command
from harness.skill_loader import StreamEventPrinter


class ClaudeCliBackend:
    name = "claude"

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config
        self._bin = shutil.which("claude") or "claude"

    def run_prompt(self, request: CliRunRequest) -> CliRunResult:
        cmd = build_llm_cli_command(
            "claude",
            self._bin,
            request.prompt,
            self._config.llm.tool_policy,
            stream_json=True,
            disallow_claude_task_tools=True,
        )
        return self._run_stream_json(cmd, request)

    def run_agent(self, request: CliRunRequest) -> CliRunResult:
        return self.run_prompt(request)

    def _run_stream_json(self, cmd: list[str], request: CliRunRequest) -> CliRunResult:
        proc = subprocess.Popen(
            cmd,
            cwd=request.cwd,
            env=dict(request.env),
            stdout=subprocess.PIPE,
            stderr=None,
        )
        captured_lines: list[str] = []
        text_chunks: list[str] = []
        timed_out = False
        token_usage = 0
        cost_usd = 0.0
        printer = StreamEventPrinter()

        def kill() -> None:
            nonlocal timed_out
            timed_out = True
            proc.kill()

        def capture(text: object) -> None:
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

        timer = threading.Timer(request.timeout_s, kill)
        try:
            timer.start()
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    printer(event)
                    etype = event.get("type")
                    if etype == "assistant":
                        for block in event.get("message", {}).get("content", []):
                            if block.get("type") == "text":
                                text = block.get("text", "")
                                text_chunks.append(text)
                                capture(text)
                    elif (
                        etype == "content_block_delta"
                        and event.get("delta", {}).get("type") == "text_delta"
                    ):
                        text = event["delta"].get("text", "")
                        text_chunks.append(text)
                        capture(text)
                    elif etype == "result":
                        token_usage = _extract_token_usage(event)
                        cost_usd = float(event.get("total_cost_usd") or 0)
                        if event.get("is_error"):
                            capture(event.get("result", ""))
                except json.JSONDecodeError:
                    capture(line)
                    text_chunks.append(line)
                    print(line, flush=True)
            proc.stdout.close()
            proc.wait()
        finally:
            timer.cancel()

        stdout = "".join(text_chunks).strip() or "\n".join(captured_lines)
        return CliRunResult(
            exit_code=-1 if timed_out else int(proc.returncode),
            stdout=stdout,
            stderr="",
            token_usage=token_usage,
            cost_usd=cost_usd,
            timed_out=timed_out,
        )


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
