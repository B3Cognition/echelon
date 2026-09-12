"""Fail-closed construction for an opt-in constrained Codex request."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
from pathlib import Path
import re
from typing import Callable, Mapping

from harness.ai_cli_backend import CliRunRequest
from harness.llm_tool_policy import (
    LlmToolPolicy,
    build_llm_cli_command,
    inject_llm_tool_policy_preamble,
)


# These controls are present in the official OpenAI Codex rust-v0.147.0
# config schema. Strict config makes an unsupported key a process failure
# instead of silently weakening this opt-in mode.
_CONSTRAINED_CONFIG_OVERRIDES = (
    "allow_login_shell=false",
    "features.shell_tool=false",
    "features.unified_exec=false",
    "features.apply_patch_freeform=false",
    'web_search="disabled"',
    "features.standalone_web_search=false",
    "features.search_tool=false",
    "features.view_image=false",
    "features.image_generation=false",
    "features.browser_use=false",
    "features.browser_use_external=false",
    "features.browser_use_full_cdp_access=false",
    "features.in_app_browser=false",
    "features.computer_use=false",
    "features.apps=false",
    "features.enable_mcp_apps=false",
    "features.tool_search=false",
    "features.tool_suggest=false",
    "features.plugins=false",
    "features.recommended_plugins=false",
    "features.remote_plugin=false",
    "mcp_servers={}",
    "plugins={}",
    "agents.enabled=false",
    "features.multi_agent=false",
    "features.multi_agent_mode=false",
    "features.multi_agent_v2=false",
    "features.enable_fanout=false",
    "features.memories=false",
    "features.external_agent_memory_import=false",
    "memories.generate_memories=false",
    "memories.use_memories=false",
    "memories.dedicated_tools=false",
    "features.hooks=false",
    "features.plugin_hooks=false",
    "hooks={}",
    "skills.include_instructions=false",
    "skills.bundled.enabled=false",
    "orchestrator.skills.enabled=false",
    "orchestrator.mcp.enabled=false",
    "include_apps_instructions=false",
    "include_collaboration_mode_instructions=false",
    "include_environment_context=false",
    "include_permissions_instructions=false",
    "project_doc_max_bytes=0",
    "analytics.enabled=false",
    "feedback.enabled=false",
    'otel.exporter="none"',
    'otel.trace_exporter="none"',
    'otel.metrics_exporter="none"',
    "otel.log_user_prompt=false",
    'history.persistence="none"',
    "notify=[]",
)

_SENSITIVE_ENV_EXACT = frozenset(
    {
        "CODEX_LOG",
        "RUST_BACKTRACE",
        "RUST_LOG",
        "RUST_LOG_STYLE",
        "TRACEPARENT",
        "TRACESTATE",
    }
)
_FORBIDDEN_METADATA_KEYS = frozenset(
    {
        "allow_unsafe_host_execution",
        "isolated_workspace",
        "permission_profile",
        "sandbox_mode",
        "tool_policy",
    }
)
_SAFE_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,255}\Z")


class ConstrainedRequestError(ValueError):
    """Sanitized request-construction failure."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class PreparedConstrainedRequest:
    command: tuple[str, ...]
    env: dict[str, str]
    prompt_bytes: bytes = field(repr=False)


def prepare_constrained_request(
    bin_: str,
    request: CliRunRequest,
    *,
    model: str,
    screen_output: Callable[[bytes], bytes],
    max_input_bytes: int,
    max_capture_bytes: int,
    tool_policy: LlmToolPolicy,
) -> PreparedConstrainedRequest:
    """Validate and render one bounded, stdin-only native Codex request."""
    if not _valid_request_shape(
        request,
        model=model,
        screen_output=screen_output,
        max_input_bytes=max_input_bytes,
        max_capture_bytes=max_capture_bytes,
    ):
        raise ConstrainedRequestError("invalid_request")

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
        raise ConstrainedRequestError("invalid_request") from None
    if len(prompt_bytes) > max_input_bytes:
        raise ConstrainedRequestError("input_overflow")
    if not _screen_identical(screen_output, prompt_bytes):
        raise ConstrainedRequestError("screen_rejected")

    command = build_llm_cli_command(
        "codex",
        bin_,
        "",
        safe_policy,
        codex_json=True,
        codex_model=model.strip(),
        codex_skip_git_repo_check=True,
        codex_ignore_user_config=True,
    )
    try:
        sandbox_index = command.index("--sandbox") + 1
        exec_index = command.index("exec")
    except ValueError:
        raise ConstrainedRequestError("invalid_request") from None
    command[sandbox_index] = "read-only"
    command[exec_index + 1 : exec_index + 1] = [
        "--strict-config",
        "--ephemeral",
        "--ignore-rules",
    ]
    command[-1:] = [
        *(
            argument
            for value in _CONSTRAINED_CONFIG_OVERRIDES
            for argument in ("-c", value)
        ),
        "-",
    ]

    return PreparedConstrainedRequest(
        command=tuple(command),
        env=_sanitized_environment(request.env),
        prompt_bytes=prompt_bytes,
    )


def _valid_request_shape(
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
        or not _is_empty_nonsymlink_directory(request.cwd)
        or _has_forbidden_scope(request.metadata)
    ):
        return False
    try:
        _sanitized_environment(request.env)
    except ConstrainedRequestError:
        return False
    return True


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
        raise ConstrainedRequestError("invalid_request")
    sanitized: dict[str, str] = {}
    try:
        items = environment.items()
        for key, value in items:
            if (
                type(key) is not str
                or type(value) is not str
                or not key
                or "=" in key
                or "\0" in key
                or "\0" in value
            ):
                raise ConstrainedRequestError("invalid_request")
            upper = key.upper()
            if upper in _SENSITIVE_ENV_EXACT or upper.startswith("OTEL_"):
                continue
            sanitized[key] = value
    except ConstrainedRequestError:
        raise
    except Exception:
        raise ConstrainedRequestError("invalid_request") from None
    return sanitized


def _screen_identical(
    screen_output: Callable[[bytes], bytes], value: bytes
) -> bool:
    try:
        screened = screen_output(value)
    except Exception:
        return False
    return type(screened) is bytes and screened == value
