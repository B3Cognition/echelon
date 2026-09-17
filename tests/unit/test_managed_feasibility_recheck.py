"""Rechecks retain the actual failed gate budget through publication/recovery."""
from copy import deepcopy
import json
from types import SimpleNamespace
import uuid

import pytest
import yaml

from tests.unit.test_managed_feasibility_retry import (
    case, enrolled, turn_prepared, prepared, checkpoint_case,
    test_released_structural_gate_authorizes_only_its_exact_repair as complete_retry,
)
from tests.unit.test_managed_feasibility_gate import assert_gate_publication, assert_gate_handoff


def assert_recheck_preparation_refusals(case):
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    from harness.discovery_assessment_gate import prepare_feasibility_gate_publication
    from harness.squad_completion import CompletionError
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    with PhaseAExecutionLock.acquire(root, "test-recheck-refusals"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-recheck-refusals"):
            for damage in ("reset", "inflate", "typed_attempt", "iteration", "typed_iteration", "cap", "source", "override"):
                changed = deepcopy(before)
                if damage == "reset": changed["feasibility_structural_attempts"] = 0
                elif damage == "inflate": changed["feasibility_structural_attempts"] += 1
                elif damage == "typed_attempt": changed["feasibility_structural_attempts"] = float(before["feasibility_structural_attempts"])
                elif damage == "iteration": changed["iteration"] += 1
                elif damage == "typed_iteration": changed["iteration"] = float(before["iteration"])
                elif damage == "cap": changed["max_iterations"] += 1
                elif damage == "source": changed["last_dispatch"]["completion_intent_sha256"] = "0" * 64
                else: changed["governance"] = {"enabled": False}
                proxy = SimpleNamespace(squad_dir=store.squad_dir, load=lambda: deepcopy(changed))
                with pytest.raises((ValueError, CompletionError)):
                    prepare_feasibility_gate_publication(root, proxy, completion_id=uuid.uuid4().hex,
                        max_iterations=changed["max_iterations"])
    assert store.load() == before and identity.identity_history(spec_id="game") == history
    assert identity.pending_identity_publication(spec_id="game") is None


def assert_gate_budget_integrity(case):
    from harness.discovery_completion import authenticate
    from harness.squad_completion import validate_retained_completion_proof, CompletionError
    root, store, identity, _ = case
    before = store.load()
    row = identity.identity_publication(spec_id="game",
        operation_id="discovery-completion-" + before["last_dispatch"]["dispatch_id"])
    proof = json.loads(row["completion_payload"])
    marker, intent, receipts = validate_retained_completion_proof(proof["completion"],
        proof["proof"]["intent"], proof["proof"]["receipts"])
    completion = SimpleNamespace(marker=marker, intent=intent, receipts=receipts)
    assert authenticate(root, store.squad_dir, before, completion).producer == "feasibility_gate"
    for key in ("iteration", "feasibility_structural_attempts"):
        for value in (bool(before[key]), float(before[key]), str(before[key]), before[key] + 1):
            changed = deepcopy(before)
            changed[key] = value
            with pytest.raises(CompletionError):
                authenticate(root, store.squad_dir, changed, completion)
    assert store.load() == before


def assert_repaired_gate(case, provider):
    assert_recheck_preparation_refusals(case)
    package = assert_gate_publication(case, passed=True, previous_attempts=1,
        attempts=0, completion_id="f" * 32)
    assert_gate_handoff(case, package, provider, passed=True, attempts=0)
    state = case[1].load()
    assert state["iteration"] == 1 and state["feasibility_structural_attempts"] == 0
    assert state["phase"] == "phase2-strategic-overview"
    assert not state["phase_dispatch_counts"].get("phase2-strategic-overview")
    assert not state["phase_dispatch_counts"].get("phase3-specialists")
    assert_gate_budget_integrity(case)


def assert_exhausted_repairs(case, provider, policy, cap):
    from harness.discovery_assessment import require_feasibility_parent
    from harness.discovery_producer import SOURCE_FIELDS
    from harness.squad_completion import CompletionError
    from tests.unit.test_managed_feasibility_retry import (
        assert_retry_authority, assert_reviewed_retry, assert_retry_publication,
        assert_retry_completion_retains_budgets)
    from tests.unit.test_managed_feasibility_publication import assert_feasibility_handoff
    root, store, _, _ = case
    for number in range(2, cap + 1):
        assert_retry_authority(case, attempts=number - 1, iteration=number - 1)
        assert_reviewed_retry(case, provider, feasibility_text=f"# Still incomplete repair {number}\n",
            round_number=number)
        completion_id = uuid.uuid4().hex
        author = assert_retry_publication(case, provider, completion_id=completion_id)
        assert_feasibility_handoff(case, author, provider)
        assert_retry_completion_retains_budgets(case, completion_id=completion_id,
            attempts=number - 1, iteration=number - 1)
        assert_recheck_preparation_refusals(case)
        action = ("block" if policy == "block" else "proceed_with_warning") if number == cap else "repair"
        gate = assert_gate_publication(case, previous_attempts=number - 1, attempts=number,
            action=action, completion_id=uuid.uuid4().hex)
        assert_gate_handoff(case, gate, provider, action=action, attempts=number)
        assert_gate_budget_integrity(case)
    final = store.load()
    assert final["iteration"] == cap - 1 and final["feasibility_structural_attempts"] == cap
    assert final["governance_gate_exhausted"] == "feasibility"
    assert not final["phase_dispatch_counts"].get("phase2-strategic-overview")
    assert not final["phase_dispatch_counts"].get("phase3-specialists")
    # Even forged phase/status labels cannot turn an exhausted gate into repair authority.
    forged = {**final, "phase": "phase2-decide", "status": "running"}
    source = {key: final["last_dispatch"][key] for key in SOURCE_FIELDS}
    with pytest.raises((ValueError, CompletionError)):
        require_feasibility_parent(root, store.squad_dir, forged, source)
    assert store.load() == final


@pytest.mark.parametrize("provider,mode,enabled", [("codex", "guided", False), ("claude", "banzai", True)])
def test_repaired_feasibility_passes_recheck_without_fresh_budget(checkpoint_case, provider, mode, enabled):
    complete_retry(checkpoint_case, provider, mode, enabled)
    assert_repaired_gate(checkpoint_case, provider)


@pytest.mark.parametrize("provider,mode,enabled,policy,cap", [
    ("codex", "guided", False, "block", 2), ("claude", "banzai", True, "warn", 3)])
def test_rechecks_exhaust_original_budget(checkpoint_case, provider, mode, enabled, policy, cap):
    from tests.unit.test_managed_feasibility_gate import test_reviewed_feasibility_gate_uses_guarded_report_handoff as first_gate
    path = checkpoint_case[0] / ".echelon/config.yml"
    config = yaml.safe_load(path.read_text())
    config.setdefault("governance", {}).update(max_repair_attempts=cap, on_exhausted=policy)
    path.write_text(yaml.safe_dump(config))
    first_gate(checkpoint_case, provider, mode, enabled)
    assert_exhausted_repairs(checkpoint_case, provider, policy, cap)
