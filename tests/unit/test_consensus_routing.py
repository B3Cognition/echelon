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
from unittest.mock import MagicMock

import pytest
import yaml

from harness.phase_graph import PhaseGraph
from harness.squad import SquadController
from harness.squad_provider import SquadAgentResult
from harness.squad_state import SquadStateStore


ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFINITION = ROOT / "extension/workflow/definition.yaml"
EXT_YML = ROOT / "extension/extension.yml"


def _consensus_node():
    d = yaml.safe_load(DEFINITION.read_text())
    return next(n for n in d["phases"] if n["id"] == "phase3-consensus")


def _runtime_route(tmp_path, state_updates, *, iteration=0):
    graph = PhaseGraph(DEFINITION, EXT_YML)
    store = SquadStateStore(tmp_path / "squad" / "run-test")
    store.initialize("r", "semi", "msg", 0, "phase3-consensus", max_iterations=5)
    state = store.load()
    state["iteration"] = iteration
    state.update(state_updates)
    store.save(state)

    ctrl = SquadController(
        provider=MagicMock(),
        state_store=store,
        phase_graph=graph,
        ext_dir=ROOT / "extension",
        project_root=tmp_path,
        token_budget=0,
        squad_dir=store.squad_dir,
    )
    result = SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": "DONE", "state_updates": {}},
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    return ctrl._evaluate_transitions(graph.get("phase3-consensus"), result)


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
    assert all("iteration < max_iterations" in t.get("condition", "") for t in why3)


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


@pytest.mark.unit
def test_runtime_why3_fail_routes_to_what_before_cap(tmp_path):
    assert _runtime_route(
        tmp_path,
        {"why3_verdict": "FAIL", "assess2_verdict": "PASS"},
        iteration=4,
    ) == "phase1-what"


@pytest.mark.unit
def test_runtime_assess2_rejected_routes_to_how_before_cap(tmp_path):
    assert _runtime_route(
        tmp_path,
        {"why3_verdict": "PASS", "assess2_verdict": "REJECTED"},
        iteration=4,
    ) == "phase3-how"


@pytest.mark.unit
@pytest.mark.parametrize(
    "state_updates",
    [
        {"why3_verdict": "FAIL", "assess2_verdict": "PASS"},
        {"why3_verdict": "PASS", "assess2_verdict": "REJECTED"},
        {"why3_verdict": "FAIL", "assess2_verdict": "REJECTED"},
    ],
)
def test_runtime_consensus_failure_uses_fallback_at_iteration_cap(
    tmp_path,
    state_updates,
):
    assert _runtime_route(tmp_path, state_updates, iteration=5) == "checkpoint-plan"
