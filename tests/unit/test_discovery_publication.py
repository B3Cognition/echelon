"""Reviewed discovery to real sealed publication; no Squad activation is mocked."""
from dataclasses import replace
import hashlib
import json
import stat

import pytest

from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
from harness.squad_source_baseline_codec import decode_initial_publication_sources
from tests.unit.test_discovery_operation import (
    case, enrolled, turn_prepared, prepared, execute, DiscoveryExecutor,
    seed_accepted_question,
)
from tests.unit.test_discovery_turns import ScriptedExecutor, Interrupted


def prepare(case, executor, *, completion_id="a" * 32):
    from harness.discovery_publication import prepare_discovery_publication
    with PhaseAExecutionLock.acquire(case[0], "test-publication"):
        with SpecRunExecutionLock.acquire(case[1].squad_dir, "test-publication"):
            return prepare_discovery_publication(case[0], case[1], executor, completion_id=completion_id)


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_only_reviewed_spec_outputs_and_exact_graph_are_sealed(prepared, provider):
    root, state, store, _ = prepared
    executor = DiscoveryExecutor(provider)
    reviewed = execute(prepared, executor, create=True)
    assert reviewed.status == "reviewed"
    before = state.load()
    history = store.identity_history(spec_id="game")
    package = prepare(prepared, executor)
    writes = {op.target: op.postimage_bytes for op in package.sources.publication.operations}
    assert set(writes) == {"specs/game/unknowns.md", "specs/game/assumptions.md", "specs/game/spec-artifact-graph.json"}
    assert writes["specs/game/unknowns.md"] == b"### U-000001: Camera choice\r\nShould movement follow the camera?\r\n"
    assert writes["specs/game/spec-artifact-graph.json"] == package.graph
    graph = json.loads(package.graph)
    assert graph["spec_id"] == "game"
    assert any(node["properties"].get("subject") == "Isometric projection choice" for node in graph["nodes"])
    audit, = (item for item in graph["inputs"] if item["role"] == "memory_audit_report")
    assert audit["status"] == "unavailable"
    assert package.request.proposed_history_sha256 == reviewed.candidate.history.sha256
    assert package.request.manifest_sha256 == package.publication.marker.manifest_sha256
    read_paths = {item.path for item in package.sources.files}
    assert {".echelon/config.yml", ".echelon/constitution.md", "re"} <= read_paths
    spec_baseline = decode_initial_publication_sources(package.request.sources.baseline_payload)
    assert [tree.path for tree in spec_baseline.trees] == ["specs/game"] and spec_baseline.files == ()
    recovery = json.loads(package.request.recovery_payload)
    assert recovery["completion_id"] == "a" * 32
    assert decode_initial_publication_sources(recovery["sources"]) == package.sources
    assert recovery["candidate_sha256"] == reviewed.candidate.candidate_sha256
    assert list((root / "specs/game").iterdir()) == []
    assert store.identity_history(spec_id="game") == history and state.load() == before
    assert store.pending_identity_publication(spec_id="game") is None
    assert len(executor.calls) == 3


def test_real_v3_source_owner_accepts_spec_baseline_with_full_read_guard(prepared):
    root, state, store, _ = prepared
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    package = prepare(prepared, executor)
    # This fixture supplies explicit test-only publication authority. Production
    # still needs authenticated pending Squad completion before invoking it.
    with PhaseAExecutionLock.acquire(root, "fixture-publish"):
        with SpecRunExecutionLock.acquire(state.squad_dir, "fixture-publish"):
            package.publication.publish_sources(package.sources,
                before_publish=lambda _: store.prepare_identity_publication(
                    spec_id="game", operation_id="fixture-publish", request=package.request),
                after_publish=lambda _: store.apply_identity_publication(spec_id="game", operation_id="fixture-publish"))
    assert store.identity_history(spec_id="game") == package.candidate.history
    assert (root / "specs/game/spec-artifact-graph.json").read_bytes() == package.graph
    assert store.pending_identity_publication(spec_id="game")["state"] == "applied"
    assert "pending_controller_completion" not in state.load()
    assert len(executor.calls) == 3


def test_preparation_cannot_start_discovery_or_consume_an_attempt(prepared):
    executor = DiscoveryExecutor()
    before = prepared[1].load()
    with pytest.raises(ValueError): prepare(prepared, executor)
    assert executor.calls == [] and prepared[1].load() == before


@pytest.mark.parametrize("completion_id", ["", "a" * 31, "G" * 32, None, True])
def test_invalid_completion_proposal_is_not_a_stage_selector(prepared, completion_id):
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    before = prepared[1].load()
    with pytest.raises(ValueError): prepare(prepared, executor, completion_id=completion_id)
    assert len(executor.calls) == 3 and prepared[1].load() == before


@pytest.mark.parametrize("damage", ["config", "input", "source", "turns", "reservations", "role"])
def test_missing_or_changed_review_inputs_do_not_become_publication_authority(prepared, damage):
    root, state, store, _ = prepared
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    path = {"config": root / ".echelon/config.yml", "input": root / "inputs/task.md",
        "source": root / "specs/game/unknowns.md", "turns": state.squad_dir / "discovery-turns.json",
        "reservations": state.squad_dir / "discovery-reservations.json",
        "role": root / ".echelon/prosaic/subagents/echelon.discovery-reviewer.md"}[damage]
    if damage in {"turns", "reservations"}: path.unlink()
    else: path.write_text("changed")
    with pytest.raises(ValueError): prepare(prepared, executor)
    assert len(executor.calls) == 3 and store.pending_identity_publication(spec_id="game") is None
    assert "pending_external_publication" not in state.load()


def test_preparation_retry_replays_review_without_new_model_work(prepared):
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    first = prepare(prepared, executor)
    second = prepare(prepared, executor)
    assert first.publication.marker != second.publication.marker
    assert first.graph == second.graph and first.candidate == second.candidate
    assert len(executor.calls) == 3
    assert list((prepared[0] / "specs/game").iterdir()) == []


def test_preparation_does_not_rewrite_completed_provider_receipts(prepared):
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    path = prepared[1].squad_dir / "discovery-turns.json"
    before, content = path.stat(), path.read_bytes()
    prepare(prepared, executor)
    after = path.stat()
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    assert path.read_bytes() == content and len(executor.calls) == 3


def test_existing_identity_publication_cannot_be_reselected(prepared):
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    first = prepare(prepared, executor)
    prepared[2].prepare_identity_publication(spec_id="game", operation_id="selected", request=first.request)
    before = prepared[2].pending_identity_publication(spec_id="game")
    with pytest.raises(ValueError): prepare(prepared, executor)
    assert prepared[2].pending_identity_publication(spec_id="game") == before
    assert len(executor.calls) == 3


def test_existing_squad_publication_is_not_reselected(prepared):
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    package = prepare(prepared, executor)
    state = prepared[1]
    state.begin_external_publication(package.publication.marker.to_dict(),
        snapshot=state.capture_routing_snapshot(expected_phase="phase1-discover"))
    before = state.load()
    with pytest.raises(ValueError): prepare(prepared, executor)
    assert state.load() == before and len(executor.calls) == 3


@pytest.mark.parametrize("field,value", [("phase", "phase1-why2"), ("status", "blocked")])
def test_review_does_not_authorize_preparation_outside_active_discovery(prepared, field, value):
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    state = prepared[1]
    state.save({**state.load(), field: value})
    before = state.load()
    with pytest.raises(ValueError): prepare(prepared, executor)
    assert state.load() == before and len(executor.calls) == 3


def test_checked_replay_cannot_fill_a_missing_completed_provider_step(prepared):
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    path = prepared[1].squad_dir / "discovery-turns.json"
    receipt = json.loads(path.read_text())
    receipt["payload"]["steps"].pop()
    raw = json.dumps(receipt["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    receipt["sha256"] = hashlib.sha256(raw.encode("ascii")).hexdigest()
    path.write_text(json.dumps(receipt))
    before = prepared[1].load()
    result = execute(prepared, executor, replay_only=True)
    assert result.status == "blocked"
    assert len(executor.calls) == 3 and prepared[1].load() == before


def test_checked_replay_requires_an_accepted_operation(prepared):
    executor = DiscoveryExecutor()
    result = execute(prepared, executor, create=True, replay_only=True)
    assert result.status == "blocked"
    assert executor.calls == []
    assert "managed_discovery_operation" not in prepared[1].load()


@pytest.mark.parametrize("damage", ["missing", "incomplete"])
def test_checked_replay_cannot_reconstruct_reservation_receipts(prepared, damage):
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    path = prepared[1].squad_dir / "discovery-reservations.json"
    receipt = json.loads(path.read_text())
    if damage == "missing": receipt["payload"]["proposals"].clear()
    else: receipt["payload"]["proposals"][0]["intents"][0]["ids"] = None
    raw = json.dumps(receipt["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    receipt["sha256"] = hashlib.sha256(raw.encode("ascii")).hexdigest()
    path.write_text(json.dumps(receipt))
    before = path.read_bytes()
    assert execute(prepared, executor, replay_only=True).status == "blocked"
    assert path.read_bytes() == before and len(executor.calls) == 3


@pytest.mark.parametrize("damage", ["config", "input", "role", "turns", "reservations"])
def test_drift_during_graph_preparation_blocks_the_handoff(prepared, monkeypatch, damage):
    import harness.discovery_publication as module
    root, state, store, _ = prepared
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    before = state.load()
    graph = module._graph
    def drift(*args):
        result = graph(*args)
        path = {"config": root / ".echelon/config.yml", "input": root / "inputs/task.md",
            "role": root / ".echelon/prosaic/subagents/echelon.discovery-reviewer.md",
            "turns": state.squad_dir / "discovery-turns.json",
            "reservations": state.squad_dir / "discovery-reservations.json"}[damage]
        path.write_text("private changed source")
        return result
    monkeypatch.setattr(module, "_graph", drift)
    with pytest.raises(ValueError) as caught: prepare(prepared, executor)
    assert "private" not in str(caught.value) and caught.value.__context__ is None
    assert state.load() == before and store.pending_identity_publication(spec_id="game") is None
    assert list((root / "specs/game").iterdir()) == [] and len(executor.calls) == 3


@pytest.mark.parametrize("damage", ["changed", "missing"])
def test_damaged_final_stage_cannot_be_returned(prepared, monkeypatch, damage):
    import harness.discovery_publication as module
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    add = module.SquadPublicationTransaction.add_write
    stages = []
    def remember(self, target, staged, **kwargs):
        result = add(self, target, staged, **kwargs)
        stages.append(staged)
        return result
    seal = module._seal
    count = 0
    def corrupt(*args):
        nonlocal count
        result = seal(*args)
        count += 1
        if count == 2:
            if damage == "changed": stages[-1].write_bytes(b"unreviewed")
            else: stages[-1].unlink()
        return result
    monkeypatch.setattr(module.SquadPublicationTransaction, "add_write", remember)
    monkeypatch.setattr(module, "_seal", corrupt)
    with pytest.raises(ValueError): prepare(prepared, executor)
    assert list((prepared[0] / "specs/game").iterdir()) == [] and len(executor.calls) == 3
    assert prepared[2].pending_identity_publication(spec_id="game") is None


@pytest.mark.parametrize("target", ["assumptions.md", "spec-artifact-graph.json"])
@pytest.mark.parametrize("damage", ["bytes", "mode"])
def test_sealing_cannot_bless_changed_reviewed_images(prepared, monkeypatch, target, damage):
    from harness.squad_publication import SquadPublicationTransaction
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    before = prepared[1].load()
    history = prepared[2].identity_history(spec_id="game")
    add = SquadPublicationTransaction.add_write
    def drift(self, selected, staged, **kwargs):
        if selected.name == target:
            if damage == "bytes": staged.write_bytes(b"UNREVIEWED EXTRA PROSE")
            else: staged.chmod(0o600)
        return add(self, selected, staged, **kwargs)
    monkeypatch.setattr(SquadPublicationTransaction, "add_write", drift)
    with pytest.raises(ValueError): prepare(prepared, executor)
    assert list((prepared[0] / "specs/game").iterdir()) == [] and len(executor.calls) == 3
    assert prepared[1].load() == before and prepared[2].identity_history(spec_id="game") == history
    assert prepared[2].pending_identity_publication(spec_id="game") is None


def test_interrupted_preparation_retries_without_identity_or_model_work(prepared, monkeypatch):
    import harness.discovery_publication as module
    executor = DiscoveryExecutor(reject=1)
    assert execute(prepared, executor, create=True).status == "reviewed"
    before = prepared[1].load()
    history = prepared[2].identity_history(spec_id="game")
    seal = module._seal
    count = 0
    def interrupt(*args):
        nonlocal count
        result = seal(*args)
        count += 1
        if count == 2: raise Interrupted()
        return result
    monkeypatch.setattr(module, "_seal", interrupt)
    with pytest.raises(Interrupted): prepare(prepared, executor)
    monkeypatch.setattr(module, "_seal", seal)
    package = prepare(prepared, executor)
    assert b"How should movement" in next(op.postimage_bytes for op in package.sources.publication.operations
        if op.target.endswith("unknowns.md"))
    assert len(executor.calls) == 6 and prepared[1].load() == before
    assert prepared[2].identity_history(spec_id="game") == history
    assert prepared[2].pending_identity_publication(spec_id="game") is None


def test_runtime_drift_after_preparation_blocks_guarded_promotion(prepared):
    from harness.squad_publication import PublicationError
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    package = prepare(prepared, executor)
    (prepared[0] / ".echelon/constitution.md").write_text("A new constraint")
    with pytest.raises(PublicationError):
        package.publication.publish_sources(package.sources,
            before_publish=lambda _: prepared[2].prepare_identity_publication(
                spec_id="game", operation_id="fixture-publish", request=package.request))
    assert list((prepared[0] / "specs/game").iterdir()) == []
    assert prepared[2].pending_identity_publication(spec_id="game") is None


def test_final_graph_projection_must_equal_sealed_graph(prepared, monkeypatch):
    import harness.discovery_publication as module
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    build = module.build_captured_identity_graph
    count = 0
    def drift(**kwargs):
        nonlocal count
        graph = build(**kwargs)
        count += 1
        return replace(graph, generator_version="changed-graph") if count == 2 else graph
    monkeypatch.setattr(module, "build_captured_identity_graph", drift)
    with pytest.raises(ValueError): prepare(prepared, executor)
    assert list((prepared[0] / "specs/game").iterdir()) == [] and len(executor.calls) == 3
    assert prepared[2].pending_identity_publication(spec_id="game") is None


def test_repair_seals_same_subject_revision_and_preserves_target_mode(prepared, monkeypatch):
    from harness.squad_publication import SquadPublicationTransaction
    add = SquadPublicationTransaction.add_write
    def private_mode(self, target, staged, **kwargs):
        staged.chmod(0o640)
        return add(self, target, staged, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(SquadPublicationTransaction, "add_write", private_mode)
        original = seed_accepted_question(prepared)
    class RepairExecutor(ScriptedExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            result = super().run_inspection_turn(*args, **kwargs)
            selected, context = self.calls[-1]["assignment"], self.calls[-1]["context"]
            if selected["step"] == "propose":
                fields = dict(new_subjects=[], revisions=[dict(id="U-000001", expected_revision="1")])
            elif selected["step"] == "author":
                fields = dict(artifacts={"unknowns.md": original.replace("Original", "Clarified")})
            else:
                fields = dict(verdict="accept", reason="Same camera question", assessments=[dict(
                    id="U-000001", verdict="accept", reason="Clarification", evidence=[context["citations"]["U-000001"]])])
            return replace(result, stdout=json.dumps({**selected, "action": "final", **fields}))
    executor = RepairExecutor()
    assert execute(prepared, executor, create=True, artifact_paths=("unknowns.md",),
        unowned_writable_paths=(), editable_revisions=(("U-000001", "1"),),
        intent=dict(kind="repair", request="Clarify camera", origin="review:camera", findings=["Clarify"])).status == "reviewed"
    package = prepare(prepared, executor)
    rows = json.loads(package.candidate.history.payload)
    assert rows["entities"][0]["revision"] == "2" and len(rows["revisions"]) == 2
    write, = (op for op in package.sources.publication.operations if op.target.endswith("unknowns.md"))
    assert write.postimage.mode == 0o640 and write.postimage_bytes == original.replace("Original", "Clarified").encode()
    target = prepared[0] / "specs/game/unknowns.md"
    assert target.read_bytes() == original.encode() and stat.S_IMODE(target.stat().st_mode) == 0o640
    assert len(executor.calls) == 3
