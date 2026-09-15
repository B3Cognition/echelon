"""Fail-closed construction and parsing for constrained Claude requests."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Callable, Mapping

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.ai_cli_backends.bounded_capture import CaptureError, capture_pipes
from harness.llm_tool_policy import LlmToolPolicy, inject_llm_tool_policy_preamble


_FORBIDDEN_METADATA_KEYS = frozenset(
    {
        "allow_unsafe_host_execution",
        "isolated_workspace",
        "permission_profile",
        "sandbox_mode",
        "tool_policy",
    }
)
_SENSITIVE_ENV_EXACT = frozenset(
    {
        "CLAUDE_CODE_DEBUG_LOGS_DIR",
        "CLAUDE_CODE_ENABLE_TELEMETRY",
        "CLAUDE_CODE_OTEL_HEADERS_HELPER_DEBOUNCE_MS",
        "TRACEPARENT",
        "TRACESTATE",
    }
)
_SAFE_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,255}\Z")
_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)
_FAILURE_TEXT = "screened Claude capture failed"


class ConstrainedClaudeError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class PreparedClaudeRequest:
    command: tuple[str, ...]
    env: dict[str, str]
    prompt_bytes: bytes = field(repr=False)


def prepare_claude_request(
    bin_: str,
    request: CliRunRequest,
    *,
    model: str,
    screen_output: Callable[[bytes], bytes],
    max_input_bytes: int,
    max_capture_bytes: int,
    tool_policy: LlmToolPolicy,
    screen_input: Callable[[bytes], bytes] | None,
) -> PreparedClaudeRequest:
    if screen_input is not None and not callable(screen_input):
        raise ConstrainedClaudeError("invalid_request")
    if not _valid_request(
        request,
        model=model,
        screen_output=screen_output,
        max_input_bytes=max_input_bytes,
        max_capture_bytes=max_capture_bytes,
    ):
        raise ConstrainedClaudeError("invalid_request")
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
        raise ConstrainedClaudeError("invalid_request") from None
    if len(prompt_bytes) > max_input_bytes:
        raise ConstrainedClaudeError("input_overflow")
    if not _screen_identical(screen_input or screen_output, prompt_bytes):
        raise ConstrainedClaudeError("screen_rejected")

    command = (
        bin_,
        "-p",
        "--input-format",
        "text",
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        model.strip(),
        "--restricted",
        "--tools",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--disable-slash-commands",
        "--permission-mode",
        "dontAsk",
        "--permission-prompts",
        "none",
        "--no-session-persistence",
    )
    return PreparedClaudeRequest(
        command=command,
        env=_sanitized_environment(request.env),
        prompt_bytes=prompt_bytes,
    )


def run_claude_process(
    proc: subprocess.Popen,
    *,
    screen_output: Callable[[bytes], bytes],
    max_capture_bytes: int,
    timeout_s: float,
    model: str,
    input_bytes: bytes,
) -> CliRunResult:
    try:
        captured = capture_pipes(
            proc,
            max_capture_bytes=max_capture_bytes,
            timeout_s=timeout_s,
            input_bytes=input_bytes,
        )
    except CaptureError as exc:
        return failure(exc.reason, timed_out=exc.timed_out)

    if not _screen_identical(screen_output, captured.stdout) or not _screen_identical(
        screen_output, captured.stderr
    ):
        return failure("screen_rejected")
    try:
        captured.stderr.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return failure("malformed_capture")

    final_text: str | None = None
    usage_details: dict[str, int] = {}
    usage_status = "unavailable"
    saw_result = False
    saw_init = False
    for raw_record in captured.stdout.splitlines():
        if not raw_record.strip():
            continue
        if saw_result:
            return failure("malformed_capture")
        if not _screen_identical(screen_output, raw_record):
            return failure("screen_rejected")
        event, reason = _strict_json_event(raw_record, screen_output)
        if reason is not None:
            return failure(reason)
        assert event is not None
        event_type = event.get("type")
        if event_type == "system":
            if event.get("subtype") == "init":
                if saw_init or not _boundary_is_attested(event):
                    return failure("boundary_not_attested")
                saw_init = True
            elif not saw_init:
                return failure("boundary_not_attested")
            continue
        if event_type == "assistant":
            if not saw_init:
                return failure("boundary_not_attested")
            if not _safe_assistant_event(event):
                return failure("tool_event")
            continue
        if event_type == "rate_limit_event":
            continue
        if event_type != "result":
            return failure("malformed_capture")
        if not saw_init:
            return failure("boundary_not_attested")
        saw_result = True
        if (
            event.get("subtype") != "success"
            or event.get("is_error") is not False
            or type(event.get("result")) is not str
        ):
            return failure("provider_event_failure")
        if _result_has_tool_activity(event):
            return failure("tool_event")
        final_text = event["result"]
        if _server_tools_used(event.get("usage")):
            return failure("tool_event")
        parsed_usage = _strict_usage(event.get("usage"))
        if parsed_usage is None:
            return failure("malformed_capture")
        usage_details, usage_status = parsed_usage

    token_usage = usage_details.get("total_tokens") if usage_details else None
    if captured.returncode != 0:
        return failure("provider_exit", token_usage=token_usage)
    if final_text is None:
        return failure("missing_final_answer", token_usage=token_usage)
    try:
        final_bytes = final_text.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return failure("malformed_capture", token_usage=token_usage)
    if not _screen_identical(screen_output, final_bytes):
        return failure("screen_rejected", token_usage=token_usage)
    return CliRunResult(
        exit_code=0,
        stdout=final_text,
        stderr="",
        token_usage=token_usage,
        metadata={
            "task_complete": True,
            "request_model": model,
            "isolated_user_config": True,
            "token_usage_details": usage_details,
            "token_usage_status": usage_status,
        },
    )


def failure(
    reason: str,
    *,
    timed_out: bool = False,
    token_usage: int | None = None,
) -> CliRunResult:
    return CliRunResult(
        exit_code=124 if timed_out else 125,
        stdout="",
        stderr=_FAILURE_TEXT,
        token_usage=token_usage,
        timed_out=timed_out,
        metadata={"failure_reason": reason},
    )


def _valid_request(
    request: object,
    *,
    model: object,
    screen_output: object,
    max_input_bytes: object,
    max_capture_bytes: object,
) -> bool:
    if not isinstance(request, CliRunRequest):
        return False
    timeout = request.timeout_s
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
        or type(max_input_bytes) is not int
        or max_input_bytes <= 0
        or type(max_capture_bytes) is not int
        or max_capture_bytes <= 0
        or type(model) is not str
        or _SAFE_MODEL.fullmatch(model) is None
        or type(request.prompt) is not str
        or not request.prompt
        or not callable(screen_output)
        or not _empty_nonsymlink_directory(request.cwd)
        or _has_forbidden_scope(request.metadata)
    ):
        return False
    try:
        _sanitized_environment(request.env)
    except ConstrainedClaudeError:
        return False
    return True


def _empty_nonsymlink_directory(raw_path: object) -> bool:
    if type(raw_path) is not str or not raw_path:
        return False
    path = Path(raw_path)
    try:
        return path.is_dir() and not path.is_symlink() and next(path.iterdir(), None) is None
    except OSError:
        return False


def _has_forbidden_scope(metadata: object) -> bool:
    if not isinstance(metadata, Mapping):
        return True
    pending = [metadata]
    seen: set[int] = set()
    while pending:
        value = pending.pop()
        identity = id(value)
        if identity in seen:
            return True
        seen.add(identity)
        for key, member in value.items():
            if type(key) is not str:
                return True
            normalized = key.strip().lower()
            if (
                normalized in _FORBIDDEN_METADATA_KEYS
                or normalized.startswith("tool_")
                or normalized.startswith("source_")
            ):
                return True
            if isinstance(member, Mapping):
                pending.append(member)
    return False


def _sanitized_environment(environment: object) -> dict[str, str]:
    if not isinstance(environment, Mapping):
        raise ConstrainedClaudeError("invalid_request")
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
                raise ConstrainedClaudeError("invalid_request")
            upper = key.upper()
            if upper in _SENSITIVE_ENV_EXACT or upper.startswith("OTEL_"):
                continue
            sanitized[key] = value
    except ConstrainedClaudeError:
        raise
    except Exception:
        raise ConstrainedClaudeError("invalid_request") from None
    return sanitized


def _safe_assistant_event(event: Mapping[str, object]) -> bool:
    message = event.get("message")
    if not isinstance(message, Mapping):
        return False
    content = message.get("content")
    if not isinstance(content, list):
        return False
    for block in content:
        if not isinstance(block, Mapping):
            return False
        block_type = block.get("type")
        if block_type == "text" and type(block.get("text")) is str:
            continue
        if block_type == "thinking" and type(block.get("thinking")) is str:
            continue
        return False
    return True


def _boundary_is_attested(event: Mapping[str, object]) -> bool:
    return (
        event.get("tools") == []
        and event.get("mcp_servers") == []
        and event.get("slash_commands") == []
        and event.get("skills") == []
        and event.get("plugins") == []
        and event.get("permissionMode") == "dontAsk"
    )


def _strict_usage(raw: object) -> tuple[dict[str, int], str] | None:
    if not isinstance(raw, Mapping):
        return None
    for key in _USAGE_KEYS:
        value = raw.get(key, 0)
        if type(value) is not int or value < 0:
            return None
    input_tokens = raw.get("input_tokens", 0)
    output_tokens = raw.get("output_tokens", 0)
    cache_creation = raw.get("cache_creation_input_tokens", 0)
    cache_read = raw.get("cache_read_input_tokens", 0)
    assert isinstance(input_tokens, int)
    assert isinstance(output_tokens, int)
    assert isinstance(cache_creation, int)
    assert isinstance(cache_read, int)
    raw_output_details = raw.get("output_tokens_details")
    thinking_tokens: int | None = None
    if isinstance(raw_output_details, Mapping):
        candidate = raw_output_details.get("thinking_tokens")
        if type(candidate) is int and 0 <= candidate <= output_tokens:
            thinking_tokens = candidate
    gross_input = input_tokens + cache_creation + cache_read
    total = gross_input + output_tokens
    return (
        {
            "input_tokens": gross_input,
            "cached_input_tokens": cache_read,
            "output_tokens": output_tokens,
            "reasoning_output_tokens": thinking_tokens or 0,
            "total_tokens": total,
        },
        "trusted_exact" if thinking_tokens is not None else "untrusted",
    )


def _server_tools_used(raw: object) -> bool:
    if not isinstance(raw, Mapping):
        return False
    server_usage = raw.get("server_tool_use")
    if not isinstance(server_usage, Mapping):
        return False
    return any(type(value) is int and value > 0 for value in server_usage.values())


def _result_has_tool_activity(event: Mapping[str, object]) -> bool:
    permission_denials = event.get("permission_denials")
    if permission_denials not in (None, []):
        return True
    subagent_stats = event.get("subagent_stats")
    if subagent_stats is not None and not isinstance(subagent_stats, Mapping):
        return True
    return isinstance(subagent_stats, Mapping) and _mapping_has_positive_count(
        subagent_stats
    )


def _mapping_has_positive_count(value: Mapping[object, object]) -> bool:
    for member in value.values():
        if type(member) is int and member > 0:
            return True
        if isinstance(member, Mapping) and _mapping_has_positive_count(member):
            return True
    return False


class _Pairs(list[tuple[str, object]]):
    pass


class _DuplicateKey(ValueError):
    pass


def _strict_json_event(
    raw: bytes, screen_output: Callable[[bytes], bytes]
) -> tuple[dict[str, object] | None, str | None]:
    try:
        decoded = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_Pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        normalized = _encode_pairs(decoded)
    except (UnicodeError, ValueError, TypeError, OverflowError, RecursionError):
        return None, "malformed_capture"
    if not _screen_identical(screen_output, normalized):
        return None, "screen_rejected"
    try:
        event = _unique(decoded)
    except (_DuplicateKey, RecursionError):
        return None, "malformed_capture"
    return (event, None) if isinstance(event, dict) else (None, "malformed_capture")


def _encode_pairs(value: object) -> bytes:
    if isinstance(value, _Pairs):
        return b"{" + b",".join(
            json.dumps(key, ensure_ascii=False).encode("utf-8")
            + b":"
            + _encode_pairs(member)
            for key, member in value
        ) + b"}"
    if isinstance(value, list):
        return b"[" + b",".join(_encode_pairs(member) for member in value) + b"]"
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def _unique(value: object) -> object:
    if isinstance(value, _Pairs):
        result: dict[str, object] = {}
        for key, member in value:
            if key in result:
                raise _DuplicateKey
            result[key] = _unique(member)
        return result
    if isinstance(value, list):
        return [_unique(member) for member in value]
    return value


def _screen_identical(screen: Callable[[bytes], bytes], value: bytes) -> bool:
    try:
        screened = screen(value)
    except Exception:
        return False
    return type(screened) is bytes and screened == value
