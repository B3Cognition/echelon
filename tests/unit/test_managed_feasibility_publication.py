"""Feasibility hands reviewed artifacts to the existing guarded completion owner."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
from harness.discovery_completion import decode_binding
from harness.discovery_publication import prepare_discovery_publication
from harness.element_identity_publication import encode_publication_request
from harness.squad_completion import CompletionError
from tests.unit.test_managed_feasibility import (
    case, enrolled, turn_prepared, prepared, checkpoint_case,
    test_feasibility_parent_is_real_native_checkpoint as complete_review,
)
from tests.unit.test_managed_feasibility_rounds import FeasibilityExecutor


def envelope(package, request=None):
    return dict(kind="external", marker=package.publication.marker.to_dict(),
        managed_discovery=dict(version=1, request=encode_publication_request(request or package.request)))


def assert_released_approval_is_historical(case):
    """Historical proof survives advancement; live resolution effects stay strict."""
    from harness.discovery_completion import _retained_input_projection
    from harness.discovery_spec import clarification_source
    root, store, identity, _ = case
    before = store.load()
    advanced = deepcopy(before)
    advanced["phase"] = "phase2-feasibility-structural"
    source = clarification_source(before["last_human_input_completion"])
    arguments = dict(operation_id="discovery-completion-" + source["dispatch_id"], source=source,
        require_checkpoint=False, required_origin="resolution", required_route=("checkpoint-assess", "phase2-decide"))
    binding, _, _ = _retained_input_projection(root, store.squad_dir, advanced, identity, **arguments)
    assert binding.producer == "checkpoint" and binding.candidate["route"] == "phase2-decide"
    publication = dict(kind="external", marker=binding.sources.publication.marker.to_dict(),
        managed_discovery=dict(version=1, request=encode_publication_request(binding.request)))
    with pytest.raises(CompletionError):
        decode_binding(publication, completion_id=source["dispatch_id"], state=advanced)
    for damage in ("receipt", "identity", "bootstrap"):
        changed = deepcopy(advanced)
        if damage == "receipt": changed["last_human_input_completion"]["intent_sha256"] = "0" * 64
        elif damage == "identity": changed["managed_identity"]["context_id"] = "foreign"
        else: changed["managed_discovery_bootstrap"]["selection"]["spec_id"] = "foreign"
        with pytest.raises((ValueError, CompletionError)):
            _retained_input_projection(root, store.squad_dir, changed, identity, **arguments)
    assert store.load() == before


def assert_feasibility_publication(case, provider, *, completion_id="e" * 32):
    root, store, identity, _ = case
    executor = FeasibilityExecutor(provider)
    before = store.load()
    history = identity.identity_history(spec_id="game")
    source_bytes = {p.name: p.read_bytes() for p in (root / "specs/game").iterdir() if p.is_file()}
    with PhaseAExecutionLock.acquire(root, "test-feasibility-publication"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-feasibility-publication"):
            package = prepare_discovery_publication(root, store, executor,
                completion_id=completion_id, producer="feasibility")
            recovery = json.loads(package.request.recovery_payload)
            assert recovery["version"] == 31 and recovery["producer"] == "feasibility"
            binding = decode_binding(envelope(package), completion_id=completion_id, state=before)
            assert binding.candidate["routing"] == dict(verdict="PASS", state_updates={})
            assert binding.request.operations == () and binding.candidate["history"] == binding.source["history"]
            assert binding.recovery["resolution"] == dict(decision=before["blocked_decision"],
                completion=before["last_human_input_completion"])
            writes = {op.target: op.postimage_bytes for op in package.sources.publication.operations}
            assert set(writes) == {"specs/game/" + name for name in (
                "feasibility.md", "prioritization.md", "estimates.md", "mvp-scope.md", "spec-artifact-graph.json")}
            assert writes["specs/game/spec-artifact-graph.json"] == package.graph
            assert not executor.calls
            assert store.load() == before and identity.identity_history(spec_id="game") == history
            assert {p.name: p.read_bytes() for p in (root / "specs/game").iterdir() if p.is_file()} == source_bytes
            assert identity.pending_identity_publication(spec_id="game") is None
    return package


def assert_closed_feasibility_binding(case, package):
    """No detached approval, identity edits or borrowed producer contract."""
    state = case[1].load()
    completion_id = json.loads(package.request.recovery_payload)["completion_id"]
    for damage in ("version", "producer", "approval", "receipt", "predecessor", "resolution", "scope", "routing", "review", "identity"):
        recovery = json.loads(package.request.recovery_payload)
        if damage == "version": recovery["version"] = 28
        elif damage == "producer": recovery["producer"] = "lexicon"
        elif damage == "approval": recovery["resolution"]["decision"]["selected_option_id"] = "reject"
        elif damage == "receipt": recovery["resolution"]["completion"]["intent_sha256"] = "0" * 64
        elif damage == "predecessor": recovery["predecessor"] = "feasibility-" + "a" * 32
        elif damage == "resolution": recovery["resolution"] = None
        else:
            from harness.discovery_completion import _json, _hash
            candidate = json.loads(recovery["candidate_inputs"])
            if damage == "scope": candidate["artifacts"]["spec.md"] = "An unauthorized replacement"
            elif damage == "routing": candidate["routing"]["state_updates"]["feasibility_structural_pass"] = True
            elif damage == "review": recovery["review"]["routing"]["verdict"] = "DEFER"
            else: candidate["proposal"]["new_subjects"] = [{"kind": "AC", "local_key": "extra"}]
            recovery["candidate_inputs"] = _json(candidate)
            recovery["candidate_sha256"] = _hash(candidate)
            recovery["operation"]["attempts"][-1]["result"]["candidate_sha256"] = _hash(candidate)
        request = replace(package.request, recovery_payload=json.dumps(recovery,
            sort_keys=True, separators=(",", ":"), ensure_ascii=True))
        # Shape-only decoding must reject even without protected live state.
        with pytest.raises(CompletionError):
            decode_binding(envelope(package, request), completion_id=completion_id)
    assert case[1].load() == state


def assert_structural_gate_cannot_be_skipped(case, package, provider):
    from tests.unit.test_discovery_completion import controller
    from harness.squad_state import StateAdvanceError
    ctrl = controller(case, FeasibilityExecutor(provider))
    completion_id = json.loads(package.request.recovery_payload)["completion_id"]
    before = case[1].load()
    for destination in ("phase2-strategic-overview", "phase3-specialists", "done", "phase1-what"):
        with pytest.raises(StateAdvanceError):
            ctrl._prepare_controller_completion(from_phase="phase2-decide", to_phase=destination,
                snapshot=case[1].capture_routing_snapshot(expected_phase="phase2-decide"),
                manual_phase_run=False, conditional_skip=False, record_completion=True,
                publication_marker=package.publication.marker.to_dict(), completion_id=completion_id,
                managed_discovery_request=encode_publication_request(package.request))
    assert case[1].load() == before


def assert_feasibility_handoff(case, package, provider):
    from harness.squad_provider import SquadAgentResult
    from tests.unit.test_discovery_completion import controller, drain
    from harness.state_transaction_namespace import PENDING_EXTERNAL_PUBLICATION_KEY
    from harness.squad_publication import PreparedSquadPublication
    from harness.element_identity_store import IdentityStore
    from tests.unit.test_discovery_turns import Interrupted
    root, store, identity, _ = case
    executor = FeasibilityExecutor(provider)
    ctrl = controller(case, executor)
    completion_id = json.loads(package.request.recovery_payload)["completion_id"]
    before, history = store.load(), identity.identity_history(spec_id="game")
    spec_bytes = {p.name: p.read_bytes() for p in (root / "specs/game").iterdir() if p.is_file()}
    node = ctrl._graph.get("phase2-decide")
    with PhaseAExecutionLock.acquire(root, "test-feasibility-handoff"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-feasibility-handoff"):
            snapshot = store.capture_routing_snapshot(expected_phase=node.id)
            result = SquadAgentResult(exit_code=0, echelon_result=dict(verdict="PASS", state_updates={}),
                raw_output="", duration_ms=0, timed_out=False)
            prepared_result = ctrl._prepare_phase_result(node, result, snapshot)
            routing = ctrl._construct_routing_decision_or_block(node, prepared_result, snapshot,
                additional_state_updates={PENDING_EXTERNAL_PUBLICATION_KEY: package.publication.marker.to_dict()},
                managed_discovery_request=encode_publication_request(package.request), completion_id=completion_id,
                token_usage_delta=21)
            assert routing is not None, store.load()
            promote = PreparedSquadPublication._promote
            def before_promotion(*args, **kwargs):
                raise Interrupted()
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(PreparedSquadPublication, "_promote", before_promotion)
                with pytest.raises(Interrupted):
                    ctrl._advance_prepared_result_or_block(node, routing.decision,
                        prepared_publication=package.publication)
    assert store.load()["last_dispatch"]["post_dispatch_complete"] is False
    assert {p.name: p.read_bytes() for p in (root / "specs/game").iterdir() if p.is_file()} == spec_bytes
    def after_one_promotion(*args, **kwargs):
        def interrupt(position):
            if position == 1:
                raise Interrupted()
        return promote(*args, **{**kwargs, "fault_hook": interrupt})
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(PreparedSquadPublication, "_promote", after_one_promotion)
        with pytest.raises(Interrupted):
            drain(controller(case, executor))
    assert store.load()["last_dispatch"]["post_dispatch_complete"] is False
    writes = package.sources.publication.operations
    promoted = sum((root / op.target).is_file() and (root / op.target).read_bytes() == op.postimage_bytes for op in writes)
    assert 0 < promoted < len(writes)
    apply = IdentityStore.apply_identity_publication
    def after_identity_apply(*args, **kwargs):
        apply(*args, **kwargs)
        raise Interrupted()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(IdentityStore, "apply_identity_publication", after_identity_apply)
        with pytest.raises(Interrupted):
            drain(controller(case, executor))
    assert identity.pending_identity_publication(spec_id="game")["state"] == "applied"
    assert drain(controller(case, executor)).recovered, store.load()
    after = store.load()
    assert after["phase"] == "phase2-feasibility-structural"
    assert after["last_dispatch"]["post_dispatch_complete"] is True
    assert after["feasibility_verdict"] == "PASS"
    assert after["token_usage"] == before["token_usage"] + 21
    assert after["phase_dispatch_counts"] == before["phase_dispatch_counts"]
    assert not after["phase_dispatch_counts"].get("phase2-feasibility-structural")
    assert not after["phase_dispatch_counts"].get("phase3-specialists")
    assert identity.identity_history(spec_id="game") == history
    row = identity.identity_publication(spec_id="game", operation_id="discovery-completion-" + completion_id)
    assert row["state"] == "released" and row["completion_payload"]
    assert (root / "specs/game/feasibility.md").read_text() == "# Feasibility\nFeasible with one generated scene.\n"
    assert (root / "specs/game/spec-artifact-graph.json").read_bytes() == package.graph
    assert not package.publication._transaction_root.exists()
    assert identity.pending_identity_publication(spec_id="game") is None
    assert not executor.calls
    # Settled completion drain is idempotent, with no fresh feasibility call.
    drain(controller(case, executor))
    assert store.load() == after and not executor.calls


@pytest.mark.parametrize("provider,mode,enabled", [("codex", "guided", False), ("claude", "banzai", True)])
def test_real_review_seals_only_feasibility_outputs(checkpoint_case, provider, mode, enabled):
    complete_review(checkpoint_case, provider, mode, enabled, "approve")
    package = assert_feasibility_publication(checkpoint_case, provider)
    assert_closed_feasibility_binding(checkpoint_case, package)
    assert_structural_gate_cannot_be_skipped(checkpoint_case, package, provider)
    assert_released_approval_is_historical(checkpoint_case)
    assert_feasibility_handoff(checkpoint_case, package, provider)
