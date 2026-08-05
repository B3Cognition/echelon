from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from collections.abc import Mapping
from pathlib import Path

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.config import HarnessConfig
from harness.llm_tool_policy import build_llm_cli_command
from harness.skill_loader import StreamEventPrinter


_MODEL_TIER_TO_CLAUDE_MODEL = {
    "fast": "haiku",
    "balanced": "sonnet",
    "strong": "opus",
    "ultra": "fable",
}


class ClaudeCliBackend:
    name = "claude"

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config
        self._bin = shutil.which("claude") or "claude"

    def run_prompt(self, request: CliRunRequest) -> CliRunResult:
        canonical_task_execution = (
            request.metadata.get("canonical_task_execution") is True
        )
        cmd = build_llm_cli_command(
            "claude",
            self._bin,
            request.prompt,
            self._config.llm.tool_policy,
            stream_json=True,
            disallow_claude_task_tools=canonical_task_execution,
        )
        model = _prompt_metadata_str(request, "model") or _claude_model_for_request(
            request
        )
        if model:
            cmd.extend(["--model", model])
        scope_args = _prompt_file_scope_args(request)
        if scope_args:
            cmd.extend(scope_args)
        raw_prompt_metadata = request.metadata.get("prompt_metadata")
        forbidden_roots = (
            _prompt_scope_paths(
                request,
                raw_prompt_metadata,
                "tool_forbidden_roots",
            )
            if isinstance(raw_prompt_metadata, Mapping)
            else ()
        )
        if forbidden_roots:
            sandbox_exec = _sandbox_exec_path()
            if sandbox_exec is None:
                return CliRunResult(
                    exit_code=125,
                    stdout="",
                    stderr="workspace synthesis host boundary is unavailable",
                    metadata={"workspace_synthesis_boundary": "unavailable"},
                )
            cmd = [
                sandbox_exec,
                "-p",
                _workspace_sandbox_profile(forbidden_roots),
                *cmd,
            ]
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
        response_model = ""
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
                        raw_message = event.get("message")
                        message = raw_message if isinstance(raw_message, Mapping) else {}
                        raw_model = message.get("model")
                        if isinstance(raw_model, str) and raw_model.strip():
                            response_model = raw_model.strip()
                        for block in message.get("content", []):
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
            metadata=(
                {"response_model": response_model} if response_model else {}
            ),
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


def _prompt_metadata_str(request: CliRunRequest, key: str) -> str:
    metadata = request.metadata.get("prompt_metadata")
    if not isinstance(metadata, Mapping):
        return ""
    value = metadata.get(key)
    return value.strip() if isinstance(value, str) else ""


def _prompt_file_scope_args(request: CliRunRequest) -> list[str]:
    metadata = request.metadata.get("prompt_metadata")
    if not isinstance(metadata, Mapping):
        return []
    read_roots = _prompt_scope_paths(request, metadata, "tool_read_roots")
    write_paths = _prompt_scope_paths(request, metadata, "tool_write_paths")
    if not read_roots and not write_paths:
        return []

    rules: list[str] = []
    for root in read_roots:
        rules.append(f"Read({_claude_absolute_rule_path(root)}/**)")
    for path in write_paths:
        rule_path = _claude_absolute_rule_path(path)
        rules.extend(f"{tool}({rule_path})" for tool in ("Write", "Edit"))
    return [
        "--safe-mode",
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--tools",
        "Read,Write,Edit",
        "--allowedTools",
        ",".join(rules),
    ]


def _prompt_scope_paths(
    request: CliRunRequest,
    metadata: Mapping[object, object],
    key: str,
) -> tuple[str, ...]:
    raw = metadata.get(key)
    if not isinstance(raw, list):
        return ()
    cwd = Path(request.cwd).resolve()
    paths: set[str] = set()
    for value in raw:
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = cwd / candidate
        paths.add(str(candidate.resolve(strict=False)))
    return tuple(sorted(paths))


def _claude_absolute_rule_path(path: str) -> str:
    return f"/{path}" if path.startswith("/") else path


def host_workspace_synthesis_boundary_available() -> bool:
    return sys.platform == "darwin" and _sandbox_exec_path() is not None


def _sandbox_exec_path() -> str | None:
    return shutil.which("sandbox-exec")


def _workspace_sandbox_profile(forbidden_roots: tuple[str, ...]) -> str:
    exclusions: list[str] = []
    for root in forbidden_roots:
        quoted = json.dumps(root)
        exclusions.extend(
            (
                f"(require-not (literal {quoted}))",
                f"(require-not (subpath {quoted}))",
            )
        )
    allowed_files = f"(require-all {' '.join(exclusions)})"
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process*)",
        f"(allow file-read* {allowed_files})",
        f"(allow file-write* {allowed_files})",
        "(allow network*)",
        "(allow sysctl-read)",
        "(allow mach-lookup)",
        "(allow ipc-posix*)",
    ]
    return "\n".join(lines)


def _claude_model_for_request(request: CliRunRequest) -> str:
    tier = _prompt_metadata_str(request, "model_tier").lower()
    return _MODEL_TIER_TO_CLAUDE_MODEL.get(tier, "")
