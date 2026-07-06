from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass

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
        saw_task_complete = False
        token_usage = 0

        def kill() -> None:
            nonlocal timed_out
            timed_out = True
            proc.kill()

        def drain_stderr() -> None:
            if proc.stderr is None:
                return
            stderr_chunks.append(proc.stderr.read().decode("utf-8", errors="replace"))

        timer = threading.Timer(request.timeout_s, kill)
        stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
        try:
            timer.start()
            stderr_thread.start()
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                event = _codex_event(line)
                if event.token_usage:
                    token_usage = event.token_usage
                if event.text:
                    stdout_chunks.append(event.text)
                    print(event.text, flush=True)
                if event.task_complete:
                    saw_task_complete = True
                    _stop_completed_process(proc)
                    break
            if not saw_task_complete:
                proc.wait()
        finally:
            timer.cancel()
            stderr_thread.join(timeout=1.0)

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
            exit_code=(
                0 if saw_task_complete else (-1 if timed_out else int(proc.returncode))
            ),
            stdout="\n".join(chunk for chunk in stdout_chunks if chunk),
            stderr="\n".join(chunk for chunk in stderr_chunks if chunk),
            token_usage=token_usage,
            timed_out=timed_out,
            metadata={"task_complete": saw_task_complete},
        )


@dataclass(frozen=True)
class _CodexEvent:
    text: str
    task_complete: bool = False
    token_usage: int = 0


def _codex_event(line: str) -> _CodexEvent:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return _CodexEvent(line)

    payload = event.get("payload")
    if isinstance(payload, dict):
        payload_type = payload.get("type")
        if payload_type == "task_complete":
            message = payload.get("last_agent_message")
            return _CodexEvent(
                message if isinstance(message, str) else "",
                task_complete=True,
            )
        if payload_type == "token_count":
            usage = _extract_token_usage(payload.get("info"))
            return _CodexEvent("", token_usage=usage)

    return _CodexEvent(_codex_event_text_from_json(event))


def _codex_event_text(line: str) -> str:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return line

    return _codex_event_text_from_json(event)


def _codex_event_text_from_json(event: dict) -> str:
    payload = event.get("payload")
    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message

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

    return json.dumps(event)


def _extract_token_usage(info: object) -> int:
    if not isinstance(info, dict):
        return 0
    total = info.get("total_token_usage")
    if not isinstance(total, dict):
        return 0
    try:
        return int(total.get("total_tokens") or 0)
    except (TypeError, ValueError):
        return 0


def _stop_completed_process(proc: subprocess.Popen) -> None:
    try:
        proc.wait(timeout=2.0)
        return
    except TypeError:
        proc.wait()
        return
    except subprocess.TimeoutExpired:
        pass

    terminate = getattr(proc, "terminate", None)
    if callable(terminate):
        terminate()
    else:
        proc.kill()

    try:
        proc.wait(timeout=2.0)
    except TypeError:
        proc.wait()
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
