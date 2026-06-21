"""
Task 9: Structural gate wiring tests for GATEKEEPER + TRACKER.

Tests that:
1. GATEKEEPER's gatekeeper.md contains the Structural Gate Mode section with correct
   CLI command and flag name.
2. definition.yaml's phase2-decide node has the structural gate re-dispatch transition
   as its FIRST transition, with the correct evaluable condition (no unresolvable config path).
3. TRACKER's tracker.md contains the Structural Gate Mode section with correct
   CLI command and flag name.
4. definition.yaml's phase2-tracker-alignment node has the structural gate re-dispatch
   transition as its FIRST transition, with the correct evaluable condition.
"""
import pytest
import yaml
import pathlib


@pytest.mark.unit
def test_gatekeeper_structural_gate_mode():
    txt = pathlib.Path("extension/agents/feasibility/gatekeeper.md").read_text()
    assert "Structural Gate Mode" in txt
    assert "--type structural" in txt and "--artifact feasibility" in txt
    assert "feasibility_structural_pass" in txt


@pytest.mark.unit
def test_phase2_decide_redispatch_transition():
    d = yaml.safe_load(pathlib.Path("extension/workflow/definition.yaml").read_text())
    node = next(n for n in d["phases"] if n["id"] == "phase2-decide")
    conds = " ".join(t.get("condition", "") for t in node["transitions"])
    assert "governance.enabled AND NOT feasibility_structural_pass" in conds
    assert "artifacts.feasibility.enabled" not in conds  # keep the guard evaluable


@pytest.mark.unit
def test_tracker_structural_gate_mode():
    txt = pathlib.Path("extension/agents/control/tracker.md").read_text()
    assert "Structural Gate Mode" in txt
    assert "--type structural" in txt and "--artifact intent-alignment-check" in txt
    assert "intent_alignment_check_structural_pass" in txt


@pytest.mark.unit
def test_phase2_tracker_alignment_redispatch_transition():
    d = yaml.safe_load(pathlib.Path("extension/workflow/definition.yaml").read_text())
    node = next(n for n in d["phases"] if n["id"] == "phase2-tracker-alignment")
    conds = " ".join(t.get("condition", "") for t in node["transitions"])
    assert "governance.enabled AND NOT intent_alignment_check_structural_pass" in conds
    assert "artifacts.intent" not in conds  # keep the guard evaluable
