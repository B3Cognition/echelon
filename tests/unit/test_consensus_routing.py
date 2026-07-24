"""Post-consensus deterministic Tasks Lexicon routing (definition.yaml).

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
    return next(
        n
        for n in d["phases"]
        if n["id"] == "phase3-consensus-tasks-lexicon"
    )


def _runtime_route(tmp_path, state_updates, *, iteration=0):
    config_path = tmp_path / ".echelon" / "config.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("lexicon_gate:\n  enabled: false\n", encoding="utf-8")
    graph = PhaseGraph(DEFINITION, EXT_YML)
    store = SquadStateStore(tmp_path / "squad" / "run-test")
    store.initialize("r", "semi", "msg", 0, "phase3-consensus", max_iterations=5)
    state = store.load()
    state["iteration"] = iteration
    state["quality_scores"] = [{"pass": True, "source": "harness:understanding"}]
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
    consensus_result = SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": "DONE", "state_updates": {}},
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    consensus = graph.get("phase3-consensus")
    snapshot = store.capture_routing_snapshot(
        expected_phase="phase3-consensus",
    )
    consensus_prepared = ctrl._prepare_phase_result(
        consensus,
        consensus_result,
        snapshot,
    )
    assert (
        ctrl._evaluate_transitions(consensus, consensus_prepared, snapshot)
        == "phase3-consensus-tasks-lexicon"
    )
    gate = graph.get("phase3-consensus-tasks-lexicon")
    gate_result = ctrl._executors["deterministic_lexicon"].execute(gate, store)
    gate_prepared = ctrl._prepare_phase_result(gate, gate_result, snapshot)
    return ctrl._evaluate_transitions(gate, gate_prepared, snapshot)


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
def test_certified_metric_failure_precedes_consensus_success_and_risk_acceptance():
    transitions = _consensus_node()["transitions"]
    quality_failure = next(
        index
        for index, transition in enumerate(transitions)
        if "quality_gates.fail" in transition.get("condition", "")
    )
    success = next(
        index
        for index, transition in enumerate(transitions)
        if "why3-verdict = PASS" in transition.get("condition", "")
    )
    accept_risk = next(
        index
        for index, transition in enumerate(transitions)
        if "accept_with_risk" in transition.get("condition", "")
    )
    qualitative_failure = next(
        index
        for index, transition in enumerate(transitions)
        if "why3-verdict = FAIL" in transition.get("condition", "")
    )

    assert quality_failure < qualitative_failure < success < accept_risk


@pytest.mark.unit
def test_legacy_consensus_resume_redirects_to_deterministic_gate(tmp_path):
    graph = PhaseGraph(DEFINITION, EXT_YML)
    store = SquadStateStore(tmp_path / "squad" / "run-test")
    store.initialize("r", "semi", "msg", 0, "phase3-consensus", max_iterations=5)
    ctrl = SquadController(
        provider=MagicMock(),
        state_store=store,
        phase_graph=graph,
        ext_dir=ROOT / "extension",
        project_root=tmp_path,
        token_budget=0,
        squad_dir=store.squad_dir,
    )

    assert ctrl._guard_understanding_evidence("phase3-consensus") == "phase3-understanding"
    assert store.current_phase() == "phase3-understanding"


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
def test_runtime_certified_metric_failure_routes_to_spec_repair_before_success(
    tmp_path,
):
    assert _runtime_route(
        tmp_path,
        {
            "why3_verdict": "PASS",
            "assess2_verdict": "PASS",
            "quality_scores": [
                {"pass": False, "source": "harness:understanding"}
            ],
        },
        iteration=4,
    ) == "phase1-what"


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
