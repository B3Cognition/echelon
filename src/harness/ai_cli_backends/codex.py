from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.ai_cli_backends.claude import (
    _sandbox_exec_path,
    _workspace_sandbox_profile,
)
from harness.config import HarnessConfig
from harness.llm_tool_policy import build_llm_cli_command


_MODEL_TIER_TO_CODEX_MODEL = {
    "fast": "gpt-5.6-luna",
    "balanced": "gpt-5.6-terra",
    "strong": "gpt-5.6-sol",
}

_PRODUCT_PLANE_PERMISSION_PROFILE = "echelon_product_plane"


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
        isolated_workspace = request.metadata.get("isolated_workspace") is True
        allow_non_git_cwd = (
            request.metadata.get("allow_non_git_cwd") is True
            or isolated_workspace
        )
        raw_prompt_metadata = request.metadata.get("prompt_metadata")
        isolated_workspace_error = _isolated_workspace_error(
            request,
            raw_prompt_metadata,
            allow_unsafe_host_execution=(
                self._config.llm.tool_policy.allow_unsafe_host_execution
            ),
        ) if isolated_workspace else None
        if isolated_workspace_error is not None:
            _unlink_if_present(final_path)
            return CliRunResult(
                exit_code=125,
                stdout="",
                stderr=isolated_workspace_error,
                metadata={"isolated_workspace": "invalid"},
            )
        isolated_user_config = not self._config.llm.codex_inherit_user_config
        raw_prompt_metadata = request.metadata.get("prompt_metadata")
        read_roots: tuple[str, ...] = ()
        write_paths: tuple[str, ...] = ()
        forbidden_roots: tuple[str, ...] = ()
        operational_roots: tuple[str, ...] = ()
        operational_read_paths: tuple[str, ...] = ()
        operational_metadata_paths: tuple[str, ...] = ()
        if isinstance(raw_prompt_metadata, Mapping):
            read_roots = _prompt_scope_paths(
                request, raw_prompt_metadata, "tool_read_roots"
            )
            write_paths = _prompt_scope_paths(
                request, raw_prompt_metadata, "tool_write_paths"
            )
            forbidden_roots = _prompt_scope_paths(
                request, raw_prompt_metadata, "tool_forbidden_roots"
            )
            operational_roots = _prompt_scope_paths(
                request, raw_prompt_metadata, "tool_operational_roots"
            )
            operational_read_paths = _prompt_scope_paths(
                request, raw_prompt_metadata, "tool_operational_read_paths"
            )
            operational_metadata_paths = _prompt_scope_paths(
                request, raw_prompt_metadata, "tool_operational_metadata_paths"
            )

        sandbox_exec = (
            _sandbox_exec_path()
            if forbidden_roots and not isolated_workspace
            else None
        )
        if forbidden_roots and not isolated_workspace and sandbox_exec is None:
            _unlink_if_present(final_path)
            return CliRunResult(
                exit_code=125,
                stdout="",
                stderr="workspace synthesis host boundary is unavailable",
                metadata={"workspace_synthesis_boundary": "unavailable"},
            )

        unsafe = self._config.llm.tool_policy.allow_unsafe_host_execution
        permission_profile = None
        if forbidden_roots and not unsafe:
            permission_profile = (
                _PRODUCT_PLANE_PERMISSION_PROFILE,
                _codex_product_plane_permission_profile(
                    read_roots=read_roots,
                    write_paths=write_paths,
                    forbidden_roots=forbidden_roots,
                    operational_roots=operational_roots,
                    operational_read_paths=operational_read_paths,
                    operational_metadata_paths=operational_metadata_paths,
                ),
            )

        cmd = build_llm_cli_command(
            "codex",
            self._bin,
            request.prompt,
            self._config.llm.tool_policy,
            codex_json=True,
            codex_model=model,
            codex_skip_git_repo_check=allow_non_git_cwd,
            codex_ignore_user_config=isolated_user_config,
            codex_permission_profile=permission_profile,
            output_last_message=final_path or None,
        )
        if forbidden_roots and unsafe and not isolated_workspace:
            assert sandbox_exec is not None
            cmd = [
                sandbox_exec,
                "-p",
                _workspace_sandbox_profile(
                    forbidden_roots,
                    read_roots=read_roots,
                    write_paths=write_paths,
                ),
                *cmd,
            ]
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
        token_usage_details: dict[str, int] = {}

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
                    token_usage_details = dict(event.token_usage_details)
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
            _unlink_if_present(final_path)

        metadata: dict[str, object] = {
            "task_complete": saw_task_complete,
            # Codex JSON events do not reliably include a response model.
            # Preserve the explicitly requested model for durable telemetry.
            "request_model": model or "",
        }
        if token_usage_details:
            metadata["token_usage_details"] = token_usage_details
        metadata["isolated_user_config"] = isolated_user_config

        return CliRunResult(
            exit_code=(
                0 if saw_task_complete else (-1 if timed_out else int(proc.returncode))
            ),
            stdout="\n".join(chunk for chunk in stdout_chunks if chunk),
            stderr="\n".join(chunk for chunk in stderr_chunks if chunk),
            token_usage=token_usage,
            timed_out=timed_out,
            metadata=metadata,
        )


def _codex_model_for_request(request: CliRunRequest) -> str | None:
    metadata = request.metadata.get("prompt_metadata")
    if not isinstance(metadata, dict):
        return None
    tier = metadata.get("model_tier")
    if not isinstance(tier, str):
        return None
    return _MODEL_TIER_TO_CODEX_MODEL.get(tier.strip().lower())


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


def _codex_product_plane_permission_profile(
    *,
    read_roots: tuple[str, ...],
    write_paths: tuple[str, ...],
    forbidden_roots: tuple[str, ...],
    operational_roots: tuple[str, ...],
    operational_read_paths: tuple[str, ...],
    operational_metadata_paths: tuple[str, ...],
) -> str:
    """Build one native Codex profile for workspace and product-plane scope."""
    access: dict[str, str] = {}

    for path in (*read_roots, *operational_roots, *operational_read_paths):
        access[path] = "read"
    for path in write_paths:
        access[path] = "write"
    metadata_visible = set(operational_metadata_paths)
    explicitly_authorized = {
        *read_roots,
        *write_paths,
        *operational_roots,
        *operational_read_paths,
    }
    for path in forbidden_roots:
        if path not in metadata_visible:
            access[path] = "deny"
            continue

        # Named runtime helpers use ordinary file metadata checks before opening
        # an authenticated config path. A read-only root exposes that metadata
        # and prevents new children; every existing unauthenticated child is
        # snapshotted as denied. More-specific authenticated paths remain usable.
        try:
            children = tuple(Path(path).iterdir())
        except OSError:
            access[path] = "deny"
            continue
        access[path] = "read"
        for child in children:
            child_path = str(child)
            if child_path not in explicitly_authorized:
                access[child_path] = "deny"

    filesystem = ",".join(
        f"{json.dumps(path)}={json.dumps(access[path])}" for path in sorted(access)
    )
    return (
        f'{{extends=":workspace",filesystem={{{filesystem}}},'
        "network={enabled=true}}"
    )


def _unlink_if_present(path: str) -> None:
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def _is_empty_isolated_directory(path: str) -> bool:
    root = Path(path)
    try:
        return (
            root.is_dir()
            and not root.is_symlink()
            and next(root.iterdir(), None) is None
        )
    except OSError:
        return False


_ISOLATED_WORKSPACE_SCOPE_KEYS = (
    "tool_read_roots",
    "tool_write_paths",
    "tool_forbidden_roots",
    "tool_operational_roots",
    "tool_operational_read_paths",
    "tool_operational_metadata_paths",
)


def _isolated_workspace_error(
    request: CliRunRequest,
    prompt_metadata: object,
    *,
    allow_unsafe_host_execution: bool,
) -> str | None:
    """Validate the narrow profile that delegates containment to Codex itself."""
    if allow_unsafe_host_execution:
        return "isolated workspace rejects unsafe host execution policy"
    if not _is_empty_isolated_directory(request.cwd):
        return "isolated workspace requires an empty isolated working directory"
    if not isinstance(prompt_metadata, Mapping):
        return None

    root = Path(request.cwd).resolve()
    for key in _ISOLATED_WORKSPACE_SCOPE_KEYS:
        for raw_path in _prompt_scope_paths(request, prompt_metadata, key):
            if not Path(raw_path).is_relative_to(root):
                return (
                    "isolated workspace requires all prompt tool scopes inside "
                    "that directory"
                )
    return None


@dataclass(frozen=True)
class _CodexEvent:
    text: str
    task_complete: bool = False
    token_usage: int | None = None
    token_usage_details: dict[str, int] = field(default_factory=dict)


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
            details = _extract_token_usage_details(payload.get("info"))
            return _CodexEvent(
                "",
                token_usage=details.get("total_tokens"),
                token_usage_details=details,
            )

    if event.get("type") == "turn.completed":
        details = _extract_token_usage_details(event.get("usage"))
        return _CodexEvent(
            "",
            token_usage=details.get("total_tokens"),
            token_usage_details=details,
        )

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


def _extract_token_usage_details(info: object) -> dict[str, int]:
    if not isinstance(info, dict):
        return {}
    nested = info.get("total_token_usage")
    usage = nested if isinstance(nested, dict) else info
    details: dict[str, int] = {}
    for key in (
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    ):
        value = usage.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        details[key] = max(0, int(value))
    if "total_tokens" not in details and (
        "input_tokens" in details or "output_tokens" in details
    ):
        details["total_tokens"] = details.get("input_tokens", 0) + details.get(
            "output_tokens", 0
        )
    return details


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
