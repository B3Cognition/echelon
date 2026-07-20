"""Reverse-engineering adapter for the shared execution analyzer."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

from echelon.telemetry.analyzer import RunAnalysis
from echelon.telemetry.model import ExecutionSpan, TokenUsage
from echelon.telemetry.store import TelemetryStore
from harness.re_profiles import migrate_legacy_re_profile


def analyze_re_run(run_dir: Path) -> RunAnalysis:
    run = run_dir.resolve()
    outer = _read_object(run / "state.json")
    inner = _read_object(run / "re" / "state.json")
    manifest = _read_object(run / "telemetry" / "manifest.json")
    profile = _profile(outer, inner, manifest)
    spans, span_diagnostics = _spans(run, profile, manifest)
    tokens, unknown_dispatches = _tokens(outer, inner, spans)
    active_duration = _optional_nonnegative(
        outer.get("active_duration_ms", inner.get("re_active_duration_ms"))
    )
    by_phase = _by_phase(spans)
    source_states = inner.get("re_source_states")
    sources = source_states if isinstance(source_states, Mapping) else {}
    repairs = {
        str(source_id): sum(
            _nonnegative(value)
            for value in (
                source_state.get("domain_repairs", {}).values()
                if isinstance(source_state, Mapping)
                and isinstance(source_state.get("domain_repairs"), Mapping)
                else ()
            )
        )
        for source_id, source_state in sources.items()
    }
    partial = sum(
        1
        for value in sources.values()
        if isinstance(value, Mapping)
        and value.get("status") == "partial_quality_debt"
    )
    domain_count = _domain_count(run, inner)
    repeated, blocking, non_blocking = _finding_summary(run, inner)
    compliance = _compliance(profile, tokens, active_duration)
    diagnostics = [item.message for item in span_diagnostics]
    if not tokens.known:
        diagnostics.append("provider token usage is unavailable")
    if active_duration is None:
        diagnostics.append("active execution duration is unavailable")
    wall_clock = _wall_clock_duration(run)
    return RunAnalysis(
        schema_version=1,
        run_id=str(outer.get("run_id") or inner.get("run_id") or run.name),
        workflow="re",
        status=str(outer.get("status") or inner.get("status") or "unknown"),
        phase=str(inner.get("phase") or outer.get("phase") or "unknown"),
        profile=profile,
        source_count=len(sources),
        domain_count=domain_count,
        domain_repairs_by_source=dict(sorted(repairs.items())),
        partial_debt_source_count=partial,
        tokens=tokens,
        unknown_token_dispatches=unknown_dispatches,
        active_duration_ms=active_duration,
        wall_clock_duration_ms=wall_clock,
        by_phase=by_phase,
        repeated_findings=repeated,
        blocking_finding_count=blocking,
        non_blocking_finding_count=non_blocking,
        compliance=compliance,
        provenance={
            "profile": "telemetry/manifest.json" if manifest else "run state",
            "tokens": "telemetry/spans.jsonl" if spans else "unavailable",
            "active_duration": "run state" if active_duration is not None else "unavailable",
            "wall_clock_duration": "filesystem timestamps (approximate)",
            "quality": "re/state.json and re/quality/sources",
        },
        diagnostics=tuple(diagnostics),
    )


def analyze_re_runs(runs_dir: Path) -> tuple[RunAnalysis, ...]:
    root = runs_dir.resolve()
    if not root.is_dir():
        return ()
    reports: list[RunAnalysis] = []
    for candidate in sorted(root.iterdir(), key=lambda path: path.name):
        if (
            candidate.is_dir()
            and candidate.name.startswith("re-")
            and (candidate / "state.json").is_file()
            and (candidate / "re/state.json").is_file()
        ):
            reports.append(analyze_re_run(candidate))
    return tuple(reports)


def operational_input_hashes(runs_dir: Path) -> dict[str, str]:
    import hashlib

    result: dict[str, str] = {}
    for report in analyze_re_runs(runs_dir):
        run = runs_dir / report.run_id
        for relative in (
            "state.json",
            "re/state.json",
            "telemetry/manifest.json",
            "telemetry/spans.jsonl",
        ):
            path = run / relative
            if path.is_file():
                key = f"runs/{report.run_id}/{relative}"
                result[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(sorted(result.items()))


def _read_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _profile(
    outer: Mapping[str, object],
    inner: Mapping[str, object],
    manifest: Mapping[str, object],
) -> dict[str, object]:
    for raw in (
        manifest.get("profile"),
        outer.get("re_execution_profile"),
        inner.get("re_execution_profile"),
    ):
        if isinstance(raw, Mapping):
            return dict(raw)
    return migrate_legacy_re_profile(inner).to_json_dict()


def _spans(
    run: Path,
    profile: Mapping[str, object],
    manifest: Mapping[str, object],
) -> tuple[tuple[ExecutionSpan, ...], tuple[object, ...]]:
    trace_id = manifest.get("trace_id")
    if not isinstance(trace_id, str) or not trace_id:
        return (), ()
    store = TelemetryStore(
        run,
        workflow="re",
        run_id=run.name,
        profile=profile,
        trace_id=trace_id,
    )
    return store.read_spans()


def _tokens(
    outer: Mapping[str, object],
    inner: Mapping[str, object],
    spans: Iterable[ExecutionSpan],
) -> tuple[TokenUsage, int]:
    span_list = tuple(spans)
    known_totals = [
        span.token_usage.total
        for span in span_list
        if span.token_usage.total is not None
    ]
    unknown = sum(1 for span in span_list if not span.token_usage.known)
    if known_totals:
        return TokenUsage(reported_total_tokens=sum(known_totals)), unknown
    explicit_unknown = _nonnegative(
        outer.get(
            "unknown_token_dispatches", inner.get("re_unknown_token_dispatches")
        )
    )
    if "token_usage" in outer and explicit_unknown == 0:
        return TokenUsage(reported_total_tokens=_nonnegative(outer["token_usage"])), 0
    if "re_token_usage" in inner and explicit_unknown == 0:
        return TokenUsage(reported_total_tokens=_nonnegative(inner["re_token_usage"])), 0
    return TokenUsage.unknown(), explicit_unknown or unknown


def _by_phase(spans: Iterable[ExecutionSpan]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for span in spans:
        phase = str(span.attributes.get("echelon.workflow.phase") or span.name)
        bucket = result.setdefault(phase, {"dispatches": 0, "duration_ms": 0, "tokens": 0})
        bucket["dispatches"] += 1
        bucket["duration_ms"] += span.duration_ms
        bucket["tokens"] += int(span.token_usage.total or 0)
    return dict(sorted(result.items()))


def _domain_count(run: Path, inner: Mapping[str, object]) -> int:
    architecture = _read_object(run / "re/workspace/architecture-map.json")
    domains = architecture.get("domains")
    if isinstance(domains, list):
        return len(domains)
    audits = inner.get("re_semantic_domain_audits")
    if isinstance(audits, Mapping):
        return len(audits)
    return 0


def _finding_summary(
    run: Path, inner: Mapping[str, object]
) -> tuple[dict[str, int], int, int]:
    messages: dict[str, int] = {}
    blocking = 0
    non_blocking = 0
    audits = inner.get("re_semantic_domain_audits")
    records = audits.values() if isinstance(audits, Mapping) else ()
    for record in records:
        if not isinstance(record, Mapping):
            continue
        review = record.get("review") if isinstance(record.get("review"), Mapping) else record
        findings = review.get("findings") if isinstance(review, Mapping) else None
        if not isinstance(findings, list):
            continue
        for finding in findings:
            if isinstance(finding, str):
                message = " ".join(finding.casefold().split())
                severity = "non_blocking"
            elif isinstance(finding, Mapping):
                raw_message = finding.get("message") or finding.get("finding") or finding.get("reason")
                message = " ".join(str(raw_message or "unknown").casefold().split())
                severity = str(finding.get("severity") or "non_blocking").casefold()
            else:
                continue
            messages[message] = messages.get(message, 0) + 1
            if severity in {"blocking", "critical", "error"}:
                blocking += 1
            else:
                non_blocking += 1
    repeated = {key: count for key, count in messages.items() if count > 1}
    return dict(sorted(repeated.items())), blocking, non_blocking


def _compliance(
    profile: Mapping[str, object], tokens: TokenUsage, active_ms: int | None
) -> dict[str, str]:
    token_limit = _optional_nonnegative(profile.get("hard_token_limit"))
    minute_limit = _optional_nonnegative(profile.get("hard_active_minutes"))
    target = _optional_nonnegative(profile.get("performance_target_minutes"))
    return {
        "token_ceiling": _limit_status(tokens.total, token_limit),
        "active_time_ceiling": _limit_status(
            active_ms, minute_limit * 60_000 if minute_limit is not None else None
        ),
        "performance_target": _limit_status(
            active_ms, target * 60_000 if target is not None else None
        ),
    }


def _limit_status(value: int | None, limit: int | None) -> str:
    if value is None or limit is None:
        return "unknown"
    return "pass" if value <= limit else "exceeded"


def _wall_clock_duration(run: Path) -> int | None:
    paths = [path for path in run.rglob("*") if path.is_file()]
    if not paths:
        return None
    timestamps = [path.stat().st_mtime for path in paths]
    return max(0, int((max(timestamps) - min(timestamps)) * 1000))


def _optional_nonnegative(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0, int(value))


def _nonnegative(value: object) -> int:
    parsed = _optional_nonnegative(value)
    return parsed if parsed is not None else 0
