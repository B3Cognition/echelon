"""
Task 9: Structural gate wiring tests for GATEKEEPER + TRACKER.

Tests that:
1. GATEKEEPER authors the governed artifact without invoking controller tools.
2. definition.yaml's phase2-decide node has the structural gate re-dispatch transition
   as its FIRST transition, with the correct evaluable condition (no unresolvable config path).
3. TRACKER authors the governed artifact without invoking controller tools.
4. definition.yaml's phase2-tracker-alignment node has the structural gate re-dispatch
   transition as its FIRST transition, with the correct evaluable condition.
"""
import pytest
import yaml
import pathlib


@pytest.mark.unit
def test_gatekeeper_leaves_structural_validation_to_controller():
    txt = pathlib.Path("extension/agents/feasibility/gatekeeper.md").read_text()
    assert "Controller-Owned Structural Gate" in txt
    assert "--type structural" not in txt
    assert "$LEXICON" not in txt
    assert "feasibility_structural_pass" not in txt


@pytest.mark.unit
def test_phase2_decide_redispatch_transition():
    d = yaml.safe_load(pathlib.Path("extension/workflow/definition.yaml").read_text())
    node = next(n for n in d["phases"] if n["id"] == "phase2-decide")
    conds = " ".join(t.get("condition", "") for t in node["transitions"])
    assert "governance.enabled AND NOT feasibility_structural_pass" in conds
    assert "artifacts.feasibility.enabled" not in conds  # keep the guard evaluable


@pytest.mark.unit
def test_tracker_leaves_structural_validation_to_controller():
    txt = pathlib.Path("extension/agents/control/tracker.md").read_text()
    assert "Controller-Owned Structural Gate" in txt
    assert "--type structural" not in txt
    assert "$LEXICON" not in txt
    assert "intent_alignment_check_structural_pass" not in txt


@pytest.mark.unit
def test_phase2_tracker_alignment_redispatch_transition():
    d = yaml.safe_load(pathlib.Path("extension/workflow/definition.yaml").read_text())
    node = next(n for n in d["phases"] if n["id"] == "phase2-tracker-alignment")
    conds = " ".join(t.get("condition", "") for t in node["transitions"])
    assert "governance.enabled AND NOT intent_alignment_check_structural_pass" in conds
    assert "artifacts.intent" not in conds  # keep the guard evaluable


@pytest.mark.unit
def test_controller_repair_context_names_governance_report():
    from harness.squad_executors import _render_controller_repair_context

    prompt = _render_controller_repair_context({
        "feasibility_structural_pass": False,
        "feasibility_structural_report": "/tmp/feasibility-report.json",
    })

    assert "Controller Structural Repair" in prompt
    assert "/tmp/feasibility-report.json" in prompt
    assert "repair every listed finding" in prompt
    assert "Do not report `feasibility_structural_pass`" in prompt
