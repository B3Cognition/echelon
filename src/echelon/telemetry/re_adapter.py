"""Reverse-engineering adapter for the shared execution analyzer."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

from echelon.telemetry.analyzer import RunAnalysis
from echelon.telemetry.model import ExecutionSpan, TokenUsage, aggregate_token_usage
from echelon.telemetry.store import TelemetryStore
from harness.re_profiles import migrate_legacy_re_profile


def analyze_re_run(run_dir: Path) -> RunAnalysis:
    run = run_dir.resolve()
    outer = _read_object(run / "state.json")
    inner = _read_object(run / "re" / "state.json")
    manifest = _read_object(run / "telemetry" / "manifest.json")
    profile, profile_source = _profile(outer, inner, manifest)
    spans, span_diagnostics = _spans(run, profile, manifest)
    tokens, known_dispatches, unknown_dispatches = _tokens(spans)
    active_duration, active_duration_source = _active_duration(outer, inner)
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
    audits = inner.get("re_semantic_domain_audits")
    audited_domains = len(audits) if isinstance(audits, Mapping) else 0
    repaired_domains = _repaired_domain_count(sources, audits)
    validator_dispatches = by_phase.get("re-extract-5-validate", {}).get("dispatches", 0)
    audit_marker = inner.get("re_semantic_audit")
    semantic_status = (
        str(audit_marker.get("status"))
        if isinstance(audit_marker, Mapping)
        else ("evaluated" if audited_domains else "unknown")
    )
    compliance = _compliance(profile, tokens, active_duration)
    diagnostics = [item.message for item in span_diagnostics]
    if not tokens.known:
        diagnostics.append("provider token usage is unavailable")
    elif unknown_dispatches:
        diagnostics.append(
            "provider token usage is partial: "
            f"{unknown_dispatches} dispatches did not report usage"
        )
    if active_duration is None:
        diagnostics.append("active execution duration is unavailable")
    if audited_domains:
        diagnostics.append("first-pass repair outcomes were not recorded")
    wall_clock, wall_clock_source = _wall_clock_duration(outer, inner, spans)
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
        known_token_dispatches=known_dispatches,
        unknown_token_dispatches=unknown_dispatches,
        active_duration_ms=active_duration,
        wall_clock_duration_ms=wall_clock,
        by_phase=by_phase,
        repeated_findings=repeated,
        blocking_finding_count=blocking,
        non_blocking_finding_count=non_blocking,
        audited_domain_count=audited_domains,
        repaired_domain_count=repaired_domains,
        first_pass_repair_rate=None,
        validator_dispatches_per_domain=(
            validator_dispatches / audited_domains if audited_domains else None
        ),
        repeated_finding_count=sum(repeated.values()),
        semantic_audit_status=semantic_status,
        baseline=(
            dict(outer["re_baseline"])
            if isinstance(outer.get("re_baseline"), Mapping)
            else {}
        ),
        compliance=compliance,
        provenance={
            "profile": profile_source,
            "tokens": "telemetry/spans.jsonl" if spans else "unavailable",
            "active_duration": active_duration_source,
            "wall_clock_duration": wall_clock_source,
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
            "re/workspace/architecture-map.json",
            "re/quality/semantic-quality-review.json",
            "telemetry/manifest.json",
            "telemetry/spans.jsonl",
        ):
            path = run / relative
            if path.is_file():
                key = f"runs/{report.run_id}/{relative}"
                result[key] = hashlib.sha256(path.read_bytes()).hexdigest()
        quality_root = run / "re/quality/sources"
        if quality_root.is_dir():
            for path in sorted(quality_root.glob("*.json")):
                relative = path.relative_to(run).as_posix()
                result[f"runs/{report.run_id}/{relative}"] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
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
) -> tuple[dict[str, object], str]:
    for raw, source in (
        (inner.get("re_execution_profile"), "re/state.json"),
        (outer.get("re_execution_profile"), "state.json"),
        (manifest.get("profile"), "telemetry/manifest.json (creation snapshot)"),
    ):
        if isinstance(raw, Mapping):
            return dict(raw), source
    return (
        migrate_legacy_re_profile(inner).to_json_dict(),
        "re/state.json (legacy migration)",
    )


def _active_duration(
    outer: Mapping[str, object], inner: Mapping[str, object]
) -> tuple[int | None, str]:
    for raw, source in (
        (inner.get("re_active_duration_ms"), "re/state.json"),
        (outer.get("active_duration_ms"), "state.json"),
    ):
        value = _optional_nonnegative(raw)
        if value is not None:
            return value, source
    return None, "unavailable"


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


def _tokens(spans: Iterable[ExecutionSpan]) -> tuple[TokenUsage, int, int]:
    span_list = tuple(spans)
    known_totals = [
        span.token_usage.total
        for span in span_list
        if span.token_usage.total is not None
    ]
    unknown = sum(1 for span in span_list if not span.token_usage.known)
    if known_totals:
        return (
            aggregate_token_usage(span.token_usage for span in span_list),
            len(known_totals),
            unknown,
        )
    return TokenUsage.unknown(), 0, unknown


def _by_phase(spans: Iterable[ExecutionSpan]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for span in spans:
        phase = str(span.attributes.get("echelon.workflow.phase") or span.name)
        bucket = result.setdefault(phase, {"dispatches": 0, "duration_ms": 0, "tokens": 0, "known_token_dispatches": 0, "unknown_token_dispatches": 0})
        bucket["dispatches"] += 1
        bucket["duration_ms"] += span.duration_ms
        bucket["tokens"] += int(span.token_usage.total or 0)
        bucket["known_token_dispatches" if span.token_usage.known else "unknown_token_dispatches"] += 1
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
    aggregate = _read_object(run / "re/quality/semantic-quality-review.json")
    failures = aggregate.get("failures")
    if isinstance(failures, list):
        for failure in failures:
            if not isinstance(failure, Mapping):
                continue
            finding_records = failure.get("semantic_finding_records")
            if isinstance(finding_records, list) and finding_records:
                for finding in finding_records:
                    if isinstance(finding, Mapping):
                        _count_message(
                            messages,
                            finding.get("text")
                            or finding.get("message")
                            or finding.get("finding"),
                        )
                continue
            raw_findings = failure.get("semantic_findings")
            if isinstance(raw_findings, list):
                for finding in raw_findings:
                    _count_message(messages, finding)
        repeated = {key: count for key, count in messages.items() if count > 1}
        return dict(sorted(repeated.items())), len(failures), 0

    blocking = 0
    audits = inner.get("re_semantic_domain_audits")
    records = audits.values() if isinstance(audits, Mapping) else ()
    for record in records:
        if not isinstance(record, Mapping):
            continue
        review = record.get("review") if isinstance(record.get("review"), Mapping) else record
        findings = review.get("findings") if isinstance(review, Mapping) else None
        if not isinstance(findings, list):
            continue
        if str(review.get("verdict") or "").upper() == "REPAIR":
            blocking += 1
        for finding in findings:
            if isinstance(finding, str):
                _count_message(messages, finding)
            elif isinstance(finding, Mapping):
                _count_message(
                    messages,
                    finding.get("message")
                    or finding.get("finding")
                    or finding.get("reason"),
                )
    repeated = {key: count for key, count in messages.items() if count > 1}
    return dict(sorted(repeated.items())), blocking, 0


def _count_message(messages: dict[str, int], raw: object) -> None:
    message = " ".join(str(raw or "").casefold().split())
    if message:
        messages[message] = messages.get(message, 0) + 1


def _repaired_domain_count(
    sources: Mapping[object, object], audits: object
) -> int:
    repaired: set[tuple[str, str]] = set()
    for source_id, source_state in sources.items():
        if not isinstance(source_state, Mapping):
            continue
        domain_repairs = source_state.get("domain_repairs")
        if not isinstance(domain_repairs, Mapping):
            continue
        repaired.update(
            (str(source_id), str(domain_id))
            for domain_id, count in domain_repairs.items()
            if _nonnegative(count) > 0
        )
    if not isinstance(audits, Mapping):
        return len(repaired)

    current: set[tuple[str, str]] = set()
    for key, record in audits.items():
        if isinstance(record, Mapping):
            source_id = record.get("source_id")
            domain_id = record.get("domain_id")
            if isinstance(source_id, str) and isinstance(domain_id, str):
                current.add((source_id, domain_id))
                continue
        if isinstance(key, str) and "/" in key:
            source_id, domain_id = key.split("/", 1)
            current.add((source_id, domain_id))
    return len(repaired & current)


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


def _wall_clock_duration(
    outer: Mapping[str, object],
    inner: Mapping[str, object],
    spans: Iterable[ExecutionSpan],
) -> tuple[int | None, str]:
    for raw_intervals in (
        inner.get("re_execution_intervals"),
        outer.get("execution_intervals"),
    ):
        duration = _timestamp_range(raw_intervals, "started_at", "ended_at")
        if duration is not None:
            return duration, "RE lifecycle intervals"
    duration = _timestamp_range(spans, "start_time", "end_time")
    if duration is not None:
        return duration, "telemetry span timestamps"
    return None, "unavailable"


def _timestamp_range(values: object, start_key: str, end_key: str) -> int | None:
    if not isinstance(values, Iterable) or isinstance(
        values, (str, bytes, Mapping)
    ):
        return None
    starts: list[datetime] = []
    ends: list[datetime] = []
    for value in values:
        if isinstance(value, ExecutionSpan):
            raw_start = getattr(value, start_key, None)
            raw_end = getattr(value, end_key, None)
        elif isinstance(value, Mapping):
            raw_start = value.get(start_key)
            raw_end = value.get(end_key)
        else:
            continue
        start = _timestamp(raw_start)
        end = _timestamp(raw_end)
        if start is not None and end is not None:
            starts.append(start)
            ends.append(end)
    if not starts:
        return None
    return max(0, int((max(ends) - min(starts)).total_seconds() * 1000))


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _optional_nonnegative(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0, int(value))


def _nonnegative(value: object) -> int:
    parsed = _optional_nonnegative(value)
    return parsed if parsed is not None else 0
