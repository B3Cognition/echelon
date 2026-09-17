"""Captured Phase 2 certification through the existing publication owner.

These associations admit PASS feasibility and ordinary alignment, including
rechecks. Native governance owns validation, repair budgets and routing; every
recheck retains its released predecessor.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re


FEASIBILITY_GATE_TRANSITIONS = (
    {"to": "phase2-decide", "condition": "structural_action = repair", "action": "increment_iteration"},
    {"to": "terminal-blocked", "condition": "structural_action = block"},
    {"to": "phase2-strategic-overview", "condition": "structural_action in [proceed, proceed_with_warning] AND feasibility_verdict = PASS"},
    {"to": "done", "condition": "structural_action in [proceed, proceed_with_warning] AND feasibility_verdict = KILL", "action": "write_kill_report"},
    {"to": "phase1-what", "condition": "structural_action in [proceed, proceed_with_warning] AND feasibility_verdict = DEFER AND defer_count < assess_defer_loop_limit", "action": "increment_defer_count"},
    {"to": "escalate", "condition": "structural_action in [proceed, proceed_with_warning] AND feasibility_verdict = DEFER AND defer_count >= assess_defer_loop_limit"},
)

ALIGNMENT_GATE_TRANSITIONS = (
    {"to": "phase2-tracker-alignment", "condition": "structural_action = repair", "action": "increment_iteration"},
    {"to": "terminal-blocked", "condition": "structural_action = block"},
    {"to": "phase3-specialists", "condition": "structural_action in [proceed, proceed_with_warning] AND intent_alignment_verdict in [ALIGNED, DRIFT]"},
)


def alignment_gate_route(routing_state, updates):
    """Admit ordinary native successors; never execute the destination here."""
    from harness.condition_evaluator import ConditionEvaluator
    from harness.discovery_completion import _require, _closed
    _closed(routing_state, ("iteration", "max_iterations", "intent_alignment_verdict"))
    _require(all(type(routing_state[key]) is int and routing_state[key] >= 0
        for key in ("iteration", "max_iterations")) and routing_state["max_iterations"] > 0
        and routing_state["intent_alignment_verdict"] in {"ALIGNED", "DRIFT"})
    for transition in ALIGNMENT_GATE_TRANSITIONS:
        verdict = ConditionEvaluator().evaluate(transition["condition"], {**updates, **routing_state})
        _require(verdict is not None)
        if verdict:
            return transition["to"]
    raise ValueError("managed alignment gate has no native successor")


def feasibility_gate_route(routing_state, updates):
    """Replay the admitted native transitions, without activating terminal work."""
    from harness.condition_evaluator import ConditionEvaluator
    from harness.discovery_completion import _require, _closed
    _closed(routing_state, ("iteration", "max_iterations", "feasibility_verdict"))
    _require(all(type(routing_state[key]) is int and routing_state[key] >= 0
        for key in ("iteration", "max_iterations")) and routing_state["max_iterations"] > 0
        and routing_state["feasibility_verdict"] == "PASS")
    state = {**updates, **routing_state}
    for transition in FEASIBILITY_GATE_TRANSITIONS:
        verdict = ConditionEvaluator().evaluate(transition["condition"], state)
        _require(verdict is not None)
        if verdict:
            return transition["to"]
    raise ValueError("managed feasibility gate has no native successor")


def evaluate_feasibility_gate(*, sources, root, spec_path, config,
        previous_attempts, iteration, max_iterations):
    return _evaluate_gate(sources=sources, root=root, spec_path=spec_path, config=config,
        previous_attempts=previous_attempts, iteration=iteration, max_iterations=max_iterations,
        artifact="feasibility")


def evaluate_alignment_gate(*, sources, root, spec_path, config,
        previous_attempts, iteration, max_iterations):
    return _evaluate_gate(sources=sources, root=root, spec_path=spec_path, config=config,
        previous_attempts=previous_attempts, iteration=iteration, max_iterations=max_iterations,
        artifact="intent-alignment-check")


def _evaluate_gate(*, sources, root, spec_path, config,
        previous_attempts, iteration, max_iterations, artifact):
    """Select only fixed, observed artifacts and delegate all gate policy."""
    from harness.discovery_completion import _require
    from harness.governance_structural_gate import evaluate_captured_governance_structural_gate
    _require(all(type(value) is int and value >= 0 for value in
        (previous_attempts, iteration, max_iterations)) and max_iterations > 0)
    governance = config.get("governance")
    _require(type(governance) is dict and type(governance.get("artifacts", {})) is dict)
    entry = governance.get("artifacts", {}).get(artifact, {})
    _require(type(entry) is dict)
    # No configured path can redirect this report-only producer into a source.
    for key, default in (("path", artifact + ".md"), ("report", artifact + "-structural-report.json")):
        _require(str(entry.get(key) or default).strip() == default)
    template = entry.get("template")
    _require(not template or template == artifact + "-template.md")
    spec, = (tree for tree in sources.trees if tree.path == spec_path)
    _require(spec.exists and Path(root).is_absolute() and not Path(spec_path).is_absolute()
        and ".." not in Path(spec_path).parts)
    documents = {item.path[len(spec_path) + 1:]: item.content.decode("utf-8") for item in spec.files}
    files = {item.path: item.content for item in sources.files}
    template_bytes = files.get(".echelon/runtime/templates/" + artifact + "-template.md")
    references = {}
    for reference in entry.get("cross_refs") or []:
        _require(type(reference) is dict)
        name = str(reference.get("against") or "").strip()
        if name:
            _require(not Path(name).is_absolute() and ".." not in Path(name).parts
                and name not in {".", ""} and Path(name).as_posix() == name)
            references[name] = documents.get(name)
    return evaluate_captured_governance_structural_gate(artifact_key=artifact,
        spec_dir=Path(root) / spec_path, governance_config=config,
        artifact_text=documents.get(artifact + ".md"), reference_texts=references,
        template_text=None if template_bytes is None else template_bytes.decode("utf-8"),
        previous_attempts=previous_attempts, iteration=iteration, max_iterations=max_iterations)


def _result(gate):
    return dict(verdict={"proceed": "PASS", "repair": "REPAIR", "proceed_with_warning": "WARN",
        "block": "FAIL"}[gate.action], state_updates=gate.state_updates())


def require_feasibility_gate_parent(root, run, state, source):
    """An actually released reviewed author publication, never a phase label."""
    from harness.discovery_completion import _retained_input_projection, _require
    from harness.element_identity_store import IdentityStore
    parent, _, _ = _retained_input_projection(root, run, state, IdentityStore.open(root),
        operation_id="discovery-completion-" + source["dispatch_id"], source=source,
        require_checkpoint=False, required_route=("phase2-decide", "phase2-feasibility-structural"))
    _require(parent.producer == "feasibility" and parent.recovery["version"] in {31, 33}
        and parent.candidate["routing"] == dict(verdict="PASS", state_updates={}))
    return parent


def prior_feasibility_attempts(root, run, state, parent, routing, config):
    """Recover the native budget from the gate that authorized this author round."""
    from harness.discovery_assessment import require_feasibility_repair
    from harness.discovery_completion import _require, _json
    if parent.recovery["version"] == 31:
        return 0
    previous = require_feasibility_repair(root, run, state,
        parent.recovery["source_completion"], parent.recovery["predecessor"])
    expected = {**previous.recovery["routing_state"],
        "iteration": previous.recovery["routing_state"]["iteration"] + 1}
    _require(_json(routing) == _json(expected) and _json(config) == _json(previous.recovery["config"]))
    return previous.recovery["result"]["state_updates"]["feasibility_structural_attempts"]


def require_alignment_gate_parent(root, run, state, source):
    """A released ordinary alignment author, not strategy or a question."""
    from harness.discovery_completion import _retained_input_projection, _require
    from harness.element_identity_store import IdentityStore
    parent, _, _ = _retained_input_projection(root, run, state, IdentityStore.open(root),
        operation_id="discovery-completion-" + source["dispatch_id"], source=source,
        require_checkpoint=False,
        required_route=("phase2-tracker-alignment", "phase2-intent-alignment-structural"))
    _require(parent.producer == "alignment" and parent.recovery["version"] in {36, 38}
        and parent.candidate["routing"]["verdict"] in {"ALIGNED", "DRIFT"}
        and parent.candidate["routing"]["state_updates"] == {})
    return parent


def require_alignment_gate_budget(root, run, state, parent, routing, config):
    """Authenticate native budgets and return the preceding alignment attempts."""
    from harness.discovery_completion import _retained_input_projection, _require, _json
    from harness.element_identity_store import IdentityStore
    if parent.recovery["version"] == 38:
        from harness.discovery_assessment import require_alignment_repair
        previous = require_alignment_repair(root, run, state,
            parent.recovery["source_completion"], parent.recovery["predecessor"])
        author = require_alignment_gate_parent(root, run, state, previous.recovery["source_completion"])
        require_alignment_gate_budget(root, run, state, author,
            previous.recovery["routing_state"], previous.recovery["config"])
        expected = {**previous.recovery["routing_state"],
            "iteration": previous.recovery["routing_state"]["iteration"] + 1,
            "intent_alignment_verdict": parent.candidate["routing"]["verdict"]}
        _require(_json(routing) == _json(expected) and _json(config) == _json(previous.recovery["config"]))
        return previous.recovery["result"]["state_updates"]["intent_alignment_check_structural_attempts"]
    store = IdentityStore.open(root)
    source = parent.recovery["source_completion"]
    strategy, _, _ = _retained_input_projection(root, run, state, store,
        operation_id="discovery-completion-" + source["dispatch_id"], source=source,
        require_checkpoint=False,
        required_route=("phase2-strategic-overview", "phase2-tracker-alignment"))
    _require(strategy.producer == "strategy" and strategy.recovery["version"] == 35)
    source = strategy.recovery["source_completion"]
    gate, _, _ = _retained_input_projection(root, run, state, store,
        operation_id="discovery-completion-" + source["dispatch_id"], source=source,
        require_checkpoint=False,
        required_route=("phase2-feasibility-structural", "phase2-strategic-overview"))
    _require(gate.producer == "feasibility_gate" and gate.recovery["version"] in {32, 34})
    expected = {**gate.recovery["routing_state"], **gate.recovery["result"]["state_updates"]}
    feasibility = {key: value for key, value in expected.items() if key.startswith("feasibility_")}
    _require(_json(routing) == _json(dict(iteration=expected["iteration"],
        max_iterations=expected["max_iterations"], intent_alignment_verdict=parent.candidate["routing"]["verdict"]))
        and _json({key: state.get(key) for key in feasibility}) == _json(feasibility)
        and _json(config) == _json(gate.recovery["config"]))
    return 0


@dataclass(frozen=True)
class PreparedAssessmentGate:
    publication: object
    sources: object
    request: object
    result: object


def decode_assessment_gate_binding(publication, request, recovery, completion_id, state):
    """Re-evaluate captured evidence and admit only exact report/graph writes."""
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
    alignment = recovery["version"] in {37, 39}
    artifact = "intent-alignment-check" if alignment else "feasibility"
    route_gate = alignment_gate_route if alignment else feasibility_gate_route
    _require(type(recovery["version"]) is int and recovery["version"] in {32, 34, 37, 39}
        and recovery["producer"] == ("alignment_gate" if alignment else "feasibility_gate") and not request.operations
        and type(recovery["completion_id"]) is str and re.fullmatch(r"[0-9a-f]{32}", recovery["completion_id"])
        and (completion_id is None or completion_id == recovery["completion_id"])
        and type(recovery["previous_attempts"]) is int and recovery["previous_attempts"] >= 0
        and ((recovery["version"] in {32, 37}) == (recovery["previous_attempts"] == 0)))
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
    prior_reports = [item for item in spec.files if item.path == spec.path + "/" + artifact + "-structural-report.json"]
    _require((recovery["version"] in {32, 37} and not prior_reports) or (recovery["version"] in {34, 39}
        and len(prior_reports) == 1 and json.loads(prior_reports[0].content).get("ok") is False))
    routing = recovery["routing_state"]
    gate, report = _evaluate_gate(artifact=artifact, sources=sources, root=root, spec_path=spec.path,
        config=recovery["config"], previous_attempts=recovery["previous_attempts"],
        iteration=routing["iteration"], max_iterations=routing["max_iterations"])
    # Python equality treats True == 1; the sealed JSON contract must not.
    _require(_json(recovery["result"]) == _json(_result(gate)))
    route_gate(routing, gate.state_updates())
    graph = _graph(sources, IdentityHistorySnapshot(**history), dict(spec_id=recovery["spec_id"], spec_path=spec.path))
    _require(hashlib.sha256(graph).hexdigest() == recovery["graph_sha256"])
    writes = {spec.path + "/spec-artifact-graph.json": graph}
    if report is not None:
        writes[spec.path + "/" + artifact + "-structural-report.json"] = (_json(report) + "\n").encode("ascii")
    modes = {item.path: item.image.mode for item in spec.files}
    operations = sources.publication.operations
    _require(len(operations) == len(writes) and {op.target for op in operations} == set(writes)
        and all(op.action == "write" and op.postimage_bytes == writes[op.target]
            and op.postimage.mode == modes.get(op.target, 0o644) for op in operations))
    if state is not None:
        selected = bootstrap_from_state(state)["selection"]
        _require(state["managed_identity"] == genesis and selected["spec_id"] == recovery["spec_id"]
            and selected["project_root"] == str(root) and selected["run_dir"] == str(run)
            and type(state.get("max_iterations")) is int and state["max_iterations"] == routing["max_iterations"])
    _require(_json(recovery) == request.recovery_payload)
    return DiscoveryCompletionBinding(request, recovery, dict(history=history, artifacts={}),
        dict(history=history, authority=authority, runtime=recovery["runtime"]), sources, baseline)


def authenticate_feasibility_gate(root, run, state, completion, binding):
    from harness.config import get_full_resolved_config
    from harness.discovery_completion import _require, _json
    parent = require_feasibility_gate_parent(root, run, state, binding.recovery["source_completion"])
    _require(binding.recovery["version"] == (32 if parent.recovery["version"] == 31 else 34)
        and binding.recovery["previous_attempts"] == prior_feasibility_attempts(root, run, state,
            parent, binding.recovery["routing_state"], binding.recovery["config"]))
    _require(get_full_resolved_config(root) == binding.recovery["config"])
    updates, routing = binding.recovery["result"]["state_updates"], binding.recovery["routing_state"]
    _require(_json({key: state.get(key) for key in updates}) == _json(updates)
        and state.get("feasibility_verdict") == routing["feasibility_verdict"])
    route = feasibility_gate_route(routing, updates)
    _require(completion.intent.route["to_phase"] == route
        and type(state.get("iteration")) is int
        and state.get("iteration", 0) == routing["iteration"] + int(route == "phase2-decide"))


def authenticate_alignment_gate(root, run, state, completion, binding):
    from harness.config import get_full_resolved_config
    from harness.discovery_completion import _require, _json
    parent = require_alignment_gate_parent(root, run, state, binding.recovery["source_completion"])
    routing, updates = binding.recovery["routing_state"], binding.recovery["result"]["state_updates"]
    _require(binding.recovery["version"] == (37 if parent.recovery["version"] == 36 else 39)
        and binding.recovery["previous_attempts"] == require_alignment_gate_budget(root, run, state,
            parent, routing, binding.recovery["config"]))
    _require(_json(get_full_resolved_config(root)) == _json(binding.recovery["config"])
        and _json({key: state.get(key) for key in updates}) == _json(updates)
        and state.get("intent_alignment_verdict") == routing["intent_alignment_verdict"])
    route = alignment_gate_route(routing, updates)
    _require(completion.intent.route["to_phase"] == route
        and type(state.get("iteration")) is int
        and state["iteration"] == routing["iteration"] + int(route == "phase2-tracker-alignment"))


def prepare_feasibility_gate_publication(root, state_store, *, completion_id, max_iterations):
    return _prepare_gate_publication(root, state_store, completion_id=completion_id,
        max_iterations=max_iterations, alignment=False)


def prepare_alignment_gate_publication(root, state_store, *, completion_id, max_iterations):
    return _prepare_gate_publication(root, state_store, completion_id=completion_id,
        max_iterations=max_iterations, alignment=True)


def _prepare_gate_publication(root, state_store, *, completion_id, max_iterations, alignment):
    """Seal one report-only handoff, without a provider call or state mutation."""
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
    artifact = "intent-alignment-check" if alignment else "feasibility"
    prefix = "intent_alignment_check_structural" if alignment else "feasibility_structural"
    verdict_key = "intent_alignment_verdict" if alignment else "feasibility_verdict"
    phase = "phase2-intent-alignment-structural" if alignment else "phase2-feasibility-structural"
    route_gate = alignment_gate_route if alignment else feasibility_gate_route
    _require(state["phase"] == phase and state["status"] == "running"
        and not state.get("cancel_requested") and type(state.get("max_iterations")) is int
        and state["max_iterations"] > 0 and state["max_iterations"] == max_iterations
        and type(state.get(prefix + "_attempts", 0)) is int
        and state.get(prefix + "_attempts", 0) >= 0
        and not any(key in state for key in ("pending_controller_completion", "pending_external_publication", "product_input_mutation", "governance")))
    selection = bootstrap_from_state(state)["selection"]
    source = {key: state["last_dispatch"][key] for key in SOURCE_FIELDS}
    if alignment:
        _require(state["last_dispatch"].get("phase_id") == "phase2-tracker-alignment"
            and state["last_dispatch"].get("post_dispatch_complete") is True)
    parent = (require_alignment_gate_parent if alignment else require_feasibility_gate_parent)(root, run, state, source)
    config = get_full_resolved_config(root)
    routing = dict(iteration=state.get("iteration", 0), max_iterations=state["max_iterations"],
        **{verdict_key: state.get(verdict_key)})
    previous = (require_alignment_gate_budget if alignment else prior_feasibility_attempts)(
        root, run, state, parent, routing, config)
    _require(state.get(prefix + "_attempts", 0) == previous)
    project_spec, project_context = released_discovery_input_projectors(root, run, state, source=source)
    capture = load_prepared_publication(root, run, selection["capture_marker"])
    with capture.inspect_sources(tree_paths=tuple(tree.path for tree in parent.sources.trees),
            file_paths=tuple(item.path for item in parent.sources.files)) as before:
        spec, = (tree for tree in before.trees if tree.path == selection["spec_path"])
        project_spec(spec)
        runtime, _ = admit_runtime_inputs(root, run, state, project_context(before))
    gate, report = _evaluate_gate(artifact=artifact, sources=before, root=root, spec_path=spec.path,
        config=config, previous_attempts=previous, iteration=routing["iteration"], max_iterations=routing["max_iterations"])
    route_gate(routing, gate.state_updates())
    store = IdentityStore.open(root)
    authority = store.check_managed_context(spec_id=selection["spec_id"], run_id=state["run_id"], record=state["managed_identity"])
    history = store.identity_history(spec_id=selection["spec_id"])
    writes = {} if report is None else {spec.path + "/" + artifact + "-structural-report.json": (_json(report) + "\n").encode("ascii")}
    modes = {item.path: item.image.mode for item in spec.files}
    provisional = _seal(root, run, writes, modes)
    try:
        projected = _inspect(provisional, before, writes, modes)
        graph = _graph(projected, history, selection)
        writes[spec.path + "/spec-artifact-graph.json"] = graph
        publication = _seal(root, run, writes, modes)
        sources = _inspect(publication, before, writes, modes)
        baseline = PublicationSourcesSnapshot(sources.publication, (identity_spec_tree(spec),), ())
        recovery = dict(version=(37 if parent.recovery["version"] == 36 else 39) if alignment
            else 32 if parent.recovery["version"] == 31 else 34,
            producer="alignment_gate" if alignment else "feasibility_gate", completion_id=completion_id,
            source_completion=source, spec_id=selection["spec_id"], sources=encode_initial_publication_sources(sources),
            history=asdict(history), authority=authority, runtime=runtime, config=config,
            result=_result(gate), previous_attempts=previous, project_root=str(root), run_dir=str(run),
            graph_sha256=hashlib.sha256(graph).hexdigest(), routing_state=routing)
        request = PublicationIntentRequest(publication.marker.manifest_sha256, _json(recovery), (),
            PublicationSourceClaim(authority["source_context"]["context_id"], authority["source_context"]["operation_id"],
                encode_initial_publication_sources(baseline)), proposed_history_sha256=history.sha256)
        decode_assessment_gate_binding(dict(kind="external", marker=publication.marker.to_dict()), request, recovery, completion_id, state)
        _require(state_store.load() == state and get_full_resolved_config(root) == config
            and store.identity_history(spec_id=selection["spec_id"]) == history)
    finally:
        provisional.discard()
    return PreparedAssessmentGate(publication, sources, request, SquadAgentResult(exit_code=0,
        echelon_result=recovery["result"], raw_output=str(gate.report_path or gate.detail), duration_ms=0, timed_out=False))
