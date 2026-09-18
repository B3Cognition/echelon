"""Publish the accepted answer-derived author without another dispatch."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
from harness.discovery_completion import decode_binding, _json
from harness.discovery_publication import prepare_discovery_publication
from harness.discovery_producer import tracker_round
from harness.squad_completion import CompletionError
from tests.unit.test_managed_alignment_answer_round import (
    case, enrolled, turn_prepared, prepared, checkpoint_case,
    test_released_answer_drives_one_resumed_alignment_author as complete_author,
)
from tests.unit.test_managed_alignment_execution import AlignmentExecutor
from tests.unit.test_managed_alignment_publication import assert_alignment_handoff, envelope


def assert_answer_publication(case, provider):
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    row = tracker_round(before, producer="alignment")
    executor = AlignmentExecutor(provider)
    with PhaseAExecutionLock.acquire(root, "test-answer-publication"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-answer-publication"):
            package = prepare_discovery_publication(root, store, executor,
                completion_id="42" * 16, producer="alignment")
            binding = decode_binding(envelope(package), state=before)
            assert binding.recovery["version"] == 42
            assert binding.recovery["resolution"] == row["resolution"]
            assert binding.recovery["predecessor"] == row["predecessor"]
            assert binding.recovery["source_completion"] == row["source"]
            assert binding.request.operations == ()
            assert binding.candidate["history"] == binding.source["history"]
            assert binding.candidate["routing"] == dict(verdict="ALIGNED", state_updates={})
            for damage in ("repair", "initial", "answer", "receipt", "source", "predecessor", "missing"):
                recovery = json.loads(package.request.recovery_payload)
                if damage == "repair": recovery["version"] = 38
                elif damage == "initial": recovery["version"] = 36
                elif damage == "answer": recovery["resolution"]["decision"]["answer_text"] = "Use arrows"
                elif damage == "receipt": recovery["resolution"]["completion"]["intent_sha256"] = "0" * 64
                elif damage == "source": recovery["source_completion"]["dispatch_id"] = "0" * 32
                elif damage == "predecessor": recovery["predecessor"] = None
                else: recovery["resolution"] = None
                with pytest.raises(CompletionError):
                    decode_binding(envelope(package, replace(package.request, recovery_payload=_json(recovery))), state=before)
    assert not executor.calls and store.load() == before
    assert identity.identity_history(spec_id="game") == history
    assert identity.pending_identity_publication(spec_id="game") is None
    return package


def assert_answer_handoff(case, package, provider):
    root, store, identity, _ = case
    before = store.load()
    assert_alignment_handoff(case, package, provider)
    after = store.load()
    for key in ("managed_alignment_rounds", "blocked_decision", "last_human_input_completion"):
        assert after[key] == before[key]
    assert after["token_usage"] == before["token_usage"] + 21
    assert_answer_ancestry(case)


def assert_answer_ancestry(case):
    root, store, identity, _ = case
    after = store.load()
    # Ancestry remains readable after the answer is no longer the source head.
    from harness.discovery_completion import released_discovery_input_projectors
    from harness.discovery_producer import SOURCE_FIELDS
    with PhaseAExecutionLock.acquire(root, "test-answer-ancestry"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-answer-ancestry"):
            released_discovery_input_projectors(root, store.squad_dir, after,
                source={key: after["last_dispatch"][key] for key in SOURCE_FIELDS})
    # Historical traversal must not weaken v41's live effect decoder.
    answer = identity.identity_publication(spec_id="game",
        operation_id="discovery-completion-" + after["last_human_input_completion"]["completion_id"])
    proof = json.loads(answer["completion_payload"])
    with pytest.raises(CompletionError):
        decode_binding(proof["proof"]["intent"]["publication"], state=after)
    from harness.squad_completion import validate_retained_completion_proof
    from harness.tracker_clarification import require_released_alignment_membership
    marker, intent, _ = validate_retained_completion_proof(proof["completion"],
        proof["proof"]["intent"], proof["proof"]["receipts"])
    binding = decode_binding(intent.publication)
    require_released_alignment_membership(after, binding, marker)
    changed = deepcopy(after)
    row = changed["managed_alignment_rounds"]["rounds"][changed["managed_alignment_rounds"]["active"]]
    row["resolution"]["completion"]["intent_sha256"] = "0" * 64
    row["source"]["completion_intent_sha256"] = "0" * 64
    # The intact latest receipt cannot mask a forged successor association.
    with pytest.raises(ValueError): require_released_alignment_membership(changed, binding, marker)
    assert store.load() == after


def assert_answer_handoff_refusals(case, completion):
    from harness.discovery_completion import authenticate
    root, store, _, _ = case
    before = store.load()
    for damage in ("count", "typed_count", "charge", "missing_charge", "typed_charge", "answer", "receipt", "historical", "policy", "outcomes", "stale_escalation"):
        changed = deepcopy(before)
        rounds = changed["managed_alignment_rounds"]
        row = rounds["rounds"][rounds["active"]]
        if damage == "count": changed["phase_dispatch_counts"]["phase2-tracker-alignment"] += 1
        elif damage == "typed_count": changed["phase_dispatch_counts"]["phase2-tracker-alignment"] = float(changed["phase_dispatch_counts"]["phase2-tracker-alignment"])
        elif damage == "charge": changed["token_usage"] += 1
        elif damage == "missing_charge": changed["token_usage"] -= 1
        elif damage == "typed_charge": changed["token_usage"] = float(changed["token_usage"])
        elif damage == "answer": row["resolution"]["decision"]["answer_text"] = "Use arrows"
        elif damage == "receipt": row["resolution"]["completion"]["intent_sha256"] = "0" * 64
        elif damage == "historical": rounds["rounds"][row["predecessor"]]["operation"] = None
        elif damage == "policy": changed["feature_policy"]["scope"] = {"extra": True}
        elif damage == "outcomes": changed["phase_completion_outcomes"] = changed["phase_completion_outcomes"][1:]
        else: changed["escalation_resolved"] = True
        with pytest.raises(CompletionError): authenticate(root, store.squad_dir, changed, completion)
    assert store.load() == before


@pytest.mark.parametrize("provider,mode", [("codex", "guided"), ("claude", "banzai")])
def test_answer_author_publication_recovers_native_structural_handoff(checkpoint_case, provider, mode):
    complete_author(checkpoint_case, provider, mode)
    package = assert_answer_publication(checkpoint_case, provider)
    assert_answer_handoff(checkpoint_case, package, provider)
