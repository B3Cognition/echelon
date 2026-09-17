"""Shared Constitution publication through the real managed controller."""
from dataclasses import replace
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.unit.test_managed_why1 import (
    case, enrolled, turn_prepared, prepared, checkpoint_case, controller,
    selection, install_why1, Why1Executor, ScriptedExecutor,
)
from tests.unit.test_managed_constitution_contract import CONSTITUTION


class ConstitutionExecutor(Why1Executor):
    def run_inspection_turn(self, *args, **kwargs):
        assignment = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])["assignment"]
        if assignment.get("producer") != "constitution":
            return super().run_inspection_turn(*args, **kwargs)
        response = ScriptedExecutor.run_inspection_turn(self, *args, **kwargs)
        if assignment["step"] == "propose":
            fields = dict(new_subjects=[], revisions=[])
        elif assignment["step"] == "author":
            fields = dict(artifacts={"constitution.md": self.calls[-1]["context"]["baseline"].get("constitution.md", CONSTITUTION)})
        else:
            fields = dict(verdict="accept", reason="Concrete project policy preserves shared governance.", assessments=[])
        return replace(response, stdout=json.dumps({**assignment, "action": "final", **fields}))


def install_constitution(case):
    install_why1(case)
    repo = Path(__file__).resolve().parents[2]
    for relative in ("prosaic/subagents/echelon.constitution-producer.md",
            "prosaic/subagents/echelon.constitution-reviewer.md", "runtime/templates/constitution-template.md"):
        destination = case[0] / ".echelon" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((repo / relative).read_bytes())


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_constitution_canonical_publication_and_exact_restart(checkpoint_case, provider):
    root, store, identity, _ = checkpoint_case
    install_constitution(checkpoint_case)
    if provider == "claude":
        (root / ".echelon/constitution.md").write_text(CONSTITUTION)
        (root / ".echelon/constitution.md").chmod(0o640)
    executor = ConstitutionExecutor(provider)
    request = {**selection(checkpoint_case), "through_phase": "phase1-constitution"}
    result = controller(checkpoint_case, executor).run(managed_discovery=request, create_managed_discovery=True)
    assert result.phase == "phase1-what", result
    assert (root / ".echelon/constitution.md").read_text() == CONSTITUTION
    assert not (root / "specs/game/constitution.md").exists()
    saved, history = store.load(), identity.identity_history(spec_id="game")
    assert saved["constitution_status"] == "exists"
    assert saved["token_usage"] == 105 and len(executor.calls) == 15
    assert controller(checkpoint_case, executor).run(managed_discovery=request).phase == "phase1-what"
    assert store.load() == saved and identity.identity_history(spec_id="game") == history
    assert len(executor.calls) == 15
    if provider == "claude":
        assert (root / ".echelon/constitution.md").stat().st_mode & 0o777 == 0o640
    assert_retained_constitution(root, store, identity)


def assert_retained_constitution(root, store, identity):
    from harness.discovery_completion import decode_binding, released_discovery_input_projectors
    from harness.discovery_producer import SOURCE_FIELDS
    from harness.element_identity_publication import encode_publication_request
    from harness.squad_completion import CompletionError, _validate_intent
    from harness.squad_publication import load_prepared_publication
    state = store.load()
    source = {key: state["last_dispatch"][key] for key in SOURCE_FIELDS}
    row = identity.identity_publication(spec_id="game", operation_id="discovery-completion-" + source["dispatch_id"])
    retained = json.loads(row["completion_payload"])
    intent = retained["proof"]["intent"]
    publication = intent["publication"]
    binding = decode_binding(publication, state=state)
    assert binding.producer == "constitution" and binding.recovery["version"] == 12
    assert binding.candidate["history"] == binding.source["history"]
    assert binding.candidate["operations"] == []
    for damage in ("version", "producer", "source", "target", "history"):
        changed = deepcopy(binding.recovery)
        if damage == "version": changed["version"] = 3
        elif damage == "producer": changed["producer"] = "synthesizer"
        elif damage == "source": changed["source_completion"]["dispatch_id"] = "0" * 32
        else:
            candidate = json.loads(changed["candidate_inputs"])
            if damage == "target": candidate["artifacts"]["config.yml"] = candidate["artifacts"].pop("constitution.md")
            else: candidate["history"] = {"payload": "{}", "sha256": "0" * 64}
            changed["candidate_inputs"] = json.dumps(candidate, sort_keys=True, separators=(",", ":"))
        value = deepcopy(publication)
        value["managed_discovery"]["request"] = encode_publication_request(replace(binding.request,
            recovery_payload=json.dumps(changed, sort_keys=True, separators=(",", ":"))))
        with pytest.raises(CompletionError): decode_binding(value, state=state)
    for phase in ("phase1-discover", "phase1-constitution", "phase1-why2"):
        altered = deepcopy(intent)
        altered["route"]["to_phase"] = phase
        with pytest.raises(CompletionError): _validate_intent(altered)
    # A subsequent producer must authenticate the new canonical file before
    # using the original runtime view for historical domain admission.
    _, original_runtime = released_discovery_input_projectors(root, store.squad_dir, state, source=source)
    empty = load_prepared_publication(root, store.squad_dir, state["managed_discovery_bootstrap"]["selection"]["capture_marker"])
    with empty.inspect_sources(tree_paths=tuple(tree.path for tree in binding.sources.trees),
            file_paths=tuple(item.path for item in binding.sources.files)) as current:
        projected = original_runtime(current)
        shared, = (item for item in projected.files if item.path == ".echelon/constitution.md")
        before, = (item for item in binding.sources.files if item.path == shared.path)
        assert shared == before
    canonical = root / ".echelon/constitution.md"
    original = canonical.read_bytes()
    try:
        canonical.write_bytes(original + b"Unproven amendment.\n")
        with pytest.raises(ValueError):
            with empty.inspect_sources(tree_paths=tuple(tree.path for tree in binding.sources.trees),
                    file_paths=tuple(item.path for item in binding.sources.files)) as changed:
                original_runtime(changed)
    finally:
        canonical.write_bytes(original)


def test_constitution_interrupted_boundaries_keep_one_dispatch(checkpoint_case, monkeypatch):
    from harness.element_identity_store import IdentityStore
    from tests.unit.test_discovery_turns import Interrupted
    root, store, identity, _ = checkpoint_case
    install_constitution(checkpoint_case)
    executor = ConstitutionExecutor()
    ctrl = controller(checkpoint_case, executor)
    request = {**selection(checkpoint_case), "through_phase": "phase1-constitution"}
    targets = [(store, "advance_discovery_operation", "accepted"),
        (ctrl, "_prepare_controller_completion", "staged"), (store, "advance", "routed"),
        (IdentityStore, "apply_identity_publication", "promoted"),
        (ctrl, "_apply_controller_completion_effect", "context"),
        (store, "complete_controller_completion", "completed"),
        (IdentityStore, "release_identity_publication", "released")]
    for target, method, point in targets:
        original = getattr(target, method)
        def interrupt(*args, **kwargs):
            value = original(*args, **kwargs)
            selected = ((kwargs.get("producer") == "constitution" and args[1] == "finish") if point == "accepted" else
                kwargs.get("from_phase") == "phase1-constitution" if point == "staged" else
                (store.load().get("last_dispatch") or {}).get("phase_id") == "phase1-constitution")
            if point == "context":
                selected = selected and args[0].marker.step == "context"
            if selected:
                raise Interrupted()
            return value
        with monkeypatch.context() as patch:
            patch.setattr(target, method, interrupt)
            with pytest.raises(Interrupted):
                ctrl.run(managed_discovery=request, create_managed_discovery=point == "accepted")
        assert len(executor.calls) == 15
        assert store.load()["phase_dispatch_counts"]["phase1-constitution"] == 1
        if point == "accepted":
            before, history = store.load(), identity.identity_history(spec_id="game")
            for target in (root / ".echelon/constitution.md", root / ".echelon/runtime/templates/constitution-template.md"):
                raw = target.read_bytes() if target.exists() else None
                try:
                    target.write_bytes((raw or b"") + b"Changed after review\n")
                    assert ctrl.run(managed_discovery=request).status == "blocked"
                    assert store.load() == before and len(executor.calls) == 15
                    assert identity.identity_history(spec_id="game") == history
                finally:
                    if raw is None: target.unlink()
                    else: target.write_bytes(raw)
        if point in {"accepted", "staged", "routed"}:
            assert not (root / ".echelon/constitution.md").exists()
        else:
            assert (root / ".echelon/constitution.md").read_text() == CONSTITUTION
    result = controller(checkpoint_case, executor).run(managed_discovery=request)
    assert result.phase == "phase1-what", result
    assert store.load()["token_usage"] == 105 and len(executor.calls) == 15
    assert identity.pending_identity_publication(spec_id="game") is None
    assert_retained_constitution(root, store, identity)
