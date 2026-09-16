"""Managed policy preparation preserves native effects; no new decision owner."""
from copy import deepcopy
from dataclasses import replace

import pytest
from tests.unit.test_discovery_turns import case, enrolled


@pytest.mark.parametrize("stopped", [False, True])
@pytest.mark.parametrize("diagnostic_key", ["external_publication_failure", "controller_completion_failure"])
def test_resolved_policy_checks_native_failure_resume_state_without_mutating(stopped, diagnostic_key):
    from harness.discovery_policy_resolution import _require_resolved_effects
    from harness.squad_state import StateAdvanceError
    marker = dict(schema_version=1, transaction_id="b" * 32, manifest_sha256="c" * 64)
    updates = dict(status="blocked" if stopped else "running", phase="terminal-blocked" if stopped else "checkpoint-assess")
    if stopped:
        updates["blocked_reason"] = "proportional_quality_debt_declined"
    recovery = dict(completion_id="a" * 32, effects=dict(state_updates=updates, state_removals=["quality_gate_remediation"]))
    state = dict(**{**updates, "status": "blocked", "blocked_reason": "external_publication_pending"},
        pending_controller_completion=dict(completion_id="a" * 32), pending_external_publication=marker,
        external_publication_failure=dict(schema_version=1, code="publish_io", resume_status=updates["status"],
            resume_blocked_reason=updates.get("blocked_reason")))
    if diagnostic_key == "controller_completion_failure":
        state[diagnostic_key] = {**state.pop("external_publication_failure"), "code": "stage_io"}
        state.pop("pending_external_publication")
        state["blocked_reason"] = "controller_completion_pending"
    before = deepcopy(state)
    _require_resolved_effects(state, recovery, dict(marker=marker))
    assert state == before
    for change in (dict(pending_controller_completion=dict(completion_id="d" * 32)),
            *((dict(pending_external_publication={**marker, "transaction_id": "d" * 32}),)
                if diagnostic_key == "external_publication_failure" else ()),
            dict(phase="phase3-plan"), dict(quality_gate_remediation={}),
            {diagnostic_key: {**state[diagnostic_key], "resume_status": "failed"}}):
        with pytest.raises((ValueError, StateAdvanceError)):
            _require_resolved_effects({**state, **change}, recovery, dict(marker=marker))


def test_debt_creation_stage_requires_the_exact_authenticated_resolution(tmp_path):
    """Stage selection only; full controller tests authenticate the binding."""
    from types import SimpleNamespace
    from harness.discovery_debt_resolution import publication
    from harness.squad import SquadController
    from harness.squad_publication import PublicationError
    from tests.unit.test_phase1_quality_debt import _debt_fixture
    state, _, native, paths = _debt_fixture(tmp_path, apply_effect=False)
    effect = dict(kind="proportional_quality", operation="debt_write", payload=native.effect_payload())
    staged = publication(tmp_path, tmp_path / "runs/run-1", "a" * 32, effect)
    ctrl = object.__new__(SquadController)
    ctrl._project_root = tmp_path
    ctrl._active_phase_a_spec_dir = lambda _: paths["debt"].parent
    ctrl._published_phase_a_spec_dir = lambda *_: paths["debt"].parent
    with staged.inspect_sources(tree_paths=("specs/001-demo",), file_paths=()) as sources:
        binding = SimpleNamespace(policy_resolution=True, recovery=dict(version=27, quality_effect=effect),
            sources=sources, source=dict(authority=dict(managed_identity=dict(spec_path="specs/001-demo"))))
        # The downstream-copy guard must still refuse an unpublished debt claim.
        with pytest.raises(PublicationError):
            ctrl._authenticate_quality_debt_publication_stage(staged, state)
        ctrl._authenticate_quality_debt_publication_stage(staged, state, managed_binding=binding)
        other = publication(tmp_path, tmp_path / "runs/run-1", "b" * 32, effect)
        with pytest.raises((PublicationError, ValueError)):
            ctrl._authenticate_quality_debt_publication_stage(other, state, managed_binding=binding)
        changed = SimpleNamespace(**{**binding.__dict__, "recovery": dict(version=21)})
        with pytest.raises(PublicationError):
            ctrl._authenticate_quality_debt_publication_stage(staged, state, managed_binding=changed)
    assert not paths["debt"].exists()


@pytest.mark.parametrize("choice,existing", [("continue_with_debt", False), ("stop", False), ("stop", True)])
def test_debt_publication_pins_native_bytes_or_exact_delete_without_applying(tmp_path, choice, existing):
    from types import SimpleNamespace
    from harness.discovery_debt_resolution import publication, require_publication, state_effects
    from harness.squad import _HumanInputResolutionEffects
    from tests.unit.test_phase1_quality_debt import _debt_fixture
    state, _, prepared, paths = _debt_fixture(tmp_path, apply_effect=existing)
    before = paths["debt"].read_bytes() if existing else None
    write = choice == "continue_with_debt"
    effect = dict(kind="proportional_quality", operation="debt_write" if write else "debt_remove",
        payload=prepared.effect_payload() if write else dict(operation="debt_remove", debt_path=prepared.debt_path))
    transaction = publication(tmp_path, tmp_path / "runs/run-1", "a" * 32, effect)
    with transaction.inspect_sources(tree_paths=("specs/001-demo",), file_paths=()) as sources:
        binding = SimpleNamespace(recovery=dict(quality_effect=effect), sources=sources,
            source=dict(authority=dict(managed_identity=dict(spec_path="specs/001-demo"))))
        require_publication(binding)
        operation, = sources.publication.operations
        assert operation.preimage.kind == ("file" if existing else "missing")
        assert operation.action == ("write" if write else "delete")
        if write:
            assert operation.postimage.mode == 0o600
        altered = replace(operation, target="specs/001-demo/spec.md")
        with pytest.raises(ValueError):
            require_publication(SimpleNamespace(**{**binding.__dict__, "sources": replace(sources,
                publication=replace(sources.publication, operations=(altered,)))}))
    assert (paths["debt"].read_bytes() if paths["debt"].exists() else None) == before
    decision = {**state["blocked_decision"], "selected_option_id": choice}
    updates = (dict(status="running", phase="checkpoint-assess", spec_status="accepted_with_debt",
        spec_quality_debt_authorization=prepared.authorization) if write else
        dict(status="blocked", phase="terminal-blocked", blocked_reason="proportional_quality_debt_declined"))
    removals = {"quality_gate_remediation"} | (set() if write else {"spec_quality_debt_authorization"})
    effects = _HumanInputResolutionEffects(updates, frozenset(removals), updates["phase"])
    assert state_effects(decision, effects, effect)["state_updates"] == updates
    with pytest.raises(ValueError):
        state_effects(decision, replace(effects, state_updates={**updates, "phase1_quality_repair": {}}), effect)


@pytest.mark.parametrize("mode,proven,expected", [("guided", True, False), ("semi", True, True),
    ("banzai", True, True), ("semi", False, False), ("banzai", False, False)])
def test_automatic_quality_policy_entry_requires_native_mode_and_review_proof(monkeypatch, mode, proven, expected):
    from harness.squad import SquadController
    from tests.unit.test_phase1_quality_debt import _sealed_decision
    controller = object.__new__(SquadController)
    decision = {**_sealed_decision(), "autonomy_mode": mode}
    state = dict(autonomy_mode=mode, blocked_decision=decision)
    monkeypatch.setattr(controller, "_managed_policy_human_input", lambda _: proven)
    assert controller._managed_automatic_policy_input(state) is expected


def test_debt_policy_shape_includes_native_extension_exhaustion_but_not_arbitrary_reasons():
    from harness.discovery_policy_resolution import supported_decision
    from tests.unit.test_phase1_quality_debt import _sealed_decision
    decision = _sealed_decision()
    for reason in ("proportional_quality_budget_exhausted", "proportional_quality_extension_exhausted"):
        assert supported_decision({**decision, "producer_id": reason, "reason_code": reason})
    assert not supported_decision({**decision, "producer_id": "unregistered", "reason_code": "unregistered"})


@pytest.mark.parametrize("version,plan,allowed", [(27, ["quality", "context"], True),
    (27, ["context"], False), (21, ["quality", "context"], False), (21, ["context"], True)])
def test_native_intent_keeps_managed_debt_effect_plan_closed(monkeypatch, version, plan, allowed):
    """Envelope shape only; decoding/ancestry are separate proof boundaries."""
    from types import SimpleNamespace
    from harness.squad_completion import _validate_intent, CompletionError
    from tests.unit.test_squad_completion import VALID_PUBLICATION_MARKER
    effect = dict(kind="proportional_quality", operation="debt_remove", payload=dict(
        operation="debt_remove", debt_path="specs/game/quality-debt.json"))
    binding = SimpleNamespace(resolution_publication=True, policy_resolution=True, producer="why2-policy", repair_unit=None,
        recovery=dict(version=version, from_phase="terminal-blocked", resolution=dict(id="dec-123"), quality_effect=effect),
        candidate=dict(route="terminal-blocked"))
    monkeypatch.setattr("harness.discovery_completion.decode_binding", lambda *args, **kwargs: binding)
    intent = dict(schema_version=1, completion_id="a" * 32, origin="resolution",
        publication=dict(kind="external", marker=VALID_PUBLICATION_MARKER, managed_discovery=dict(version=1, request="shape-only")),
        route=dict(kind="resolution", decision_id="dec-123", from_phase="terminal-blocked", to_phase="terminal-blocked"),
        effect_plan=plan, checkpoint_prestate=dict(kind="none"), quality_effect=effect if "quality" in plan else dict(kind="none"),
        context_reason="human-input proportional quality resolution", mine_phase_a=False, judgment_payload_sha256=[], judgments=[])
    if allowed:
        assert _validate_intent(intent)["effect_plan"] == plan
    else:
        with pytest.raises(CompletionError):
            _validate_intent(intent)


def test_reset_reconstruction_preserves_human_only_native_recommendation():
    from harness.blocked_decision import build_blocked_decision_v3
    from harness.human_input import HumanInputPolicyRegistry, controller_safeguard_policies, why2_safeguard_question
    from harness.discovery_policy_resolution import require_native_decision
    registry = HumanInputPolicyRegistry(controller_safeguard_policies())
    prepared = registry.prepare(source_kind="controller_safeguard", producer_id="why2_metric_stagnation",
        phase_id="phase1-why2", reason_code="why2_metric_stagnation",
        question=why2_safeguard_question("why2_metric_stagnation", 2), source_state_revision=7)
    decision = build_blocked_decision_v3(prepared=prepared, decision_id="dec-reset-decision", status="awaiting_human",
        autonomy_mode="guided")
    assert decision["automatic_eligible"] is False
    require_native_decision(prepared, decision)
    with pytest.raises(ValueError):
        require_native_decision(prepared, {**decision, "question": "A substituted counter question"})


def test_reset_capture_preserves_absence_of_perfectionist_repair_state():
    from harness.discovery_policy_resolution import _before_keys
    from harness.discovery_quality import capture_quality_policy
    original = dict(spec_authoring_mode="perfectionist", why_fail_count=3, why2_metric_stagnation_count=2)
    captured = {key: original.get(key) for key in _before_keys(True, original)}
    assert "phase1_quality_repair" not in captured
    assert capture_quality_policy(captured) == capture_quality_policy(original)
    assert "phase1_quality_repair" in _before_keys(False, {"spec_authoring_mode": "proportional"})
    assert "phase1_quality_repair" in _before_keys(True, {"spec_authoring_mode": "proportional"})
    with pytest.raises(ValueError):
        _before_keys(True, {**original, "phase1_quality_repair": None})


@pytest.mark.parametrize("handler", ["reset_why_fail_count", "reset_why2_stagnation"])
def test_native_counter_reset_payload_never_creates_a_proportional_budget(handler):
    from harness.discovery_policy_resolution import state_only_effects
    from harness.squad import SquadController
    from tests.unit.test_blocked_decision import _v2_decision
    ctrl = object.__new__(SquadController)
    ctrl._validate_human_input_route = lambda route, *args, **kwargs: route
    state = dict(spec_authoring_mode="perfectionist", phase="phase1-why2", status="blocked",
        why_fail_count=7, why2_metric_stagnation_count=4, iteration=6, token_usage=987)
    decision = {**_v2_decision(), "source_phase": "phase1-why2", "source_kind": "controller_safeguard",
        "producer_id": "consecutive_why_fails" if handler == "reset_why_fail_count" else "why2_metric_stagnation",
        "resolution_handler": handler}
    native = getattr(ctrl, "_" + handler + "_resolution")(state, decision, None, None, None)
    before = deepcopy(state)
    payload = state_only_effects(state, decision, None, native)
    expected = dict(status="running", phase="phase1-why2", why_fail_count=0)
    if handler == "reset_why2_stagnation":
        expected["why2_metric_stagnation_count"] = 0
    assert payload == dict(route="phase1-why2", state_updates=expected, state_removals=[])
    assert state == before
    for change in (dict(native.state_updates, token_usage=0), dict(native.state_updates, phase1_quality_repair={}),
            dict(native.state_updates, why_fail_count=1)):
        with pytest.raises(ValueError):
            state_only_effects(state, decision, None, replace(native, state_updates=change))


def test_extension_payload_preserves_consumption_and_candidate_membership():
    from types import SimpleNamespace
    from harness.discovery_policy_resolution import state_only_effects
    from harness.proportional_quality import initialize_repair_state
    from harness.squad import _HumanInputResolutionEffects
    from tests.unit.test_phase1_quality_debt import _sealed_decision
    repair = initialize_repair_state({"spec_authoring_mode": "proportional"})
    repair.update(automatic_consumed=3, baseline_candidate_id="quality-candidate-0",
        candidate_ids=["quality-candidate-" + str(index) for index in range(4)])
    state = dict(spec_authoring_mode="proportional", phase1_quality_repair=repair)
    updates = dict(status="running", phase="phase1-what", phase1_quality_repair={**repair, "extension_authorized": 1},
        why_fail_count=0, why2_metric_stagnation_count=0, quality_gate_remediation={"native": "retained"})
    effects = _HumanInputResolutionEffects(updates, frozenset(), "phase1-what")
    selected = SimpleNamespace(id="extend_once")
    payload = state_only_effects(state, _sealed_decision(), selected, effects)
    assert payload == dict(route="phase1-what", state_updates=updates, state_removals=[])
    assert payload["state_updates"] is not updates
    for key, value in (("automatic_consumed", 0), ("extension_consumed", 1), ("candidate_ids", [])):
        changed = deepcopy(updates)
        changed["phase1_quality_repair"][key] = value
        with pytest.raises(ValueError):
            state_only_effects(state, _sealed_decision(), selected, replace(effects, state_updates=changed))
    for option in ("continue_with_debt", "stop"):
        with pytest.raises(ValueError):
            state_only_effects(state, _sealed_decision(), SimpleNamespace(id=option), effects)
    with pytest.raises(ValueError):
        state_only_effects(state, _sealed_decision(), selected, replace(effects, completion=object()))


def test_policy_choice_is_not_a_clarification_record(enrolled):
    from tests.unit.test_why1_tracker_parent import row, resolved
    from tests.unit.test_phase1_quality_debt import _sealed_decision
    from harness.discovery_producer import tracker_rounds
    from harness.discovery_spec import clarification_source
    from harness.discovery_policy_resolution import resolution_associations
    from harness.tracker_clarification import _resolution_rows
    state = enrolled[1].load()
    first, parent, child = "what-" + "a" * 32, "why2-" + "b" * 32, "what-" + "c" * 32
    state["managed_why2_rounds"] = dict(schema_version=1, active=parent, rounds={parent: row("b", "why2")})
    association = resolved("c", "Audience?", "Single player", "why2")
    association["decision"] = {**_sealed_decision(status="resolved"), "selected_option_id": "extend_once"}
    association["completion"]["decision_id"] = association["decision"]["id"]
    current = dict(source=clarification_source(association["completion"]), resolution=None, predecessor=first,
        operation=None, turns=None, review_resolution=association, review_parent=parent)
    state["managed_what_rounds"] = dict(schema_version=1, active=child, rounds={first: row("a", "what"), child: current})
    assert tracker_rounds(state, "what")["rounds"][child] == current
    assert resolution_associations(state) == ((current, association),)
    assert _resolution_rows(state, "why2") == ()
    for option in ("continue_with_debt", "stop"):
        changed = deepcopy(state)
        changed["managed_what_rounds"]["rounds"][child]["review_resolution"]["decision"]["selected_option_id"] = option
        with pytest.raises(ValueError):
            tracker_rounds(changed, "what")


@pytest.mark.parametrize("option", ["extend_once", "continue_with_debt", "stop"])
def test_policy_admission_does_not_prepare_effects_without_review_proof(monkeypatch, option):
    from types import SimpleNamespace
    from harness.squad import SquadController, LEGACY_IDENTITY_EXECUTION_BLOCKED
    from harness.human_input import AppliedHumanInputResolution, HumanInputPolicyError
    from tests.unit.test_phase1_quality_debt import _sealed_decision
    ctrl = object.__new__(SquadController)
    state = dict(managed_identity={}, blocked_decision=_sealed_decision(), state_revision=5)
    ctrl._state_store = SimpleNamespace(load=lambda: deepcopy(state))
    monkeypatch.setattr(ctrl, "_managed_tracker_human_input", lambda _: False)
    monkeypatch.setattr(ctrl, "_legacy_identity_execution_blocked", lambda _: True)
    monkeypatch.setattr(ctrl, "_managed_why2_completion_wait", lambda _: False)
    monkeypatch.setattr(ctrl, "_proportional_quality_debt_resolution",
        lambda *args: pytest.fail("Unadmitted choices must not prepare native file effects"))
    with pytest.raises(HumanInputPolicyError, match=LEGACY_IDENTITY_EXECUTION_BLOCKED):
        ctrl.apply_human_input_resolution(state["blocked_decision"]["id"], expected_state_revision=5,
            resolution=AppliedHumanInputResolution(option, None, "user"))


def test_native_reset_question_has_one_exact_counter_derived_form():
    from harness.human_input import why2_safeguard_question, HumanInputPolicyError
    assert why2_safeguard_question("why2_metric_stagnation", 2) == (
        "WHY2 certified metrics did not improve across 2 consecutive repair cycles. "
        "Provide new evidence, narrow scope, or authorize a different repair strategy.")
    assert why2_safeguard_question("consecutive_why_fails", 3).startswith(
        "phase1-why2 still fails after 3 assessments without a spec artifact change. No automatic retry is authorized.")
    for reason, count in (("other", 2), ("why2_metric_stagnation", True), ("consecutive_why_fails", 1),
            ("why2_metric_stagnation", "2")):
        with pytest.raises(HumanInputPolicyError):
            why2_safeguard_question(reason, count)


@pytest.mark.parametrize("handler,reason", [("reset_why_fail_count", "consecutive_why_fails"),
    ("reset_why2_stagnation", "why2_metric_stagnation")])
def test_proven_native_reset_enters_policy_publication_not_clarification(monkeypatch, handler, reason):
    from types import SimpleNamespace
    from harness.squad import SquadController
    from harness.human_input import AppliedHumanInputResolution
    from tests.unit.test_blocked_decision import _v2_decision
    import harness.discovery_policy_resolution as policy
    ctrl = object.__new__(SquadController)
    decision = {**_v2_decision(), "source_phase": "phase1-why2", "source_kind": "controller_safeguard",
        "producer_id": reason, "reason_code": reason, "resolution_handler": handler}
    state = dict(managed_identity={}, blocked_decision=decision, state_revision=5)
    ctrl._state_store = SimpleNamespace(load=lambda: deepcopy(state))
    monkeypatch.setattr(ctrl, "_managed_tracker_human_input", lambda _: False)
    monkeypatch.setattr(ctrl, "_legacy_identity_execution_blocked", lambda _: True)
    monkeypatch.setattr(ctrl, "_managed_why2_completion_wait", lambda _: True)
    monkeypatch.setattr(ctrl, "_policy_for_human_input_decision", lambda _: None)
    monkeypatch.setattr(ctrl, "_validate_human_input_resolver", lambda *args: None)
    monkeypatch.setattr(ctrl, "_validate_human_input_resolution_answer", lambda *args: None)
    monkeypatch.setattr(ctrl, "_validate_human_input_route", lambda phase, *args: phase)
    monkeypatch.setattr(ctrl, "_cleanup_controller_completion_orphans", lambda: True)
    class PrepareReached(Exception):
        pass
    def prepare(*args):
        assert args[-1].state_updates["why_fail_count"] == 0
        assert "phase1_quality_repair" not in args[-1].state_updates
        raise PrepareReached()
    monkeypatch.setattr(policy, "prepare", prepare)
    with pytest.raises(PrepareReached):
        ctrl.apply_human_input_resolution(decision["id"], expected_state_revision=5,
            resolution=AppliedHumanInputResolution(None, "Use the existing acceptance criterion.", "user"))


def test_reset_round_retains_receipt_without_creating_clarification(enrolled):
    from tests.unit.test_why1_tracker_parent import row, resolved
    from tests.unit.test_blocked_decision import _v2_decision
    from harness.human_input import AppliedHumanInputResolution
    from harness.squad_state import build_human_input_resolution_postimage
    from harness.discovery_spec import clarification_source
    from harness.discovery_producer import tracker_rounds
    from harness.discovery_policy_resolution import resolution_associations, require_reset_resolved
    from harness.tracker_clarification import _resolution_rows
    state = enrolled[1].load()
    previous, current = "why2-" + "a" * 32, "why2-" + "c" * 32
    association = resolved("c", "Controls?", "Arrow keys", "why2")
    before = {**_v2_decision(), "source_phase": "phase1-why2", "source_kind": "controller_safeguard",
        "producer_id": "why2_metric_stagnation", "reason_code": "why2_metric_stagnation",
        "resolution_handler": "reset_why2_stagnation"}
    association["decision"] = build_human_input_resolution_postimage(before,
        AppliedHumanInputResolution(None, "Reassess the existing acceptance criterion.", "user"), resolved_at="2026-09-16T12:00:00+00:00")
    association["completion"]["decision_id"] = association["decision"]["id"]
    child = dict(source=clarification_source(association["completion"]), resolution=association,
        predecessor=previous, operation=None, turns=None)
    state["managed_why2_rounds"] = dict(schema_version=1, active=current, rounds={previous: row("a", "why2"), current: child})
    require_reset_resolved(association["decision"])
    assert tracker_rounds(state, "why2")["rounds"][current] == child
    assert resolution_associations(state) == ((child, association),) and _resolution_rows(state, "why2") == ()
    changed = deepcopy(association["decision"])
    changed["resolution_handler"] = "clarification_resume"
    with pytest.raises(ValueError):
        require_reset_resolved(changed)


@pytest.mark.parametrize("proven", [False, True])
@pytest.mark.parametrize("choice", [False, True])
def test_public_human_resume_requires_policy_proof_and_keeps_native_answer_parsing(monkeypatch, proven, choice):
    from types import SimpleNamespace
    from harness.squad import SquadController, LEGACY_IDENTITY_EXECUTION_BLOCKED
    from harness.human_input import AppliedHumanInputResolution, HumanInputPolicyError
    from tests.unit.test_blocked_decision import _v2_decision
    from tests.unit.test_phase1_quality_debt import _sealed_decision
    ctrl = object.__new__(SquadController)
    decision = _sealed_decision() if choice else {**_v2_decision(), "status": "awaiting_human", "source_phase": "phase1-why2",
        "source_kind": "controller_safeguard", "producer_id": "why2_metric_stagnation",
        "reason_code": "why2_metric_stagnation", "resolution_handler": "reset_why2_stagnation"}
    state = dict(blocked_decision=decision, state_revision=9)
    ctrl._state_store = SimpleNamespace(load=lambda: deepcopy(state))
    monkeypatch.setattr(ctrl, "_legacy_identity_execution_blocked", lambda _: True)
    monkeypatch.setattr(ctrl, "_managed_tracker_human_input", lambda _: False)
    monkeypatch.setattr(ctrl, "_managed_policy_human_input", lambda _: proven)
    monkeypatch.setattr("harness.recovery_instruction.validate_decision_recovery_pair", lambda *args: None)
    resolutions = []
    def apply(decision_id, **kwargs):
        assert decision_id == decision["id"] and kwargs["expected_state_revision"] == 9
        resolutions.append(kwargs["resolution"])
        return True
    monkeypatch.setattr(ctrl, "apply_human_input_resolution", apply)
    answer = "extend_once" if choice else "Keep the existing scope and reassess."
    if not proven:
        with pytest.raises(HumanInputPolicyError, match=LEGACY_IDENTITY_EXECUTION_BLOCKED):
            ctrl.resume_with_human_input(answer)
        assert not resolutions
    else:
        assert ctrl.resume_with_human_input(answer)
        assert resolutions == [AppliedHumanInputResolution("extend_once" if choice else None,
            None if choice else answer, "user")]
    assert ctrl._state_store.load() == state


def test_native_issue_effects_can_be_rederived_from_captured_candidates_and_timestamp(tmp_path):
    from harness.blocked_decision import build_blocked_decision_v3
    from tests.unit.test_projected_quality_assessment import failing_review
    ctrl, store, result, sources = failing_review(tmp_path, banzai=True)
    snapshot = store.capture_routing_snapshot(expected_phase="phase1-why2")
    assessment = ctrl._authoritative_quality_assessment(provider_verdict="FAIL", eval_state=snapshot.state,
        routes=tuple(result.echelon_result["state_updates"]["finding_routes"]["findings"]),
        spec_dir=tmp_path / snapshot.state["spec_dir"], publication_sources=sources)
    prepared = ctrl._prepare_banzai_quality_issue_resolution(snapshot, assessment)
    decision = build_blocked_decision_v3(prepared=prepared, decision_id="dec-issue-proof", status="pending",
        autonomy_mode="banzai")
    candidates = ctrl._banzai_issue_resolution_candidates(snapshot.state, sage_evidence=assessment.sage_evidence)
    selected = ctrl._human_input_options_from_decision(decision)[0]
    policy = ctrl._policy_for_human_input_decision(decision)
    stamp = "2026-09-16T14:00:00+00:00"
    before = deepcopy(snapshot.state)
    effects = ctrl._banzai_issue_resolution_effects(before, decision, policy, selected, candidates, recorded_at=stamp)
    assert effects.route == "phase1-what" and effects.state_removals == frozenset({"quality_gate_remediation"})
    assert effects.state_updates["selected_issue_resolution"] == "ISS-000001"
    assert effects.state_updates["issue_resolution_repair_baseline"]["recorded_at"] == stamp
    assert effects.state_updates["issue_resolution_ledger"]["ISS-000001"]["issue_fingerprint"] == candidates[0]["issue_fingerprint"]
    assert "phase1_quality_repair" not in effects.state_updates and before == snapshot.state
    assert ctrl._banzai_issue_resolution_effects(before, decision, policy, selected, candidates, recorded_at=stamp) == effects
    from types import SimpleNamespace
    from harness.discovery_issue_resolution import require_issue_effects, evidence_reader
    parent = SimpleNamespace(sources=sources, candidate={"routing": result.echelon_result})
    payload = dict(route=effects.route, state_updates=effects.state_updates, state_removals=sorted(effects.state_removals))
    from harness.discovery_policy_resolution import state_only_effects
    assert state_only_effects(before, decision, selected, effects) == payload
    require_issue_effects(ctrl, before, decision, selected.id, parent, payload)
    require_issue_effects(evidence_reader(tmp_path), before, decision, selected.id, parent, payload)
    from harness.squad_state import build_human_input_resolution_postimage
    resolved = build_human_input_resolution_postimage(decision, ctrl._banzai_issue_controller_resolution(decision), resolved_at=stamp)
    require_issue_effects(evidence_reader(tmp_path), before, resolved, selected.id, parent, payload)
    changed_payload = deepcopy(payload)
    changed_payload["state_updates"]["issue_resolution_ledger"]["ISS-000001"]["issue_fingerprint"] = "0" * 64
    with pytest.raises(ValueError):
        require_issue_effects(ctrl, before, decision, selected.id, parent, changed_payload)
    from harness.human_input import HumanInputPolicyError
    changed = deepcopy(candidates)
    changed[0]["suggested_option"] = "A different, unsealed repair"
    with pytest.raises(HumanInputPolicyError):
        ctrl._banzai_issue_resolution_effects(before, decision, policy, selected, changed, recorded_at=stamp)
    for invalid in ("not-a-date", "2026-09-16T14:00:00", True):
        with pytest.raises(HumanInputPolicyError):
            ctrl._banzai_issue_resolution_effects(before, decision, policy, selected, candidates, recorded_at=invalid)
