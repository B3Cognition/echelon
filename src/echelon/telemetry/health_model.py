"""Stable data contracts for observe-only telemetry health analysis."""

from __future__ import annotations

from dataclasses import asdict, dataclass


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
