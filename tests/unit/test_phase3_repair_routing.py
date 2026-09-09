from dataclasses import asdict

import pytest

from harness.phase3_repair import RepairIdentity


def work_state(kind="investigate_or_design", mode="banzai"):
    identity = RepairIdentity("r", "f" * 64, 7)
    manifest = {"spec.md": "a" * 64, "contracts/api.md": "b" * 64}
    action = {"schema_version": 1, "identity": asdict(identity), "kind": kind,
        "owner_phase": "phase3-how", "affected_artifacts": ["contracts/api.md"],
        "evidence_refs": ["spec.md#FR-001"], "action": "Design an observation protocol.",
        "constraints": ["Preserve all requirements; proposals are not facts."]}
    state = {"phase": "phase3-consensus", "run_id": "r", "autonomy_mode": mode,
        "why3_verdict": "FAIL", "phase_dispatch_counts": {"phase3-how": 4},
        "phase3_pending_action": {"identity": asdict(identity), "issue_id": "ISS-002",
            "title": "Observation missing", "input_manifest": manifest, "assessment": action}}
    return state, manifest


def test_technical_work_routes_without_accepting_answer_or_resetting_caps():
    from harness.phase3_repair_routing import phase3_work_route
    state, manifest = work_state()
    route, updates = phase3_work_route(state, manifest)
    assert route == "phase3-how"
    assert updates["selected_issue_resolution"] == "ISS-002"
    entry = updates["issue_resolution_ledger"]["ISS-002"]
    assert entry["status"] == "selected"
    assert entry["repair_action"]["kind"] == "investigate_or_design"
    assert "decision" not in entry
    assert "phase_dispatch_counts" not in updates
    assert state["why3_verdict"] == "FAIL"


@pytest.mark.parametrize("kind", ["human_decision", "external_prerequisite", "apply_evidenced_resolution"])
def test_non_work_classifications_never_become_automatic_answer_adoption(kind):
    from harness.phase3_repair_routing import phase3_work_route
    state, manifest = work_state(kind)
    route, updates = phase3_work_route(state, manifest)
    assert route == "terminal-blocked"
    assert "selected_issue_resolution" not in updates


@pytest.mark.parametrize("change", ["semi", "why2", "stale", "protected", "scope", "owner"])
def test_work_route_preserves_existing_authority_boundaries(change):
    from harness.phase3_repair_routing import phase3_work_route
    state, manifest = work_state()
    if change == "semi": state["autonomy_mode"] = "semi"
    if change == "why2": state["phase"] = "phase1-why2"
    if change == "stale": manifest = {**manifest, "spec.md": "c" * 64}
    if change == "protected": state["phase3_pending_action"]["assessment"]["affected_artifacts"] = ["spec.md"]
    if change == "scope": state["phase3_pending_action"]["assessment"]["affected_artifacts"] = ["../app.ts"]
    if change == "owner": state["phase3_pending_action"]["assessment"]["owner_phase"] = "phase1-what"
    route, updates = phase3_work_route(state, manifest)
    assert route != "phase3-how"
    assert "selected_issue_resolution" not in updates


def test_existing_iteration_cap_wins_before_technical_work_assignment():
    from harness.phase3_repair_routing import phase3_work_route
    state, manifest = work_state()
    state.update(iteration=2, max_iterations=2)
    route, updates = phase3_work_route(state, manifest)
    assert route == "terminal-blocked"
    assert updates["blocked_reason"] == "repair_budget_exhausted"
    assert "selected_issue_resolution" not in updates


def test_fresh_pass_does_not_replay_pending_work():
    from harness.phase3_repair_routing import phase3_work_route
    state, manifest = work_state()
    state["why3_verdict"] = "PASS"
    route, updates = phase3_work_route(state, manifest)
    assert route is None
    assert "selected_issue_resolution" not in updates


def test_pass_cannot_leave_any_stale_validated_receipt_behind():
    from harness.phase3_repair_routing import phase3_work_route
    state, manifest = work_state()
    state.update(why3_verdict="PASS", phase3_pending_action=None,
        issue_resolution_ledger={"ISS-A": {"status": "validated", "repair_phase": "phase3-how",
            "repair_identity": asdict(RepairIdentity("r", "a" * 64, 1)), "last_review_dispatch_id": "old"}},
        phase3_issue_reviews={"old": {"reviewed_artifacts": {"spec.md": "c" * 64}}})
    route, _ = phase3_work_route(state, manifest)
    assert route == "phase3-consensus"


def test_external_prerequisite_has_actionable_terminal_reason():
    from harness.phase3_repair_routing import phase3_work_route
    state, manifest = work_state("external_prerequisite")
    route, updates = phase3_work_route(state, manifest)
    assert route == "terminal-blocked"
    assert updates["blocked_reason"] == "repair_external_prerequisite"


def test_changed_finding_cannot_replay_pending_work_despite_aggregate_fail():
    from harness.phase3_repair_routing import phase3_work_route
    state, manifest = work_state()
    route, updates = phase3_work_route(state, manifest, current_findings=frozenset({"c" * 64}))
    assert route is None
    assert updates == {"phase3_pending_action": None}
