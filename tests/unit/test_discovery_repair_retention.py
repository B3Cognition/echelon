"""Repair prerequisites must not discard or reset accepted discovery history."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_discovery_normal_entry import (
    case, enrolled, turn_prepared, prepared, controller, selection,
    FullDiscoveryExecutor, Interrupted,
)
from tests.unit.test_discovery_checkpoint import checkpoint_case


def released(case):
    executor = FullDiscoveryExecutor()
    controller(case, executor).run(managed_discovery=selection(case), create_managed_discovery=True)
    state = case[1].load()
    assert state["last_dispatch"]["post_dispatch_complete"] is True
    row = case[2].identity_publication(spec_id="game",
        operation_id="discovery-completion-" + state["last_dispatch"]["dispatch_id"])
    return state, row, executor


@pytest.mark.parametrize("with_checkpoint", [False, True])
def test_new_completion_retains_full_proof_after_cleanup(prepared, checkpoint_case, with_checkpoint):
    # checkpoint_case shares the same fixture; remove only its selected policy
    # for the no-checkpoint branch, before any discovery is run.
    if not with_checkpoint:
        state = prepared[1].load()
        state.pop("spec_dir")
        state.pop("checkpoint_policy_version")
        state.pop("phase_completion_outcomes")
        prepared[1].save(state)
    state, row, _ = released(prepared)
    proof = json.loads(row["completion_payload"])
    assert proof["version"] == 3
    from harness.discovery_completion import released_discovery_projector
    from harness.squad_source_snapshot import inspect_project_tree
    project = released_discovery_projector(prepared[0], prepared[1].squad_dir, state)
    with inspect_project_tree(prepared[0], "specs/game") as tree:
        assert len(project(tree).files) == 7
    from harness.squad_completion import validate_retained_completion_proof, CompletionError
    damaged = deepcopy(proof["proof"])
    damaged["intent"]["route"]["to_phase"] = "phase1-what"
    with pytest.raises(CompletionError):
        validate_retained_completion_proof(proof["completion"], damaged["intent"], damaged["receipts"])
    assert not list((prepared[1].squad_dir / ".spec-step-effects").iterdir())


@pytest.mark.parametrize("version", [1, 2])
def test_old_release_retry_preserves_exact_payload(prepared, checkpoint_case, monkeypatch, version):
    from harness.element_identity_store import IdentityStore
    from harness.discovery_completion import released_discovery_projector
    from harness.squad_completion import CompletionError
    if version == 1:
        state = prepared[1].load()
        state.pop("spec_dir")
        state.pop("checkpoint_policy_version")
        state.pop("phase_completion_outcomes")
        prepared[1].save(state)
    original = IdentityStore.release_identity_publication
    saved = []
    def legacy_release(self, **kwargs):
        current = json.loads(kwargs["completion_payload"])
        legacy = dict(version=version, completion=current["completion"])
        if version == 2:
            legacy["checkpoint"] = current.get("proof", current.get("checkpoint"))
        kwargs["completion_payload"] = json.dumps(legacy, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        saved.append(kwargs["completion_payload"])
        original(self, **kwargs)
        raise Interrupted()
    executor = FullDiscoveryExecutor()
    with monkeypatch.context() as patch:
        patch.setattr(IdentityStore, "release_identity_publication", legacy_release)
        with pytest.raises(Interrupted):
            controller(prepared, executor).run(managed_discovery=selection(prepared), create_managed_discovery=True)
    controller(prepared, executor).run(managed_discovery=selection(prepared))
    state = prepared[1].load()
    row = prepared[2].identity_publication(spec_id="game",
        operation_id="discovery-completion-" + state["last_dispatch"]["dispatch_id"])
    assert row["completion_payload"] == saved[0]
    assert not list((prepared[1].squad_dir / ".spec-step-effects").iterdir())
    assert len(executor.calls) == 3 and state["token_usage"] == 21
    if version == 1:
        with pytest.raises(CompletionError):
            released_discovery_projector(prepared[0], prepared[1].squad_dir, state)
    else:
        assert callable(released_discovery_projector(prepared[0], prepared[1].squad_dir, state))


def repair_selection(state):
    dispatch = state["last_dispatch"]
    return dict(source={key: dispatch[key] for key in ("dispatch_id", "completion_intent_sha256",
        "completion_receipts_sha256", "completed_publication_binding_sha256")},
        origin=dict(review_id="why1-review-occurrence-1", return_phase="phase1-why1"),
        findings=[dict(key="camera-evidence", detail="Clarify the source for the camera decision."),
                  dict(key="camera-scope", detail="Limit the choice to the initial scene.")],
        artifact_paths=["unknowns.md"], editable_revisions=[["U-000001", "1"]])


def test_repair_selection_preserves_original_state_and_cannot_reset_budget(prepared):
    from harness.squad_state import StateAdvanceError, SquadStateStore
    state, _, _ = released(prepared)
    selected = repair_selection(state)
    store = prepared[1]
    original_receipts = {name: (store.squad_dir / name).read_bytes()
        for name in ("discovery-turns.json", "discovery-reservations.json")}
    store.prepare_discovery_repair(selected)
    saved = store.load()
    units = saved["managed_discovery_repairs"]["units"]
    unit, = units
    original_keys = ("managed_discovery_bootstrap", "managed_discovery_operation", "managed_discovery_turns", "managed_identity")
    for key in original_keys:
        assert saved[key] == state[key]
    reordered = deepcopy(selected)
    reordered["findings"].reverse()
    store.prepare_discovery_repair(reordered)
    assert store.load() == saved
    for number in range(1, 4):
        store.advance_discovery_repair(unit, "begin")
        before = store.load()
        SquadStateStore(store.squad_dir).advance_discovery_repair(unit, "begin")
        assert store.load() == before
        assert len(before["managed_discovery_repairs"]["units"][unit]["attempts"]) == number
        store.advance_discovery_repair(unit, "finish", result=dict(status="rejected",
            candidate_sha256=str(number) * 64, findings_sha256="b" * 64, progress_sha256=str(number) * 64))
    exhausted = store.load()
    store.prepare_discovery_repair(reordered)
    with pytest.raises(StateAdvanceError):
        store.advance_discovery_repair(unit, "begin")
    assert store.load() == exhausted
    for change in ("scope", "finding", "origin", "source"):
        altered = deepcopy(selected)
        if change == "scope": altered["editable_revisions"] = [["U-000001", "2"]]
        elif change == "finding": altered["findings"][0]["detail"] = "Different instruction"
        elif change == "origin": altered["origin"]["review_id"] = "new-id-to-reset-budget"
        else: altered["source"]["dispatch_id"] = "f" * 32
        with pytest.raises(StateAdvanceError):
            store.prepare_discovery_repair(altered)
        assert store.load() == exhausted
    for key in original_keys:
        assert exhausted[key] == state[key]
    assert {name: (store.squad_dir / name).read_bytes() for name in original_receipts} == original_receipts


def test_repair_state_cannot_be_removed_or_edited_by_generic_save(prepared):
    from harness.squad_state import StateAdvanceError
    state, _, _ = released(prepared)
    store = prepared[1]
    store.prepare_discovery_repair(repair_selection(state))
    saved = store.load()
    for remove in (True, False):
        changed = deepcopy(saved)
        if remove:
            del changed["managed_discovery_repairs"]
        else:
            unit, = changed["managed_discovery_repairs"]["units"].values()
            unit["selection"]["findings"][0]["detail"] = "Injected instruction"
        with pytest.raises(StateAdvanceError):
            store.save(changed)
        assert store.load() == saved


def test_repair_attempt_cannot_resume_without_selection(prepared):
    from harness.squad_state import StateAdvanceError
    released(prepared)
    saved = prepared[1].load()
    with pytest.raises(StateAdvanceError):
        prepared[1].advance_discovery_repair("a" * 64, "begin")
    assert prepared[1].load() == saved


def test_receipt_namespaces_preserve_original_and_other_units(tmp_path):
    from harness.discovery_receipts import DiscoveryReceiptFile
    for name in ("discovery-turns", "discovery-reservations"):
        for unit, content in ((None, "original"), ("a" * 64, "first repair"), ("b" * 64, "second repair")):
            with DiscoveryReceiptFile(tmp_path, name, repair_unit=unit) as file:
                assert file._read() is None
                file._write(content)
        for unit, content in ((None, "original"), ("a" * 64, "first repair"), ("b" * 64, "second repair")):
            with DiscoveryReceiptFile(tmp_path, name, repair_unit=unit) as file:
                assert file._read() == content
        with DiscoveryReceiptFile(tmp_path, name, repair_unit="c" * 64) as missing:
            assert missing._read() is None
            assert not missing.path.exists()
        for bad in ("../discovery-turns", "a" * 63, "A" * 64, True, ""):
            with pytest.raises(ValueError):
                DiscoveryReceiptFile(tmp_path, name, repair_unit=bad)


@pytest.mark.parametrize("last_status", ["accepted", "rejected"])
def test_finished_or_unchanged_repair_cannot_dispatch_again(prepared, last_status):
    from harness.squad_state import StateAdvanceError
    state, _, _ = released(prepared)
    store = prepared[1]
    store.prepare_discovery_repair(repair_selection(state))
    unit, = store.load()["managed_discovery_repairs"]["units"]
    for number in range(1, 2 if last_status == "accepted" else 3):
        store.advance_discovery_repair(unit, "begin")
        store.advance_discovery_repair(unit, "finish", result=dict(status=last_status,
            candidate_sha256=str(number) * 64, findings_sha256=str(number) * 64, progress_sha256="f" * 64))
    saved = store.load()
    with pytest.raises(StateAdvanceError):
        store.advance_discovery_repair(unit, "begin")
    assert store.load() == saved


def test_repair_selection_rejects_malformed_or_stale_claims_without_mutation(prepared):
    from harness.squad_state import StateAdvanceError
    state, _, _ = released(prepared)
    selected = repair_selection(state)
    for damage in ("duplicate", "extra", "phase", "path", "revision", "digest", "source"):
        altered = deepcopy(selected)
        if damage == "duplicate": altered["findings"].append(altered["findings"][0])
        elif damage == "extra": altered["extra"] = True
        elif damage == "phase": altered["origin"]["return_phase"] = "../../elsewhere"
        elif damage == "path": altered["artifact_paths"] = ["../unknowns.md"]
        elif damage == "revision": altered["editable_revisions"] = [["U-000001", 1]]
        elif damage == "digest": altered["source"]["completion_intent_sha256"] = "f" * 64
        else: altered["source"]["dispatch_id"] = "a" * 32
        with pytest.raises(StateAdvanceError):
            prepared[1].prepare_discovery_repair(altered)
        assert prepared[1].load() == state


@pytest.mark.parametrize("link", ["symlink", "hardlink"])
@pytest.mark.parametrize("target", ["record", "lock"])
def test_repair_receipts_reject_link_aliases(tmp_path, link, target):
    import os
    from harness.discovery_receipts import DiscoveryReceiptFile
    original = tmp_path / "original.json"
    original.write_text("do not change")
    file = DiscoveryReceiptFile(tmp_path, "discovery-turns", repair_unit="a" * 64)
    path = file.path if target == "record" else tmp_path / (file.name + ".lock")
    if link == "symlink": path.symlink_to(original)
    else: os.link(original, path)
    with pytest.raises((ValueError, OSError)):
        with file:
            file._read()
    assert original.read_text() == "do not change"


def test_interrupted_repair_state_commit_does_not_reset_attempt(prepared, monkeypatch):
    from harness.squad_state import SquadStateStore
    state, _, _ = released(prepared)
    store = prepared[1]
    selected = repair_selection(state)
    store.prepare_discovery_repair(selected)
    unit, = store.load()["managed_discovery_repairs"]["units"]
    original = store._confirm_durable_state_unlocked
    def stop_after(*args):
        original(*args)
        raise Interrupted()
    with monkeypatch.context() as patch:
        patch.setattr(store, "_confirm_durable_state_unlocked", stop_after)
        with pytest.raises(Interrupted):
            store.advance_discovery_repair(unit, "begin")
    interrupted = store.load()
    resumed = SquadStateStore(store.squad_dir)
    resumed.prepare_discovery_repair(selected)
    resumed.advance_discovery_repair(unit, "begin")
    assert resumed.load() == interrupted
    assert len(interrupted["managed_discovery_repairs"]["units"][unit]["attempts"]) == 1


@pytest.mark.parametrize("different_source", [False, True])
def test_load_rejects_impossible_multiple_repair_units(prepared, different_source):
    from harness.discovery_repair_state import normalize_selection
    from harness.squad_state import StateAdvanceError
    state, _, _ = released(prepared)
    store = prepared[1]
    store.prepare_discovery_repair(repair_selection(state))
    damaged = store.load()
    units = damaged["managed_discovery_repairs"]["units"]
    another = deepcopy(next(iter(units.values())))
    another["selection"]["origin"]["review_id"] = "second-origin"
    if different_source:
        another["selection"]["source"]["dispatch_id"] = "c" * 32
    key, another["selection"] = normalize_selection(state, another["selection"])
    if not different_source:
        # Only one unit is unfinished here, so duplicate-source rejection is
        # independently necessary rather than masked by the unfinished limit.
        next(iter(units.values()))["attempts"] = [dict(number=1, result=dict(status="accepted",
            candidate_sha256="a" * 64, findings_sha256="b" * 64, progress_sha256="c" * 64))]
    units[key] = another
    # Simulate corrupt retained bytes, not an authorized state-owner transition.
    store._path.write_text(json.dumps(damaged))
    with pytest.raises(StateAdvanceError):
        store.load()
