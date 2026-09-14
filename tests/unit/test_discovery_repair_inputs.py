"""Accepted input capture uses real discovery/publication, not synthetic proof."""
from contextlib import contextmanager
import json

import pytest

from tests.unit.test_discovery_repair_retention import (
    case, enrolled, turn_prepared, prepared, checkpoint_case, released, repair_selection,
    controller, selection, FullDiscoveryExecutor, Interrupted,
)


def capture_inputs(root, store, unit):
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    from harness.discovery_operation import capture_discovery_repair_inputs
    with PhaseAExecutionLock.acquire(root, "repair-input-test"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "repair-input-test"):
            return capture_discovery_repair_inputs(root, store, unit)


def selected(case):
    state, _, executor = released(case)
    case[1].prepare_discovery_repair(repair_selection(state))
    unit, = case[1].load()["managed_discovery_repairs"]["units"]
    return unit, executor


@pytest.mark.parametrize("checkpoint", [False, True])
def test_capture_accepts_only_proven_artifacts_graph_and_context(checkpoint_case, checkpoint):
    if not checkpoint:
        state = checkpoint_case[1].load()
        for key in ("spec_dir", "checkpoint_policy_version", "phase_completion_outcomes"):
            state.pop(key)
        checkpoint_case[1].save(state)
    unit, executor = selected(checkpoint_case)
    root, store, identity, _ = checkpoint_case
    state = store.load()
    history = identity.identity_history(spec_id="game")
    receipts = {name: (store.squad_dir / name).read_bytes()
        for name in ("discovery-turns.json", "discovery-reservations.json")}
    captured = capture_inputs(root, store, unit)
    _, before, evidence, actual_history, templates, runtime, sources, _ = captured
    assert set(before) == {"glossary.md", "mental-model.md", "boundaries.md", "assumptions.md", "unknowns.md", "reference-architectures.md"}
    assert "### U-000001: Camera choice" in before["unknowns.md"]
    context = store.squad_dir.relative_to(root).as_posix() + "/context/current-feature-context.md"
    assert "U-000001" in evidence[context]
    assert evidence[context] == (root / context).read_text()
    assert "unknowns.md" in templates
    assert actual_history == history and runtime["mode"] == "greenfield"
    spec, = (tree for tree in sources.trees if tree.path == "specs/game")
    assert any(item.path.endswith("/spec-artifact-graph.json") for item in spec.files)
    assert any("/.echelon/" in item.path for item in spec.files) == checkpoint
    assert store.load() == state and identity.identity_history(spec_id="game") == history
    assert len(executor.calls) == 3
    assert {name: (store.squad_dir / name).read_bytes() for name in receipts} == receipts
    assert capture_inputs(root, store, unit) == captured


@pytest.mark.parametrize("damage", ["graph", "graph_missing", "context", "context_missing", "context_mode",
    "metadata", "foreign_context", "memory", "source_binding", "unknown_unit"])
def test_capture_rejects_unproven_or_changed_inputs(checkpoint_case, damage):
    unit, executor = selected(checkpoint_case)
    from harness.discovery_inputs import DiscoveryInputError
    root, store, _, _ = checkpoint_case
    spec = root / "specs/game"
    context = store.squad_dir / "context"
    if damage == "graph": (spec / "spec-artifact-graph.json").write_text("{}")
    elif damage == "graph_missing": (spec / "spec-artifact-graph.json").unlink()
    elif damage == "context": (context / "current-feature-context.md").write_text("U-000001: Foreign meaning")
    elif damage == "context_missing": (context / "current-feature-context.md").unlink()
    elif damage == "context_mode": (context / "current-feature-context.md").chmod(0o777)
    elif damage == "metadata": (spec / ".echelon/checkpoints.json").write_text("{}")
    elif damage == "foreign_context":
        (root / "knowledge-base").mkdir(exist_ok=True)
        (root / "knowledge-base/foreign.md").write_text("See U-000001")
    elif damage == "memory": (root / ".echelon/config.yml").write_text("mempalace:\n  wing: foreign\n")
    elif damage == "source_binding":
        value = store.load()
        value["managed_discovery_repairs"]["units"][unit]["selection"]["source"]["completion_intent_sha256"] = "f" * 64
        store._path.write_text(json.dumps(value))
    else: unit = "f" * 64
    saved = store.load()
    with pytest.raises(DiscoveryInputError):
        capture_inputs(root, store, unit)
    assert store.load() == saved and len(executor.calls) == 3


@pytest.mark.parametrize("target", ["context", "state"])
def test_mutation_during_capture_cannot_return_a_snapshot(checkpoint_case, monkeypatch, target):
    unit, _ = selected(checkpoint_case)
    from harness.discovery_inputs import DiscoveryInputError
    from harness.squad_publication import PreparedSquadPublication
    original = PreparedSquadPublication.inspect_sources
    @contextmanager
    def changed(self, **kwargs):
        with original(self, **kwargs) as captured:
            yield captured
            if target == "context":
                (checkpoint_case[1].squad_dir / "context/current-feature-context.md").write_text("Changed during capture")
            else:
                state = checkpoint_case[1].load()
                state["user_message"] = "Changed during capture"
                checkpoint_case[1].save(state)
    monkeypatch.setattr(PreparedSquadPublication, "inspect_sources", changed)
    with pytest.raises(DiscoveryInputError):
        capture_inputs(checkpoint_case[0], checkpoint_case[1], unit)


def test_missing_repair_selection_cannot_read_accepted_inputs(checkpoint_case):
    from harness.discovery_inputs import DiscoveryInputError
    state, _, executor = released(checkpoint_case)
    with pytest.raises(DiscoveryInputError):
        capture_inputs(checkpoint_case[0], checkpoint_case[1], "f" * 64)
    assert checkpoint_case[1].load() == state and len(executor.calls) == 3


@pytest.mark.parametrize("version", [1, 2])
def test_capture_obeys_retained_legacy_proof_capability(checkpoint_case, monkeypatch, version):
    from harness.discovery_inputs import DiscoveryInputError
    from harness.element_identity_store import IdentityStore
    root, store, identity, _ = checkpoint_case
    if version == 1:
        state = store.load()
        for key in ("spec_dir", "checkpoint_policy_version", "phase_completion_outcomes"):
            state.pop(key)
        store.save(state)
    release = IdentityStore.release_identity_publication
    def legacy_release(self, **kwargs):
        current = json.loads(kwargs["completion_payload"])
        legacy = dict(version=version, completion=current["completion"])
        if version == 2:
            legacy["checkpoint"] = current["proof"]
        kwargs["completion_payload"] = json.dumps(legacy, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        release(self, **kwargs)
        raise Interrupted()
    executor = FullDiscoveryExecutor()
    with monkeypatch.context() as patch:
        patch.setattr(IdentityStore, "release_identity_publication", legacy_release)
        with pytest.raises(Interrupted):
            controller(checkpoint_case, executor).run(managed_discovery=selection(checkpoint_case), create_managed_discovery=True)
    controller(checkpoint_case, executor).run(managed_discovery=selection(checkpoint_case))
    store.prepare_discovery_repair(repair_selection(store.load()))
    saved = store.load()
    unit, = saved["managed_discovery_repairs"]["units"]
    operation = "discovery-completion-" + saved["last_dispatch"]["dispatch_id"]
    retained = identity.identity_publication(spec_id="game", operation_id=operation)["completion_payload"]
    if version == 1:
        with pytest.raises(DiscoveryInputError):
            capture_inputs(root, store, unit)
    else:
        captured = capture_inputs(root, store, unit)
        assert "U-000001" in captured[1]["unknowns.md"]
        assert "U-000001" in captured[2]["runs/first/context/current-feature-context.md"]
    assert store.load() == saved and len(executor.calls) == 3
    assert identity.identity_publication(spec_id="game", operation_id=operation)["completion_payload"] == retained
