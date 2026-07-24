"""Append-only local storage for Echelon execution spans."""

from __future__ import annotations

from contextlib import contextmanager
import errno
import fcntl
import json
import os
import stat
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Mapping

from echelon.telemetry.model import ExecutionSpan, PhaseTimingEvent, TelemetryDiagnostic
from harness.controller_lock_order import controller_lock_order


TELEMETRY_SCHEMA_VERSION = 1
OTEL_SEMCONV_VERSION = "1.43.0"
_DISPATCH_REASONS = frozenset({"initial", "planned_iteration", "semantic_repair", "deterministic_repair", "provider_retry", "resume", "manual_rerun"})
_MAX_EVENT_STREAM_BYTES = 67_108_864


class TelemetryDurabilityError(RuntimeError):
    """A bounded failure to durably replace or confirm telemetry."""

    _STAGES = frozenset(
        {
            "directory_create",
            "pre_replace",
            "post_replace",
            "confirm",
        }
    )

    def __init__(self, message: str, *, stage: str) -> None:
        super().__init__(message)
        self.stage = stage if stage in self._STAGES else "confirm"


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _fsync_retry(descriptor: int) -> None:
    while True:
        try:
            os.fsync(descriptor)
            return
        except OSError as exc:
            if exc.errno != errno.EINTR:
                raise


def _open_real_directory(path: Path, *, stage: str) -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        named = os.lstat(path)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or stat.S_ISLNK(named.st_mode)
            or not stat.S_ISDIR(named.st_mode)
            or _identity(opened) != _identity(named)
        ):
            raise TelemetryDurabilityError(
                "telemetry directory identity changed",
                stage=stage,
            )
        return descriptor
    except TelemetryDurabilityError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise TelemetryDurabilityError(
            "telemetry directory is unavailable",
            stage=stage,
        ) from exc


def _ensure_directory_durable(path: Path) -> None:
    parent_fd = _open_real_directory(
        path.parent,
        stage="directory_create",
    )
    directory_fd = -1
    try:
        try:
            os.mkdir(path.name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        flags = os.O_RDONLY
        flags |= getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        directory_fd = os.open(
            path.name,
            flags,
            dir_fd=parent_fd,
        )
        opened = os.fstat(directory_fd)
        named = os.stat(
            path.name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISDIR(opened.st_mode)
            or stat.S_ISLNK(named.st_mode)
            or not stat.S_ISDIR(named.st_mode)
            or _identity(opened) != _identity(named)
        ):
            raise TelemetryDurabilityError(
                "telemetry directory identity changed",
                stage="directory_create",
            )
        _fsync_retry(directory_fd)
        _fsync_retry(parent_fd)
        final_named = os.stat(
            path.name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISDIR(final_named.st_mode)
            or _identity(final_named) != _identity(opened)
        ):
            raise TelemetryDurabilityError(
                "telemetry directory identity changed",
                stage="directory_create",
            )
    except TelemetryDurabilityError:
        raise
    except OSError as exc:
        raise TelemetryDurabilityError(
            "telemetry directory could not be created durably",
            stage="directory_create",
        ) from exc
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)
        os.close(parent_fd)


def _validate_event_stream_bytes(content: bytes) -> None:
    if len(content) > _MAX_EVENT_STREAM_BYTES:
        raise ValueError("telemetry event stream is too large")
    if content and not content.endswith(b"\n"):
        raise ValueError("telemetry event stream has a torn final record")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("telemetry event stream is not UTF-8") from exc
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError("telemetry event stream has invalid JSON") from exc
        if type(value) is not dict:
            raise ValueError("telemetry event record must be an object")
        if value.get("type") == "phase_timing":
            PhaseTimingEvent.from_json_dict(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class TelemetryStore:
    def __init__(
        self,
        run_dir: Path,
        *,
        workflow: str,
        run_id: str,
        profile: Mapping[str, object],
        trace_id: str,
    ) -> None:
        self.run_dir = run_dir.resolve()
        self.directory = self.run_dir / "telemetry"
        self.manifest_path = self.directory / "manifest.json"
        self.spans_path = self.directory / "spans.jsonl"
        self.events_path = self.directory / "events.jsonl"
        self.phase_timing_lock_path = self.directory / "phase-timing.lock"
        self.workflow = workflow
        self.run_id = run_id
        self.profile = dict(profile)
        self.trace_id = trace_id
        self._write_lock = threading.RLock()
        self._controller_lock_identity = str(self.directory.absolute())
        self._phase_timing_transaction_depth = 0

    def ensure_manifest(self) -> None:
        _ensure_directory_durable(self.directory)
        if self.manifest_path.is_file():
            existing = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if (
                existing.get("trace_id") != self.trace_id
                or existing.get("run_id") != self.run_id
                or existing.get("workflow") != self.workflow
            ):
                raise ValueError("telemetry manifest identity mismatch")
            return
        payload = {
            "schema_version": TELEMETRY_SCHEMA_VERSION,
            "semantic_conventions_version": OTEL_SEMCONV_VERSION,
            "created_at": _utc_now(),
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "workflow": self.workflow,
            "profile": self.profile,
            "content_capture": False,
        }
        fd, temporary = tempfile.mkstemp(
            dir=str(self.directory), prefix=".manifest-", suffix=".tmp"
        )
        replaced = False
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                _fsync_retry(handle.fileno())
            os.replace(temporary, self.manifest_path)
            replaced = True
            directory_fd = _open_real_directory(
                self.directory,
                stage="post_replace",
            )
            try:
                _fsync_retry(directory_fd)
            except OSError as exc:
                raise TelemetryDurabilityError(
                    "telemetry manifest parent sync failed",
                    stage="post_replace",
                ) from exc
            finally:
                os.close(directory_fd)
        except Exception:
            if not replaced:
                Path(temporary).unlink(missing_ok=True)
            raise

    def append_span(self, span: ExecutionSpan) -> None:
        if span.trace_id != self.trace_id:
            raise ValueError("span trace id does not match telemetry manifest")
        with controller_lock_order(
            "telemetry",
            self._controller_lock_identity,
        ):
            with self._write_lock:
                self.ensure_manifest()
                record = json.dumps(span.to_json_dict(), separators=(",", ":"), sort_keys=True)
                with self.spans_path.open("a", encoding="utf-8") as handle:
                    handle.write(record + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())

    def append_phase_timing(self, event: PhaseTimingEvent) -> None:
        """Persist phase timing separately from mutable controller state."""
        PhaseTimingEvent.from_json_dict(event.to_json_dict())
        self.append_event(event.to_json_dict())

    def _read_event_stream_bytes_unlocked(self) -> bytes:
        flags = os.O_RDONLY
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        descriptor = -1
        try:
            descriptor = os.open(self.events_path, flags)
        except FileNotFoundError:
            return b""
        except OSError as exc:
            raise TelemetryDurabilityError(
                "telemetry event stream is unavailable",
                stage="confirm",
            ) from exc
        try:
            opened = os.fstat(descriptor)
            named = os.lstat(self.events_path)
            if (
                not stat.S_ISREG(opened.st_mode)
                or stat.S_ISLNK(named.st_mode)
                or not stat.S_ISREG(named.st_mode)
                or _identity(opened) != _identity(named)
                or opened.st_size > _MAX_EVENT_STREAM_BYTES
            ):
                raise TelemetryDurabilityError(
                    "telemetry event stream identity changed",
                    stage="confirm",
                )
            chunks: list[bytes] = []
            remaining = _MAX_EVENT_STREAM_BYTES + 1
            while remaining:
                chunk = os.read(
                    descriptor,
                    min(1_048_576, remaining),
                )
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            after = os.fstat(descriptor)
            if (
                len(content) > _MAX_EVENT_STREAM_BYTES
                or _identity(after) != _identity(opened)
                or after.st_size != opened.st_size
            ):
                raise TelemetryDurabilityError(
                    "telemetry event stream changed while read",
                    stage="confirm",
                )
            return content
        finally:
            os.close(descriptor)

    @staticmethod
    def _event_record_bytes(event: Mapping[str, object]) -> bytes:
        return (
            json.dumps(
                dict(event),
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )

    def _current_phase_timing_stream_unlocked(self) -> bytes:
        content = self._read_event_stream_bytes_unlocked()
        _validate_event_stream_bytes(content)
        return content

    def current_phase_timing_stream(self) -> bytes:
        with controller_lock_order(
            "telemetry",
            self._controller_lock_identity,
        ):
            with self._write_lock:
                if self._phase_timing_transaction_depth:
                    return self._current_phase_timing_stream_unlocked()
                with self._phase_timing_transaction_ordered():
                    return self._current_phase_timing_stream_unlocked()

    def phase_timing_stream_with_event(
        self,
        event: PhaseTimingEvent,
    ) -> bytes:
        PhaseTimingEvent.from_json_dict(event.to_json_dict())
        with controller_lock_order(
            "telemetry",
            self._controller_lock_identity,
        ):
            with self._write_lock:
                if self._phase_timing_transaction_depth:
                    prior = self._current_phase_timing_stream_unlocked()
                else:
                    with self._phase_timing_transaction_ordered():
                        prior = self._current_phase_timing_stream_unlocked()
                expected = prior + self._event_record_bytes(
                    event.to_json_dict()
                )
                _validate_event_stream_bytes(expected)
                return expected

    def _confirm_phase_timing_stream_unlocked(
        self,
        expected: bytes,
    ) -> bytes:
        if type(expected) is not bytes:
            raise TelemetryDurabilityError(
                "expected telemetry stream must be bytes",
                stage="confirm",
            )
        _validate_event_stream_bytes(expected)
        flags = os.O_RDONLY
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        descriptor = -1
        directory_fd = -1
        try:
            descriptor = os.open(self.events_path, flags)
            opened = os.fstat(descriptor)
            named = os.lstat(self.events_path)
            if (
                not stat.S_ISREG(opened.st_mode)
                or stat.S_ISLNK(named.st_mode)
                or not stat.S_ISREG(named.st_mode)
                or _identity(opened) != _identity(named)
                or opened.st_size != len(expected)
            ):
                raise TelemetryDurabilityError(
                    "telemetry stream identity changed",
                    stage="confirm",
                )
            content = bytearray()
            while len(content) <= _MAX_EVENT_STREAM_BYTES:
                chunk = os.read(descriptor, 1_048_576)
                if not chunk:
                    break
                content.extend(chunk)
            if bytes(content) != expected:
                raise TelemetryDurabilityError(
                    "telemetry stream postimage changed",
                    stage="confirm",
                )
            _fsync_retry(descriptor)
            directory_fd = _open_real_directory(
                self.directory,
                stage="confirm",
            )
            directory_before = os.fstat(directory_fd)
            _fsync_retry(directory_fd)
            final_opened = os.fstat(descriptor)
            final_named = os.lstat(self.events_path)
            directory_after = os.fstat(directory_fd)
            directory_named = os.lstat(self.directory)
            if (
                _identity(final_opened) != _identity(opened)
                or final_opened.st_size != opened.st_size
                or not stat.S_ISREG(final_named.st_mode)
                or _identity(final_named) != _identity(opened)
                or _identity(directory_after)
                != _identity(directory_before)
                or stat.S_ISLNK(directory_named.st_mode)
                or not stat.S_ISDIR(directory_named.st_mode)
                or _identity(directory_named)
                != _identity(directory_after)
            ):
                raise TelemetryDurabilityError(
                    "telemetry durability identity changed",
                    stage="confirm",
                )
            os.lseek(descriptor, 0, os.SEEK_SET)
            final_content = bytearray()
            while len(final_content) <= _MAX_EVENT_STREAM_BYTES:
                chunk = os.read(descriptor, 1_048_576)
                if not chunk:
                    break
                final_content.extend(chunk)
            if bytes(final_content) != expected:
                raise TelemetryDurabilityError(
                    "telemetry stream changed after synchronization",
                    stage="confirm",
                )
            return expected
        except TelemetryDurabilityError:
            raise
        except (OSError, ValueError) as exc:
            raise TelemetryDurabilityError(
                "telemetry durability confirmation failed",
                stage="confirm",
            ) from exc
        finally:
            if directory_fd >= 0:
                os.close(directory_fd)
            if descriptor >= 0:
                os.close(descriptor)

    def confirm_phase_timing_stream(self, expected: bytes) -> bytes:
        with controller_lock_order(
            "telemetry",
            self._controller_lock_identity,
        ):
            with self._write_lock:
                if self._phase_timing_transaction_depth:
                    return self._confirm_phase_timing_stream_unlocked(
                        expected
                    )
                with self._phase_timing_transaction_ordered():
                    return self._confirm_phase_timing_stream_unlocked(
                        expected
                    )

    def _atomic_rewrite_event_stream_unlocked(
        self,
        expected: bytes,
    ) -> None:
        _validate_event_stream_bytes(expected)
        fd, temporary = tempfile.mkstemp(
            dir=str(self.directory),
            prefix=".events-",
            suffix=".tmp",
        )
        replaced = False
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(expected)
                handle.flush()
                _fsync_retry(handle.fileno())
            os.replace(temporary, self.events_path)
            replaced = True
            directory_fd = _open_real_directory(
                self.directory,
                stage="post_replace",
            )
            try:
                _fsync_retry(directory_fd)
            except OSError as exc:
                raise TelemetryDurabilityError(
                    "telemetry parent directory sync failed",
                    stage="post_replace",
                ) from exc
            finally:
                os.close(directory_fd)
        except Exception as exc:
            if not replaced:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
            if replaced:
                raise
            raise TelemetryDurabilityError(
                "telemetry event stream replacement failed",
                stage="pre_replace",
            ) from exc

    def _append_event_unlocked(
        self,
        event: Mapping[str, object],
    ) -> None:
        self.ensure_manifest()
        prior = self._read_event_stream_bytes_unlocked()
        _validate_event_stream_bytes(prior)
        record = self._event_record_bytes(event)
        self._atomic_rewrite_event_stream_unlocked(prior + record)

    def append_event(self, event: Mapping[str, object]) -> None:
        """Append a content-free lifecycle event to the run event stream."""
        if event.get("trace_id") != self.trace_id:
            raise ValueError("event trace id does not match telemetry manifest")
        if event.get("type") == "dispatch":
            required = ("phase", "agent", "attempt", "reason", "outcome", "event_time", "started_at", "ended_at", "duration_ms")
            if any(event.get(key) is None or event.get(key) == "" for key in required):
                raise ValueError("invalid dispatch lifecycle event")
            if event.get("reason") not in _DISPATCH_REASONS:
                raise ValueError("invalid dispatch lifecycle reason")
            if isinstance(event.get("attempt"), bool) or not isinstance(event.get("attempt"), int) or event["attempt"] < 1:
                raise ValueError("invalid dispatch lifecycle attempt")
            if isinstance(event.get("duration_ms"), bool) or not isinstance(event.get("duration_ms"), int) or event["duration_ms"] < 0:
                raise ValueError("invalid dispatch lifecycle duration")
            if not isinstance(event.get("model"), str) or not isinstance(event.get("blocker"), str):
                raise ValueError("invalid dispatch lifecycle metadata")
        with controller_lock_order(
            "telemetry",
            self._controller_lock_identity,
        ):
            with self._write_lock:
                if self._phase_timing_transaction_depth:
                    self._append_event_unlocked(event)
                else:
                    with self._phase_timing_transaction_ordered():
                        self._append_event_unlocked(event)

    def read_spans(self) -> tuple[tuple[ExecutionSpan, ...], tuple[TelemetryDiagnostic, ...]]:
        if not self.spans_path.is_file():
            return (), ()
        raw = self.spans_path.read_text(encoding="utf-8", errors="replace")
        lines = raw.splitlines()
        spans: list[ExecutionSpan] = []
        diagnostics: list[TelemetryDiagnostic] = []
        for index, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("span record must be an object")
                spans.append(ExecutionSpan.from_json_dict(value))
            except json.JSONDecodeError as exc:
                final = index == len(lines) and not raw.endswith("\n")
                diagnostics.append(
                    TelemetryDiagnostic(
                        "truncated-final-line" if final else "invalid-json",
                        str(exc),
                        index,
                    )
                )
            except ValueError as exc:
                diagnostics.append(TelemetryDiagnostic("invalid-span", str(exc), index))
        return tuple(spans), tuple(diagnostics)

    def read_phase_timings(
        self,
    ) -> tuple[tuple[PhaseTimingEvent, ...], tuple[TelemetryDiagnostic, ...]]:
        return self._read_phase_timings_unlocked()

    @staticmethod
    def _parse_phase_timings(
        raw: str,
    ) -> tuple[
        tuple[PhaseTimingEvent, ...],
        tuple[TelemetryDiagnostic, ...],
    ]:
        lines = raw.splitlines()
        events: list[PhaseTimingEvent] = []
        diagnostics: list[TelemetryDiagnostic] = []
        for index, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("event record must be an object")
                if value.get("type") != "phase_timing":
                    continue
                events.append(PhaseTimingEvent.from_json_dict(value))
            except json.JSONDecodeError as exc:
                final = index == len(lines) and not raw.endswith("\n")
                diagnostics.append(
                    TelemetryDiagnostic(
                        "truncated-final-line" if final else "invalid-json",
                        str(exc),
                        index,
                    )
                )
            except ValueError as exc:
                diagnostics.append(
                    TelemetryDiagnostic("invalid-event", str(exc), index)
                )
        return tuple(events), tuple(diagnostics)

    def _read_phase_timings_unlocked(
        self,
    ) -> tuple[tuple[PhaseTimingEvent, ...], tuple[TelemetryDiagnostic, ...]]:
        if not self.events_path.is_file():
            return (), ()
        raw = self.events_path.read_text(encoding="utf-8", errors="replace")
        return self._parse_phase_timings(raw)

    def read_durable_phase_timings(
        self,
    ) -> tuple[
        tuple[PhaseTimingEvent, ...],
        tuple[TelemetryDiagnostic, ...],
    ]:
        """Read timing events only from an exactly confirmed durable stream."""
        with controller_lock_order(
            "telemetry",
            self._controller_lock_identity,
        ):
            with self._write_lock:
                if self._phase_timing_transaction_depth:
                    content = self._current_phase_timing_stream_unlocked()
                    self.confirm_phase_timing_stream(content)
                else:
                    with self._phase_timing_transaction_ordered():
                        content = self._current_phase_timing_stream_unlocked()
                        self.confirm_phase_timing_stream(content)
                return self._parse_phase_timings(
                    content.decode("utf-8")
                )

    @contextmanager
    def phase_timing_transaction(
        self,
    ) -> Iterator[
        tuple[
            tuple[PhaseTimingEvent, ...],
            tuple[TelemetryDiagnostic, ...],
        ]
    ]:
        """Serialize phase timing read/validate/append across store instances."""

        with controller_lock_order(
            "telemetry",
            self._controller_lock_identity,
        ):
            with self._write_lock:
                with self._phase_timing_transaction_ordered() as transaction:
                    yield transaction

    @contextmanager
    def _phase_timing_transaction_ordered(
        self,
    ) -> Iterator[
        tuple[
            tuple[PhaseTimingEvent, ...],
            tuple[TelemetryDiagnostic, ...],
        ]
    ]:

        self.ensure_manifest()
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.phase_timing_lock_path, flags, 0o600)
        locked = False
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise ValueError("phase timing lock must be a regular file")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            locked = True
            current = os.lstat(self.phase_timing_lock_path)
            if (
                not stat.S_ISREG(current.st_mode)
                or (current.st_dev, current.st_ino)
                != (opened.st_dev, opened.st_ino)
            ):
                raise ValueError("phase timing lock identity changed")
            self._phase_timing_transaction_depth += 1
            try:
                yield self._read_phase_timings_unlocked()
            finally:
                self._phase_timing_transaction_depth -= 1
        finally:
            if locked:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
