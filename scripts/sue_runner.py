"""Isolated, offline-testable subprocess transport for SUE cold readers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


_CODEX_REASONING_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
CODEX_DISABLED_FEATURES = (
    "apps",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "chronicle",
    "code_mode",
    "code_mode_buffered_exec",
    "code_mode_host",
    "code_mode_only",
    "computer_use",
    "deferred_executor",
    "enable_mcp_apps",
    "external_agent_memory_import",
    "hooks",
    "in_app_browser",
    "memories",
    "multi_agent",
    "multi_agent_v2",
    "plugin_sharing",
    "plugins",
    "remote_plugin",
    "shell_snapshot",
    "shell_tool",
    "shell_zsh_fork",
    "skill_mcp_dependency_install",
    "skill_search",
    "standalone_web_search",
    "tool_suggest",
    "unified_exec",
    "unified_exec_zsh_fork",
)
COLD_READER_ENV_ALLOWLIST = (
    # Executable discovery and Codex's explicit auth/config root.
    "PATH",
    "CODEX_HOME",
    # TLS trust and explicitly configured proxy routing.
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "NODE_EXTRA_CA_CERTS",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    # Localization and temporary-file operation.
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "TMPDIR",
    "TEMP",
    "TMP",
    # Windows process-launch necessities; absent on other platforms.
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    # macOS may synthesize this locale/encoding process variable at exec.
    "__CF_USER_TEXT_ENCODING",
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([A-Z0-9_-]*(?:api[_-]?key|token|secret|password|credential)"
    r"[A-Z0-9_-]*)=([^\s]+)"
)
_SECRET_OPTION_MARKERS = (
    "api-key",
    "api_key",
    "token",
    "secret",
    "password",
    "credential",
)


def _is_secret_name(value: str) -> bool:
    normalized = value.lower().lstrip("-")
    return any(marker in normalized for marker in _SECRET_OPTION_MARKERS)


def redact_sensitive_text(value: str) -> str:
    """Redact credential assignments without retaining any value suffix."""
    if "=" in value:
        name, _assigned = value.split("=", 1)
        if _is_secret_name(name):
            return f"{name}=<redacted>"
    return _SECRET_ASSIGNMENT_RE.sub(r"\1=<redacted>", value)


class RunnerConfigurationError(ValueError):
    """Raised when a cold-reader request cannot be executed reproducibly."""


class _RunnerOutputError(ValueError):
    """Raised for output that does not meet the Codex JSONL contract."""


@dataclass(frozen=True)
class ColdReaderRequest:
    run_id: str
    provider: str
    command: str
    model: str | None
    reasoning_effort: str | None
    prompt: str
    timeout_seconds: float
    output_schema: dict[str, Any] | None
    scientific: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id:
            raise RunnerConfigurationError("run_id is required")
        if self.provider != "codex":
            raise RunnerConfigurationError(f"unsupported provider: {self.provider}")
        if not isinstance(self.command, str) or not self.command.strip():
            raise RunnerConfigurationError("command is required")
        if not isinstance(self.prompt, str) or not self.prompt:
            raise RunnerConfigurationError("prompt is required")
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
        ):
            raise RunnerConfigurationError("timeout_seconds must be positive")
        if self.model is not None and (not isinstance(self.model, str) or not self.model):
            raise RunnerConfigurationError("model must be a non-empty string when provided")
        if (
            self.reasoning_effort is not None
            and self.reasoning_effort not in _CODEX_REASONING_EFFORTS
        ):
            raise RunnerConfigurationError("invalid Codex reasoning effort")
        if self.output_schema is not None and not isinstance(self.output_schema, dict):
            raise RunnerConfigurationError("output schema must be an object")
        if self.output_schema is not None:
            try:
                json.dumps(self.output_schema, allow_nan=False)
            except (TypeError, ValueError) as exc:
                raise RunnerConfigurationError(
                    "output schema must be JSON-serializable"
                ) from exc
        if self.scientific and not self.model:
            raise RunnerConfigurationError("scientific Codex runs require a model")
        if self.scientific and not self.reasoning_effort:
            raise RunnerConfigurationError(
                "scientific Codex runs require a reasoning effort"
            )
        if self.scientific and not self.output_schema:
            raise RunnerConfigurationError("scientific Codex runs require an output schema")
        if self.scientific:
            try:
                command = shlex.split(self.command)
            except ValueError as exc:
                raise RunnerConfigurationError(
                    "scientific Codex command must be a single executable token"
                ) from exc
            if len(command) != 1 or redact_sensitive_text(command[0]) != command[0]:
                raise RunnerConfigurationError(
                    "scientific Codex command must be a single executable token"
                )


@dataclass(frozen=True)
class ModelInvocation:
    argv: list[str]
    stdin_text: str


@dataclass(frozen=True)
class ColdReaderResult:
    run_id: str
    status: str
    provider: str
    model_requested: str | None
    model_reported: str | None
    reasoning_effort: str | None
    protocol: str
    argv_redacted: tuple[str, ...]
    duration_seconds: float
    exit_code: int | None
    raw_output: str
    final_output: str
    stderr: str
    raw_output_digest: str
    final_output_digest: str
    usage: dict | None
    started_at_utc: str = ""
    timeout_seconds: float = 0.0
    provider_cli_version: str = "unavailable"
    provider_cli_version_status: str = "unavailable"
    prompt_digest: str = ""
    schema_digest: str | None = None
    stderr_digest: str = ""


def _default_codex_home() -> str:
    """Resolve Codex auth/config home without forwarding ambient HOME."""
    if os.name == "posix":
        try:
            import pwd

            return str(Path(pwd.getpwuid(os.getuid()).pw_dir) / ".codex")
        except (KeyError, OSError):
            pass
    return str(Path.home() / ".codex")


def build_subprocess_environment(
    parent_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return the explicit cold-reader process environment.

    API keys, repository/Echelon state, Codex thread markers, and unrelated
    credentials are deliberately not inherited. Codex authentication is
    available only through the explicit ``CODEX_HOME`` credential store.
    """
    source = os.environ if parent_env is None else parent_env
    environment = {
        key: value
        for key in COLD_READER_ENV_ALLOWLIST
        if (value := source.get(key))
    }
    environment.setdefault("PATH", os.defpath)
    environment.setdefault("CODEX_HOME", _default_codex_home())
    return environment


def _canonical_schema(output_schema: dict[str, Any] | None) -> str | None:
    if output_schema is None:
        return None
    return json.dumps(
        output_schema,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def build_model_invocation(request: ColdReaderRequest, workdir: Path) -> ModelInvocation:
    """Build a non-interactive Codex invocation with prompt transport via stdin."""
    try:
        command = shlex.split(request.command)
    except ValueError as exc:
        raise RunnerConfigurationError(f"command is not shell-parseable: {exc}") from exc
    if not command:
        raise RunnerConfigurationError("command is required")

    final_path = workdir / "final.json"
    argv = command + [
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox", "read-only",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "-c", "shell_environment_policy.inherit=none",
        "-c", 'tools.web_search="disabled"',
        "-c", "mcp_servers={}",
    ]
    for feature in CODEX_DISABLED_FEATURES:
        argv.extend(["--disable", feature])
    if request.model:
        argv.extend(["--model", request.model])
    if request.reasoning_effort:
        argv.extend(["-c", f'model_reasoning_effort="{request.reasoning_effort}"'])
    if request.output_schema is not None:
        schema_path = workdir / "output-schema.json"
        try:
            schema_path.write_text(
                _canonical_schema(request.output_schema) or "", encoding="utf-8"
            )
        except OSError as exc:
            raise RunnerConfigurationError(
                f"could not construct hardened Codex schema input: {exc}"
            ) from exc
        argv.extend(["--output-schema", str(schema_path)])
    argv.extend(["--json", "--output-last-message", str(final_path), "-"])
    return ModelInvocation(
        argv=argv,
        stdin_text=request.prompt,
    )


def parse_codex_jsonl(raw: str) -> tuple[dict | None, dict | None]:
    """Extract immutable run metadata and usage from strict Codex JSONL."""
    metadata: dict[str, Any] = {}
    usage: dict | None = None
    saw_event = False
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise _RunnerOutputError("Codex stdout is not valid JSONL") from exc
        if not isinstance(event, dict):
            raise _RunnerOutputError("Codex JSONL event must be an object")
        saw_event = True
        if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
            metadata["thread_id"] = event["thread_id"]
        if event.get("type") == "turn.completed":
            if isinstance(event.get("model"), str):
                metadata["model_reported"] = event["model"]
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
    if (
        not saw_event
        or not metadata.get("thread_id")
        or not metadata.get("model_reported")
        or usage is None
    ):
        raise _RunnerOutputError(
            "Codex JSONL is missing required thread_id and model metadata or usage"
        )
    return metadata, usage


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    """Kill the reader and descendants created in its dedicated process group."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        process.kill()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _query_provider_cli_version(
    command: list[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> tuple[str, str]:
    """Query the local CLI binary without sending a prompt or provider request."""
    try:
        process = subprocess.Popen(
            command + ["--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=dict(env),
            text=True,
            start_new_session=True,
        )
    except OSError:
        return "unavailable", "unavailable"
    try:
        stdout, _stderr = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        try:
            process.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        return "unavailable", "unavailable"
    version = next((line.strip() for line in stdout.splitlines() if line.strip()), "")
    if process.returncode == 0 and version:
        return version[:256], "reported"
    return "unavailable", "unavailable"


def _redact_argv(argv: list[str], workdir: Path) -> tuple[str, ...]:
    schema_path = str(workdir / "output-schema.json")
    final_path = str(workdir / "final.json")
    redacted: list[str] = []
    redact_next = False
    for value in argv:
        if redact_next:
            redacted.append("<redacted>")
            redact_next = False
            continue
        if value == schema_path:
            redacted.append("<output-schema>")
            continue
        if value == final_path:
            redacted.append("<final-output>")
            continue
        if "=" not in value and _is_secret_name(value):
            redacted.append(value)
            redact_next = True
            continue
        redacted.append(redact_sensitive_text(value))
    return tuple(redacted)


def _result(
    request: ColdReaderRequest,
    *,
    status: str,
    argv_redacted: tuple[str, ...] = (),
    duration_seconds: float = 0.0,
    exit_code: int | None = None,
    raw_output: str = "",
    final_output: str = "",
    stderr: str = "",
    model_reported: str | None = None,
    usage: dict | None = None,
    started_at_utc: str = "",
    provider_cli_version: str = "unavailable",
    provider_cli_version_status: str = "unavailable",
) -> ColdReaderResult:
    schema = _canonical_schema(request.output_schema)
    return ColdReaderResult(
        run_id=request.run_id,
        status=status,
        provider=request.provider,
        model_requested=request.model,
        model_reported=model_reported,
        reasoning_effort=request.reasoning_effort,
        protocol="codex-jsonl-stdin",
        argv_redacted=argv_redacted,
        duration_seconds=duration_seconds,
        exit_code=exit_code,
        raw_output=raw_output,
        final_output=final_output,
        stderr=stderr,
        raw_output_digest=_digest(raw_output),
        final_output_digest=_digest(final_output),
        usage=usage,
        started_at_utc=started_at_utc,
        timeout_seconds=float(request.timeout_seconds),
        provider_cli_version=provider_cli_version,
        provider_cli_version_status=provider_cli_version_status,
        prompt_digest=_digest(request.prompt),
        schema_digest=_digest(schema) if schema is not None else None,
        stderr_digest=_digest(stderr),
    )


def unexpected_transport_result(
    request: ColdReaderRequest,
    error: BaseException,
) -> ColdReaderResult:
    """Preserve request-known evidence when the runner fails unexpectedly."""
    return _result(
        request,
        status="transport_error",
        stderr=(
            "model call failed unexpectedly: "
            f"{error.__class__.__name__}: {error}"
        ),
        started_at_utc=_utc_now(),
    )


def run_cold_reader(request: ColdReaderRequest) -> ColdReaderResult:
    """Run one Codex cold reader in a temporary neutral working directory."""
    started_at_utc = _utc_now()
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="sue-reader-") as directory:
        workdir = Path(directory)
        try:
            invocation = build_model_invocation(request, workdir)
        except RunnerConfigurationError as exc:
            return _result(
                request,
                status="transport_error",
                stderr=str(exc),
                started_at_utc=started_at_utc,
            )
        argv_redacted = _redact_argv(invocation.argv, workdir)
        process_env = build_subprocess_environment()
        command_length = len(shlex.split(request.command))
        provider_cli_version, provider_cli_version_status = _query_provider_cli_version(
            invocation.argv[:command_length],
            cwd=workdir,
            env=process_env,
        )
        try:
            process = subprocess.Popen(
                invocation.argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=workdir,
                env=process_env,
                text=True,
                start_new_session=True,
            )
        except FileNotFoundError:
            return _result(
                request,
                status="launch_missing",
                argv_redacted=argv_redacted,
                duration_seconds=time.monotonic() - start,
                started_at_utc=started_at_utc,
                provider_cli_version=provider_cli_version,
                provider_cli_version_status=provider_cli_version_status,
            )
        except OSError as exc:
            return _result(
                request,
                status="transport_error",
                argv_redacted=argv_redacted,
                duration_seconds=time.monotonic() - start,
                stderr=str(exc),
                started_at_utc=started_at_utc,
                provider_cli_version=provider_cli_version,
                provider_cli_version_status=provider_cli_version_status,
            )
        try:
            raw_output, stderr = process.communicate(
                input=invocation.stdin_text,
                timeout=request.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            _kill_process_group(process)
            try:
                raw_output, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                raw_output, stderr = "", ""
            return _result(
                request,
                status="timeout",
                argv_redacted=argv_redacted,
                duration_seconds=time.monotonic() - start,
                exit_code=process.returncode,
                raw_output=raw_output or "",
                stderr=stderr or "",
                started_at_utc=started_at_utc,
                provider_cli_version=provider_cli_version,
                provider_cli_version_status=provider_cli_version_status,
            )

        raw_output = raw_output or ""
        stderr = stderr or ""
        duration = time.monotonic() - start
        if process.returncode != 0:
            return _result(
                request,
                status="transport_error",
                argv_redacted=argv_redacted,
                duration_seconds=duration,
                exit_code=process.returncode,
                raw_output=raw_output,
                stderr=stderr,
                started_at_utc=started_at_utc,
                provider_cli_version=provider_cli_version,
                provider_cli_version_status=provider_cli_version_status,
            )
        final_path = workdir / "final.json"
        final_output = ""
        try:
            final_output = final_path.read_text(encoding="utf-8")
            if not final_output:
                raise _RunnerOutputError("Codex final output is empty")
            metadata, usage = parse_codex_jsonl(raw_output)
        except (OSError, _RunnerOutputError) as exc:
            return _result(
                request,
                status="unusable_output",
                argv_redacted=argv_redacted,
                duration_seconds=duration,
                exit_code=process.returncode,
                raw_output=raw_output,
                final_output=final_output,
                stderr=stderr if stderr else str(exc),
                started_at_utc=started_at_utc,
                provider_cli_version=provider_cli_version,
                provider_cli_version_status=provider_cli_version_status,
            )
        return _result(
            request,
            status="success",
            argv_redacted=argv_redacted,
            duration_seconds=duration,
            exit_code=process.returncode,
            raw_output=raw_output,
            final_output=final_output,
            stderr=stderr,
            model_reported=metadata.get("model_reported"),
            usage=usage,
            started_at_utc=started_at_utc,
            provider_cli_version=provider_cli_version,
            provider_cli_version_status=provider_cli_version_status,
        )
