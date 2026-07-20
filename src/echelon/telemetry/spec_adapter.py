"""Specification-workflow adapter for shared execution analysis."""

from __future__ import annotations

import json
import hashlib
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping

from echelon.telemetry.analyzer import RunAnalysis
from echelon.telemetry.model import ExecutionSpan, TokenUsage
from echelon.telemetry.store import TelemetryStore


def analyze_spec_run(run_dir: Path) -> RunAnalysis:
    run = run_dir.resolve()
    state = _read_object(run / "state.json")
    manifest = _read_object(run / "telemetry/manifest.json")
    trace_id = manifest.get("trace_id")
    spans: tuple[ExecutionSpan, ...] = ()
    diagnostics: list[str] = []
    if isinstance(trace_id, str) and trace_id:
        store = TelemetryStore(
            run,
            workflow="spec",
            run_id=str(state.get("run_id") or run.name),
            profile=(
                manifest.get("profile")
                if isinstance(manifest.get("profile"), Mapping)
                else {"name": str(state.get("autonomy_mode") or "legacy")}
            ),
            trace_id=trace_id,
        )
        spans, span_diagnostics = store.read_spans()
        diagnostics.extend(item.message for item in span_diagnostics)
    if not spans:
        diagnostics.append("telemetry spans are unavailable")
    tokens, unknown = _tokens(state, spans)
    dimensions = {
        "by_phase": _dimension(spans, "echelon.workflow.phase"),
        "by_agent": _dimension(spans, "echelon.agent.name"),
        "by_model": _dimension(spans, "gen_ai.response.model"),
        "by_dispatch_kind": _dimension(spans, "echelon.dispatch.kind"),
    }
    blockers = Counter(
        str(item)
        for item in state.get("blocked_reason_history", [])
        if isinstance(item, str) and item
    )
    loops = {
        "why": _nonnegative(state.get("why_fail_count")),
        "what": _nonnegative(state.get("what_repair_count")),
        "plan": _nonnegative(state.get("plan_repair_count")),
    }
    by_phase = dimensions["by_phase"]
    return RunAnalysis(
        schema_version=1,
        run_id=str(state.get("run_id") or run.name),
        workflow="spec",
        status=str(state.get("status") or "unknown"),
        phase=str(state.get("phase") or "unknown"),
        profile=(
            dict(manifest["profile"])
            if isinstance(manifest.get("profile"), Mapping)
            else {"name": str(state.get("autonomy_mode") or "legacy")}
        ),
        source_count=0,
        domain_count=0,
        domain_repairs_by_source={},
        partial_debt_source_count=0,
        tokens=tokens,
        unknown_token_dispatches=unknown,
        active_duration_ms=sum(span.duration_ms for span in spans) if spans else None,
        wall_clock_duration_ms=None,
        by_phase=by_phase,
        dimensions=dimensions,
        workflow_metrics={
            "spec_id": str(state.get("spec_id") or ""),
            "repair_loops": loops,
            "repair_dispatches": dimensions["by_dispatch_kind"].get("repair", {}).get("dispatches", 0),
            "repeated_blockers": dict(sorted((key, count) for key, count in blockers.items() if count > 1)),
        },
        provenance={
            "tokens": "telemetry/spans.jsonl" if spans else "state.json",
            "quality": "state.json",
        },
        diagnostics=tuple(diagnostics),
    )


def analyze_spec_runs(runs_dir: Path) -> tuple[RunAnalysis, ...]:
    root = runs_dir.resolve()
    if not root.is_dir():
        return ()
    reports: list[RunAnalysis] = []
    for candidate in sorted(root.iterdir(), key=lambda path: path.name):
        if not candidate.is_dir() or not (candidate / "state.json").is_file():
            continue
        state = _read_object(candidate / "state.json")
        if (candidate / "re/state.json").is_file():
            continue
        run_id = str(state.get("run_id") or candidate.name)
        if state.get("spec_id") or run_id.startswith(("spec-", "squad-")):
            reports.append(analyze_spec_run(candidate))
    return tuple(reports)


def operational_input_hashes(runs_dir: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for report in analyze_spec_runs(runs_dir):
        run = runs_dir / report.run_id
        for relative in ("state.json", "telemetry/manifest.json", "telemetry/spans.jsonl"):
            path = run / relative
            if path.is_file():
                result[f"runs/{report.run_id}/{relative}"] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
    return dict(sorted(result.items()))


def _dimension(
    spans: Iterable[ExecutionSpan], attribute: str
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for span in spans:
        key = str(span.attributes.get(attribute) or "unknown")
        bucket = result.setdefault(
            key, {"dispatches": 0, "duration_ms": 0, "tokens": 0}
        )
        bucket["dispatches"] += 1
        bucket["duration_ms"] += span.duration_ms
        bucket["tokens"] += int(span.token_usage.total or 0)
    return dict(sorted(result.items()))


def _tokens(
    state: Mapping[str, object], spans: Iterable[ExecutionSpan]
) -> tuple[TokenUsage, int]:
    span_list = tuple(spans)
    known = [span.token_usage.total for span in span_list if span.token_usage.known]
    unknown = sum(1 for span in span_list if not span.token_usage.known)
    if known:
        return TokenUsage(reported_total_tokens=sum(int(value or 0) for value in known)), unknown
    raw = state.get("token_usage")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return TokenUsage(reported_total_tokens=max(0, int(raw))), unknown
    return TokenUsage.unknown(), unknown


def _read_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _nonnegative(value: object) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else 0
