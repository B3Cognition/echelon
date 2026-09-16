"""Completion-owned restoration continuation, never provider publication authority.

The private preparation seam requires authenticated completion and selected
history inputs from its caller. It stages only the graph and prepares the
existing identity journal; native Git-first remains the artifact writer.
"""
from dataclasses import asdict, dataclass, replace
import hashlib

from harness.discovery_completion import _closed, _document, _json, _require
from harness.discovery_publication import _graph, _seal
from harness.discovery_restoration import _requirement_restoration_changes, _selected_history
from harness.discovery_restoration_sources import restoration_source_snapshot
from harness.element_identity_publication import (
    PublicationIntentRequest, PublicationSourceClaim, PublicationContinuationClaim,
    PublicationOperation, decode_publication_request,
)
from harness.element_identity_request_codec import encode_request
from harness.element_identity_snapshot import IdentityHistorySnapshot
from harness.git_first_restore import GitFirstRestorePlan, RestoreCommitEntry, verify_git_first_restore_commit
from harness.squad_source_baseline_codec import encode_initial_publication_sources, decode_initial_publication_sources
from harness.squad_source_manifest import snapshot_source_manifest
from harness.squad_source_projection import project_publication_source_images
from harness.squad_source_snapshot import PublicationSourcesSnapshot


@dataclass(frozen=True)
class RestorationContinuation:
    request: object
    plan: object
    sources: object
    graph_sources: object
    history: object
    selected_history: object
    selected_source: dict
    state: str


def continuation_id(completion_id):
    import re
    _require(type(completion_id) is str and re.fullmatch(r"[0-9a-f]{32}", completion_id) is not None)
    return "discovery-restore-" + completion_id


def _claim(binding, completion, parent):
    _require(binding.request.continuation_id == continuation_id(completion.marker.completion_id))
    return PublicationContinuationClaim(binding.operation_id, parent["preparation"]["request_sha256"],
        hashlib.sha256(parent["application_receipt"].encode("ascii")).hexdigest(),
        completion.marker.completion_id, completion.marker.intent_sha256)


def _operations(binding, selected_history, plan):
    changes = _requirement_restoration_changes(current_history=IdentityHistorySnapshot(**binding.candidate["history"]),
        selected_history=selected_history, snapshot_id=plan.selected_candidate_id)
    return (() if not changes else (PublicationOperation("lifecycle", binding.request.continuation_id + "-membership",
        encode_request("lifecycle", changes)),))


def _baseline(sources, spec_id):
    tree, = (tree for tree in sources.trees if tree.path == "specs/" + spec_id)
    return PublicationSourcesSnapshot(sources.publication, (tree,), ())


def _require_parent_sources(binding, sources):
    from harness.discovery_producer import identity_spec_tree
    expected = project_publication_source_images(binding.sources)
    trees = tuple(identity_spec_tree(tree) if tree.path == "specs/" + binding.spec_id else tree
        for tree in expected.trees)
    _require(snapshot_source_manifest(trees=sources.trees, files=sources.files)
        == snapshot_source_manifest(trees=trees, files=expected.files))


def _request(binding, completion, parent, logical, operations, recovery, proposed=None):
    return PublicationIntentRequest(logical.publication.marker.manifest_sha256, recovery, operations,
        PublicationSourceClaim(binding.request.sources.context_id, binding.operation_id,
            encode_initial_publication_sources(_baseline(logical, binding.spec_id))),
        proposed_history_sha256=None if proposed is None else proposed.sha256,
        continuation=_claim(binding, completion, parent))


def _read_continuation(root, store, *, binding, completion, parent):
    """Validate the retained child against its exact immutable parent inputs."""
    claim = _claim(binding, completion, parent)
    row = store.identity_publication(spec_id=binding.spec_id, operation_id=binding.request.continuation_id)
    if row is None:
        return None
    request = decode_publication_request(row["request"])
    _require(request.continuation == claim and request.continuation_id is None)
    recovery = _document(request.recovery_payload)
    _closed(recovery, ("version", "plan", "sources", "graph_sources", "history", "selected_history", "selected_source"))
    _require(type(recovery["version"]) is int and recovery["version"] == 1)
    raw = recovery["plan"]
    plan = GitFirstRestorePlan(**{**raw, "entries": tuple(RestoreCommitEntry(**entry) for entry in raw["entries"])})
    _require(asdict(plan) == {**raw, "entries": tuple(raw["entries"])})
    verify_git_first_restore_commit(root, plan)
    _require(plan.spec_id == binding.spec_id)
    sources = decode_initial_publication_sources(recovery["sources"])
    graph_sources = decode_initial_publication_sources(recovery["graph_sources"])
    _require_parent_sources(binding, graph_sources)
    history = IdentityHistorySnapshot(**recovery["history"])
    selected_history = IdentityHistorySnapshot(**recovery["selected_history"])
    source = recovery["selected_source"]
    from harness.discovery_producer import SOURCE_FIELDS
    import re
    _closed(source, SOURCE_FIELDS)
    _require(all(type(value) is str and re.fullmatch(r"[0-9a-f]{%d}" % (32 if key == "dispatch_id" else 64), value)
        for key, value in source.items()))
    _selected_history(history, _document(history.payload))
    _require(sources == restoration_source_snapshot(project_root=root, plan=plan, sources=graph_sources)
        and request == _request(binding, completion, parent, sources, _operations(binding, selected_history, plan),
            request.recovery_payload, history))
    graph, = graph_sources.publication.operations
    _require(graph.postimage_bytes == _graph(sources, history,
        dict(spec_id=binding.spec_id, spec_path="specs/" + binding.spec_id)))
    return RestorationContinuation(request, plan, sources, graph_sources, history, selected_history, source, row["state"])


def _prepare_continuation(root, run, store, *, binding, completion, parent, plan, before_sources,
        selected_history, selected_source, project_tree=None):
    """Called only after native completion/selection/source authentication.

    Retrying an existing child never stages another graph or previews against
    the now-advanced identity head. Original captured B remains the preimage.
    """
    retained = _read_continuation(root, store, binding=binding, completion=completion, parent=parent)
    if retained is not None:
        _require(retained.plan == plan and retained.selected_history == selected_history
            and retained.selected_source == selected_source)
        return retained
    _require(parent["state"] == "applied" and not before_sources.publication.operations
        and asdict(store.identity_history(spec_id=binding.spec_id)) == binding.candidate["history"])
    _require_parent_sources(binding, before_sources)
    logical = restoration_source_snapshot(project_root=root, plan=plan, sources=before_sources)
    operations = _operations(binding, selected_history, plan)
    preview = _request(binding, completion, parent, logical, operations, "restoration-preview")
    history = store.preview_identity_history(spec_id=binding.spec_id, operations=operations,
        publication_id=binding.request.continuation_id, continuation_request=preview)
    graph_path = "specs/" + binding.spec_id + "/spec-artifact-graph.json"
    graph = _graph(logical, history, dict(spec_id=binding.spec_id, spec_path="specs/" + binding.spec_id))
    original, = (item for tree in before_sources.trees for item in tree.files if item.path == graph_path)
    publication = _seal(root, run, {graph_path: graph}, {graph_path: original.image.mode})
    with publication.inspect_sources(tree_paths=tuple(tree.path for tree in before_sources.trees),
            file_paths=tuple(item.path for item in before_sources.files)) as observed:
        graph_sources = observed if project_tree is None else replace(observed,
            trees=tuple(project_tree(tree) for tree in observed.trees))
        _require(snapshot_source_manifest(trees=graph_sources.trees, files=graph_sources.files)
            == snapshot_source_manifest(trees=before_sources.trees, files=before_sources.files))
    logical = restoration_source_snapshot(project_root=root, plan=plan, sources=graph_sources)
    recovery = _json(dict(version=1, plan=asdict(plan), sources=encode_initial_publication_sources(logical),
        graph_sources=encode_initial_publication_sources(graph_sources), history=asdict(history),
        selected_history=asdict(selected_history), selected_source=selected_source))
    request = _request(binding, completion, parent, logical, operations, recovery, history)
    store.prepare_identity_publication(spec_id=binding.spec_id, operation_id=binding.request.continuation_id, request=request)
    return _read_continuation(root, store, binding=binding, completion=completion, parent=parent)


def _inspect_continuation(root, run, retained, *, project_tree=None, journal_root=None):
    """Join two read-only writer proofs without interpreting new bytes as inputs.

    The caller must authenticate the retained request and supply the native
    checkpoint projector. Only exact native base/target images are normalized
    back to captured B for the separate graph-stage source-progress check.
    """
    from harness.git_first_restore import inspect_git_first_restore_worktree
    from harness.squad_publication import load_prepared_publication
    from harness.squad_source_guard import _validate_source_progress
    try:
        plan = retained.plan
        images = inspect_git_first_restore_worktree(project_root=root,
            spec_dir=root / ("specs/" + plan.spec_id), journal_root=run if journal_root is None else journal_root, plan=plan)
        publication = load_prepared_publication(root, run, retained.graph_sources.publication.marker)
        originals = {item.path: item for tree in retained.graph_sources.trees for item in tree.files if item.path in images}
        _require(set(originals) == set(images))
        with publication.inspect_sources(tree_paths=tuple(tree.path for tree in retained.sources.trees),
                file_paths=tuple(item.path for item in retained.sources.files)) as observed:
            actual = {item.path: (item.image.mode, item.image.sha256) for tree in observed.trees
                for item in tree.files if item.path in images}
            _require(actual == images)
            normalized = observed if project_tree is None else replace(observed,
                trees=tuple(project_tree(tree) for tree in observed.trees))
            normalized = replace(normalized, trees=tuple(replace(tree,
                files=tuple(originals.get(item.path, item) for item in tree.files)) for tree in normalized.trees))
            _validate_source_progress(retained.graph_sources, normalized)
            native_done = images == {entry.path: (int(entry.target_mode[-3:], 8), entry.target_sha256) for entry in plan.entries}
            _require(observed.publication.promoted_prefix == 0 or native_done)
            if retained.state in {"applied", "released"}:
                _require(native_done and all(op.current == op.postimage for op in observed.publication.operations))
        return observed
    except Exception:
        raise ValueError("restoration progress differs from its retained writers") from None


def _finish_continuation(root, run, store, retained, *, binding, project_tree, journal_root=None):
    """After native restoration, publish only the graph then accept identity atomically.

    Caller supplies the checkpoint owner's authenticated projector after the
    native restore receipt has been checked. Exceptions preserve both pending
    records for retry; only the enclosing completion may release them.
    """
    from harness.discovery_restoration_sources import graph_publication_sources
    from harness.squad_publication import load_prepared_publication
    observed = _inspect_continuation(root, run, retained, project_tree=project_tree, journal_root=journal_root)
    guard = graph_publication_sources(logical=retained.sources, graph_sources=retained.graph_sources,
        observed=observed, project_tree=project_tree)
    publication = load_prepared_publication(root, run, retained.graph_sources.publication.marker)
    publication.publish_sources(guard, after_publish=lambda _: store.apply_identity_publication(
        spec_id=binding.spec_id, operation_id=binding.request.continuation_id))


def _restore_checkpoint_projector(root, retained, *, ledger_preimage, checkpoint_receipt, pending):
    """Prove the third checkpoint using A artifacts and the original B graph.

    The native Git checkpoint precedes graph publication. Its source tree must
    never be verified against the regenerated graph or today's observed files.
    The caller binds the retained plan to the exact assessed-candidate checkpoint
    and supplies that checkpoint's authenticated ledger image.
    """
    from functools import partial
    from harness.discovery_completion import _project_checkpoint_tree
    from harness.phase_checkpoints import fresh_completion_checkpoint_ledger_image
    plan = retained.plan
    verify_git_first_restore_commit(root, plan)
    graph, = retained.graph_sources.publication.operations
    native = replace(retained.sources, publication=replace(retained.sources.publication,
        operations=tuple(op for op in retained.sources.publication.operations if op.target != graph.target)))
    spec = "specs/" + plan.spec_id
    tree, = (tree for tree in project_publication_source_images(native).trees if tree.path == spec)
    if checkpoint_receipt is None and not pending:
        # A child may be applied before the enclosing quality receipt is saved.
        # Derive only the expected image from immutable native authority; the
        # projector still requires the actual final ledger, and inspection also
        # proves native worktree/ref convergence. This is not a persisted receipt.
        from harness.phase_checkpoints import _preflight_prebuilt_completion_checkpoint
        authority = _preflight_prebuilt_completion_checkpoint(project_root=root, spec_dir=root / spec,
            phase="phase1-quality-candidate-restored", next_phase=plan.next_phase, run_id=plan.run_id,
            spec_id=plan.spec_id, completion_id=plan.completion_id, expected_parent=plan.base_commit,
            commit=plan.target_commit, expected_entries=plan.entries)
        checkpoint_receipt = dict(authority.receipt)
    ledger = fresh_completion_checkpoint_ledger_image(project_root=root, spec_dir=root / spec,
        phase="phase1-quality-candidate-restored", next_phase=plan.next_phase, run_id=plan.run_id,
        spec_id=plan.spec_id, completion_id=plan.completion_id,
        checkpoint_prestate={"kind": "git_head", "head": plan.base_commit},
        expected_receipt=checkpoint_receipt, allow_pending=pending, rewind="supported",
        artifact_images={item.path: (item.image.mode, item.content) for item in tree.files},
        ledger_preimage=ledger_preimage)
    return partial(_project_checkpoint_tree, spec=spec, ledger=ledger, pending=pending, preimage=ledger_preimage)


def pending_tree_projector(root, run, completion, *, sources, checkpoint):
    """Normalize only checkpoint/context images proved by their existing owners."""
    from harness.discovery_completion import _context
    context = (run / "context").relative_to(root).as_posix()
    original, = (tree for tree in sources.trees if tree.path == context)
    def project(tree):
        if tree.path == context:
            _context(completion, original, tree)
            return original
        return checkpoint(tree)
    return project


def authenticated_continuation(root, run, state, *, binding, completion, parent):
    """Read the exact child only through its native effect and managed ancestry."""
    from harness.discovery_restoration import retained_quality_candidate_history
    from harness.element_identity_store import IdentityStore
    from harness.proportional_quality import preflight_quality_candidate_restore
    try:
        if binding.request.continuation_id is None:
            return None
        retained = _read_continuation(root, IdentityStore.open(root), binding=binding,
            completion=completion, parent=parent)
        if retained is None:
            _require(parent["state"] == "applied" and completion.receipts["effects"].get("quality") is None)
            return None
        plan = retained.plan
        selected = preflight_quality_candidate_restore(project_root=root, spec_dir=root / ("specs/" + binding.spec_id),
            manifest_path=run / "quality-candidates" / (plan.selected_candidate_id + ".json"),
            expected_candidate_id=plan.selected_candidate_id, expected_manifest_sha256=plan.selected_manifest_sha256)
        _validate_native_authority(root, run, completion, plan, selected)
        history, source = retained_quality_candidate_history(root, run, state,
            source=binding.recovery["source_completion"], selected=selected)
        _require(history == retained.selected_history and source == retained.selected_source)
        return retained
    except Exception:
        raise ValueError("restoration continuation lacks managed completion authority") from None


def restoration_callbacks(root, run, state, completion):
    """Join native quality restoration to the existing pending completion owner."""
    from harness import discovery_completion
    from harness.discovery_producer import identity_spec_tree
    from harness.discovery_restoration import retained_quality_candidate_history
    from harness.element_identity_store import IdentityStore
    def before(plan, selected):
        binding = discovery_completion.require_applied(root, run, state, completion)
        _require(binding is not None and binding.producer == "why2" and binding.request.continuation_id is not None)
        _validate_native_authority(root, run, completion, plan, selected)
        history, source = retained_quality_candidate_history(root, run, state,
            source=binding.recovery["source_completion"], selected=selected)
        store = IdentityStore.open(root)
        parent = store.identity_publication(spec_id=binding.spec_id, operation_id=binding.operation_id)
        checkpoint = discovery_completion._checkpoint_projection(root, run, state, intent=completion.intent,
            marker=completion.marker, receipts=completion.receipts, binding=binding)
        project = pending_tree_projector(root, run, completion, sources=binding.sources, checkpoint=checkpoint)
        projected = project_publication_source_images(binding.sources)
        initial = PublicationSourcesSnapshot(replace(binding.sources.publication, operations=(), promoted_prefix=0),
            tuple(identity_spec_tree(tree) if tree.path == "specs/" + binding.spec_id else tree for tree in projected.trees), projected.files)
        _prepare_continuation(root, run, store, binding=binding, completion=completion, parent=parent, plan=plan,
            before_sources=initial, selected_history=history, selected_source=source, project_tree=project)

    def after(plan, selected, receipt):
        binding = discovery_completion.authenticate(root, run, state, completion)
        _require(binding is not None and binding.restoration is not None and binding.restoration.plan == plan)
        _validate_native_authority(root, run, completion, plan, selected)
        checkpoint = discovery_completion._checkpoint_projection(root, run, state, intent=completion.intent,
            marker=completion.marker, receipts=completion.receipts, binding=binding,
            restore_checkpoint_receipt=receipt["checkpoint"])
        project = pending_tree_projector(root, run, completion, sources=binding.sources, checkpoint=checkpoint)
        _finish_continuation(root, run, IdentityStore.open(root), binding.restoration, binding=binding, project_tree=project)
    return dict(before_restore=before, after_restore=after)


def _validate_native_authority(root, run, completion, plan, selected):
    """Match immutable native objects to the sealed effect, without restoration.

    This is only the native half of authentication. The completion caller must
    additionally prove the selected candidate's managed ancestry/history and
    the current candidate's routed checkpoint ledger.
    """
    from harness.proportional_quality import (
        preflight_quality_candidate_restore, quality_candidate_effect_payload,
        candidate_artifact_preimage_digests, _validate_restore_candidate, _is_candidate_id,
    )
    from harness.proportional_quality_effects import _quality_completion_id, _git_first_selected_entries, _preflight_quality_effect_receipt
    try:
        verify_git_first_restore_commit(root, plan)
        effect = completion.intent.quality_effect
        _require(effect["kind"] == "proportional_quality" and effect["operation"] == "candidate"
            and _is_candidate_id(effect["candidate"]["candidate_id"])
            and effect["spec_dir"] == "specs/" + effect["spec_id"]
            and plan.spec_id == effect["spec_id"] and plan.run_id == effect["run_id"]
            and plan.completion_id == _quality_completion_id(completion.marker.completion_id, "restore")
            and plan.next_phase == completion.intent.route["to_phase"]
            and plan.selected_candidate_id == effect["restore_candidate_id"]
            and plan.selected_manifest_sha256 == effect["restore_candidate_manifest_sha256"]
            and effect["candidate"]["candidate_id"] != plan.selected_candidate_id)
        spec = root / effect["spec_dir"]
        actual = preflight_quality_candidate_restore(project_root=root, spec_dir=spec,
            manifest_path=run / "quality-candidates" / (plan.selected_candidate_id + ".json"),
            expected_candidate_id=plan.selected_candidate_id, expected_manifest_sha256=plan.selected_manifest_sha256)
        _require(actual == selected and selected.snapshot.manifest.run_artifact_root == str(run))
        _validate_restore_candidate(root, selected.snapshot.manifest, run_id=plan.run_id, spec_id=plan.spec_id)
        receipt = _preflight_quality_effect_receipt(effect, "candidate", completion.receipts["effects"].get("quality"))
        candidate_id = effect["candidate"]["candidate_id"]
        from harness.proportional_quality import load_quality_candidate_snapshot
        current = load_quality_candidate_snapshot(run / "quality-candidates" / (candidate_id + ".json"),
            expected_candidate_id=candidate_id,
            **({"expected_sha256": receipt["candidate"]["manifest_sha256"]} if receipt is not None else {}))
        _require(current.manifest.run_artifact_root == str(run)
            and current.manifest.checkpoint_commit == plan.base_commit
            and quality_candidate_effect_payload(replace(current.manifest, checkpoint_commit="0" * 40)) == effect["candidate"]
            and candidate_artifact_preimage_digests(spec, selected.snapshot.manifest, current_candidate=current.manifest)
                == effect["restore_artifact_preimage_digests"])
        entries = _git_first_selected_entries(project_root=root, spec_dir=spec, selected_restore=selected)
        _require({entry.path: (entry.target_mode, entry.target_blob_oid, entry.target_sha256) for entry in plan.entries}
            == {entry.path: (entry.mode, entry.blob_oid, entry.sha256) for entry in entries}
            and {entry.path.removeprefix(effect["spec_dir"] + "/"): entry.base_sha256 for entry in plan.entries}
                == effect["restore_artifact_preimage_digests"])
        if receipt is not None:
            from harness.git_first_restore import _restore_plan_sha256
            shared = dict(schema_version=1, run_id=plan.run_id, spec_id=plan.spec_id,
                next_phase=plan.next_phase, outcome="committed")
            _require(receipt["candidate"]["candidate_id"] == candidate_id
                and receipt["candidate"]["checkpoint"] == dict(shared, phase="phase1-" + candidate_id,
                    completion_id=_quality_completion_id(completion.marker.completion_id, "candidate"), commit=plan.base_commit)
                and receipt["restore"]["checkpoint"] == dict(shared, phase="phase1-quality-candidate-restored",
                    completion_id=plan.completion_id, commit=plan.target_commit)
                and receipt["restore"]["candidate_id"] == plan.selected_candidate_id
                and receipt["restore"]["artifact_preimage_digests"] == effect["restore_artifact_preimage_digests"]
                and receipt["restore"]["artifact_postimage_digests"] == dict(selected.snapshot.manifest.owned_artifact_digests)
                and receipt["restore"]["target_commit"] == plan.target_commit
                and receipt["restore"]["plan_sha256"] == _restore_plan_sha256(plan))
        return selected
    except Exception:
        raise ValueError("native restoration differs from its sealed managed effect") from None
