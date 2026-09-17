"""Detached source result for native restore plus native graph publication.

The composite marker is a logical identity-journal claim, never an outbox stage.
Git-first remains the only artifact writer; Squad publication owns only the graph.
The completion owner must authenticate candidate selection and both writer proofs
before accepting this result. This module reads immutable objects and writes none.
"""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

from harness.git_first_restore import verify_git_first_restore_commit, _blob_bytes
from harness.squad_publication import PublicationMarker
from harness.squad_publication_snapshot import (
    PublicationImageDescriptor, PublicationOperationSnapshot, PublicationSnapshot,
)
from harness.squad_source_baseline_codec import encode_initial_publication_sources
from harness.squad_source_snapshot import PublicationSourcesSnapshot


def restoration_source_snapshot(*, project_root, plan, sources):
    """Compose exact initial sources with zero or one graph-only staged write."""
    try:
        return _compose(Path(project_root), plan, sources)
    except Exception:
        raise ValueError("restoration source projection is not bound") from None


def _compose(root, plan, sources):
    encode_initial_publication_sources(sources)
    verify_git_first_restore_commit(root, plan)
    spec = "specs/" + plan.spec_id
    tree, = (tree for tree in sources.trees if tree.path == spec)
    before = {item.path: item for item in tree.files}
    graph_operations = sources.publication.operations
    if len(graph_operations) > 1 or any(op.action != "write"
            or op.target != spec + "/spec-artifact-graph.json" for op in graph_operations):
        raise ValueError("only the graph has publication write authority")
    operations = list(graph_operations)
    for entry in plan.entries:
        original = before[entry.path]
        preimage = PublicationImageDescriptor("file", entry.base_sha256, int(entry.base_mode[-3:], 8))
        if original.image != preimage:
            raise ValueError("restore preimage differs from captured sources")
        content = _blob_bytes(root, entry.target_blob_oid)
        postimage = PublicationImageDescriptor("file", entry.target_sha256, int(entry.target_mode[-3:], 8))
        operations.append(PublicationOperationSnapshot("write", entry.path, preimage,
            postimage, preimage, original.content, content))
    claim = dict(version=1, restore=asdict(plan),
        graph=sources.publication.marker.to_dict() if graph_operations else None)
    digest = hashlib.sha256(json.dumps(claim, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()
    logical = PublicationSnapshot(PublicationMarker(1, digest[:32], digest), 0,
        tuple(sorted(operations, key=lambda operation: operation.target)))
    result = PublicationSourcesSnapshot(logical, sources.trees, sources.files)
    encode_initial_publication_sources(result)
    return result


def graph_publication_sources(*, logical, graph_sources, observed, project_tree=None):
    """Recover the graph writer's initial guard after native artifact restoration.

    The caller authenticates the logical continuation and supplies the existing
    checkpoint owner's projector when metadata has advanced. The native source
    guard validates every remaining source, including graph pre/post progress.
    Returned sources retain the observed physical metadata so the subsequent
    guarded write still detects races. No fresh observation becomes authority.
    """
    from harness.squad_source_guard import _validate_source_progress
    from harness.squad_source_projection import project_publication_source_images
    try:
        encode_initial_publication_sources(logical)
        encode_initial_publication_sources(graph_sources)
        graph, = graph_sources.publication.operations
        if (graph.action != "write" or not graph.target.endswith("/spec-artifact-graph.json")
                or graph.preimage.kind != "file"
                or [op for op in logical.publication.operations if op.target == graph.target] != [graph]):
            raise ValueError("graph stage differs from logical continuation")
        native = replace(logical, publication=replace(logical.publication,
            operations=tuple(op for op in logical.publication.operations if op.target != graph.target)))
        restored = project_publication_source_images(native)
        expected = PublicationSourcesSnapshot(graph_sources.publication, restored.trees, restored.files)
        encode_initial_publication_sources(expected)
        normalized = observed if project_tree is None else replace(observed,
            trees=tuple(project_tree(tree) for tree in observed.trees))
        _validate_source_progress(expected, normalized)
        before, = (item for tree in expected.trees for item in tree.files if item.path == graph.target)
        initial = PublicationSourcesSnapshot(graph_sources.publication,
            tuple(replace(tree, files=tuple(before if item.path == graph.target else item for item in tree.files))
                for tree in observed.trees), observed.files)
        encode_initial_publication_sources(initial)
        return initial
    except Exception:
        raise ValueError("restoration graph publication is not bound") from None
