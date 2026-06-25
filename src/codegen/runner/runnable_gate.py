"""Executes a runnable_contract against the composed whole. L1 (hard) = liveness
AND the primary surface; L2 (scored) = remaining surfaces. The probe_fn is
injected so the L1/L2 decision logic is pure and unit-testable; the real probe
families (browser/http/exec) and the ephemeral-sandbox lifecycle wrap it (Task 5
in the design's execution-environment section)."""
from __future__ import annotations

import os
import re
import socket
import subprocess
from dataclasses import dataclass, field
from typing import Callable

from codegen.schema.runnable_contract import RunnableContract

# Components a composed entry mounts that are framework/shell scaffolding, not
# evidence of real feature composition — excluded when judging stub-vs-wired.
_SHELL_COMPONENTS = frozenset({
    "App", "React", "StrictMode", "Fragment", "Suspense", "ErrorBoundary",
    "Router", "BrowserRouter", "HashRouter", "Routes", "Route", "Provider",
    "ReactFlowProvider", "QueryClientProvider", "Outlet",
})
# Entry/composition source filenames worth reading as evidence.
_ENTRY_BASENAMES = ("App", "main", "index", "Root", "root")
_ENTRY_EXTS = (".tsx", ".jsx", ".ts", ".js")


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


def composed_components(evidence: str) -> set[str]:
    """Return the set of non-shell PascalCase components mounted in `evidence`
    (entry/composition source or built bundle). A stub entry like
    `<main>echelon</main>` mounts none; a wired app mounts CatalogTable, etc."""
    mounted = set(re.findall(r"<([A-Z][A-Za-z0-9_]+)", evidence))
    return {c for c in mounted if c not in _SHELL_COMPONENTS}


def composition_is_real(evidence: str, min_components: int = 1) -> bool:
    """Deterministic stub-vs-wired check: the composed entry mounts at least
    `min_components` real feature components. Catches the `App = <main>echelon</main>`
    stub (0 feature mounts) that built + served HTTP 200 yet rendered nothing."""
    return len(composed_components(evidence)) >= min_components


def _gather_composition_evidence(workspace: str) -> str:
    """Read the app's entry/composition source (App/main/index/Root under any
    `src/` dir, excluding node_modules/dist/tests); fall back to the built
    bundle if no entry source is found. Bounded read."""
    parts: list[str] = []
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in ("node_modules", "dist", "build", ".git")]
        if os.path.basename(root) in ("test", "tests", "__tests__"):
            continue
        for fn in files:
            stem, ext = os.path.splitext(fn)
            if ext in _ENTRY_EXTS and stem in _ENTRY_BASENAMES and not stem.endswith(".test"):
                try:
                    parts.append(open(os.path.join(root, fn), encoding="utf-8", errors="replace").read())
                except OSError:
                    continue
    if not parts:  # fall back to built bundle text
        for root, dirs, files in os.walk(workspace):
            if os.path.basename(root) not in ("dist", "build", "assets"):
                continue
            for fn in files:
                if fn.endswith(".js"):
                    try:
                        parts.append(open(os.path.join(root, fn), encoding="utf-8", errors="replace").read(1_000_000))
                    except OSError:
                        continue
    return "\n".join(parts)


def _browser_probe(workspace: str, contract: RunnableContract, port: int | None) -> ProbeOutcome:
    """SPA composition probe: run the build, then assert the composed entry
    actually mounts feature components (not a stub). Deterministic, no browser
    or backend — catches the entry-point/composition gap that shipped a Psi=1.0
    app rendering nothing. (A full headless-render check is a higher-fidelity
    follow-up; this catches the motivating stub bug today.)"""
    built_ok = True
    if contract.build:
        try:
            proc = subprocess.run(
                contract.build, shell=True, cwd=workspace,
                capture_output=True, text=True, timeout=900,
            )
            built_ok = proc.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            built_ok = False

    evidence = _gather_composition_evidence(workspace)
    composed = composition_is_real(evidence)
    # liveness = the app builds AND its entry composes real components (a stub
    # that "builds" but mounts nothing is not live in any meaningful sense).
    live = built_ok and composed
    # every declared surface shares the composition signal (no per-surface
    # render data without a backend); L2 is scored/non-blocking regardless.
    present = {contract.primary_surface["req"]: composed}
    for s in contract.surfaces:
        present[s["req"]] = composed
    return ProbeOutcome(live=live, present=present)


def _http_probe(workspace: str, contract: RunnableContract, port: int | None) -> ProbeOutcome:
    """service: build, start on `port`, assert liveness + surfaces over HTTP."""
    raise NotImplementedError("wired during execution against the running worktree")


def _exec_probe(workspace: str, contract: RunnableContract, port: int | None) -> ProbeOutcome:
    """cli/library: build, run `--help`/import smoke; no server."""
    raise NotImplementedError("wired during execution against the running worktree")


def make_probe(kind: str):
    return {"spa": _browser_probe, "service": _http_probe,
            "cli": _exec_probe, "library": _exec_probe}[kind]
