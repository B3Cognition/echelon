"""Managed Lexicon continuation from real WHY2 authority; providers are scripted."""
from dataclasses import replace
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from tests.unit.test_managed_why2 import (case, enrolled, turn_prepared, prepared,
    checkpoint_case, controller, selection, install_why2, Why2Executor, ScriptedExecutor)


def install_lexicon(case):
    install_why2(case)
    repo = Path(__file__).resolve().parents[2]
    for role in ("producer", "reviewer"):
        name = "echelon.lexicon-" + role + ".md"
        (case[0] / ".echelon/prosaic/subagents" / name).write_bytes(
            (repo / "prosaic/subagents" / name).read_bytes())


class LexiconExecutor(Why2Executor):
    def run_inspection_turn(self, *args, **kwargs):
        payload = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])
        assignment = payload["assignment"]
        if assignment.get("producer") != "lexicon":
            return super().run_inspection_turn(*args, **kwargs)
        assert payload["context"]["lexicon_source"] == dict(source_name="spec.md",
            source_sha256=hashlib.sha256(payload["context"]["baseline"]["spec.md"].encode("utf-8")).hexdigest())
        response = ScriptedExecutor.run_inspection_turn(self, *args, **kwargs)
        if assignment["step"] == "propose":
            fields = dict(new_subjects=[], revisions=[])
        elif assignment["step"] == "author":
            # Reference-safe but deliberately not valid Lexicon: grammar must
            # reach the native gate, not acquire certification from this reply.
            fields = dict(artifacts={"requirements.lexicon.md":
                "Uncertified translation of FR-000001, NFR-000001 and AC-000001.\n"},
                routing=dict(verdict="DONE", state_updates={}))
        else:
            fields = dict(verdict="accept", reason="No source identities changed; gate certification remains pending.",
                assessments=[])
        return replace(response, stdout=json.dumps({**assignment, "action": "final", **fields}))


def test_explicit_derivation_selection_admits_existing_bootstrap_without_dispatch(checkpoint_case):
    root, store, identity, _ = checkpoint_case
    install_lexicon(checkpoint_case)
    executor = LexiconExecutor()
    selected = {**selection(checkpoint_case), "through_phase": "phase1-lexicon-derive"}
    ctrl = controller(checkpoint_case, executor)
    ctrl._admit_managed_discovery(selected, True)
    state = store.load()
    assert state["phase"] == "phase1-discover"
    assert state["managed_discovery_bootstrap"]["selection"] == selected["bootstrap"]
    assert executor.calls == []
    assert identity.pending_identity_publication(spec_id="game") is None


def assert_retained_lexicon(root, store, identity):
    from harness.discovery_completion import decode_binding, released_discovery_input_projectors
    from harness.discovery_producer import SOURCE_FIELDS
    from harness.element_identity_publication import encode_publication_request
    from harness.squad_completion import CompletionError
    state = store.load()
    source = {key: state["last_dispatch"][key] for key in SOURCE_FIELDS}
    retained = identity.identity_publication(spec_id="game", operation_id="discovery-completion-" + source["dispatch_id"])
    publication = json.loads(retained["completion_payload"])["proof"]["intent"]["publication"]
    binding = decode_binding(publication, state=state)
    assert binding.producer == "lexicon" and binding.recovery["version"] == 28
    assert binding.candidate["operations"] == [] and binding.candidate["reservations"] == []
    assert binding.candidate["history"] == binding.source["history"]
    released_discovery_input_projectors(root, store.squad_dir, state, source=source)
    for damage in ("version", "producer", "source", "scope", "gate_authority", "identity"):
        recovery = deepcopy(binding.recovery)
        if damage == "version": recovery["version"] = True
        elif damage == "producer": recovery["producer"] = "what"
        elif damage == "source": recovery["source_completion"]["dispatch_id"] = "0" * 32
        else:
            candidate = json.loads(recovery["candidate_inputs"])
            if damage == "scope": candidate["artifacts"]["spec.md"] = "Unauthorized source change\n"
            elif damage == "gate_authority":
                candidate["routing"]["state_updates"] = {"lexicon_pass": True}
                recovery["review"]["routing"] = candidate["routing"]
            else:
                candidate["proposal"]["new_subjects"] = [dict(key="new", kind="FR", subject="New", caption="New")]
            recovery["candidate_inputs"] = json.dumps(candidate, sort_keys=True, separators=(",", ":"))
            recovery["candidate_sha256"] = hashlib.sha256(recovery["candidate_inputs"].encode("ascii")).hexdigest()
            recovery["operation"]["attempts"][-1]["result"]["candidate_sha256"] = recovery["candidate_sha256"]
        changed = deepcopy(publication)
        changed["managed_discovery"]["request"] = encode_publication_request(replace(binding.request,
            recovery_payload=json.dumps(recovery, sort_keys=True, separators=(",", ":"))))
        # The closed envelope itself refuses these claims even without mutable
        # state membership; rehashing does not confer source or gate authority.
        with pytest.raises(CompletionError):
            decode_binding(changed)
    with pytest.raises(CompletionError):
        released_discovery_input_projectors(root, store.squad_dir, state,
            source={**source, "completion_receipts_sha256": "0" * 64})
    assert store.load() == state


def test_derivation_entry_rejects_unproven_parent_before_any_work(checkpoint_case):
    from tests.unit.test_why1_tracker_parent import source
    root, store, identity, _ = checkpoint_case
    install_lexicon(checkpoint_case)
    executor = LexiconExecutor()
    selected = {**selection(checkpoint_case), "through_phase": "phase1-lexicon-derive"}
    ctrl = controller(checkpoint_case, executor)
    ctrl._admit_managed_discovery(selected, True)
    state = store.load()
    state.update(phase="phase1-lexicon-derive", last_dispatch={**source("a"),
        "phase_id": "phase1-why2", "post_dispatch_complete": True})
    store.save(state)
    before, history = store.load(), identity.identity_history(spec_id="game")
    result = ctrl.run(managed_discovery=selected)
    assert result.summary == "managed_lexicon_selection_requires_reconciliation"
    assert store.load() == before and executor.calls == []
    assert identity.identity_history(spec_id="game") == history


def test_derivation_operation_cannot_treat_structural_selection_as_authority(checkpoint_case):
    from harness.discovery_operation import run_discovery_operation
    from tests.unit.test_managed_lexicon_rounds import select_parent
    from tests.unit.test_why1_tracker_parent import source
    root, store, identity, _ = checkpoint_case
    install_lexicon(checkpoint_case)
    executor = LexiconExecutor()
    selected = {**selection(checkpoint_case), "through_phase": "phase1-lexicon-derive"}
    controller(checkpoint_case, executor)._admit_managed_discovery(selected, True)
    before = select_parent(store)
    store.prepare_spec_round("lexicon", source("a"), expected_state=before)
    before, history = store.load(), identity.identity_history(spec_id="game")
    result = run_discovery_operation(root, store, executor, producer="lexicon", input_tree="inputs",
        artifact_paths=("requirements.lexicon.md",), unowned_writable_paths=("requirements.lexicon.md",),
        intent=dict(kind="derive", request="Translate the current approved specification"), create=True)
    assert result.status == "blocked" and result.reason == "lexicon_parent_requires_reconciliation"
    assert store.load() == before and executor.calls == []
    assert identity.identity_history(spec_id="game") == history


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_managed_derivation_publishes_only_projection_and_preserves_history(checkpoint_case, provider):
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    root, store, identity, _ = checkpoint_case
    install_lexicon(checkpoint_case)
    config = root / ".echelon/config.yml"
    value = yaml.safe_load(config.read_text())
    value["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.write_text(yaml.safe_dump(value))
    executor = LexiconExecutor(provider)
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why2"}
    result = controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True)
    assert result.phase == "phase1-lexicon-derive", result
    before = store.load()
    history = identity.identity_history(spec_id="game")
    sources = {path.name: path.read_bytes() for path in (root / "specs/game").iterdir()
        if path.is_file() and path.name != "spec-artifact-graph.json"}
    selected["through_phase"] = "phase1-lexicon-derive"
    result = controller(checkpoint_case, executor).run(managed_discovery=selected)
    assert result.phase == "phase1-lexicon", (result, store.load().get("controller_contract_error"))
    state = store.load()
    assert (root / "specs/game/requirements.lexicon.md").read_text() == (
        "Uncertified translation of FR-000001, NFR-000001 and AC-000001.\n")
    assert {name: (root / "specs/game" / name).read_bytes() for name in sources} == sources
    assert identity.identity_history(spec_id="game") == history
    assert len(executor.calls) == 24 and state["token_usage"] == 168
    assert state["last_dispatch"]["phase_id"] == "phase1-lexicon-derive"
    assert state["last_dispatch"]["post_dispatch_complete"] is True
    assert state.get("lexicon_attempts", 0) == before.get("lexicon_attempts", 0)
    assert not state.get("lexicon_pass")
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == "phase1-lexicon"
    assert store.load() == state and len(executor.calls) == 24
    assert identity.pending_identity_publication(spec_id="game") is None
    assert_retained_lexicon(root, store, identity)
