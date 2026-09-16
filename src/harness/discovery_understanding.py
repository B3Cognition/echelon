"""Deterministic Understanding handoff through the existing completion owners.

There are no model turns or identity edits here. An empty guarded publication
retains the exact analyzed sources/report and the native completion proof.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re

from harness.discovery_bootstrap_state import bootstrap_from_state
from harness.discovery_inputs import admit_runtime_inputs
from harness.discovery_producer import SOURCE_FIELDS, identity_spec_tree
from harness.element_identity_publication import PublicationIntentRequest, PublicationSourceClaim
from harness.element_identity_store import IdentityStore
from harness.squad_publication import SquadPublicationTransaction, load_prepared_publication
from harness.squad_source_baseline_codec import encode_initial_publication_sources, decode_initial_publication_sources
from harness.squad_source_manifest import snapshot_source_manifest
from harness.squad_source_snapshot import PublicationSourcesSnapshot
from harness.understanding_gate import UnderstandingGateResult, _resolve_thresholds, _diagram_enabled


@dataclass(frozen=True)
class PreparedUnderstandingPublication:
    publication: object
    sources: PublicationSourcesSnapshot
    request: PublicationIntentRequest
    result: object


def _parent(root, run, state, source):
    from harness.discovery_completion import _retained_input_projection, _require
    binding, spec, context = _retained_input_projection(root, run, state, IdentityStore.open(root),
        operation_id="discovery-completion-" + source["dispatch_id"], source=source,
        require_checkpoint=False, required_route=("phase1-what", "phase1-understanding"))
    _require(binding.producer == "what" and not binding.clarification)
    return binding, spec, context


def _analysis_source(root, run, state):
    """A failed deterministic attempt does not replace the accepted WHAT parent."""
    from harness.discovery_completion import _document, _require, _retained_input_projection
    dispatch = state.get("last_dispatch") or {}
    if dispatch.get("phase_id") == "phase1-what":
        return {key: dispatch[key] for key in SOURCE_FIELDS}
    _require(dispatch.get("phase_id") == "phase1-understanding" and dispatch.get("verdict") == "BLOCKED")
    store = IdentityStore.open(root)
    selected = bootstrap_from_state(state)["selection"]
    observed = store.check_managed_context(spec_id=selected["spec_id"], run_id=state["run_id"], record=state["managed_identity"])
    operation = observed["source_context"]["operation_id"]
    binding, _, _ = _retained_input_projection(root, run, state, store, operation_id=operation,
        source=None, require_checkpoint=False, required_route=("phase1-what", "phase1-understanding"))
    _require(binding.producer == "what")
    row = store.identity_publication(spec_id=selected["spec_id"], operation_id=operation)
    marker = _document(row["completion_payload"])["completion"]
    return dict(dispatch_id=marker["completion_id"], completion_intent_sha256=marker["intent_sha256"],
        completion_receipts_sha256=marker["receipts_sha256"],
        completed_publication_binding_sha256=marker["publication_binding_sha256"])


def _report_result(recovery, sources, root, run, spec_path):
    from harness.discovery_completion import _require
    from harness.element_identity_json import _unique_object, _reject_number
    path = recovery["report_path"]
    prefix = (run / "evidence/understanding").relative_to(root).as_posix() + "/"
    _require(type(path) is str and path.startswith(prefix)
        and re.fullmatch(r"phase1-why2-iter-\d+(?:-[0-9a-f]{12})?\.json", path[len(prefix):]) is not None)
    captured, = (item for item in sources.files if item.path == path)
    _require(captured.content is not None)
    # Reports contain native numeric scores; the identity request string-tree
    # decoder deliberately rejects those. Keep duplicate/nonfinite rejection.
    report = json.loads(captured.content.decode("utf-8"), object_pairs_hook=_unique_object,
        parse_constant=_reject_number)
    spec, = (item for tree in sources.trees if tree.path == spec_path
        for item in tree.files if item.path == spec_path + "/spec.md")
    _require(type(recovery["iteration"]) is int and recovery["iteration"] >= 0
        and type(recovery["prior_scores"]) is list
        and report["schema_version"] == 1 and type(report["schema_version"]) is int
        and report["phase"] == "phase1-why2" and report["iteration"] == recovery["iteration"]
        and type(report["iteration"]) is int and type(report["pass"]) is bool
        and report["status"] == "completed"
        and report["spec"] == dict(path=spec.path, sha256=hashlib.sha256(spec.content).hexdigest()))
    thresholds = recovery["thresholds"]
    _require(report["thresholds"] == thresholds)
    if report["status"] == "completed":
        _require(report.get("analysis_inputs") == dict(spec_path=spec.path,
            spec_sha256=report["spec"]["sha256"], thresholds=thresholds,
            diagram_enabled=_diagram_enabled(recovery["config"])))
        from harness.proportional_quality import _authoritative_gates
        _authoritative_gates(report)
    error = report.get("error") if report["status"] == "error" else None
    _require(error is None if report["status"] == "completed" else type(error) is str and bool(error.strip()))
    gate = UnderstandingGateResult(report["status"] == "completed", report["pass"], "phase1-why2",
        recovery["iteration"], root / path, hashlib.sha256(captured.content).hexdigest(), report, error)
    updates = gate.state_updates(recovery["prior_scores"])
    if error:
        updates["blocked_reason"] = error
    return dict(verdict="DONE" if gate.completed else "BLOCKED", state_updates=updates)


def decode_understanding_binding(publication, request, recovery, completion_id, state):
    """Closed, provider-free envelope; accepted ancestry is checked separately."""
    from harness.discovery_completion import DiscoveryCompletionBinding, _require, _closed, _json
    _closed(recovery, ("version", "producer", "completion_id", "source_completion", "spec_id",
        "sources", "history", "authority", "runtime", "report_path", "iteration", "prior_scores", "config", "result",
        "project_root", "run_dir", "thresholds"))
    _require(type(recovery["version"]) is int and recovery["version"] == 14
        and recovery["producer"] == "understanding" and not request.operations
        and type(recovery["completion_id"]) is str and re.fullmatch(r"[0-9a-f]{32}", recovery["completion_id"])
        and (completion_id is None or completion_id == recovery["completion_id"]))
    parent = recovery["source_completion"]
    _closed(parent, SOURCE_FIELDS)
    _require(all(type(value) is str and re.fullmatch(r"[0-9a-f]{%d}" % (32 if key == "dispatch_id" else 64), value)
        for key, value in parent.items()))
    authority = recovery["authority"]
    genesis = authority["managed_identity"]
    root, run = Path(recovery["project_root"]), Path(recovery["run_dir"])
    _require(root.is_absolute() and run.is_relative_to(root) and run != root
        and str(root) == recovery["project_root"] and str(run) == recovery["run_dir"]
        and ".." not in root.parts and ".." not in run.parts
        and recovery["runtime"]["context_dir"] == str(run / "context"))
    history = recovery["history"]
    _closed(history, ("payload", "sha256"))
    _require(hashlib.sha256(history["payload"].encode("ascii")).hexdigest() == history["sha256"]
        and request.proposed_history_sha256 == history["sha256"])
    sources = decode_initial_publication_sources(recovery["sources"])
    baseline = decode_initial_publication_sources(request.sources.baseline_payload)
    spec, = (tree for tree in sources.trees if tree.path == genesis["spec_path"])
    _require(not sources.publication.operations and sources.publication.promoted_prefix == 0
        and sources.publication == baseline.publication and baseline.trees == (identity_spec_tree(spec),)
        and baseline.files == () and sources.publication.marker.to_dict() == publication["marker"]
        and request.manifest_sha256 == sources.publication.marker.manifest_sha256
        and request.sources.context_id == genesis["context_id"] == authority["source_context"]["context_id"]
        and request.sources.expected_operation_id == authority["source_context"]["operation_id"]
        == "discovery-completion-" + parent["dispatch_id"]
        and asdict(snapshot_source_manifest(trees=baseline.trees, files=())) == authority["source_context"]["manifest"]
        and recovery["result"] == _report_result(recovery, sources, root, run, genesis["spec_path"]))
    if state is not None:
        selected = bootstrap_from_state(state)["selection"]
        _require(state["managed_identity"] == genesis and selected["spec_id"] == recovery["spec_id"]
            and selected["project_root"] == str(root) and selected["run_dir"] == str(run))
    _require(_json(recovery) == request.recovery_payload)
    source = dict(history=history, authority=authority, runtime=recovery["runtime"])
    return DiscoveryCompletionBinding(request, recovery, dict(history=history, artifacts={}), source, sources, baseline)


def authenticate_understanding(root, run, state, completion, binding):
    from harness.discovery_completion import _require
    _parent(root, run, state, binding.recovery["source_completion"])
    from harness.config import get_full_resolved_config
    _require(get_full_resolved_config(root) == binding.recovery["config"])
    _require(_resolve_thresholds(root, binding.recovery["config"]) == binding.recovery["thresholds"])
    for key, value in binding.recovery["result"]["state_updates"].items():
        _require(state.get(key) == value)
    _require(completion.intent.route["to_phase"] == "phase1-why2")


def prepare_understanding_publication(root, state_store, node, executor, *, completion_id):
    from harness.config import get_full_resolved_config
    from harness.discovery_completion import released_discovery_input_projectors, _require, _json
    root, run = Path(root), state_store.squad_dir
    state = state_store.load()
    selection = bootstrap_from_state(state)["selection"]
    _require(state["phase"] == node.id == "phase1-understanding" and state["status"] == "running")
    source = _analysis_source(root, run, state)
    parent, _, _ = _parent(root, run, state, source)
    project_spec, project_context = released_discovery_input_projectors(root, run, state, source=source)
    capture = load_prepared_publication(root, run, selection["capture_marker"])
    trees = tuple(tree.path for tree in parent.sources.trees)
    files = tuple(item.path for item in parent.sources.files)
    with capture.inspect_sources(tree_paths=trees, file_paths=files) as before:
        spec, = (tree for tree in before.trees if tree.path == selection["spec_path"])
        project_spec(spec)
        runtime, _ = admit_runtime_inputs(root, run, state, project_context(before))
    config = get_full_resolved_config(root)
    thresholds = _resolve_thresholds(root, config)
    result = executor.execute(node, state_store)
    if result.verdict == "BLOCKED":
        # The native retryable-analysis owner records errors, including when
        # evidence storage itself failed. No completed publication is claimed.
        _require(state_store.load() == state)
        return PreparedUnderstandingPublication(None, before, None, result)
    report = Path(result.state_updates["understanding_evidence"]["path"])
    report_path = report.relative_to(root).as_posix()
    _require(state_store.load() == state and get_full_resolved_config(root) == config
        and _resolve_thresholds(root, config) == thresholds)
    publication = SquadPublicationTransaction.begin(root, run, completion_id).seal()
    with publication.inspect_sources(tree_paths=trees, file_paths=(*files, report_path)) as sources:
        _require(sources.trees == before.trees and tuple(item for item in sources.files if item.path != report_path) == before.files)
    identity = IdentityStore.open(root)
    authority = identity.check_managed_context(spec_id=selection["spec_id"], run_id=state["run_id"], record=state["managed_identity"])
    history = identity.identity_history(spec_id=selection["spec_id"])
    baseline = PublicationSourcesSnapshot(sources.publication, (identity_spec_tree(spec),), ())
    recovery = dict(version=14, producer="understanding", completion_id=completion_id, source_completion=source,
        spec_id=selection["spec_id"], sources=encode_initial_publication_sources(sources), history=asdict(history),
        authority=authority, runtime=runtime, report_path=report_path, iteration=state["iteration"],
        prior_scores=state.get("quality_scores") or [], config=config, result=result.echelon_result,
        project_root=str(root), run_dir=str(run), thresholds=thresholds)
    request = PublicationIntentRequest(publication.marker.manifest_sha256, _json(recovery), (),
        PublicationSourceClaim(authority["source_context"]["context_id"], authority["source_context"]["operation_id"],
            encode_initial_publication_sources(baseline)), proposed_history_sha256=history.sha256)
    decode_understanding_binding(dict(kind="external", marker=publication.marker.to_dict()), request, recovery, completion_id, state)
    return PreparedUnderstandingPublication(publication, sources, request, result)
