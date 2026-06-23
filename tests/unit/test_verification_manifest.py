"""The honest verification-boundary manifest for codegen DELIVER.

Every codegen gate is a proxy that binds something narrow; none observes the
delivered system doing its real job. The manifest makes DELIVER report what it
did NOT verify — green is a claim, not a fact, until a human observes the
running artifact.
"""

import pytest

from codegen.delivery.verification_manifest import (
    build_manifest, render_markdown, terminal_summary,
)


def _state(**over):
    s = {
        "tier1_gate": "pass",
        "psi": {"score": 1.0, "threshold": 0.7},
        "security_gate": "pass",
        "runnable_gate": "pass",
        # NOTE: no integration_gate key — that boundary was not gated this run.
    }
    s.update(over)
    return s


@pytest.mark.unit
def test_manifest_records_claim_and_boundary_per_gate():
    m = build_manifest(_state())
    gates = {c["gate"]: c for c in m["claims"]}
    assert {"tier1_gate", "psi", "security_gate", "runnable_gate"} <= set(gates)
    for c in m["claims"]:
        assert c["bound"] and c["not_bound"]      # every gate states BOTH


@pytest.mark.unit
def test_ungated_boundary_is_listed_unverified():
    m = build_manifest(_state())
    blob = " ".join(m["unverified"]).lower()
    # integration was never gated this run -> must surface as unverified
    assert "integration" in blob
    # the human-ground-truth boundary is always unverified
    assert any("real" in u.lower() and "job" in u.lower() for u in m["unverified"])


@pytest.mark.unit
def test_markdown_leads_with_unverified_not_green():
    md = render_markdown(build_manifest(_state()))
    i_not = md.lower().find("not verified")
    i_claims = md.lower().find("what each gate")
    assert 0 <= i_not < i_claims          # gaps appear before the green claims
    assert "human must observe" in md.lower()


@pytest.mark.unit
def test_terminal_summary_demotes_verdict_language():
    t = terminal_summary(build_manifest(_state()))
    assert "delivered" in t.lower()
    # never claim completeness/verification as fact
    assert "complete" not in t.lower()
    assert "verified ✓" not in t.lower()
    assert "human must observe" in t.lower()


@pytest.mark.unit
def test_failed_or_absent_gate_not_reported_as_a_supporting_claim():
    m = build_manifest(_state(security_gate="fail"))
    gates = {c["gate"]: c for c in m["claims"]}
    # a failed gate is not a green claim
    assert "security_gate" not in gates
    assert any("security" in u.lower() for u in m["unverified"])


@pytest.mark.unit
def test_deliver_phase_wires_the_manifest():
    import pathlib
    spec = pathlib.Path("extension/workflow/phases/codegen-7-deliver.md").read_text()
    assert "verification_manifest" in spec        # calls the module
    assert "codegen-verification.md" in spec      # emits the artifact
    assert 'NEVER report the build as "complete"' in spec or "claim" in spec.lower()
