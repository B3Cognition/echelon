"""The managed adapter selects captured inputs; native governance owns policy."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.unit.test_captured_governance_gate import FEASIBILITY, TEMPLATE
from tests.unit.test_governance_structural_gate import _governance


def evaluate(text=FEASIBILITY, **changes):
    from harness.discovery_assessment_gate import evaluate_feasibility_gate
    sources = SimpleNamespace(trees=(SimpleNamespace(path="specs/game", exists=True,
        files=(SimpleNamespace(path="specs/game/feasibility.md", content=text.encode()),)),),
        files=(SimpleNamespace(path=".echelon/runtime/templates/feasibility-template.md", content=TEMPLATE.encode()),))
    return evaluate_feasibility_gate(**{**dict(sources=sources, root=Path("/project"),
        spec_path="specs/game", config=_governance(), previous_attempts=0,
        iteration=0, max_iterations=5), **changes})


@pytest.mark.parametrize("valid,action,attempts", [(True, "proceed", 0), (False, "repair", 1)])
def test_adapter_uses_only_captured_inputs(valid, action, attempts, monkeypatch):
    import harness.discovery_completion  # Load bundled schemas before forbidding input I/O.
    import lexicon.structural
    def forbidden(*args, **kwargs):
        pytest.fail("Managed adapter must not read or write live input")
    with monkeypatch.context() as patch:
        for method in ("read_text", "read_bytes", "write_text", "write_bytes", "resolve", "is_file"):
            patch.setattr(Path, method, forbidden)
        result, report = evaluate(FEASIBILITY if valid else "# Incomplete\n")
    assert result.action == action and result.attempts == attempts
    assert report["ok"] is valid


@pytest.mark.parametrize("key,value", [("path", "elsewhere.md"), ("report", "spec.md"),
    ("template", "../outside.md"), ("template", "other-template.md")])
def test_unadmitted_selections_do_not_gain_authority(key, value):
    config = deepcopy(_governance())
    config["governance"]["artifacts"]["feasibility"][key] = value
    with pytest.raises(ValueError):
        evaluate(config=config)


@pytest.mark.parametrize("action,want", [("repair", "phase2-decide"), ("block", "terminal-blocked"),
    ("proceed", "phase2-strategic-overview"), ("proceed_with_warning", "phase2-strategic-overview")])
def test_gate_routes_using_native_transitions(action, want):
    from harness.discovery_assessment_gate import feasibility_gate_route
    assert feasibility_gate_route(dict(iteration=0, max_iterations=5, feasibility_verdict="PASS"),
        {"structural_action": action}) == want


@pytest.mark.parametrize("value", [True, -1, "0", 0.5])
def test_adapter_does_not_normalize_forged_counters(value):
    with pytest.raises(ValueError):
        evaluate(previous_attempts=value)


def test_literal_transition_contract_matches_native_graph():
    import yaml
    from harness.discovery_assessment_gate import FEASIBILITY_GATE_TRANSITIONS
    definition = Path(__file__).parents[2] / "runtime/workflow/definition.yaml"
    data = yaml.safe_load(definition.read_text())
    nodes = data["phases"]
    gate = next(node for node in nodes if node["id"] == "phase2-feasibility-structural")
    assert tuple(gate["transitions"]) == FEASIBILITY_GATE_TRANSITIONS


@pytest.mark.parametrize("verdict", ["KILL", "DEFER", "FAIL"])
def test_unfinished_terminal_corridors_remain_closed(verdict):
    from harness.discovery_assessment_gate import feasibility_gate_route
    with pytest.raises(ValueError):
        feasibility_gate_route(dict(iteration=0, max_iterations=5, feasibility_verdict=verdict),
            {"structural_action": "proceed"})


@pytest.mark.parametrize("enabled,cap,policy,action,route,attempts", [
    (True, 3, "block", "repair", "phase2-decide", 1),
    (True, 1, "block", "block", "terminal-blocked", 1),
    (True, 1, "warn", "proceed_with_warning", "phase2-strategic-overview", 1),
    (False, 1, "block", "proceed", "phase2-strategic-overview", 0),
])
def test_native_policy_is_not_replaced_by_adapter(enabled, cap, policy, action, route, attempts):
    from harness.discovery_assessment_gate import feasibility_gate_route, _result
    gate, report = evaluate(
        "# Incomplete\n", config=_governance(enabled=enabled, max_repair_attempts=cap, on_exhausted=policy))
    assert gate.action == action and gate.attempts == attempts
    assert (report is not None) is enabled
    result = _result(gate)
    assert result["verdict"] == {"repair": "REPAIR", "block": "FAIL", "proceed_with_warning": "WARN", "proceed": "PASS"}[action]
    assert feasibility_gate_route(dict(iteration=0, max_iterations=5, feasibility_verdict="PASS"), result["state_updates"]) == route


def test_absent_template_cannot_certify_or_charge_attempt():
    sources = SimpleNamespace(trees=(SimpleNamespace(path="specs/game", exists=True,
        files=(SimpleNamespace(path="specs/game/feasibility.md", content=FEASIBILITY.encode()),)),), files=())
    gate, report = evaluate(sources=sources)
    assert gate.action == "block" and report is None
    assert gate.attempts == 0 and gate.blocked_reason == "governance_structural_capture_invalid"


@pytest.mark.parametrize("damage", ["counter", "cancelled", "phase", "pending"])
def test_gate_preparation_refuses_invalid_state_before_source_access(damage):
    from harness.discovery_assessment_gate import prepare_feasibility_gate_publication
    state = dict(phase="phase2-feasibility-structural", status="running", max_iterations=5)
    if damage == "counter": state["feasibility_structural_attempts"] = -1
    elif damage == "cancelled": state["cancel_requested"] = True
    elif damage == "phase": state["phase"] = "phase2-decide"
    else: state["pending_controller_completion"] = {}
    store = SimpleNamespace(squad_dir=Path("/absent/runs/first"), load=lambda: state)
    with pytest.raises(ValueError):
        prepare_feasibility_gate_publication(Path("/absent"), store, completion_id="a" * 32, max_iterations=5)
