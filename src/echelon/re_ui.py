"""Operator-facing presentation for durable RE v2 protocol state."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
import threading
import time
from typing import IO, Iterator, Mapping

from echelon.ui import banner


_STATUS_ICONS = {
    "complete": "✓",
    "completed": "✓",
    "paused": "◐",
    "in_progress": "▶",
    "active": "▶",
}

_INTERNAL_PROTOCOL_RE = re.compile(r"\bprotocol[- ]?\d+(?:\.\d+)*\b", re.IGNORECASE)


def _public_text(value: object) -> str:
    return _INTERNAL_PROTOCOL_RE.sub("RE v2", str(value))


def _layer(document: Mapping[str, object]) -> str:
    banner_text = str(document.get("banner") or "").strip()
    first = banner_text.split(maxsplit=1)[0] if banner_text else ""
    if first in {"L0", "L1", "L2", "L3", "L4"}:
        return first
    target = str(document.get("target_layer") or "").strip().upper()
    return target if target in {"L0", "L1", "L2", "L3", "L4"} else "RE"


def _public_stage(document: Mapping[str, object]) -> str:
    if "synthesis_status" in document:
        return "WORKSPACE SYNTHESIS"
    return {
        "L0": "L0 INVENTORY",
        "L1": "L1 COMPACT BASELINE",
        "L2": "L2 BEHAVIORAL DEEPENING",
        "L3": "L3 SEMANTIC AUDIT",
        "L4": "L4 EXHAUSTIVE ANALYSIS",
    }.get(_layer(document), "ANALYSIS")


def _status(document: Mapping[str, object]) -> str:
    explicit = str(document.get("status") or "").strip()
    if explicit:
        return explicit
    synthesis = str(document.get("synthesis_status") or "").strip()
    if synthesis == "complete":
        return "complete"
    if synthesis == "in_progress":
        return "in_progress"
    return "unknown"


def _result(document: Mapping[str, object]) -> str:
    explicit = str(document.get("banner") or "").strip()
    if explicit:
        return explicit
    synthesis = str(document.get("synthesis_status") or "").strip()
    quality = str(document.get("input_quality") or "").strip()
    publication = str(document.get("publication_status") or "").strip()
    if synthesis == "in_progress":
        return "RE WORKSPACE SYNTHESIS — IN PROGRESS"
    if synthesis != "complete":
        return "RE WORKSPACE SYNTHESIS — INCOMPLETE"
    if publication == "conflict":
        return "RE WORKSPACE SYNTHESIS — COMPLETE, PUBLICATION CONFLICT"
    if quality == "partial":
        return "RE WORKSPACE SYNTHESIS — COMPLETE OVER ACCEPTED PARTIAL INPUTS"
    return "RE WORKSPACE SYNTHESIS — COMPLETE"


def _scope(document: Mapping[str, object]) -> str:
    selection = document.get("selection")
    if isinstance(selection, Mapping):
        sources = selection.get("selected_sources")
        domains = selection.get("selected_domains")
        if isinstance(sources, int) and isinstance(domains, int):
            return f"{sources} sources · {domains} domains"
        selected_counts = document.get("selected_counts")
        if isinstance(selected_counts, Mapping):
            sources = selected_counts.get("sources")
            domains = selected_counts.get("domains")
            if isinstance(sources, int) and isinstance(domains, int):
                return f"{sources} sources · {domains} domains"
    sources = document.get("sources")
    if isinstance(sources, Mapping):
        complete = sources.get("complete")
        partial = sources.get("partial")
        if isinstance(complete, list) and isinstance(partial, list):
            return f"{len(complete)} complete sources · {len(partial)} partial sources"
    return str(document.get("completion_scope") or "recorded run scope")


def _progress(document: Mapping[str, object]) -> str:
    counts = document.get("artifact_counts")
    if isinstance(counts, Mapping):
        for key in ("total", "selected_l2", "requested_outputs"):
            nested = counts.get(key)
            if isinstance(nested, Mapping):
                accepted = nested.get("accepted")
                required = nested.get("required")
                if isinstance(accepted, int) and isinstance(required, int):
                    return f"{accepted}/{required} accepted"
    slices = document.get("slice_counts")
    if isinstance(slices, Mapping):
        accepted = slices.get("accepted")
        planned = slices.get("planned")
        if isinstance(accepted, int) and isinstance(planned, int):
            return f"{accepted}/{planned} slices accepted"
    if not isinstance(counts, Mapping):
        return "see durable status"
    parts: list[str] = []
    for key, candidates in (
        ("generated", ("generated", "generated_l3", "generated_l2")),
        ("accepted", ("accepted",)),
        ("adopted", ("adopted",)),
    ):
        value = next(
            (counts.get(candidate) for candidate in candidates if isinstance(counts.get(candidate), int)),
            None,
        )
        if isinstance(value, int):
            parts.append(f"{value} {key}")
    return " · ".join(parts) or "see durable status"


def _accepted_total(document: Mapping[str, object]) -> tuple[int, int]:
    counts = document.get("artifact_counts")
    if isinstance(counts, Mapping):
        required = counts.get("required")
        generated = counts.get("generated")
        adopted = counts.get("adopted")
        if all(isinstance(value, int) for value in (required, generated, adopted)):
            return int(generated) + int(adopted), int(required)
        for key in ("total", "selected_l2", "requested_outputs"):
            nested = counts.get(key)
            if isinstance(nested, Mapping):
                accepted = nested.get("accepted")
                required = nested.get("required")
                if isinstance(accepted, int) and isinstance(required, int):
                    return accepted, required
    slices = document.get("slice_counts")
    if isinstance(slices, Mapping):
        accepted = slices.get("accepted")
        planned = slices.get("planned")
        if isinstance(accepted, int) and isinstance(planned, int):
            return accepted, planned
    selection = document.get("selection")
    preflight = document.get("preflight")
    preflight_total = (
        preflight.get("selected_target_count")
        if isinstance(preflight, Mapping)
        else None
    )
    total = (
        preflight_total
        if isinstance(preflight_total, int)
        else selection.get("selected_domains")
        if isinstance(selection, Mapping)
        else 0
    )
    accepted = 0
    if isinstance(counts, Mapping):
        for key in ("generated", "generated_l3", "generated_l2"):
            if isinstance(counts.get(key), int):
                accepted = counts[key]
                break
    return accepted, total if isinstance(total, int) else 0


def print_re_status_card(
    document: Mapping[str, object],
    *,
    title: str = "RE STATUS",
    file: IO[str] | None = None,
) -> None:
    """Render protocol-neutral RE state with the shared Echelon card UI."""
    status = _status(document)
    result = _result(document)
    fields = [
        ("run", str(document.get("run_id") or "unknown")),
        ("scope", _scope(document)),
        ("progress", _progress(document)),
        ("result", result),
    ]
    preflight = document.get("preflight")
    if isinstance(preflight, Mapping) and preflight.get("state") != "not_run":
        preflight_lines = [
            f"{preflight.get('state')} after "
            f"{preflight.get('checked_target_count', 0)}/"
            f"{preflight.get('selected_target_count', 0)} target(s)"
        ]
        measured = preflight.get("max_measured_canonical_json_bytes")
        ceiling = preflight.get("max_canonical_json_bytes")
        if isinstance(measured, int) and isinstance(ceiling, int):
            relation = "exceeds" if measured > ceiling else "within"
            preflight_lines.append(f"{measured} bytes {relation} {ceiling}")
        if preflight.get("provider_dispatch_count") == 0:
            preflight_lines.append("no provider call was made")
        failure = preflight.get("failure")
        if isinstance(failure, Mapping):
            location = str(failure.get("source_id") or "unknown source")
            if failure.get("domain_key") is not None:
                location += f" / {failure['domain_key']}"
            preflight_lines.append(
                f"{location}: {failure.get('reason_code', 'unknown reason')}"
            )
        fields.append(("preflight", "\n".join(preflight_lines)))
    not_run = document.get("not_run")
    if isinstance(not_run, Mapping):
        fields.append(
            (
                "not run",
                "\n".join(
                    f"{str(key).replace('_', ' ')}: {value}"
                    for key, value in not_run.items()
                ),
            )
        )
    post_l4 = document.get("post_l4")
    if isinstance(post_l4, Mapping):
        fields.append(
            (
                "post-L4",
                "\n".join(
                    f"{str(key).replace('_', ' ')}: {value}"
                    for key, value in post_l4.items()
                ),
            )
        )
    next_action = document.get("next_action")
    if isinstance(next_action, str) and next_action.strip() and next_action != "none":
        fields.append(("next", next_action.replace("`", "")))
    public_fields = [(label, _public_text(value)) for label, value in fields]
    banner(
        f"RE v2 · {_public_stage(document)}",
        public_fields,
        subtitle=f"{_STATUS_ICONS.get(status, '✗')} {_public_text(result)}",
        file=file,
    )


def print_re_error(command: str, error: object, *, file: IO[str] | None = None) -> None:
    """Render one actionable RE command error through the shared UI."""
    banner(
        "RE v2 · ERROR",
        [("command", command), ("error", _public_text(error))],
        subtitle="✗ COMMAND FAILED",
        file=file if file is not None else sys.stderr,
    )


@dataclass
class ReProgressTracker:
    """Turn durable RE events into compact protocol-neutral progress lines."""

    layer: str
    total: int
    accepted: int = 0
    provider_active: bool = False

    def consume(self, event: Mapping[str, object]) -> str | None:
        event_type = str(event.get("type") or "")
        payload = event.get("payload")
        details = payload if isinstance(payload, Mapping) else {}
        if event_type in {"dispatch_started", "provider_started"}:
            self.provider_active = True
            return (
                f"[re] {self.layer} · {self.accepted}/{self.total} accepted · "
                "provider dispatch started"
            )
        if event_type in {"dispatch_observed", "provider_completed"}:
            self.provider_active = False
            return None
        if event_type in {
            "artifact_accepted",
            "accepted_slice_recorded",
            "synthesis_artifact_accepted",
        }:
            self.accepted += 1
            return f"[re] {self.layer} · {self.accepted}/{self.total} accepted"
        if event_type in {
            "run_paused",
            "run_failed",
            "run_completed",
            "run_blocked",
        }:
            self.provider_active = False
            state = event_type.removeprefix("run_")
            reason = _public_text(details.get("reason") or "").strip()
            return f"[re] {self.layer} · {state}" + (f" · {reason}" if reason else "")
        return None

    def heartbeat(self) -> str:
        activity = (
            "provider still working"
            if self.provider_active
            else "controller still working"
        )
        return (
            f"[re] {self.layer} · {self.accepted}/{self.total} accepted · "
            f"{activity}"
        )


class _EventMonitor:
    def __init__(
        self,
        run_dir: Path,
        tracker: ReProgressTracker,
        *,
        file: IO[str],
        poll_interval: float,
    ) -> None:
        self._path = Path(run_dir) / "v2" / "events.jsonl"
        self._tracker = tracker
        self._file = file
        self._poll_interval = poll_interval
        self._offset = self._path.stat().st_size if self._path.is_file() else 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._last_visible = time.monotonic()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=min(2.0, max(1.0, self._poll_interval * 4)))
        self._drain()

    def _run(self) -> None:
        while not self._stop.wait(self._poll_interval):
            self._drain()
            now = time.monotonic()
            if now - self._last_visible >= 15:
                print(
                    self._tracker.heartbeat(),
                    file=self._file,
                    flush=True,
                )
                self._last_visible = now

    def _drain(self) -> None:
        if not self._path.is_file():
            return
        try:
            with self._path.open(encoding="utf-8") as handle:
                handle.seek(self._offset)
                while True:
                    line = handle.readline()
                    if not line:
                        break
                    self._offset = handle.tell()
                    try:
                        event = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(event, Mapping):
                        continue
                    message = self._tracker.consume(event)
                    if message is not None:
                        print(message, file=self._file, flush=True)
                        self._last_visible = time.monotonic()
        except (OSError, ValueError):
            return


@contextmanager
def re_progress_session(
    run_dir: Path,
    document: Mapping[str, object],
    *,
    file: IO[str] | None = None,
    poll_interval: float = 0.25,
) -> Iterator[None]:
    """Show start, event progress, and liveness without changing protocol state."""
    output = file if file is not None else sys.stdout
    print_re_status_card(document, title="RE RUN", file=output)
    accepted, total = _accepted_total(document)
    tracker = ReProgressTracker(
        layer=_layer(document),
        total=total,
        accepted=accepted,
    )
    print(
        f"[re] {tracker.layer} · {tracker.accepted}/{tracker.total} accepted · "
        "controller started",
        file=output,
        flush=True,
    )
    monitor = _EventMonitor(
        run_dir,
        tracker,
        file=output,
        poll_interval=poll_interval,
    )
    monitor.start()
    try:
        yield
    finally:
        monitor.stop()


__all__ = (
    "ReProgressTracker",
    "print_re_error",
    "print_re_status_card",
    "re_progress_session",
)
