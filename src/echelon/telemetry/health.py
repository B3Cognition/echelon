"""Deterministic, observe-only health aggregation for execution analyses."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
from statistics import median
from typing import Iterable, Mapping

from echelon.telemetry.analyzer import RunAnalysis


_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
_REPAIR_REASONS = frozenset({"semantic_repair", "deterministic_repair"})


@dataclass(frozen=True)
class HealthFinding:
    code: str
    severity: str
    scope: str
    subject: str
    affected_runs: int
    eligible_runs: int
    evidence: str
    observed: object | None = None
    comparison: object | None = None

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class HealthReport:
    schema_version: int
    workflow: str
    state: str
    cohort: dict[str, object]
    summary: dict[str, object]
    phase_observations: dict[str, dict[str, object]]
    findings: tuple[HealthFinding, ...]
    excluded_runs: dict[str, int]
    diagnostics: tuple[str, ...]

    def to_json_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["findings"] = [
            finding.to_json_dict() for finding in self.findings
        ]
        return payload


def analyze_spec_health(reports: Iterable[RunAnalysis]) -> HealthReport:
    """Aggregate compatible Spec analyses without reading or mutating run files."""
    discovered = tuple(reports)
    if not discovered:
        return HealthReport(
            schema_version=1,
            workflow="spec",
            state="INSUFFICIENT_DATA",
            cohort={
                "latest_run": None,
                "eligible_runs": 0,
                "discovered_runs": 0,
                "identity": {},
            },
            summary={
                "runs": 0,
                "blocked_runs": 0,
                "dispatches": 0,
                "telemetry_coverage": None,
            },
            phase_observations={},
            findings=(),
            excluded_runs={},
            diagnostics=("no Spec run analyses were supplied",),
        )

    latest = max(discovered, key=_run_order_key)
    latest_identity = _cohort_identity(latest)
    eligible: list[RunAnalysis] = []
    excluded: Counter[str] = Counter()
    for report in discovered:
        reason = _incompatibility(latest, latest_identity, report)
        if reason is None:
            eligible.append(report)
        else:
            excluded[reason] += 1
    eligible.sort(key=_run_order_key)

    phase_order = _phase_order(eligible, latest)
    phase_observations = _phase_observations(eligible, phase_order)
    findings: list[HealthFinding] = []
    run_count = len(eligible)
    dispatch_totals = [_dispatch_total(report) for report in eligible]
    usable_runs = sum(total > 0 for total in dispatch_totals)
    blocked_runs = sum(_is_blocked(report) for report in eligible)

    if usable_runs == 0:
        findings.append(
            HealthFinding(
                code="telemetry.dispatches_unavailable",
                severity="warning",
                scope="telemetry",
                subject="dispatches",
                affected_runs=run_count,
                eligible_runs=run_count,
                evidence="No eligible run contains usable dispatch lifecycle telemetry.",
                observed=0,
            )
        )
    elif usable_runs < run_count:
        findings.append(
            HealthFinding(
                code="telemetry.dispatches_partial",
                severity="warning",
                scope="telemetry",
                subject="dispatches",
                affected_runs=run_count - usable_runs,
                eligible_runs=run_count,
                evidence=(
                    f"{run_count - usable_runs}/{run_count} eligible runs lack "
                    "dispatch lifecycle telemetry."
                ),
                observed=usable_runs / run_count,
            )
        )

    if blocked_runs:
        findings.append(
            HealthFinding(
                code="reliability.blocked_runs",
                severity="critical",
                scope="run",
                subject="terminal-state",
                affected_runs=blocked_runs,
                eligible_runs=run_count,
                evidence=f"{blocked_runs}/{run_count} eligible runs ended blocked or failed.",
                observed=blocked_runs,
            )
        )

    findings.extend(
        _phase_findings(eligible, phase_observations)
    )

    partial_token_runs = sum(
        report.unknown_token_dispatches > 0 for report in eligible
    )
    if partial_token_runs:
        findings.append(
            HealthFinding(
                code="telemetry.partial_tokens",
                severity="warning",
                scope="telemetry",
                subject="tokens",
                affected_runs=partial_token_runs,
                eligible_runs=run_count,
                evidence=(
                    f"{partial_token_runs}/{run_count} eligible runs contain "
                    "dispatches with unknown token usage."
                ),
                observed=partial_token_runs,
            )
        )

    diagnostic_runs = sum(bool(report.diagnostics) for report in eligible)
    if diagnostic_runs:
        findings.append(
            HealthFinding(
                code="telemetry.diagnostics",
                severity="warning",
                scope="telemetry",
                subject="records",
                affected_runs=diagnostic_runs,
                eligible_runs=run_count,
                evidence=(
                    f"{diagnostic_runs}/{run_count} eligible runs report "
                    "telemetry data limitations."
                ),
                observed=diagnostic_runs,
            )
        )

    if not _identity_available(latest_identity):
        findings.append(
            HealthFinding(
                code="telemetry.identity_unavailable",
                severity="info",
                scope="telemetry",
                subject="provider/model",
                affected_runs=1,
                eligible_runs=run_count,
                evidence=(
                    "The latest run lacks complete provider/model identity; "
                    "cross-run regression comparison is disabled."
                ),
            )
        )

    findings.extend(_performance_findings(eligible, latest))
    findings.sort(key=lambda item: _finding_sort_key(item, phase_order))

    if usable_runs == 0:
        state = "INSUFFICIENT_DATA"
    elif any(
        finding.severity in {"critical", "warning"} for finding in findings
    ):
        state = "DEGRADED"
    else:
        state = "HEALTHY"

    known_tokens = sum(report.known_token_dispatches for report in eligible)
    unknown_tokens = sum(report.unknown_token_dispatches for report in eligible)
    token_dispatches = known_tokens + unknown_tokens
    diagnostics = tuple(
        sorted(
            {
                diagnostic
                for report in eligible
                for diagnostic in report.diagnostics
            }
        )
    )
    return HealthReport(
        schema_version=1,
        workflow="spec",
        state=state,
        cohort={
            "latest_run": latest.run_id,
            "eligible_runs": run_count,
            "discovered_runs": len(discovered),
            "identity": {
                "schema_version": latest_identity["schema_version"],
                "profile": latest_identity["profile"],
                "autonomy_mode": latest_identity["autonomy_mode"],
                "providers": list(latest_identity["providers"]),
                "models": list(latest_identity["models"]),
            },
        },
        summary={
            "runs": run_count,
            "blocked_runs": blocked_runs,
            "dispatches": sum(dispatch_totals),
            "telemetry_coverage": (
                usable_runs / run_count if run_count else None
            ),
            "token_coverage": (
                known_tokens / token_dispatches if token_dispatches else None
            ),
        },
        phase_observations=phase_observations,
        findings=tuple(findings),
        excluded_runs=dict(sorted(excluded.items())),
        diagnostics=diagnostics,
    )


def _cohort_identity(report: RunAnalysis) -> dict[str, object]:
    return {
        "schema_version": report.schema_version,
        "workflow": report.workflow,
        "profile": str(report.profile.get("name") or "unknown"),
        "autonomy_mode": str(
            report.profile.get("autonomy_mode")
            or report.profile.get("mode")
            or "unknown"
        ),
        "providers": _known_dimension_names(report, "by_provider"),
        "models": _known_dimension_names(report, "by_model"),
    }


def _known_dimension_names(
    report: RunAnalysis,
    dimension: str,
) -> tuple[str, ...]:
    values = report.dimensions.get(dimension)
    if not isinstance(values, Mapping):
        return ()
    return tuple(
        sorted(
            key
            for key in values
            if isinstance(key, str) and key and key != "unknown"
        )
    )


def _identity_available(identity: Mapping[str, object]) -> bool:
    return bool(identity.get("providers")) and bool(identity.get("models"))


def _incompatibility(
    latest: RunAnalysis,
    latest_identity: Mapping[str, object],
    candidate: RunAnalysis,
) -> str | None:
    candidate_identity = _cohort_identity(candidate)
    if candidate_identity["schema_version"] != latest_identity["schema_version"]:
        return "schema_mismatch"
    if candidate_identity["workflow"] != latest_identity["workflow"]:
        return "workflow_mismatch"
    if candidate_identity["profile"] != latest_identity["profile"]:
        return "profile_mismatch"
    if candidate_identity["autonomy_mode"] != latest_identity["autonomy_mode"]:
        return "autonomy_mode_mismatch"
    if candidate is latest:
        return None
    if not _identity_available(latest_identity) or not _identity_available(
        candidate_identity
    ):
        return "identity_unavailable"
    if candidate_identity["providers"] != latest_identity["providers"]:
        return "provider_mismatch"
    if candidate_identity["models"] != latest_identity["models"]:
        return "model_mismatch"
    return None


def _run_order_key(report: RunAnalysis) -> tuple[datetime, str]:
    recency = report.workflow_metrics.get("recency")
    value = recency.get("value") if isinstance(recency, Mapping) else None
    parsed = datetime.min.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            candidate = datetime.fromisoformat(value.replace("Z", "+00:00"))
            parsed = (
                candidate.replace(tzinfo=timezone.utc)
                if candidate.tzinfo is None
                else candidate.astimezone(timezone.utc)
            )
        except ValueError:
            pass
    return parsed, report.run_id


def _dispatch_total(report: RunAnalysis) -> int:
    dispatches = report.workflow_metrics.get("dispatches")
    return _nonnegative(dispatches.get("total")) if isinstance(dispatches, Mapping) else 0


def _is_blocked(report: RunAnalysis) -> bool:
    terminal = f"{report.status} {report.phase}".casefold()
    return any(word in terminal for word in ("blocked", "failed", "error"))


def _phase_order(
    reports: Iterable[RunAnalysis],
    latest: RunAnalysis,
) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    sequence = (latest,) + tuple(
        report for report in reports if report is not latest
    )
    for report in sequence:
        phases = report.workflow_metrics.get("phase_order")
        if isinstance(phases, list):
            for phase in phases:
                if isinstance(phase, str) and phase and phase not in seen:
                    seen.add(phase)
                    ordered.append(phase)
    extras: set[str] = set()
    for report in sequence:
        dispatches = report.workflow_metrics.get("dispatches")
        by_phase = dispatches.get("by_phase") if isinstance(dispatches, Mapping) else None
        if isinstance(by_phase, Mapping):
            extras.update(
                phase for phase in by_phase if isinstance(phase, str) and phase
            )
    ordered.extend(sorted(extras - seen))
    return tuple(ordered)


def _phase_observations(
    reports: Iterable[RunAnalysis],
    phase_order: tuple[str, ...],
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for phase in phase_order:
        result[phase] = {
            "dispatches": 0,
            "repairs": 0,
            "manual_reruns": 0,
            "provider_retries": 0,
            "errors": 0,
            "max_attempt": 0,
            "blockers": {},
        }
    for report in reports:
        dispatches = report.workflow_metrics.get("dispatches")
        by_phase = dispatches.get("by_phase") if isinstance(dispatches, Mapping) else None
        if isinstance(by_phase, Mapping):
            for phase, raw_bucket in by_phase.items():
                if not isinstance(phase, str) or not isinstance(raw_bucket, Mapping):
                    continue
                bucket = result.setdefault(
                    phase,
                    {
                        "dispatches": 0,
                        "repairs": 0,
                        "manual_reruns": 0,
                        "provider_retries": 0,
                        "errors": 0,
                        "max_attempt": 0,
                        "blockers": {},
                    },
                )
                reasons = raw_bucket.get("by_reason")
                reason_counts = reasons if isinstance(reasons, Mapping) else {}
                bucket["dispatches"] = int(bucket["dispatches"]) + _nonnegative(
                    raw_bucket.get("total")
                )
                bucket["repairs"] = int(bucket["repairs"]) + sum(
                    _nonnegative(reason_counts.get(reason))
                    for reason in _REPAIR_REASONS
                )
                bucket["manual_reruns"] = int(
                    bucket["manual_reruns"]
                ) + _nonnegative(reason_counts.get("manual_rerun"))
                bucket["provider_retries"] = int(
                    bucket["provider_retries"]
                ) + _nonnegative(reason_counts.get("provider_retry"))
                bucket["errors"] = int(bucket["errors"]) + _nonnegative(
                    raw_bucket.get("errors")
                )
                bucket["max_attempt"] = max(
                    int(bucket["max_attempt"]),
                    _nonnegative(raw_bucket.get("max_attempt")),
                )
        blockers = report.workflow_metrics.get("blockers_by_phase")
        if isinstance(blockers, Mapping):
            for phase, raw_reasons in blockers.items():
                if not isinstance(phase, str) or not isinstance(raw_reasons, Mapping):
                    continue
                bucket = result.setdefault(
                    phase,
                    {
                        "dispatches": 0,
                        "repairs": 0,
                        "manual_reruns": 0,
                        "provider_retries": 0,
                        "errors": 0,
                        "max_attempt": 0,
                        "blockers": {},
                    },
                )
                blocker_counts = bucket["blockers"]
                if not isinstance(blocker_counts, dict):
                    continue
                for reason, count in raw_reasons.items():
                    if isinstance(reason, str) and reason:
                        blocker_counts[reason] = _nonnegative(
                            blocker_counts.get(reason)
                        ) + _nonnegative(count)
    for bucket in result.values():
        blockers = bucket.get("blockers")
        if isinstance(blockers, dict):
            bucket["blockers"] = dict(sorted(blockers.items()))
    return result


def _phase_findings(
    reports: list[RunAnalysis],
    observations: Mapping[str, Mapping[str, object]],
) -> list[HealthFinding]:
    findings: list[HealthFinding] = []
    run_count = len(reports)
    for phase, values in observations.items():
        repairs = _nonnegative(values.get("repairs"))
        reruns = _nonnegative(values.get("manual_reruns"))
        retries = _nonnegative(values.get("provider_retries"))
        errors = _nonnegative(values.get("errors"))
        if repairs:
            findings.append(
                _phase_finding(
                    "convergence.phase_repairs",
                    phase,
                    repairs,
                    _affected_phase_runs(reports, phase, _REPAIR_REASONS),
                    run_count,
                    f"{phase} required {repairs} semantic or deterministic repair dispatches.",
                )
            )
        if reruns:
            findings.append(
                _phase_finding(
                    "convergence.manual_reruns",
                    phase,
                    reruns,
                    _affected_phase_runs(reports, phase, {"manual_rerun"}),
                    run_count,
                    f"{phase} was manually replayed {reruns} times.",
                )
            )
        if retries:
            findings.append(
                _phase_finding(
                    "reliability.provider_retries",
                    phase,
                    retries,
                    _affected_phase_runs(reports, phase, {"provider_retry"}),
                    run_count,
                    f"{phase} required {retries} provider result retries.",
                )
            )
        if errors:
            findings.append(
                _phase_finding(
                    "reliability.dispatch_errors",
                    phase,
                    errors,
                    _affected_phase_error_runs(reports, phase),
                    run_count,
                    f"{phase} recorded {errors} failed dispatches.",
                )
            )
        blockers = values.get("blockers")
        if isinstance(blockers, Mapping):
            for reason, count in blockers.items():
                parsed = _nonnegative(count)
                if not parsed or not isinstance(reason, str):
                    continue
                findings.append(
                    HealthFinding(
                        code="reliability.blocker",
                        severity="warning",
                        scope="phase",
                        subject=f"{phase}:{reason}",
                        affected_runs=_affected_blocker_runs(
                            reports, phase, reason
                        ),
                        eligible_runs=run_count,
                        evidence=f"{phase} recorded blocker {reason!r} {parsed} times.",
                        observed=parsed,
                    )
                )
    return findings


def _phase_finding(
    code: str,
    phase: str,
    observed: int,
    affected_runs: int,
    eligible_runs: int,
    evidence: str,
) -> HealthFinding:
    return HealthFinding(
        code=code,
        severity="warning",
        scope="phase",
        subject=phase,
        affected_runs=affected_runs,
        eligible_runs=eligible_runs,
        evidence=evidence,
        observed=observed,
    )


def _affected_phase_runs(
    reports: Iterable[RunAnalysis],
    phase: str,
    reasons: Iterable[str],
) -> int:
    expected = set(reasons)
    affected = 0
    for report in reports:
        bucket = _phase_bucket(report, phase)
        raw_reasons = bucket.get("by_reason")
        values = raw_reasons if isinstance(raw_reasons, Mapping) else {}
        if any(_nonnegative(values.get(reason)) for reason in expected):
            affected += 1
    return affected


def _affected_phase_error_runs(
    reports: Iterable[RunAnalysis],
    phase: str,
) -> int:
    return sum(
        _nonnegative(_phase_bucket(report, phase).get("errors")) > 0
        for report in reports
    )


def _affected_blocker_runs(
    reports: Iterable[RunAnalysis],
    phase: str,
    reason: str,
) -> int:
    affected = 0
    for report in reports:
        blockers = report.workflow_metrics.get("blockers_by_phase")
        phase_blockers = blockers.get(phase) if isinstance(blockers, Mapping) else None
        if isinstance(phase_blockers, Mapping) and _nonnegative(
            phase_blockers.get(reason)
        ):
            affected += 1
    return affected


def _phase_bucket(
    report: RunAnalysis,
    phase: str,
) -> Mapping[str, object]:
    dispatches = report.workflow_metrics.get("dispatches")
    by_phase = dispatches.get("by_phase") if isinstance(dispatches, Mapping) else None
    bucket = by_phase.get(phase) if isinstance(by_phase, Mapping) else None
    return bucket if isinstance(bucket, Mapping) else {}


def _performance_findings(
    reports: list[RunAnalysis],
    latest: RunAnalysis,
) -> list[HealthFinding]:
    if len(reports) < 5 or latest not in reports:
        return []
    findings: list[HealthFinding] = []
    for code, subject, accessor in (
        (
            "performance.active_duration_regression",
            "active-duration",
            lambda report: report.active_duration_ms,
        ),
        (
            "performance.token_regression",
            "tokens",
            lambda report: report.tokens.total,
        ),
    ):
        latest_value = accessor(latest)
        preceding = [
            value
            for report in reports
            if report is not latest
            for value in (accessor(report),)
            if value is not None
        ]
        if latest_value is None or len(preceding) < 4:
            continue
        baseline_median = float(median(preceding))
        baseline_p95 = _nearest_rank_percentile(preceding, 0.95)
        if (
            latest_value > baseline_median * 1.5
            and latest_value > baseline_p95
        ):
            findings.append(
                HealthFinding(
                    code=code,
                    severity="info",
                    scope="run",
                    subject=subject,
                    affected_runs=1,
                    eligible_runs=len(reports),
                    evidence=(
                        f"Latest {subject} {latest_value} exceeds the preceding "
                        f"median {baseline_median:g} by more than 50% and p95 "
                        f"{baseline_p95:g}."
                    ),
                    observed=latest_value,
                    comparison={
                        "median": baseline_median,
                        "p95": baseline_p95,
                    },
                )
            )
    return findings


def _nearest_rank_percentile(values: Iterable[int], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return float(ordered[index])


def _finding_sort_key(
    finding: HealthFinding,
    phase_order: tuple[str, ...],
) -> tuple[int, int, int, str, str]:
    phase = finding.subject.split(":", 1)[0]
    try:
        phase_index = phase_order.index(phase)
    except ValueError:
        phase_index = len(phase_order)
    return (
        _SEVERITY_ORDER.get(finding.severity, len(_SEVERITY_ORDER)),
        -finding.affected_runs,
        phase_index,
        finding.subject,
        finding.code,
    )


def _nonnegative(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))
