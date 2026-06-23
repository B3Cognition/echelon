"""Executes a runnable_contract against the composed whole. L1 (hard) = liveness
AND the primary surface; L2 (scored) = remaining surfaces. The probe_fn is
injected so the L1/L2 decision logic is pure and unit-testable; the real probe
families (browser/http/exec) and the ephemeral-sandbox lifecycle wrap it (Task 5
in the design's execution-environment section)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from codegen.schema.runnable_contract import RunnableContract


@dataclass
class ProbeOutcome:
    live: bool
    present: dict[str, bool]   # REQ id -> surface observed in the running whole


@dataclass
class RunnableGateResult:
    passed: bool               # L1 verdict (the hard gate)
    level: str                 # "L1"
    surface_score: float       # L2 score: fraction of surfaces[] present
    failures: list[str] = field(default_factory=list)


def run_runnable_gate(
    contract: RunnableContract,
    workspace: str,
    *,
    probe_fn: Callable[[str, RunnableContract, int | None], ProbeOutcome],
    port: int | None = None,
) -> RunnableGateResult:
    outcome = probe_fn(workspace, contract, port)
    failures: list[str] = []

    if not outcome.live:
        failures.append(f"liveness failed: {contract.liveness!r}")

    primary_req = contract.primary_surface["req"]
    if not outcome.present.get(primary_req, False):
        failures.append(
            f"primary surface {primary_req} not present: "
            f"{contract.primary_surface['assert']!r}"
        )

    surfaces = contract.surfaces
    present = sum(1 for s in surfaces if outcome.present.get(s["req"], False))
    surface_score = (present / len(surfaces)) if surfaces else 1.0

    return RunnableGateResult(
        passed=not failures,
        level="L1",
        surface_score=surface_score,
        failures=failures,
    )
