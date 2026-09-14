"""Managed discovery association for the existing Squad completion owner.

Digest preimages prove membership in protected accepted discovery state, not new
authority. The caller owns execution leases and durable completion provenance.
"""
from dataclasses import asdict, dataclass, replace
from functools import partial
import hashlib
import json
from pathlib import Path

from harness.discovery_bootstrap_state import BOOTSTRAP_KEY, bootstrap_from_state
from harness.discovery_inputs import admit_runtime_inputs
from harness.discovery_operation_state import DISCOVERY_OPERATION_KEY, operation_from_state
from harness.discovery_publication import _graph
from harness.discovery_receipts import DiscoveryReceiptFile
from harness.discovery_turn_state import DISCOVERY_TURNS_KEY
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
    _closed(recovery, ("version", "completion_id", "operation", "candidate_sha256", "source_fingerprint",
        "candidate_inputs", "source_inputs", "review", "provider", "sources", "graph_sha256"))
    _require(type(recovery["version"]) is int and recovery["version"] == 2
        and _json(recovery) == request.recovery_payload)
    if completion_id is not None:
        _require(recovery["completion_id"] == completion_id)
    candidate = _document(recovery["candidate_inputs"])
    source = _document(recovery["source_inputs"])
    _closed(candidate, ("artifacts", "proposal", "reservations", "operations", "history"))
    _closed(source, ("manifest", "history", "authority", "runtime"))
    _require(_json(candidate) == recovery["candidate_inputs"] and _hash(candidate) == recovery["candidate_sha256"]
        and _json(source) == recovery["source_inputs"] and _hash(source) == recovery["source_fingerprint"])
    operation = recovery["operation"]
    selected = operation["binding"]
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
    _require(baseline.trees == (spec,) and baseline.files == ()
        and request.sources.context_id == genesis["context_id"] == authority["source_context"]["context_id"]
        and request.sources.expected_operation_id == authority["source_context"]["operation_id"]
        and asdict(snapshot_source_manifest(trees=(spec,), files=())) == authority["source_context"]["manifest"])
    _require(type(candidate["artifacts"]) is dict and set(candidate["artifacts"]) == set(selected["artifact_paths"]))
    writes = {spec_path + "/" + name: text.encode("utf-8") for name, text in candidate["artifacts"].items()}
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
        _require(bootstrap is not None and operation_from_state(state) == operation
            and state.get("managed_identity") == genesis and state.get(DISCOVERY_TURNS_KEY) == recovery["provider"])
        _require(all(bootstrap["selection"][key] == selected[key] for key in ("spec_id", "run_id", "operation_id")))
    return DiscoveryCompletionBinding(request, recovery, candidate, source, sources, baseline)


def authenticate(root, run, state, completion):
    """Authenticate the saved completion association without live-source replay."""
    try:
        binding = decode_binding(completion.intent.publication, completion_id=completion.marker.completion_id, state=state)
        if binding is None:
            return None
        route = completion.intent.route
        _require(completion.intent.origin == "routed" and route["from_phase"] == "phase1-discover"
            and route["manual_phase_run"] is False and route["record_completion"] is True
            and set(completion.intent.effect_plan) <= {"journal", "timing", "checkpoint", "context"}
            and "product_input_mutation" not in state)
        selection = bootstrap_from_state(state)["selection"]
        _require(str(root) == selection["project_root"] and str(run) == selection["run_dir"])
        runtime, _ = admit_runtime_inputs(root, run, state, binding.sources)
        _require(runtime == binding.source["runtime"])
        store = IdentityStore.open(root)
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
        _require(binding is not None and state.get("phase") == "phase1-discover"
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


def _read_receipt(run, name):
    with DiscoveryReceiptFile(run, name) as file:
        raw = file._read()
        value = json.loads(raw, object_pairs_hook=_unique_object)
        _closed(value, ("payload", "sha256"))
        _require(_hash(value["payload"]) == value["sha256"])
        _require(file._read() == raw)
    return value["payload"]


def _receipts(root, run, state, binding, store):
    from harness.discovery_turns import _validate
    from harness.discovery_reservations import _validate as validate_reservations
    turns = _read_receipt(run, "discovery-turns")
    _validate(turns)
    _require(_hash(turns["binding"]) == state[DISCOVERY_TURNS_KEY]["binding_sha256"]
        and turns["binding"]["authority"] == binding.source["authority"])
    from harness.prosaic_prompt_loader import ProsaicPromptLoader
    loader = ProsaicPromptLoader(root, timeout_s=10)
    _require({name: asdict(loader.load_subagent("echelon.discovery-" + name))
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
    reservations = _read_receipt(run, "discovery-reservations")
    _require(reservations["binding"]["context"] == binding.source["authority"])
    known = validate_reservations(reservations, reservations["binding"])
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
    if "checkpoint" not in plan:
        return lambda tree: tree
    selection = bootstrap_from_state(state)["selection"]
    spec = selection["spec_path"]
    target = Path(str(state.get("spec_dir") or ""))
    if not target.is_absolute():
        target = root / target
    _require(target == root / spec)
    original, = (tree for tree in binding.sources.trees if tree.path == spec)
    metadata = spec + "/.echelon"
    _require(not any(item.path == metadata or item.path.startswith(metadata + "/")
        for item in (*original.directories, *original.files)))
    step = marker.step
    if step in plan and plan.index(step) < plan.index("checkpoint"):
        return lambda tree: tree
    _require(step == "complete" or step in plan)
    pending = step == "checkpoint" and "checkpoint" not in receipts["effects"]
    route = intent.route
    artifacts, = project_publication_source_images(binding.baseline).trees
    ledger = fresh_completion_checkpoint_ledger_image(project_root=root, spec_dir=root / spec,
        phase=route["from_phase"], next_phase=route["to_phase"], run_id=selection["run_id"],
        spec_id=selection["spec_id"], completion_id=marker.completion_id,
        checkpoint_prestate=intent.checkpoint_prestate,
        expected_receipt=receipts["effects"].get("checkpoint"),
        allow_pending=pending, rewind=str(route.get("rewind_policy") or "supported"),
        artifact_images={item.path: (item.image.mode, item.content) for item in artifacts.files})
    return partial(_project_checkpoint_tree, spec=spec, ledger=ledger, pending=pending)


def _project_checkpoint_tree(tree, *, spec, ledger, pending):
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
    if not pending:
        _require(len(directories) == 1 and len(names) == 2 and ledger is not None)
    for path, item in names.items():
        expected = b"" if path.endswith("/checkpoints.lock") else ledger
        _require(item.image.mode == 0o600 and expected is not None and item.content == expected)
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
    selected = {spec + "/" + name for name in binding.recovery["operation"]["binding"]["artifact_paths"]}
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
    """Prepare a checked spec-identity view after completion outbox cleanup.

    Caller owns execution leases, then captures the complete tree under the
    existing source inspector and calls the returned pure projection there.
    Keep that full capture for read guards; only the authenticated identity view
    omits checkpoint metadata. This does not admit other repair input domains.
    """
    from harness.squad_completion import validate_retained_completion_proof
    try:
        selection = bootstrap_from_state(state)["selection"]
        _require(str(root) == selection["project_root"] and str(run) == selection["run_dir"])
        store = IdentityStore.open(root)
        observed = store.check_managed_context(spec_id=selection["spec_id"], run_id=selection["run_id"],
            record=state["managed_identity"])
        row = store.identity_publication(spec_id=selection["spec_id"], operation_id=observed["source_context"]["operation_id"])
        _require(row is not None and row["state"] == "released"
            and store.pending_identity_publication(spec_id=selection["spec_id"]) is None)
        proof = _document(row["completion_payload"])
        _require(type(require_checkpoint) is bool and type(proof["version"]) is int and proof["version"] in {2, 3})
        field = "checkpoint" if proof["version"] == 2 else "proof"
        _closed(proof, ("version", "completion", field))
        _closed(proof[field], ("intent", "receipts"))
        marker, intent, receipts = validate_retained_completion_proof(proof["completion"],
            proof[field]["intent"], proof[field]["receipts"])
        _require(not (require_checkpoint or proof["version"] == 2) or "checkpoint" in intent.effect_plan)
        binding = decode_binding(intent.publication, completion_id=marker.completion_id, state=state)
        _require(binding is not None and row["request"] == encode_publication_request(binding.request)
            and binding.operation_id == observed["source_context"]["operation_id"]
            and asdict(store.identity_history(spec_id=binding.spec_id)) == binding.candidate["history"])
        expected = project_publication_source_images(binding.baseline).manifest
        _require(asdict(expected) == observed["source_context"]["manifest"])
        project = _checkpoint_projection(root, run, state, intent=intent, marker=marker,
            receipts=receipts, binding=binding)
        def checked(tree):
            _require(tree.path == selection["spec_path"])
            projected = project(tree)
            _require(snapshot_source_manifest(trees=(projected,), files=()) == expected)
            return projected
        return checked
    except Exception:
        pass
    raise CompletionError("intent_mismatch")
