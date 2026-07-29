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
def test_phase2_decide_routes_only_to_structural_node():
    d = yaml.safe_load(pathlib.Path("extension/workflow/definition.yaml").read_text())
    node = next(n for n in d["phases"] if n["id"] == "phase2-decide")
    assert node["transitions"] == [
        {"to": "phase2-feasibility-structural", "condition": "always"}
    ]
    gate = next(
        n for n in d["phases"] if n["id"] == "phase2-feasibility-structural"
    )
    assert gate.get("agent") is None
    assert gate["structural_artifact"] == "feasibility"


@pytest.mark.unit
def test_tracker_leaves_structural_validation_to_controller():
    txt = pathlib.Path("extension/agents/control/tracker.md").read_text()
    assert "Controller-Owned Structural Gate" in txt
    assert "--type structural" not in txt
    assert "$LEXICON" not in txt
    assert "intent_alignment_check_structural_pass" not in txt


@pytest.mark.unit
def test_phase2_tracker_alignment_routes_only_to_structural_node():
    d = yaml.safe_load(pathlib.Path("extension/workflow/definition.yaml").read_text())
    node = next(n for n in d["phases"] if n["id"] == "phase2-tracker-alignment")
    assert node["transitions"] == [
        {
            "to": "phase2-intent-alignment-structural",
            "condition": "always",
        }
    ]
    gate = next(
        n
        for n in d["phases"]
        if n["id"] == "phase2-intent-alignment-structural"
    )
    assert gate.get("agent") is None
    assert gate["structural_artifact"] == "intent-alignment-check"


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


@pytest.mark.unit
def test_quality_remediation_context_requires_an_actual_spec_edit(tmp_path):
    from harness.squad_executors import _render_controller_repair_context

    report = tmp_path / "understanding.json"
    report.write_text(
        '{"gates": {"structure": {"pass": false, "score": 0.5, "threshold": 0.75}}}',
        encoding="utf-8",
    )

    prompt = _render_controller_repair_context({
        "quality_gate_remediation": {
            "evidence": {"path": str(report)},
        },
        "issue_resolution_ledger": {
            "ISS-042": {"status": "validated"},
            "ISS-099": {"status": "open"},
        },
    })

    assert "structure (0.5 < required 0.75)" in prompt
    assert "Edit `spec.md`" in prompt
    assert "SHA-256" in prompt
    assert "OVERRIDES any stale `issues.md`" in prompt
    assert "`ISS-042`" in prompt
    assert "ISS-006" not in prompt
    assert "Do NOT invoke any `echelon spec resolve`" in prompt


@pytest.mark.unit
def test_issue_resolution_context_keeps_repaired_issue_available_for_retry():
    from harness.squad_executors import _render_issue_resolution_context

    prompt = _render_issue_resolution_context({
        "selected_issue_resolution": "ISS-001",
        "issue_resolution_ledger": {
            "ISS-001": {
                "status": "repaired",
                "title": "Retry policy",
                "guidance": "Choose retry behavior.",
                "decision": "Use exponential backoff.",
            }
        },
    })

    assert "ISS-001" in prompt
    assert "Use exponential backoff." in prompt
    assert "targeted validation" in prompt
    assert "OMIT this issue from `finding_routes`" in prompt
