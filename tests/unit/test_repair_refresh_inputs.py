"""Semantic dependency decisions and immutable accepted refresh inputs."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from tests.unit.test_repair_refresh_rounds import (
    case, enrolled, turn_prepared, prepared, checkpoint_case, controller,
    selection, install_why1, RepairExecutor, select_refresh,
)


def snapshot(text=b"Unknown", *, revision="2", metadata=b"old", context=b"old"):
    from harness.squad_source_snapshot import ProjectTreeSnapshot, ProjectFileSnapshot
    from harness.squad_publication_snapshot import PublicationImageDescriptor
    from harness.element_identity_snapshot import IdentityHistorySnapshot
    def file(path, data):
        return ProjectFileSnapshot(path, PublicationImageDescriptor("file", hashlib.sha256(data).hexdigest(), 0o644), data)
    trees = (
        ProjectTreeSnapshot("specs/game", True, (), (
            file("specs/game/unknowns.md", text),
            file("specs/game/spec-artifact-graph.json", metadata),
            file("specs/game/.echelon/checkpoint.json", metadata))),
        ProjectTreeSnapshot("run/context", True, (), (file("run/context/current-feature-context.md", context),)),
    )
    history = dict(version="1", spec_id="game", entities=[dict(element_id="U-000001", subject="Camera", revision=revision)],
        revisions=[dict(element_id="U-000001", revision=revision, content="Unknown", operation_id="old")],
        lineage=[], reference_claims=[], issue_occurrences=[])
    raw = json.dumps(history, sort_keys=True, separators=(",", ":"))
    return trees, (), IdentityHistorySnapshot(raw, hashlib.sha256(raw.encode()).hexdigest())


def view(values):
    from harness.discovery_refresh_inputs import dependency_view
    trees, files, history = values
    return dependency_view(trees=trees, files=files, history=history,
        spec_path="specs/game", run_path="run", runtime={"user_request": "Game"})


def test_dependency_comparison_ignores_only_derived_bookkeeping():
    from harness.discovery_refresh_inputs import compare_dependencies
    old = view(snapshot())
    new = view(snapshot(metadata=b"new checkpoint and graph", context=b"new phase and dispatch"))
    result = compare_dependencies(old, new)
    assert result["changed"] == []
    assert result["before_sha256"] == result["after_sha256"]
    trees, files, history = snapshot()
    value = json.loads(history.payload)
    value["revisions"][0]["operation_id"] = "another-publication"
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    changed_owner = replace(history, payload=raw, sha256=hashlib.sha256(raw.encode()).hexdigest())
    assert compare_dependencies(old, view((trees, files, changed_owner)))["changed"] == []


@pytest.mark.parametrize("change,want", [
    ({"text": b"Fixed camera"}, ["file:specs/game/unknowns.md"]),
    ({"revision": "3"}, ["identity"]),
])
def test_dependency_comparison_observes_content_and_exact_revisions(change, want):
    from harness.discovery_refresh_inputs import compare_dependencies
    result = compare_dependencies(view(snapshot()), view(snapshot(**change)))
    assert result["changed"] == want
    assert result["before_sha256"] != result["after_sha256"]


@pytest.mark.parametrize("field", ["subject", "reference_claims", "issue_occurrences"])
def test_dependency_comparison_preserves_identity_and_evidence(field):
    from harness.discovery_refresh_inputs import compare_dependencies
    trees, files, history = snapshot()
    value = json.loads(history.payload)
    if field == "subject":
        value["entities"][0]["subject"] = "Different subject"
    elif field == "reference_claims":
        value[field] = [dict(target_id="U-000001", target_revision="2", source_path="issues.md",
            source_anchor="ISS-000001", operation_id="publication", entry_index="1")]
    else:
        value[field] = [dict(issue_id="ISS-000001", issue_revision="1", report_id="review-occurrence",
            body="Unresolved camera", operation_id="publication", entry_index="1")]
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    changed = replace(history, payload=raw, sha256=hashlib.sha256(raw.encode()).hexdigest())
    assert compare_dependencies(view(snapshot()), view((trees, files, changed)))["changed"] == ["identity"]


def test_dependency_comparison_observes_external_files_and_absence():
    from harness.discovery_refresh_inputs import compare_dependencies, dependency_view
    from harness.squad_source_snapshot import ProjectPathSnapshot
    from harness.squad_publication_snapshot import PublicationImageDescriptor
    trees, _, history = snapshot()
    missing = ProjectPathSnapshot("run/staging/user-clarifications.md", PublicationImageDescriptor("missing", None, None), None)
    empty = replace(missing, content=b"", image=PublicationImageDescriptor("file", hashlib.sha256(b"").hexdigest(), 0o644))
    assert compare_dependencies(view((trees, (missing,), history)), view((trees, (empty,), history)))["changed"] == [
        "file:run/staging/user-clarifications.md"]
    changed_runtime = dependency_view(trees=trees, files=(), history=history,
        spec_path="specs/game", run_path="run", runtime={"user_request": "Different game"})
    assert compare_dependencies(view(snapshot()), changed_runtime)["changed"] == ["runtime"]


@pytest.mark.parametrize("method", ["reference_claims", "issue_occurrences"])
def test_dependency_comparison_ignores_binding_owner_but_not_evidence(method):
    from harness.discovery_refresh_inputs import compare_dependencies
    from harness.element_identity_binding_store import materialized_row
    payload = (dict(source_path="issues.md", source_sha256="a" * 64, source_anchor="ISS-000001",
        target_id="U-000001", target_revision="2", relation="evidence") if method == "reference_claims" else
        dict(issue_id="ISS-000001", issue_revision="1", report_id="original-review", report_sha256="a" * 64,
            display_id="ISS-000001", title="Camera", body="Unresolved camera"))
    trees, files, history = snapshot()
    def with_binding(operation, index, content):
        value = json.loads(history.payload)
        value[method] = [materialized_row("game", operation, index, content, method)]
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
        return view((trees, files, replace(history, payload=raw, sha256=hashlib.sha256(raw.encode()).hexdigest())))
    original = with_binding("old-operation", 1, payload)
    assert compare_dependencies(original, with_binding("new-operation", 2, payload))["changed"] == []
    change = {"target_revision": "3"} if method == "reference_claims" else {"report_id": "different-review"}
    assert compare_dependencies(original, with_binding("old-operation", 1, {**payload, **change}))["changed"] == ["identity"]


def bind_input(root, store, producer="synthesizer"):
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    from harness.discovery_repair_admission import bind_repair_refresh_input
    with PhaseAExecutionLock.acquire(root, "test-refresh-input"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-refresh-input"):
            return bind_repair_refresh_input(root, store, producer)


def test_input_owner_cannot_bind_without_a_retained_repair(enrolled):
    from harness.squad_state import StateAdvanceError
    _, store, _, _ = enrolled
    before = store.load()
    with pytest.raises(StateAdvanceError):
        store.bind_refresh_input("synthesizer", {}, expected_state=before)
    assert store.load() == before


def test_text_identical_repair_still_refreshes_new_review_evidence(checkpoint_case):
    """A no-op author must not hide the intervening WHY1 report and identities."""
    from harness.discovery_producer import tracker_round

    class NoopRepair(RepairExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            assignment = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])["assignment"]
            if assignment["operation_id"].startswith("discovery-repair-") and assignment["step"] == "review":
                from tests.unit.test_discovery_turns import ScriptedExecutor
                response = ScriptedExecutor.run_inspection_turn(self, *args, **kwargs)
                assert assignment["assigned_ids"] == []
                return replace(response, stdout=json.dumps({**assignment, "action": "final",
                    "verdict": "accept", "reason": "Existing question already records the required investigation.",
                    "assessments": []}))
            response = super().run_inspection_turn(*args, **kwargs)
            reply = json.loads(response.stdout)
            if reply["operation_id"].startswith("discovery-repair-") and reply["step"] == "author":
                reply["artifacts"] = {"unknowns.md": self.calls[-1]["context"]["baseline"]["unknowns.md"]}
            if reply["operation_id"].startswith("synthesizer-"):
                if reply["step"] == "propose":
                    reply["revisions"] = [dict(id="U-000001", expected_revision="2")]
                elif reply["step"] == "author":
                    reply["artifacts"] = {name: self.calls[-1]["context"]["baseline"][name]
                        for name in reply["artifact_paths"]}
            return replace(response, stdout=json.dumps(reply))

    root, store, identity, _ = checkpoint_case
    install_why1(checkpoint_case)
    executor = NoopRepair("codex")
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    assert controller(checkpoint_case, executor).run(managed_discovery=selected,
        create_managed_discovery=True).phase == "phase1-discover"
    original = (root / "specs/game/unknowns.md").read_bytes()
    entities = json.loads(identity.identity_history(spec_id="game").payload)["entities"]
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).summary == "managed_repair_dependency_refresh_not_supported"
    assert (root / "specs/game/unknowns.md").read_bytes() == original
    assert json.loads(identity.identity_history(spec_id="game").payload)["entities"] == entities
    select_refresh(root, store, "synthesizer")
    saved = bind_input(root, store)
    row = tracker_round(saved, producer="synthesizer")
    assert row["execution_input"]["dependencies"]["changed"] == [
        "file:specs/game/assumption-review.md", "file:specs/game/issues.md",
        "file:specs/game/user-intent.md", "identity"]
    assert row["operation"] is None and row["turns"] is None
    assert len(executor.calls) == 15
    from tests.unit.test_discovery_completion import controller as full_controller
    before_refresh = {path.name: path.read_bytes() for path in (root / "specs/game").glob("*.md")}
    result = full_controller(checkpoint_case, executor).run(managed_discovery=selected)
    assert result.summary == "managed_repair_refresh_complete", result
    assert {path.name: path.read_bytes() for path in (root / "specs/game").glob("*.md")} == before_refresh
    assert json.loads(identity.identity_history(spec_id="game").payload)["entities"] == entities
    saved = store.load()
    assert tracker_round(saved)["execution_input"]["dependencies"]["changed"] == [
        "file:specs/game/assumption-review.md", "file:specs/game/issues.md", "identity"]
    assert saved["token_usage"] == 147 and len(executor.calls) == 21


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_refresh_input_is_authenticated_once_without_dispatch(checkpoint_case, provider, monkeypatch):
    from harness.discovery_producer import tracker_round
    from harness.squad_state import SquadStateStore, StateAdvanceError
    root, store, identity, _ = checkpoint_case
    install_why1(checkpoint_case)
    executor = RepairExecutor(provider)
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    assert controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True).phase == "phase1-discover"
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).summary == "managed_repair_dependency_refresh_not_supported"
    select_refresh(root, store, "synthesizer")
    before = store.load()
    history = identity.identity_history(spec_id="game")
    original_bind = store.bind_refresh_input
    def concurrent_revision(*args, **kwargs):
        store.save(store.load())
        return original_bind(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(store, "bind_refresh_input", concurrent_revision)
        with pytest.raises(StateAdvanceError): bind_input(root, store)
    raced = store.load()
    assert raced["state_revision"] > before["state_revision"]
    assert "execution_input" not in tracker_round(raced, producer="synthesizer")
    before = raced
    saved = bind_input(root, store)
    row = tracker_round(saved, producer="synthesizer")
    from harness.discovery_producer import producer_operation_id, producer_component
    from harness.discovery_operation_state import operation_from_state
    from harness.discovery_turns import read_discovery_usage
    original_id = saved["managed_synthesizer_operation"]["binding"]["operation_id"]
    assert producer_operation_id(saved, "synthesizer") == saved["managed_synthesizer_rounds"]["active"]
    assert operation_from_state(saved, "synthesizer") is None
    assert producer_component(saved, "synthesizer", "turns") is None
    assert operation_from_state(saved, "synthesizer", operation_id=original_id) == saved["managed_synthesizer_operation"]
    assert read_discovery_usage(store, "synthesizer") == dict(token_usage=0, dispatch_count=0)
    bound = row["execution_input"]
    assert bound["source"] == row["refresh"]["repair_source"]
    assert bound["dependencies"]["changed"] == [
        "file:specs/game/assumption-review.md", "file:specs/game/issues.md",
        "file:specs/game/unknowns.md", "file:specs/game/user-intent.md", "identity"]
    from harness.discovery_completion import _retained_input_projection
    from harness.discovery_refresh_inputs import dependency_view
    from harness.element_identity_snapshot import IdentityHistorySnapshot
    prior_source = row["refresh"]["predecessor_source"]
    previous, _, _ = _retained_input_projection(root, store.squad_dir, saved, identity,
        operation_id="discovery-completion-" + prior_source["dispatch_id"], source=prior_source, require_checkpoint=False)
    wrong_preimages = dependency_view(trees=previous.sources.trees, files=previous.sources.files,
        history=IdentityHistorySnapshot(**previous.source["history"]), spec_path="specs/game",
        run_path=store.squad_dir.relative_to(root).as_posix(), runtime=previous.source["runtime"])
    wrong_digest = hashlib.sha256(json.dumps(wrong_preimages, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert bound["dependencies"]["before_sha256"] != wrong_digest
    assert row["operation"] is None and row["turns"] is None
    assert bind_input(root, SquadStateStore(store.squad_dir)) == saved
    for key in ("managed_discovery_repairs", "managed_synthesizer_source", "managed_synthesizer_operation",
            "managed_synthesizer_turns", "phase_dispatch_counts", "token_usage", "last_dispatch", "phase"):
        assert saved[key] == before[key]
    for damage in ("source", "dependencies", "remove"):
        changed = deepcopy(saved)
        active = changed["managed_synthesizer_rounds"]["rounds"][saved["managed_synthesizer_rounds"]["active"]]
        if damage == "remove": del active["execution_input"]
        elif damage == "source": active["execution_input"]["source"]["dispatch_id"] = "0" * 32
        else: active["execution_input"]["dependencies"]["changed"] = []
        with pytest.raises(StateAdvanceError): store.save(changed)
        assert store.load() == saved
    with pytest.raises(StateAdvanceError):
        store.bind_refresh_input("synthesizer", bound, expected_state=before)
    altered = deepcopy(bound)
    altered["dependencies"]["after_sha256"] = "0" * 64
    with pytest.raises(StateAdvanceError):
        store.bind_refresh_input("synthesizer", altered, expected_state=saved)
    for producer in ("tracker", "why1"):
        with pytest.raises(ValueError): bind_input(root, store, producer)
        assert store.load() == saved
    from harness.element_identity_store import IdentityStore
    original_publication = IdentityStore.identity_publication
    def damaged_proof(self, *args, **kwargs):
        result = original_publication(self, *args, **kwargs)
        if kwargs.get("operation_id") == "discovery-completion-" + bound["source"]["dispatch_id"]:
            result = {**result, "completion_payload": "{}"}
        return result
    with monkeypatch.context() as patch:
        patch.setattr(IdentityStore, "identity_publication", damaged_proof)
        with pytest.raises(ValueError): bind_input(root, store)
    assert store.load() == saved
    for target in (root / "specs/game/unknowns.md", store.squad_dir / "context/current-feature-context.md",
            root / ".echelon/runtime/templates/risks-template.md"):
        original = target.read_bytes()
        try:
            target.write_bytes(original + b"tampered\n")
            with pytest.raises(ValueError): bind_input(root, store)
            assert store.load() == saved
        finally:
            target.write_bytes(original)
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).summary == "managed_repair_dependency_refresh_not_supported"
    assert store.load() == saved and len(executor.calls) == 15
    assert identity.identity_history(spec_id="game") == history
