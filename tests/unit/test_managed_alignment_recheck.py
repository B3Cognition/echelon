"""Repaired alignment is rechecked against its retained native budget."""
from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from harness.discovery_producer import SOURCE_FIELDS
from harness.squad_completion import CompletionError
from tests.unit.test_managed_alignment_retry import (
    case, enrolled, turn_prepared, prepared, checkpoint_case,
    test_alignment_repair_preserves_gate_ancestry_and_budgets as complete_retry,
)
from tests.unit.test_managed_alignment_gate import assert_gate_publication, assert_gate_handoff


def assert_recheck_parent(case):
    from harness.discovery_assessment_gate import require_alignment_gate_parent
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    source = {key: before["last_dispatch"][key] for key in SOURCE_FIELDS}
    parent = require_alignment_gate_parent(root, store.squad_dir, before, source)
    assert parent.recovery["version"] == 38
    assert parent.recovery["predecessor"] is not None
    assert store.load() == before and identity.identity_history(spec_id="game") == history


def assert_recheck_preparation_refusals(case):
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    from harness.discovery_assessment_gate import prepare_alignment_gate_publication
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    with PhaseAExecutionLock.acquire(root, "test-alignment-recheck-refusals"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-alignment-recheck-refusals"):
            for damage in ("reset", "inflate", "typed_attempt", "iteration", "typed_iteration",
                    "cap", "source", "override", "feasibility", "verdict"):
                changed = deepcopy(before)
                if damage == "reset": changed["intent_alignment_check_structural_attempts"] = 0
                elif damage == "inflate": changed["intent_alignment_check_structural_attempts"] += 1
                elif damage == "typed_attempt": changed["intent_alignment_check_structural_attempts"] = 1.0
                elif damage == "iteration": changed["iteration"] += 1
                elif damage == "typed_iteration": changed["iteration"] = float(before["iteration"])
                elif damage == "cap": changed["max_iterations"] += 1
                elif damage == "source": changed["last_dispatch"]["completion_intent_sha256"] = "0" * 64
                elif damage == "override": changed["governance"] = {"enabled": False}
                elif damage == "feasibility": changed["feasibility_structural_attempts"] += 1
                else: changed["intent_alignment_verdict"] = "DRIFT"
                proxy = SimpleNamespace(squad_dir=store.squad_dir, load=lambda: deepcopy(changed))
                with pytest.raises((ValueError, CompletionError)):
                    prepare_alignment_gate_publication(root, proxy, completion_id=uuid4().hex,
                        max_iterations=changed["max_iterations"])
    assert store.load() == before and identity.identity_history(spec_id="game") == history
    assert identity.pending_identity_publication(spec_id="game") is None


def assert_repaired_gate(case, provider):
    assert_recheck_parent(case)
    assert_recheck_preparation_refusals(case)
    before = case[1].load()
    package = assert_gate_publication(case, passed=True, previous_attempts=1, attempts=0)
    assert_gate_handoff(case, package, provider, passed=True, attempts=0)
    state = case[1].load()
    assert state["iteration"] == before["iteration"]
    assert state["intent_alignment_check_structural_attempts"] == 0
    assert state["phase"] == "phase3-specialists"
    assert not state["phase_dispatch_counts"].get("phase3-specialists")
    assert_recheck_budget_integrity(case)


def assert_recheck_budget_integrity(case):
    from harness.discovery_completion import authenticate
    from harness.squad_completion import validate_retained_completion_proof
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    row = identity.identity_publication(spec_id="game",
        operation_id="discovery-completion-" + before["last_dispatch"]["dispatch_id"])
    proof = json.loads(row["completion_payload"])
    marker, intent, receipts = validate_retained_completion_proof(proof["completion"],
        proof["proof"]["intent"], proof["proof"]["receipts"])
    completion = SimpleNamespace(marker=marker, intent=intent, receipts=receipts)
    binding = authenticate(root, store.squad_dir, before, completion)
    assert binding.producer == "alignment_gate" and binding.recovery["version"] == 39
    assert binding.recovery["previous_attempts"] == 1
    from harness.discovery_assessment import require_alignment_parent
    source = {key: before["last_dispatch"][key] for key in SOURCE_FIELDS}
    forged = {**before, "phase": "phase2-tracker-alignment", "status": "running"}
    with pytest.raises((ValueError, CompletionError)):
        require_alignment_parent(root, store.squad_dir, forged, source)
    for key in ("iteration", "intent_alignment_check_structural_attempts", "feasibility_structural_attempts"):
        for value in (bool(before[key]), float(before[key]), str(before[key]), before[key] + 1):
            changed = deepcopy(before)
            changed[key] = value
            with pytest.raises(CompletionError): authenticate(root, store.squad_dir, changed, completion)
    assert store.load() == before and identity.identity_history(spec_id="game") == history


@pytest.mark.parametrize("provider,mode,enabled", [("codex", "guided", False), ("claude", "banzai", True)])
def test_repaired_alignment_rechecks_without_fresh_budget(checkpoint_case, provider, mode, enabled):
    complete_retry(checkpoint_case, provider, mode, enabled)
    assert_repaired_gate(checkpoint_case, provider)
