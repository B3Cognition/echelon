"""A real reviewed feasibility publication supplies the deterministic gate."""
from dataclasses import replace
import json

import pytest

from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
from harness.discovery_completion import decode_binding
from harness.element_identity_publication import encode_publication_request
from harness.squad_completion import CompletionError
from tests.unit.test_managed_feasibility_publication import (
    case, enrolled, turn_prepared, prepared, checkpoint_case, envelope,
    test_real_review_seals_only_feasibility_outputs as publish_review,
)
from tests.unit.test_managed_feasibility_rounds import FeasibilityExecutor


def assert_gate_publication(case, *, passed=False, previous_attempts=0, action=None,
        attempts=None, completion_id="c" * 32, has_report=True):
    from harness.discovery_assessment_gate import prepare_feasibility_gate_publication
    root, store, identity, _ = case
    before = store.load()
    history = identity.identity_history(spec_id="game")
    documents = {p.name: p.read_bytes() for p in (root / "specs/game").iterdir() if p.is_file()}
    with PhaseAExecutionLock.acquire(root, "test-feasibility-gate"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-feasibility-gate"):
            package = prepare_feasibility_gate_publication(root, store, completion_id=completion_id,
                max_iterations=before["max_iterations"])
    binding = decode_binding(envelope(package), state=before)
    assert binding.producer == "feasibility_gate" and binding.recovery["version"] == (34 if previous_attempts else 32)
    assert binding.request.operations == () and binding.source["history"] == binding.candidate["history"]
    assert binding.recovery["previous_attempts"] == previous_attempts
    updates = binding.recovery["result"]["state_updates"]
    assert updates["structural_action"] == (action or ("proceed" if passed else "repair"))
    assert updates["feasibility_structural_attempts"] == (int(not passed) if attempts is None else attempts)
    writes = {op.target: op.postimage_bytes for op in package.sources.publication.operations}
    expected_writes = {"specs/game/spec-artifact-graph.json"}
    if has_report:
        expected_writes.add("specs/game/feasibility-structural-report.json")
        report = json.loads(writes["specs/game/feasibility-structural-report.json"])
        assert report["ok"] is passed and bool(report["findings"]) is not passed
    else:
        assert "feasibility_structural_report" not in updates
        assert updates["feasibility_structural_findings"] == 0
    assert set(writes) == expected_writes
    assert store.load() == before and identity.identity_history(spec_id="game") == history
    assert {p.name: p.read_bytes() for p in (root / "specs/game").iterdir() if p.is_file()} == documents
    for damage in ("counter", "result", "typed_result", "verdict", "source", "extra", "report", "template"):
        recovery = json.loads(package.request.recovery_payload)
        if damage == "counter": recovery["previous_attempts"] = 0 if previous_attempts else 1
        elif damage == "result": recovery["result"]["state_updates"]["structural_action"] = "repair" if passed else "proceed"
        elif damage == "typed_result": recovery["result"]["state_updates"]["feasibility_structural_attempts"] = not passed
        elif damage == "verdict": recovery["routing_state"]["feasibility_verdict"] = "KILL"
        elif damage == "source": recovery["source_completion"]["dispatch_id"] = "0" * 32
        elif damage == "extra": recovery["retry_authorized"] = True
        elif damage == "report": recovery["config"]["governance"]["artifacts"]["feasibility"]["report"] = "spec.md"
        else: recovery["config"]["governance"]["artifacts"]["feasibility"]["template"] = "other.md"
        request = replace(package.request, recovery_payload=json.dumps(recovery,
            sort_keys=True, separators=(",", ":"), ensure_ascii=True))
        with pytest.raises(CompletionError):
            decode_binding(envelope(package, request), state=before)
    return package


def assert_gate_handoff(case, package, provider, *, passed=False, action=None, attempts=None, has_report=True):
    from tests.unit.test_discovery_completion import controller, drain
    from tests.unit.test_discovery_turns import Interrupted
    from harness.squad_publication import PreparedSquadPublication
    from harness.element_identity_store import IdentityStore
    from harness.squad_state import StateAdvanceError
    from harness.state_transaction_namespace import SPEC_STEP_PUBLICATION_PLAN_KEY
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    executor = FeasibilityExecutor(provider)
    ctrl = controller(case, executor)
    node = ctrl._graph.get("phase2-feasibility-structural")
    completion_id = json.loads(package.request.recovery_payload)["completion_id"]
    action = action or ("proceed" if passed else "repair")
    destination = {"repair": "phase2-decide", "proceed": "phase2-strategic-overview",
        "proceed_with_warning": "phase2-strategic-overview", "block": "terminal-blocked"}[action]
    with PhaseAExecutionLock.acquire(root, "test-feasibility-gate"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-feasibility-gate"):
            snapshot = store.capture_routing_snapshot(expected_phase=node.id)
            for route in ({"phase2-decide", "phase2-strategic-overview", "phase3-specialists", "done"} - {destination}):
                with pytest.raises(StateAdvanceError):
                    ctrl._prepare_spec_step_effects(from_phase=node.id, to_phase=route, snapshot=snapshot,
                        manual_phase_run=False, conditional_skip=False, record_completion=True,
                        publication_marker=package.publication.marker.to_dict(), completion_id=completion_id,
                        managed_discovery_request=encode_publication_request(package.request))
            prepared_result = ctrl._prepare_phase_result(node, package.result, snapshot)
            routing = ctrl._construct_routing_decision_or_block(node, prepared_result, snapshot,
                additional_state_updates={SPEC_STEP_PUBLICATION_PLAN_KEY: package.publication.marker.to_dict()},
                managed_discovery_request=encode_publication_request(package.request), completion_id=completion_id)
            assert routing is not None, store.load()
            promote = PreparedSquadPublication._promote
            interruptions = []
            def interrupted(*args, **kwargs):
                def fault(position):
                    if position == 1:
                        interruptions.append(position)
                        raise Interrupted()
                return promote(*args, **{**kwargs, "fault_hook": fault})
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(PreparedSquadPublication, "_promote", interrupted)
                with pytest.raises(Interrupted):
                    ctrl._advance_prepared_result_or_block(node, routing.decision, prepared_publication=package.publication)
    pending = store.load()
    assert pending["last_dispatch"] == before["last_dispatch"]
    assert "pending_spec_step" in pending
    writes = package.sources.publication.operations
    # Gate publication may leave graph bytes unchanged. The real hook proves
    # partial report/graph promotion, or completion of the sole bypass write.
    assert interruptions == [1] and len(writes) == (2 if has_report else 1)
    apply = IdentityStore.apply_identity_publication
    def after_apply(*args, **kwargs):
        apply(*args, **kwargs)
        raise Interrupted()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(IdentityStore, "apply_identity_publication", after_apply)
        with pytest.raises(Interrupted):
            drain(controller(case, executor))
    assert identity.pending_identity_publication(spec_id="game")["state"] == "applied"
    assert drain(controller(case, executor)).recovered, store.load()
    after = store.load()
    assert after["phase"] == destination and after["status"] == ("blocked" if action == "block" else "running")
    assert after["iteration"] == before["iteration"] + int(action == "repair")
    assert after["feasibility_structural_attempts"] == (int(not passed) if attempts is None else attempts)
    assert after["structural_action"] == action
    assert after["token_usage"] == before["token_usage"] and not executor.calls
    assert after["phase_dispatch_counts"] == before["phase_dispatch_counts"]
    assert identity.identity_history(spec_id="game") == history
    assert identity.identity_publication(spec_id="game", operation_id="discovery-completion-" + completion_id)["state"] == "released"
    assert all((root / op.target).read_bytes() == op.postimage_bytes for op in writes)
    drain(controller(case, executor))
    assert store.load() == after and not executor.calls
    if not passed:
        from tests.unit.test_managed_feasibility import parent
        # The old approval cannot be reused as authority for a structural retry.
        with pytest.raises((ValueError, CompletionError)):
            parent(case)
        assert store.load() == after and not executor.calls


@pytest.mark.parametrize("provider,mode,enabled", [("codex", "guided", False), ("claude", "banzai", True)])
def test_reviewed_feasibility_gate_uses_guarded_report_handoff(checkpoint_case, provider, mode, enabled):
    publish_review(checkpoint_case, provider, mode, enabled)
    package = assert_gate_publication(checkpoint_case)
    assert_gate_handoff(checkpoint_case, package, provider)


def test_valid_claude_banzai_feasibility_reaches_strategy_without_dispatch(checkpoint_case):
    from tests.unit.test_managed_checkpoint_assess import test_managed_checkpoint_uses_native_policy_and_stops_before_phase2 as checkpoint
    from tests.unit.test_managed_feasibility import assert_reviewed_feasibility
    from tests.unit.test_managed_feasibility_publication import assert_feasibility_publication, assert_feasibility_handoff
    from tests.unit.test_captured_governance_gate import FEASIBILITY
    checkpoint(checkpoint_case, "claude", "banzai", True, "approve")
    assert_reviewed_feasibility(checkpoint_case, "claude", feasibility_text=FEASIBILITY)
    author = assert_feasibility_publication(checkpoint_case, "claude")
    assert_feasibility_handoff(checkpoint_case, author, "claude")
    gate = assert_gate_publication(checkpoint_case, passed=True)
    assert_gate_handoff(checkpoint_case, gate, "claude", passed=True)
