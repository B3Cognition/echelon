"""Append-only local storage for Echelon execution spans."""

from __future__ import annotations

from contextlib import contextmanager
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


TELEMETRY_SCHEMA_VERSION = 1
OTEL_SEMCONV_VERSION = "1.43.0"
_DISPATCH_REASONS = frozenset({"initial", "planned_iteration", "semantic_repair", "deterministic_repair", "provider_retry", "resume", "manual_rerun"})


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
        self._write_lock = threading.Lock()

    def ensure_manifest(self) -> None:
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
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            dir=str(self.directory), prefix=".manifest-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            Path(temporary).replace(self.manifest_path)
        except Exception:
            Path(temporary).unlink(missing_ok=True)
            raise

    def append_span(self, span: ExecutionSpan) -> None:
        if span.trace_id != self.trace_id:
            raise ValueError("span trace id does not match telemetry manifest")
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
        with self._write_lock:
            self.ensure_manifest()
            record = json.dumps(dict(event), separators=(",", ":"), sort_keys=True)
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(record + "\n")
                handle.flush()
                os.fsync(handle.fileno())

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

    def _read_phase_timings_unlocked(
        self,
    ) -> tuple[tuple[PhaseTimingEvent, ...], tuple[TelemetryDiagnostic, ...]]:
        if not self.events_path.is_file():
            return (), ()
        raw = self.events_path.read_text(encoding="utf-8", errors="replace")
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
                diagnostics.append(TelemetryDiagnostic("invalid-event", str(exc), index))
        return tuple(events), tuple(diagnostics)

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
            yield self._read_phase_timings_unlocked()
        finally:
            if locked:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
