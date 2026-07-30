"""Isolated, offline-testable subprocess transport for SUE cold readers."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_CODEX_REASONING_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})


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
        if self.scientific and not self.output_schema:
            raise RunnerConfigurationError("scientific Codex runs require an output schema")


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
    ]
    if request.model:
        argv.extend(["--model", request.model])
    if request.reasoning_effort:
        argv.extend(["-c", f'model_reasoning_effort="{request.reasoning_effort}"'])
    if request.output_schema is not None:
        schema_path = workdir / "output-schema.json"
        schema_path.write_text(
            json.dumps(request.output_schema, allow_nan=False), encoding="utf-8"
        )
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


def _redact_argv(argv: list[str], workdir: Path) -> tuple[str, ...]:
    schema_path = str(workdir / "output-schema.json")
    final_path = str(workdir / "final.json")
    return tuple(
        "<output-schema>" if value == schema_path else "<final-output>" if value == final_path else value
        for value in argv
    )


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
) -> ColdReaderResult:
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
    )


def run_cold_reader(request: ColdReaderRequest) -> ColdReaderResult:
    """Run one Codex cold reader in a temporary neutral working directory."""
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="sue-reader-") as directory:
        workdir = Path(directory)
        try:
            invocation = build_model_invocation(request, workdir)
        except RunnerConfigurationError as exc:
            return _result(request, status="transport_error", stderr=str(exc))
        argv_redacted = _redact_argv(invocation.argv, workdir)
        try:
            process = subprocess.Popen(
                invocation.argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=workdir,
                text=True,
                start_new_session=True,
            )
        except FileNotFoundError:
            return _result(
                request,
                status="launch_missing",
                argv_redacted=argv_redacted,
                duration_seconds=time.monotonic() - start,
            )
        except OSError as exc:
            return _result(
                request,
                status="transport_error",
                argv_redacted=argv_redacted,
                duration_seconds=time.monotonic() - start,
                stderr=str(exc),
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
        )
