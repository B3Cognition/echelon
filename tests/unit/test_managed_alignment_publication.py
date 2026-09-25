"""Ordinary alignment publishes only its report and enters native structural gating."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
from harness.discovery_completion import decode_binding, _json, _hash
from harness.discovery_publication import prepare_discovery_publication
from harness.element_identity_publication import encode_publication_request
from harness.squad_completion import CompletionError
from tests.unit.test_discovery_completion import controller
from tests.unit.test_managed_feasibility_publication import envelope
from tests.unit.test_managed_alignment_execution import (
    case, enrolled, turn_prepared, prepared, checkpoint_case, AlignmentExecutor,
    test_released_strategy_authorizes_reviewed_alignment as complete_review,
)


def assert_alignment_publication(case, provider, verdict="ALIGNED"):
    root, store, identity, _ = case
    executor = AlignmentExecutor(provider, verdict)
    ctrl = controller(case, executor)
    before, history = store.load(), identity.identity_history(spec_id="game")
    documents = {p.name: p.read_bytes() for p in (root / "specs/game").iterdir() if p.is_file()}
    with PhaseAExecutionLock.acquire(root, "test-alignment-publication"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-alignment-publication"):
            package = prepare_discovery_publication(root, store, executor, completion_id="8" * 32, producer="alignment")
            recovery = json.loads(package.request.recovery_payload)
            assert recovery["version"] == 36 and recovery["producer"] == "alignment"
            binding = decode_binding(envelope(package), completion_id="8" * 32, state=before)
            assert binding.candidate["routing"] == dict(verdict=verdict, state_updates={})
            assert binding.request.operations == () and binding.candidate["history"] == binding.source["history"]
            assert binding.recovery["resolution"] is None and binding.recovery["predecessor"] is None
            writes = {op.target: op.postimage_bytes for op in package.sources.publication.operations}
            assert set(writes) == {"specs/game/intent-alignment-check.md", "specs/game/spec-artifact-graph.json"}
            assert writes["specs/game/spec-artifact-graph.json"] == package.graph
            assert not executor.calls
            assert store.load() == before and identity.identity_history(spec_id="game") == history
            assert {p.name: p.read_bytes() for p in (root / "specs/game").iterdir() if p.is_file()} == documents
            assert identity.pending_identity_publication(spec_id="game") is None
    return package


def assert_closed_alignment_binding(case, package):
    before = case[1].load()
    for damage in ("version", "producer", "predecessor", "resolution", "scope", "routing", "review", "identity", "editable", "source", "question"):
        recovery = json.loads(package.request.recovery_payload)
        if damage == "version": recovery["version"] = 31
        elif damage == "producer": recovery["producer"] = "feasibility"
        elif damage == "predecessor": recovery["predecessor"] = "alignment-" + "a" * 32
        elif damage == "resolution": recovery["resolution"] = {}
        elif damage == "editable": recovery["operation"]["binding"]["editable_revisions"] = [["AC-000001", 1]]
        elif damage == "source": recovery["source_completion"]["dispatch_id"] = "0" * 32
        else:
            candidate = json.loads(recovery["candidate_inputs"])
            if damage == "question":
                candidate["routing"] = dict(verdict="STOP_AND_ASK", state_updates=dict(status="blocked", blocked_reason="human_clarification_required", escalation_question="Approve scope drift?"))
                recovery["review"]["routing"] = deepcopy(candidate["routing"])
            elif damage == "scope": candidate["artifacts"]["spec.md"] = "Unauthorized replacement"
            elif damage == "routing": candidate["routing"]["state_updates"]["feasibility_structural_attempts"] = 0
            elif damage == "review": recovery["review"]["routing"]["verdict"] = "PASS"
            else: candidate["proposal"]["new_subjects"] = [{"kind": "AC", "key": "extra"}]
            recovery["candidate_inputs"] = _json(candidate)
            recovery["candidate_sha256"] = _hash(candidate)
            recovery["operation"]["attempts"][-1]["result"]["candidate_sha256"] = _hash(candidate)
        request = replace(package.request, recovery_payload=_json(recovery))
        with pytest.raises(CompletionError):
            # A question is now a valid first-entry shape, but this accepted
            # ordinary operation did not ask it. Bind that forgery to state.
            decode_binding(envelope(package, request), completion_id="8" * 32,
                state=before if damage == "question" else None)
    assert case[1].load() == before


def assert_alignment_handoff(case, package, provider, verdict="ALIGNED"):
    from harness.squad_provider import SquadAgentResult
    from tests.unit.test_discovery_completion import controller
    from harness.state_transaction_namespace import SPEC_STEP_PUBLICATION_PLAN_KEY
    from harness.squad_publication import PreparedSquadPublication
    from harness.squad_state import StateAdvanceError
    from tests.unit.test_discovery_turns import Interrupted
    root, store, identity, _ = case
    executor = AlignmentExecutor(provider, verdict)
    ctrl = controller(case, executor)
    before, history = store.load(), identity.identity_history(spec_id="game")
    completion_id = json.loads(package.request.recovery_payload)["completion_id"]
    documents = {p.name: p.read_bytes() for p in (root / "specs/game").iterdir() if p.is_file()}
    node = ctrl._graph.get("phase2-tracker-alignment")
    with PhaseAExecutionLock.acquire(root, "test-alignment-handoff"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-alignment-handoff"):
            snapshot = store.capture_routing_snapshot(expected_phase=node.id)
            for destination in ("phase3-specialists", "done", "phase2-feasibility-structural", "phase1-what"):
                with pytest.raises(StateAdvanceError):
                    ctrl._prepare_spec_step_effects(from_phase=node.id, to_phase=destination,
                        snapshot=snapshot, manual_phase_run=False, conditional_skip=False, record_completion=True,
                        publication_marker=package.publication.marker.to_dict(), completion_id=completion_id,
                        managed_discovery_request=encode_publication_request(package.request))
            assert store.load() == before
            result = SquadAgentResult(exit_code=0, echelon_result=dict(verdict=verdict, state_updates={}),
                raw_output="", duration_ms=0, timed_out=False)
            prepared_result = ctrl._prepare_phase_result(node, result, snapshot)
            routing = ctrl._construct_routing_decision_or_block(node, prepared_result, snapshot,
                additional_state_updates={SPEC_STEP_PUBLICATION_PLAN_KEY: package.publication.marker.to_dict()},
                managed_discovery_request=encode_publication_request(package.request), completion_id=completion_id,
                token_usage_delta=21)
            assert routing is not None, store.load()
            def before_promotion(*args, **kwargs): raise Interrupted()
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(PreparedSquadPublication, "_promote", before_promotion)
                with pytest.raises(Interrupted):
                    ctrl._advance_prepared_result_or_block(node, routing.decision, prepared_publication=package.publication)
    pending = store.load()
    assert pending["last_dispatch"] == before["last_dispatch"]
    assert "pending_spec_step" in pending
    assert {p.name: p.read_bytes() for p in (root / "specs/game").iterdir() if p.is_file()} == documents
    assert pending["token_usage"] == before["token_usage"]
    from harness.spec_step import load_prepared_spec_step
    sealed_step = load_prepared_spec_step(
        store.squad_dir,
        pending["pending_spec_step"],
    )
    assert (
        sealed_step.intent.final_state["token_usage"]
        == before["token_usage"] + 21
    )
    assert store.load()["phase_dispatch_counts"] == before["phase_dispatch_counts"]
    assert identity.identity_history(spec_id="game") == history
    assert_alignment_pending_recovery(case, package, provider, verdict)


def assert_alignment_pending_recovery(case, package, provider, verdict="ALIGNED"):
    """Recover the actual pending completion, including a retained failure diagnostic."""
    from harness.discovery_completion import authenticate
    from harness.squad_publication import PreparedSquadPublication
    from harness.element_identity_store import IdentityStore
    from tests.unit.test_discovery_completion import controller, drain
    from tests.unit.test_discovery_turns import Interrupted
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    documents = {p.name: p.read_bytes() for p in (root / "specs/game").iterdir() if p.is_file()}
    executor = AlignmentExecutor(provider, verdict)
    ctrl = controller(case, executor)
    completion_id = json.loads(package.request.recovery_payload)["completion_id"]
    promote = PreparedSquadPublication._promote
    from tests.unit.test_discovery_completion import pending_spec_companion
    actual_pending = store.load()
    pending, completion, step = pending_spec_companion(ctrl)
    assert authenticate(root, store.squad_dir, pending, completion).producer == "alignment"
    changed = deepcopy(pending)
    changed["intent_alignment_verdict"] = "DRIFT" if verdict == "ALIGNED" else "ALIGNED"
    with pytest.raises(CompletionError): authenticate(root, store.squad_dir, changed, completion)
    for key in ("iteration", "max_iterations", "feasibility_structural_attempts", "feasibility_verdict", "structural_action"):
        changed = deepcopy(pending)
        changed[key] = changed[key] + 1 if type(changed[key]) is int else "forged"
        with pytest.raises(CompletionError): authenticate(root, store.squad_dir, changed, completion)
    for key in ("iteration", "max_iterations", "feasibility_structural_attempts"):
        changed = deepcopy(pending)
        changed[key] = float(changed[key])
        with pytest.raises(CompletionError): authenticate(root, store.squad_dir, changed, completion)
    if "intent_alignment_check_structural_attempts" in before:
        for value in (0, True, float(before["intent_alignment_check_structural_attempts"]), 999):
            changed = deepcopy(pending)
            changed["intent_alignment_check_structural_attempts"] = value
            with pytest.raises(CompletionError): authenticate(root, store.squad_dir, changed, completion)
        for key, value in (("intent_alignment_check_structural_pass", False),
                ("intent_alignment_check_structural_findings", 1),
                ("intent_alignment_check_structural_report", "stale-report.json")):
            changed = deepcopy(pending)
            changed[key] = value
            with pytest.raises(CompletionError): authenticate(root, store.squad_dir, changed, completion)
    assert store.load() == actual_pending
    if json.loads(package.request.recovery_payload)["version"] == 42:
        from tests.unit.test_managed_alignment_answer_publication import assert_answer_handoff_refusals
        assert_answer_handoff_refusals(case, completion)
    if json.loads(package.request.recovery_payload)["version"] in {38, 42} and step.marker.failure is None:
        store.record_spec_step_failure(
            step.marker,
            effect=step.marker.cursor,
            code="intent_mismatch",
        )
        assert store.load()["blocked_reason"] == "spec_step_pending"
    interruptions = []
    def after_one_promotion(*args, **kwargs):
        def interrupt(position):
            if position == 1:
                interruptions.append(position)
                raise Interrupted()
        return promote(*args, **{**kwargs, "fault_hook": interrupt})
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(PreparedSquadPublication, "_promote", after_one_promotion)
        with pytest.raises(Interrupted): drain(controller(case, executor))
    assert interruptions == [1] and len(package.sources.publication.operations) == 2
    apply = IdentityStore.apply_identity_publication
    def after_identity_apply(*args, **kwargs):
        apply(*args, **kwargs)
        raise Interrupted()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(IdentityStore, "apply_identity_publication", after_identity_apply)
        with pytest.raises(Interrupted): drain(controller(case, executor))
    assert identity.pending_identity_publication(spec_id="game")["state"] == "applied"
    assert drain(controller(case, executor)).recovered, store.load()
    after = store.load()
    assert after["phase"] == "phase2-intent-alignment-structural" and after["last_dispatch"]["post_dispatch_complete"] is True
    assert after["status"] == "running" and "spec_step_effect_failure" not in after
    assert after["intent_alignment_verdict"] == verdict
    assert "governance_gate_exhausted" not in after and "blocked_reason" not in after
    assert after["token_usage"] == before["token_usage"] + 21
    assert after["phase_dispatch_counts"] == before["phase_dispatch_counts"]
    for key in ("iteration", "max_iterations", "feasibility_verdict", "feasibility_structural_attempts"):
        assert after[key] == before[key]
    if "intent_alignment_check_structural_attempts" in before:
        assert after["intent_alignment_check_structural_attempts"] == before["intent_alignment_check_structural_attempts"]
    for key in ("intent_alignment_check_structural_pass", "intent_alignment_check_structural_report",
            "intent_alignment_check_structural_findings"):
        assert key not in after
    assert not after["phase_dispatch_counts"].get("phase2-intent-alignment-structural")
    assert not after["phase_dispatch_counts"].get("phase3-specialists")
    assert identity.identity_history(spec_id="game") == history
    assert identity.identity_publication(spec_id="game", operation_id="discovery-completion-" + completion_id)["state"] == "released"
    for op in package.sources.publication.operations:
        assert (root / op.target).read_bytes() == op.postimage_bytes
    for name, content in documents.items():
        if name not in {"intent-alignment-check.md", "spec-artifact-graph.json"}:
            assert (root / "specs/game" / name).read_bytes() == content
    assert not package.publication._transaction_root.exists()
    assert identity.pending_identity_publication(spec_id="game") is None and not executor.calls
    drain(controller(case, executor))
    assert store.load() == after and not executor.calls


@pytest.mark.parametrize("provider,mode,enabled,policy", [
    ("codex", "guided", False, "disabled"), ("claude", "banzai", True, "warn")])
def test_alignment_publishes_and_hands_off_without_running_structural_gate(checkpoint_case, provider, mode, enabled, policy):
    complete_review(checkpoint_case, provider, mode, enabled, policy)
    verdict = "ALIGNED" if provider == "codex" else "DRIFT"
    package = assert_alignment_publication(checkpoint_case, provider, verdict)
    assert_closed_alignment_binding(checkpoint_case, package)
    assert_alignment_handoff(checkpoint_case, package, provider, verdict)
