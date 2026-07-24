"""Python-owned compatibility entry point for Spec phase timing."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from echelon.telemetry.model import PhaseTimingEvent
from echelon.telemetry.store import TelemetryStore


def _timestamp(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def record_phase_start(
    store: TelemetryStore,
    *,
    phase: str,
    budget_seconds: float,
    event_time: str | None = None,
) -> PhaseTimingEvent:
    events, diagnostics = store.read_phase_timings()
    if diagnostics:
        raise ValueError("cannot start phase timing with invalid telemetry events")
    prior = next((event for event in reversed(events) if event.phase == phase), None)
    if prior is not None and prior.event == "started":
        return prior
    event = PhaseTimingEvent.started(
        trace_id=store.trace_id,
        phase=phase,
        budget_seconds=budget_seconds,
        event_time=event_time or _timestamp(),
    )
    store.append_phase_timing(event)
    return event


def record_phase_finish(
    store: TelemetryStore,
    *,
    phase: str,
    event_time: str | None = None,
) -> PhaseTimingEvent:
    events, diagnostics = store.read_phase_timings()
    if diagnostics:
        raise ValueError("cannot finish phase timing with invalid telemetry events")
    prior = next((event for event in reversed(events) if event.phase == phase), None)
    if prior is None or prior.event != "started":
        raise ValueError(f"no active phase timing start event for {phase!r}")
    finished_at = event_time or _timestamp()
    elapsed_seconds = max(
        0.0,
        (_parse_timestamp(finished_at) - _parse_timestamp(prior.event_time)).total_seconds(),
    )
    event = PhaseTimingEvent.finished(
        trace_id=store.trace_id,
        phase=phase,
        budget_seconds=prior.budget_seconds,
        elapsed_seconds=elapsed_seconds,
        event_time=finished_at,
    )
    store.append_phase_timing(event)
    return event


def record_split_metrics(
    store: TelemetryStore,
    *,
    rework_count: int,
    fallback_count: int,
    qa_coverage: float,
    event_time: str | None = None,
) -> None:
    store.append_event(
        {
            "schema_version": 1,
            "type": "split_metrics",
            "trace_id": store.trace_id,
            "event_time": event_time or _timestamp(),
            "rework_count": rework_count,
            "fallback_count": fallback_count,
            "qa_coverage": qa_coverage,
        }
    )


def store_for_run(run_dir: Path) -> TelemetryStore:
    manifest_path = run_dir / "telemetry" / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"telemetry manifest is unavailable for {run_dir}") from exc
    trace_id = manifest.get("trace_id")
    run_id = manifest.get("run_id")
    workflow = manifest.get("workflow")
    profile = manifest.get("profile")
    if not all(isinstance(value, str) and value for value in (trace_id, run_id, workflow)):
        raise ValueError("telemetry manifest has invalid identity")
    if not isinstance(profile, dict):
        raise ValueError("telemetry manifest has invalid profile")
    return TelemetryStore(
        run_dir,
        workflow=workflow,
        run_id=run_id,
        profile=profile,
        trace_id=trace_id,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record append-only Echelon phase timing")
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start_phase")
    start.add_argument("phase")
    start.add_argument("budget_seconds", type=float)
    start.add_argument("--run-dir", type=Path, required=True)
    finish = subparsers.add_parser("end_phase")
    finish.add_argument("phase")
    finish.add_argument("--run-dir", type=Path, required=True)
    split = subparsers.add_parser("record_split_metrics")
    split.add_argument("rework_count", type=int)
    split.add_argument("fallback_count", type=int)
    split.add_argument("qa_coverage", type=float)
    split.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        store = store_for_run(args.run_dir)
        if args.command == "start_phase":
            record_phase_start(store, phase=args.phase, budget_seconds=args.budget_seconds)
        elif args.command == "end_phase":
            record_phase_finish(store, phase=args.phase)
        else:
            record_split_metrics(
                store,
                rework_count=args.rework_count,
                fallback_count=args.fallback_count,
                qa_coverage=args.qa_coverage,
            )
    except Exception as exc:
        print(f"phase timing diagnostic: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
