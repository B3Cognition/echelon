"""Compatible-cohort selection and stable phase ordering."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping

from echelon.telemetry.analyzer import RunAnalysis


@dataclass(frozen=True)
class CohortSelection:
    latest: RunAnalysis
    eligible: tuple[RunAnalysis, ...]
    excluded_runs: dict[str, int]
    identity: dict[str, object]
    phase_order: tuple[str, ...]


def select_spec_cohort(reports: Iterable[RunAnalysis]) -> CohortSelection:
    discovered = tuple(reports)
    if not discovered:
        raise ValueError("cannot select a cohort without run analyses")
    latest = max(discovered, key=run_order_key)
    latest_identity = cohort_identity(latest)
    eligible: list[RunAnalysis] = []
    excluded: Counter[str] = Counter()
    for report in discovered:
        reason = _incompatibility(latest, latest_identity, report)
        if reason is None:
            eligible.append(report)
        else:
            excluded[reason] += 1
    eligible.sort(key=run_order_key)
    return CohortSelection(
        latest=latest,
        eligible=tuple(eligible),
        excluded_runs=dict(sorted(excluded.items())),
        identity=latest_identity,
        phase_order=_phase_order(eligible, latest),
    )


def cohort_identity(report: RunAnalysis) -> dict[str, object]:
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


def identity_available(identity: Mapping[str, object]) -> bool:
    return bool(identity.get("providers")) and bool(identity.get("models"))


def run_order_key(report: RunAnalysis) -> tuple[datetime, str]:
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


def _incompatibility(
    latest: RunAnalysis,
    latest_identity: Mapping[str, object],
    candidate: RunAnalysis,
) -> str | None:
    candidate_identity = cohort_identity(candidate)
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
    if not identity_available(latest_identity) or not identity_available(
        candidate_identity
    ):
        return "identity_unavailable"
    if candidate_identity["providers"] != latest_identity["providers"]:
        return "provider_mismatch"
    if candidate_identity["models"] != latest_identity["models"]:
        return "model_mismatch"
    return None


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
        by_phase = (
            dispatches.get("by_phase")
            if isinstance(dispatches, Mapping)
            else None
        )
        if isinstance(by_phase, Mapping):
            extras.update(
                phase for phase in by_phase if isinstance(phase, str) and phase
            )
    ordered.extend(sorted(extras - seen))
    return tuple(ordered)
