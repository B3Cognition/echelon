from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Mapping

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.ai_cli_backends.codex_capture import (
    CodexCaptureError,
    capture_codex_pipes,
)
from harness.ai_cli_backends.codex_constrained import (
    ConstrainedRequestError,
    prepare_constrained_request,
)
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
    constrained_execution_contract_id = "codex-constrained-prompt-v1"

    def __init__(self, config: HarnessConfig) -> None:
        self._config = config
        self._bin = shutil.which("codex") or "codex"

    def model_for_tier(self, tier: str) -> str | None:
        """Resolve neutral Prosaic model intent inside the provider adapter."""
        if not isinstance(tier, str):
            return None
        return _MODEL_TIER_TO_CODEX_MODEL.get(tier.strip().lower())

    def run_prompt(self, request: CliRunRequest) -> CliRunResult:
        return self._run_codex(request, use_final_message=True)

    def run_agent(self, request: CliRunRequest) -> CliRunResult:
        return self._run_codex(request, use_final_message=True)

    def run_prompt_screened(
        self,
        request: CliRunRequest,
        *,
        screen_output: Callable[[bytes], bytes],
        max_capture_bytes: int,
    ) -> CliRunResult:
        timeout = request.timeout_s
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
            or isinstance(max_capture_bytes, bool)
            or not isinstance(max_capture_bytes, int)
            or max_capture_bytes <= 0
            or not callable(screen_output)
        ):
            return _screened_failure("invalid_request")
        return self._run_codex(
            request,
            use_final_message=False,
            screen_output=screen_output,
            max_capture_bytes=max_capture_bytes,
        )

    def run_constrained_prompt(
        self,
        request: CliRunRequest,
        *,
        model: str,
        screen_output: Callable[[bytes], bytes],
        max_input_bytes: int,
        max_capture_bytes: int,
        screen_input: Callable[[bytes], bytes] | None = None,
    ) -> CliRunResult:
        """Run one opt-in bounded request through native Codex stdin."""
        try:
            prepared = prepare_constrained_request(
                self._bin,
                request,
                model=model,
                screen_output=screen_output,
                max_input_bytes=max_input_bytes,
                max_capture_bytes=max_capture_bytes,
                tool_policy=self._config.llm.tool_policy,
                screen_input=screen_input,
            )
        except ConstrainedRequestError as exc:
            return _screened_failure(exc.reason)

        try:
            proc = subprocess.Popen(
                list(prepared.command),
                cwd=request.cwd,
                env=prepared.env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception:
            return _screened_failure("process_start_error")

        return _run_screened_process(
            proc,
            screen_output=screen_output,
            max_capture_bytes=max_capture_bytes,
            timeout_s=float(request.timeout_s),
            request_model=model,
            isolated_user_config=True,
            input_bytes=prepared.prompt_bytes,
        )

    def _run_codex(
        self,
        request: CliRunRequest,
        *,
        use_final_message: bool,
        screen_output: Callable[[bytes], bytes] | None = None,
        max_capture_bytes: int | None = None,
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
        isolated_workspace_error = (
            _isolated_workspace_error(request, raw_prompt_metadata)
            if isolated_workspace
            else None
        )
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
        exclusive_write_scope = False
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
            exclusive_write_scope = (
                raw_prompt_metadata.get("tool_write_scope_exclusive") is True
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

        tool_policy = self._config.llm.tool_policy
        if isolated_workspace and tool_policy.allow_unsafe_host_execution:
            tool_policy = replace(
                tool_policy,
                allow_unsafe_host_execution=False,
                approval_reason=None,
            )
        unsafe = tool_policy.allow_unsafe_host_execution
        if exclusive_write_scope and unsafe:
            # A review role must not be able to escape its artifact boundary
            # merely because the surrounding project permits host execution.
            tool_policy = replace(
                tool_policy,
                allow_unsafe_host_execution=False,
                approval_reason=None,
            )
            unsafe = False
        permission_profile = None
        if (
            (forbidden_roots or exclusive_write_scope)
            and not unsafe
            and not isolated_workspace
        ):
            permission_profile = (
                _PRODUCT_PLANE_PERMISSION_PROFILE,
                _codex_product_plane_permission_profile(
                    workspace_root=str(Path(request.cwd).resolve()),
                    read_roots=read_roots,
                    write_paths=write_paths,
                    forbidden_roots=forbidden_roots,
                    operational_roots=operational_roots,
                    operational_read_paths=operational_read_paths,
                    operational_metadata_paths=operational_metadata_paths,
                    exclusive_write_scope=exclusive_write_scope,
                ),
            )

        cmd = build_llm_cli_command(
            "codex",
            self._bin,
            request.prompt,
            tool_policy,
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
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=request.cwd,
                env=dict(request.env),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception:
            if screen_output is not None:
                return _screened_failure("process_start_error")
            raise

        if screen_output is not None:
            assert max_capture_bytes is not None
            return _run_screened_process(
                proc,
                screen_output=screen_output,
                max_capture_bytes=max_capture_bytes,
                timeout_s=float(request.timeout_s),
                request_model=model,
                isolated_user_config=isolated_user_config,
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
                if event.diagnostic:
                    print(event.diagnostic, flush=True)
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


_SCREENED_FAILURE_TEXT = "screened Codex capture failed"


def _screened_failure(
    reason: str,
    *,
    timed_out: bool = False,
    token_usage: int | None = None,
    token_usage_details: Mapping[str, int] | None = None,
    token_usage_status: str | None = None,
) -> CliRunResult:
    metadata: dict[str, object] = {"failure_reason": reason}
    if token_usage_details:
        metadata["token_usage_details"] = dict(token_usage_details)
        metadata["token_usage_status"] = token_usage_status or "untrusted"
    return CliRunResult(
        exit_code=124 if timed_out else 125,
        stdout="",
        stderr=_SCREENED_FAILURE_TEXT,
        token_usage=token_usage,
        timed_out=timed_out,
        metadata=metadata,
    )


def _screen_identical(
    screen_output: Callable[[bytes], bytes], value: bytes
) -> bool:
    try:
        screened = screen_output(value)
    except Exception:
        return False
    return type(screened) is bytes and screened == value


class _JsonObjectPairs(list[tuple[str, object]]):
    """JSON object representation that retains duplicate keys until screening."""


class _DuplicateJsonKey(ValueError):
    pass


def _screened_json_event(
    raw_record: bytes,
    screen_output: Callable[[bytes], bytes],
) -> tuple[dict[str, object] | None, str | None]:
    try:
        decoded = json.loads(
            raw_record.decode("utf-8", errors="strict"),
            object_pairs_hook=_JsonObjectPairs,
        )
        decoded_record = _encode_json_preserving_pairs(decoded)
    except (UnicodeError, ValueError, TypeError, OverflowError, RecursionError):
        return None, "malformed_capture"
    if not _screen_identical(screen_output, decoded_record):
        return None, "screen_rejected"
    try:
        event = _unique_json_value(decoded)
    except (_DuplicateJsonKey, RecursionError):
        return None, "malformed_capture"
    if not isinstance(event, dict):
        return None, "malformed_capture"
    return event, None


def _encode_json_preserving_pairs(value: object) -> bytes:
    if isinstance(value, _JsonObjectPairs):
        members = (
            json.dumps(key, ensure_ascii=False).encode("utf-8")
            + b":"
            + _encode_json_preserving_pairs(member)
            for key, member in value
        )
        return b"{" + b",".join(members) + b"}"
    if isinstance(value, list):
        return b"[" + b",".join(_encode_json_preserving_pairs(item) for item in value) + b"]"
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _unique_json_value(value: object) -> object:
    if isinstance(value, _JsonObjectPairs):
        result: dict[str, object] = {}
        for key, member in value:
            if key in result:
                raise _DuplicateJsonKey
            result[key] = _unique_json_value(member)
        return result
    if isinstance(value, list):
        return [_unique_json_value(item) for item in value]
    return value


def _run_screened_process(
    proc: subprocess.Popen,
    *,
    screen_output: Callable[[bytes], bytes],
    max_capture_bytes: int,
    timeout_s: float,
    request_model: str | None,
    isolated_user_config: bool,
    input_bytes: bytes | None = None,
) -> CliRunResult:
    try:
        captured = capture_codex_pipes(
            proc,
            max_capture_bytes=max_capture_bytes,
            timeout_s=timeout_s,
            input_bytes=input_bytes,
        )
    except CodexCaptureError as exc:
        return _screened_failure(exc.reason, timed_out=exc.timed_out)

    stdout = captured.stdout
    stderr = captured.stderr
    failure_reason: str | None = None
    if not _screen_identical(screen_output, stdout):
        failure_reason = "screen_rejected"
    if not _screen_identical(screen_output, stderr):
        failure_reason = failure_reason or "screen_rejected"

    final_text: str | None = None
    pending_modern_answer: str | None = None
    modern_turn_unfinished = False
    usage = _ScreenedUsage()
    try:
        stderr.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        failure_reason = failure_reason or "malformed_capture"
    for raw_record in stdout.splitlines():
        if not raw_record.strip():
            continue
        if not _screen_identical(screen_output, raw_record):
            failure_reason = failure_reason or "screen_rejected"
            usage.mark_untrusted()
            continue
        event, parse_failure = _screened_json_event(raw_record, screen_output)
        if parse_failure is not None:
            failure_reason = failure_reason or parse_failure
            usage.mark_untrusted()
            continue
        assert event is not None
        if not _screened_event_is_inspectable(event):
            failure_reason = failure_reason or "malformed_capture"
            usage.mark_untrusted()
            continue

        event_type = event.get("type")
        item = event.get("item")
        if event_type in {"error", "turn.failed"} or (
            isinstance(item, dict) and item.get("type") == "error"
        ):
            failure_reason = failure_reason or "provider_event_failure"
            usage.fail_modern()
        if isinstance(item, dict) and item.get("type") in {
            "command_execution",
            "file_change",
            "mcp_tool_call",
            "web_search",
        }:
            failure_reason = failure_reason or "tool_event"
        if event_type == "turn.started":
            final_text = None
            pending_modern_answer = None
            modern_turn_unfinished = True
            usage.start_modern()
        if event_type == "item.completed" and isinstance(item, dict):
            if item.get("type") == "agent_message":
                candidate = item.get("text")
                if isinstance(candidate, str):
                    pending_modern_answer = candidate
                    modern_turn_unfinished = True

        payload = event.get("payload")
        payload_type = payload.get("type") if isinstance(payload, dict) else None
        if event_type == "event_msg" and isinstance(payload_type, str):
            if _legacy_tool_event(payload_type):
                failure_reason = failure_reason or "tool_event"
            if _legacy_failure_event(payload_type):
                failure_reason = failure_reason or "provider_event_failure"
            if payload_type == "task_complete":
                candidate = payload.get("last_agent_message")
                if isinstance(candidate, str):
                    final_text = candidate
                    pending_modern_answer = None
                    modern_turn_unfinished = False

        if event_type == "turn.completed":
            final_text = pending_modern_answer
            pending_modern_answer = None
            modern_turn_unfinished = False
            usage.add_modern(event.get("usage"))
        elif event_type == "event_msg" and payload_type == "token_count":
            assert isinstance(payload, dict)
            usage.set_legacy(payload.get("info"))

    token_usage, token_usage_details, token_usage_status = usage.result()
    if failure_reason is not None:
        return _screened_failure(
            failure_reason,
            token_usage=token_usage,
            token_usage_details=token_usage_details,
            token_usage_status=token_usage_status,
        )

    if captured.returncode != 0:
        return _screened_failure(
            "provider_exit",
            token_usage=token_usage,
            token_usage_details=token_usage_details,
            token_usage_status=token_usage_status,
        )
    if final_text is None or modern_turn_unfinished:
        return _screened_failure(
            "missing_final_answer",
            token_usage=token_usage,
            token_usage_details=token_usage_details,
            token_usage_status=token_usage_status,
        )
    try:
        final_bytes = final_text.encode("utf-8")
    except UnicodeEncodeError:
        return _screened_failure(
            "malformed_capture",
            token_usage=token_usage,
            token_usage_details=token_usage_details,
            token_usage_status=token_usage_status,
        )
    if not _screen_identical(screen_output, final_bytes):
        return _screened_failure(
            "screen_rejected",
            token_usage=token_usage,
            token_usage_details=token_usage_details,
            token_usage_status=token_usage_status,
        )

    metadata: dict[str, object] = {
        "task_complete": True,
        "request_model": request_model or "",
        "isolated_user_config": isolated_user_config,
    }
    if token_usage_details:
        metadata["token_usage_details"] = token_usage_details
        metadata["token_usage_status"] = token_usage_status
    return CliRunResult(
        exit_code=0,
        stdout=final_text,
        stderr="",
        token_usage=token_usage,
        metadata=metadata,
    )


class _ScreenedUsage:
    """Aggregate modern turn observations without double-counting legacy snapshots."""

    def __init__(self) -> None:
        self._modern_count = 0
        self._modern_complete = True
        self._modern_totals_complete = True
        self._stream_complete = True
        self._modern_pending = False
        self._modern_failed = False
        self._known_modern_total = 0
        self._has_known_modern_total = False
        self._modern_details: dict[str, int] = {}
        self._legacy: tuple[int | None, dict[str, int], str] | None = None
        # Mixed formats may overlap. Preserve bounds before incomplete or
        # inconsistent later observations lose their component evidence.
        self._modern_lower_bound: int | None = None
        self._legacy_lower_bound: tuple[int, dict[str, int]] | None = None

    def mark_untrusted(self) -> None:
        self._stream_complete = False

    def start_modern(self) -> None:
        self._modern_pending = True

    def fail_modern(self) -> None:
        self._modern_pending = False
        self._modern_failed = True

    def add_modern(self, raw: object) -> None:
        self._modern_pending = False
        self._modern_count += 1
        total, details, status = _screened_usage_observation(raw)
        lower_bound = _screened_usage_lower_bound(total, details)
        if lower_bound is not None:
            # Modern completed turns are disjoint; total and components within
            # one turn are alternative bounds, not additional spend.
            self._modern_lower_bound = (self._modern_lower_bound or 0) + lower_bound
        if total is None:
            self._modern_complete = False
            self._modern_totals_complete = False
        else:
            self._known_modern_total += total
            self._has_known_modern_total = True
        if status != "trusted_exact":
            self._modern_complete = False
        for key, value in details.items():
            self._modern_details[key] = self._modern_details.get(key, 0) + value

    def set_legacy(self, raw: object) -> None:
        observed = _screened_usage_observation(raw)
        total, details, _ = observed
        lower_bound = _screened_usage_lower_bound(total, details)
        if lower_bound is not None and (
            self._legacy_lower_bound is None or lower_bound > self._legacy_lower_bound[0]
        ):
            # Legacy snapshots are cumulative, so retain a maximum, never a sum
            # or a synthetic combination of components from different snapshots.
            self._legacy_lower_bound = (lower_bound, dict(details))
        if self._legacy is None:
            self._legacy = observed
            return
        previous_total, previous_details, previous_status = self._legacy
        total, details, status = observed
        if total is None:
            self._legacy = (
                previous_total,
                previous_details or details,
                "untrusted" if previous_total is not None or details else previous_status,
            )
            return
        if previous_total is None or total > previous_total:
            self._legacy = (total, details, status)
            return
        if total == previous_total and status == "trusted_exact":
            self._legacy = observed
            return
        # Legacy token_count events are cumulative snapshots. A lower or
        # incomplete later snapshot cannot refund the greatest known spend.
        self._legacy = (previous_total, previous_details, "untrusted")

    def result(self) -> tuple[int | None, dict[str, int], str]:
        if self._modern_count:
            details = dict(self._modern_details)
            if self._modern_totals_complete:
                total = details.get("total_tokens")
            else:
                details.pop("total_tokens", None)
                # A later incomplete turn must not erase a complete earlier
                # observation. This is a lower bound only, so it remains
                # explicitly untrusted downstream.
                total = (
                    self._known_modern_total
                    if self._has_known_modern_total
                    else None
                )
            if self._legacy is not None:
                total = self._modern_lower_bound
                # Both formats can describe overlapping spend. Retain the
                # larger observed lower bound with its observed breakdown,
                # never sum the representations or let a partial turn refund it.
                if self._legacy_lower_bound is not None:
                    legacy_total, legacy_details = self._legacy_lower_bound
                    if total is None or legacy_total > total:
                        return legacy_total, dict(legacy_details), "untrusted"
                return total, details, "untrusted"
            if not details:
                return None, {}, "unavailable"
            status = (
                "trusted_exact"
                if (
                    total is not None
                    and self._modern_complete
                    and self._stream_complete
                    and not self._modern_pending
                    and not self._modern_failed
                    and self._legacy is None
                )
                else "untrusted"
            )
            return total, details, status
        if self._legacy is not None:
            total, details, status = self._legacy
            if details and not self._stream_complete:
                status = "untrusted"
            return total, details, status
        return None, {}, "unavailable"


def _screened_usage_lower_bound(total: int | None, details: Mapping[str, int]) -> int | None:
    """Compare already-screened billable counts without recounting subcomponents."""
    if total is None and "input_tokens" not in details and "output_tokens" not in details:
        return None
    return max(total or 0, details.get("input_tokens", 0) + details.get("output_tokens", 0))


def _screened_usage_observation(
    raw: object,
) -> tuple[int | None, dict[str, int], str]:
    source = raw.get("total_token_usage") if isinstance(raw, dict) else None
    values = source if isinstance(source, dict) else raw
    if not isinstance(values, dict):
        return None, {}, "unavailable"

    details: dict[str, int] = {}
    for key in (
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    ):
        value = values.get(key)
        if type(value) is int and value >= 0:
            details[key] = value
    if (
        "total_tokens" not in details
        and "input_tokens" in details
        and "output_tokens" in details
    ):
        details["total_tokens"] = (
            details["input_tokens"] + details["output_tokens"]
        )

    total = details.get("total_tokens")
    if not details:
        return None, {}, "unavailable"

    required = (
        "input_tokens",
        "output_tokens",
        "cached_input_tokens",
        "reasoning_output_tokens",
    )
    exact = total is not None and all(key in details for key in required)
    if "total_tokens" in values:
        explicit_total = values.get("total_tokens")
        exact = (
            exact
            and type(explicit_total) is int
            and explicit_total >= 0
            and explicit_total
            == details["input_tokens"] + details["output_tokens"]
        )
    if exact:
        exact = (
            details["cached_input_tokens"] <= details["input_tokens"]
            and details["reasoning_output_tokens"] <= details["output_tokens"]
        )
    return total, details, "trusted_exact" if exact else "untrusted"


def _screened_event_is_inspectable(event: dict[object, object]) -> bool:
    event_type = event.get("type")
    if not isinstance(event_type, str) or not event_type:
        return False
    if "item" in event:
        item = event.get("item")
        if not isinstance(item, dict) or not isinstance(item.get("type"), str):
            return False
    if event_type in {"item.started", "item.completed"}:
        item = event.get("item")
        if not isinstance(item, dict):
            return False
        if event_type == "item.completed" and item.get("type") == "agent_message":
            return isinstance(item.get("text"), str)
        return True
    if event_type == "turn.completed":
        usage = event.get("usage")
        return usage is None or isinstance(usage, dict)
    if event_type == "event_msg":
        payload = event.get("payload")
        if not isinstance(payload, dict) or not isinstance(payload.get("type"), str):
            return False
        if payload.get("type") == "task_complete":
            return isinstance(payload.get("last_agent_message"), str)
        return True
    return True


def _legacy_tool_event(payload_type: str) -> bool:
    return payload_type == "tool" or payload_type.startswith(
        ("exec_command_", "tool_", "mcp_tool_", "web_search_", "apply_patch_")
    )


def _legacy_failure_event(payload_type: str) -> bool:
    return payload_type == "error" or payload_type.endswith("_error")


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
    workspace_root: str,
    read_roots: tuple[str, ...],
    write_paths: tuple[str, ...],
    forbidden_roots: tuple[str, ...],
    operational_roots: tuple[str, ...],
    operational_read_paths: tuple[str, ...],
    operational_metadata_paths: tuple[str, ...],
    exclusive_write_scope: bool = False,
) -> str:
    """Build one native Codex profile for workspace and product-plane scope."""
    access: dict[str, str] = {}

    # The profile extends `:workspace`, which is otherwise writable. A root
    # read rule makes explicitly declared report paths the only writable
    # product-plane paths while preserving normal read access for review work.
    if exclusive_write_scope:
        access[workspace_root] = "read"

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
) -> str | None:
    """Validate the narrow profile that delegates containment to Codex itself."""
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
    diagnostic: str = ""


def _codex_event(line: str) -> _CodexEvent:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return _CodexEvent(line)

    item = event.get("item")
    if isinstance(item, dict) and item.get("type") == "command_execution":
        return _CodexEvent("", diagnostic=_codex_command_event_text(event, item))

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
    if failed and not debug:
        return header
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
