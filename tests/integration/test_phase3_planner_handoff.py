"""Standalone PLAN must reach review before another dependency asks a human."""
from dataclasses import asdict
from unittest.mock import MagicMock

import pytest

from harness.phase3_repair import RepairIdentity
from harness.squad_provider import SquadAgentResult
from tests.integration.test_squad_controller import _controller, _mark_constitution_complete, _disable_lexicon_gate


def planner_fixture(tmp_path, *, mode="banzai"):
    controller, store = _controller(tmp_path)
    _disable_lexicon_gate(tmp_path)
    store.initialize("r", "greenfield", "task", 0, "phase3-plan", autonomy_mode=mode)
    _mark_constitution_complete(tmp_path, store)
    spec = tmp_path / "specs/008-test"
    (spec / "contracts").mkdir(parents=True, exist_ok=True)
    for name, text in {
        "spec.md": "FR-001: Preserve acceptance strength.",
        "contracts/api.md": "A implemented; B observation protocol still missing.",
        "tasks.md": "T-001 waits for B; no task is declared executable.",
        "critical-path.md": "B precedes implementation.",
        "risk-matrix.md": "B remains open.",
        "dependencies.md": "B requires architecture-owned work.",
        "issues.md": "### ISS-B: Observation missing\n- **Responsible agent:** ARCHITECT\n- **Banzai eligible:** no\n",
    }.items():
        (spec / name).write_text(text)
    state = store.load()
    state.update(spec_dir=str(spec), status="running", iteration=12, max_iterations=14,
        why3_verdict="FAIL", selected_issue_resolution="ISS-A",
        issue_resolution_ledger={"ISS-A": {
            "title": "Previously assigned repair", "status": "repaired",
            "repair_phase": "phase3-how", "submission_count": 1,
            "repair_identity": asdict(RepairIdentity("r", "a" * 64, 7)),
        }}, issue_resolution_repair_baseline={"issue_id": "ISS-A", "repair_phase": "phase3-how"})
    store.save(state)
    return controller, store


def blocked_plan(explicit=True):
    return SquadAgentResult(exit_code=0, raw_output="", duration_ms=0, timed_out=False,
        echelon_result={"verdict": "BLOCKED", "journal_entries": [],
            "state_updates": {"blocked_reason": "ISS-B requires its producer-owned contract"} if explicit else {},
            "phase3_blocker": {"issue_id": "ISS-B", "owner_phase": "phase3-how",
                "detail": "Observation contract missing", "next_action": "Design the missing protocol"}})


@pytest.mark.parametrize("explicit", [False, True])
def test_standalone_plan_block_enters_consensus_not_human_clarification(tmp_path, explicit):
    controller, store = planner_fixture(tmp_path)
    # The external phase returns the exact shape from the demo. Consensus is
    # interrupted at its boundary so this test isolates the main-loop routing.
    agent = MagicMock()
    agent.execute.return_value = blocked_plan(explicit)
    controller._executors["agent"] = agent
    consensus = MagicMock()
    consensus.execute.return_value = SquadAgentResult(exit_code=1, raw_output="review interrupted",
        duration_ms=0, timed_out=True, echelon_result=None)
    controller._executors["staged_parallel"] = consensus
    result = controller.run("task", mode="banzai")
    state = store.load()
    assert result.status == "blocked"
    assert state["phase_dispatch_counts"]["phase3-consensus"] == 1
    assert state["recovery_instruction"]["phase"] == "phase3-consensus"
    assert state["blocked_reason"] == "agent_timeout"
    assert not state.get("blocked_decision")
    assert state["selected_issue_resolution"] == "ISS-A"
    assert state["issue_resolution_ledger"]["ISS-A"]["status"] == "repaired"
    assert state["iteration"] == 12 and state["max_iterations"] == 14
    assert state["why3_verdict"] == "FAIL"
    assert state["phase3_last_blocker"]["issue_id"] == "ISS-B"


def test_planner_handoff_survives_restart_and_cannot_repeat_unchanged(tmp_path):
    controller, store = planner_fixture(tmp_path)
    node = controller._graph.get("phase3-plan")
    before = store.load()
    snapshot = store.capture_routing_snapshot()
    prepared = controller._prepare_phase_result(node, blocked_plan(), snapshot)
    route = controller._construct_routing_decision_or_block(node, prepared, snapshot)
    assert route.decision.to_phase == "phase3-consensus"
    assert controller._advance_prepared_result_or_block(node, route.decision)
    state = store.load()
    assert state["issue_resolution_ledger"] == before["issue_resolution_ledger"]
    assert "phase3-plan" not in state["completed_phases"]
    assert state["status"] == "running" and state.get("blocked_reason") is None
    state["phase"] = "phase3-plan"
    store.save(state)
    controller, store = _controller(tmp_path, squad_dir=store.squad_dir)
    snapshot = store.capture_routing_snapshot()
    prepared = controller._prepare_phase_result(node, blocked_plan(), snapshot)
    route = controller._construct_routing_decision_or_block(node, prepared, snapshot)
    assert route.decision.to_phase == "terminal-blocked"
    assert controller._advance_prepared_result_or_block(node, route.decision)
    assert store.load()["blocked_reason"] == "repair_no_progress"


@pytest.mark.parametrize("change", ["semi", "guided", "no_selection", "not_submitted", "not_submitted_missing_inputs", "already_validated", "exit_failure", "timeout", "provider_limit", "success"])
def test_planner_handoff_does_not_override_unrelated_paths(tmp_path, change):
    controller, store = planner_fixture(tmp_path)
    state = store.load()
    result = blocked_plan()
    if change in {"semi", "guided"}:
        state["autonomy_mode"] = change
    elif change == "no_selection":
        state["selected_issue_resolution"] = None
    elif change in {"not_submitted", "not_submitted_missing_inputs"}:
        state["issue_resolution_ledger"]["ISS-A"]["status"] = "selected"
        if change == "not_submitted_missing_inputs":
            state["spec_dir"] = str(tmp_path / "not-yet-written")
    elif change == "already_validated":
        state["issue_resolution_ledger"]["ISS-A"]["status"] = "validated"
    elif change == "exit_failure":
        result.exit_code = 1
    elif change == "timeout":
        result.timed_out = True
    elif change == "provider_limit":
        result.provider_limit_message = "provider session exhausted"
    elif change == "success":
        result.echelon_result["verdict"] = "DONE"
        result.echelon_result["state_updates"] = {}
    store.save(state)
    before = store.load()
    node = controller._graph.get("phase3-plan")
    snapshot = store.capture_routing_snapshot()
    prepared = controller._prepare_phase_result(node, result, snapshot)
    assert controller._phase3_planner_block_routing(node, prepared, snapshot) == (None, {})
    assert store.load() == before


def test_explicit_planner_blocked_status_is_cleared_only_by_review_handoff(tmp_path):
    controller, store = planner_fixture(tmp_path)
    node = controller._graph.get("phase3-plan")
    result = blocked_plan()
    result.echelon_result["state_updates"]["status"] = "blocked"
    snapshot = store.capture_routing_snapshot()
    prepared = controller._prepare_phase_result(node, result, snapshot)
    route = controller._construct_routing_decision_or_block(node, prepared, snapshot)
    assert controller._advance_prepared_result_or_block(node, route.decision)
    assert store.load()["phase"] == "phase3-consensus"
    assert store.load()["status"] == "running"
    assert store.load()["blocked_reason"] is None


def test_planner_cannot_select_an_owner_or_reset_budget_at_the_review_boundary(tmp_path):
    controller, store = planner_fixture(tmp_path)
    state = store.load()
    state["iteration"] = 14
    store.save(state)
    result = blocked_plan()
    result.echelon_result["phase3_blocker"]["owner_phase"] = "phase4-document"
    node = controller._graph.get("phase3-plan")
    snapshot = store.capture_routing_snapshot()
    prepared = controller._prepare_phase_result(node, result, snapshot)
    route = controller._construct_routing_decision_or_block(node, prepared, snapshot)
    assert route.decision.to_phase == "phase3-consensus"
    assert controller._advance_prepared_result_or_block(node, route.decision)
    current = store.load()
    assert current["iteration"] == current["max_iterations"] == 14
    assert current["selected_issue_resolution"] == "ISS-A"
    assert current["issue_resolution_ledger"]["ISS-A"]["repair_phase"] == "phase3-how"


def test_stale_planner_diagnostic_is_not_replayed_as_current_review_context(tmp_path):
    from harness.phase3_repair_context import planner_handoff_context, capture_review_inputs
    controller, store = planner_fixture(tmp_path)
    node = controller._graph.get("phase3-plan")
    snapshot = store.capture_routing_snapshot()
    prepared = controller._prepare_phase_result(node, blocked_plan(), snapshot)
    route = controller._construct_routing_decision_or_block(node, prepared, snapshot)
    assert controller._advance_prepared_result_or_block(node, route.decision)
    state = store.load()
    from pathlib import Path
    manifest, _ = capture_review_inputs(Path(state["spec_dir"]), project_root=tmp_path)
    assert "Observation contract missing" in planner_handoff_context(state, manifest)
    assert planner_handoff_context(state, {**manifest, "spec.md": "0" * 64}) == ""


@pytest.mark.parametrize("identity", [None, {"run_id": "other", "issue_fingerprint": "a" * 64, "selection_revision": 7}])
def test_missing_or_foreign_repair_identity_fails_closed(tmp_path, identity):
    controller, store = planner_fixture(tmp_path)
    state = store.load()
    state["issue_resolution_ledger"]["ISS-A"]["repair_identity"] = identity
    store.save(state)
    node = controller._graph.get("phase3-plan")
    snapshot = store.capture_routing_snapshot()
    prepared = controller._prepare_phase_result(node, blocked_plan(), snapshot)
    route = controller._construct_routing_decision_or_block(node, prepared, snapshot)
    assert route.decision.to_phase == "terminal-blocked"
    assert controller._advance_prepared_result_or_block(node, route.decision)
    assert store.load()["blocked_reason"] == "repair_review_stale"
