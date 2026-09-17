"""Completion-owned request preparation; native writers stay separate."""
from dataclasses import asdict, replace
import hashlib
from types import SimpleNamespace

import pytest

from tests.unit.test_discovery_restoration_sources import repo, restoration


@pytest.fixture
def continuation(restoration, request):
    from harness.element_identity_store import IdentityStore
    from harness.element_identity_publication import PublicationIntentRequest, PublicationSourceClaim
    from harness.squad_source_baseline_codec import encode_initial_publication_sources
    from harness.squad_source_manifest import snapshot_source_manifest
    repository, plan, sources = restoration
    identity = IdentityStore.initialize(repository.root)
    selected_history = None
    if getattr(request, "param", None) == "membership":
        from harness.element_identity_lifecycle import ElementCreate, ElementRevision
        identity.reserve(spec_id=plan.spec_id, kind="FR", operation_id="fr", count=2)
        identity.reserve(spec_id=plan.spec_id, kind="ISS", operation_id="iss", count=1)
        identity.apply_lifecycle(spec_id=plan.spec_id, operation_id="a", changes=(
            ElementCreate("FR-000001", "Movement", "Move in scene", "fr"),
            ElementCreate("ISS-000001", "Controls", "Controls unclear", "iss")))
        selected_history = identity.identity_history(spec_id=plan.spec_id)
        identity.apply_lifecycle(spec_id=plan.spec_id, operation_id="b", changes=(
            ElementRevision("FR-000001", "1", "Movement", "Move using arrow keys"),
            ElementCreate("FR-000002", "Lighting", "Light the scene", "fr"),
            ElementRevision("ISS-000001", "1", "Controls", "Controls reviewed again")))
    history = identity.identity_history(spec_id=plan.spec_id)
    if getattr(request, "param", False) is True:
        from harness.discovery_publication import _graph, _seal
        from harness.discovery_restoration_sources import restoration_source_snapshot
        from tests.unit.test_git_first_restore import _restore_plan
        native = restoration_source_snapshot(project_root=repository.root, plan=plan,
            sources=replace(sources, publication=replace(sources.publication, operations=())))
        graph = _graph(native, history, dict(spec_id=plan.spec_id, spec_path="specs/" + plan.spec_id))
        target = "specs/" + plan.spec_id + "/spec-artifact-graph.json"
        (repository.root / target).write_bytes(graph)
        repository.git("add", target)
        repository.git("commit", "-qm", "capture identical graph")
        repository.base_commit = repository.head()
        plan = _restore_plan(repository)
        publication = _seal(repository.root, repository.root / "runs/test", {target: graph}, {})
        with publication.inspect_sources(tree_paths=("specs/" + plan.spec_id,), file_paths=("README.md",)) as sources:
            pass
    initial = replace(sources, files=(), publication=replace(sources.publication, operations=()))
    identity.register_source_context(spec_id=plan.spec_id, context_id="run", operation_id="register",
        manifest=snapshot_source_manifest(trees=initial.trees, files=()))
    completion_id = "a" * 32
    operation_id = "discovery-completion-" + completion_id
    request = PublicationIntentRequest(initial.publication.marker.manifest_sha256, "fixture-root",
        sources=PublicationSourceClaim("run", "register", encode_initial_publication_sources(initial)),
        proposed_history_sha256=history.sha256, continuation_id="discovery-restore-" + completion_id)
    identity.prepare_identity_publication(spec_id=plan.spec_id, operation_id=operation_id, request=request)
    identity.apply_identity_publication(spec_id=plan.spec_id, operation_id=operation_id)
    row = identity.identity_publication(spec_id=plan.spec_id, operation_id=operation_id)
    binding = SimpleNamespace(request=request, operation_id=operation_id, spec_id=plan.spec_id,
        candidate={"history": asdict(history)}, sources=replace(sources,
            publication=replace(sources.publication, operations=())))
    completion = SimpleNamespace(marker=SimpleNamespace(completion_id=completion_id, intent_sha256="b" * 64))
    source = dict(dispatch_id="c" * 32, completion_intent_sha256="d" * 64,
        completion_receipts_sha256="e" * 64, completed_publication_binding_sha256="f" * 64)
    # Exact native completion identity is already built into the immutable plan.
    return repository, identity, plan, sources, selected_history or history, binding, completion, row, source


def prepare(values):
    from harness.discovery_restoration_completion import _prepare_continuation
    repository, identity, plan, sources, history, binding, completion, row, source = values
    return _prepare_continuation(repository.root, repository.root / "runs/test", identity,
        binding=binding, completion=completion, parent=row, plan=plan,
        before_sources=replace(sources, publication=replace(sources.publication, operations=())),
        selected_history=history, selected_source=source)


def test_preparation_retains_exact_native_plan_and_graph_without_promoting(continuation):
    from harness.element_identity_publication import decode_publication_request
    from harness.discovery_restoration_completion import _read_continuation
    repository, identity, plan, sources, history, binding, completion, row, source = continuation
    before = repository.head(), repository.spec_bytes(), history
    result = prepare(continuation)
    child = identity.identity_publication(spec_id=plan.spec_id, operation_id=binding.request.continuation_id)
    assert child["state"] == "prepared"
    request = decode_publication_request(child["request"])
    assert request.continuation.parent_request_sha256 == row["preparation"]["request_sha256"]
    assert request.continuation.parent_application_sha256 == hashlib.sha256(row["application_receipt"].encode("ascii")).hexdigest()
    assert request.continuation.completion_intent_sha256 == completion.marker.intent_sha256
    assert result.plan == plan and result.selected_source == source
    assert result.history == history
    assert result == _read_continuation(repository.root, identity, binding=binding,
        completion=completion, parent=row)
    assert (repository.head(), repository.spec_bytes(), identity.identity_history(spec_id=plan.spec_id)) == before
    assert identity.pending_identity_publication(spec_id=plan.spec_id) == row


@pytest.mark.parametrize("damage", ["completion", "intent", "parent", "history", "source", "plan"])
def test_prepared_continuation_cannot_be_rebound_on_retry(continuation, damage):
    repository, identity, plan, sources, history, binding, completion, row, source = continuation
    prepare(continuation)
    if damage in {"completion", "intent"}:
        completion = SimpleNamespace(marker=SimpleNamespace(completion_id="1" * 32 if damage == "completion" else completion.marker.completion_id,
            intent_sha256="2" * 64 if damage == "intent" else completion.marker.intent_sha256))
    elif damage == "parent":
        row = {**row, "application_receipt": row["application_receipt"] + " "}
    elif damage == "history":
        history = replace(history, sha256="3" * 64)
    elif damage == "source":
        source = {**source, "dispatch_id": "4" * 32}
    else:
        plan = replace(plan, selected_manifest_sha256="5" * 64)
    with pytest.raises(ValueError):
        prepare((repository, identity, plan, sources, history, binding, completion, row, source))


def test_retry_reuses_retained_graph_stage_and_request(continuation, monkeypatch):
    from harness import discovery_restoration_completion
    original = prepare(continuation)
    def forbidden(*args, **kwargs):
        raise AssertionError("retry must not restage or replan")
    monkeypatch.setattr(discovery_restoration_completion, "_seal", forbidden)
    assert prepare(continuation) == original


@pytest.mark.parametrize("stage", ["prepared", "native", "graph", "identity"])
def test_pending_continuation_inspects_exact_native_and_graph_progress(continuation, stage):
    from harness.discovery_restoration_completion import _inspect_continuation
    from harness.discovery_producer import identity_spec_tree
    from harness.discovery_restoration_sources import graph_publication_sources
    from harness.squad_publication import load_prepared_publication
    from tests.unit.test_git_first_restore import _apply
    repository, identity, plan, sources, history, binding, completion, row, source = continuation
    retained = prepare(continuation)
    publication = load_prepared_publication(repository.root, repository.root / "runs/test",
        retained.graph_sources.publication.marker)
    if stage != "prepared":
        _apply(repository, plan)
    if stage in {"graph", "identity"}:
        with publication.inspect_sources(tree_paths=tuple(tree.path for tree in retained.sources.trees),
                file_paths=tuple(item.path for item in retained.sources.files)) as current:
            pass
        guard = graph_publication_sources(logical=retained.sources, graph_sources=retained.graph_sources,
            observed=current, project_tree=identity_spec_tree)
        publication.publish_sources(guard)
    if stage == "identity":
        identity.apply_identity_publication(spec_id=plan.spec_id, operation_id=binding.request.continuation_id)
        retained = replace(retained, state="applied")
    # This isolates source progress. Production callers must provide the real
    # third-checkpoint projector; metadata cannot be ignored there.
    _inspect_continuation(repository.root, repository.root / "runs/test", retained,
        project_tree=identity_spec_tree, journal_root=repository.run_root)
    assert repository.spec_bytes() == (b"# current spec\n" if stage == "prepared" else b"#!/bin/sh\n# selected spec\n")


@pytest.mark.parametrize("damage", ["unowned", "external", "native", "extra", "mode", "applied_early"])
def test_pending_continuation_does_not_normalize_unauthorized_changes(continuation, damage):
    from harness.discovery_restoration_completion import _inspect_continuation
    repository, identity, plan, sources, history, binding, completion, row, source = continuation
    retained = prepare(continuation)
    if damage == "applied_early":
        retained = replace(retained, state="applied")
    else:
        path = repository.root / {"unowned": "specs/001-example/unknowns.md", "external": "README.md",
            "native": "specs/001-example/spec.md", "extra": "specs/001-example/extra.md",
            "mode": "specs/001-example/spec.md"}[damage]
        if damage == "mode":
            path.chmod(0o600)
        else:
            path.write_bytes(b"not an authorized image\n")
    with pytest.raises(ValueError):
        _inspect_continuation(repository.root, repository.root / "runs/test", retained,
            journal_root=repository.run_root)


@pytest.mark.parametrize("continuation", [True], indirect=True)
def test_applied_continuation_with_identical_graph_is_recoverable(continuation):
    test_pending_continuation_inspects_exact_native_and_graph_progress(continuation, "identity")


@pytest.mark.parametrize("boundary", ["graph", "identity"])
@pytest.mark.parametrize("when", ["before", "after"])
def test_finish_continuation_replays_uncertain_native_owner_outcomes(continuation, monkeypatch, boundary, when):
    from harness.discovery_restoration_completion import _finish_continuation, _read_continuation
    from harness.discovery_producer import identity_spec_tree
    from harness.element_identity_store import IdentityStore
    from harness.squad_publication import PreparedSquadPublication
    from tests.unit.test_git_first_restore import _apply
    from tests.unit.test_discovery_turns import Interrupted
    repository, identity, plan, sources, history, binding, completion, row, source = continuation
    retained = prepare(continuation)
    _apply(repository, plan)
    owner, name = (PreparedSquadPublication, "_promote") if boundary == "graph" else (IdentityStore, "apply_identity_publication")
    original = getattr(owner, name)
    def interrupt(*args, **kwargs):
        if when == "before":
            raise Interrupted()
        original(*args, **kwargs)
        raise Interrupted()
    with monkeypatch.context() as patch:
        patch.setattr(owner, name, interrupt)
        with pytest.raises(Interrupted):
            _finish_continuation(repository.root, repository.root / "runs/test", identity, retained,
                binding=binding, project_tree=identity_spec_tree, journal_root=repository.run_root)
    identity = IdentityStore.open(repository.root)
    retained = _read_continuation(repository.root, identity, binding=binding, completion=completion, parent=row)
    _finish_continuation(repository.root, repository.root / "runs/test", identity, retained,
        binding=binding, project_tree=identity_spec_tree, journal_root=repository.run_root)
    assert identity.identity_publication(spec_id=plan.spec_id, operation_id=binding.request.continuation_id)["state"] == "applied"
    assert identity.identity_history(spec_id=plan.spec_id) == retained.history
    assert identity.pending_identity_publication(spec_id=plan.spec_id) == row
    assert len(repository.checkpoint_rows()) == 1


@pytest.mark.parametrize("continuation", ["membership"], indirect=True)
def test_completion_child_replays_original_history_after_forward_membership_application(continuation):
    from harness.discovery_restoration_completion import _finish_continuation, _read_continuation
    from harness.discovery_producer import identity_spec_tree
    from tests.unit.test_git_first_restore import _apply
    repository, identity, plan, sources, history, binding, completion, row, source = continuation
    retained = prepare(continuation)
    assert retained.history != history
    _apply(repository, plan)
    _finish_continuation(repository.root, repository.root / "runs/test", identity, retained,
        binding=binding, project_tree=identity_spec_tree, journal_root=repository.run_root)
    assert identity.lookup(spec_id=plan.spec_id, element_id="FR-000001")["revision"] == "3"
    assert identity.lookup(spec_id=plan.spec_id, element_id="FR-000002")["present"] is False
    assert identity.lookup(spec_id=plan.spec_id, element_id="ISS-000001")["revision"] == "2"
    replay = prepare(continuation)
    assert replay.request == retained.request and replay.history == retained.history and replay.state == "applied"
    _finish_continuation(repository.root, repository.root / "runs/test", identity, replay,
        binding=binding, project_tree=identity_spec_tree, journal_root=repository.run_root)
    assert identity.identity_history(spec_id=plan.spec_id) == retained.history
    identity.release_identity_publication(spec_id=plan.spec_id, operation_id=binding.operation_id, completion_payload="fixture-complete")
    assert identity.reserve(spec_id=plan.spec_id, kind="FR", operation_id="next", count=1) == ("FR-000003",)


@pytest.mark.parametrize("continuation", ["membership"], indirect=True)
def test_effective_restoration_result_preserves_original_assessment_binding(continuation):
    from harness.discovery_completion import DiscoveryCompletionBinding
    from harness.squad_source_snapshot import PublicationSourcesSnapshot
    repository, identity, plan, sources, history, binding, completion, row, source = continuation
    retained = prepare(continuation)
    baseline = PublicationSourcesSnapshot(binding.sources.publication, binding.sources.trees, ())
    original = DiscoveryCompletionBinding(binding.request, {"completion_id": completion.marker.completion_id,
        "producer": "why2", "operation": {"binding": {"spec_id": plan.spec_id}}}, binding.candidate,
        {}, binding.sources, baseline)
    pending = replace(original, restoration=retained)
    assert pending.result_sources == original.sources and pending.result_baseline == original.baseline
    assert asdict(pending.result_history) == original.candidate["history"]
    assert pending.result_operation_id == original.operation_id
    applied = replace(pending, restoration=replace(retained, state="applied"))
    assert applied.result_sources == retained.sources and applied.result_history == retained.history
    assert applied.result_operation_id == original.request.continuation_id
    assert applied.result_baseline.trees == retained.sources.trees and applied.result_baseline.files == ()
    assert applied.candidate == original.candidate and applied.request == original.request


@pytest.mark.parametrize("restored", [False, True])
def test_continuation_uses_native_checkpoint_proof_not_metadata_omission(continuation, restored):
    from harness.discovery_restoration_completion import _restore_checkpoint_projector, _inspect_continuation
    from tests.unit.test_git_first_restore import _apply
    repository, identity, plan, sources, history, binding, completion, row, source = continuation
    retained = prepare(continuation)
    receipt = _apply(repository, plan) if restored else None
    project = _restore_checkpoint_projector(repository.root, retained, ledger_preimage=None,
        checkpoint_receipt=None if receipt is None else receipt.checkpoint, pending=not restored)
    _inspect_continuation(repository.root, repository.root / "runs/test", retained,
        project_tree=project, journal_root=repository.run_root)
    if restored:
        ledger = repository.root / "specs/001-example/.echelon/checkpoints.json"
        ledger.write_bytes(ledger.read_bytes() + b" ")
        with pytest.raises(ValueError):
            _inspect_continuation(repository.root, repository.root / "runs/test", retained,
                project_tree=project, journal_root=repository.run_root)


def test_applied_child_recovers_checkpoint_without_outer_quality_receipt(continuation):
    from harness.discovery_restoration_completion import _restore_checkpoint_projector, _finish_continuation, _inspect_continuation
    from tests.unit.test_git_first_restore import _apply
    repository, identity, plan, sources, history, binding, completion, row, source = continuation
    retained = prepare(continuation)
    native = _apply(repository, plan)
    project = _restore_checkpoint_projector(repository.root, retained, ledger_preimage=None,
        checkpoint_receipt=native.checkpoint, pending=False)
    _finish_continuation(repository.root, repository.root / "runs/test", identity, retained,
        binding=binding, project_tree=project, journal_root=repository.run_root)
    applied = prepare(continuation)
    assert applied.state == "applied"
    recovered = _restore_checkpoint_projector(repository.root, applied, ledger_preimage=None,
        checkpoint_receipt=None, pending=False)
    _inspect_continuation(repository.root, repository.root / "runs/test", applied,
        project_tree=recovered, journal_root=repository.run_root)
    ledger = repository.root / "specs/001-example/.echelon/checkpoints.json"
    ledger.unlink()
    with pytest.raises(ValueError):
        _inspect_continuation(repository.root, repository.root / "runs/test", applied,
            project_tree=recovered, journal_root=repository.run_root)


@pytest.mark.parametrize("stage", ["before", "partial", "after", "drift", "mode", "noop"])
def test_restoration_context_projection_uses_the_native_context_receipt(tmp_path, stage):
    from harness.discovery_restoration_completion import pending_tree_projector
    from harness.discovery_publication import _seal
    from harness.squad_completion import (prepare_or_load_completion_context, install_or_verify_completion_context,
        load_prepared_controller_completion)
    from tests.unit.test_squad_completion import (_prepare_context_completion, _completion_context_generator,
        _COMPLETION_CONTEXT_NAMES)
    root, run, completion = _prepare_context_completion(tmp_path)
    context = run / "context"
    context.mkdir()
    for name in _COMPLETION_CONTEXT_NAMES:
        (context / name).write_text(name + "||\n" if stage == "noop" else "original " + name)
        if stage == "noop":
            (context / name).chmod(0o755)
    publication = _seal(root, run, {}, {})
    def capture():
        with publication.inspect_sources(tree_paths=(context.relative_to(root).as_posix(),), file_paths=()) as observed:
            return observed
    original = capture()
    prepare_or_load_completion_context(completion, project_root=root, source_state_revision=1,
        prepared_at="2026-07-23T10:11:12Z", generator=_completion_context_generator([]))
    completion = load_prepared_controller_completion(root, run, completion.marker)
    if stage == "partial":
        def interrupt(point):
            raise RuntimeError("interrupted")
        with pytest.raises(RuntimeError, match="interrupted"):
            install_or_verify_completion_context(completion, fault_hook=interrupt)
    elif stage in {"after", "drift", "mode", "noop"}:
        install_or_verify_completion_context(completion)
    project = pending_tree_projector(root, run, completion, sources=original, checkpoint=lambda tree: tree)
    if stage in {"drift", "mode"}:
        if stage == "drift":
            (context / "current-feature-context.md").write_text("not a retained context image")
        else:
            (context / "current-feature-context.md").chmod(0o755)
        with pytest.raises(ValueError):
            project(capture().trees[0])
    else:
        assert project(capture().trees[0]) == original.trees[0]
