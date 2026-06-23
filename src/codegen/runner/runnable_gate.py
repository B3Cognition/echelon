"""Executes a runnable_contract against the composed whole. L1 (hard) = liveness
AND the primary surface; L2 (scored) = remaining surfaces. The probe_fn is
injected so the L1/L2 decision logic is pure and unit-testable; the real probe
families (browser/http/exec) and the ephemeral-sandbox lifecycle wrap it (Task 5
in the design's execution-environment section)."""
from __future__ import annotations

import socket
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
    try:
        outcome = probe_fn(workspace, contract, port)
    except Exception as exc:
        return RunnableGateResult(
            passed=False,
            level="L1",
            surface_score=0.0,
            failures=[f"probe error (fail-closed): {type(exc).__name__}: {exc}"],
        )
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


def _free_port() -> int:
    """Return an OS-assigned free TCP port (closed immediately; caller binds)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _browser_probe(workspace: str, contract: RunnableContract, port: int | None) -> ProbeOutcome:
    """SPA: build, serve dist on `port`, drive a headless browser, read the DOM.
    A curl body check is insufficient (client-side render). Teardown always runs."""
    raise NotImplementedError("wired during execution against the running worktree")


def _http_probe(workspace: str, contract: RunnableContract, port: int | None) -> ProbeOutcome:
    """service: build, start on `port`, assert liveness + surfaces over HTTP."""
    raise NotImplementedError("wired during execution against the running worktree")


def _exec_probe(workspace: str, contract: RunnableContract, port: int | None) -> ProbeOutcome:
    """cli/library: build, run `--help`/import smoke; no server."""
    raise NotImplementedError("wired during execution against the running worktree")


def make_probe(kind: str):
    return {"spa": _browser_probe, "service": _http_probe,
            "cli": _exec_probe, "library": _exec_probe}[kind]
