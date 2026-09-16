"""Managed CHIEF has one shared target and no identity mutation authority."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from tests.unit.test_discovery_turns import case, enrolled
from tests.unit.test_why1_tracker_parent import source


CONSTITUTION = """# Isometric Game Constitution

## Core Principles
### Playable prototype
**Rule:** Movement MUST remain responsive in the browser.
**Rationale:** The initial scene exists to test movement and lighting.

## Project Constraints
Browser rendering only; no multiplayer services in the initial prototype.

## Delivery and Quality Gates
Every change MUST preserve the movement smoke test.

## Governance
Changes to these rules require an explicit reviewed amendment.

**Version**: 1.0.0 | **Ratified**: 2026-09-16 | **Last Amended**: 2026-09-16
"""


def assignment(step="propose"):
    from harness.discovery_semantics import DiscoveryAssignment
    return DiscoveryAssignment("constitution-" + "a" * 32, "attempt-1-" + step,
        "game", "first", step, "b" * 64, ("constitution.md",), producer="constitution")


def test_constitution_assignment_round_trips_without_identity_authority():
    from harness.discovery_semantics import decode_discovery_assignment, validate_discovery_reply
    for step in ("propose", "author", "review"):
        selected = assignment(step)
        assert decode_discovery_assignment(selected.identity()) == selected
        fields = dict(new_subjects=[], revisions=[]) if step == "propose" else (
            dict(artifacts={"constitution.md": CONSTITUTION}) if step == "author" else
            dict(verdict="accept", reason="Concrete browser constraints and quality gates.", assessments=[]))
        assert validate_discovery_reply({**selected.identity(), "action": "final", **fields}, selected)["action"] == "final"
    selected = assignment()
    with pytest.raises(ValueError):
        validate_discovery_reply({**selected.identity(), "action": "final", "revisions": [],
            "new_subjects": [dict(key="question", kind="U", subject="Camera", caption="Camera")]}, selected)
    for changed in (replace(selected, artifact_paths=("config.yml",)),
            replace(selected, editable_revisions=(("U-000001", "1"),)),
            replace(selected, assigned_ids=("U-000001",))):
        with pytest.raises(ValueError): changed.identity()


def test_shared_policy_candidate_preserves_existing_text_and_rejects_unsafe_text():
    from harness.discovery_candidate import author_artifacts
    selected = assignment("author")
    def candidate(text, before=None):
        return author_artifacts(selected, {**selected.identity(), "action": "final",
            "artifacts": {"constitution.md": text}}, before={"constitution.md": before})
    assert candidate(CONSTITUTION)[0].after_text == CONSTITUTION
    assert candidate(CONSTITUTION, CONSTITUTION)[0].before_text == CONSTITUTION
    for text in ("", "# [PROJECT_NAME] Constitution", CONSTITUTION + "See U-000001.\n"):
        with pytest.raises(ValueError): candidate(text)
    with pytest.raises(ValueError): candidate(CONSTITUTION + "New rule.\n", CONSTITUTION)


def test_constitution_selection_is_once_bound_and_operation_charges_once(enrolled):
    from harness.squad_state import StateAdvanceError
    from harness.discovery_operation_state import operation_from_state
    root, store, _, _ = enrolled
    state = store.load()
    state.update(phase="phase1-constitution", last_dispatch={**source("a"),
        "phase_id": "phase1-why1", "post_dispatch_complete": True})
    store.save(state)
    before = store.load()
    saved = store.prepare_constitution(source("a"), expected_state=before)
    assert store.prepare_constitution(source("a"), expected_state=saved) == saved
    assert saved["phase_dispatch_counts"] == before["phase_dispatch_counts"]
    with pytest.raises(StateAdvanceError): store.prepare_constitution(source("a"), expected_state=before)
    for changed in ({**saved, "managed_constitution_source": source("b")},
            {key: value for key, value in saved.items() if key != "managed_constitution_source"}):
        with pytest.raises(StateAdvanceError): store.save(changed)
    binding = dict(operation_id="constitution-" + "a" * 32, spec_id="game", run_id="first",
        input_tree="inputs", artifact_paths=["constitution.md"], editable_revisions=[],
        unowned_writable_paths=["constitution.md"], intent=dict(kind="constitute", request="Create shared policy"), fingerprint="b" * 64)
    begun = store.advance_discovery_operation(binding, "prepare", producer="constitution")
    assert operation_from_state(begun, "constitution")["binding"] == binding
    assert begun["phase_dispatch_counts"]["phase1-constitution"] == 1
    assert store.advance_discovery_operation(binding, "prepare", producer="constitution") == begun
    changed = deepcopy(begun)
    del changed["managed_constitution_operation"]
    with pytest.raises(StateAdvanceError): store.save(changed)


def test_constitution_refresh_keeps_original_authority_and_receipts(enrolled):
    from harness.discovery_operation_state import operation_from_state
    from harness.discovery_producer import tracker_round, producer_operation_id
    from harness.discovery_receipts import DiscoveryReceiptFile, receipt_round_operation_id
    from harness.squad_state import StateAdvanceError
    root, store, _, _ = enrolled
    state = store.load()
    state.update(phase="phase1-constitution", last_dispatch={**source("a"),
        "phase_id": "phase1-why1", "post_dispatch_complete": True})
    store.save(state)
    store.prepare_constitution(source("a"), expected_state=store.load())
    original_id = "constitution-" + "a" * 32
    binding = dict(operation_id=original_id, spec_id="game", run_id="first", input_tree="inputs",
        artifact_paths=["constitution.md"], editable_revisions=[], unowned_writable_paths=["constitution.md"],
        intent=dict(kind="constitute", request="Reaffirm shared policy"), fingerprint="b" * 64)
    store.advance_discovery_operation(binding, "prepare", producer="constitution")
    state = store.load()
    state["last_dispatch"] = {**source("b"), "phase_id": "phase1-why1", "post_dispatch_complete": True}
    store.save(state)
    with pytest.raises(StateAdvanceError):
        store.prepare_constitution(source("b"), expected_state=store.load())
    store.advance_discovery_operation(binding, "begin", producer="constitution")
    store.advance_discovery_operation(binding, "finish", producer="constitution",
        result=dict(status="accepted", candidate_sha256="c" * 64, findings_sha256="d" * 64))
    before = store.load()
    selected = store.prepare_constitution(source("b"), expected_state=before)
    assert store.prepare_constitution(source("b"), expected_state=selected) == selected
    refreshed_id = "constitution-refresh-" + "b" * 32
    assert producer_operation_id(selected, "constitution") == refreshed_id
    assert producer_operation_id(selected, "constitution", original_id) == original_id
    from harness.discovery_constitution import constitution_input_source, constitution_source
    assert constitution_source(selected) == source("a")
    assert constitution_input_source(selected) == source("b")
    assert constitution_input_source(selected, original_id) == source("a")
    assert operation_from_state(selected, "constitution") is None
    assert operation_from_state(selected, "constitution", operation_id=original_id) == before["managed_constitution_operation"]
    row = tracker_round(selected, producer="constitution")
    assert row["predecessor"] == original_id and row["source"] == source("b")
    first = DiscoveryReceiptFile(store.squad_dir, "discovery-turns", producer="constitution",
        round_operation_id=receipt_round_operation_id("constitution", original_id))
    second = DiscoveryReceiptFile(store.squad_dir, "discovery-turns", producer="constitution",
        round_operation_id=receipt_round_operation_id("constitution", refreshed_id))
    assert first.path.name == "constitution-turns.json" and second.path != first.path
    from harness.discovery_turns import read_discovery_usage
    first.path.write_text("Original receipt must not be read or changed by refresh accounting.\n")
    original_bytes = first.path.read_bytes()
    assert read_discovery_usage(store, "constitution") == dict(token_usage=0, dispatch_count=0)
    assert first.path.read_bytes() == original_bytes
    revised = {**binding, "operation_id": refreshed_id}
    begun = store.advance_discovery_operation(revised, "prepare", producer="constitution")
    assert begun["phase_dispatch_counts"]["phase1-constitution"] == 2
    assert store.advance_discovery_operation(revised, "prepare", producer="constitution") == begun
    marker = dict(schema_version=1, operation_id=refreshed_id, binding_sha256="e" * 64)
    begun = store.prepare_discovery_turns(marker, producer="constitution")
    assert store.prepare_discovery_turns(marker, producer="constitution") == begun
    assert tracker_round(begun, producer="constitution")["turns"] == marker
    with pytest.raises(StateAdvanceError):
        store.prepare_discovery_turns({**marker, "binding_sha256": "f" * 64}, producer="constitution")
    for key in ("managed_constitution_source", "managed_constitution_operation", "managed_constitution_turns"):
        assert begun.get(key) == before.get(key)
    for damage in ("drop", "source", "predecessor", "original"):
        changed = deepcopy(begun)
        if damage == "drop":
            del changed["managed_constitution_rounds"]
        elif damage == "original":
            changed["managed_constitution_operation"]["attempts"] = []
        else:
            active = changed["managed_constitution_rounds"]["rounds"][refreshed_id]
            active[damage] = source("c") if damage == "source" else refreshed_id
        with pytest.raises(StateAdvanceError):
            store.save(changed)


@pytest.mark.parametrize("operation_id", ["constitution-refresh-" + "a" * 31, "constitution-refresh-" + "A" * 32,
    "constitution-refresh-../escape", "constitution-other-" + "a" * 32, "why1-" + "a" * 32, False])
def test_constitution_refresh_receipts_reject_noncanonical_namespace(tmp_path, operation_id):
    from harness.discovery_receipts import DiscoveryReceiptFile, receipt_round_operation_id
    with pytest.raises(ValueError):
        receipt_round_operation_id("constitution", operation_id)
    with pytest.raises(ValueError):
        DiscoveryReceiptFile(tmp_path, "discovery-turns", producer="constitution", round_operation_id=operation_id)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("refresh,version", [(False, 6), (True, 6), (True, 11)])
def test_constitution_refresh_parent_requires_actual_refreshed_why1(enrolled, monkeypatch, refresh, version):
    from types import SimpleNamespace
    from harness.discovery_constitution import require_constitution_parent
    import harness.discovery_completion as completion
    root, store, _, _ = enrolled
    state = store.load()
    if refresh:
        state["managed_constitution_source"] = source("a")
    def parent(*args, **kwargs):
        assert kwargs["required_route"] == ("phase1-why1", "phase1-constitution")
        assert kwargs["source"] == source("b")
        return SimpleNamespace(producer="why1", clarification=False, recovery={"version": version}), None, None
    monkeypatch.setattr(completion, "_retained_input_projection", parent)
    if refresh and version != 11:
        with pytest.raises(ValueError):
            require_constitution_parent(root, store.squad_dir, state, source("b"))
    else:
        require_constitution_parent(root, store.squad_dir, state, source("b"))


@pytest.mark.parametrize("version", [12, 16])
def test_constitution_completion_cannot_route_outside_what(tmp_path, monkeypatch, version):
    from types import SimpleNamespace
    import harness.discovery_completion as discovery
    import harness.squad_completion as completion
    from tests.unit.test_squad_completion import _prepare_minimal
    _, _, sealed = _prepare_minimal(tmp_path)
    record = sealed.intent.to_dict()
    record["route"].update(from_phase="phase1-constitution", to_phase="phase1-what")
    publication = {"kind": "external", "managed_discovery": {}}
    # Isolate routing validation from the separately tested v12 decoder.
    monkeypatch.setattr(completion, "_validate_publication", lambda value: publication)
    monkeypatch.setattr(discovery, "decode_binding", lambda *args, **kwargs: SimpleNamespace(
        clarification=False, resolution_publication=False, producer="constitution", repair_unit=None, recovery={"version": version}))
    assert completion._validate_intent(record)["route"]["to_phase"] == "phase1-what"
    record["route"]["to_phase"] = "phase1-discover"
    with pytest.raises(completion.CompletionError): completion._validate_intent(record)
def test_constitution_refresh_accepts_only_authenticated_answer_descendants(monkeypatch):
    from types import SimpleNamespace
    from harness.discovery_constitution import require_refreshed_why1
    from harness.discovery_spec import clarification_source
    import harness.discovery_completion as completion
    import pytest
    receipt = dict(schema_version=1, decision_id="decision", completion_id="a" * 32,
        intent_sha256="b" * 64, receipts_sha256="c" * 64, publication_binding_sha256="d" * 64)
    source = clarification_source(receipt)
    original = {**source, "dispatch_id": "e" * 32}
    decision = {"id": "decision"}
    refresh = SimpleNamespace(producer="why1", clarification=False, recovery=dict(version=11,
        operation={"binding": {"operation_id": "why1-original"}}))
    answer = SimpleNamespace(producer="why1", clarification=True, recovery=dict(version=18,
        resolution=decision, operation=refresh.recovery["operation"], source_completion=original))
    review = SimpleNamespace(producer="why1", clarification=False, recovery=dict(version=6,
        source_completion=source, resolution=dict(decision=decision, completion=receipt),
        operation={"binding": {"operation_id": "why1-later"}}))
    monkeypatch.setattr("harness.discovery_constitution.tracker_predecessor", lambda *args: "why1-original")
    monkeypatch.setattr(completion, "_retained_input_projection", lambda *args, **kwargs:
        (answer if kwargs["source"] == source else refresh, None, None))
    require_refreshed_why1(None, None, {}, review, object())
    review.recovery["resolution"] = None
    with pytest.raises(ValueError):
        require_refreshed_why1(None, None, {}, review, object())
