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


def test_constitution_completion_cannot_route_outside_what(tmp_path, monkeypatch):
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
        clarification=False, producer="constitution", repair_unit=None, recovery={"version": 12}))
    assert completion._validate_intent(record)["route"]["to_phase"] == "phase1-what"
    record["route"]["to_phase"] = "phase1-discover"
    with pytest.raises(completion.CompletionError): completion._validate_intent(record)
