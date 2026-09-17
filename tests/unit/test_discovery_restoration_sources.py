"""Native restored bytes and the graph have distinct writers, one source result."""
from dataclasses import replace
import hashlib

import pytest

from harness.discovery_publication import _seal
from harness.squad_source_projection import project_publication_source_images
from tests.unit.test_git_first_restore import repo, _restore_plan


@pytest.fixture
def restoration(repo):
    spec = repo.root / "specs/001-example"
    (spec / "spec-artifact-graph.json").write_bytes(b"old graph\n")
    (spec / "unknowns.md").write_bytes(b"retained evidence\n")
    repo.git("add", ".")
    repo.git("commit", "-qm", "capture graph and evidence")
    repo.base_commit = repo.head()
    plan = _restore_plan(repo)
    (repo.root / "runs/test").mkdir(parents=True)
    graph = _seal(repo.root, repo.root / "runs/test",
        {"specs/001-example/spec-artifact-graph.json": b"new graph\n"}, {})
    with graph.inspect_sources(tree_paths=("specs/001-example",), file_paths=("README.md",)) as sources:
        pass
    return repo, plan, sources


def compose(restoration):
    from harness import discovery_restoration_sources
    repo, plan, sources = restoration
    return discovery_restoration_sources.restoration_source_snapshot(
        project_root=repo.root, plan=plan, sources=sources)


def test_composite_projection_preserves_native_selected_bytes_and_unowned_sources(restoration):
    repo, plan, sources = restoration
    result = compose(restoration)
    final = project_publication_source_images(result)
    files = {item.path: item for tree in final.trees for item in tree.files}
    assert files["specs/001-example/spec.md"].content == b"#!/bin/sh\n# selected spec\n"
    assert files["specs/001-example/spec.md"].image.mode == 0o755
    assert files["specs/001-example/quality-gates.md"].content == b"# selected gates\n"
    assert files["specs/001-example/issues.md"].content == b"# selected issues\n"
    assert files["specs/001-example/spec-artifact-graph.json"].content == b"new graph\n"
    assert files["specs/001-example/unknowns.md"].content == b"retained evidence\n"
    assert final.files == sources.files
    assert result.publication.marker != sources.publication.marker
    assert result == compose(restoration)
    assert repo.spec_bytes() == b"# current spec\n" and repo.head() == plan.base_commit
    assert (repo.root / "specs/001-example/spec-artifact-graph.json").read_bytes() == b"old graph\n"


@pytest.mark.parametrize("damage", ["artifact", "mode", "graph_scope", "plan", "duplicate"])
def test_composite_projection_rejects_unbound_preimages_or_writers(restoration, damage):
    repo, plan, sources = restoration
    if damage in {"artifact", "mode"}:
        tree, = sources.trees
        files = []
        for item in tree.files:
            if item.path.endswith("/spec.md"):
                content = b"drifted\n" if damage == "artifact" else item.content
                item = replace(item, content=content, image=replace(item.image,
                    sha256=hashlib.sha256(content).hexdigest(), mode=0o600 if damage == "mode" else item.image.mode))
            files.append(item)
        sources = replace(sources, trees=(replace(tree, files=tuple(files)),))
    elif damage == "graph_scope":
        op, = sources.publication.operations
        sources = replace(sources, publication=replace(sources.publication,
            operations=(replace(op, target="specs/001-example/unknowns.md"),)))
    elif damage == "plan":
        plan = replace(plan, selected_manifest_sha256="b" * 64)
    else:
        plan = replace(plan, entries=(*plan.entries, plan.entries[0]))
    with pytest.raises(ValueError):
        compose((repo, plan, sources))


def test_projection_before_graph_staging_has_only_native_owned_changes(restoration):
    from harness import discovery_restoration_sources
    repo, plan, sources = restoration
    sources = replace(sources, publication=replace(sources.publication, operations=()))
    result = discovery_restoration_sources.restoration_source_snapshot(
        project_root=repo.root, plan=plan, sources=sources)
    files = {item.path: item.content for tree in project_publication_source_images(result).trees for item in tree.files}
    assert files["specs/001-example/spec-artifact-graph.json"] == b"old graph\n"
    assert files["specs/001-example/spec.md"] == b"#!/bin/sh\n# selected spec\n"


@pytest.mark.parametrize("damage", ["native_preimage", "artifact", "evidence", "external", "marker", "graph", "extra"])
def test_graph_guard_rejects_drift_outside_its_exact_restore_progress(restoration, damage):
    from harness.discovery_restoration_sources import graph_publication_sources
    from harness.discovery_producer import identity_spec_tree
    from harness.squad_publication import load_prepared_publication
    from tests.unit.test_git_first_restore import _apply
    repo, plan, graph_sources = restoration
    logical = compose(restoration)
    if damage != "native_preimage":
        _apply(repo, plan)
    if damage in {"artifact", "evidence", "external", "graph", "extra"}:
        target = {"artifact": "specs/001-example/spec.md", "evidence": "specs/001-example/unknowns.md",
            "external": "README.md", "graph": "specs/001-example/spec-artifact-graph.json",
            "extra": "specs/001-example/extra.md"}[damage]
        (repo.root / target).write_bytes(b"unauthorized image\n")
    publication = load_prepared_publication(repo.root, repo.root / "runs/test", graph_sources.publication.marker)
    # The real stage inspector itself rejects an unknown graph image.
    if damage == "graph":
        from harness.squad_publication import PublicationError
        with pytest.raises(PublicationError):
            with publication.inspect_sources(tree_paths=("specs/001-example",), file_paths=("README.md",)):
                pass
        return
    with publication.inspect_sources(tree_paths=("specs/001-example",), file_paths=("README.md",)) as observed:
        pass
    # This unit test isolates nonmetadata source validation; the cross-owner
    # test below uses the actual checkpoint proof/projector as well.
    observed = replace(observed, trees=tuple(identity_spec_tree(tree) for tree in observed.trees))
    if damage == "marker":
        observed = replace(observed, publication=replace(observed.publication,
            marker=replace(observed.publication.marker, manifest_sha256="d" * 64)))
    with pytest.raises(ValueError):
        graph_publication_sources(logical=logical, graph_sources=graph_sources, observed=observed)


@pytest.mark.parametrize("stop_after", ["prepare", "native_restore", "graph", "identity"])
def test_native_writers_join_one_forward_identity_continuation(restoration, stop_after):
    """Exercise the existing writers, not managed selection/dispatch admission."""
    from dataclasses import asdict
    from harness.discovery_restoration import requirement_restoration_changes
    from harness.element_identity_lifecycle import ElementCreate, ElementRevision
    from harness.element_identity_publication import (
        PublicationIntentRequest, PublicationSourceClaim, PublicationOperation, PublicationContinuationClaim,
    )
    from harness.element_identity_request_codec import encode_request
    from harness.element_identity_store import IdentityStore
    from harness.squad_publication import load_prepared_publication
    from harness.squad_source_baseline_codec import encode_initial_publication_sources
    from harness.squad_source_manifest import snapshot_source_manifest
    from tests.unit.test_git_first_restore import _apply

    repo, plan, graph_sources = restoration
    spec_id = "001-example"
    identity = IdentityStore.initialize(repo.root)
    identity.reserve(spec_id=spec_id, kind="FR", operation_id="reserve", count=2)
    identity.apply_lifecycle(spec_id=spec_id, operation_id="a", changes=(
        ElementCreate("FR-000001", "Movement", "Move in scene", "reserve"),))
    selected_history = identity.identity_history(spec_id=spec_id)
    identity.apply_lifecycle(spec_id=spec_id, operation_id="b", changes=(
        ElementRevision("FR-000001", "1", "Movement", "Move using arrows"),
        ElementCreate("FR-000002", "Lighting", "Light the scene", "reserve")))
    initial = replace(graph_sources, publication=replace(graph_sources.publication, operations=()))
    identity.register_source_context(spec_id=spec_id, context_id="run", operation_id="register",
        manifest=snapshot_source_manifest(trees=initial.trees, files=initial.files))
    parent_request = PublicationIntentRequest(initial.publication.marker.manifest_sha256, "parent-proof",
        sources=PublicationSourceClaim("run", "register", encode_initial_publication_sources(initial)),
        continuation_id="restore")
    identity.prepare_identity_publication(spec_id=spec_id, operation_id="parent", request=parent_request)
    original = identity.apply_identity_publication(spec_id=spec_id, operation_id="parent")
    row = identity.identity_publication(spec_id=spec_id, operation_id="parent")
    changes = requirement_restoration_changes(identity, spec_id=spec_id,
        selected_history=selected_history, snapshot_id=plan.selected_candidate_id)
    operations = (PublicationOperation("lifecycle", "restore-membership", encode_request("lifecycle", changes)),)
    logical = compose(restoration)
    child = PublicationIntentRequest(logical.publication.marker.manifest_sha256, "bound-restore-proof", operations,
        PublicationSourceClaim("run", "parent", encode_initial_publication_sources(logical)),
        continuation=PublicationContinuationClaim("parent", row["preparation"]["request_sha256"],
            hashlib.sha256(row["application_receipt"].encode("ascii")).hexdigest(), plan.completion_id, "c" * 64))
    proposed = identity.preview_identity_history(spec_id=spec_id, operations=operations,
        publication_id="restore", continuation_request=child)
    child = replace(child, proposed_history_sha256=proposed.sha256)
    identity.prepare_identity_publication(spec_id=spec_id, operation_id="restore", request=child)

    def restore_files_and_graph():
        from functools import partial
        from harness.discovery_completion import _project_checkpoint_tree
        from harness.discovery_restoration_sources import graph_publication_sources
        from harness.phase_checkpoints import fresh_completion_checkpoint_ledger_image
        receipt = _apply(repo, plan)
        native_sources = replace(logical, publication=replace(logical.publication,
            operations=tuple(op for op in logical.publication.operations
                if not op.target.endswith("/spec-artifact-graph.json"))))
        tree, = project_publication_source_images(native_sources).trees
        ledger = fresh_completion_checkpoint_ledger_image(project_root=repo.root,
            spec_dir=repo.root / "specs/001-example", phase="phase1-quality-candidate-restored",
            next_phase=plan.next_phase, run_id=plan.run_id, spec_id=plan.spec_id,
            completion_id=plan.completion_id, checkpoint_prestate={"kind": "git_head", "head": plan.base_commit},
            expected_receipt=receipt.checkpoint, allow_pending=False, ledger_preimage=None,
            artifact_images={item.path: (item.image.mode, item.content) for item in tree.files})
        publication = load_prepared_publication(repo.root, repo.root / "runs/test", graph_sources.publication.marker)
        with publication.inspect_sources(tree_paths=("specs/001-example",), file_paths=("README.md",)) as current:
            pass
        initial_graph = graph_publication_sources(logical=logical, graph_sources=graph_sources,
            observed=current, project_tree=partial(_project_checkpoint_tree,
                spec="specs/001-example", ledger=ledger, pending=False))
        publication.publish_sources(initial_graph)
        return receipt

    # Stop at a real durable boundary, reopen, then repeat the native owners.
    if stop_after != "prepare":
        _apply(repo, plan)
    if stop_after in {"graph", "identity"}:
        restore_files_and_graph()
    if stop_after == "identity":
        identity.apply_identity_publication(spec_id=spec_id, operation_id="restore")
    identity = IdentityStore.open(repo.root)
    identity.prepare_identity_publication(spec_id=spec_id, operation_id="restore", request=child)
    restore_files_and_graph()
    identity.apply_identity_publication(spec_id=spec_id, operation_id="restore")
    assert identity.identity_history(spec_id=spec_id) == proposed
    assert identity.lookup(spec_id=spec_id, element_id="FR-000001")["revision"] == "3"
    assert identity.lookup(spec_id=spec_id, element_id="FR-000002")["present"] is False
    assert identity.source_context(spec_id=spec_id, context_id="run")["manifest"] == asdict(
        project_publication_source_images(logical).manifest)
    assert identity.apply_identity_publication(spec_id=spec_id, operation_id="parent") == original
    assert identity.pending_identity_publication(spec_id=spec_id)["preparation"]["operation_id"] == "parent"
    identity.release_identity_publication(spec_id=spec_id, operation_id="parent", completion_payload="complete")
    assert identity.pending_identity_publication(spec_id=spec_id) is None
    assert identity.reserve(spec_id=spec_id, kind="FR", operation_id="next", count=1) == ("FR-000003",)
    assert len(repo.checkpoint_rows()) == 1 and repo.head() == plan.target_commit
    assert repo.spec_bytes() == b"#!/bin/sh\n# selected spec\n"
    assert (repo.root / "specs/001-example/spec-artifact-graph.json").read_bytes() == b"new graph\n"
    identity.audit()
