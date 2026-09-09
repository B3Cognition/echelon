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
import pathlib
import json
from types import SimpleNamespace

import pytest
import yaml


@pytest.mark.unit
def test_gatekeeper_leaves_structural_validation_to_controller():
    txt = pathlib.Path("prosaic/subagents/echelon.gatekeeper.md").read_text()
    assert "Controller-Owned Structural Gate" in txt
    assert "--type structural" not in txt
    assert "$LEXICON" not in txt
    assert "feasibility_structural_pass" not in txt


@pytest.mark.unit
def test_phase2_decide_routes_only_to_structural_node():
    d = yaml.safe_load(pathlib.Path("runtime/workflow/definition.yaml").read_text())
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
    txt = pathlib.Path("prosaic/subagents/echelon.tracker.md").read_text()
    assert "Controller-Owned Structural Gate" in txt
    assert "--type structural" not in txt
    assert "$LEXICON" not in txt
    assert "intent_alignment_check_structural_pass" not in txt


@pytest.mark.unit
def test_phase2_tracker_alignment_routes_only_to_structural_node():
    d = yaml.safe_load(pathlib.Path("runtime/workflow/definition.yaml").read_text())
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
def test_controller_repair_context_names_invalid_coverage_finding():
    from harness.squad_executors import _render_controller_repair_context

    prompt = _render_controller_repair_context({
        "phase_output_recovery": {
            "phase": "phase3-sentinel",
            "invalid_outputs": [{
                "path": "coverage-map.md",
                "reason": "coverage test type/case cardinality must match",
            }],
            "prior_state_updates": {},
        },
    })

    assert "Phase Output Repair" in prompt
    assert "coverage-map.md: coverage test type/case cardinality must match" in prompt
    assert "repair only the named artifacts" in prompt
    assert "Do not repeat external retrieval or discard established evidence" in prompt
    assert "source frontier" not in prompt  # investigation-only recovery must not leak into SENTINEL


@pytest.mark.unit
def test_sentinel_output_validation_rejects_invalid_coverage_contract(tmp_path):
    from harness.squad_executors import AgentExecutor

    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("- **FR-001**: Animate collection.\n")
    (spec_dir / "coverage-map.md").write_text(
        "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
        "|---|---|---|---|---|---|---|\n"
        "| FR-001 | UT-001; E2E-001/E2E-002 | unit/e2e | planned | planned | tests | implement |\n"
    )
    executor = object.__new__(AgentExecutor)
    executor._project_root = tmp_path

    invalid = executor._required_phase_outputs_invalid(
        SimpleNamespace(id="phase3-sentinel"),
        {"spec_dir": "specs/001-demo"},
    )

    assert invalid == [{
        "path": "coverage-map.md",
        "reason": "line 3 (FR-001): coverage test type/case cardinality must be one or match case count. "
                  "Use one test case and its test type per row, repeating the requirement ID as needed.",
    }]


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
def test_why_journal_context_honors_phase_type_filter_and_byte_bound(tmp_path):
    from harness.squad_executors import _render_context_candidate

    journal = tmp_path / "reasoning-journal.jsonl"
    retained = {
        "type": "decision",
        "phase": "phase1-what",
        "data": {"detail": "keep"},
    }
    excluded = {
        "type": "challenge",
        "phase": "phase1-why2",
        "data": {"detail": "exclude"},
    }
    oversized = {
        "type": "decision",
        "phase": "phase1-what",
        "data": {"detail": "x" * 30_000},
    }
    journal.write_text(
        "\n".join(json.dumps(item) for item in (retained, excluded, oversized)),
        encoding="utf-8",
    )

    rendered = _render_context_candidate(
        "reasoning-journal.jsonl [type=routing_decision, phase=phase1-what]",
        journal,
        filters={"type": "routing_decision", "phase": "phase1-what"},
    )

    assert '"detail": "keep"' in rendered
    assert "exclude" not in rendered
    assert len(rendered.encode("utf-8")) < 25_000


@pytest.mark.unit
def test_why_state_context_excludes_large_historical_payloads():
    from harness.squad_executors import _render_why_state_context

    rendered = _render_why_state_context(
        {
            "run_id": "run-1",
            "phase": "phase1-why2",
            "iteration": 2,
            "issue_resolution_ledger": {
                "ISS-001": {"status": "validated", "guidance": "large" * 1000},
            },
            "published_re_context": {"artifacts": "large" * 10_000},
            "product_input_mapping_repair": {"details": "large" * 10_000},
        }
    )

    assert "run-1" in rendered
    assert "ISS-001" in rendered
    assert "published_re_context" not in rendered
    assert "product_input_mapping_repair" not in rendered


@pytest.mark.unit
def test_issue_resolution_context_keeps_repaired_issue_available_for_retry():
    from harness.squad_executors import _render_issue_resolution_context

    prompt = _render_issue_resolution_context({
        "selected_issue_resolution": "ISS-001",
        "issue_resolution_ledger": {
            "ISS-001": {
                "status": "repaired",
                "title": "Stale mental model",
                "guidance": "Reconcile mental-model.md with resolved evidence.",
                "decision": "Record the shared-seed lifecycle in mental-model.md.",
            }
        },
    })

    assert "ISS-001" in prompt
    assert "Record the shared-seed lifecycle in mental-model.md." in prompt
    assert "Amend spec.md only when the named repair requires" in prompt
    assert "current affected artifacts implement that decision" in prompt
    assert "targeted validation" in prompt
    assert "OMIT this issue from `finding_routes`" in prompt
