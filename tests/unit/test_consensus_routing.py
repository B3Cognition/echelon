"""phase3-consensus ownership-based re-dispatch routing (definition.yaml).

Regression guard for the 002-echelon-control-fe non-convergence loop: the
consensus gate routed EVERY WHY3 FAIL to phase3-how (ARCHITECT). A WHY3 FAIL is
a spec-quality failure (Structure gate / glossary / atomicity / ambiguity) owned
by CARTOGRAPHER — ARCHITECT cannot amend spec.md, so the gate reproduced the
identical FAIL every cycle until the iteration-10 force-kill. The phase spec
(phase3-consensus.md §Consensus Gate Check) already documents the correct
ownership routing; definition.yaml must match it:

    WHY3 CRITICAL spec issues   -> WHAT (phase1-what / CARTOGRAPHER)
    ASSESS2 CRITICAL feasibility -> HOW  (phase3-how / ARCHITECT)

This mirrors the proven phase1-why2 -> phase1-what spec-quality re-dispatch (same
agent, SAGE; same failure class).
"""
import pathlib

import pytest
import yaml


def _consensus_node():
    d = yaml.safe_load(pathlib.Path("extension/workflow/definition.yaml").read_text())
    return next(n for n in d["phases"] if n["id"] == "phase3-consensus")


@pytest.mark.unit
def test_why3_fail_routes_to_what_not_how():
    node = _consensus_node()
    why3 = [
        t for t in node["transitions"]
        if "why3-verdict = FAIL" in t.get("condition", "")
    ]
    assert why3, "no transition keyed on 'why3-verdict = FAIL'"
    assert all(t["to"] == "phase1-what" for t in why3), (
        "WHY3 FAIL (spec quality) must re-dispatch CARTOGRAPHER via phase1-what, "
        f"got {[t['to'] for t in why3]}"
    )
    # Bounded re-dispatch: increment + cap, like every other re-dispatch edge.
    assert all(t.get("action") == "increment_iteration" for t in why3)
    assert all("iteration < max_iterations" in t.get("guard", "") for t in why3)


@pytest.mark.unit
def test_assess2_rejected_still_routes_to_how():
    node = _consensus_node()
    assess2 = [
        t for t in node["transitions"]
        if "assess2-verdict = REJECTED" in t.get("condition", "")
    ]
    assert assess2, "no transition keyed on 'assess2-verdict = REJECTED'"
    assert all(t["to"] == "phase3-how" for t in assess2), (
        "ASSESS2 REJECTED (feasibility) must route to phase3-how (ARCHITECT)"
    )


@pytest.mark.unit
def test_no_bare_why3_fail_routes_to_how():
    # THE REGRESSION: the old single transition sent why3 FAIL to phase3-how.
    node = _consensus_node()
    for t in node["transitions"]:
        if t["to"] == "phase3-how":
            assert "why3-verdict = FAIL" not in t.get("condition", ""), (
                "WHY3 FAIL must not route to phase3-how — that is the spec-side "
                "non-convergence loop this guard exists to prevent"
            )


@pytest.mark.unit
def test_iteration_cap_fallback_preserved():
    # The force-convergence escape at the cap must remain.
    node = _consensus_node()
    fallback = [
        t for t in node["transitions"]
        if "iteration >= max_iterations" in t.get("condition", "")
    ]
    assert fallback and all(t.get("action") == "force_convergence_warning" for t in fallback)
