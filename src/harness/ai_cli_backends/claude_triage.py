"""Isolated Claude review-triage execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Mapping

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.ai_cli_backends.codex_capture import CodexCaptureError, capture_codex_pipes
from harness.llm_tool_policy import (
    LlmToolPolicy,
    inject_llm_tool_policy_preamble,
)


_MODEL_TIER_TO_CLAUDE_MODEL = {
    "fast": "haiku",
    "balanced": "sonnet",
    "strong": "opus",
}
_EFFORT_LEVELS = frozenset({"low", "medium", "high"})
_MAX_INPUT_BYTES = 1024 * 1024
_MAX_CAPTURE_BYTES = 256 * 1024
_PROVIDER_METADATA_KEYS = frozenset(
    {"model", "provider", "model_id", "model_name", "reasoning_effort"}
)
_SENSITIVE_ENV_EXACT = frozenset(
    {"CLAUDE_CODE_ENTRYPOINT", "TRACEPARENT", "TRACESTATE"}
)


@dataclass(frozen=True)
class PreparedClaudeTriageRequest:
    command: tuple[str, ...]
    env: dict[str, str]
    prompt_bytes: bytes


def _sandbox_exec_path() -> str | None:
    return shutil.which("sandbox-exec")


def run_claude_review_triage(
    bin_: str,
    request: CliRunRequest,
    *,
    tool_policy: LlmToolPolicy,
) -> CliRunResult:
    try:
        prepared = prepare_claude_triage_request(
            bin_, request, tool_policy=tool_policy
        )
    except _ClaudeTriageError as exc:
        return _failure(exc.reason)

    try:
        process = subprocess.Popen(
            list(prepared.command),
            cwd=request.cwd,
            env=prepared.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception:
        return _failure("process_start_error")

    try:
        captured = capture_codex_pipes(
            process,
            max_capture_bytes=_MAX_CAPTURE_BYTES,
            timeout_s=float(request.timeout_s),
            input_bytes=prepared.prompt_bytes,
        )
    except CodexCaptureError as exc:
        return _failure(exc.reason, timed_out=exc.timed_out)
    return _parse_claude_triage_capture(
        captured.stdout,
        captured.stderr,
        returncode=captured.returncode,
        request_model=prepared.command[
            prepared.command.index("--model") + 1
        ],
    )


def prepare_claude_triage_request(
    bin_: str,
    request: CliRunRequest,
    *,
    tool_policy: LlmToolPolicy,
) -> PreparedClaudeTriageRequest:
    isolation = _sandbox_exec_path()
    if sys.platform != "darwin" or isolation is None:
        raise _ClaudeTriageError("isolation_unavailable")
    metadata = _review_triage_metadata(request)
    if metadata is None or not _valid_request(request):
        raise _ClaudeTriageError("invalid_request")
    tier, effort = metadata
    safe_policy = replace(
        tool_policy,
        allow_unsafe_host_execution=False,
        approval_reason=None,
    )
    try:
        prompt_bytes = inject_llm_tool_policy_preamble(
            request.prompt, safe_policy
        ).encode("utf-8", errors="strict")
    except (AttributeError, TypeError, UnicodeError, ValueError):
        raise _ClaudeTriageError("invalid_request") from None
    if len(prompt_bytes) > _MAX_INPUT_BYTES:
        raise _ClaudeTriageError("input_overflow")

    model = _MODEL_TIER_TO_CLAUDE_MODEL[tier]
    command = (
        isolation,
        "-p",
        _sandbox_profile(request.cwd),
        bin_,
        "-p",
        "--input-format",
        "text",
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        model,
        "--effort",
        effort,
        "--safe-mode",
        "--setting-sources",
        "",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--permission-mode",
        "dontAsk",
        "--tools",
        "",
        "--no-session-persistence",
        "--no-chrome",
    )
    return PreparedClaudeTriageRequest(
        command=command,
        env=_sanitized_environment(request.env),
        prompt_bytes=prompt_bytes,
    )


class _ClaudeTriageError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _valid_request(request: object) -> bool:
    if not isinstance(request, CliRunRequest):
        return False
    timeout = request.timeout_s
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
        or type(request.prompt) is not str
        or not request.prompt
        or not _is_empty_nonsymlink_directory(request.cwd)
    ):
        return False
    try:
        _sanitized_environment(request.env)
    except _ClaudeTriageError:
        return False
    return True


def _review_triage_metadata(request: CliRunRequest) -> tuple[str, str] | None:
    if set(request.metadata) != {"prompt_metadata"}:
        return None
    metadata = request.metadata.get("prompt_metadata")
    if not isinstance(metadata, Mapping):
        return None
    if _PROVIDER_METADATA_KEYS.intersection(metadata) or any(
        type(key) is not str
        or key.strip().lower().startswith(("tool_", "source_"))
        for key in metadata
    ):
        return None
    tier = metadata.get("model_tier")
    effort = metadata.get("effort")
    if (
        type(tier) is not str
        or tier not in _MODEL_TIER_TO_CLAUDE_MODEL
        or type(effort) is not str
        or effort not in _EFFORT_LEVELS
    ):
        return None
    return tier, effort


def _is_empty_nonsymlink_directory(raw_path: object) -> bool:
    if type(raw_path) is not str or not raw_path:
        return False
    path = Path(raw_path)
    try:
        return (
            path.is_dir()
            and not path.is_symlink()
            and next(path.iterdir(), None) is None
        )
    except OSError:
        return False


def _sanitized_environment(environment: object) -> dict[str, str]:
    if not isinstance(environment, Mapping):
        raise _ClaudeTriageError("invalid_request")
    sanitized: dict[str, str] = {}
    try:
        for key, value in environment.items():
            if (
                type(key) is not str
                or type(value) is not str
                or not key
                or "=" in key
                or "\0" in key
                or "\0" in value
            ):
                raise _ClaudeTriageError("invalid_request")
            upper = key.upper()
            if (
                upper in _SENSITIVE_ENV_EXACT
                or upper.startswith("OTEL_")
                or (
                    upper.startswith("CLAUDE_CODE_")
                    and upper != "CLAUDE_CODE_USE_BEDROCK"
                    and upper != "CLAUDE_CODE_USE_VERTEX"
                    and upper != "CLAUDE_CODE_USE_FOUNDRY"
                )
            ):
                continue
            sanitized[key] = value
    except _ClaudeTriageError:
        raise
    except Exception:
        raise _ClaudeTriageError("invalid_request") from None
    return sanitized


def _sandbox_profile(cwd: str) -> str:
    quoted = json.dumps(str(Path(cwd).resolve()))
    outside_invocation = " ".join(
        (f"(require-not (literal {quoted}))", f"(require-not (subpath {quoted}))")
    )
    return "\n".join(
        (
            "(version 1)",
            "(deny default)",
            "(allow process*)",
            f"(allow file-read* (require-all {outside_invocation}))",
            f"(allow file-write* (require-all {outside_invocation}))",
            f"(allow file-read-metadata (literal {quoted}))",
            "(allow network*)",
            "(allow sysctl-read)",
            "(allow mach-lookup)",
            "(allow ipc-posix*)",
        )
    )


def _parse_claude_triage_capture(
    stdout: bytes,
    stderr: bytes,
    *,
    returncode: int,
    request_model: str,
) -> CliRunResult:
    try:
        stderr_text = stderr.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError:
        return _failure("malformed_capture")

    final_event: dict[str, object] | None = None
    failure_reason: str | None = None
    usage: dict[str, int] = {}
    for raw_line in stdout.splitlines():
        if not raw_line.strip():
            continue
        event = _strict_json_object(raw_line)
        if event is None:
            failure_reason = failure_reason or "malformed_capture"
            continue
        event_type = event.get("type")
        if type(event_type) is not str:
            failure_reason = failure_reason or "malformed_capture"
            continue
        if _is_tool_event(event):
            failure_reason = failure_reason or "tool_event"
        observed_usage = _event_usage(event)
        if _usage_total(observed_usage) is not None and (
            _usage_total(usage) is None
            or _usage_total(observed_usage) > _usage_total(usage)
        ):
            usage = observed_usage
        if event_type == "result":
            if final_event is not None:
                failure_reason = failure_reason or "malformed_capture"
            final_event = event

    token_usage = _usage_total(usage)
    if final_event is not None and (
        final_event.get("is_error") is True
        or final_event.get("subtype") != "success"
    ):
        failure_reason = failure_reason or "provider_event_failure"
    if failure_reason is None and returncode != 0:
        failure_reason = "provider_exit"
    final_text = final_event.get("result") if final_event is not None else None
    if failure_reason is None and (
        type(final_text) is not str or not final_text.strip()
    ):
        failure_reason = "missing_final_answer"
    if failure_reason is not None:
        return _failure(
            failure_reason,
            token_usage=token_usage,
            usage=usage,
            stderr=stderr_text,
        )
    assert isinstance(final_event, dict) and isinstance(final_text, str)
    raw_cost = final_event.get("total_cost_usd")
    cost = (
        float(raw_cost)
        if type(raw_cost) in {int, float} and math.isfinite(float(raw_cost))
        else 0.0
    )
    metadata: dict[str, object] = {
        "task_complete": True,
        "request_model": request_model,
        "isolated_user_config": True,
    }
    if usage:
        metadata["token_usage_details"] = usage
        metadata["token_usage_status"] = "trusted_exact"
    return CliRunResult(
        exit_code=0,
        stdout=final_text.strip(),
        stderr=stderr_text,
        token_usage=token_usage,
        cost_usd=cost,
        metadata=metadata,
    )


class _ObjectPairs(list[tuple[str, object]]):
    pass


def _strict_json_object(raw: bytes) -> dict[str, object] | None:
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"), object_pairs_hook=_ObjectPairs
        )
        decoded = _unique_object(value)
        return decoded if isinstance(decoded, dict) else None
    except (UnicodeError, ValueError, TypeError, RecursionError):
        return None


def _unique_object(value: object) -> object:
    if isinstance(value, _ObjectPairs):
        result: dict[str, object] = {}
        for key, member in value:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = _unique_object(member)
        return result
    if isinstance(value, list):
        return [_unique_object(member) for member in value]
    return value


def _is_tool_event(event: Mapping[str, object]) -> bool:
    if _contains_tool_marker(event):
        return True
    event_type = event.get("type")
    tools = event.get("tools")
    return event_type == "system" and isinstance(tools, list) and bool(tools)


def _contains_tool_marker(value: object) -> bool:
    if isinstance(value, Mapping):
        marker = value.get("type")
        if isinstance(marker, str) and (
            "tool" in marker.lower()
            or marker.lower()
            in {"bash", "computer_use", "file_change", "web_search"}
        ):
            return True
        return any(_contains_tool_marker(member) for member in value.values())
    if isinstance(value, list):
        return any(_contains_tool_marker(member) for member in value)
    return False


def _event_usage(event: Mapping[str, object]) -> dict[str, int]:
    usage = _usage_details(event.get("usage"))
    message = event.get("message")
    if isinstance(message, Mapping):
        message_usage = _usage_details(message.get("usage"))
        if (_usage_total(message_usage) or -1) > (_usage_total(usage) or -1):
            return message_usage
    return usage


def _usage_details(raw: object) -> dict[str, int]:
    if not isinstance(raw, Mapping):
        return {}
    details: dict[str, int] = {}
    for key in (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ):
        value = raw.get(key)
        if type(value) is int and value >= 0:
            details[key] = value
    if "input_tokens" in details and "output_tokens" in details:
        details["total_tokens"] = sum(
            details.get(key, 0)
            for key in (
                "input_tokens",
                "output_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            )
        )
    return details


def _usage_total(usage: Mapping[str, int]) -> int | None:
    return usage.get("total_tokens")


def _failure(
    reason: str,
    *,
    timed_out: bool = False,
    token_usage: int | None = None,
    usage: Mapping[str, int] | None = None,
    stderr: str = "",
) -> CliRunResult:
    metadata: dict[str, object] = {"failure_reason": reason}
    if usage:
        metadata["token_usage_details"] = dict(usage)
        metadata["token_usage_status"] = "untrusted"
    return CliRunResult(
        exit_code=124 if timed_out else 125,
        stdout="",
        stderr=stderr or "isolated Claude review-triage capture failed",
        token_usage=token_usage,
        timed_out=timed_out,
        metadata=metadata,
    )
