"""Alignment cannot skip actual released strategy or rewrite its input scope."""
from copy import deepcopy
import os
from pathlib import Path

import pytest

from harness import discovery_assessment as assessment
from harness.discovery_producer import SOURCE_FIELDS
from harness.squad_completion import CompletionError
from tests.unit.test_managed_strategy_publication import (
    case, enrolled, turn_prepared, prepared, checkpoint_case,
    test_strategy_publishes_and_hands_off_without_running_alignment as complete_strategy,
)


def parent(case, state=None, source=None):
    root, store, _, _ = case
    state = store.load() if state is None else state
    source = {key: state["last_dispatch"][key] for key in SOURCE_FIELDS} if source is None else source
    function = getattr(assessment, "require_alignment_parent", None)
    assert callable(function), "Alignment must authenticate its released strategy predecessor"
    return function(root, store.squad_dir, state, source)


def assert_alignment_parent(case, *, admitted=True):
    _, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    if not admitted:
        forged = deepcopy(before)
        forged.update(phase="phase2-tracker-alignment", status="running", feasibility_verdict="PASS")
        with pytest.raises((ValueError, CompletionError)): parent(case, forged)
    else:
        binding = parent(case)
        assert binding.producer == "strategy" and binding.recovery["version"] == 35
        assert binding.candidate["routing"] == dict(verdict="DONE", state_updates={})
        for damage in ("phase", "status", "cancelled", "unfinished", "source", "receipt", "parent", "attempts",
                "typed_attempts", "iteration", "typed_iteration", "cap", "override", "pending", "verdict"):
            changed = deepcopy(before)
            source = {key: before["last_dispatch"][key] for key in SOURCE_FIELDS}
            if damage == "phase": changed["phase"] = "phase3-specialists"
            elif damage == "status": changed["status"] = "blocked"
            elif damage == "cancelled": changed["cancel_requested"] = True
            elif damage == "unfinished": changed["last_dispatch"]["post_dispatch_complete"] = False
            elif damage == "source": source["dispatch_id"] = "0" * 32
            elif damage == "receipt": changed["last_dispatch"]["completion_intent_sha256"] = "0" * 64
            elif damage == "parent": changed["last_dispatch"]["phase_id"] = "phase2-feasibility-structural"
            elif damage == "attempts": changed["feasibility_structural_attempts"] += 1
            elif damage == "typed_attempts": changed["feasibility_structural_attempts"] = float(before["feasibility_structural_attempts"])
            elif damage == "iteration": changed["iteration"] += 1
            elif damage == "typed_iteration": changed["iteration"] = float(before["iteration"])
            elif damage == "cap": changed["max_iterations"] += 1
            elif damage == "override": changed["governance"] = {"enabled": False}
            elif damage == "pending": changed["_spec_step_effect_plan"] = {}
            else: changed["feasibility_verdict"] = "DEFER"
            with pytest.raises((ValueError, CompletionError)): parent(case, changed, source)
    assert store.load() == before and identity.identity_history(spec_id="game") == history


def capture(case, **changes):
    from harness.discovery_bootstrap_state import bootstrap_from_state
    from harness.discovery_operation import _capture
    from tests.unit.test_managed_checkpoint_assess import selection
    root, store, identity, _ = case
    return _capture(root, store, identity, bootstrap_from_state(store.load()), selection(case)["input_tree"],
        **{**dict(artifact_paths=("intent-alignment-check.md",), producer="alignment"), **changes})


def assert_alignment_capture(case):
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    fingerprint, baseline, evidence, captured_history, templates, runtime, sources, inputs = capture(case)
    assert set(templates) == {"intent-alignment-check.md"} and templates["intent-alignment-check.md"]
    assert {"spec.md", "user-intent.md", "feasibility.md", "mvp-scope.md", "strategic-overview.md"} <= baseline.keys()
    assert captured_history == history and not sources.publication.operations
    assert inputs["authority"]["source_context"]["operation_id"] == "discovery-completion-" + before["last_dispatch"]["dispatch_id"]
    assert runtime["autonomy_mode"] == before["autonomy_mode"] and len(fingerprint) == 64
    journal = "runs/first/reasoning-journal.jsonl"
    assert evidence[journal]
    for changes in (dict(artifact_paths=("user-intent.md",)), dict(clarification=True), dict(repair_unit="a" * 64),
            dict(source_completion={key: "0" * (32 if key == "dispatch_id" else 64) for key in SOURCE_FIELDS})):
        with pytest.raises((ValueError, CompletionError)): capture(case, **changes)
    assert store.load() == before and identity.identity_history(spec_id="game") == history
    assert "managed_alignment_rounds" not in before


def assert_alignment_capture_refuses_drift(case):
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    paths = ["specs/game/user-intent.md", "specs/game/mvp-scope.md", "specs/game/strategic-overview.md",
        "runs/first/context/current-feature-context.md"]
    if (root / "specs/game/feasibility-structural-report.json").exists():
        paths.append("specs/game/feasibility-structural-report.json")
    for relative in paths:
        path = root / relative
        content, stat = path.read_bytes(), path.stat()
        try:
            path.write_bytes(content + b"\nchanged after strategy release\n")
            with pytest.raises((ValueError, CompletionError)): capture(case)
        finally:
            path.write_bytes(content)
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert store.load() == before and identity.identity_history(spec_id="game") == history
    assert not before["phase_dispatch_counts"].get("phase2-tracker-alignment")


def test_alignment_rejects_phase_label_without_released_strategy():
    function = getattr(assessment, "require_alignment_parent", None)
    assert callable(function), "Alignment must authenticate its released strategy predecessor"
    with pytest.raises(ValueError):
        function(Path("/absent"), Path("/absent/runs/first"), dict(phase="phase2-tracker-alignment", status="running"), {})


@pytest.mark.parametrize("provider,mode,enabled,policy", [
    ("codex", "guided", False, "disabled"), ("claude", "banzai", True, "warn")])
def test_alignment_captures_only_released_strategy(checkpoint_case, provider, mode, enabled, policy):
    complete_strategy(checkpoint_case, provider, mode, enabled, policy)
    assert_alignment_parent(checkpoint_case)
    assert_alignment_capture(checkpoint_case)
    assert_alignment_capture_refuses_drift(checkpoint_case)
