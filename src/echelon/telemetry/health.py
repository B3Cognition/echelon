"""Deterministic orchestration for observe-only telemetry health analysis."""

from __future__ import annotations

from typing import Iterable

from echelon.telemetry.analyzer import RunAnalysis
from echelon.telemetry.health_cohort import (
    CohortSelection,
    identity_available,
    select_spec_cohort,
)
from echelon.telemetry.health_model import HealthFinding, HealthReport
from echelon.telemetry.health_signals import (
    build_performance_findings,
    build_phase_findings,
    build_phase_observations,
    dispatch_total,
    finding_sort_key,
    is_blocked,
)


def analyze_spec_health(reports: Iterable[RunAnalysis]) -> HealthReport:
    """Aggregate compatible Spec analyses without reading or mutating run files."""
    discovered = tuple(reports)
    if not discovered:
        return _empty_report()

    selection = select_spec_cohort(discovered)
    eligible = selection.eligible
    phase_observations = build_phase_observations(
        eligible,
        selection.phase_order,
    )
    dispatch_totals = [dispatch_total(report) for report in eligible]
    usable_runs = sum(total > 0 for total in dispatch_totals)
    blocked_runs = sum(is_blocked(report) for report in eligible)
    findings = [
        *_dispatch_coverage_findings(eligible, usable_runs),
        *_blocked_run_findings(eligible, blocked_runs),
        *build_phase_findings(eligible, phase_observations),
        *_token_coverage_findings(eligible),
        *_diagnostic_findings(eligible),
        *_identity_findings(selection),
        *build_performance_findings(eligible, selection.latest),
    ]
    findings.sort(
        key=lambda finding: finding_sort_key(
            finding,
            selection.phase_order,
        )
    )
    known_tokens = sum(
        report.known_token_dispatches for report in eligible
    )
    unknown_tokens = sum(
        report.unknown_token_dispatches for report in eligible
    )
    token_dispatches = known_tokens + unknown_tokens
    return HealthReport(
        schema_version=1,
        workflow="spec",
        state=_health_state(usable_runs, findings),
        cohort=_cohort_payload(selection, len(discovered)),
        summary={
            "runs": len(eligible),
            "blocked_runs": blocked_runs,
            "dispatches": sum(dispatch_totals),
            "telemetry_coverage": (
                usable_runs / len(eligible) if eligible else None
            ),
            "token_coverage": (
                known_tokens / token_dispatches if token_dispatches else None
            ),
        },
        phase_observations=phase_observations,
        findings=tuple(findings),
        excluded_runs=selection.excluded_runs,
        diagnostics=_diagnostics(eligible),
    )


def _empty_report() -> HealthReport:
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


def _cohort_payload(
    selection: CohortSelection,
    discovered_runs: int,
) -> dict[str, object]:
    identity = selection.identity
    return {
        "latest_run": selection.latest.run_id,
        "eligible_runs": len(selection.eligible),
        "discovered_runs": discovered_runs,
        "identity": {
            "schema_version": identity["schema_version"],
            "profile": identity["profile"],
            "autonomy_mode": identity["autonomy_mode"],
            "providers": list(identity["providers"]),
            "models": list(identity["models"]),
        },
    }


def _dispatch_coverage_findings(
    reports: tuple[RunAnalysis, ...],
    usable_runs: int,
) -> list[HealthFinding]:
    run_count = len(reports)
    if usable_runs == 0:
        return [
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
        ]
    if usable_runs < run_count:
        missing = run_count - usable_runs
        return [
            HealthFinding(
                code="telemetry.dispatches_partial",
                severity="warning",
                scope="telemetry",
                subject="dispatches",
                affected_runs=missing,
                eligible_runs=run_count,
                evidence=(
                    f"{missing}/{run_count} eligible runs lack dispatch "
                    "lifecycle telemetry."
                ),
                observed=usable_runs / run_count,
            )
        ]
    return []


def _blocked_run_findings(
    reports: tuple[RunAnalysis, ...],
    blocked_runs: int,
) -> list[HealthFinding]:
    if not blocked_runs:
        return []
    return [
        HealthFinding(
            code="reliability.blocked_runs",
            severity="critical",
            scope="run",
            subject="terminal-state",
            affected_runs=blocked_runs,
            eligible_runs=len(reports),
            evidence=(
                f"{blocked_runs}/{len(reports)} eligible runs ended blocked "
                "or failed."
            ),
            observed=blocked_runs,
        )
    ]


def _token_coverage_findings(
    reports: tuple[RunAnalysis, ...],
) -> list[HealthFinding]:
    affected = sum(report.unknown_token_dispatches > 0 for report in reports)
    if not affected:
        return []
    return [
        HealthFinding(
            code="telemetry.partial_tokens",
            severity="warning",
            scope="telemetry",
            subject="tokens",
            affected_runs=affected,
            eligible_runs=len(reports),
            evidence=(
                f"{affected}/{len(reports)} eligible runs contain dispatches "
                "with unknown token usage."
            ),
            observed=affected,
        )
    ]


def _diagnostic_findings(
    reports: tuple[RunAnalysis, ...],
) -> list[HealthFinding]:
    affected = sum(bool(report.diagnostics) for report in reports)
    if not affected:
        return []
    return [
        HealthFinding(
            code="telemetry.diagnostics",
            severity="warning",
            scope="telemetry",
            subject="records",
            affected_runs=affected,
            eligible_runs=len(reports),
            evidence=(
                f"{affected}/{len(reports)} eligible runs report telemetry "
                "data limitations."
            ),
            observed=affected,
        )
    ]


def _identity_findings(
    selection: CohortSelection,
) -> list[HealthFinding]:
    if identity_available(selection.identity):
        return []
    return [
        HealthFinding(
            code="telemetry.identity_unavailable",
            severity="info",
            scope="telemetry",
            subject="provider/model",
            affected_runs=1,
            eligible_runs=len(selection.eligible),
            evidence=(
                "The latest run lacks complete provider/model identity; "
                "cross-run regression comparison is disabled."
            ),
        )
    ]


def _health_state(
    usable_runs: int,
    findings: Iterable[HealthFinding],
) -> str:
    if usable_runs == 0:
        return "INSUFFICIENT_DATA"
    if any(
        finding.severity in {"critical", "warning"}
        for finding in findings
    ):
        return "DEGRADED"
    return "HEALTHY"


def _diagnostics(reports: Iterable[RunAnalysis]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                diagnostic
                for report in reports
                for diagnostic in report.diagnostics
            }
        )
    )
