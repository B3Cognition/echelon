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


_MODEL_TIER_TO_CODEX_MODEL = {
    "fast": "gpt-5.6-luna",
    "balanced": "gpt-5.6-terra",
    "strong": "gpt-5.6-sol",
}


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

        model = _codex_model_for_request(request)
        allow_non_git_cwd = request.metadata.get("allow_non_git_cwd") is True
        cmd = build_llm_cli_command(
            "codex",
            self._bin,
            request.prompt,
            self._config.llm.tool_policy,
            codex_json=True,
            codex_model=model,
            codex_skip_git_repo_check=allow_non_git_cwd,
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
        token_usage: int | None = None

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
                if event.token_usage is not None:
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
            metadata={
                "task_complete": saw_task_complete,
                # Codex JSON events do not reliably include a response model.
                # Preserve the explicitly requested model for durable telemetry.
                "request_model": model or "",
            },
        )


def _codex_model_for_request(request: CliRunRequest) -> str | None:
    metadata = request.metadata.get("prompt_metadata")
    if not isinstance(metadata, dict):
        return None
    tier = metadata.get("model_tier")
    if not isinstance(tier, str):
        return None
    return _MODEL_TIER_TO_CODEX_MODEL.get(tier.strip().lower())


@dataclass(frozen=True)
class _CodexEvent:
    text: str
    task_complete: bool = False
    token_usage: int | None = None


def _codex_event(line: str) -> _CodexEvent:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return _CodexEvent(line)

    item = event.get("item")
    if isinstance(item, dict) and item.get("type") == "command_execution":
        return _CodexEvent(_codex_command_event_text(event, item))

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
    event_type = event.get("type")
    if event_type in {
        "item.started",
        "item.completed",
        "turn.started",
        "turn.completed",
        "thread.started",
    }:
        return ""

    payload = event.get("payload")
    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message

    if event_type == "response_item":
        text = _codex_response_item_text(event.get("payload"))
        if text:
            return text

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

    return ""


def _codex_response_item_text(payload: object) -> str:
    if not isinstance(payload, dict) or payload.get("type") != "message":
        return ""
    chunks: list[str] = []
    content = payload.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "".join(chunks).strip()


def _codex_command_event_text(event: dict, item: dict) -> str:
    event_type = event.get("type")
    status = str(item.get("status") or "")
    exit_code = item.get("exit_code")
    command = _truncate_one_line(str(item.get("command") or "command"), limit=180)
    output = str(item.get("aggregated_output") or "").strip()
    debug = _debug_llm_enabled()

    if event_type == "item.started":
        return f"[codex] command started: {command}" if debug else ""

    failed = exit_code not in (None, 0) or status == "failed"
    if not failed and not debug:
        return ""

    if failed:
        header = f"[codex] command failed"
    else:
        header = f"[codex] command completed"
    if exit_code is not None:
        header += f" (exit {exit_code})"
    header += f": {command}"

    if output and (failed or debug):
        header += "\n" + _truncate_multiline(output, limit=4000)
    return header


def _truncate_one_line(text: str, *, limit: int) -> str:
    line = " ".join(text.split())
    if len(line) <= limit:
        return line
    return line[: limit - 1].rstrip() + "..."


def _truncate_multiline(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "\n..."


def _debug_llm_enabled() -> bool:
    value = os.environ.get("ECHELON_DEBUG_LLM", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


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
