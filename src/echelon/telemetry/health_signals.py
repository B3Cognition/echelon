"""Phase and performance signals derived from normalized run analyses."""

from __future__ import annotations

import math
from statistics import median
from typing import Iterable, Mapping

from echelon.telemetry.analyzer import RunAnalysis
from echelon.telemetry.health_model import HealthFinding


REPAIR_REASONS = frozenset({"semantic_repair", "deterministic_repair"})


def dispatch_total(report: RunAnalysis) -> int:
    dispatches = report.workflow_metrics.get("dispatches")
    return (
        nonnegative(dispatches.get("total"))
        if isinstance(dispatches, Mapping)
        else 0
    )


def is_blocked(report: RunAnalysis) -> bool:
    terminal = f"{report.status} {report.phase}".casefold()
    return any(word in terminal for word in ("blocked", "failed", "error"))


def build_phase_observations(
    reports: Iterable[RunAnalysis],
    phase_order: tuple[str, ...],
) -> dict[str, dict[str, object]]:
    result = {phase: _empty_phase_observation() for phase in phase_order}
    for report in reports:
        _add_dispatch_observations(result, report)
        _add_blocker_observations(result, report)
    for bucket in result.values():
        blockers = bucket.get("blockers")
        if isinstance(blockers, dict):
            bucket["blockers"] = dict(sorted(blockers.items()))
    return result


def build_phase_findings(
    reports: Iterable[RunAnalysis],
    observations: Mapping[str, Mapping[str, object]],
) -> list[HealthFinding]:
    report_list = list(reports)
    findings: list[HealthFinding] = []
    for phase, values in observations.items():
        findings.extend(
            _dispatch_exception_findings(report_list, phase, values)
        )
        findings.extend(_blocker_findings(report_list, phase, values))
    return findings


def build_performance_findings(
    reports: Iterable[RunAnalysis],
    latest: RunAnalysis,
) -> list[HealthFinding]:
    report_list = list(reports)
    if len(report_list) < 5 or latest not in report_list:
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
            for report in report_list
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
                    eligible_runs=len(report_list),
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


def finding_sort_key(
    finding: HealthFinding,
    phase_order: tuple[str, ...],
) -> tuple[int, int, int, str, str]:
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    phase = finding.subject.split(":", 1)[0]
    try:
        phase_index = phase_order.index(phase)
    except ValueError:
        phase_index = len(phase_order)
    return (
        severity_order.get(finding.severity, len(severity_order)),
        -finding.affected_runs,
        phase_index,
        finding.subject,
        finding.code,
    )


def nonnegative(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


def _empty_phase_observation() -> dict[str, object]:
    return {
        "dispatches": 0,
        "repairs": 0,
        "manual_reruns": 0,
        "provider_retries": 0,
        "errors": 0,
        "max_attempt": 0,
        "blockers": {},
    }


def _add_dispatch_observations(
    result: dict[str, dict[str, object]],
    report: RunAnalysis,
) -> None:
    dispatches = report.workflow_metrics.get("dispatches")
    by_phase = (
        dispatches.get("by_phase")
        if isinstance(dispatches, Mapping)
        else None
    )
    if not isinstance(by_phase, Mapping):
        return
    for phase, raw_bucket in by_phase.items():
        if not isinstance(phase, str) or not isinstance(raw_bucket, Mapping):
            continue
        bucket = result.setdefault(phase, _empty_phase_observation())
        reasons = raw_bucket.get("by_reason")
        reason_counts = reasons if isinstance(reasons, Mapping) else {}
        bucket["dispatches"] = int(bucket["dispatches"]) + nonnegative(
            raw_bucket.get("total")
        )
        bucket["repairs"] = int(bucket["repairs"]) + sum(
            nonnegative(reason_counts.get(reason))
            for reason in REPAIR_REASONS
        )
        bucket["manual_reruns"] = int(
            bucket["manual_reruns"]
        ) + nonnegative(reason_counts.get("manual_rerun"))
        bucket["provider_retries"] = int(
            bucket["provider_retries"]
        ) + nonnegative(reason_counts.get("provider_retry"))
        bucket["errors"] = int(bucket["errors"]) + nonnegative(
            raw_bucket.get("errors")
        )
        bucket["max_attempt"] = max(
            int(bucket["max_attempt"]),
            nonnegative(raw_bucket.get("max_attempt")),
        )


def _add_blocker_observations(
    result: dict[str, dict[str, object]],
    report: RunAnalysis,
) -> None:
    blockers = report.workflow_metrics.get("blockers_by_phase")
    if not isinstance(blockers, Mapping):
        return
    for phase, raw_reasons in blockers.items():
        if not isinstance(phase, str) or not isinstance(raw_reasons, Mapping):
            continue
        bucket = result.setdefault(phase, _empty_phase_observation())
        blocker_counts = bucket["blockers"]
        if not isinstance(blocker_counts, dict):
            continue
        for reason, count in raw_reasons.items():
            if isinstance(reason, str) and reason:
                blocker_counts[reason] = nonnegative(
                    blocker_counts.get(reason)
                ) + nonnegative(count)


def _dispatch_exception_findings(
    reports: list[RunAnalysis],
    phase: str,
    values: Mapping[str, object],
) -> list[HealthFinding]:
    findings: list[HealthFinding] = []
    run_count = len(reports)
    definitions = (
        (
            "convergence.phase_repairs",
            nonnegative(values.get("repairs")),
            REPAIR_REASONS,
            "semantic or deterministic repair dispatches",
        ),
        (
            "convergence.manual_reruns",
            nonnegative(values.get("manual_reruns")),
            frozenset({"manual_rerun"}),
            "manual replay dispatches",
        ),
        (
            "reliability.provider_retries",
            nonnegative(values.get("provider_retries")),
            frozenset({"provider_retry"}),
            "provider result retries",
        ),
    )
    for code, observed, reasons, label in definitions:
        if observed:
            findings.append(
                _phase_finding(
                    code,
                    phase,
                    observed,
                    _affected_phase_runs(reports, phase, reasons),
                    run_count,
                    f"{phase} recorded {observed} {label}.",
                )
            )
    errors = nonnegative(values.get("errors"))
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
    return findings


def _blocker_findings(
    reports: list[RunAnalysis],
    phase: str,
    values: Mapping[str, object],
) -> list[HealthFinding]:
    blockers = values.get("blockers")
    if not isinstance(blockers, Mapping):
        return []
    findings: list[HealthFinding] = []
    for reason, count in blockers.items():
        parsed = nonnegative(count)
        if not parsed or not isinstance(reason, str):
            continue
        findings.append(
            HealthFinding(
                code="reliability.blocker",
                severity="warning",
                scope="phase",
                subject=f"{phase}:{reason}",
                affected_runs=_affected_blocker_runs(reports, phase, reason),
                eligible_runs=len(reports),
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
        if any(nonnegative(values.get(reason)) for reason in expected):
            affected += 1
    return affected


def _affected_phase_error_runs(
    reports: Iterable[RunAnalysis],
    phase: str,
) -> int:
    return sum(
        nonnegative(_phase_bucket(report, phase).get("errors")) > 0
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
        phase_blockers = (
            blockers.get(phase) if isinstance(blockers, Mapping) else None
        )
        if isinstance(phase_blockers, Mapping) and nonnegative(
            phase_blockers.get(reason)
        ):
            affected += 1
    return affected


def _phase_bucket(
    report: RunAnalysis,
    phase: str,
) -> Mapping[str, object]:
    dispatches = report.workflow_metrics.get("dispatches")
    by_phase = (
        dispatches.get("by_phase")
        if isinstance(dispatches, Mapping)
        else None
    )
    bucket = by_phase.get(phase) if isinstance(by_phase, Mapping) else None
    return bucket if isinstance(bucket, Mapping) else {}


def _nearest_rank_percentile(
    values: Iterable[int],
    percentile: float,
) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return float(ordered[index])
