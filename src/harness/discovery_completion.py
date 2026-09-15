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
from harness.discovery_receipts import DiscoveryReceiptFile
from harness.discovery_turn_state import DISCOVERY_TURNS_KEY
from harness.discovery_producer import producer_component, producer_phase, producer_role, synthesis_source, identity_spec_tree, tracker_round, tracker_input_source
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

    @property
    def producer(self):
        return self.recovery.get("producer", "discovery")

    @property
    def repair_unit(self):
        return self.recovery.get("repair_unit")

    @property
    def clarification(self):
        return self.recovery["version"] in {5, 7}

    @property
    def spec_id(self):
        return self.recovery["operation"]["binding"]["spec_id"]

    @property
    def operation_id(self):
        return "discovery-completion-" + self.recovery["completion_id"]


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
    recovery = _document(request.recovery_payload)
    if recovery.get("version") in {5, 7}:
        from harness.tracker_clarification import decode_clarification_binding
        return decode_clarification_binding(publication, request, recovery, completion_id, state)
    _closed(recovery, ("version", "completion_id", "operation", "candidate_sha256", "source_fingerprint",
        "candidate_inputs", "source_inputs", "review", "provider", "sources", "graph_sha256",
        *(("producer", "source_completion") if recovery.get("version") in {3, 4, 6, 8} else ()),
        *(("resolution",) if recovery.get("version") in {4, 6} else ()),
        *(("repair_unit",) if recovery.get("version") == 8 else ())))
    producer = recovery.get("producer", "discovery")
    repair_unit = recovery.get("repair_unit")
    _require(type(recovery["version"]) is int and recovery["version"] in {2, 3, 4, 6, 8}
        and (recovery["version"] != 3 or producer == "synthesizer")
        and (recovery["version"] != 4 or producer == "tracker")
        and (recovery["version"] != 6 or producer == "why1")
        and (recovery["version"] != 8 or producer == "discovery")
        and _json(recovery) == request.recovery_payload)
    if completion_id is not None:
        _require(recovery["completion_id"] == completion_id)
    candidate = _document(recovery["candidate_inputs"])
    source = _document(recovery["source_inputs"])
    _closed(candidate, ("artifacts", "proposal", "reservations", "operations", "history",
        *(("routing",) if producer in {"tracker", "why1"} else ())))
    if producer in {"tracker", "why1"}:
        from harness.discovery_semantics import _tracker_routing
        _tracker_routing(candidate["routing"], producer)
        _require(recovery["review"]["routing"] == candidate["routing"])
    _closed(source, ("manifest", "history", "authority", "runtime"))
    _require(_json(candidate) == recovery["candidate_inputs"] and _hash(candidate) == recovery["candidate_sha256"]
        and _json(source) == recovery["source_inputs"] and _hash(source) == recovery["source_fingerprint"])
    operation = recovery["operation"]
    selected = operation["binding"]
    if recovery["version"] == 8:
        _require(type(repair_unit) is str and re.fullmatch(r"[0-9a-f]{64}", repair_unit) is not None
            and selected["operation_id"] == "discovery-repair-" + repair_unit
            and selected["intent"]["kind"] == "repair"
            and selected["intent"]["origin"]["return_phase"] == "phase1-why1")
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
    writes = {spec_path + "/" + name: text.encode("utf-8") for name, text in candidate["artifacts"].items() if text is not None}
    graph = _graph(sources, IdentityHistorySnapshot(**candidate["history"]), dict(spec_id=selected["spec_id"], spec_path=spec_path))
    _require(hashlib.sha256(graph).hexdigest() == recovery["graph_sha256"])
    writes[spec_path + "/spec-artifact-graph.json"] = graph
    modes = {item.path: item.image.mode for item in spec.files}
    operations = sources.publication.operations
    _require(len(operations) == len(writes) and {op.target for op in operations} == set(writes)
        and sources.publication.promoted_prefix == 0)
    _require(all(op.action == "write" and op.postimage_bytes == writes[op.target]
        and op.postimage.mode == modes.get(op.target, 0o644) for op in operations))
    if state is not None:
        bootstrap = bootstrap_from_state(state)
        op_id = selected["operation_id"] if producer in {"tracker", "why1"} else None
        _require(bootstrap is not None and operation_from_state(state, producer, operation_id=op_id, repair_unit=repair_unit) == operation
            and state.get("managed_identity") == genesis
            and producer_component(state, producer, "turns", operation_id=op_id, repair_unit=repair_unit) == recovery["provider"])
        _require(all(bootstrap["selection"][key] == selected[key]
            for key in (("spec_id", "run_id", "operation_id") if producer == "discovery" and repair_unit is None else ("spec_id", "run_id"))))
        if repair_unit is not None:
            from harness.discovery_producer import repair_record
            _require(repair_record(state, producer, repair_unit)["selection"]["source"] == recovery["source_completion"])
        if producer == "synthesizer":
            _require(synthesis_source(state) == recovery["source_completion"])
        if producer in {"tracker", "why1"}:
            row = tracker_round(state, selected["operation_id"], producer=producer)
            _require(tracker_input_source(state, selected["operation_id"], producer=producer) == recovery["source_completion"]
                and row["resolution"] == recovery["resolution"])
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
        if binding.clarification:
            _require(completion.intent.origin == "resolution" and route["from_phase"] == producer_phase(binding.producer)
                and route["decision_id"] == binding.recovery["resolution"]["id"]
                and completion.intent.effect_plan == ("context",))
        else:
            _require(completion.intent.origin == "routed" and route["from_phase"] == producer_phase(binding.producer)
                and route["manual_phase_run"] is False and route["record_completion"] is True
                and set(completion.intent.effect_plan) <= {"journal", "timing", "checkpoint", "context"})
        selection = bootstrap_from_state(state)["selection"]
        _require(str(root) == selection["project_root"] and str(run) == selection["run_dir"])
        input_view = binding.sources
        if binding.producer != "discovery" or binding.repair_unit is not None:
            spec_view, runtime_view = _released_discovery_projections(root, run, state,
                source=binding.recovery["source_completion"], historical=True,
                repair_child=binding if binding.repair_unit is not None else None)
            spec_tree, = (tree for tree in binding.sources.trees if tree.path == selection["spec_path"])
            _require(spec_view(spec_tree) == binding.baseline.trees[0])
            input_view = runtime_view(binding.sources)
        runtime, _ = admit_runtime_inputs(root, run, state, input_view)
        _require(runtime == binding.source["runtime"])
        store = IdentityStore.open(root)
        if binding.clarification:
            from harness.tracker_clarification import require_parent
            require_parent(state, binding, store)
        observed = store.check_managed_context(spec_id=binding.spec_id, run_id=state["run_id"], record=state["managed_identity"])
        pending = store.pending_identity_publication(spec_id=binding.spec_id)
        retained = store.identity_publication(spec_id=binding.spec_id, operation_id=binding.operation_id)
        _require(pending is None or pending == retained)
        if retained is not None:
            _require(retained["request"] == encode_publication_request(binding.request))
        applied = retained is not None and retained["state"] in {"applied", "released"}
        expected = project_publication_source_images(binding.baseline).manifest if applied else snapshot_source_manifest(
            trees=binding.baseline.trees, files=binding.baseline.files)
        _require(observed["source_context"]["manifest"] == asdict(expected)
            and observed["source_context"]["operation_id"] == (binding.operation_id if applied else binding.request.sources.expected_operation_id)
            and asdict(store.identity_history(spec_id=binding.spec_id)) == (binding.candidate if applied else binding.source)["history"])
        _receipts(root, run, state, binding, store)
        return binding
    except Exception:
        pass
    raise CompletionError("intent_mismatch")


def require_unpublished_orphan(root, run, state, intent):
    """Authorize disposal, never promotion, of a sealed but never-routed draft."""
    try:
        binding = decode_binding(intent["publication"], completion_id=intent["completion_id"], state=state)
        _require(binding is not None and state.get("phase") == producer_phase(binding.producer)
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
    if binding.clarification:
        # Human decision membership is checked by the closed binding decoder;
        # the parent Tracker's retained proof is checked by ancestry traversal.
        return
    from harness.discovery_turns import _validate
    from harness.discovery_reservations import _validate as validate_reservations
    operation_id = binding.recovery["operation"]["binding"]["operation_id"] if binding.producer in {"tracker", "why1"} else None
    turns = _read_receipt(run, "discovery-turns", binding.producer, operation_id=operation_id, repair_unit=binding.repair_unit)
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
    if binding.producer in {"tracker", "why1"}:
        _require(replies["author"]["routing"] == binding.candidate["routing"] == replies["review"]["routing"])
    reservations = _read_receipt(run, "discovery-reservations", binding.producer, operation_id=operation_id, repair_unit=binding.repair_unit)
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


def _checkpoint_projection(root, run, state, *, intent, marker, receipts, binding):
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
    ledger = fresh_completion_checkpoint_ledger_image(project_root=root, spec_dir=root / spec,
        phase=route["from_phase"], next_phase=route["to_phase"], run_id=selection["run_id"],
        spec_id=selection["spec_id"], completion_id=marker.completion_id,
        checkpoint_prestate=intent.checkpoint_prestate,
        expected_receipt=receipts["effects"].get("checkpoint"),
        allow_pending=pending, rewind=str(route.get("rewind_policy") or "supported"),
        artifact_images=images, ledger_preimage=prior_ledger)
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


def context_generator(root, run, state, completion):
    """Supply captured postimages to the existing completion context owner."""
    from echelon.context_builder import build_run_context
    binding = require_applied(root, run, state, completion)
    _require(binding is not None)
    spec = binding.source["authority"]["managed_identity"]["spec_path"]
    if binding.clarification:
        projected = project_publication_source_images(binding.sources)
        artifacts = {item.path: item.content for tree in projected.trees for item in tree.files
            if tree.path == spec and item.path.endswith(".md")}
        artifacts.update({item.path: item.content for item in projected.files
            if item.path in binding.candidate["artifacts"] and item.path.endswith(".md")})
        return partial(build_run_context, captured_discovery_artifacts=artifacts)
    selected = {spec + "/" + name for name in binding.recovery["operation"]["binding"]["artifact_paths"]
        if binding.candidate["artifacts"][name] is not None}
    projected = project_publication_source_images(binding.sources)
    artifacts = {item.path: item.content for tree in projected.trees for item in tree.files if item.path in selected}
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
    if binding.clarification:
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
    try:
        publication = load_prepared_publication(root, run, binding.sources.publication.marker)
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
    _require(parent.producer == "why1" and not parent.clarification
        and parent.candidate["routing"]["verdict"] == "FAIL" and parent.recovery["review"]["verdict"] == "accept"
        and claim["origin"] == dict(review_id=parent.recovery["completion_id"], return_phase="phase1-why1"))
    def artifacts(binding):
        tree, = binding.baseline.trees
        return {item.path[len(tree.path) + 1:]: item.content.decode("utf-8") for item in tree.files}
    findings, paths, revisions = repair_findings(artifacts(child), IdentityHistorySnapshot(**child.source["history"]),
        artifacts(parent), IdentityHistorySnapshot(**parent.source["history"]))
    _require(claim["findings"] == findings and claim["artifact_paths"] == paths and claim["editable_revisions"] == revisions)


def _released_discovery_projections(root, run, state, *, require_checkpoint=False, source=None, historical=False, repair_child=None):
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
        seen, contexts = set(), []
        child = None
        while True:
            _require(operation_id not in seen)
            seen.add(operation_id)
            repair = repair_child if child is None else child
            repairing = repair is not None and repair.repair_unit is not None
            binding, project, context = _retained_input_projection(root, run, state, store,
                operation_id=operation_id, source=source, require_checkpoint=require_checkpoint,
                required_route=("phase1-why1", "phase1-discover") if repairing else None)
            if repairing:
                _require_repair_origin(state, repair, binding)
            if child is None:
                expected = project_publication_source_images(binding.baseline).manifest
                _require(historical or (asdict(expected) == observed["source_context"]["manifest"]
                    and asdict(store.identity_history(spec_id=binding.spec_id)) == binding.candidate["history"]))
                selected_project = project
            else:
                # A digest-matching receipt is not sufficient: the child's
                # captured before-images must be this parent's exact result.
                _require(child.request.sources.expected_operation_id == binding.operation_id
                    and child.request.sources.context_id == binding.request.sources.context_id
                    and child.source["history"] == binding.candidate["history"])
                spec, = (tree for tree in child.sources.trees if tree.path == selection["spec_path"])
                _require(project(spec) == child.baseline.trees[0])
                context(child.sources)
            contexts.append(context)
            source = binding.recovery.get("source_completion")
            if source is None:
                _require(binding.producer == "discovery")
                break
            child = binding
            operation_id = "discovery-completion-" + source["dispatch_id"]
            require_checkpoint = False
        def original_runtime(sources):
            for project_context in contexts:
                sources = project_context(sources)
            return sources
        return selected_project, original_runtime
    except Exception:
        pass
    raise CompletionError("intent_mismatch")


def _retained_input_projection(root, run, state, store, *, operation_id, source, require_checkpoint, required_route=None):
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
        _require(intent.origin == "routed" and intent.route["from_phase"] == required_route[0]
            and intent.route["to_phase"] == required_route[1]
            and intent.route["manual_phase_run"] is False and intent.route["record_completion"] is True)
    if source is not None:
        _require(source == dict(dispatch_id=marker.completion_id,
            completion_intent_sha256=marker.intent_sha256,
            completion_receipts_sha256=marker.receipts_sha256,
            completed_publication_binding_sha256=marker.publication_binding_sha256))
    _require(not (require_checkpoint or proof["version"] == 2) or "checkpoint" in intent.effect_plan)
    binding = decode_binding(intent.publication, completion_id=marker.completion_id, state=state)
    _require(binding is not None and row["request"] == encode_publication_request(binding.request)
        and binding.operation_id == operation_id)
    if binding.clarification:
        from harness.tracker_clarification import require_parent, require_resolution_receipt
        require_parent(state, binding, store)
        require_resolution_receipt(state, binding, marker)
    elif binding.producer in {"tracker", "why1"}:
        selected_round = tracker_round(state, binding.recovery["operation"]["binding"]["operation_id"], producer=binding.producer)
        if selected_round["predecessor"] is not None:
            _require(selected_round["resolution"] == binding.recovery["resolution"])
    expected = project_publication_source_images(binding.baseline).manifest
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
    if binding.producer in {"tracker", "why1"} or binding.repair_unit is not None:
        staging = (run / "staging").relative_to(root).as_posix()
        names = {staging + "/" + name for name in ("user-clarifications.md", "feature-policy.json", "feature-policy.md")}
        originals = {item.path: item for item in binding.sources.files if item.path in names}
        projected = project_publication_source_images(binding.sources)
        expected = {item.path: item for item in projected.files if item.path in names}
        actual_files = {item.path: item for item in sources.files if item.path in names}
        _require(set(originals) == names and actual_files == expected)
        files = tuple(originals.get(item.path, item) for item in files)
    return replace(sources, trees=tuple(before if tree.path == context else tree for tree in sources.trees), files=files)
