"""Managed Tracker/WHY1 bridge to the existing human-input and publication owners.

No decision is inferred from Markdown. Preparation is detached; only the normal
resolution CAS and completion transaction may publish its candidate.
"""
from dataclasses import asdict
import hashlib
import json

from harness.blocked_decision import validate_blocked_decision
from harness.clarification_candidate import ClarificationRecord, prepare_clarification_candidate
from harness.discovery_bootstrap_state import bootstrap_from_state
from harness.discovery_operation import _capture
from harness.discovery_operation_state import operation_from_state
from harness.discovery_producer import SOURCE_FIELDS, tracker_rounds, identity_spec_tree, producer_phase
from harness.discovery_publication import _seal, _inspect, _graph
from harness.discovery_semantics import artifact_roles
from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope
from harness.element_identity_publication import PublicationIntentRequest, PublicationSourceClaim
from harness.element_identity_snapshot import IdentityHistorySnapshot
from harness.element_identity_store import IdentityStore
from harness.squad_source_baseline_codec import encode_initial_publication_sources, decode_initial_publication_sources
from harness.squad_source_manifest import snapshot_source_manifest
from harness.squad_source_snapshot import PublicationSourcesSnapshot


def _record(decision, producer="tracker"):
    checked = validate_blocked_decision(decision)
    if (checked != decision or checked["status"] != "resolved"
            or checked["source_phase"] != producer_phase(producer) or checked["resolution_handler"] != "clarification_resume"
            or checked["selected_option_id"] is not None):
        raise ValueError("exact free-text Tracker resolution required")
    return ClarificationRecord(checked["id"], checked["question"], checked["answer_text"])


def previous_records(state, operation_id, producer="tracker"):
    return _previous_records(state, operation_id, producer, set())


def _previous_records(state, operation_id, producer, seen):
    rounds = tracker_rounds(state, producer)["rounds"]
    # Follow protected round ancestry, not JSON object ordering.
    records = []
    while True:
        if (producer, operation_id) in seen or operation_id not in rounds:
            raise ValueError("invalid clarification ancestry")
        seen.add((producer, operation_id))
        row = rounds[operation_id]
        if "refresh" in row:
            if producer == "why1" and "execution_input" in row:
                previous = _previous_records(state, row["tracker_parent"], "tracker", seen)
                return previous + tuple(reversed(records))
            if producer == "tracker":
                why1 = tracker_rounds(state, "why1")
                matches = [] if why1 is None else [item for item in why1["rounds"].values()
                    if item.get("refresh", {}).get("repair_unit") == row["refresh"]["repair_unit"]]
                if len(matches) != 1:
                    raise ValueError("Tracker refresh requires its requesting WHY1 history")
                previous = _previous_records(state, matches[0]["predecessor"], "why1", seen)
                return previous + tuple(reversed(records))
            # An inactive refresh is not a human answer or a new history root.
            operation_id = row["predecessor"]
            continue
        resolution = row["resolution"]
        if resolution is None:
            break
        records.append(_record(resolution["decision"], producer))
        operation_id = row["predecessor"]
    previous = ()
    if producer == "why1":
        tracker = tracker_rounds(state)
        if tracker is None:
            raise ValueError("WHY1 requires retained Tracker ancestry")
        parent = row.get("tracker_parent")
        if parent is None:
            # Legacy roots remain readable before refresh execution. An empty
            # refresh association is not new history; never guess after one ran.
            if any("refresh" in item and item["operation"] is not None for item in tracker["rounds"].values()):
                raise ValueError("historical WHY1 Tracker parent must be pinned")
            parent = tracker["active"]
            while "refresh" in tracker["rounds"][parent]:
                parent = tracker["rounds"][parent]["predecessor"]
        previous = _previous_records(state, parent, "tracker", seen)
    return previous + tuple(reversed(records))


def _candidate(sources, spec_path, run_path, decision, previous, producer="tracker"):
    spec, = (tree for tree in sources.trees if tree.path == spec_path)
    texts = {item.path[len(spec_path) + 1:]: item.content.decode("utf-8")
        for item in identity_spec_tree(spec).files if item.path.endswith(".md")}
    staging = run_path + "/staging/"
    files = {item.path: None if item.content is None else item.content.decode("utf-8") for item in sources.files
        if item.path.startswith(staging)}
    candidate = prepare_clarification_candidate(decision=_record(decision, producer), previous=previous,
        receipt_before=files[staging + "user-clarifications.md"],
        policy_before=files[staging + "feature-policy.json"], artifacts=texts)
    writes = {staging + "user-clarifications.md": candidate.receipt_text,
        staging + "feature-policy.json": candidate.policy_text,
        staging + "feature-policy.md": candidate.policy_context_text,
        spec_path + "/feature-policy-reconciliation.md": candidate.reconciliation_text}
    return candidate, writes, texts


def prepare(root, state_store, *, state, resolved, completion_id, producer="tracker"):
    from harness.discovery_completion import _json, _hash, decode_binding
    selected = bootstrap_from_state(state)
    operation = operation_from_state(state, producer)
    selection = selected["selection"]
    source = {key: state["last_dispatch"][key] for key in SOURCE_FIELDS}
    store = IdentityStore.open(root)
    _, _, _, history, _, _, original, source_inputs = _capture(root, state_store, store, selected,
        operation["binding"]["input_tree"], tuple(operation["binding"]["artifact_paths"]),
        producer=producer, source_completion=source)
    previous = previous_records(state, operation["binding"]["operation_id"], producer)
    candidate, texts, before = _candidate(original, selection["spec_path"],
        state_store.squad_dir.relative_to(root).as_posix(), resolved, previous, producer)
    spec_path = selection["spec_path"]
    report = "feature-policy-reconciliation.md"
    from harness.discovery_producer import post_why1_context
    post_review = post_why1_context(state, producer)
    artifacts = tuple(CandidateArtifact(name, artifact_roles("why1" if post_review else producer)[name], text,
        candidate.reconciliation_text if name == report else text) for name, text in before.items())
    if report not in before:
        artifacts += (CandidateArtifact(report, "references", None, candidate.reconciliation_text),)
    artifacts += tuple(CandidateArtifact(path, "references", None, text)
        for path, text in texts.items() if path != spec_path + "/" + report)
    scope_paths = (report, *(path for path in texts if path != spec_path + "/" + report))
    from harness.discovery_candidate import issue_report_changes
    reports, _ = issue_report_changes(artifacts, (), history, report_id=completion_id) if producer == "why1" or post_review else ((), ())
    preview = store.preview_identity_candidate(spec_id=selection["spec_id"], artifacts=artifacts,
        scope=IdentityEditScope(scope_paths, (), scope_paths), operations=(), issue_reports=reports)
    if preview.check.diagnostics or preview.history != history:
        raise ValueError("clarification identity reconciliation required")
    writes = {path: text.encode("utf-8") for path, text in texts.items()}
    modes = {item.path: item.image.mode for tree in original.trees for item in tree.files}
    modes.update({item.path: item.image.mode for item in original.files if item.content is not None})
    provisional = _seal(root, state_store.squad_dir, writes, modes)
    staged = _inspect(provisional, original, writes, modes)
    graph = _graph(staged, history, selection)
    writes[spec_path + "/spec-artifact-graph.json"] = graph
    publication = _seal(root, state_store.squad_dir, writes, modes)
    sources = _inspect(publication, original, writes, modes)
    if _graph(sources, history, selection) != graph or state_store.load() != state:
        raise ValueError("clarification inputs changed")
    spec, = (tree for tree in sources.trees if tree.path == spec_path)
    baseline = PublicationSourcesSnapshot(sources.publication, (identity_spec_tree(spec),), ())
    recovery = dict(version=7 if producer == "why1" else 5, producer=producer, completion_id=completion_id, operation=operation,
        source_completion=source, resolution=resolved, previous=[asdict(row) for row in previous],
        source_inputs=_json(source_inputs), source_fingerprint=_hash(source_inputs),
        candidate_inputs=_json(dict(artifacts=texts, history=asdict(history))),
        sources=encode_initial_publication_sources(sources), graph_sha256=hashlib.sha256(graph).hexdigest())
    context = source_inputs["authority"]["source_context"]
    request = PublicationIntentRequest(publication.marker.manifest_sha256, _json(recovery), (),
        PublicationSourceClaim(context["context_id"], context["operation_id"], encode_initial_publication_sources(baseline)),
        proposed_history_sha256=history.sha256)
    from harness.element_identity_publication import encode_publication_request
    decode_binding(dict(kind="external", marker=publication.marker.to_dict(),
        managed_discovery=dict(version=1, request=encode_publication_request(request))), completion_id=completion_id, state=state)
    provisional.discard()
    return publication, request, candidate


def decode_clarification_binding(publication, request, recovery, completion_id, state):
    from harness.discovery_completion import _closed, _require, _document, _hash, DiscoveryCompletionBinding
    _closed(recovery, ("version", "producer", "completion_id", "operation", "source_completion", "resolution",
        "previous", "source_inputs", "source_fingerprint", "candidate_inputs", "sources", "graph_sha256"))
    producer = recovery["producer"]
    _require(type(recovery["version"]) is int and ((recovery["version"], producer) in {(5, "tracker"), (7, "why1")})
        and (completion_id is None or completion_id == recovery["completion_id"]) and request.operations == ())
    source = _document(recovery["source_inputs"])
    _closed(source, ("manifest", "history", "authority", "runtime"))
    _require(_hash(source) == recovery["source_fingerprint"])
    candidate = _document(recovery["candidate_inputs"])
    _closed(candidate, ("artifacts", "history"))
    _require(candidate["history"] == source["history"] and candidate["history"]["sha256"] == request.proposed_history_sha256)
    history = IdentityHistorySnapshot(**source["history"])
    _require(hashlib.sha256(history.payload.encode("ascii")).hexdigest() == history.sha256)
    sources = decode_initial_publication_sources(recovery["sources"])
    baseline = decode_initial_publication_sources(request.sources.baseline_payload)
    _require(sources.publication == baseline.publication and sources.publication.marker.to_dict() == publication["marker"]
        and request.manifest_sha256 == sources.publication.marker.manifest_sha256
        and asdict(snapshot_source_manifest(trees=sources.trees, files=sources.files)) == source["manifest"])
    genesis, context = source["authority"]["managed_identity"], source["authority"]["source_context"]
    spec_path = genesis["spec_path"]
    spec, = (tree for tree in sources.trees if tree.path == spec_path)
    _require(baseline.trees == (identity_spec_tree(spec),) and baseline.files == ()
        and request.sources.context_id == genesis["context_id"] == context["context_id"]
        and request.sources.expected_operation_id == context["operation_id"]
        and asdict(snapshot_source_manifest(trees=baseline.trees, files=())) == context["manifest"])
    _closed(recovery["source_completion"], SOURCE_FIELDS)
    _require(request.sources.expected_operation_id == "discovery-completion-" + recovery["source_completion"]["dispatch_id"])
    selected = recovery["operation"]["binding"]
    # The selected spec/input trees may also be named context. Only the
    # separately captured runtime context identifies the run's staging owner.
    context_tree, = (tree for tree in sources.trees if tree.path.endswith("/context")
        and tree.path not in {spec_path, selected["input_tree"]})
    run_path = context_tree.path.removesuffix("/context")
    previous = tuple(ClarificationRecord(**row) for row in recovery["previous"])
    prepared, texts, _ = _candidate(sources, spec_path, run_path, recovery["resolution"], previous, producer)
    _require(candidate["artifacts"] == texts)
    writes = {path: text.encode("utf-8") for path, text in texts.items()}
    graph = _graph(sources, history, dict(spec_id=selected["spec_id"], spec_path=spec_path))
    _require(hashlib.sha256(graph).hexdigest() == recovery["graph_sha256"])
    writes[spec_path + "/spec-artifact-graph.json"] = graph
    modes = {item.path: item.image.mode for tree in sources.trees for item in tree.files}
    modes.update({item.path: item.image.mode for item in sources.files if item.content is not None})
    operations = sources.publication.operations
    _require(sources.publication.promoted_prefix == 0 and len(operations) == len(writes)
        and {op.target for op in operations} == set(writes)
        and all(op.action == "write" and op.postimage_bytes == writes[op.target]
            and op.postimage.mode == modes.get(op.target, 0o644) for op in operations))
    if state is not None:
        bootstrap = bootstrap_from_state(state)
        _require(bootstrap is not None and state["managed_identity"] == genesis
            and selected["run_id"] == bootstrap["selection"]["run_id"]
            and selected["spec_id"] == bootstrap["selection"]["spec_id"]
            and operation_from_state(state, producer, operation_id=selected["operation_id"]) == recovery["operation"]
            and previous_records(state, selected["operation_id"], producer) == previous)
        decisions = [state.get("blocked_decision"), *(row["resolution"]["decision"]
            for row in tracker_rounds(state, producer)["rounds"].values() if row["resolution"] is not None)]
        current = next((item for item in decisions if item and item["id"] == recovery["resolution"]["id"]), None)
        _require(current is not None)
        rounds = tracker_rounds(state, producer)
        successors = [row for row in rounds["rounds"].values() if row["resolution"] is not None
            and row["resolution"]["decision"]["id"] == recovery["resolution"]["id"]]
        if successors:
            successor, = successors
            _require(successor["predecessor"] == selected["operation_id"]
                and successor["source"] == recovery["source_completion"]
                and successor["resolution"]["completion"]["completion_id"] == recovery["completion_id"])
        else:
            dispatch = state.get("last_dispatch") or {}
            _require(rounds["active"] == selected["operation_id"] and state["blocked_decision"]["id"] == current["id"]
                and dispatch.get("phase_id") == producer_phase(producer) and dispatch.get("post_dispatch_complete") is True
                and {key: dispatch.get(key) for key in SOURCE_FIELDS} == recovery["source_completion"])
        if current["status"] == "resolved":
            _require(current == recovery["resolution"])
        else:
            from harness.squad_state import build_human_input_resolution_postimage
            from harness.human_input import AppliedHumanInputResolution
            resolved = recovery["resolution"]
            answer = AppliedHumanInputResolution(None, resolved["answer_text"], resolved["resolved_by"],
                rationale=resolved.get("resolution_rationale"), confidence=resolved.get("resolution_confidence"))
            _require(build_human_input_resolution_postimage(current, answer, resolved_at=resolved["resolved_at"]) == resolved)
    # Derived from the authenticated report; never accepted from provider prose
    # or a caller-supplied destination. Preserve the legacy reconciliation route.
    candidate["route"] = "phase1-what" if json.loads(prepared.reconciliation_json)["requires_repair"] else producer_phase(producer)
    return DiscoveryCompletionBinding(request, recovery, candidate, source, sources, baseline)


def require_parent(state, binding, store):
    """Authenticate the exact retained Tracker result that asked this question."""
    from harness.discovery_completion import _document, _require, decode_binding
    from harness.squad_completion import validate_retained_completion_proof
    from harness.element_identity_publication import encode_publication_request
    source = binding.recovery["source_completion"]
    retained = store.identity_publication(spec_id=binding.spec_id,
        operation_id="discovery-completion-" + source["dispatch_id"])
    _require(retained is not None and retained["state"] == "released")
    proof = _document(retained["completion_payload"])
    marker, intent, _ = validate_retained_completion_proof(proof["completion"], proof["proof"]["intent"], proof["proof"]["receipts"])
    _require(source == dict(dispatch_id=marker.completion_id, completion_intent_sha256=marker.intent_sha256,
        completion_receipts_sha256=marker.receipts_sha256, completed_publication_binding_sha256=marker.publication_binding_sha256))
    parent = decode_binding(intent.publication, completion_id=marker.completion_id, state=state)
    _require(parent is not None and parent.producer == binding.producer and not parent.clarification
        and parent.recovery["operation"] == binding.recovery["operation"]
        and retained["request"] == encode_publication_request(parent.request))
    decision, routing = binding.recovery["resolution"], parent.candidate["routing"]
    _require(routing["verdict"] == "STOP_AND_ASK" and routing["question"] == decision["question"]
        and routing["recommended_answer"] == decision["recommended_answer"] and routing["risk_level"] == decision["risk_level"])


def require_resolution_receipt(state, binding, marker):
    from harness.discovery_completion import _require
    expected = dict(schema_version=1, completion_id=marker.completion_id, intent_sha256=marker.intent_sha256,
        receipts_sha256=marker.receipts_sha256, publication_binding_sha256=marker.publication_binding_sha256,
        decision_id=binding.recovery["resolution"]["id"])
    producer = binding.producer
    receipts = [state.get("last_human_input_completion"), *(row["resolution"]["completion"]
        for row in tracker_rounds(state, producer)["rounds"].values() if row["resolution"] is not None)]
    _require(expected in receipts)
