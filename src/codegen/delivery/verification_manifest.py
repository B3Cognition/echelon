"""Honest verification-boundary manifest for codegen DELIVER.

Every codegen gate is a PROXY. It binds something narrow (unit behaviour at
mocked boundaries, a quality score, a static composition check, a dependency
audit) and leaves the thing that actually matters — *does the delivered system
do its real job, observed from outside?* — unverified. Stacking green gates
manufactures confidence that is decoupled from reality.

This module turns the gate results into an explicit claims-and-boundaries
manifest so DELIVER reports what it did NOT verify, leading with the gaps rather
than the green checks. The operating stance it encodes: **a gate result is a
claim, not a fact, until a human observes the running artifact.** It does not —
and cannot — make codegen self-trustworthy; it stops codegen from pretending it
is.
"""
from __future__ import annotations

from typing import Any

# Per gate: (the claim a PASS supports, what that PASS does NOT bind).
_GATE_BOUNDARIES: dict[str, tuple[str, str]] = {
    "tier1_gate": (
        "unit tests pass",
        "behaviour only at MOCKED / in-process boundaries — no live cross-service "
        "call, no real I/O, no running system",
    ),
    "psi": (
        "code-quality score >= threshold (structure / testability / readability "
        "of the generated files)",
        "nothing about runtime behaviour or whether anything actually runs",
    ),
    "security_gate": (
        "dependency vulnerabilities and licenses (audit) are clean",
        "application correctness or behaviour",
    ),
    "runnable_gate": (
        "the composed entry STATICALLY mounts feature components (build-check)",
        "that the app RENDERS or WORKS with data, and any cross-service integration",
    ),
    "integration_gate": (
        "the services start and a cross-service call parses against the shared schema",
        "that the UI renders REAL data, and full functional behaviour",
    ),
}

# Boundaries no codegen gate can ever bind — only a human observing reality does.
_NEVER_GATED: list[str] = [
    "the delivered system, started in its real environment, does its real job",
    "the UI renders real data from the running backend (observed by a person)",
    "behaviour under the real inputs and load a human would actually exercise",
]

# Gates we name even when ABSENT, so a skipped boundary surfaces as a gap.
_EXPECTED_GATES = ("tier1_gate", "psi", "security_gate", "runnable_gate", "integration_gate")

_HUMAN_LINE = (
    "No gate here observed the artifact doing its real job in its real "
    "environment. Treat every PASS above as a claim, not a fact. "
    "A human must observe the running system before trusting this build."
)


def _passed(state: dict[str, Any], gate: str) -> bool:
    v = state.get(gate)
    if gate == "psi":
        if not isinstance(v, dict):
            return False
        try:
            return float(v.get("score", 0)) >= float(v.get("threshold", 0.7))
        except (TypeError, ValueError):
            return False
    return v == "pass"


def build_manifest(state: dict[str, Any]) -> dict[str, Any]:
    """From a codegen-state.json dict, return:
      {claims: [{gate, status, bound, not_bound}], unverified: [str], human_line: str}
    A gate is a *claim* only if it actually passed; otherwise its boundary
    (and the gate's own absence/failure) is folded into `unverified`."""
    claims: list[dict[str, str]] = []
    unverified: list[str] = []

    for gate in _EXPECTED_GATES:
        bound, not_bound = _GATE_BOUNDARIES[gate]
        if gate in state and _passed(state, gate):
            claims.append({"gate": gate, "status": "pass", "bound": bound, "not_bound": not_bound})
            unverified.append(f"[{gate}] {not_bound}")
        elif gate in state:  # present but not passing
            unverified.append(f"[{gate}] did not pass — {bound} is NOT established")
        else:  # never ran this build
            unverified.append(f"[{gate}] not run this build — {bound} is NOT established")

    unverified.extend(_NEVER_GATED)
    return {"claims": claims, "unverified": unverified, "human_line": _HUMAN_LINE}


def render_markdown(manifest: dict[str, Any]) -> str:
    """Render the manifest, LEADING with what was not verified (the gaps),
    then the demoted green claims. Written as ./codegen-verification.md."""
    lines = ["# Verification boundary — read this before trusting the build", ""]
    lines.append(
        "Every check below is a proxy. This manifest states what each check "
        "leaves unbound, so the green results are not mistaken for a working system."
    )
    lines += ["", "## NOT verified (where ground truth is still missing)", ""]
    for u in manifest["unverified"]:
        lines.append(f"- {u}")
    lines += ["", f"> {manifest['human_line']}", ""]
    lines += ["## What each gate actually established (claims, not facts)", ""]
    for c in manifest["claims"]:
        lines.append(f"- **{c['gate']}** (pass): {c['bound']}.")
        lines.append(f"  - does NOT bind: {c['not_bound']}")
    lines.append("")
    return "\n".join(lines)


def terminal_summary(manifest: dict[str, Any]) -> str:
    """Short terminal text: lead with the unverified count, demote the verdict.
    Never prints 'complete' or 'verified ✓' — delivery is a claim."""
    n = len(manifest["unverified"])
    passed = ", ".join(c["gate"] for c in manifest["claims"]) or "none"
    return (
        f"[CODEGEN] DELIVERED — unverified beyond its gates: {n} boundaries were "
        f"not bound by any check; see codegen-verification.md.\n"
        f"  {manifest['human_line']}\n"
        f"  gates that passed (claims only): {passed}"
    )
