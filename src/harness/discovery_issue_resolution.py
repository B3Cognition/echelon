"""Re-derive native Banzai issue effects from captured WHY2 evidence.

This module cannot grant managed execution or publish a decision. Its caller
must authenticate the review, source images, original state and resolved choice.
"""
from types import SimpleNamespace


def supported_decision(decision):
    return (type(decision) is dict and decision.get("source_kind") == "controller_safeguard"
        and decision.get("source_phase") == "phase1-why2" and decision.get("autonomy_mode") == "banzai"
        and decision.get("producer_id") == decision.get("reason_code") == decision.get("resolution_handler") == "banzai_issue_resolution")


def require_resolved(decision):
    from harness.blocked_decision import validate_blocked_decision
    from harness.discovery_completion import _require
    _require(validate_blocked_decision(decision) == decision and supported_decision(decision)
        and decision["status"] == "resolved" and decision["answer_text"] is None
        and decision["selected_option_id"] is not None)


def admitted_choice(decision, selected_id=None):
    """Native WHY2 choice successor; Discovery uses its prior direct owner route."""
    if not supported_decision(decision):
        return False
    chosen = selected_id or decision.get("selected_option_id") or decision.get("recommended_option_id")
    return any(option.get("id") == chosen and option.get("next_phase") == "phase1-what"
        for option in decision.get("options", []))


def evidence_reader(root):
    """Native read/derive methods only; no graph, executor, store or dispatcher."""
    from harness.squad import SquadController
    from harness.human_input import HumanInputPolicyRegistry, controller_safeguard_policies
    reader = object.__new__(SquadController)
    reader._project_root = root
    reader._human_input_registry = HumanInputPolicyRegistry(controller_safeguard_policies())
    return reader


def require_issue_effects(controller, before, decision, selected_id, parent, payload):
    from harness.discovery_completion import _require
    from harness.discovery_policy_resolution import require_native_decision
    from harness.proportional_quality import project_authoritative_sage_evidence_snapshot

    _require(decision["source_kind"] == "controller_safeguard"
        and decision["producer_id"] == decision["reason_code"] == decision["resolution_handler"] == "banzai_issue_resolution"
        and decision["source_phase"] == "phase1-why2" and decision["autonomy_mode"] == before["autonomy_mode"] == "banzai"
        and before["spec_authoring_mode"] == "proportional" and parent.candidate["routing"]["verdict"] == "FAIL")
    sage = project_authoritative_sage_evidence_snapshot(parent.sources,
        controller._proportional_spec_dir(before) / "issues.md", project_root=controller._project_root)
    assessment = SimpleNamespace(sage_evidence=sage,
        exact_routes=tuple(parent.candidate["routing"]["state_updates"]["finding_routes"]["findings"]))
    prepared = controller._prepare_banzai_quality_issue_resolution(
        SimpleNamespace(state=before, state_revision=decision["source_state_revision"]), assessment)
    _require(prepared is not None)
    require_native_decision(prepared, decision)
    candidates = controller._banzai_issue_resolution_candidates(before, sage_evidence=sage)
    selected, = (option for option in controller._human_input_options_from_decision(decision) if option.id == selected_id)
    controller._policy_for_human_input_decision(decision)
    sealed = [controller._dispatch_cap_candidate_for_resolution(before, option, candidates=candidates)
        for option in controller._human_input_options_from_decision(decision)]
    candidate, = (item for item in sealed if item["issue_id"] == selected.id)
    selection = controller._validate_banzai_issue_resolution_selection(dict(issue_id=selected.id,
        decision=candidate["suggested_option"], rationale=candidate["evidence_basis"], confidence="high", evidence_backed=True), [candidate])
    _require(selection is not None and selected.next_phase == selection["repair_phase"])
    updates = controller._issue_resolution_state_updates(before, selection, source_phase=decision["source_phase"],
        pending_candidates=sealed, recorded_at=payload["state_updates"]["issue_resolution_repair_baseline"]["recorded_at"])
    updates.update(status="running", phase=selected.next_phase, why_fail_count=0,
        why2_metric_stagnation_count=0, why_failure_baseline=None)
    _require(payload == dict(route=selected.next_phase, state_updates=updates, state_removals=["quality_gate_remediation"]))
