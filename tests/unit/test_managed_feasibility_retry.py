"""Structural repair requires released gate evidence, never a recycled approval."""
from copy import deepcopy
import json
import os

import pytest

from harness.discovery_assessment import require_feasibility_parent
from harness.discovery_producer import SOURCE_FIELDS
from harness.squad_completion import CompletionError
from tests.unit.test_managed_feasibility_gate import (
    case, enrolled, turn_prepared, prepared, checkpoint_case,
    test_reviewed_feasibility_gate_uses_guarded_report_handoff as complete_failed_gate,
)


def assert_retry_authority(case):
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    source = {key: before["last_dispatch"][key] for key in SOURCE_FIELDS}
    binding = require_feasibility_parent(root, store.squad_dir, before, source)
    assert binding.producer == "feasibility_gate"
    assert binding.recovery["result"]["state_updates"]["structural_action"] == "repair"
    assert before["iteration"] == 1 and before["feasibility_structural_attempts"] == 1
    for damage in ("counter", "typed_counter", "iteration", "typed_iteration", "cap", "action",
            "findings", "verdict", "phase", "cancelled", "unfinished", "source", "approval"):
        state, selected = deepcopy(before), dict(source)
        if damage == "counter": state["feasibility_structural_attempts"] = 0
        elif damage == "typed_counter": state["feasibility_structural_attempts"] = True
        elif damage == "iteration": state["iteration"] = 0
        elif damage == "typed_iteration": state["iteration"] = True
        elif damage == "cap": state["max_iterations"] += 1
        elif damage == "action": state["structural_action"] = "proceed"
        elif damage == "findings": state["feasibility_structural_findings"] = []
        elif damage == "verdict": state["feasibility_verdict"] = "DEFER"
        elif damage == "phase": state["phase"] = "phase2-strategic-overview"
        elif damage == "cancelled": state["cancel_requested"] = True
        elif damage == "unfinished": state["last_dispatch"]["post_dispatch_complete"] = False
        elif damage == "source": selected["completion_receipts_sha256"] = "0" * 64
        else:
            from harness.discovery_spec import clarification_source
            selected = clarification_source(state["last_human_input_completion"])
        with pytest.raises((ValueError, CompletionError)):
            require_feasibility_parent(root, store.squad_dir, state, selected)
    assert store.load() == before and identity.identity_history(spec_id="game") == history


def assert_reviewed_retry(case, provider):
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    from harness.discovery_assessment import ASSESSMENT_OUTPUTS
    from harness.discovery_operation import run_discovery_operation
    from harness.discovery_producer import tracker_round
    from tests.unit.test_managed_checkpoint_assess import selection
    from tests.unit.test_managed_feasibility_rounds import FeasibilityExecutor
    from tests.unit.test_captured_governance_gate import FEASIBILITY
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    source = {key: before["last_dispatch"][key] for key in SOURCE_FIELDS}
    old_rounds = deepcopy(before["managed_feasibility_rounds"]["rounds"])
    old_rounds.pop("feasibility-" + source["dispatch_id"], None)
    documents = {p.name: p.read_bytes() for p in (root / "specs/game").iterdir() if p.is_file()}
    executor = FeasibilityExecutor(provider, feasibility_text=FEASIBILITY)
    paths = tuple(ASSESSMENT_OUTPUTS["feasibility"])
    args = dict(input_tree=selection(case)["input_tree"], artifact_paths=paths,
        unowned_writable_paths=paths, intent=dict(kind="assess", request="Repair the captured feasibility findings"),
        producer="feasibility")
    with PhaseAExecutionLock.acquire(root, "test-feasibility-retry"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-feasibility-retry"):
            require_feasibility_parent(root, store.squad_dir, before, source)
            store.prepare_spec_round("feasibility", source, expected_state=before)
            result = run_discovery_operation(root, store, executor, create=True, **args)
            assert result.status == "reviewed", (result.reason, len(executor.calls))
            assert result.dispatch_count == 3 and result.token_usage == 21
            assert result.candidate.operations == () and result.candidate.history == history
            report = documents["feasibility-structural-report.json"].decode()
            for call in executor.calls:
                assert call["context"]["evidence"]["specs/game/feasibility-structural-report.json"] == report
            retained = store.load()
            replay = run_discovery_operation(root, store, executor, replay_only=True, **args)
            assert replay == result and len(executor.calls) == 3 and store.load() == retained
            for relative in ("specs/game/spec.md", "specs/game/feasibility-structural-report.json",
                    "runs/first/context/current-feature-context.md"):
                path = root / relative
                original, stat = path.read_bytes(), path.stat()
                try:
                    path.write_bytes(original + b"\nChanged after gate release.\n")
                    refused = run_discovery_operation(root, store, executor, replay_only=True, **args)
                    assert refused.status != "reviewed" and len(executor.calls) == 3
                    assert store.load() == retained
                finally:
                    path.write_bytes(original)
                    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    after = store.load()
    selected = tracker_round(after, producer="feasibility")
    assert selected["resolution"] is None and selected["predecessor"] in old_rounds
    assert selected["operation"]["attempts"][-1]["result"]["status"] == "accepted"
    assert all(after["managed_feasibility_rounds"]["rounds"][key] == row for key, row in old_rounds.items())
    assert after["phase_dispatch_counts"]["phase2-decide"] == 2
    assert after["iteration"] == after["feasibility_structural_attempts"] == 1
    assert after["blocked_decision"] == before["blocked_decision"]
    assert identity.identity_history(spec_id="game") == history
    assert {p.name: p.read_bytes() for p in (root / "specs/game").iterdir() if p.is_file()} == documents
    assert not after["phase_dispatch_counts"].get("phase3-specialists")


def assert_retry_publication(case, provider):
    from dataclasses import replace
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    from harness.discovery_completion import decode_binding
    from harness.discovery_publication import prepare_discovery_publication
    from tests.unit.test_managed_feasibility_publication import envelope
    from tests.unit.test_managed_feasibility_rounds import FeasibilityExecutor
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    executor = FeasibilityExecutor(provider)
    with PhaseAExecutionLock.acquire(root, "test-retry-publication"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-retry-publication"):
            package = prepare_discovery_publication(root, store, executor, completion_id="d" * 32,
                producer="feasibility")
    binding = decode_binding(envelope(package), state=before)
    assert binding.recovery["version"] == 33 and binding.recovery["resolution"] is None
    assert binding.recovery["predecessor"] == before["managed_feasibility_rounds"]["rounds"][
        before["managed_feasibility_rounds"]["active"]]["predecessor"]
    assert binding.request.operations == () and binding.source["history"] == binding.candidate["history"]
    assert {op.target for op in package.sources.publication.operations} == {
        "specs/game/" + name for name in ("feasibility.md", "prioritization.md", "estimates.md",
            "mvp-scope.md", "spec-artifact-graph.json")}
    for damage in ("version", "predecessor", "resolution", "source"):
        recovery = json.loads(package.request.recovery_payload)
        if damage == "version": recovery["version"] = 31
        elif damage == "predecessor": recovery["predecessor"] = None
        elif damage == "resolution": recovery["resolution"] = dict(
            decision=before["blocked_decision"], completion=before["last_human_input_completion"])
        else: recovery["source_completion"]["dispatch_id"] = "0" * 32
        request = replace(package.request, recovery_payload=json.dumps(recovery,
            sort_keys=True, separators=(",", ":"), ensure_ascii=True))
        with pytest.raises(CompletionError):
            decode_binding(envelope(package, request))
    assert store.load() == before and identity.identity_history(spec_id="game") == history and not executor.calls
    return package


def assert_retry_completion_retains_budgets(case):
    from types import SimpleNamespace
    from harness.discovery_completion import authenticate
    from harness.squad_completion import validate_retained_completion_proof
    root, store, identity, _ = case
    before = store.load()
    assert before["phase"] == "phase2-feasibility-structural"
    assert before["iteration"] == before["feasibility_structural_attempts"] == 1
    row = identity.identity_publication(spec_id="game", operation_id="discovery-completion-" + "d" * 32)
    proof = json.loads(row["completion_payload"])
    marker, intent, receipts = validate_retained_completion_proof(proof["completion"],
        proof["proof"]["intent"], proof["proof"]["receipts"])
    completion = SimpleNamespace(marker=marker, intent=intent, receipts=receipts)
    assert authenticate(root, store.squad_dir, before, completion).recovery["version"] == 33
    for key in ("iteration", "feasibility_structural_attempts", "max_iterations"):
        for value in (0, True, 1.0, "1", 999):
            changed = deepcopy(before)
            changed[key] = value
            with pytest.raises(CompletionError):
                authenticate(root, store.squad_dir, changed, completion)
    assert store.load() == before


@pytest.mark.parametrize("provider,mode,enabled", [("codex", "guided", False), ("claude", "banzai", True)])
def test_released_structural_gate_authorizes_only_its_exact_repair(checkpoint_case, provider, mode, enabled):
    complete_failed_gate(checkpoint_case, provider, mode, enabled)
    assert_retry_authority(checkpoint_case)
    assert_reviewed_retry(checkpoint_case, provider)
    package = assert_retry_publication(checkpoint_case, provider)
    from tests.unit.test_managed_feasibility_publication import assert_structural_gate_cannot_be_skipped, assert_feasibility_handoff
    assert_structural_gate_cannot_be_skipped(checkpoint_case, package, provider)
    assert_feasibility_handoff(checkpoint_case, package, provider)
    assert_retry_completion_retains_budgets(checkpoint_case)
