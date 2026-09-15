"""Retained context ancestry uses real completed runs and publication proofs."""
from contextlib import closing, contextmanager
from copy import deepcopy
import hashlib
import json
import sqlite3

import pytest

from tests.unit.test_managed_synthesizer import (
    case, enrolled, turn_prepared, prepared, checkpoint_case,
    controller, selection, install_synthesis, SynthesisExecutor,
)
from harness.discovery_bootstrap_state import bootstrap_from_state
from harness.discovery_completion import released_discovery_input_projectors
from harness.discovery_inputs import admit_runtime_inputs, runtime_input_paths
from harness.discovery_producer import SOURCE_FIELDS
from harness.squad_publication import load_prepared_publication
from harness.squad_source_snapshot import inspect_project_tree
from harness.squad_completion import CompletionError


@contextmanager
def captured(case):
    root, store, _, _ = case
    selected = bootstrap_from_state(store.load())["selection"]
    capture = load_prepared_publication(root, store.squad_dir, selected["capture_marker"])
    trees, files = runtime_input_paths(root, store.squad_dir)
    with capture.inspect_sources(tree_paths=(selected["spec_path"], *trees), file_paths=files) as sources:
        yield sources


def context_tree(sources):
    return next(tree for tree in sources.trees if tree.path.endswith("/context"))


@pytest.fixture
def synthesized(checkpoint_case):
    install_synthesis(checkpoint_case)
    executor = SynthesisExecutor()
    result = controller(checkpoint_case, executor).run(managed_discovery={**selection(checkpoint_case),
        "through_phase": "phase1-synthesizer"}, create_managed_discovery=True)
    assert result.phase == "phase1-modeler", result
    return checkpoint_case, executor


def source_for(state):
    return {key: state["last_dispatch"][key] for key in SOURCE_FIELDS}


@pytest.mark.parametrize("checkpoint", [False, True])
def test_synthesis_context_traces_to_original_input_without_rewriting_live_sources(checkpoint_case, checkpoint):
    case = checkpoint_case
    root, store, identity, _ = case
    if not checkpoint:
        state = store.load()
        for key in ("spec_dir", "checkpoint_policy_version", "phase_completion_outcomes"):
            state.pop(key)
        store.save(state)
    with inspect_project_tree(root, (store.squad_dir / "context").relative_to(root).as_posix()) as original_context:
        pass
    install_synthesis(case)
    executor = SynthesisExecutor()
    result = controller(case, executor).run(managed_discovery={**selection(case),
        "through_phase": "phase1-synthesizer"}, create_managed_discovery=True)
    assert result.phase == "phase1-modeler", result
    state = store.load()
    history = identity.identity_history(spec_id="game")
    retained = {path: path.read_bytes() for path in store.squad_dir.glob("*-turns.json")}
    source = source_for(state)
    spec_view, runtime_view = released_discovery_input_projectors(root, store.squad_dir, state, source=source)
    with captured(case) as current:
        live_context = context_tree(current)
        assert live_context != original_context
        assert any(b"U-000001" in item.content for item in live_context.files)
        projected = runtime_view(current)
        assert context_tree(projected) == original_context
        runtime, _ = admit_runtime_inputs(root, store.squad_dir, state, projected)
        assert runtime["mode"] == "greenfield"
        spec = next(tree for tree in current.trees if tree.path == "specs/game")
        assert any(item.path.endswith("unknowns.md") for item in spec_view(spec).files)
        assert projected.files == current.files
        assert tuple(tree for tree in projected.trees if tree.path != live_context.path) == tuple(
            tree for tree in current.trees if tree.path != live_context.path)
    with captured(case) as after:
        assert after == current
    assert store.load() == state and identity.identity_history(spec_id="game") == history
    assert {path: path.read_bytes() for path in retained} == retained
    assert state["token_usage"] == 42 and len(executor.calls) == 6
    assert not list((store.squad_dir / ".completion-outbox").iterdir())


@pytest.mark.parametrize("damage", ["missing_proof", "legacy_without_proof", "receipt_hash", "foreign_completion"])
def test_current_context_cannot_outlive_its_parent_completion_proof(synthesized, damage):
    case, executor = synthesized
    root, store, identity, _ = case
    state = store.load()
    history = identity.identity_history(spec_id="game")
    parent = "discovery-completion-" + state["managed_synthesizer_source"]["dispatch_id"]
    retained = identity.identity_publication(spec_id="game", operation_id=parent)
    proof = json.loads(retained["completion_payload"])
    if damage == "missing_proof":
        del proof["proof"]
    elif damage == "legacy_without_proof":
        proof = dict(version=1, completion=proof["completion"])
    elif damage == "receipt_hash":
        proof["completion"]["receipts_sha256"] = "f" * 64
    else:
        current = identity.identity_publication(spec_id="game",
            operation_id="discovery-completion-" + state["last_dispatch"]["dispatch_id"])
        proof = json.loads(current["completion_payload"])
    raw = json.dumps(proof, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    # Corrupt the retained completion, not its storage checksum. This isolates
    # ancestry authentication from the already-tested SQLite checksum gate.
    with closing(sqlite3.connect(root / ".echelon/identity/registry.sqlite3")) as connection:
        connection.execute("UPDATE publication_intents SET completion_payload=?, completion_payload_sha256=? WHERE operation_id=?",
            (raw, hashlib.sha256(raw.encode("utf-8")).hexdigest(), parent))
        connection.commit()
    identity.check_managed_context(spec_id="game", run_id="first", record=state["managed_identity"])
    with pytest.raises(CompletionError):
        released_discovery_input_projectors(root, store.squad_dir, state, source=source_for(state))
    assert store.load() == state and identity.identity_history(spec_id="game") == history
    assert len(executor.calls) == 6 and state["token_usage"] == 42
    assert identity.identity_publication(spec_id="game", operation_id=parent)["completion_payload"] == raw


@pytest.mark.parametrize("damage", ["context", "context_mode", "context_missing", "spec", "ledger", "source"])
def test_ancestry_does_not_hide_current_source_drift(synthesized, damage):
    case, executor = synthesized
    root, store, identity, _ = case
    state = store.load()
    history = identity.identity_history(spec_id="game")
    source = source_for(state)
    context = store.squad_dir / "context/current-feature-context.md"
    if damage == "context": context.write_text("Foreign U-000001\n")
    elif damage == "context_mode": context.chmod(0o777)
    elif damage == "context_missing": context.unlink()
    elif damage == "spec": (root / "specs/game/unknowns.md").write_text("### U-000001: Foreign question\n")
    elif damage == "ledger": (root / "specs/game/.echelon/checkpoints.json").write_text("{}")
    else: source["completion_receipts_sha256"] = "f" * 64
    with pytest.raises((CompletionError, ValueError)):
        spec_view, runtime_view = released_discovery_input_projectors(root, store.squad_dir, state, source=source)
        with captured(case) as sources:
            spec_view(next(tree for tree in sources.trees if tree.path == "specs/game"))
            runtime_view(sources)
    assert store.load() == state and identity.identity_history(spec_id="game") == history
    assert len(executor.calls) == 6


def test_ancestor_checkpoint_proof_keeps_its_original_encoding(checkpoint_case, monkeypatch):
    from harness.element_identity_store import IdentityStore
    root, store, identity, _ = checkpoint_case
    original_release = IdentityStore.release_identity_publication
    retained = {}
    def old_release(self, **kwargs):
        if not retained:
            proof = json.loads(kwargs["completion_payload"])
            legacy = dict(version=2, completion=proof["completion"], checkpoint=proof["proof"])
            kwargs["completion_payload"] = json.dumps(legacy, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            retained.update(deepcopy(kwargs))
        return original_release(self, **kwargs)
    install_synthesis(checkpoint_case)
    executor = SynthesisExecutor()
    with monkeypatch.context() as patch:
        patch.setattr(IdentityStore, "release_identity_publication", old_release)
        result = controller(checkpoint_case, executor).run(managed_discovery={**selection(checkpoint_case),
            "through_phase": "phase1-synthesizer"}, create_managed_discovery=True)
    assert result.phase == "phase1-modeler", result
    state = store.load()
    _, runtime_view = released_discovery_input_projectors(root, store.squad_dir, state, source=source_for(state))
    with captured(checkpoint_case) as sources:
        admit_runtime_inputs(root, store.squad_dir, state, runtime_view(sources))
    assert identity.identity_publication(spec_id="game", operation_id=retained["operation_id"])["completion_payload"] == retained["completion_payload"]
    assert len(executor.calls) == 6 and store.load() == state
