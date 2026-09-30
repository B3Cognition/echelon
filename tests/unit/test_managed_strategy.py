"""Strategy reads only the actual released feasibility-gate successor."""
from copy import deepcopy
import os
from pathlib import Path

import pytest

from harness import discovery_assessment as assessment
from harness.discovery_producer import SOURCE_FIELDS
from harness.squad_completion import CompletionError
from tests.unit.test_managed_feasibility_policy import (
    case, enrolled, turn_prepared, prepared, checkpoint_case,
    test_first_gate_preserves_native_policy as complete_policy,
)


def parent(case, state=None, source=None):
    root, store, _, _ = case
    state = store.load() if state is None else state
    source = {key: state["last_dispatch"][key] for key in SOURCE_FIELDS} if source is None else source
    function = getattr(assessment, "require_strategy_parent", None)
    assert callable(function), "Strategy must authenticate its released feasibility gate"
    return function(root, store.squad_dir, state, source)


def assert_strategy_parent(case, *, admitted=True):
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    if admitted:
        binding = parent(case)
        assert binding.producer == "feasibility_gate"
        assert binding.recovery["routing_state"]["feasibility_verdict"] == "PASS"
        for damage in ("phase", "status", "cancelled", "unfinished", "source", "receipt", "verdict_kill",
                "verdict_defer", "attempts", "typed_attempts", "iteration", "typed_iteration", "cap", "override", "pending"):
            changed = deepcopy(before)
            source = {key: before["last_dispatch"][key] for key in SOURCE_FIELDS}
            if damage == "phase": changed["phase"] = "phase3-specialists"
            elif damage == "status": changed["status"] = "blocked"
            elif damage == "cancelled": changed["cancel_requested"] = True
            elif damage == "unfinished": changed["last_dispatch"]["post_dispatch_complete"] = False
            elif damage == "source": source["dispatch_id"] = "0" * 32
            elif damage == "receipt": changed["last_dispatch"]["completion_intent_sha256"] = "0" * 64
            elif damage == "verdict_kill": changed["feasibility_verdict"] = "KILL"
            elif damage == "verdict_defer": changed["feasibility_verdict"] = "DEFER"
            elif damage == "attempts": changed["feasibility_structural_attempts"] += 1
            elif damage == "typed_attempts": changed["feasibility_structural_attempts"] = float(before["feasibility_structural_attempts"])
            elif damage == "iteration": changed["iteration"] += 1
            elif damage == "typed_iteration": changed["iteration"] = float(before["iteration"])
            elif damage == "cap": changed["max_iterations"] += 1
            elif damage == "override": changed["governance"] = {"enabled": False}
            else: changed["_spec_step_effect_plan"] = {}
            with pytest.raises((ValueError, CompletionError)):
                parent(case, changed, source)
    else:
        forged = deepcopy(before)
        forged.update(phase="phase2-strategic-overview", status="running", feasibility_verdict="PASS")
        with pytest.raises((ValueError, CompletionError)):
            parent(case, forged)
    assert store.load() == before and identity.identity_history(spec_id="game") == history


def capture(case, **changes):
    from harness.discovery_bootstrap_state import bootstrap_from_state
    from harness.discovery_operation import _capture
    from tests.unit.test_managed_checkpoint_assess import selection
    root, store, identity, _ = case
    selected = bootstrap_from_state(store.load())
    return _capture(root, store, identity, selected, selection(case)["input_tree"],
        **{**dict(artifact_paths=("strategic-overview.md",), producer="strategy"), **changes})


def assert_strategy_capture(case):
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    fingerprint, baseline, evidence, captured_history, templates, runtime, sources, inputs = capture(case)
    assert set(templates) == {"strategic-overview.md"} and templates["strategic-overview.md"]
    assert {"spec.md", "user-intent.md", "feasibility.md", "estimates.md", "prioritization.md", "unknowns.md"} <= baseline.keys()
    assert captured_history == history and not sources.publication.operations
    assert inputs["authority"]["source_context"]["operation_id"] == "discovery-completion-" + before["last_dispatch"]["dispatch_id"]
    report = "specs/game/feasibility-structural-report.json"
    if (root / report).exists():
        assert evidence[report] == (root / report).read_text()
    assert runtime["autonomy_mode"] == before["autonomy_mode"] and len(fingerprint) == 64
    for changes in (dict(artifact_paths=("spec.md",)), dict(clarification=True), dict(repair_unit="a" * 64),
            dict(source_completion={key: "0" * (32 if key == "dispatch_id" else 64) for key in SOURCE_FIELDS})):
        with pytest.raises((ValueError, CompletionError)):
            capture(case, **changes)
    assert store.load() == before and identity.identity_history(spec_id="game") == history
    assert "managed_strategy_rounds" not in before  # Capture is not execution admission.


def assert_strategy_capture_refuses_drift(case):
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    paths = ["specs/game/feasibility.md", "runs/first/context/current-feature-context.md"]
    if (root / "specs/game/feasibility-structural-report.json").exists():
        paths.append("specs/game/feasibility-structural-report.json")
    for relative in paths:
        path = root / relative
        content, stat = path.read_bytes(), path.stat()
        try:
            path.write_bytes(content + b"\nchanged after released gate\n")
            with pytest.raises((ValueError, CompletionError)):
                capture(case)
        finally:
            path.write_bytes(content)
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert store.load() == before and identity.identity_history(spec_id="game") == history
    assert not before["phase_dispatch_counts"].get("phase2-strategic-overview")


def test_strategy_rejects_phase_label_without_released_gate():
    function = getattr(assessment, "require_strategy_parent", None)
    assert callable(function), "Strategy must authenticate its released feasibility gate"
    with pytest.raises(ValueError):
        function(Path("/absent"), Path("/absent/runs/first"),
            dict(phase="phase2-strategic-overview", status="running"), {})


@pytest.mark.parametrize("provider,mode,enabled,policy", [
    ("codex", "guided", False, "disabled"), ("claude", "banzai", True, "warn")])
def test_strategy_captures_released_gate_without_dispatch(checkpoint_case, provider, mode, enabled, policy):
    complete_policy(checkpoint_case, provider, mode, enabled, policy)
    assert_strategy_parent(checkpoint_case)
    assert_strategy_capture(checkpoint_case)
    assert_strategy_capture_refuses_drift(checkpoint_case)
