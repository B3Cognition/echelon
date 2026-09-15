"""Inactive reviewed-discovery publication preparation, without promotion.

The caller owns Phase A/run leases. The returned package is a proposed handoff,
not durable Squad completion authority. Full runtime dependencies guard source
promotion; the identity source claim retains the registered spec-only selection.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import uuid

from echelon.spec_graph import render_spec_graph
from echelon.spec_graph_captured import CapturedGraphMemory, build_captured_identity_graph
from echelon.spec_graph_memory import GraphMemoryAudit
from harness.discovery_bootstrap_state import bootstrap_from_state
from harness.discovery_operation import ReviewedDiscoveryCandidate, _capture, run_discovery_operation
from harness.discovery_operation_state import operation_from_state
from harness.discovery_producer import producer_component, producer_phase, synthesis_input_source, identity_spec_tree, tracker_round, tracker_input_source
from harness.element_identity_publication import PublicationIntentRequest, PublicationSourceClaim
from harness.element_identity_store import IdentityStore
from harness.squad_publication import PreparedSquadPublication, SquadPublicationTransaction
from harness.squad_source_baseline_codec import encode_initial_publication_sources
from harness.squad_source_manifest import snapshot_source_manifest
from harness.squad_source_projection import project_publication_source_images
from harness.squad_source_snapshot import PublicationSourcesSnapshot
from harness.state_transaction_namespace import (
    PENDING_CONTROLLER_COMPLETION_KEY, PENDING_EXTERNAL_PUBLICATION_KEY, PRODUCT_INPUT_MUTATION_KEY,
)


@dataclass(frozen=True)
class PreparedDiscoveryPublication:
    publication: PreparedSquadPublication
    sources: PublicationSourcesSnapshot
    request: PublicationIntentRequest
    candidate: ReviewedDiscoveryCandidate
    graph: bytes


def _selected(root, state_store, store, producer="discovery", *, repair_unit=None):
    state = state_store.load()
    selected = bootstrap_from_state(state)
    operation = operation_from_state(state, producer, repair_unit=repair_unit)
    if (selected is None or "managed_identity" not in state or operation is None
            or not operation["attempts"] or (operation["attempts"][-1]["result"] or {}).get("status") != "accepted"
            or state.get("phase") != producer_phase(producer) or state.get("status") != "running"
            or str(root) != selected["selection"]["project_root"]
            or str(state_store.squad_dir) != selected["selection"]["run_dir"]
            or any(key in state for key in (PENDING_CONTROLLER_COMPLETION_KEY,
                PENDING_EXTERNAL_PUBLICATION_KEY, PRODUCT_INPUT_MUTATION_KEY))
            or store.pending_identity_publication(spec_id=operation["binding"]["spec_id"]) is not None):
        raise ValueError("accepted unbound discovery required")
    return state, selected, operation


def _replay(root, state_store, executor, binding, producer="discovery", *, repair_unit=None):
    result = run_discovery_operation(root, state_store, executor,
        input_tree=binding["input_tree"], artifact_paths=tuple(binding["artifact_paths"]),
        editable_revisions=tuple(tuple(pair) for pair in binding["editable_revisions"]),
        unowned_writable_paths=tuple(binding["unowned_writable_paths"]), intent=binding["intent"], replay_only=True,
        producer=producer, repair_unit=repair_unit)
    if result.status != "reviewed" or result.candidate is None:
        raise ValueError("checked discovery replay required")
    return result.candidate


def _manifest(sources):
    return snapshot_source_manifest(trees=sources.trees, files=sources.files)


def _inspect(publication, original, writes, modes):
    with publication.inspect_sources(tree_paths=tuple(tree.path for tree in original.trees),
            file_paths=tuple(item.path for item in original.files)) as sources:
        if _manifest(sources) != _manifest(original):
            raise ValueError("reviewed source images changed")
        operations = sources.publication.operations
        if (sources.publication.promoted_prefix != 0 or len(operations) != len(writes)
                or {op.target for op in operations} != set(writes)
                or any(op.action != "write" or op.postimage.kind != "file"
                    or op.postimage_bytes != writes[op.target]
                    or op.postimage.mode != modes.get(op.target, 0o644) for op in operations)):
            raise ValueError("sealed outputs differ from reviewed images")
    return sources


def _seal(root, run, writes, modes):
    transaction = SquadPublicationTransaction.begin(root, run, uuid.uuid4().hex)
    owned = {Path(path) for path in writes}
    for index, (target, content) in enumerate(sorted(writes.items())):
        staged = transaction.build_path(f"artifact-{index}")
        staged.write_bytes(content)
        staged.chmod(modes.get(target, 0o644))
        transaction.add_write(Path(target), staged, owned_paths=owned)
    return transaction.seal()


def _graph(sources, history, selection):
    # _capture admitted no configured memory wing or published RE. Report that
    # actual boundary as unavailable, not a successful external memory audit.
    audit = GraphMemoryAudit("returned", 1, None, "unavailable", 0, 0, 0,
        (), (), (), (), (), (), (), ("memory_not_configured",))
    graph = build_captured_identity_graph(spec_id=selection["spec_id"], lifecycle="phase_a",
        generator_version="managed-discovery-v1", sources=project_publication_source_images(sources),
        policy_paths=(), memory=(CapturedGraphMemory("canonical-spec", (), (), audit),),
        re_artifacts=(), re_sources=(), history=history, spec_source_path=selection["spec_path"])
    return render_spec_graph(graph)


def prepare_discovery_publication(project_root, state_store, executor, *, completion_id, producer="discovery", repair_unit=None) -> PreparedDiscoveryPublication:
    """Seal a checked accepted candidate; ordinary errors expose no source text.

    Interrupted preparations may leave unbound outbox stages. Only the existing
    publication owner may discard them; pending publications are never reselected.
    """
    try:
        return _prepare(project_root, state_store, executor, completion_id, producer, repair_unit=repair_unit)
    except Exception:
        pass
    raise ValueError("discovery publication preparation requires reconciliation")


def _prepare(project_root, state_store, executor, completion_id, producer="discovery", *, repair_unit=None):
    if type(completion_id) is not str or re.fullmatch(r"[0-9a-f]{32}", completion_id) is None:
        raise ValueError("invalid proposed completion ID")
    root = Path(project_root)
    store = IdentityStore.open(root)
    state, selected, operation = _selected(root, state_store, store, producer, repair_unit=repair_unit)
    binding, selection = operation["binding"], selected["selection"]
    candidate = _replay(root, state_store, executor, binding, producer, repair_unit=repair_unit)
    fingerprint, *_, original, source_inputs = _capture(root, state_store, store, selected,
        binding["input_tree"], tuple(binding["artifact_paths"]), producer=producer, repair_unit=repair_unit)
    if fingerprint != candidate.source_fingerprint:
        raise ValueError("reviewed discovery inputs changed")
    spec, = (tree for tree in original.trees if tree.path == selection["spec_path"])
    modes = {item.path: item.image.mode for item in spec.files}
    authored = {artifact.path: artifact.after_text for artifact in candidate.artifacts
        if artifact.path in binding["artifact_paths"]}
    missing = set(binding["artifact_paths"]) - set(authored)
    from harness.discovery_semantics import optional_artifacts
    if not missing <= optional_artifacts(producer) or any(text is None for text in authored.values()):
        raise ValueError("reviewed discovery outputs missing")
    writes = {selection["spec_path"] + "/" + name: text.encode("utf-8") for name, text in authored.items()}
    provisional = _seal(root, state_store.squad_dir, writes, modes)
    source_only = _inspect(provisional, original, writes, modes)
    graph = _graph(source_only, candidate.history, selection)
    writes[selection["spec_path"] + "/spec-artifact-graph.json"] = graph
    publication = _seal(root, state_store.squad_dir, writes, modes)
    sources = _inspect(publication, original, writes, modes)
    if _graph(sources, candidate.history, selection) != graph:
        raise ValueError("final projected graph changed")
    # Recheck roles, replies, reservations, history and all runtime inputs after
    # staging. Replay-only cannot fill in any missing accepted receipt.
    if _replay(root, state_store, executor, binding, producer, repair_unit=repair_unit) != candidate:
        raise ValueError("reviewed discovery changed during staging")
    if _selected(root, state_store, store, producer, repair_unit=repair_unit) != (state, selected, operation):
        raise ValueError("discovery publication selection changed")
    sources = _inspect(publication, original, writes, modes)
    observed = store.check_managed_context(spec_id=binding["spec_id"], run_id=binding["run_id"], record=state["managed_identity"])
    baseline = PublicationSourcesSnapshot(sources.publication, (identity_spec_tree(spec) if producer != "discovery" or repair_unit is not None else spec,), ())
    recovery_fields = dict(version=2, completion_id=completion_id, operation=operation,
        candidate_sha256=candidate.candidate_sha256, source_fingerprint=candidate.source_fingerprint,
        candidate_inputs=candidate.candidate_inputs, source_inputs=candidate.source_inputs,
        review=candidate.review, provider=producer_component(state, producer, "turns", repair_unit=repair_unit), sources=encode_initial_publication_sources(sources),
        graph_sha256=hashlib.sha256(graph).hexdigest())
    if producer == "synthesizer":
        recovery_fields.update(version=3, producer=producer, source_completion=synthesis_input_source(state))
        if binding["operation_id"].startswith("synthesizer-"):
            row = tracker_round(state, binding["operation_id"], producer=producer)
            recovery_fields.update(version=9, **{key: row[key] for key in ("refresh", "execution_input", "predecessor")})
    if producer in {"tracker", "why1"}:
        recovery_fields.update(version=6 if producer == "why1" else 4, producer=producer,
            source_completion=tracker_input_source(state, producer=producer),
            resolution=tracker_round(state, producer=producer)["resolution"])
    if repair_unit is not None:
        from harness.discovery_producer import repair_record
        claim = repair_record(state, producer, repair_unit)["selection"]
        recovery_fields.update(version=8, producer=producer, repair_unit=repair_unit,
            source_completion=claim["source"])
    recovery = json.dumps(recovery_fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    context = observed["source_context"]
    request = PublicationIntentRequest(publication.marker.manifest_sha256, recovery, candidate.operations,
        PublicationSourceClaim(context["context_id"], context["operation_id"], encode_initial_publication_sources(baseline)),
        proposed_history_sha256=candidate.history.sha256)
    provisional.discard()
    return PreparedDiscoveryPublication(publication, sources, request, candidate, graph)
