"""Closed managed derivation contract; the native gate owns certification."""
import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
import re

LEXICON_OUTPUT = "requirements.lexicon.md"
LEXICON_GATE_TRANSITIONS = (
    {"to": "phase1-lexicon-derive", "condition": "lexicon_gate.spec_enabled AND lexicon_evaluation = pending AND iteration < max_iterations", "action": "increment_iteration"},
    {"to": "phase1-lexicon-derive", "condition": "lexicon_gate.spec_enabled AND lexicon_evaluation = failed AND lexicon_attempts < lexicon_gate.max_repair_attempts AND iteration < max_iterations", "action": "increment_iteration"},
    {"to": "checkpoint-assess", "condition": "always"},
)


def lexicon_gate_route(config, routing_state, updates):
    """Replay the admitted native transitions and native exhaustion override."""
    from harness.discovery_completion import _require, _closed
    from harness.spec_lexicon_gate import lexicon_gate_exhausted
    from harness.condition_evaluator import ConditionEvaluator
    _closed(routing_state, ("iteration", "max_iterations"))
    _require(all(type(value) is int and value >= 0 for value in routing_state.values())
        and routing_state["max_iterations"] > 0)
    gate = config["lexicon_gate"]
    if lexicon_gate_exhausted(gate=gate, artifact="spec", state=routing_state,
            updates=updates, default_max_iterations=routing_state["max_iterations"]):
        return "terminal-blocked"
    enabled = bool(gate.get("enabled", False) and gate.get("artifacts", {}).get("spec", {}).get("enabled", True) is not False)
    state = {**routing_state, **updates, "lexicon_gate": {**gate, "spec_enabled": enabled}}
    for transition in LEXICON_GATE_TRANSITIONS:
        verdict = ConditionEvaluator().evaluate(transition["condition"], state)
        _require(verdict is not None)
        if verdict:
            return transition["to"]
    raise ValueError("managed Lexicon gate has no native successor")


def source_metadata(source_text):
    """Model-facing metadata from the already authenticated captured source."""
    return dict(source_name="spec.md", source_sha256=hashlib.sha256(source_text.encode("utf-8")).hexdigest())


def validate_lexicon_routing(value):
    if (type(value) is not dict or set(value) != {"verdict", "state_updates"}
            or type(value["verdict"]) is not str or value["verdict"] not in {"DONE", "FAIL"}
            or type(value["state_updates"]) is not dict or value["state_updates"]):
        raise ValueError("derivation cannot supply gate authority or state updates")


def validate_lexicon_artifacts(artifacts):
    if (type(artifacts) is not dict or set(artifacts) != {LEXICON_OUTPUT}
            or type(artifacts[LEXICON_OUTPUT]) is not str
            or not artifacts[LEXICON_OUTPUT].strip() or "\x00" in artifacts[LEXICON_OUTPUT]):
        raise ValueError("derivation requires its single nonblank text artifact")
    artifacts[LEXICON_OUTPUT].encode("utf-8")


def require_lexicon_parent(root, run, state, source):
    """Authenticate the completed review before selecting any derivation work."""
    from harness.discovery_completion import _retained_input_projection, _require
    from harness.element_identity_store import IdentityStore
    from harness.phase1_quality import has_current_phase1_quality_certificate
    binding, _, _ = _retained_input_projection(root, run, state, IdentityStore.open(root),
        operation_id="discovery-completion-" + source["dispatch_id"], source=source,
        require_checkpoint=False, required_route=("phase1-why2", "phase1-lexicon-derive"))
    _require(binding.producer == "why2" and not binding.resolution_publication
        and binding.candidate["routing"]["verdict"] == "PASS"
        and has_current_phase1_quality_certificate(state, project_root=root))
    return binding


@dataclass(frozen=True)
class PreparedLexiconGate:
    publication: object
    sources: object
    request: object
    result: object


def _gate_parent(root, run, state, source):
    from harness.discovery_completion import _retained_input_projection, _require
    from harness.element_identity_store import IdentityStore
    parent, _, _ = _retained_input_projection(root, run, state, IdentityStore.open(root),
        operation_id="discovery-completion-" + source["dispatch_id"], source=source,
        require_checkpoint=False, required_route=("phase1-lexicon-derive", "phase1-lexicon"))
    # This increment admits the first gate only. Repair/debt authority is added
    # with its own retained-round tests, never inferred from phase strings.
    _require(parent.producer == "lexicon" and parent.recovery["predecessor"] is None)
    require_lexicon_parent(root, run, state, parent.recovery["source_completion"])
    return parent


def _gate_evaluation(sources, root, spec_path, config, previous_attempts):
    from harness.discovery_completion import _require
    from harness.spec_lexicon_gate import evaluate_captured_spec_lexicon
    gate = config["lexicon_gate"]
    spec_gate = gate.get("artifacts", {}).get("spec", {})
    _require(gate.get("enabled") is True and spec_gate.get("enabled", True) is True
        and str(spec_gate.get("type") or "spec").upper() == "SPEC"
        and str(spec_gate.get("path") or LEXICON_OUTPUT).strip() == LEXICON_OUTPUT
        and str(spec_gate.get("source_ref") or "spec.md").strip() == "spec.md"
        and str(spec_gate.get("glossary_file") or gate.get("glossary_file") or "glossary.md").strip() == "glossary.md"
        and str(spec_gate.get("report") or "spec-lexicon-report.json").strip() == "spec-lexicon-report.json"
        and type(previous_attempts) is int and previous_attempts == 0)
    spec, = (tree for tree in sources.trees if tree.path == spec_path)
    documents = {item.path[len(spec_path) + 1:]: item.content.decode("utf-8") for item in spec.files}
    result, report = evaluate_captured_spec_lexicon(
        derived_text=documents.get(LEXICON_OUTPUT), source_text=documents.get("spec.md"),
        glossary_text=documents.get("glossary.md"), derived_path=root / spec_path / LEXICON_OUTPUT,
        source_path=root / spec_path / "spec.md", glossary_path=root / spec_path / "glossary.md",
        report_path=root / spec_path / "spec-lexicon-report.json", artifact_type="SPEC",
        previous_attempts=previous_attempts)
    _require(report is not None and result.passed is not None)
    return result, report


def _gate_projection(store, spec_id, sources, spec_path):
    """A passing translation remains a read-only association, not new IDs."""
    from harness.discovery_completion import _require
    from harness.element_identity_bundle import LexiconProjectionSource
    from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope
    spec, = (tree for tree in sources.trees if tree.path == spec_path)
    texts = {item.path[len(spec_path) + 1:]: item.content.decode("utf-8") for item in spec.files}
    artifacts = tuple(CandidateArtifact(name, role, texts[name], texts[name])
        for name, role in (("spec.md", "requirements"), (LEXICON_OUTPUT, "lexicon_projection"), ("glossary.md", "glossary"))
        if name in texts)
    checked = store.check_identity_candidate(spec_id=spec_id, artifacts=artifacts, scope=IdentityEditScope((), ()),
        projection_sources=(LexiconProjectionSource(LEXICON_OUTPUT, "spec.md", "glossary.md" if "glossary.md" in texts else None),))
    _require(not checked.diagnostics)


def decode_lexicon_gate_binding(publication, request, recovery, completion_id, state):
    """Closed provider-free proof for one report-only publication."""
    from harness.discovery_bootstrap_state import bootstrap_from_state
    from harness.discovery_completion import DiscoveryCompletionBinding, _require, _closed, _json, _document
    from harness.discovery_producer import SOURCE_FIELDS, identity_spec_tree
    from harness.discovery_publication import _graph
    from harness.element_identity_snapshot import IdentityHistorySnapshot
    from harness.squad_source_baseline_codec import decode_initial_publication_sources
    from harness.squad_source_manifest import snapshot_source_manifest
    _closed(recovery, ("version", "producer", "completion_id", "source_completion", "spec_id",
        "sources", "history", "authority", "runtime", "config", "result", "previous_attempts",
        "project_root", "run_dir", "graph_sha256", "routing_state"))
    _require(type(recovery["version"]) is int and recovery["version"] == 29
        and recovery["producer"] == "lexicon_gate" and not request.operations
        and type(recovery["completion_id"]) is str and re.fullmatch(r"[0-9a-f]{32}", recovery["completion_id"])
        and (completion_id is None or completion_id == recovery["completion_id"]))
    parent = recovery["source_completion"]
    _closed(parent, SOURCE_FIELDS)
    _require(all(type(value) is str and re.fullmatch(r"[0-9a-f]{%d}" % (32 if key == "dispatch_id" else 64), value)
        for key, value in parent.items()))
    authority, history = recovery["authority"], recovery["history"]
    genesis = authority["managed_identity"]
    root, run = Path(recovery["project_root"]), Path(recovery["run_dir"])
    _require(root.is_absolute() and run.is_relative_to(root) and run != root
        and str(root) == recovery["project_root"] and str(run) == recovery["run_dir"]
        and ".." not in root.parts and ".." not in run.parts
        and recovery["runtime"]["context_dir"] == str(run / "context"))
    _closed(history, ("payload", "sha256"))
    _document(history["payload"])
    _require(hashlib.sha256(history["payload"].encode("ascii")).hexdigest() == history["sha256"]
        and request.proposed_history_sha256 == history["sha256"])
    sources = decode_initial_publication_sources(recovery["sources"])
    baseline = decode_initial_publication_sources(request.sources.baseline_payload)
    spec, = (tree for tree in sources.trees if tree.path == genesis["spec_path"])
    _require(sources.publication.promoted_prefix == 0 and sources.publication == baseline.publication
        and baseline.trees == (identity_spec_tree(spec),) and baseline.files == ()
        and sources.publication.marker.to_dict() == publication["marker"]
        and request.manifest_sha256 == sources.publication.marker.manifest_sha256
        and request.sources.context_id == genesis["context_id"] == authority["source_context"]["context_id"]
        and request.sources.expected_operation_id == authority["source_context"]["operation_id"]
        == "discovery-completion-" + parent["dispatch_id"]
        and asdict(snapshot_source_manifest(trees=baseline.trees, files=())) == authority["source_context"]["manifest"])
    result, report = _gate_evaluation(sources, root, spec.path, recovery["config"], recovery["previous_attempts"])
    _require(recovery["result"] == dict(verdict="DONE", state_updates=result.state_updates()))
    lexicon_gate_route(recovery["config"], recovery["routing_state"], result.state_updates())
    graph = _graph(sources, IdentityHistorySnapshot(**history), dict(spec_id=recovery["spec_id"], spec_path=spec.path))
    _require(hashlib.sha256(graph).hexdigest() == recovery["graph_sha256"])
    writes = {spec.path + "/spec-lexicon-report.json": (_json(report) + "\n").encode("ascii"),
        spec.path + "/spec-artifact-graph.json": graph}
    modes = {item.path: item.image.mode for item in spec.files}
    operations = sources.publication.operations
    _require(len(operations) == len(writes) and {op.target for op in operations} == set(writes)
        and all(op.action == "write" and op.postimage_bytes == writes[op.target]
            and op.postimage.mode == modes.get(op.target, 0o644) for op in operations))
    if state is not None:
        selected = bootstrap_from_state(state)["selection"]
        _require(state["managed_identity"] == genesis and selected["spec_id"] == recovery["spec_id"]
            and selected["project_root"] == str(root) and selected["run_dir"] == str(run)
            and type(state.get("max_iterations")) is int
            and state["max_iterations"] == recovery["routing_state"]["max_iterations"])
    _require(_json(recovery) == request.recovery_payload)
    return DiscoveryCompletionBinding(request, recovery, dict(history=history, artifacts={}),
        dict(history=history, authority=authority, runtime=recovery["runtime"]), sources, baseline)


def authenticate_lexicon_gate(root, run, state, completion, binding):
    from harness.config import get_full_resolved_config
    from harness.discovery_completion import _require
    from harness.element_identity_store import IdentityStore
    _gate_parent(root, run, state, binding.recovery["source_completion"])
    _require(get_full_resolved_config(root) == binding.recovery["config"])
    updates = binding.recovery["result"]["state_updates"]
    _require(all(state.get(key) == value for key, value in updates.items()))
    route = lexicon_gate_route(binding.recovery["config"], binding.recovery["routing_state"], updates)
    _require(completion.intent.route["to_phase"] == route
        and state.get("iteration", 0) == binding.recovery["routing_state"]["iteration"] + int(route == "phase1-lexicon-derive"))
    if updates["lexicon_pass"]:
        _gate_projection(IdentityStore.open(root), binding.spec_id, binding.sources, binding.baseline.trees[0].path)


def prepare_lexicon_gate_publication(root, state_store, *, completion_id, max_iterations):
    from harness.config import get_full_resolved_config
    from harness.discovery_bootstrap_state import bootstrap_from_state
    from harness.discovery_completion import released_discovery_input_projectors, _require, _json
    from harness.discovery_inputs import admit_runtime_inputs
    from harness.discovery_producer import SOURCE_FIELDS, identity_spec_tree
    from harness.discovery_publication import _seal, _inspect, _graph
    from harness.element_identity_publication import PublicationIntentRequest, PublicationSourceClaim
    from harness.element_identity_store import IdentityStore
    from harness.squad_publication import load_prepared_publication
    from harness.squad_source_baseline_codec import encode_initial_publication_sources
    from harness.squad_source_snapshot import PublicationSourcesSnapshot
    from harness.squad_provider import SquadAgentResult
    root, run = Path(root), state_store.squad_dir
    state = state_store.load()
    _require(state["phase"] == "phase1-lexicon" and state["status"] == "running"
        and type(state.get("max_iterations")) is int and state["max_iterations"] > 0
        and not any(key in state for key in ("pending_controller_completion", "pending_external_publication", "product_input_mutation", "lexicon_gate")))
    selection = bootstrap_from_state(state)["selection"]
    source = {key: state["last_dispatch"][key] for key in SOURCE_FIELDS}
    parent = _gate_parent(root, run, state, source)
    project_spec, project_context = released_discovery_input_projectors(root, run, state, source=source)
    capture = load_prepared_publication(root, run, selection["capture_marker"])
    with capture.inspect_sources(tree_paths=tuple(tree.path for tree in parent.sources.trees),
            file_paths=tuple(item.path for item in parent.sources.files)) as before:
        spec, = (tree for tree in before.trees if tree.path == selection["spec_path"])
        project_spec(spec)
        runtime, _ = admit_runtime_inputs(root, run, state, project_context(before))
    config = get_full_resolved_config(root)
    previous = state.get("lexicon_attempts", 0)
    result, report = _gate_evaluation(before, root, spec.path, config, previous)
    store = IdentityStore.open(root)
    authority = store.check_managed_context(spec_id=selection["spec_id"], run_id=state["run_id"], record=state["managed_identity"])
    history = store.identity_history(spec_id=selection["spec_id"])
    if result.passed:
        _gate_projection(store, selection["spec_id"], before, spec.path)
    writes = {spec.path + "/spec-lexicon-report.json": (_json(report) + "\n").encode("ascii")}
    modes = {item.path: item.image.mode for item in spec.files}
    provisional = _seal(root, run, writes, modes)
    projected = _inspect(provisional, before, writes, modes)
    graph = _graph(projected, history, selection)
    writes[spec.path + "/spec-artifact-graph.json"] = graph
    publication = _seal(root, run, writes, modes)
    sources = _inspect(publication, before, writes, modes)
    baseline = PublicationSourcesSnapshot(sources.publication, (identity_spec_tree(spec),), ())
    recovery = dict(version=29, producer="lexicon_gate", completion_id=completion_id,
        source_completion=source, spec_id=selection["spec_id"], sources=encode_initial_publication_sources(sources),
        history=asdict(history), authority=authority, runtime=runtime, config=config,
        result=dict(verdict="DONE", state_updates=result.state_updates()), previous_attempts=previous,
        project_root=str(root), run_dir=str(run), graph_sha256=hashlib.sha256(graph).hexdigest(),
        routing_state=dict(iteration=state.get("iteration") or 0, max_iterations=state.get("max_iterations") or max_iterations))
    request = PublicationIntentRequest(publication.marker.manifest_sha256, _json(recovery), (),
        PublicationSourceClaim(authority["source_context"]["context_id"], authority["source_context"]["operation_id"],
            encode_initial_publication_sources(baseline)), proposed_history_sha256=history.sha256)
    decode_lexicon_gate_binding(dict(kind="external", marker=publication.marker.to_dict()), request, recovery, completion_id, state)
    _require(state_store.load() == state and get_full_resolved_config(root) == config
        and store.identity_history(spec_id=selection["spec_id"]) == history)
    provisional.discard()
    return PreparedLexiconGate(publication, sources, request, SquadAgentResult(exit_code=0,
        echelon_result=recovery["result"], raw_output="", duration_ms=0, timed_out=False))
