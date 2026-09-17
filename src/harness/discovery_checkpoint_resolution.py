"""Associate the existing Phase 1 human gate with managed completion proof.

No provider, recommendation policy, decision journal or Phase 2 dispatch lives
here. Native Squad owns the sealed decision and its resolution effects.
"""
from dataclasses import asdict, replace
from pathlib import Path
import hashlib
import re


def supported_decision(decision):
    return (type(decision) is dict and decision.get("source_kind") == "human_gate"
        and decision.get("producer_id") == decision.get("source_phase") == "checkpoint-assess"
        and decision.get("reason_code") == "checkpoint_assess_decision_required"
        and decision.get("resolution_handler") == "gate_outcome")


def policy_payload(policy):
    value = asdict(policy)
    for key in ("allowed_phase_ids", "allowed_target_phases"):
        value[key] = sorted(value[key])
    for key in ("context_state_keys", "context_paths", "options"):
        value[key] = list(value[key])
    return value


def policy_from_payload(value):
    from harness.discovery_completion import _require, _closed
    from harness.human_input import HumanInputPolicy, HumanInputOption
    _closed(value, ("source_kind", "producer_id", "reason_code", "classification", "semi_policy",
        "resolution_handler", "allow_free_text", "allowed_phase_ids", "allowed_target_phases",
        "context_state_keys", "context_paths", "options", "recommendation_mode"))
    policy = HumanInputPolicy(**{**value, "options": tuple(HumanInputOption(**item) for item in value["options"])})
    _require(policy_payload(policy) == value and policy.source_kind == "human_gate"
        and policy.producer_id == "checkpoint-assess" and policy.reason_code == "checkpoint_assess_decision_required"
        and policy.classification == "material" and policy.semi_policy == "require_human"
        and policy.resolution_handler == "gate_outcome" and policy.recommendation_mode == "controller"
        and policy.allow_free_text is False and policy.allowed_phase_ids == {"checkpoint-assess"}
        and policy.allowed_target_phases == {"phase2-decide", "terminal-blocked"}
        and {(item.id, item.outcome, item.next_phase) for item in policy.options}
        == {("approve", "approved", "phase2-decide"), ("reject", "rejected", "terminal-blocked")})
    return policy


def require_checkpoint_parent(root, run, state, source):
    from harness.config import get_full_resolved_config
    from harness.discovery_completion import _retained_input_projection, _require
    from harness.element_identity_store import IdentityStore
    from harness.phase1_quality import has_current_phase1_quality_certificate
    from harness.phase1_quality_debt import has_current_quality_debt_authorization
    from harness.spec_lexicon_gate import has_current_spec_lexicon_evidence
    parent, _, _ = _retained_input_projection(root, run, state, IdentityStore.open(root),
        operation_id="discovery-completion-" + source["dispatch_id"], source=source, require_checkpoint=False)
    config = get_full_resolved_config(root)
    gate = config["lexicon_gate"]
    enabled = bool(gate.get("enabled", False) and gate.get("artifacts", {}).get("spec", {}).get("enabled", True) is not False)
    if enabled:
        _require(parent.producer == "lexicon_gate" and parent.recovery["result"]["state_updates"]["lexicon_pass"] is True
            and has_current_spec_lexicon_evidence(state, project_root=root, config=config))
        route = ("phase1-lexicon", "checkpoint-assess")
    elif parent.recovery["version"] == 27:
        _require(parent.candidate["route"] == "checkpoint-assess"
            and parent.recovery["resolution"]["selected_option_id"] == "continue_with_debt")
        route = (parent.recovery["from_phase"], "checkpoint-assess")
    else:
        _require(parent.producer == "why2" and not parent.resolution_publication
            and parent.candidate["routing"]["verdict"] == "PASS")
        route = ("phase1-why2", "checkpoint-assess")
    _retained_input_projection(root, run, state, IdentityStore.open(root),
        operation_id=parent.operation_id, source=source, require_checkpoint=False, required_route=route,
        required_origin="resolution" if parent.resolution_publication else "routed")
    _require(has_current_phase1_quality_certificate(state, project_root=root)
        or has_current_quality_debt_authorization(state, project_root=root))
    return parent


def require_native_choice(root, before, decision, policy):
    from harness.discovery_completion import _require
    from harness.discovery_policy_resolution import require_native_decision
    from harness.human_input import HumanInputPolicyRegistry, AppliedHumanInputResolution
    from harness.squad import SquadController
    reader = object.__new__(SquadController)
    reader._project_root, reader._gate_config_cache = Path(root), None
    reader._human_input_registry = HumanInputPolicyRegistry((policy,))
    _require(before["phase"] == "checkpoint-assess" and before["autonomy_mode"] == decision["autonomy_mode"])
    prepared = reader._prepare_checkpoint_assessment_decision(before, question=decision["question"],
        source_state_revision=decision["source_state_revision"])
    require_native_decision(prepared, decision)
    resolution = AppliedHumanInputResolution(decision["selected_option_id"], decision["answer_text"], decision["resolved_by"],
        rationale=decision["resolution_rationale"], confidence=decision["resolution_confidence"])
    reader._validate_human_input_resolver(before["blocked_decision"], resolution)
    reader._validate_human_input_resolution_answer(before["blocked_decision"], resolution)


def state_effects(decision):
    from harness.blocked_decision import validate_blocked_decision
    from harness.discovery_completion import _require
    _require(validate_blocked_decision(decision) == decision and supported_decision(decision)
        and decision["status"] == "resolved" and decision["selected_option_id"] in {"approve", "reject"}
        and decision["answer_text"] is None and decision["resolved_by"] in {"user", "COMMANDER"}
        and (decision["resolved_by"] != "COMMANDER" or decision["autonomy_mode"] == "banzai"))
    approved = decision["selected_option_id"] == "approve"
    route = "phase2-decide" if approved else "terminal-blocked"
    updates = dict(phase=route, status="running" if approved else "blocked")
    if not approved:
        updates["blocked_reason"] = "gate_rejected"
    return dict(route=route, state_updates=updates, state_removals=[])


def prepare(controller, state, decision, selected, resolution, effects, *, token_usage_delta=0):
    from datetime import datetime, timezone
    import uuid
    from harness.discovery_completion import _require, _json, released_discovery_input_projectors
    from harness.discovery_spec import current_spec_source
    from harness.discovery_inputs import admit_runtime_inputs
    from harness.discovery_producer import identity_spec_tree
    from harness.element_identity_store import IdentityStore
    from harness.element_identity_publication import PublicationIntentRequest, PublicationSourceClaim, encode_publication_request
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_snapshot import PublicationSourcesSnapshot
    from harness.squad_source_baseline_codec import encode_initial_publication_sources
    from harness.squad_state import build_human_input_resolution_postimage
    root, run = controller._project_root, controller._squad_dir
    source = current_spec_source(root, state, "checkpoint")
    parent = require_checkpoint_parent(root, run, state, source)
    project_spec, project_context = released_discovery_input_projectors(root, run, state, source=source)
    policy = controller._policy_for_human_input_decision(decision)
    policy_from_payload(policy_payload(policy))
    resolved_at = datetime.now(timezone.utc).isoformat()
    resolved = build_human_input_resolution_postimage(decision, resolution, resolved_at=resolved_at)
    payload = state_effects(resolved)
    _require(effects.completion is None and effects.resolved_at is None and effects.resolved_decision_postimage is None
        and effects.state_updates == payload["state_updates"] and not effects.state_removals and effects.route == payload["route"])
    require_native_choice(root, state, resolved, policy)
    from harness.managed_commander import resolution_receipt
    commander = resolution_receipt(run, state, resolved, policy)
    _require(token_usage_delta == (commander["token_usage"] if commander is not None else 0))
    completion_id = uuid.uuid4().hex
    publication = SquadPublicationTransaction.begin(root, run, completion_id).seal()
    with publication.inspect_sources(tree_paths=tuple(tree.path for tree in parent.sources.trees),
            file_paths=tuple(item.path for item in parent.sources.files)) as sources:
        spec, = (tree for tree in sources.trees if tree.path == state["managed_identity"]["spec_path"])
        project_spec(spec)
        runtime, _ = admit_runtime_inputs(root, run, state, project_context(sources))
    store = IdentityStore.open(root)
    authority = store.check_managed_context(spec_id=parent.spec_id, run_id=state["run_id"], record=state["managed_identity"])
    history = store.identity_history(spec_id=parent.spec_id)
    baseline = PublicationSourcesSnapshot(sources.publication, (identity_spec_tree(spec),), ())
    recovery = dict(version=30, producer="checkpoint", completion_id=completion_id, spec_id=parent.spec_id,
        source_completion=source, before=state, resolution=resolved, effects=payload, policy=policy_payload(policy),
        history=asdict(history), authority=authority, runtime=runtime, sources=encode_initial_publication_sources(sources),
        commander_receipt=commander)
    request = PublicationIntentRequest(publication.marker.manifest_sha256, _json(recovery), (),
        PublicationSourceClaim(authority["source_context"]["context_id"], authority["source_context"]["operation_id"],
            encode_initial_publication_sources(baseline)), proposed_history_sha256=history.sha256)
    decode_binding(dict(kind="external", marker=publication.marker.to_dict()), request, recovery, completion_id, state)
    snapshot = controller._state_store.capture_routing_snapshot(expected_phase="checkpoint-assess")
    _require(snapshot.state == state)
    completion = controller._prepare_controller_completion(from_phase="checkpoint-assess", to_phase=effects.route,
        snapshot=snapshot, manual_phase_run=False, conditional_skip=False, record_completion=True,
        publication_marker=publication.marker.to_dict(), origin="resolution", resolution_decision_id=decision["id"],
        completion_id=completion_id, managed_discovery_request=encode_publication_request(request))
    return replace(effects, completion=completion, resolved_at=resolved_at, resolved_decision_postimage=resolved)


def decode_binding(publication, request, recovery, completion_id, state):
    from harness.discovery_completion import _require, _closed, _json, DiscoveryCompletionBinding
    from harness.discovery_bootstrap_state import bootstrap_from_state
    from harness.discovery_producer import SOURCE_FIELDS, identity_spec_tree
    from harness.squad_source_baseline_codec import decode_initial_publication_sources
    from harness.squad_source_manifest import snapshot_source_manifest
    from harness.squad_state import build_human_input_resolution_postimage
    from harness.human_input import AppliedHumanInputResolution
    _closed(recovery, ("version", "producer", "completion_id", "spec_id", "source_completion", "before",
        "resolution", "effects", "policy", "history", "authority", "runtime", "sources", "commander_receipt"))
    _require(type(recovery["version"]) is int and recovery["version"] == 30 and recovery["producer"] == "checkpoint"
        and not request.operations and request.continuation is None and request.continuation_id is None
        and type(recovery["completion_id"]) is str and re.fullmatch(r"[0-9a-f]{32}", recovery["completion_id"])
        and (completion_id is None or completion_id == recovery["completion_id"]) and _json(recovery) == request.recovery_payload)
    before, resolved = recovery["before"], recovery["resolution"]
    commander = recovery["commander_receipt"]
    if resolved["resolved_by"] == "COMMANDER":
        _closed(commander, ("sha256", "token_usage"))
        _require(type(commander["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", commander["sha256"])
            and type(commander["token_usage"]) is int and commander["token_usage"] >= 0)
    else:
        _require(commander is None)
    _require(state_effects(resolved) == recovery["effects"])
    policy_from_payload(recovery["policy"])
    answer = AppliedHumanInputResolution(resolved["selected_option_id"], resolved["answer_text"], resolved["resolved_by"],
        rationale=resolved["resolution_rationale"], confidence=resolved["resolution_confidence"])
    _require(before["phase"] == "checkpoint-assess" and before["autonomy_mode"] == resolved["autonomy_mode"]
        and build_human_input_resolution_postimage(before["blocked_decision"], answer, resolved_at=resolved["resolved_at"]) == resolved)
    source = recovery["source_completion"]
    _closed(source, SOURCE_FIELDS)
    _require(all(type(value) is str and re.fullmatch(r"[0-9a-f]{%d}" % (32 if key == "dispatch_id" else 64), value)
        for key, value in source.items()))
    history, authority = recovery["history"], recovery["authority"]
    _closed(history, ("payload", "sha256"))
    _require(hashlib.sha256(history["payload"].encode("ascii")).hexdigest() == history["sha256"] == request.proposed_history_sha256)
    sources = decode_initial_publication_sources(recovery["sources"])
    baseline = decode_initial_publication_sources(request.sources.baseline_payload)
    genesis = authority["managed_identity"]
    spec, = (tree for tree in sources.trees if tree.path == genesis["spec_path"])
    _require(not sources.publication.operations and sources.publication.promoted_prefix == 0
        and sources.publication == baseline.publication and baseline.trees == (identity_spec_tree(spec),) and not baseline.files
        and sources.publication.marker.to_dict() == publication["marker"]
        and request.manifest_sha256 == sources.publication.marker.manifest_sha256
        and request.sources.context_id == genesis["context_id"] == authority["source_context"]["context_id"]
        and request.sources.expected_operation_id == authority["source_context"]["operation_id"]
        == "discovery-completion-" + source["dispatch_id"]
        and asdict(snapshot_source_manifest(trees=baseline.trees, files=())) == authority["source_context"]["manifest"])
    selection = bootstrap_from_state(before)["selection"]
    _require(before["managed_identity"] == genesis and recovery["spec_id"] == selection["spec_id"])
    if state is not None:
        _require(state["managed_identity"] == genesis and bootstrap_from_state(state) == bootstrap_from_state(before))
        if state["blocked_decision"] == resolved:
            from harness.discovery_policy_resolution import _require_resolved_effects
            _require_resolved_effects(state, recovery, publication)
            _require(state["token_usage"] >= before["token_usage"] + (commander["token_usage"] if commander else 0))
        else:
            _require(state == before)
    return DiscoveryCompletionBinding(request, recovery, dict(history=history, artifacts={}, route=recovery["effects"]["route"]),
        dict(history=history, authority=authority, runtime=recovery["runtime"]), sources, baseline)


def require_parent(root, run, state, binding):
    from harness.discovery_completion import _require
    from harness.discovery_spec import current_spec_source
    before = binding.recovery["before"]
    source = binding.recovery["source_completion"]
    # The saved source is bound to the released ancestry and exact snapshot;
    # the source head may now be this resolution during completion/replay.
    from harness.discovery_producer import SOURCE_FIELDS
    from harness.discovery_spec import clarification_source
    _require(source in ({key: before["last_dispatch"][key] for key in SOURCE_FIELDS},
        clarification_source(before["last_human_input_completion"]) if before.get("last_human_input_completion") else None))
    require_checkpoint_parent(root, run, before, source)
    require_native_choice(root, before, binding.recovery["resolution"], policy_from_payload(binding.recovery["policy"]))
    from harness.managed_commander import resolution_receipt
    _require(resolution_receipt(run, before, binding.recovery["resolution"], policy_from_payload(binding.recovery["policy"]))
        == binding.recovery["commander_receipt"])


def require_receipt(state, binding, marker):
    from harness.discovery_completion import _require
    _require(state.get("last_human_input_completion") == dict(schema_version=1,
        decision_id=binding.recovery["resolution"]["id"], completion_id=marker.completion_id,
        intent_sha256=marker.intent_sha256, receipts_sha256=marker.receipts_sha256,
        publication_binding_sha256=marker.publication_binding_sha256))
