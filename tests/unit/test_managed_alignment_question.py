"""Reviewed alignment questions seal native decisions, not author-made answers."""
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
from harness.discovery_completion import authenticate, decode_binding
from harness.discovery_publication import prepare_discovery_publication
from harness.element_identity_publication import encode_publication_request
from harness.squad_completion import CompletionError, load_prepared_spec_step_effects
from harness.squad_publication import PreparedSquadPublication
from tests.unit.test_managed_alignment_execution import (
    case, enrolled, turn_prepared, prepared, checkpoint_case, complete_strategy,
    AlignmentExecutor, assert_reviewed_alignment,
)
from tests.unit.test_managed_alignment_publication import envelope
from tests.unit.test_discovery_completion import controller, drain
from tests.unit.test_discovery_turns import Interrupted


def question():
    return dict(verdict="STOP_AND_ASK", state_updates=dict(status="blocked",
        blocked_reason="human_clarification_required", escalation_question="Which movement controls?",
        escalation_recommended_answer="Use arrow keys", escalation_risk_level="low"))


def test_alignment_question_claim_preserves_native_evidence():
    from harness.tracker_clarification import question_claim
    claim = question()
    before = deepcopy(claim)
    assert question_claim(claim, "alignment") == dict(question="Which movement controls?",
        recommended_answer="Use arrow keys", risk_level="low")
    assert claim == before
    assert question_claim(dict(verdict="ALIGNED", state_updates={}), "alignment") is None
    for field in ("answer_text", "resolved_by", "automatic_eligible"):
        forged = deepcopy(claim)
        forged["state_updates"][field] = "injected"
        with pytest.raises(ValueError): question_claim(forged, "alignment")


@pytest.mark.parametrize("mode,recommendation,risk,want", [
    ("guided", "Use arrow keys", "low", "awaiting_human"),
    ("semi", "Use arrow keys", "low", "awaiting_human"),
    ("banzai", "Use arrow keys", "low", "pending"),
    ("banzai", None, None, "awaiting_human"),
    ("banzai", "Use arrow keys", "high", "awaiting_human"),
])
def test_alignment_question_binds_native_pending_decision(checkpoint_case, mode, recommendation, risk, want):
    from harness import discovery_assessment as assessment
    from harness.blocked_decision import build_blocked_decision_v3
    from harness.human_input import select_initial_decision_status
    from harness.phase_graph import load_workspace_phase_graph
    root = checkpoint_case[0]
    from tests.unit.test_managed_checkpoint_assess import install_commander
    install_commander(root)
    registry = load_workspace_phase_graph(root)[0].human_input_policy_registry()
    request = registry.prepare(source_kind="provider_escalation", producer_id="phase2-tracker-alignment",
        phase_id="phase2-tracker-alignment", reason_code="human_clarification_required",
        question="Which movement controls?", recommended_answer=recommendation, risk_level=risk,
        source_state_revision=12)
    policy = registry.lookup("provider_escalation", "phase2-tracker-alignment", "human_clarification_required")
    assert select_initial_decision_status(mode, policy, request) == want
    decision = build_blocked_decision_v3(prepared=request, decision_id="dec-alignment-question", status=want,
        autonomy_mode=mode, created_at="2026-09-18T00:00:00+00:00")
    state = dict(phase="phase2-tracker-alignment", autonomy_mode=mode, blocked_decision=decision)
    claim = question()
    if recommendation is None:
        claim["state_updates"].pop("escalation_recommended_answer")
        claim["state_updates"].pop("escalation_risk_level")
    else:
        claim["state_updates"]["escalation_risk_level"] = risk
    check = getattr(assessment, "require_alignment_question", None)
    assert callable(check), "Alignment completion must bind the native sealed question"
    before = deepcopy(state)
    check(root, state, claim)
    for key, value in (("question", "Different question"), ("risk_level", "critical"),
            ("recommended_answer", "Use WASD"), ("automatic_eligible", not decision["automatic_eligible"]),
            ("attempts", 1), ("attempts", False), ("answer_text", "Self-approved"),
            ("source_phase", "phase1-tracker"), ("recommendation_authority", "controller_evidence")):
        changed = deepcopy(state)
        changed["blocked_decision"][key] = value
        with pytest.raises(ValueError): check(root, changed, claim)
    assert state == before


def assert_question_publication(case, provider):
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    executor = AlignmentExecutor(provider, routing=question())
    ctrl = controller(case, executor)
    with PhaseAExecutionLock.acquire(root, "test-alignment-question"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-alignment-question"):
            package = prepare_discovery_publication(root, store, executor, completion_id=uuid4().hex, producer="alignment")
    binding = decode_binding(envelope(package), state=before)
    assert binding.producer == "alignment" and not binding.resolution_publication
    assert binding.candidate["routing"] == question()
    assert binding.request.operations == () and binding.candidate["history"] == binding.source["history"]
    assert {op.target for op in package.sources.publication.operations} == {
        "specs/game/intent-alignment-check.md", "specs/game/spec-artifact-graph.json"}
    assert store.load() == before and identity.identity_history(spec_id="game") == history
    assert identity.pending_identity_publication(spec_id="game") is None and not executor.calls
    return package


def assert_question_handoff(case, package, provider):
    from harness.human_input import select_initial_decision_status, HumanInputPolicyError
    from harness.squad_provider import SquadAgentResult
    from harness.squad_state import StateAdvanceError
    from harness.state_transaction_namespace import SPEC_STEP_PUBLICATION_PLAN_KEY
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    documents = {p.name: p.read_bytes() for p in (root / "specs/game").iterdir() if p.is_file()}
    executor = AlignmentExecutor(provider, routing=question())
    ctrl = controller(case, executor)
    node = ctrl._graph.get("phase2-tracker-alignment")
    completion_id = json.loads(package.request.recovery_payload)["completion_id"]
    with PhaseAExecutionLock.acquire(root, "test-alignment-question"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-alignment-question"):
            snapshot = store.capture_routing_snapshot(expected_phase=node.id)
            for target in ("phase3-specialists", "phase2-intent-alignment-structural", "phase1-what", "done"):
                with pytest.raises(StateAdvanceError):
                    ctrl._prepare_spec_step_effects(from_phase=node.id, to_phase=target,
                        snapshot=snapshot, manual_phase_run=False, conditional_skip=False, record_completion=True,
                        publication_marker=package.publication.marker.to_dict(), completion_id=completion_id,
                        managed_discovery_request=encode_publication_request(package.request))
            result = SquadAgentResult(exit_code=0, echelon_result=question(), raw_output="", duration_ms=0, timed_out=False)
            prepared = ctrl._prepare_phase_result(node, result, snapshot)
            routed = ctrl._construct_routing_decision_or_block(node, prepared, snapshot,
                additional_state_updates={SPEC_STEP_PUBLICATION_PLAN_KEY: package.publication.marker.to_dict()},
                managed_discovery_request=encode_publication_request(package.request), completion_id=completion_id,
                token_usage_delta=21)
            assert routed is not None, store.load()
            human = routed.human_input or ctrl._prepare_provider_human_input(node, prepared, snapshot)
            assert human is not None
            def interrupt(*args, **kwargs): raise Interrupted()
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(PreparedSquadPublication, "_promote", interrupt)
                with pytest.raises(Interrupted):
                    ctrl._advance_prepared_result_or_block(node, routed.decision, prepared_publication=package.publication,
                        human_input=human, human_input_initial_status=select_initial_decision_status(
                            before["autonomy_mode"], ctrl._validate_prepared_human_input(human), human))
    pending = store.load()
    from harness.spec_step import load_prepared_spec_step
    step = load_prepared_spec_step(
        store.squad_dir,
        pending["pending_spec_step"],
    )
    projected = step.intent.final_state
    decision = deepcopy(projected["blocked_decision"])
    assert pending["phase"] == node.id and pending["status"] == "running"
    assert pending["last_dispatch"] == before["last_dispatch"]
    assert "pending_spec_step" in pending
    assert pending["token_usage"] == before["token_usage"]
    assert projected["token_usage"] == before["token_usage"] + 21
    assert decision["question"] == "Which movement controls?" and decision["answer_text"] is None
    assert decision["source_phase"] == node.id and decision["resolution_handler"] == "clarification_resume"
    assert decision["status"] == ("pending" if before["autonomy_mode"] == "banzai" else "awaiting_human")
    assert "intent_alignment_verdict" not in projected
    assert {p.name: p.read_bytes() for p in (root / "specs/game").iterdir() if p.is_file()} == documents
    assert_question_recovery(case, package, provider)
    after = store.load()
    assert after["blocked_decision"] == decision and after["phase"] == node.id and after["status"] == "blocked"
    assert after["token_usage"] == before["token_usage"] + 21
    assert after["phase_dispatch_counts"] == before["phase_dispatch_counts"]
    for key in ("iteration", "max_iterations", "feasibility_verdict", "feasibility_structural_attempts",
            "structural_action", "governance_gate_exhausted"):
        assert (key in after, after.get(key)) == (key in before, before.get(key))
    for name, content in documents.items():
        if name not in {"intent-alignment-check.md", "spec-artifact-graph.json"}:
            assert (root / "specs/game" / name).read_bytes() == content
    assert identity.identity_history(spec_id="game") == history
    # Stop at the pending question. The answer-application suite exercises the
    # newly admitted public path separately, including COMMANDER replay.
    assert controller(case, executor)._managed_alignment_human_input(after)
    assert store.load() == after and not executor.calls


def assert_question_recovery(case, package, provider):
    from harness.element_identity_store import IdentityStore
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    executor = AlignmentExecutor(provider, routing=question())
    ctrl = controller(case, executor)
    from tests.unit.test_discovery_completion import pending_spec_companion
    before, completion, _ = pending_spec_companion(ctrl)
    assert authenticate(root, store.squad_dir, before, completion).candidate["routing"] == question()
    for key, value in (("question", "Forged question"), ("recommended_answer", "Use WASD"),
            ("risk_level", "critical"), ("source_phase", "phase1-tracker")):
        forged = deepcopy(before)
        forged["blocked_decision"][key] = value
        with pytest.raises(CompletionError): authenticate(root, store.squad_dir, forged, completion)
    forged = {**before, "intent_alignment_verdict": "ALIGNED"}
    with pytest.raises(CompletionError): authenticate(root, store.squad_dir, forged, completion)
    for key in ("iteration", "max_iterations", "feasibility_structural_attempts"):
        forged = {**before, key: float(before[key])}
        with pytest.raises(CompletionError): authenticate(root, store.squad_dir, forged, completion)
    promote = PreparedSquadPublication._promote
    positions = []
    def partial(*args, **kwargs):
        def fault(position):
            if position == 1:
                positions.append(position)
                raise Interrupted()
        return promote(*args, **{**kwargs, "fault_hook": fault})
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(PreparedSquadPublication, "_promote", partial)
        with pytest.raises(Interrupted): drain(controller(case, executor))
    assert positions == [1]
    apply = IdentityStore.apply_identity_publication
    def applied(*args, **kwargs):
        apply(*args, **kwargs)
        raise Interrupted()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(IdentityStore, "apply_identity_publication", applied)
        with pytest.raises(Interrupted): drain(controller(case, executor))
    assert drain(controller(case, executor)).recovered, store.load()
    after = store.load()
    assert after["last_dispatch"]["post_dispatch_complete"] is True
    assert after["blocked_decision"] == before["blocked_decision"]
    assert after["token_usage"] == before["token_usage"] and not executor.calls
    assert identity.identity_history(spec_id="game") == history
    assert identity.identity_publication(spec_id="game", operation_id="discovery-completion-" + completion.marker.completion_id)["state"] == "released"
    for op in package.sources.publication.operations:
        assert (root / op.target).read_bytes() == op.postimage_bytes
    assert not after["phase_dispatch_counts"].get("phase3-specialists")
    assert identity.pending_identity_publication(spec_id="game") is None
    drain(controller(case, executor))
    assert store.load() == after and not executor.calls


@pytest.mark.parametrize("provider,mode,enabled,policy", [
    ("codex", "guided", False, "disabled"), ("claude", "banzai", True, "warn")])
def test_alignment_question_reaches_native_pending_decision(checkpoint_case, provider, mode, enabled, policy):
    complete_strategy(checkpoint_case, provider, mode, enabled, policy)
    assert_reviewed_alignment(checkpoint_case, provider, routing=question())
    assert_question_handoff(checkpoint_case, assert_question_publication(checkpoint_case, provider), provider)
