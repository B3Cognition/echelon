"""Alignment repair consumes its released failed gate, without resetting history."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from uuid import uuid4

import pytest

from harness import discovery_assessment as assessment
from harness.discovery_producer import SOURCE_FIELDS, tracker_round
from harness.squad_completion import CompletionError
from tests.unit.test_managed_alignment_execution import AlignmentExecutor
from tests.unit.test_managed_alignment_publication import assert_alignment_handoff, envelope
from tests.unit.test_managed_feasibility_recheck import (
    case, enrolled, turn_prepared, prepared, checkpoint_case, complete_retry, assert_repaired_gate,
)


def test_repair_requires_released_gate_not_phase_or_approval():
    repair = getattr(assessment, "require_alignment_repair", None)
    assert callable(repair), "Alignment repair needs its exact released failed gate"
    with pytest.raises((ValueError, CompletionError)):
        assessment.require_alignment_parent(Path("/absent"), Path("/absent/runs/first"),
            dict(phase="phase2-tracker-alignment", status="running", last_dispatch=dict(
                phase_id="phase2-intent-alignment-structural", post_dispatch_complete=True)), {})


def assert_retry_authority(case):
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    source = {key: before["last_dispatch"][key] for key in SOURCE_FIELDS}
    binding = assessment.require_alignment_parent(root, store.squad_dir, before, source)
    assert binding.producer == "alignment_gate" and binding.recovery["version"] == 37
    assert binding.recovery["result"]["state_updates"]["structural_action"] == "repair"
    for damage in ("attempt", "typed_attempt", "iteration", "typed_iteration", "cap", "action", "findings",
            "verdict", "feasibility", "phase", "cancelled", "unfinished", "source", "override", "old_parent"):
        state, selected = deepcopy(before), dict(source)
        if damage == "attempt": state["intent_alignment_check_structural_attempts"] = 0
        elif damage == "typed_attempt": state["intent_alignment_check_structural_attempts"] = True
        elif damage == "iteration": state["iteration"] += 1
        elif damage == "typed_iteration": state["iteration"] = float(before["iteration"])
        elif damage == "cap": state["max_iterations"] += 1
        elif damage == "action": state["structural_action"] = "proceed"
        elif damage == "findings": state["intent_alignment_check_structural_findings"] = 0
        elif damage == "verdict": state["intent_alignment_verdict"] = "DRIFT"
        elif damage == "feasibility": state["feasibility_structural_attempts"] += 1
        elif damage == "phase": state["phase"] = "phase3-specialists"
        elif damage == "cancelled": state["cancel_requested"] = True
        elif damage == "unfinished": state["last_dispatch"]["post_dispatch_complete"] = False
        elif damage == "source": selected["completion_receipts_sha256"] = "0" * 64
        elif damage == "override": state["governance"] = {"enabled": False}
        else: selected = tracker_round(before, producer="alignment")["source"]
        with pytest.raises((ValueError, CompletionError)):
            assessment.require_alignment_parent(root, store.squad_dir, state, selected)
    assert store.load() == before and identity.identity_history(spec_id="game") == history


class RepairExecutor(AlignmentExecutor):
    def run_inspection_turn(self, *args, **kwargs):
        result = super().run_inspection_turn(*args, **kwargs)
        payload = json.loads(result.stdout)
        if payload["step"] == "author":
            payload["artifacts"]["intent-alignment-check.md"] = payload["artifacts"][
                "intent-alignment-check.md"].replace("Movement remains in scope.", "ALIGNED: Movement remains in scope.")
            result = replace(result, stdout=json.dumps(payload))
        return result


def assert_reviewed_retry(case, provider):
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    from harness.discovery_operation import run_discovery_operation
    from tests.unit.test_managed_checkpoint_assess import selection
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    source = {key: before["last_dispatch"][key] for key in SOURCE_FIELDS}
    documents = {p.name: p.read_bytes() for p in (root / "specs/game").iterdir() if p.is_file()}
    executor = RepairExecutor(provider)
    args = dict(input_tree=selection(case)["input_tree"], artifact_paths=("intent-alignment-check.md",),
        unowned_writable_paths=("intent-alignment-check.md",),
        intent=dict(kind="align", request="Repair the captured alignment findings"), producer="alignment")
    with PhaseAExecutionLock.acquire(root, "test-alignment-retry"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-alignment-retry"):
            assessment.require_alignment_parent(root, store.squad_dir, before, source)
            store.prepare_spec_round("alignment", source, expected_state=before)
            result = run_discovery_operation(root, store, executor, create=True, **args)
            assert result.status == "reviewed", (result.reason, len(executor.calls))
            assert result.dispatch_count == 3 and result.token_usage == 21
            assert result.candidate.operations == () and result.candidate.history == history
            report = documents["intent-alignment-check-structural-report.json"].decode()
            assert all(call["context"]["evidence"]["specs/game/intent-alignment-check-structural-report.json"]
                == report for call in executor.calls)
            accepted = store.load()
            assert run_discovery_operation(root, store, executor, replay_only=True, **args) == result
            assert len(executor.calls) == 3 and store.load() == accepted
    row = tracker_round(accepted, producer="alignment")
    assert row["predecessor"] == before["managed_alignment_rounds"]["active"] and row["resolution"] is None
    for key, value in before["managed_alignment_rounds"]["rounds"].items():
        assert accepted["managed_alignment_rounds"]["rounds"][key] == value
    for key in ("iteration", "max_iterations", "feasibility_structural_attempts",
            "intent_alignment_check_structural_attempts", "blocked_decision"):
        assert accepted[key] == before[key]
    assert accepted["phase_dispatch_counts"]["phase2-tracker-alignment"] == 2
    assert identity.identity_history(spec_id="game") == history
    assert {p.name: p.read_bytes() for p in (root / "specs/game").iterdir() if p.is_file()} == documents
    assert not accepted["phase_dispatch_counts"].get("phase3-specialists")


def assert_retry_publication(case, provider):
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    from harness.discovery_completion import decode_binding, _json
    from harness.discovery_publication import prepare_discovery_publication
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    executor = RepairExecutor(provider)
    with PhaseAExecutionLock.acquire(root, "test-alignment-retry-publication"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-alignment-retry-publication"):
            package = prepare_discovery_publication(root, store, executor, completion_id=uuid4().hex, producer="alignment")
    binding = decode_binding(envelope(package), state=before)
    assert binding.recovery["version"] == 38 and binding.recovery["resolution"] is None
    assert binding.recovery["predecessor"] == tracker_round(before, producer="alignment")["predecessor"]
    assert binding.request.operations == () and binding.source["history"] == binding.candidate["history"]
    assert {op.target for op in package.sources.publication.operations} == {
        "specs/game/intent-alignment-check.md", "specs/game/spec-artifact-graph.json"}
    for damage in ("version", "predecessor", "resolution", "source"):
        recovery = json.loads(package.request.recovery_payload)
        if damage == "version": recovery["version"] = 36
        elif damage == "predecessor": recovery["predecessor"] = None
        elif damage == "resolution": recovery["resolution"] = {}
        else: recovery["source_completion"]["dispatch_id"] = "0" * 32
        with pytest.raises(CompletionError):
            decode_binding(envelope(package, replace(package.request, recovery_payload=_json(recovery))))
    assert store.load() == before and identity.identity_history(spec_id="game") == history and not executor.calls
    return package


def assert_retry_stops_before_unadmitted_recheck(case):
    from harness.discovery_assessment_gate import require_alignment_gate_parent
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    source = {key: before["last_dispatch"][key] for key in SOURCE_FIELDS}
    assert before["phase"] == "phase2-intent-alignment-structural"
    assert before["last_dispatch"]["post_dispatch_complete"] is True
    with pytest.raises((ValueError, CompletionError)):
        require_alignment_gate_parent(root, store.squad_dir, before, source)
    assert not before["phase_dispatch_counts"].get("phase3-specialists")
    assert store.load() == before and identity.identity_history(spec_id="game") == history


@pytest.mark.parametrize("provider,mode,enabled", [("codex", "guided", False), ("claude", "banzai", True)])
def test_alignment_repair_preserves_gate_ancestry_and_budgets(checkpoint_case, provider, mode, enabled):
    from tests.unit.test_managed_strategy_execution import assert_reviewed_strategy
    from tests.unit.test_managed_strategy_publication import assert_strategy_publication, assert_strategy_handoff
    from tests.unit.test_managed_alignment_execution import assert_reviewed_alignment
    from tests.unit.test_managed_alignment_publication import assert_alignment_publication
    from tests.unit.test_managed_alignment_gate import assert_gate_publication, assert_gate_handoff
    complete_retry(checkpoint_case, provider, mode, enabled)
    assert_repaired_gate(checkpoint_case, provider)
    assert_reviewed_strategy(checkpoint_case, provider)
    assert_strategy_handoff(checkpoint_case, assert_strategy_publication(checkpoint_case, provider), provider)
    assert_reviewed_alignment(checkpoint_case, provider)
    assert_alignment_handoff(checkpoint_case, assert_alignment_publication(checkpoint_case, provider), provider)
    assert_gate_handoff(checkpoint_case, assert_gate_publication(checkpoint_case), provider)
    assert_retry_authority(checkpoint_case)
    assert_reviewed_retry(checkpoint_case, provider)
    assert_alignment_handoff(checkpoint_case, assert_retry_publication(checkpoint_case, provider), provider)
    assert_retry_stops_before_unadmitted_recheck(checkpoint_case)
