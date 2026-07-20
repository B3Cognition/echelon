"""Append-only local storage for Echelon execution spans."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from echelon.telemetry.model import ExecutionSpan, TelemetryDiagnostic


TELEMETRY_SCHEMA_VERSION = 1
OTEL_SEMCONV_VERSION = "1.43.0"


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
