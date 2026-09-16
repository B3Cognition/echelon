"""Managed answers retain the native clarification policy, not stale authority."""
from copy import deepcopy

import pytest


@pytest.mark.parametrize("producer", ["tracker", "why1", "why2"])
def test_clarification_claim_uses_exact_producer_contract(producer):
    from harness.tracker_clarification import question_claim
    from tests.unit.test_managed_spec_contract import routing
    expected = dict(question="Which audience?", recommended_answer="Single player", risk_level="low")
    if producer == "why2":
        claim = routing("why2")
        assert question_claim(claim, producer) is None
        claim["verdict"] = "STOP_AND_ASK"
        claim["state_updates"].update(status="blocked", blocked_reason="human_clarification_required",
            escalation_question=expected["question"], escalation_recommended_answer=expected["recommended_answer"],
            escalation_risk_level=expected["risk_level"])
    else:
        claim = dict(verdict="STOP_AND_ASK", **expected)
    before = deepcopy(claim)
    assert question_claim(claim, producer) == expected and claim == before
    if producer == "why2":
        claim["question"] = "Injected top-level question"
    else:
        claim["state_updates"] = dict(escalation_question="Injected nested question")
    with pytest.raises(ValueError):
        question_claim(claim, producer)


@pytest.mark.parametrize("mode", ["proportional", "perfectionist"])
def test_clarification_quality_reset_preserves_native_mode_and_unrelated_counters(mode):
    from harness.squad import SquadController
    from harness.proportional_quality import initialize_repair_state
    ctrl = object.__new__(SquadController)
    state = dict(spec_authoring_mode=mode, token_usage=321, phase_dispatch_counts={"phase1-why2": 3},
        iteration=2, quality_gate_remediation={"candidate_id": "old"},
        proportional_quality_candidate_evidence={"selected_candidate_id": "old"})
    before = deepcopy(state)
    updates, removals = ctrl._clarification_quality_effects(state)
    assert state == before
    if mode == "proportional":
        assert updates == {"phase1_quality_repair": initialize_repair_state({"spec_authoring_mode": mode})}
        assert removals == frozenset({"quality_gate_remediation", "proportional_quality_candidate_evidence"})
    else:
        assert updates == {} and removals == frozenset()


@pytest.mark.parametrize("mode", ["proportional", "perfectionist"])
@pytest.mark.parametrize("native_default", [False, True])
def test_managed_clarification_applies_native_quality_reset(monkeypatch, tmp_path, mode, native_default):
    from types import SimpleNamespace
    import harness.squad as squad
    import harness.tracker_clarification as clarification
    import harness.element_identity_publication as publication
    ctrl = object.__new__(squad.SquadController)
    ctrl._project_root, ctrl._squad_dir = tmp_path, tmp_path / "run"
    state = dict(phase="phase1-why2", spec_authoring_mode=mode)
    ctrl._state_store = SimpleNamespace(capture_routing_snapshot=lambda **kwargs: SimpleNamespace(state=state))
    ctrl._graph = SimpleNamespace(all_phase_ids=lambda: {"phase1-why2", "phase1-what"})
    monkeypatch.setattr(ctrl, "_managed_tracker_human_input", lambda current: True)
    monkeypatch.setattr(ctrl, "_banzai_default_candidate_for_decision", lambda *args: object() if native_default else None)
    monkeypatch.setattr(ctrl, "_validate_human_input_route", lambda phase, *args, **kwargs: phase)
    monkeypatch.setattr(ctrl, "_prepare_controller_completion", lambda **kwargs: "prepared")
    monkeypatch.setattr(squad, "build_human_input_resolution_postimage", lambda *args, **kwargs: {"id": "decision"})
    monkeypatch.setattr(publication, "encode_publication_request", lambda request: request)
    monkeypatch.setattr(clarification, "prepare", lambda *args, **kwargs: (
        SimpleNamespace(marker=SimpleNamespace(to_dict=lambda: {})), {},
        SimpleNamespace(reconciliation_json='{"requires_repair":false}', policy_text='{}')))
    effects = ctrl._managed_clarification_resume_resolution(state, {"id": "decision"}, None, None, None)
    if mode == "proportional":
        from harness.proportional_quality import initialize_repair_state
        assert effects.state_updates["phase1_quality_repair"] == initialize_repair_state({"spec_authoring_mode": mode})
        assert effects.state_removals == frozenset({"quality_gate_remediation", "proportional_quality_candidate_evidence"})
    else:
        assert "phase1_quality_repair" not in effects.state_updates and not effects.state_removals
    assert effects.completion == "prepared" and effects.route == ("phase1-what" if native_default else "phase1-why2")


@pytest.mark.parametrize("producer", ["tracker", "why1"])
def test_later_answer_previews_downstream_artifacts_without_write_authority(monkeypatch, tmp_path, producer):
    """Exercise preparation to its real preview boundary, not just role lookup."""
    from types import SimpleNamespace
    import harness.tracker_clarification as clarification
    import harness.discovery_producer as producers
    from harness.element_identity_store import IdentityStore
    state = {"last_dispatch": {key: "captured" for key in producers.SOURCE_FIELDS}}
    selected = {"selection": {"spec_id": "game", "spec_path": "specs/game"}}
    operation = {"binding": {"input_tree": "input", "artifact_paths": (), "operation_id": "selected"}}
    before = {"spec.md": "requirements", "requirements-overview.md": "overview", "quality-gates.md": "review"}
    writes = {"specs/game/feature-policy-reconciliation.md": "report", "run/staging/user-clarifications.md": "answer"}
    candidate = SimpleNamespace(reconciliation_text="report")
    class PreviewReached(Exception):
        pass
    def preview(**kwargs):
        from harness.discovery_semantics import captured_artifact_roles
        roles = captured_artifact_roles(producer, after_review=True)
        artifacts = {item.path: item for item in kwargs["artifacts"]}
        for name, text in before.items():
            assert artifacts[name].role == roles[name]
            assert artifacts[name].before_text == artifacts[name].after_text == text
        assert kwargs["scope"].writable_paths == ("feature-policy-reconciliation.md", "run/staging/user-clarifications.md")
        assert kwargs["operations"] == ()
        raise PreviewReached
    monkeypatch.setattr(IdentityStore, "open", lambda root: SimpleNamespace(preview_identity_candidate=preview))
    monkeypatch.setattr(clarification, "bootstrap_from_state", lambda current: selected)
    monkeypatch.setattr(clarification, "operation_from_state", lambda *args: operation)
    monkeypatch.setattr(clarification, "_capture", lambda *args, **kwargs: (None, None, None, "history", None, None, "sources", {}))
    monkeypatch.setattr(clarification, "retained_clarification_records", lambda *args, **kwargs: ())
    monkeypatch.setattr(clarification, "capture_clarification_history", lambda *args: (18, ()))
    monkeypatch.setattr(clarification, "_candidate", lambda *args: (candidate, writes, before))
    monkeypatch.setattr(producers, "post_why1_context", lambda *args: True)
    monkeypatch.setattr("harness.discovery_candidate.issue_report_changes", lambda *args, **kwargs: ((), ()))
    with pytest.raises(PreviewReached):
        clarification.prepare(tmp_path, SimpleNamespace(squad_dir=tmp_path / "run"),
            state=state, resolved={}, completion_id="completion", producer=producer)


@pytest.mark.parametrize("damage", [None, "mode", "phase", "authority", "eligible", "digest", "issue", "missing", "unsealed", "guided", "semi"])
def test_default_answer_target_requires_exact_native_envelope(damage):
    from harness.tracker_clarification import require_question_default, clarification_target
    from harness.human_input import AutonomousDefaultCandidate, BANZAI_DEFAULT_RECOMMENDED_ACTION
    from tests.unit.test_managed_spec_contract import routing
    payload = dict(issue_id="ISS-000001", authority_capability="banzai_default", question="Which controls?",
        affected_requirements=["FR-000001"], alternatives=["Arrow keys", "WASD"],
        constraints=["Use one keyboard scheme"], source_references=["spec.md#FR-000001"])
    candidate = AutonomousDefaultCandidate.from_provider_payload(payload)
    decision = dict(source_phase="phase1-why2", autonomy_mode="banzai", automatic_eligible=True,
        question=payload["question"], recommended_action=BANZAI_DEFAULT_RECOMMENDED_ACTION,
        recommendation_authority="controller_evidence", recommendation_evidence=[dict(
            id="banzai-default:ISS-000001", kind="banzai_default_candidate",
            reference="ISS-000001:spec.md#FR-000001", digest=candidate.fingerprint)])
    claim = routing("why2")
    claim["verdict"] = "STOP_AND_ASK"
    claim["state_updates"].update(status="blocked", blocked_reason="human_clarification_required",
        escalation_question=payload["question"], autonomous_default_candidate=payload)
    claim["state_updates"]["finding_routes"]["findings"] = [dict(issue_id="ISS-000001",
        route="autonomous_default_candidate", rationale="A bounded control default is required.")]
    if damage == "mode": decision["autonomy_mode"] = "guided"
    elif damage == "phase": decision["source_phase"] = "phase1-why1"
    elif damage == "authority": decision["recommendation_authority"] = "provider_evidence"
    elif damage == "eligible": decision["automatic_eligible"] = False
    elif damage == "digest": decision["recommendation_evidence"][0]["digest"] = "0" * 64
    elif damage == "issue": claim["state_updates"]["finding_routes"]["findings"][0]["issue_id"] = "ISS-000002"
    elif damage == "missing": claim["state_updates"].pop("autonomous_default_candidate")
    elif damage in {"unsealed", "guided", "semi"}:
        decision.update(autonomy_mode="banzai" if damage == "unsealed" else damage,
            automatic_eligible=False, recommended_action=None,
            recommendation_authority="workflow_policy", recommendation_evidence=[])
    if damage in {"guided", "semi"}:
        # Native preparation validates the raw proposal but seals an ordinary
        # human question outside Banzai; it does not seal default authority.
        assert require_question_default(claim, "why2", decision) is None
        assert clarification_target("why2", decision, requires_repair=False) == "phase1-why2"
    elif damage is not None:
        with pytest.raises(ValueError):
            require_question_default(claim, "why2", decision)
    else:
        assert require_question_default(claim, "why2", decision) == candidate
        # No textual contradiction is necessary: the native default must be
        # authored by WHAT before a new Understanding/WHY2 assessment.
        assert clarification_target("why2", decision, requires_repair=False) == "phase1-what"
        assert clarification_target("why2", {}, requires_repair=False) == "phase1-why2"


@pytest.mark.parametrize("cleanup", [False, True])
def test_managed_answer_retry_cleans_only_verified_drafts_before_replacement(monkeypatch, cleanup):
    from types import SimpleNamespace
    import harness.squad as squad
    from harness.human_input import AppliedHumanInputResolution, HumanInputPolicyError
    ctrl = object.__new__(squad.SquadController)
    decision = dict(id="decision", status="awaiting_human", resolution_handler="clarification_resume")
    state = dict(state_revision=3, blocked_decision=decision)
    ctrl._state_store = SimpleNamespace(load=lambda: deepcopy(state))
    seen = []
    monkeypatch.setattr(ctrl, "_managed_tracker_human_input", lambda current: True)
    monkeypatch.setattr(ctrl, "_legacy_identity_execution_blocked", lambda current: True)
    monkeypatch.setattr(squad, "validate_blocked_decision", lambda value: value)
    monkeypatch.setattr(ctrl, "_policy_for_human_input_decision", lambda value: None)
    monkeypatch.setattr(ctrl, "_validate_human_input_resolver", lambda *args: None)
    monkeypatch.setattr(ctrl, "_validate_human_input_resolution_answer", lambda *args: None)
    monkeypatch.setattr(ctrl, "_cleanup_controller_completion_orphans", lambda: seen.append("cleanup") or cleanup)
    class Prepared(Exception):
        pass
    def prepare(*args):
        seen.append("prepare")
        raise Prepared
    monkeypatch.setattr(ctrl, "_managed_clarification_resume_resolution", prepare)
    with pytest.raises(Prepared if cleanup else HumanInputPolicyError):
        ctrl.apply_human_input_resolution("decision", expected_state_revision=3,
            resolution=AppliedHumanInputResolution(None, "Single player", "user"))
    assert seen == (["cleanup", "prepare"] if cleanup else ["cleanup"])
