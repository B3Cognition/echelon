"""Managed discovery association for the existing Squad completion owner.

Digest preimages prove membership in protected accepted discovery state, not new
authority. The caller owns execution leases and durable completion provenance.
"""
from dataclasses import asdict, dataclass, replace
from functools import partial
import hashlib
import json
from pathlib import Path
import re

from harness.discovery_bootstrap_state import BOOTSTRAP_KEY, bootstrap_from_state
from harness.discovery_inputs import admit_runtime_inputs
from harness.discovery_operation_state import DISCOVERY_OPERATION_KEY, operation_from_state
from harness.discovery_publication import _graph
from harness.discovery_receipts import DiscoveryReceiptFile, receipt_round_operation_id
from harness.discovery_turn_state import DISCOVERY_TURNS_KEY
from harness.discovery_producer import producer_component, producer_phase, producer_role, synthesis_input_source, identity_spec_tree, tracker_round, tracker_input_source, validate_refresh_input, SOURCE_FIELDS
from harness.element_identity_json import strict_json, _unique_object
from harness.element_identity_publication import decode_publication_request, encode_publication_request
from harness.element_identity_snapshot import IdentityHistorySnapshot
from harness.element_identity_store import IdentityStore
from harness.squad_completion import CompletionError
from harness.squad_publication import PublicationError, load_prepared_publication
from harness.squad_source_baseline_codec import decode_initial_publication_sources
from harness.squad_source_manifest import snapshot_source_manifest
from harness.squad_source_projection import project_publication_source_images


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode("ascii")).hexdigest()


def _document(raw):
    value = json.loads(raw, object_pairs_hook=_unique_object)
    _require(_json(value) == raw)
    return value


def _require(condition):
    if not condition:
        raise ValueError("invalid managed discovery completion")


def _closed(value, keys):
    _require(type(value) is dict and set(value) == set(keys))


@dataclass(frozen=True)
class DiscoveryCompletionBinding:
    request: object
    recovery: dict
    candidate: dict
    source: dict
    sources: object
    baseline: object
    restoration: object = None

    @property
    def producer(self):
        return self.recovery.get("producer", "discovery")

    @property
    def repair_unit(self):
        return self.recovery.get("repair_unit")

    @property
    def clarification(self):
        return self.recovery["version"] in {5, 7, 18}

    @property
    def policy_resolution(self):
        return self.recovery["version"] in {21, 23, 25, 27}

    @property
    def resolution_publication(self):
        return self.clarification or self.policy_resolution or self.producer == "checkpoint"

    @property
    def spec_id(self):
        if self.producer in {"understanding", "lexicon_gate", "checkpoint"}:
            return self.recovery["spec_id"]
        return self.recovery["operation"]["binding"]["spec_id"]

    @property
    def operation_id(self):
        return "discovery-completion-" + self.recovery["completion_id"]

    @property
    def _restoration_applied(self):
        return self.restoration is not None and self.restoration.state in {"applied", "released"}

    @property
    def result_sources(self):
        return self.restoration.sources if self._restoration_applied else self.sources

    @property
    def result_baseline(self):
        if not self._restoration_applied:
            return self.baseline
        from harness.discovery_restoration_completion import _baseline
        return _baseline(self.restoration.sources, self.spec_id)

    @property
    def result_history(self):
        return self.restoration.history if self._restoration_applied else IdentityHistorySnapshot(**self.candidate["history"])

    @property
    def result_operation_id(self):
        return self.request.continuation_id if self._restoration_applied else self.operation_id


def decode_binding(publication, *, completion_id=None, state=None):
    """Closed optional envelope; ordinary external publications stay unchanged."""
    try:
        return _decode(publication, completion_id, state)
    except Exception:
        pass
    raise CompletionError("intent_mismatch")


def _decode(publication, completion_id, state):
    if "managed_discovery" not in publication:
        _require(state is None or not any(key in state for key in (
            "managed_identity", BOOTSTRAP_KEY, DISCOVERY_OPERATION_KEY, DISCOVERY_TURNS_KEY)))
        return None
    _closed(publication, ("kind", "marker", "managed_discovery"))
    _require(publication["kind"] == "external")
    envelope = publication["managed_discovery"]
    _closed(envelope, ("version", "request"))
    _require(type(envelope["version"]) is int and envelope["version"] == 1)
    raw = envelope["request"]
    _require(type(raw) is str and len(raw.encode("utf-8")) <= 4_194_304)
    request = decode_publication_request(raw)
    _require(encode_publication_request(request) == raw and request.sources is not None
        and request.proposed_history_sha256 is not None)
    # Storage children are never provider dispatches. Only a WHY2 root can
    # declare its deterministic child; authenticate also binds the native effect.
    _require(request.continuation is None)
    recovery = _document(request.recovery_payload)
    if request.continuation_id is not None:
        from harness.discovery_restoration_completion import continuation_id
        _require(recovery.get("version") in {15, 19, 24} and recovery.get("producer") == "why2"
            and request.continuation_id == continuation_id(recovery["completion_id"]))
    if recovery.get("version") == 14:
        from harness.discovery_understanding import decode_understanding_binding
        return decode_understanding_binding(publication, request, recovery, completion_id, state)
    if recovery.get("version") == 29:
        from harness.discovery_lexicon import decode_lexicon_gate_binding
        return decode_lexicon_gate_binding(publication, request, recovery, completion_id, state)
    if recovery.get("version") == 30:
        from harness.discovery_checkpoint_resolution import decode_binding as decode_checkpoint
        return decode_checkpoint(publication, request, recovery, completion_id, state)
    if recovery.get("version") in {21, 23, 25, 27}:
        from harness.discovery_policy_resolution import decode_policy_binding
        return decode_policy_binding(publication, request, recovery, completion_id, state)
    if recovery.get("version") in {5, 7, 18}:
        from harness.tracker_clarification import decode_clarification_binding
        return decode_clarification_binding(publication, request, recovery, completion_id, state)
    _closed(recovery, ("version", "completion_id", "operation", "candidate_sha256", "source_fingerprint",
        "candidate_inputs", "source_inputs", "review", "provider", "sources", "graph_sha256",
        *(("producer", "source_completion") if recovery.get("version") in {3, 4, 6, 8, 9, 10, 11, 12, 13, 15, 16, 17, 19, 20, 22, 24, 26, 28} else ()),
        *(("resolution",) if recovery.get("version") in {4, 6, 10, 11, 13, 15, 17, 19, 20, 22, 24, 26, 28} else ()),
        *(("predecessor",) if recovery.get("version") in {13, 15, 16, 17, 19, 20, 22, 24, 26, 28} else ()),
        *(("review_resolution", "review_parent") if recovery.get("version") in {20, 22, 26} else ()),
        *(("constitution_parent",) if recovery.get("version") == 17 else ()),
        *(("repair_unit",) if recovery.get("version") == 8 else ()),
        *(("refresh", "execution_input", "predecessor") if recovery.get("version") in {9, 10, 11} else ()),
        *(("tracker_parent",) if recovery.get("version") == 11 else ())))
    producer = recovery.get("producer", "discovery")
    repair_unit = recovery.get("repair_unit")
    _require(type(recovery["version"]) is int and recovery["version"] in {2, 3, 4, 6, 8, 9, 10, 11, 12, 13, 15, 16, 17, 19, 20, 22, 24, 26, 28}
        and (recovery["version"] != 3 or producer == "synthesizer")
        and (recovery["version"] != 4 or producer == "tracker")
        and (recovery["version"] != 6 or producer == "why1")
        and (recovery["version"] != 8 or producer == "discovery")
        and (recovery["version"] != 9 or producer == "synthesizer")
        and (recovery["version"] != 10 or producer == "tracker")
        and (recovery["version"] != 11 or producer == "why1")
        and ((recovery["version"] in {12, 16}) == (producer == "constitution"))
        and ((recovery["version"] in {13, 17, 20, 22, 26}) == (producer == "what"))
        and ((recovery["version"] in {15, 19, 24}) == (producer == "why2"))
        and ((recovery["version"] == 28) == (producer == "lexicon"))
        and _json(recovery) == request.recovery_payload)
    if completion_id is not None:
        _require(recovery["completion_id"] == completion_id)
    candidate = _document(recovery["candidate_inputs"])
    source = _document(recovery["source_inputs"])
    _closed(candidate, ("artifacts", "proposal", "reservations", "operations", "history",
        *(("routing",) if producer in {"tracker", "why1", "what", "why2", "lexicon"} else ())))
    if producer == "lexicon":
        from harness.discovery_lexicon import validate_lexicon_routing, validate_lexicon_artifacts
        validate_lexicon_routing(candidate["routing"])
        validate_lexicon_artifacts(candidate["artifacts"])
        _require(recovery["review"]["routing"] == candidate["routing"]
            and candidate["operations"] == [] and candidate["reservations"] == []
            and candidate["history"] == source["history"]
            and candidate["proposal"]["new_subjects"] == [] and candidate["proposal"]["revisions"] == [])
    if producer in {"what", "why2"}:
        from harness.discovery_spec import validate_spec_routing, validate_spec_artifacts
        validate_spec_routing(candidate["routing"], producer)
        validate_spec_artifacts(candidate["artifacts"], candidate["routing"], producer)
        _require(set(candidate["artifacts"]) == ({"spec.md", "requirements-overview.md"} if producer == "what"
                else {"quality-gates.md", "issues.md"})
            and recovery["review"]["routing"] == candidate["routing"])
    if producer in {"tracker", "why1"}:
        from harness.discovery_semantics import _tracker_routing
        _tracker_routing(candidate["routing"], producer)
        _require(recovery["review"]["routing"] == candidate["routing"])
    _closed(source, ("manifest", "history", "authority", "runtime", *(("quality_policy",) if producer == "why2" else ())))
    if producer == "why2":
        from harness.discovery_quality import validate_quality_policy
        validate_quality_policy(source["quality_policy"])
    _require(_json(candidate) == recovery["candidate_inputs"] and _hash(candidate) == recovery["candidate_sha256"]
        and _json(source) == recovery["source_inputs"] and _hash(source) == recovery["source_fingerprint"])
    operation = recovery["operation"]
    selected = operation["binding"]
    if producer in {"what", "why2", "lexicon"}:
        parent = recovery["source_completion"]
        _closed(parent, SOURCE_FIELDS)
        _require(all(type(value) is str and re.fullmatch(r"[0-9a-f]{%d}" % (32 if key == "dispatch_id" else 64), value)
            for key, value in parent.items()))
        _require(selected["operation_id"] == producer + "-" + parent["dispatch_id"]
            and selected["intent"]["kind"] == ("derive" if producer == "lexicon" else "specify" if producer == "what" else "validate")
            and ((producer == "lexicon") or ((recovery["resolution"] is not None) == (recovery["version"] in {19, 24})))
            and (recovery["predecessor"] is None or (type(recovery["predecessor"]) is str
                and re.fullmatch(producer + r"-[0-9a-f]{32}", recovery["predecessor"]) is not None)))
        if producer == "lexicon" and recovery["resolution"] is not None:
            from harness.discovery_spec import clarification_source
            from harness.discovery_policy_resolution import require_resolved
            association = recovery["resolution"]
            _closed(association, ("decision", "completion"))
            require_resolved(association["decision"], debt=True)
            _require(recovery["predecessor"] is None and association["decision"]["selected_option_id"] == "continue_with_debt"
                and parent == clarification_source(association["completion"])
                and association["completion"]["decision_id"] == association["decision"]["id"])
        if recovery["version"] == 17:
            _require(recovery["predecessor"] is not None and type(recovery["constitution_parent"]) is str
                and re.fullmatch(r"constitution-refresh-[0-9a-f]{32}", recovery["constitution_parent"]) is not None)
        if recovery["version"] in {19, 24}:
            from harness.discovery_spec import clarification_source
            from harness.tracker_clarification import _record
            _closed(recovery["resolution"], ("decision", "completion"))
            if recovery["version"] == 24:
                from harness.discovery_policy_resolution import require_reset_resolved
                require_reset_resolved(recovery["resolution"]["decision"])
            else:
                _record(recovery["resolution"]["decision"], "why2")
            _require(recovery["predecessor"] is not None
                and parent == clarification_source(recovery["resolution"]["completion"])
                and recovery["resolution"]["completion"]["decision_id"] == recovery["resolution"]["decision"]["id"])
        if recovery["version"] in {20, 22, 26}:
            from harness.discovery_spec import clarification_source
            from harness.tracker_clarification import _record
            association = recovery["review_resolution"]
            _closed(association, ("decision", "completion"))
            if recovery["version"] == 26:
                from harness.discovery_issue_resolution import require_resolved
                require_resolved(association["decision"])
            elif recovery["version"] == 22:
                from harness.discovery_policy_resolution import require_resolved
                require_resolved(association["decision"])
            else:
                _record(association["decision"], "why2")
            _require(recovery["predecessor"] is not None and parent == clarification_source(association["completion"])
                and association["completion"]["decision_id"] == association["decision"]["id"]
                and type(recovery["review_parent"]) is str and re.fullmatch(r"why2-[0-9a-f]{32}", recovery["review_parent"]) is not None)
    if producer == "constitution":
        parent = recovery["source_completion"]
        _closed(parent, SOURCE_FIELDS)
        _require(all(type(value) is str and re.fullmatch(r"[0-9a-f]{%d}" % (32 if key == "dispatch_id" else 64), value)
            for key, value in parent.items()))
        prefix = "constitution-refresh-" if recovery["version"] == 16 else "constitution-"
        _require(selected["operation_id"] == prefix + parent["dispatch_id"]
            and selected["intent"]["kind"] == "constitute"
            and selected["editable_revisions"] == []
            and candidate["operations"] == [] and candidate["reservations"] == []
            and candidate["history"] == source["history"]
            and candidate["proposal"]["new_subjects"] == [] and candidate["proposal"]["revisions"] == [])
        if recovery["version"] == 16:
            _require(type(recovery["predecessor"]) is str
                and re.fullmatch(r"constitution-(?:refresh-)?[0-9a-f]{32}", recovery["predecessor"]) is not None
                and recovery["predecessor"] != selected["operation_id"])
    if recovery["version"] == 3:
        _require(selected["operation_id"] == "synthesis-" + recovery["source_completion"]["dispatch_id"])
    if recovery["version"] in {4, 6} and recovery["resolution"] is None:
        _require(selected["operation_id"] == producer + "-" + recovery["source_completion"]["dispatch_id"])
    if recovery["version"] in {9, 10, 11}:
        refresh = recovery["refresh"]
        _closed(refresh, ("repair_unit", "repair_source", "predecessor_source"))
        _require(type(refresh["repair_unit"]) is str and re.fullmatch(r"[0-9a-f]{64}", refresh["repair_unit"]) is not None)
        for parent in (refresh["repair_source"], refresh["predecessor_source"]):
            _closed(parent, SOURCE_FIELDS)
            _require(all(type(value) is str and re.fullmatch(r"[0-9a-f]{%d}" % (32 if key == "dispatch_id" else 64), value)
                for key, value in parent.items()))
        validate_refresh_input(producer, refresh, recovery["execution_input"])
        _require(recovery["source_completion"] == recovery["execution_input"]["source"]
            and selected["operation_id"] == producer + "-" + refresh["repair_source"]["dispatch_id"]
            and type(recovery["predecessor"]) is str
            and re.fullmatch((r"(?:synthesis|synthesizer)" if producer == "synthesizer" else producer) + r"-[0-9a-f]{32}", recovery["predecessor"]) is not None
            and refresh["predecessor_source"]["dispatch_id"] != refresh["repair_source"]["dispatch_id"]
            and request.sources.expected_operation_id == "discovery-completion-" + recovery["source_completion"]["dispatch_id"])
        if producer in {"tracker", "why1"}:
            _require(recovery["resolution"] is None)
        if producer == "why1":
            _require(type(recovery["tracker_parent"]) is str
                and re.fullmatch(r"tracker-[0-9a-f]{32}", recovery["tracker_parent"]) is not None)
    if recovery["version"] == 8:
        _require(type(repair_unit) is str and re.fullmatch(r"[0-9a-f]{64}", repair_unit) is not None
            and selected["operation_id"] == "discovery-repair-" + repair_unit
            and selected["intent"]["kind"] == "repair"
            and selected["intent"]["origin"]["return_phase"] in {"phase1-why1", "phase1-why2"})
    _require(operation["attempts"][-1]["result"]["status"] == "accepted"
        and operation["attempts"][-1]["result"]["candidate_sha256"] == recovery["candidate_sha256"]
        and selected["fingerprint"] == recovery["source_fingerprint"])
    _require(candidate["operations"] == [asdict(op) for op in request.operations])
    for history in (source["history"], candidate["history"]):
        _closed(history, ("payload", "sha256"))
        _require(_json(strict_json(history["payload"])) == history["payload"]
            and hashlib.sha256(history["payload"].encode("ascii")).hexdigest() == history["sha256"])
    _require(candidate["history"]["sha256"] == request.proposed_history_sha256)
    sources = decode_initial_publication_sources(recovery["sources"])
    baseline = decode_initial_publication_sources(request.sources.baseline_payload)
    _require(sources.publication == baseline.publication and sources.publication.marker.to_dict() == publication["marker"]
        and request.manifest_sha256 == sources.publication.marker.manifest_sha256)
    manifest = snapshot_source_manifest(trees=sources.trees, files=sources.files)
    _require(asdict(manifest) == source["manifest"])
    authority = source["authority"]
    genesis = authority["managed_identity"]
    spec_path = genesis["spec_path"]
    spec, = (tree for tree in sources.trees if tree.path == spec_path)
    if producer != "discovery" or repair_unit is not None:
        spec = identity_spec_tree(spec)
    _require(baseline.trees == (spec,) and baseline.files == ()
        and request.sources.context_id == genesis["context_id"] == authority["source_context"]["context_id"]
        and request.sources.expected_operation_id == authority["source_context"]["operation_id"]
        and asdict(snapshot_source_manifest(trees=(spec,), files=())) == authority["source_context"]["manifest"])
    _require(type(candidate["artifacts"]) is dict and set(candidate["artifacts"]) == set(selected["artifact_paths"]))
    omitted = {name for name, text in candidate["artifacts"].items() if text is None}
    from harness.discovery_semantics import optional_artifacts
    _require(omitted <= optional_artifacts(producer)
        and all(item.path not in {spec_path + "/" + name for name in omitted} for item in spec.files))
    from harness.discovery_constitution import CONSTITUTION_PATH, publication_target, validate_constitution_candidate
    if producer == "constitution":
        _require(set(candidate["artifacts"]) == {"constitution.md"})
        shared, = (item for item in sources.files if item.path == CONSTITUTION_PATH)
        validate_constitution_candidate(candidate["artifacts"]["constitution.md"],
            None if shared.content is None else shared.content.decode("utf-8"))
    writes = {publication_target(producer, spec_path, name): text.encode("utf-8") for name, text in candidate["artifacts"].items() if text is not None}
    graph = _graph(sources, IdentityHistorySnapshot(**candidate["history"]), dict(spec_id=selected["spec_id"], spec_path=spec_path))
    _require(hashlib.sha256(graph).hexdigest() == recovery["graph_sha256"])
    writes[spec_path + "/spec-artifact-graph.json"] = graph
    modes = {item.path: item.image.mode for item in (*spec.files, *sources.files) if item.content is not None}
    operations = sources.publication.operations
    _require(len(operations) == len(writes) and {op.target for op in operations} == set(writes)
        and sources.publication.promoted_prefix == 0)
    _require(all(op.action == "write" and op.postimage_bytes == writes[op.target]
        and op.postimage.mode == modes.get(op.target, 0o644) for op in operations))
    if state is not None:
        bootstrap = bootstrap_from_state(state)
        op_id = selected["operation_id"] if producer != "discovery" else None
        _require(bootstrap is not None and operation_from_state(state, producer, operation_id=op_id, repair_unit=repair_unit) == operation
            and state.get("managed_identity") == genesis
            and producer_component(state, producer, "turns", operation_id=op_id, repair_unit=repair_unit) == recovery["provider"])
        _require(all(bootstrap["selection"][key] == selected[key]
            for key in (("spec_id", "run_id", "operation_id") if producer == "discovery" and repair_unit is None else ("spec_id", "run_id"))))
        if repair_unit is not None:
            from harness.discovery_producer import repair_record
            _require(repair_record(state, producer, repair_unit)["selection"]["source"] == recovery["source_completion"])
        if producer == "synthesizer":
            _require(synthesis_input_source(state, selected["operation_id"]) == recovery["source_completion"])
            if recovery["version"] == 9:
                row = tracker_round(state, selected["operation_id"], producer=producer)
                _require(all(row[key] == recovery[key] for key in ("refresh", "execution_input", "predecessor")))
        if producer == "constitution":
            from harness.discovery_constitution import constitution_input_source
            _require(constitution_input_source(state, selected["operation_id"]) == recovery["source_completion"])
            if recovery["version"] == 16:
                row = tracker_round(state, selected["operation_id"], producer=producer)
                _require(row["predecessor"] == recovery["predecessor"])
        if producer in {"what", "why2", "lexicon"}:
            row = tracker_round(state, selected["operation_id"], producer=producer)
            _require(row["source"] == recovery["source_completion"]
                and row["resolution"] == recovery["resolution"] and row["predecessor"] == recovery["predecessor"])
            _require(("constitution_parent" in row) == (recovery["version"] == 17))
            _require(("review_resolution" in row) == (recovery["version"] in {20, 22, 26}))
            if recovery["version"] in {20, 22, 26}:
                _require(row["review_resolution"] == recovery["review_resolution"] and row["review_parent"] == recovery["review_parent"])
            if recovery["version"] == 17:
                _require(row["constitution_parent"] == recovery["constitution_parent"])
        if producer in {"tracker", "why1"}:
            row = tracker_round(state, selected["operation_id"], producer=producer)
            _require(tracker_input_source(state, selected["operation_id"], producer=producer) == recovery["source_completion"]
                and row["resolution"] == recovery["resolution"])
            _require(("refresh" in row) == (recovery["version"] in {10, 11}))
            if recovery["version"] in {10, 11}:
                _require(all(row[key] == recovery[key] for key in ("refresh", "execution_input", "predecessor")))
            if recovery["version"] == 11:
                _require(row["tracker_parent"] == recovery["tracker_parent"])
    return DiscoveryCompletionBinding(request, recovery, candidate, source, sources, baseline)


def require_tracker_skip(state, intent):
    row = tracker_round(state)
    route = intent["route"]
    _require(row is not None and row["resolution"] is None and state.get("mode") == "greenfield"
        and intent["origin"] == "routed" and route["from_phase"] == "phase1-modeler"
        and route["to_phase"] == "phase1-tracker" and route["record_completion"] is True
        and route["manual_phase_run"] is False and not intent["effect_plan"]
        and intent["publication"] == {"kind": "none"}
        and (state.get("last_dispatch") or {}).get("conditional_skip") is True)
    return row


def authenticate(root, run, state, completion):
    """Authenticate the saved completion association without live-source replay."""
    try:
        if completion.intent.publication == {"kind": "none"} and "managed_identity" in state:
            row = require_tracker_skip(state, completion.intent.to_dict())
            released_discovery_input_projectors(root, run, state, source=row["source"])
            return None
        binding = decode_binding(completion.intent.publication, completion_id=completion.marker.completion_id, state=state)
        if binding is None:
            return None
        route = completion.intent.route
        _require("product_input_mutation" not in state)
        if binding.resolution_publication:
            _require(completion.intent.origin == "resolution" and route["from_phase"] == (
                binding.recovery["from_phase"] if binding.policy_resolution else producer_phase(binding.producer))
                and route["decision_id"] == binding.recovery["resolution"]["id"]
                and completion.intent.effect_plan == (("quality", "context") if binding.recovery["version"] == 27 else ("context",)))
            if binding.recovery["version"] == 27:
                from harness.discovery_debt_resolution import require_effect
                require_effect(binding, completion.intent)
        else:
            _require(completion.intent.origin == "routed" and route["from_phase"] == producer_phase(binding.producer)
                and route["manual_phase_run"] is False and route["record_completion"] is True
                and set(completion.intent.effect_plan) <= {"journal", "timing", "checkpoint", "context",
                    *(("quality",) if binding.producer == "why2" else ())})
        if binding.producer == "why2" and not binding.clarification:
            from harness.discovery_quality import validate_why2_quality_effect
            validate_why2_quality_effect(binding, completion.intent.quality_effect, root=root, run=run,
                checkpoint_prestate=completion.intent.checkpoint_prestate, state=state)
        selection = bootstrap_from_state(state)["selection"]
        _require(str(root) == selection["project_root"] and str(run) == selection["run_dir"])
        input_view = binding.sources
        if binding.producer != "discovery" or binding.repair_unit is not None:
            spec_view, runtime_view = _released_discovery_projections(root, run, state,
                source=binding.recovery["source_completion"], historical=True,
                repair_child=binding if binding.repair_unit is not None else None,
                refresh_child=binding if binding.recovery["version"] in {9, 10, 11} else None,
                why1_child=binding if binding.producer == "why1" else None,
                constitution_child=binding if binding.producer == "constitution" else None,
                spec_child=binding if binding.producer in {"what", "why2", "lexicon", "lexicon_gate"} and not binding.clarification else None,
                clarification_child=binding if binding.clarification else None)
            spec_tree, = (tree for tree in binding.sources.trees if tree.path == selection["spec_path"])
            _require(spec_view(spec_tree) == binding.baseline.trees[0])
            input_view = runtime_view(binding.sources)
        runtime, _ = admit_runtime_inputs(root, run, state, input_view)
        _require(runtime == binding.source["runtime"])
        store = IdentityStore.open(root)
        if binding.producer == "understanding":
            from harness.discovery_understanding import authenticate_understanding
            authenticate_understanding(root, run, state, completion, binding)
        if binding.producer == "lexicon_gate":
            from harness.discovery_lexicon import authenticate_lexicon_gate
            authenticate_lexicon_gate(root, run, state, completion, binding)
        if binding.clarification:
            from harness.tracker_clarification import require_parent
            require_parent(state, binding, store)
        if binding.policy_resolution:
            from harness.discovery_policy_resolution import require_parent
            require_parent(root, run, state, binding, store)
        if binding.producer == "checkpoint":
            from harness.discovery_checkpoint_resolution import require_parent
            require_parent(root, run, state, binding)
        observed = store.check_managed_context(spec_id=binding.spec_id, run_id=state["run_id"], record=state["managed_identity"])
        pending = store.pending_identity_publication(spec_id=binding.spec_id)
        retained = store.identity_publication(spec_id=binding.spec_id, operation_id=binding.operation_id)
        _require(pending is None or pending == retained)
        if retained is not None:
            _require(retained["request"] == encode_publication_request(binding.request))
        applied = retained is not None and retained["state"] in {"applied", "released"}
        if applied and binding.request.continuation_id is not None:
            from harness.discovery_restoration_completion import authenticated_continuation
            binding = replace(binding, restoration=authenticated_continuation(root, run, state,
                binding=binding, completion=completion, parent=retained))
        expected = project_publication_source_images(binding.result_baseline).manifest if applied else snapshot_source_manifest(
            trees=binding.baseline.trees, files=binding.baseline.files)
        _require(observed["source_context"]["manifest"] == asdict(expected)
            and observed["source_context"]["operation_id"] == (binding.result_operation_id if applied else binding.request.sources.expected_operation_id)
            and asdict(store.identity_history(spec_id=binding.spec_id)) == (asdict(binding.result_history) if applied else binding.source["history"]))
        if binding.producer not in {"understanding", "lexicon_gate", "checkpoint"}:
            _receipts(root, run, state, binding, store)
        return binding
    except Exception:
        pass
    raise CompletionError("intent_mismatch")


def require_unpublished_orphan(root, run, state, intent):
    """Authorize disposal, never promotion, of a sealed but never-routed draft."""
    try:
        binding = decode_binding(intent["publication"], completion_id=intent["completion_id"], state=state)
        _require(binding is not None and state.get("phase") == (
            binding.recovery["from_phase"] if binding.policy_resolution else producer_phase(binding.producer))
            and not any(key in state for key in ("pending_controller_completion", "pending_external_publication")))
        dispatch = state.get("last_dispatch") or {}
        _require(dispatch.get("dispatch_id") != intent["completion_id"]
            and dispatch.get("post_dispatch_complete") is not False)
        selection = bootstrap_from_state(state)["selection"]
        _require(str(root) == selection["project_root"] and str(run) == selection["run_dir"])
        store = IdentityStore.open(root)
        store.check_managed_context(spec_id=binding.spec_id, run_id=selection["run_id"], record=state["managed_identity"])
        _require(store.identity_publication(spec_id=binding.spec_id, operation_id=binding.operation_id) is None
            and store.pending_identity_publication(spec_id=binding.spec_id) is None)
        try:
            publication = load_prepared_publication(root, run, intent["publication"]["marker"])
        except PublicationError as error:
            if error.code != "stage_missing":
                raise
            # Disposal can stop between the external stage and completion
            # stage. Prove the exact original sources still exist using the
            # retained empty inspection transaction; missing is not release.
            capture = load_prepared_publication(root, run, selection["capture_marker"])
            with capture.inspect_sources(tree_paths=tuple(tree.path for tree in binding.sources.trees),
                    file_paths=tuple(item.path for item in binding.sources.files)) as observed:
                _require(not observed.publication.operations and snapshot_source_manifest(
                    trees=observed.trees, files=observed.files) == snapshot_source_manifest(
                    trees=binding.sources.trees, files=binding.sources.files))
        else:
            with publication.inspect() as images:
                _require(images.promoted_prefix == 0 and all(item.current == item.preimage for item in images.operations))
        return
    except Exception:
        pass
    raise CompletionError("intent_mismatch")


def _read_receipt(run, name, producer="discovery", *, operation_id=None, repair_unit=None):
    with DiscoveryReceiptFile(run, name, producer=producer, round_operation_id=operation_id, repair_unit=repair_unit) as file:
        raw = file._read()
        value = json.loads(raw, object_pairs_hook=_unique_object)
        _closed(value, ("payload", "sha256"))
        _require(_hash(value["payload"]) == value["sha256"])
        _require(file._read() == raw)
    return value["payload"]


def _receipts(root, run, state, binding, store):
    if binding.resolution_publication:
        # Human decision membership is checked by the closed binding decoder;
        # the parent Tracker's retained proof is checked by ancestry traversal.
        return
    from harness.discovery_turns import _validate
    from harness.discovery_reservations import _validate as validate_reservations
    selected_id = binding.recovery["operation"]["binding"]["operation_id"]
    operation_id = selected_id if binding.producer != "discovery" else None
    round_id = receipt_round_operation_id(binding.producer, selected_id)
    turns = _read_receipt(run, "discovery-turns", binding.producer, operation_id=round_id, repair_unit=binding.repair_unit)
    _validate(turns)
    _require(_hash(turns["binding"]) == producer_component(state, binding.producer, "turns", operation_id=operation_id, repair_unit=binding.repair_unit)["binding_sha256"]
        and turns["binding"]["authority"] == binding.source["authority"])
    from harness.prosaic_prompt_loader import ProsaicPromptLoader
    loader = ProsaicPromptLoader(root, timeout_s=10)
    _require({name: asdict(loader.load_subagent(producer_role(binding.producer, name)))
        for name in ("producer", "reviewer")} == turns["binding"]["roles"])
    number = len(binding.recovery["operation"]["attempts"])
    replies = {}
    for step in turns["steps"]:
        if step["assignment"]["dispatch_id"].startswith(f"attempt-{number}-"):
            _require(step["records"] and step["records"][-1]["accepted"] is True)
            replies[step["assignment"]["step"]] = step["records"][-1]["reply"]
    _require(replies["propose"] == binding.candidate["proposal"]
        and replies["author"]["artifacts"] == binding.candidate["artifacts"]
        and replies["review"] == binding.recovery["review"] and replies["review"]["verdict"] == "accept")
    if binding.producer in {"tracker", "why1", "what", "why2", "lexicon"}:
        _require(replies["author"]["routing"] == binding.candidate["routing"] == replies["review"]["routing"])
    reservations = _read_receipt(run, "discovery-reservations", binding.producer, operation_id=round_id, repair_unit=binding.repair_unit)
    _require(reservations["binding"]["context"] == binding.source["authority"])
    known = validate_reservations(reservations, reservations["binding"], binding.producer)
    _require([asdict(known[item["key"]][1]) for item in replies["propose"]["new_subjects"]] == binding.candidate["reservations"])
    for proposal in reservations["proposals"]:
        for intent in proposal["intents"]:
            _require(intent["ids"] is not None and tuple(intent["ids"]) == store.reservation(
                spec_id=binding.spec_id, kind=intent["kind"], operation_id=intent["operation_id"], count=len(intent["keys"])))


def publish(root, run, state, completion, publication):
    binding = authenticate(root, run, state, completion)
    _require(binding is not None)
    store = IdentityStore.open(root)
    publication.publish_sources(binding.sources,
        before_publish=lambda _: store.prepare_identity_publication(spec_id=binding.spec_id,
            operation_id=binding.operation_id, request=binding.request),
        after_publish=lambda _: store.apply_identity_publication(spec_id=binding.spec_id, operation_id=binding.operation_id))


def require_applied(root, run, state, completion):
    try:
        return _require_applied(root, run, state, completion)
    except Exception:
        pass
    raise CompletionError("intent_mismatch")


def _require_applied(root, run, state, completion):
    binding = authenticate(root, run, state, completion)
    if binding is None:
        return None
    store = IdentityStore.open(root)
    retained = store.identity_publication(spec_id=binding.spec_id, operation_id=binding.operation_id)
    _require(retained is not None and retained["state"] in {"applied", "released"})
    if binding.restoration is not None:
        from harness.discovery_restoration_completion import _inspect_continuation, pending_tree_projector
        checkpoint = _checkpoint_projection(root, run, state, intent=completion.intent,
            marker=completion.marker, receipts=completion.receipts, binding=binding)
        project = pending_tree_projector(root, run, completion, sources=binding.sources, checkpoint=checkpoint)
        _inspect_continuation(root, run, binding.restoration, project_tree=project)
        return binding
    publication = load_prepared_publication(root, run, binding.sources.publication.marker)
    projected = project_publication_source_images(binding.sources)
    checkpoint = _checkpoint_projection(root, run, state, intent=completion.intent,
        marker=completion.marker, receipts=completion.receipts, binding=binding)
    # Context and exact checkpoint metadata have existing completion owners.
    # All other captured sources remain pinned through effects and release.
    context = (run / "context").relative_to(root).as_posix()
    trees = tuple(tree for tree in projected.trees if tree.path != context)
    if binding.producer != "discovery" or binding.repair_unit is not None:
        trees = tuple(identity_spec_tree(tree) if tree.path == binding.baseline.trees[0].path else tree for tree in trees)
    expected = snapshot_source_manifest(trees=trees, files=projected.files)
    with publication.inspect_sources(tree_paths=tuple(tree.path for tree in projected.trees),
            file_paths=tuple(item.path for item in projected.files)) as current:
        _require(snapshot_source_manifest(trees=tuple(checkpoint(tree) for tree in current.trees if tree.path != context),
            files=current.files) == expected)
        original_context, = (tree for tree in projected.trees if tree.path == context)
        current_context, = (tree for tree in current.trees if tree.path == context)
        _context(completion, original_context, current_context)
    return binding


def _checkpoint_projection(root, run, state, *, intent, marker, receipts, binding, restore_checkpoint_receipt=None):
    """Resolve Git proof before the source lock; projection checks captured bytes."""
    from harness.phase_checkpoints import fresh_completion_checkpoint_ledger_image
    plan = intent.effect_plan
    selection = bootstrap_from_state(state)["selection"]
    spec = selection["spec_path"]
    original, = (tree for tree in binding.sources.trees if tree.path == spec)
    metadata = spec + "/.echelon"
    prior_ledger = None
    if binding.producer != "discovery" or binding.repair_unit is not None:
        matches = [item.content for item in original.files if item.path == metadata + "/checkpoints.json"]
        prior_ledger = matches[0] if matches else None
    else:
        _require(not any(item.path == metadata or item.path.startswith(metadata + "/")
            for item in (*original.directories, *original.files)))
    prior_projection = partial(_project_checkpoint_tree, spec=spec, ledger=prior_ledger, pending=False) if prior_ledger is not None else lambda tree: tree
    if "checkpoint" not in plan:
        return prior_projection
    target = Path(str(state.get("spec_dir") or ""))
    if not target.is_absolute():
        target = root / target
    _require(target == root / spec)
    step = marker.step
    if step in plan and plan.index(step) < plan.index("checkpoint"):
        return prior_projection
    _require(step == "complete" or step in plan)
    pending = step == "checkpoint" and "checkpoint" not in receipts["effects"]
    route = intent.route
    artifacts, = project_publication_source_images(binding.baseline).trees
    images = {item.path: (item.image.mode, item.content) for item in artifacts.files}
    additional = {}
    if binding.producer == "constitution":
        from harness.discovery_constitution import CONSTITUTION_PATH
        shared, = (item for item in project_publication_source_images(binding.sources).files if item.path == CONSTITUTION_PATH)
        additional[shared.path] = (shared.image.mode, shared.content)
    ledger = fresh_completion_checkpoint_ledger_image(project_root=root, spec_dir=root / spec,
        phase=route["from_phase"], next_phase=route["to_phase"], run_id=selection["run_id"],
        spec_id=selection["spec_id"], completion_id=marker.completion_id,
        checkpoint_prestate=intent.checkpoint_prestate,
        expected_receipt=receipts["effects"].get("checkpoint"),
        allow_pending=pending, rewind=str(route.get("rewind_policy") or "supported"),
        artifact_images=images, ledger_preimage=prior_ledger, additional_file_images=additional)
    if binding.producer == "why2" and "quality" in plan and (step == "complete" or plan.index(step) >= plan.index("quality")):
        from harness.discovery_quality import validate_why2_quality_effect
        from harness.proportional_quality_effects import (
            _quality_completion_id, _routed_quality_checkpoint_context, _preflight_quality_effect_receipt,
        )
        from harness.proportional_quality import load_quality_candidate_snapshot, quality_candidate_effect_payload
        draft = validate_why2_quality_effect(binding, intent.quality_effect, root=root, run=run,
            checkpoint_prestate=intent.checkpoint_prestate)
        quality_receipt = _preflight_quality_effect_receipt(intent.quality_effect, "candidate", receipts["effects"].get("quality"))
        candidate_receipt = quality_receipt["candidate"] if quality_receipt is not None else None
        next_phase, prestate = _routed_quality_checkpoint_context(route=route, completion_id=marker.completion_id,
            sealed_prestate=intent.quality_effect["checkpoint_prestate"],
            preceding_checkpoint_receipt=receipts["effects"].get("checkpoint"))
        pending = step == "quality" and quality_receipt is None
        prior_ledger = ledger
        ledger = fresh_completion_checkpoint_ledger_image(project_root=root, spec_dir=root / spec,
            phase="phase1-" + draft.candidate_id, next_phase=next_phase, run_id=selection["run_id"],
            spec_id=selection["spec_id"], completion_id=_quality_completion_id(marker.completion_id, "candidate"),
            checkpoint_prestate=prestate, expected_receipt=candidate_receipt["checkpoint"] if candidate_receipt else None,
            allow_pending=pending, artifact_images=images, ledger_preimage=prior_ledger)
        if candidate_receipt is not None:
            candidate = load_quality_candidate_snapshot(run / "quality-candidates" / (draft.candidate_id + ".json"),
                expected_sha256=candidate_receipt["manifest_sha256"], expected_candidate_id=draft.candidate_id)
            _require(candidate.manifest.checkpoint_commit == candidate_receipt["checkpoint"]["commit"]
                and quality_candidate_effect_payload(replace(candidate.manifest, checkpoint_commit="0" * 40))
                    == intent.quality_effect["candidate"])
        if binding.restoration is not None:
            from harness.discovery_restoration_completion import _restore_checkpoint_projector
            restored = quality_receipt["restore"]["checkpoint"] if quality_receipt is not None else restore_checkpoint_receipt
            return _restore_checkpoint_projector(root, binding.restoration, ledger_preimage=ledger,
                checkpoint_receipt=restored, pending=pending and restored is None and not binding._restoration_applied)
    return partial(_project_checkpoint_tree, spec=spec, ledger=ledger, pending=pending, preimage=prior_ledger)


def _project_checkpoint_tree(tree, *, spec, ledger, pending, preimage=None):
    if tree.path != spec:
        return tree
    metadata = spec + "/.echelon"
    directories = tuple(item for item in tree.directories
        if item.path == metadata or item.path.startswith(metadata + "/"))
    files = tuple(item for item in tree.files if item.path.startswith(metadata + "/"))
    _require(len(directories) <= 1 and all(item.path == metadata and item.mode == 0o700 for item in directories))
    names = {item.path: item for item in files}
    _require(set(names) <= {metadata + "/checkpoints.lock", metadata + "/checkpoints.json"})
    if ledger is not None:
        # The commit follows creation of the directory and lock. Only the
        # ledger write may still be pending once that commit exists.
        _require(len(directories) == 1 and metadata + "/checkpoints.lock" in names)
    if preimage is not None:
        # An append may replace a retained ledger, never recreate a lost one.
        _require(metadata + "/checkpoints.json" in names)
    if not pending:
        _require(len(directories) == 1 and len(names) == 2 and ledger is not None)
    for path, item in names.items():
        expected = b"" if path.endswith("/checkpoints.lock") else ledger
        _require(item.image.mode == 0o600 and expected is not None and (item.content == expected
            or (pending and path.endswith("/checkpoints.json") and preimage is not None and item.content == preimage)))
    return replace(tree, directories=tuple(item for item in tree.directories if item not in directories),
        files=tuple(item for item in tree.files if item not in files))


def _context(completion, original, current):
    """Bind the existing context receipt's preimages to the reviewed capture."""
    from harness.squad_completion import _read_context_stage, _validate_completion_context_receipt
    receipt = completion.receipts["effects"].get("context")
    if receipt is None:
        _require(current == original)
        return
    receipt = _validate_completion_context_receipt(receipt, prepared=completion,
        staged=_read_context_stage(completion))
    _require(current.exists == original.exists and current.directories == original.directories
        and tuple(item.path for item in current.files) == tuple(item.path for item in original.files))
    by_name = {item["name"]: item for item in receipt["files"]}
    for before, actual in zip(original.files, current.files, strict=True):
        item = by_name[Path(before.path).name]
        _require(item["preimage"] == dict(kind="file", sha256=before.image.sha256, size_bytes=len(before.content)))
        postimage = actual.image.sha256 == item["sha256"] and len(actual.content) == item["size_bytes"]
        _require(postimage or (completion.marker.step == "context" and actual == before))
        _require(actual.image.mode == (before.image.mode if actual.content == before.content else 0o600))


def context_generator(root, run, state, completion):
    """Supply captured postimages to the existing completion context owner."""
    from echelon.context_builder import build_run_context
    binding = require_applied(root, run, state, completion)
    _require(binding is not None)
    spec = binding.source["authority"]["managed_identity"]["spec_path"]
    if binding.resolution_publication or binding.producer in {"understanding", "lexicon_gate"} or binding._restoration_applied:
        projected = project_publication_source_images(binding.result_sources)
        artifacts = {item.path: item.content for tree in projected.trees for item in tree.files
            if tree.path == spec and item.path.endswith(".md")}
        artifacts.update({item.path: item.content for item in projected.files
            if item.path in binding.candidate["artifacts"] and item.path.endswith(".md")})
        return partial(build_run_context, captured_discovery_artifacts=artifacts)
    from harness.discovery_constitution import publication_target
    selected = {publication_target(binding.producer, spec, name) for name in binding.recovery["operation"]["binding"]["artifact_paths"]
        if binding.candidate["artifacts"][name] is not None}
    projected = project_publication_source_images(binding.sources)
    artifacts = {item.path: item.content for tree in projected.trees for item in tree.files if item.path in selected}
    artifacts.update({item.path: item.content for item in projected.files if item.path in selected})
    _require(set(artifacts) == selected)
    return partial(build_run_context, captured_discovery_artifacts=artifacts)


def release(root, run, state_store, completion):
    try:
        return _release(root, run, state_store, completion)
    except Exception:
        pass
    raise CompletionError("intent_mismatch")


def _release(root, run, state_store, completion):
    state = state_store.confirm_durable_state(state_store.load())
    binding = authenticate(root, run, state, completion)
    _require(binding is not None)
    dispatch, marker = state.get("last_dispatch", {}), completion.marker
    if binding.resolution_publication:
        receipt = state.get("last_human_input_completion", {})
        _require(receipt.get("decision_id") == binding.recovery["resolution"]["id"])
        dispatch = dict(post_dispatch_complete=True, dispatch_id=receipt.get("completion_id"),
            completion_intent_sha256=receipt.get("intent_sha256"), completion_receipts_sha256=receipt.get("receipts_sha256"),
            completed_publication_binding_sha256=receipt.get("publication_binding_sha256"))
    _require("pending_controller_completion" not in state and "pending_external_publication" not in state
        and marker.step == "complete" and dispatch.get("post_dispatch_complete") is True
        and dispatch.get("dispatch_id") == marker.completion_id
        and dispatch.get("completion_intent_sha256") == marker.intent_sha256
        and dispatch.get("completion_receipts_sha256") == marker.receipts_sha256
        and dispatch.get("completed_publication_binding_sha256") == marker.publication_binding_sha256)
    store = IdentityStore.open(root)
    retained = store.identity_publication(spec_id=binding.spec_id, operation_id=binding.operation_id)
    _require(retained is not None)
    # A release is immutable, including when cleanup resumes under newer code.
    # Its old encoding is replayed exactly; it is never upgraded in storage.
    version = _document(retained["completion_payload"])["version"] if retained["state"] == "released" else 3
    payload = _release_payload(completion, version)
    if retained["state"] == "released":
        _require(retained["completion_payload"] == payload)
    else:
        require_applied(root, run, state, completion)
        store.release_identity_publication(spec_id=binding.spec_id,
            operation_id=binding.operation_id, completion_payload=payload)
    stages = [binding.sources.publication.marker]
    if binding.restoration is not None:
        stages.append(binding.restoration.graph_sources.publication.marker)
    for stage in stages:
        try:
            publication = load_prepared_publication(root, run, stage)
        except PublicationError as error:
            if error.code != "stage_missing":
                raise
        else:
            publication.discard()


def _release_payload(completion, version):
    from harness.squad_completion import validate_retained_completion_proof
    _require(type(version) is int and version in {1, 2, 3})
    result = dict(version=version, completion=completion.marker.to_dict())
    if version != 1:
        _require(version == 3 or "checkpoint" in completion.intent.effect_plan)
        proof = dict(intent=completion.intent.to_dict(), receipts=completion.receipts)
        validate_retained_completion_proof(result["completion"], proof["intent"], proof["receipts"])
        result["checkpoint" if version == 2 else "proof"] = proof
    return _json(result)


def released_checkpoint_projector(root, run, state):
    """Compatibility reader for releases that actually performed a checkpoint."""
    return released_discovery_projector(root, run, state, require_checkpoint=True)


def released_discovery_projector(root, run, state, *, require_checkpoint=False):
    return _released_discovery_projections(root, run, state, require_checkpoint=require_checkpoint)[0]


def released_discovery_input_projectors(root, run, state, *, source):
    """Bind a repair's source claim to retained spec and context proof.

    Returned projections are pure captured-image checks. They do not grant
    requesting-review provenance or repair execution authority.
    """
    return _released_discovery_projections(root, run, state, source=source)


def _require_repair_origin(state, child, parent):
    """A stored association is not review authority, including during recovery."""
    from harness.discovery_producer import repair_record
    from harness.discovery_repair_admission import repair_findings
    claim = repair_record(state, "discovery", child.repair_unit)["selection"]
    _require(parent.producer in {"why1", "why2"} and not parent.clarification
        and parent.candidate["routing"]["verdict"] == "FAIL" and parent.recovery["review"]["verdict"] == "accept"
        and claim["origin"] == dict(review_id=parent.recovery["completion_id"], return_phase="phase1-" + parent.producer))
    if parent.producer == "why2":
        _require(child.source["runtime"] == parent.source["runtime"])
    def artifacts(binding):
        tree, = binding.baseline.trees
        return {item.path[len(tree.path) + 1:]: item.content.decode("utf-8") for item in tree.files}
    findings, paths, revisions = repair_findings(artifacts(child), IdentityHistorySnapshot(**child.source["history"]),
        artifacts(parent), IdentityHistorySnapshot(**parent.source["history"]), review_producer=parent.producer)
    _require(claim["findings"] == findings and claim["artifact_paths"] == paths and claim["editable_revisions"] == revisions)


def _require_refresh_dependencies(row, previous, source, sources, inputs, selection, run, root, *, producer="synthesizer"):
    from harness.discovery_refresh_inputs import refresh_dependency_comparison
    _require(source == row["refresh"]["predecessor_source"]
        and previous.producer == producer and not previous.clarification
        and previous.recovery["operation"]["binding"]["operation_id"] == row["predecessor"])
    comparison = refresh_dependency_comparison(previous, sources,
        history=IdentityHistorySnapshot(**inputs["history"]), runtime=inputs["runtime"],
        spec_path=selection["spec_path"], run_path=run.relative_to(root).as_posix())
    _require(comparison == row["execution_input"]["dependencies"])


def _refresh_predecessor(root, run, state, row, *, producer="synthesizer"):
    """Resolve the nearest accepted producer in the authenticated repair ancestry.

    The capture caller first authenticates the full current chain. Resolve before
    entering source inspection: retained checkpoint proof may access Git.
    """
    store = IdentityStore.open(root)
    source = row["refresh"]["repair_source"]
    from harness.discovery_producer import repair_return_phase
    binding, _, _ = _retained_input_projection(root, run, state, store,
        operation_id="discovery-completion-" + source["dispatch_id"], source=source,
        require_checkpoint=False, required_route=("phase1-discover", repair_return_phase(state, row["refresh"]["repair_unit"])))
    _require(binding.producer == "discovery" and binding.repair_unit == row["refresh"]["repair_unit"])
    seen = {source["dispatch_id"]}
    while binding.producer != producer or binding.clarification:
        source = binding.recovery["source_completion"]
        _require(source["dispatch_id"] not in seen)
        seen.add(source["dispatch_id"])
        binding, _, _ = _retained_input_projection(root, run, state, store,
            operation_id="discovery-completion-" + source["dispatch_id"], source=source, require_checkpoint=False)
    _require(source == row["refresh"]["predecessor_source"]
        and binding.recovery["operation"]["binding"]["operation_id"] == row["predecessor"])
    return binding


def _require_why1_tracker_parent(state, child, parent):
    if child is None or child.producer != "why1" or child.clarification:
        return
    row = tracker_round(state, child.recovery["operation"]["binding"]["operation_id"], producer="why1")
    if "tracker_parent" in row:
        _require(parent.producer == "tracker" and not parent.clarification
            and parent.recovery["operation"]["binding"]["operation_id"] == row["tracker_parent"])


def _require_refresh_parent(child, parent, source):
    refresh = child.recovery["refresh"]
    _require(source == child.recovery["execution_input"]["source"])
    if child.recovery["version"] == 9:
        _require(parent.producer == "discovery" and parent.repair_unit == refresh["repair_unit"]
            and source == refresh["repair_source"])
    elif child.recovery["version"] == 11:
        _require(parent.producer == "tracker" and not parent.clarification
            and parent.recovery["operation"]["binding"]["operation_id"] == child.recovery["tracker_parent"])
    else:
        _require(child.recovery["version"] == 10 and parent.producer == "synthesizer"
            and parent.recovery["version"] == 9
            and all(parent.recovery["refresh"][key] == refresh[key] for key in ("repair_unit", "repair_source")))


def _released_discovery_projections(root, run, state, *, require_checkpoint=False, source=None, historical=False, repair_child=None, refresh_child=None, why1_child=None, constitution_child=None, spec_child=None, clarification_child=None):
    """Prepare a checked spec-identity view after completion outbox cleanup.

    Caller owns execution leases, then captures the complete tree under the
    existing source inspector and calls the returned pure projection there.
    Keep that full capture for read guards; only the authenticated identity view
    omits checkpoint metadata. This does not admit other repair input domains.
    """
    try:
        selection = bootstrap_from_state(state)["selection"]
        _require(str(root) == selection["project_root"] and str(run) == selection["run_dir"])
        store = IdentityStore.open(root)
        observed = store.check_managed_context(spec_id=selection["spec_id"], run_id=selection["run_id"],
            record=state["managed_identity"])
        operation_id = "discovery-completion-" + source["dispatch_id"] if historical else observed["source_context"]["operation_id"]
        _require(historical or store.pending_identity_publication(spec_id=selection["spec_id"]) is None)
        if not historical and not operation_id.startswith("discovery-completion-"):
            child_row = store.identity_publication(spec_id=selection["spec_id"], operation_id=operation_id)
            _require(child_row is not None and child_row["state"] == "released")
            child_request = decode_publication_request(child_row["request"])
            _require(child_request.continuation is not None)
            operation_id = child_request.continuation.parent_operation_id
        seen, contexts = set(), []
        child, pending_refreshes, pending_spec_predecessors = None, [], []
        clarifications = []
        while True:
            _require(operation_id not in seen)
            seen.add(operation_id)
            repair = repair_child if child is None else child
            repairing = repair is not None and repair.repair_unit is not None
            constitution = constitution_child if child is None else child
            constituting = constitution is not None and constitution.producer == "constitution"
            if constituting and constitution.recovery["version"] == 16:
                pending_spec_predecessors.append(constitution)
            specification = spec_child if child is None else child
            specifying = specification is not None and specification.producer == "what" and not specification.clarification
            reviewing = specification is not None and specification.producer == "why2" and not specification.clarification
            deriving = specification is not None and specification.producer == "lexicon"
            deriving_debt = deriving and specification.recovery["resolution"] is not None
            gating = specification is not None and specification.producer == "lexicon_gate"
            reviewing_answer = reviewing and specification.recovery["version"] in {19, 24}
            reviewing_policy = reviewing_answer and specification.recovery["version"] == 24
            specifying_answer = specifying and specification.recovery["version"] in {20, 22, 26}
            specifying_policy = specifying_answer and specification.recovery["version"] in {22, 26}
            specification_parent = "why2" if (specifying and specification.recovery["predecessor"] is not None
                and specification.recovery["version"] != 17) else "constitution"
            if (specification is not None and specification.producer in {"what", "why2", "lexicon"} and not specification.clarification
                    and specification.recovery["predecessor"] is not None):
                pending_spec_predecessors.append(specification)
            binding, project, context = _retained_input_projection(root, run, state, store,
                operation_id=operation_id, source=source, require_checkpoint=require_checkpoint,
                required_origin="resolution" if reviewing_answer or specifying_answer or deriving_debt else "routed",
                required_route=(None if specifying_policy or reviewing_policy or deriving_debt else
                    ("phase1-lexicon-derive", "phase1-lexicon") if gating else
                    ("phase1-lexicon" if specification.recovery["predecessor"] is not None else "phase1-why2", "phase1-lexicon-derive") if deriving else
                    ("phase1-why2", "phase1-what") if specifying_answer else
                    ("phase1-why2", "phase1-why2") if reviewing_answer else
                    ("phase1-understanding", "phase1-why2") if reviewing else
                    ("phase1-" + specification_parent, "phase1-what") if specifying else
                    ("phase1-why1", "phase1-constitution") if constituting else
                    (repair.recovery["operation"]["binding"]["intent"]["origin"]["return_phase"], "phase1-discover") if repairing else None))
            if gating:
                from harness.discovery_lexicon import prior_gate_attempts
                _require(binding.producer == "lexicon" and specification.recovery["previous_attempts"]
                    == prior_gate_attempts(root, run, state, binding))
            if deriving:
                if specification.recovery["predecessor"] is not None:
                    _require(binding.producer == "lexicon_gate"
                        and binding.recovery["result"]["state_updates"]["lexicon_evaluation"] == "failed")
                else:
                    if deriving_debt:
                        _require(binding.recovery["version"] == 27 and binding.candidate["route"] == "phase1-lexicon-derive"
                            and binding.recovery["resolution"] == specification.recovery["resolution"]["decision"]
                            and binding.recovery["resolution"]["selected_option_id"] == "continue_with_debt")
                    else:
                        _require(binding.producer == "why2" and not binding.resolution_publication
                            and binding.candidate["routing"]["verdict"] == "PASS")
            if specifying_answer:
                _require((binding.policy_resolution if specifying_policy else binding.producer == "why2" and binding.recovery["version"] == 18)
                    and binding.candidate["route"] == "phase1-what"
                    and binding.recovery["resolution"] == specification.recovery["review_resolution"]["decision"]
                    and binding.recovery["operation"]["binding"]["operation_id"] == specification.recovery["review_parent"])
            elif specifying:
                _require(binding.producer == specification_parent and not binding.clarification)
                if specification.recovery["version"] == 17:
                    _require(binding.recovery["version"] == 16
                        and binding.recovery["operation"]["binding"]["operation_id"] == specification.recovery["constitution_parent"])
            for pending_spec in tuple(pending_spec_predecessors):
                if binding.producer == pending_spec.producer and not binding.clarification:
                    _require(binding.recovery["operation"]["binding"]["operation_id"]
                        == pending_spec.recovery["predecessor"])
                    pending_spec_predecessors.remove(pending_spec)
            if reviewing_answer:
                _require((binding.policy_resolution and binding.recovery["version"] == 23 if reviewing_policy
                    else binding.producer == "why2" and binding.recovery["version"] == 18)
                    and binding.candidate["route"] == "phase1-why2"
                    and binding.recovery["operation"]["binding"]["operation_id"] == specification.recovery["predecessor"]
                    and binding.recovery["resolution"] == specification.recovery["resolution"]["decision"])
                prefix = run.relative_to(root).as_posix() + "/evidence/understanding/"
                report, = (item for item in binding.sources.files if item.path.startswith(prefix))
                captured, = (item for item in specification.sources.files if item.path == report.path)
                _require(captured == report)
            elif reviewing:
                _require(binding.producer == "understanding" and binding.recovery["result"]["verdict"] == "DONE")
                report, = (item for item in binding.sources.files if item.path == binding.recovery["report_path"])
                captured, = (item for item in specification.sources.files if item.path == report.path)
                _require(captured == report)
            if constituting:
                _require(binding.producer == "why1" and not binding.clarification)
                if constitution.recovery["version"] == 16:
                    from harness.discovery_constitution import require_refreshed_why1
                    require_refreshed_why1(root, run, state, binding, store)
            if repairing:
                _require_repair_origin(state, repair, binding)
            _require_why1_tracker_parent(state, why1_child if child is None else child, binding)
            refreshing = refresh_child if child is None else child
            if refreshing is not None and refreshing.recovery["version"] in {9, 10, 11}:
                _require_refresh_parent(refreshing, binding, source)
                pending_refreshes.append(refreshing)
            for pending_refresh in tuple(pending_refreshes):
                if binding.producer == pending_refresh.producer and not binding.clarification:
                    _require_refresh_dependencies(pending_refresh.recovery, binding, source,
                        pending_refresh.sources, pending_refresh.source, selection, run, root,
                        producer=pending_refresh.producer)
                    pending_refreshes.remove(pending_refresh)
            if child is None:
                expected = project_publication_source_images(binding.result_baseline).manifest
                _require(historical or (asdict(expected) == observed["source_context"]["manifest"]
                    and observed["source_context"]["operation_id"] == binding.result_operation_id
                    and store.identity_history(spec_id=binding.spec_id) == binding.result_history))
                selected_project = project
            else:
                # A digest-matching receipt is not sufficient: the child's
                # captured before-images must be this parent's exact result.
                _require(child.request.sources.expected_operation_id == binding.result_operation_id
                    and child.request.sources.context_id == binding.request.sources.context_id
                    and child.source["history"] == asdict(binding.result_history))
                spec, = (tree for tree in child.sources.trees if tree.path == selection["spec_path"])
                _require(project(spec) == child.baseline.trees[0])
                context(child.sources)
            contexts.append(context)
            if binding.clarification:
                clarifications.append(binding)
            source = binding.recovery.get("source_completion")
            if source is None:
                _require(binding.producer == "discovery" and not pending_refreshes and not pending_spec_predecessors)
                break
            child = binding
            operation_id = "discovery-completion-" + source["dispatch_id"]
            require_checkpoint = False
        from harness.tracker_clarification import validate_clarification_history
        validate_clarification_history(clarifications, pending=clarification_child)
        def original_runtime(sources):
            for project_context in contexts:
                sources = project_context(sources)
            return sources
        return selected_project, original_runtime
    except Exception:
        pass
    raise CompletionError("intent_mismatch")


def _retained_input_projection(root, run, state, store, *, operation_id, source, require_checkpoint, required_route=None, required_origin="routed"):
    """Read one exact retained completion; ancestry selection stays with caller."""
    from harness.squad_completion import validate_retained_completion_proof
    selection = bootstrap_from_state(state)["selection"]
    row = store.identity_publication(spec_id=selection["spec_id"], operation_id=operation_id)
    _require(row is not None and row["state"] == "released")
    proof = _document(row["completion_payload"])
    _require(type(require_checkpoint) is bool and type(proof["version"]) is int and proof["version"] in {2, 3})
    field = "checkpoint" if proof["version"] == 2 else "proof"
    _closed(proof, ("version", "completion", field))
    _closed(proof[field], ("intent", "receipts"))
    marker, intent, receipts = validate_retained_completion_proof(proof["completion"],
        proof[field]["intent"], proof[field]["receipts"])
    if required_route is not None:
        _require(required_origin in {"routed", "resolution"} and intent.origin == required_origin and intent.route["from_phase"] == required_route[0]
            and intent.route["to_phase"] == required_route[1])
        if required_origin == "routed":
            _require(intent.route["manual_phase_run"] is False and intent.route["record_completion"] is True)
    if source is not None:
        _require(source == dict(dispatch_id=marker.completion_id,
            completion_intent_sha256=marker.intent_sha256,
            completion_receipts_sha256=marker.receipts_sha256,
            completed_publication_binding_sha256=marker.publication_binding_sha256))
    _require(not (require_checkpoint or proof["version"] == 2) or "checkpoint" in intent.effect_plan)
    binding = decode_binding(intent.publication, completion_id=marker.completion_id, state=state)
    _require(binding is not None and row["request"] == encode_publication_request(binding.request)
        and binding.operation_id == operation_id)
    if required_route is not None and required_origin == "resolution":
        _require(binding.resolution_publication and intent.route["decision_id"] == binding.recovery["resolution"]["id"])
    if binding.request.continuation_id is not None:
        from types import SimpleNamespace
        from harness.discovery_restoration_completion import authenticated_continuation
        binding = replace(binding, restoration=authenticated_continuation(root, run, state, binding=binding,
            completion=SimpleNamespace(marker=marker, intent=intent, receipts=receipts), parent=row))
        _require(binding.restoration is not None and binding.restoration.state == "released")
    if binding.clarification:
        from harness.tracker_clarification import require_parent, require_resolution_receipt
        require_parent(state, binding, store)
        require_resolution_receipt(state, binding, marker)
    elif binding.policy_resolution:
        from harness.discovery_policy_resolution import require_parent, require_resolution_receipt
        require_parent(root, run, state, binding, store)
        require_resolution_receipt(state, binding, marker)
        if binding.recovery["version"] == 27:
            from harness.discovery_debt_resolution import require_effect
            require_effect(binding, intent)
    elif binding.producer == "checkpoint":
        from harness.discovery_checkpoint_resolution import require_parent, require_receipt
        require_parent(root, run, state, binding)
        require_receipt(state, binding, marker)
    elif binding.producer in {"tracker", "why1"}:
        selected_round = tracker_round(state, binding.recovery["operation"]["binding"]["operation_id"], producer=binding.producer)
        if selected_round["predecessor"] is not None:
            _require(selected_round["resolution"] == binding.recovery["resolution"])
    expected = project_publication_source_images(binding.result_baseline).manifest
    project = _checkpoint_projection(root, run, state, intent=intent, marker=marker,
        receipts=receipts, binding=binding)
    def checked(tree):
        _require(tree.path == selection["spec_path"])
        projected = project(tree)
        _require(snapshot_source_manifest(trees=(projected,), files=()) == expected)
        return projected
    return binding, checked, partial(_project_released_context, root=root, run=run,
        binding=binding, marker=marker, receipts=receipts)


def _project_released_context(sources, *, root, run, binding, marker, receipts):
    """Use authenticated preimages only for the original domain-admission checks.

    Consumers still receive the actual postimage documents, and the raw capture
    remains the publication/read fingerprint. Never regenerate live context.
    """
    from harness.squad_completion import validate_completion_context_images
    context = (run / "context").relative_to(root).as_posix()
    before, = (tree for tree in binding.sources.trees if tree.path == context)
    actual, = (tree for tree in sources.trees if tree.path == context)
    _require(actual.exists == before.exists and actual.directories == before.directories
        and tuple(item.path for item in actual.files) == tuple(item.path for item in before.files))
    receipt = receipts["effects"].get("context")
    if receipt is None:
        _require(actual == before)
    else:
        receipt = validate_completion_context_images(receipt, completion_id=marker.completion_id,
            images={Path(item.path).name: item.content for item in actual.files})
        rows = {item["name"]: item for item in receipt["files"]}
        for original, current in zip(before.files, actual.files, strict=True):
            row = rows[Path(current.path).name]
            _require(row["preimage"] == dict(kind="file", sha256=original.image.sha256,
                size_bytes=len(original.content)))
            # The owner skips identical postimages, otherwise installs a private
            # replacement. Do not accept arbitrary mode changes during repair.
            mode = original.image.mode if current.content == original.content else 0o600
            _require(current.image.mode == mode)
    files = sources.files
    if binding.producer == "constitution":
        from harness.discovery_constitution import CONSTITUTION_PATH
        original, = (item for item in binding.sources.files if item.path == CONSTITUTION_PATH)
        expected, = (item for item in project_publication_source_images(binding.sources).files if item.path == CONSTITUTION_PATH)
        actual_file, = (item for item in files if item.path == CONSTITUTION_PATH)
        _require(actual_file == expected)
        files = tuple(original if item.path == CONSTITUTION_PATH else item for item in files)
    if binding.producer in {"tracker", "why1"} or binding.clarification or binding.repair_unit is not None:
        staging = (run / "staging").relative_to(root).as_posix()
        names = {staging + "/" + name for name in ("user-clarifications.md", "feature-policy.json", "feature-policy.md")}
        originals = {item.path: item for item in binding.sources.files if item.path in names}
        projected = project_publication_source_images(binding.sources)
        expected = {item.path: item for item in projected.files if item.path in names}
        actual_files = {item.path: item for item in sources.files if item.path in names}
        _require(set(originals) == names and actual_files == expected)
        files = tuple(originals.get(item.path, item) for item in files)
    return replace(sources, trees=tuple(before if tree.path == context else tree for tree in sources.trees), files=files)
