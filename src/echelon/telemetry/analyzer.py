"""Workflow-neutral aggregation types for local Echelon run analysis."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from echelon.telemetry.model import TokenUsage


@dataclass(frozen=True)
class RunAnalysis:
    schema_version: int
    run_id: str
    workflow: str
    status: str
    phase: str
    profile: dict[str, object]
    source_count: int
    domain_count: int
    domain_repairs_by_source: dict[str, int]
    partial_debt_source_count: int
    tokens: TokenUsage
    known_token_dispatches: int
    unknown_token_dispatches: int
    active_duration_ms: int | None
    wall_clock_duration_ms: int | None
    by_phase: dict[str, dict[str, int]] = field(default_factory=dict)
    repeated_findings: dict[str, int] = field(default_factory=dict)
    blocking_finding_count: int = 0
    non_blocking_finding_count: int = 0
    audited_domain_count: int = 0
    repaired_domain_count: int = 0
    first_pass_repair_rate: float | None = None
    validator_dispatches_per_domain: float | None = None
    repeated_finding_count: int = 0
    semantic_audit_status: str = "unknown"
    baseline: dict[str, object] = field(default_factory=dict)
    dimensions: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)
    workflow_metrics: dict[str, object] = field(default_factory=dict)
    compliance: dict[str, str] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()

    @property
    def token_coverage(self) -> float | None:
        """Share of recorded provider dispatches that reported token usage.

        ``None`` deliberately means that no dispatch telemetry is available, not
        that every dispatch failed to report usage.
        """
        dispatches = self.known_token_dispatches + self.unknown_token_dispatches
        return self.known_token_dispatches / dispatches if dispatches else None

    @property
    def token_status(self) -> str:
        if not self.tokens.known:
            return "unavailable"
        if self.unknown_token_dispatches:
            return "partial"
        return "complete"

    def to_json_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["tokens"] = self.tokens.to_json_dict()
        payload["tokens"]["known"] = self.tokens.known
        payload["tokens"]["known_dispatches"] = self.known_token_dispatches
        payload["tokens"]["unknown_dispatches"] = self.unknown_token_dispatches
        payload["tokens"]["coverage"] = self.token_coverage
        payload["tokens"]["status"] = self.token_status
        return payload
