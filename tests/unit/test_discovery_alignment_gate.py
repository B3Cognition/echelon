"""Alignment uses captured evidence and the existing native structural policy."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.unit.test_governance_structural_gate import _governance
from tests.unit.test_structural_validate import SPEC


TEXT = "## Alignment Verdict\nVerdict: ALIGNED\n"


def evaluate(text=TEXT, **changes):
    from harness import discovery_assessment_gate as module
    function = getattr(module, "evaluate_alignment_gate", None)
    assert callable(function), "Alignment requires its captured structural adapter"
    sources = SimpleNamespace(trees=(SimpleNamespace(path="specs/game", exists=True,
        files=(SimpleNamespace(path="specs/game/intent-alignment-check.md", content=text.encode()),
            SimpleNamespace(path="specs/game/spec.md", content=SPEC.encode()))),),
        files=(SimpleNamespace(path=".echelon/runtime/templates/intent-alignment-check-template.md",
            content=b"## Alignment Verdict\n"),))
    return function(**{**dict(sources=sources, root=Path("/project"), spec_path="specs/game",
        config=_governance(), previous_attempts=0, iteration=0, max_iterations=5), **changes})


@pytest.mark.parametrize("text,enabled,cap,policy,action,attempts", [
    (TEXT, True, 3, "block", "proceed", 0),
    ("# Incomplete\n", True, 3, "block", "repair", 1),
    ("# Incomplete\n", True, 1, "block", "block", 1),
    ("# Incomplete\n", True, 1, "warn", "proceed_with_warning", 1),
    ("# Incomplete\n", False, 1, "block", "proceed", 0),
])
def test_captured_alignment_preserves_native_policy_without_io(text, enabled, cap, policy, action, attempts, monkeypatch):
    import harness.discovery_completion
    import lexicon.structural
    from lexicon import parser
    read_text = Path.read_text
    def bundled_only(path, *args, **kwargs):
        if path != parser._GRAMMAR_PATH:
            forbidden()
        return read_text(path, *args, **kwargs)
    def forbidden(*args, **kwargs):
        pytest.fail("Alignment adapter must not read or write live inputs")
    with monkeypatch.context() as patch:
        for method in ("read_text", "read_bytes", "write_text", "write_bytes", "resolve", "is_file"):
            patch.setattr(Path, method, forbidden)
        patch.setattr(Path, "read_text", bundled_only)
        gate, report = evaluate(text, config=_governance(enabled=enabled,
            max_repair_attempts=cap, on_exhausted=policy))
    assert gate.action == action and gate.attempts == attempts
    assert (report is not None) is enabled
    assert gate.state_updates()["intent_alignment_check_structural_attempts"] == attempts


@pytest.mark.parametrize("key,value", [("path", "spec.md"), ("report", "spec.md"),
    ("template", "../other.md"), ("template", "other-template.md")])
def test_alignment_cannot_redirect_captured_paths(key, value):
    config = deepcopy(_governance())
    config["governance"]["artifacts"]["intent-alignment-check"][key] = value
    with pytest.raises(ValueError): evaluate(config=config)


@pytest.mark.parametrize("value", [True, -1, "0", 0.5])
def test_alignment_adapter_refuses_forged_budget(value):
    with pytest.raises(ValueError): evaluate(previous_attempts=value)


@pytest.mark.parametrize("verdict", ["ALIGNED", "DRIFT"])
@pytest.mark.parametrize("action,want", [("repair", "phase2-tracker-alignment"),
    ("block", "terminal-blocked"), ("proceed", "phase3-specialists"),
    ("proceed_with_warning", "phase3-specialists")])
def test_alignment_gate_routes_without_executing_successor(verdict, action, want):
    from harness import discovery_assessment_gate as module
    function = getattr(module, "alignment_gate_route", None)
    assert callable(function), "Alignment requires exact native structural routing"
    assert function(dict(iteration=0, max_iterations=5, intent_alignment_verdict=verdict),
        {"structural_action": action}) == want


@pytest.mark.parametrize("verdict", ["STOP_AND_ASK", "PASS", None])
def test_question_cannot_enter_ordinary_alignment_gate(verdict):
    from harness.discovery_assessment_gate import alignment_gate_route
    with pytest.raises(ValueError):
        alignment_gate_route(dict(iteration=0, max_iterations=5, intent_alignment_verdict=verdict),
            {"structural_action": "proceed"})


def test_alignment_capture_checks_references_without_live_lookup():
    result, report = evaluate(TEXT + "Requirement FR-999 must remain.\n")
    assert result.action == "repair" and result.attempts == 1
    assert [row["code"] for row in report["findings"]] == ["unresolved-ref"]


def test_alignment_missing_template_blocks_without_charging_attempt():
    sources = SimpleNamespace(trees=(SimpleNamespace(path="specs/game", exists=True,
        files=(SimpleNamespace(path="specs/game/intent-alignment-check.md", content=TEXT.encode()),)),), files=())
    result, report = evaluate(sources=sources)
    assert result.action == "block" and result.attempts == 0 and report is None
    assert result.blocked_reason == "governance_structural_capture_invalid"


def test_alignment_transition_contract_matches_native_graph():
    import yaml
    from harness.discovery_assessment_gate import ALIGNMENT_GATE_TRANSITIONS
    nodes = yaml.safe_load((Path(__file__).parents[2] / "runtime/workflow/definition.yaml").read_text())["phases"]
    node = next(node for node in nodes if node["id"] == "phase2-intent-alignment-structural")
    assert tuple(node["transitions"]) == ALIGNMENT_GATE_TRANSITIONS


@pytest.mark.parametrize("damage", ["counter", "cancelled", "phase", "pending"])
def test_alignment_gate_refuses_invalid_state_before_reading_sources(damage):
    from harness.discovery_assessment_gate import prepare_alignment_gate_publication
    state = dict(phase="phase2-intent-alignment-structural", status="running", max_iterations=5)
    if damage == "counter": state["intent_alignment_check_structural_attempts"] = -1
    elif damage == "cancelled": state["cancel_requested"] = True
    elif damage == "phase": state["phase"] = "phase2-tracker-alignment"
    else: state["_spec_step_effect_plan"] = {}
    store = SimpleNamespace(squad_dir=Path("/absent/runs/first"), load=lambda: state)
    with pytest.raises(ValueError):
        prepare_alignment_gate_publication(Path("/absent"), store, completion_id="9" * 32, max_iterations=5)
