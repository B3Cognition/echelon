"""Detached contracts for native WHY2 policy resolutions.

These checks grant no decision, route or publication authority. Native handlers
remain the effect owners; their source proof and completion must be bound before
managed execution may use a payload from this module.
"""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path


_BEFORE_KEYS = ("spec_authoring_mode", "phase1_quality_repair", "proportional_quality_candidate_evidence",
    "understanding_evidence", "product_input_mapping_repair")
_RESET_BEFORE_KEYS = (*_BEFORE_KEYS, "quality_scores", "why_fail_count", "why2_metric_stagnation_count", "why_failure_baseline")
_ISSUE_BEFORE_KEYS = (*_BEFORE_KEYS, "autonomy_mode", "spec_dir", "issue_resolution_ledger", "selected_issue_resolution")


def _before_keys(reset, state, issue=False):
    keys = _ISSUE_BEFORE_KEYS if issue else _RESET_BEFORE_KEYS if reset else _BEFORE_KEYS
    # Native perfectionist policy rejects even a null proportional budget.
    # Its absence must survive the detached prestate capture.
    if reset and state.get("spec_authoring_mode") == "perfectionist":
        if "phase1_quality_repair" in state:
            raise ValueError("perfectionist reset cannot contain proportional repair state")
        return tuple(key for key in keys if key != "phase1_quality_repair")
    return keys


def supported_decision(decision):
    """A narrow shape check, not admission or a substitute for parent proof."""
    return (type(decision) is dict and decision.get("source_phase") == "phase1-why2"
        and decision.get("source_kind") == "controller_safeguard"
        and decision.get("producer_id") == decision.get("reason_code")
        and decision.get("reason_code") in {"proportional_quality_budget_exhausted", "proportional_quality_extension_exhausted"}
        and decision.get("resolution_handler") == "proportional_quality_debt")


def supported_reset_decision(decision):
    reasons = {"consecutive_why_fails": "reset_why_fail_count", "why2_metric_stagnation": "reset_why2_stagnation"}
    return (type(decision) is dict and decision.get("source_phase") == "phase1-why2"
        and decision.get("source_kind") == "controller_safeguard"
        and decision.get("producer_id") == decision.get("reason_code") and decision.get("reason_code") in reasons
        and decision.get("resolution_handler") == reasons[decision["reason_code"]])


def require_reset_resolved(decision):
    from harness.blocked_decision import validate_blocked_decision
    from harness.discovery_completion import _require
    _require(validate_blocked_decision(decision) == decision and supported_reset_decision(decision)
        and decision["status"] == "resolved" and decision["selected_option_id"] is None
        and type(decision["answer_text"]) is str and bool(decision["answer_text"].strip()))


def resolution_associations(state):
    from harness.discovery_producer import tracker_rounds
    from harness.discovery_issue_resolution import supported_decision as issue_decision
    result = []
    for producer in ("what", "why2"):
        rounds = tracker_rounds(state, producer)
        for row in (() if rounds is None else rounds["rounds"].values()):
            association = row.get("review_resolution", row["resolution"])
            if association is not None and (supported_decision(association["decision"]) or supported_reset_decision(association["decision"]) or issue_decision(association["decision"])):
                result.append((row, association))
    return tuple(result)


def require_resolved(decision, *, debt=False):
    from harness.blocked_decision import validate_blocked_decision
    from harness.discovery_completion import _require
    _require(validate_blocked_decision(decision) == decision and supported_decision(decision)
        and decision["status"] == "resolved" and decision["selected_option_id"] in (
            {"continue_with_debt", "stop"} if debt else {"extend_once"})
        and decision["answer_text"] is None)


def require_native_decision(prepared, decision):
    """Compare native immutable fields without changing the sealed decision."""
    from harness.blocked_decision import build_blocked_decision_v3
    from harness.discovery_completion import _require
    # This detached comparison grants no automatic eligibility. Human-only
    # safeguards cannot be represented as pending automatic decisions.
    derived = build_blocked_decision_v3(prepared=prepared, decision_id=decision["id"], status="awaiting_human",
        autonomy_mode=decision["autonomy_mode"], created_at=decision["created_at"])
    changing = {"status", "attempts", "failure_code", "selected_option_id", "answer_text", "resolved_by",
        "resolved_at", "resolution_rationale", "resolution_confidence", "recommendation_followed", "override_reason"}
    _require({key: value for key, value in derived.items() if key not in changing}
        == {key: value for key, value in decision.items() if key not in changing})


def prepare(controller, state, decision, selected, resolution, effects, *, quality_effect=None,
        completion_id=None, resolved_at=None, resolved=None):
    """Wrap a native state-only choice in the existing publication/completion."""
    from datetime import datetime, timezone
    import uuid
    from dataclasses import replace
    from harness.discovery_bootstrap_state import bootstrap_from_state
    from harness.discovery_completion import _require, _json, released_discovery_input_projectors, _retained_input_projection
    from harness.discovery_inputs import admit_runtime_inputs
    from harness.discovery_producer import SOURCE_FIELDS, identity_spec_tree
    from harness.element_identity_publication import PublicationIntentRequest, PublicationSourceClaim, encode_publication_request
    from harness.element_identity_store import IdentityStore
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_baseline_codec import encode_initial_publication_sources
    from harness.squad_source_snapshot import PublicationSourcesSnapshot
    from harness.squad_state import build_human_input_resolution_postimage
    from harness.discovery_issue_resolution import supported_decision as issue_decision, require_issue_effects
    reset, issue = supported_reset_decision(decision), issue_decision(decision)
    debt = quality_effect is not None
    _require((reset and selected is None) or (issue and selected is not None)
        or (supported_decision(decision) and selected is not None and selected.id in (
            {"continue_with_debt", "stop"} if debt else {"extend_once"})))
    if debt:
        from harness.discovery_debt_resolution import state_effects
        _require(completion_id is not None and resolved_at is not None and resolved is not None)
        payload = state_effects(resolved, effects, quality_effect)
    else:
        payload = state_only_effects(state, decision, selected, effects)
    root, run = controller._project_root, controller._squad_dir
    source = {key: state["last_dispatch"][key] for key in SOURCE_FIELDS}
    store = IdentityStore.open(root)
    parent, _, _ = _retained_input_projection(root, run, state, store,
        operation_id="discovery-completion-" + source["dispatch_id"], source=source, require_checkpoint=False)
    _require(parent.producer == "why2" and not parent.clarification)
    # Reuse the native recommendation owner, but not its newly prepared restore
    # effect. The already released parent's effect remains the only authority.
    if issue:
        require_issue_effects(controller, state, decision, selected.id, parent, payload)
    elif reset:
        from harness.human_input import why2_safeguard_question
        count = state["why2_metric_stagnation_count" if decision["reason_code"] == "why2_metric_stagnation" else "why_fail_count"]
        prepared = controller._human_input_registry.prepare(source_kind="controller_safeguard",
            producer_id=decision["producer_id"], phase_id="phase1-why2", reason_code=decision["reason_code"],
            question=why2_safeguard_question(decision["reason_code"], count), source_state_revision=decision["source_state_revision"])
    else:
        prepared, evidence = controller._prepare_proportional_quality_decision(state,
            repair_state=state["phase1_quality_repair"], reason_code=decision["reason_code"],
            source_state_revision=decision["source_state_revision"],
            last_repair_outcome=state["proportional_quality_candidate_evidence"]["last_repair_outcome"])
    if not issue:
        require_native_decision(prepared, decision)
    if not reset and not issue:
        _require(evidence["proportional_quality_candidate_evidence"] == state["proportional_quality_candidate_evidence"]
            and evidence["understanding_evidence"] == state["understanding_evidence"])
    project_spec, project_context = released_discovery_input_projectors(root, run, state, source=source)
    completion_id = completion_id or uuid.uuid4().hex
    if debt:
        from harness.discovery_debt_resolution import publication as debt_publication
        publication = debt_publication(root, run, completion_id, quality_effect)
    else:
        publication = SquadPublicationTransaction.begin(root, run, completion_id).seal()
    with publication.inspect_sources(tree_paths=tuple(tree.path for tree in parent.sources.trees),
            file_paths=tuple(item.path for item in parent.sources.files)) as sources:
        spec, = (tree for tree in sources.trees if tree.path == state["managed_identity"]["spec_path"])
        project_spec(spec)
        runtime, _ = admit_runtime_inputs(root, run, state, project_context(sources))
    authority = store.check_managed_context(spec_id=parent.spec_id, run_id=state["run_id"], record=state["managed_identity"])
    history = store.identity_history(spec_id=parent.spec_id)
    baseline = PublicationSourcesSnapshot(sources.publication, (identity_spec_tree(spec),), ())
    resolved_at = resolved_at or datetime.now(timezone.utc).isoformat()
    resolved = resolved or build_human_input_resolution_postimage(decision, resolution, resolved_at=resolved_at)
    recovery = dict(version=27 if debt else 25 if issue else 23 if reset else 21, producer="why2-policy", completion_id=completion_id,
        operation=parent.recovery["operation"], source_completion=source, resolution=resolved,
        before={key: deepcopy(state.get(key)) for key in _before_keys(reset, state, issue)}, effects=payload, from_phase=state["phase"],
        history=asdict(history), authority=authority, runtime=runtime, sources=encode_initial_publication_sources(sources))
    if debt:
        recovery["quality_effect"] = quality_effect
    request = PublicationIntentRequest(publication.marker.manifest_sha256, _json(recovery), (),
        PublicationSourceClaim(authority["source_context"]["context_id"], authority["source_context"]["operation_id"],
            encode_initial_publication_sources(baseline)), proposed_history_sha256=history.sha256)
    binding = decode_policy_binding(dict(kind="external", marker=publication.marker.to_dict()), request, recovery, completion_id, state)
    require_parent(root, run, state, binding, store)
    snapshot = controller._state_store.capture_routing_snapshot(expected_phase=state["phase"])
    _require(snapshot.state == state and bootstrap_from_state(state) is not None)
    completion = controller._prepare_controller_completion(from_phase=state["phase"], to_phase=effects.route,
        snapshot=snapshot, manual_phase_run=False, conditional_skip=False, record_completion=True,
        publication_marker=publication.marker.to_dict(), origin="resolution", resolution_decision_id=decision["id"],
        completion_id=completion_id, managed_discovery_request=encode_publication_request(request), quality_effect=quality_effect)
    return replace(effects, completion=completion, resolved_at=resolved_at, resolved_decision_postimage=resolved)


def _require_resolved_effects(state, recovery, publication):
    """Check effects through native pending-publication/completion failures."""
    from harness.discovery_completion import _require
    from harness.squad_state import SquadStateStore
    observed = dict(state)
    for key in ("external_publication_failure", "controller_completion_failure"):
        if key not in observed:
            continue
        _require((state.get("pending_controller_completion") or {}).get("completion_id") == recovery["completion_id"])
        if key == "external_publication_failure":
            _require(state.get("pending_external_publication") == publication["marker"])
        SquadStateStore._restore_failure_lifecycle(observed, diagnostic_key=key)
    payload = recovery["effects"]
    _require(all(observed.get(key) == value for key, value in payload["state_updates"].items())
        and not any(key in observed for key in payload["state_removals"]))


def decode_policy_binding(publication, request, recovery, completion_id, state):
    import hashlib
    import re
    from harness.discovery_completion import _require, _closed, _json, DiscoveryCompletionBinding
    from harness.discovery_bootstrap_state import bootstrap_from_state
    from harness.discovery_operation_state import operation_from_state
    from harness.discovery_producer import SOURCE_FIELDS, identity_spec_tree
    from harness.squad_source_baseline_codec import decode_initial_publication_sources
    from harness.squad_source_manifest import snapshot_source_manifest
    _closed(recovery, ("version", "producer", "completion_id", "operation", "source_completion", "resolution",
        "before", "effects", "from_phase", "history", "authority", "runtime", "sources",
        *(("quality_effect",) if recovery.get("version") == 27 else ())))
    _require(type(recovery["version"]) is int and recovery["version"] in {21, 23, 25, 27} and recovery["producer"] == "why2-policy"
        and not request.operations and request.continuation is None and request.continuation_id is None
        and type(recovery["completion_id"]) is str and re.fullmatch(r"[0-9a-f]{32}", recovery["completion_id"])
        and (completion_id is None or completion_id == recovery["completion_id"]) and _json(recovery) == request.recovery_payload)
    from harness.discovery_issue_resolution import require_resolved as require_issue_resolved
    reset, issue = recovery["version"] == 23, recovery["version"] == 25
    debt = recovery["version"] == 27
    if debt:
        require_resolved(recovery["resolution"], debt=True)
    else:
        (require_issue_resolved if issue else require_reset_resolved if reset else require_resolved)(recovery["resolution"])
    before_keys = _before_keys(reset, recovery["before"], issue)
    _closed(recovery["before"], before_keys)
    _closed(recovery["effects"], ("route", "state_updates", "state_removals"))
    _require(recovery["from_phase"] in {"phase1-why2", "terminal-blocked"})
    from types import SimpleNamespace
    from harness.squad import _HumanInputResolutionEffects
    payload = recovery["effects"]
    selected = None if reset else SimpleNamespace(id="extend_once")
    if issue:
        option, = (option for option in recovery["resolution"]["options"] if option["id"] == recovery["resolution"]["selected_option_id"])
        selected = SimpleNamespace(id=option["id"], next_phase=option["next_phase"])
    effects = _HumanInputResolutionEffects(payload["state_updates"], frozenset(payload["state_removals"]), payload["route"])
    if debt:
        from harness.discovery_debt_resolution import state_effects
        _require(state_effects(recovery["resolution"], effects, recovery["quality_effect"]) == payload)
    else:
        _require(state_only_effects(recovery["before"], recovery["resolution"], selected, effects) == payload)
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
    _require((debt or not sources.publication.operations) and sources.publication.promoted_prefix == 0
        and sources.publication == baseline.publication and baseline.trees == (identity_spec_tree(spec),) and not baseline.files
        and sources.publication.marker.to_dict() == publication["marker"]
        and request.manifest_sha256 == sources.publication.marker.manifest_sha256
        and request.sources.context_id == genesis["context_id"] == authority["source_context"]["context_id"]
        and request.sources.expected_operation_id == authority["source_context"]["operation_id"]
        and asdict(snapshot_source_manifest(trees=baseline.trees, files=())) == authority["source_context"]["manifest"])
    if state is not None:
        selected = recovery["operation"]["binding"]
        _require(bootstrap_from_state(state) is not None and state["managed_identity"] == genesis
            and operation_from_state(state, "why2", operation_id=selected["operation_id"]) == recovery["operation"])
        associations = resolution_associations(state)
        matches = [(row, item) for row, item in associations if item["decision"]["id"] == recovery["resolution"]["id"]]
        if matches:
            (row, association), = matches
            from harness.discovery_spec import clarification_source
            _require(association["decision"] == recovery["resolution"]
                and association["completion"]["completion_id"] == recovery["completion_id"]
                and row["source"] == clarification_source(association["completion"])
                and row.get("review_parent", row["predecessor"]) == selected["operation_id"])
        elif debt and (state.get("last_human_input_completion") or {}).get("completion_id") == recovery["completion_id"]:
            # After release, native debt authority follows its frozen resolution
            # receipt, not whichever phase/dispatch/decision is currently active.
            # Retained authentication below must match the complete receipt.
            from harness.discovery_spec import clarification_source
            receipt = state["last_human_input_completion"]
            _require(clarification_source(receipt)["dispatch_id"] == recovery["completion_id"]
                and receipt["decision_id"] == recovery["resolution"]["id"])
        elif debt and state.get("spec_quality_debt_authorization") == recovery["quality_effect"]["payload"].get("authorization"):
            from harness.discovery_debt_resolution import retained_debt_receipt
            authorization = state["spec_quality_debt_authorization"]
            _require(authorization["resolved_decision"] == recovery["resolution"]
                and retained_debt_receipt(Path(bootstrap_from_state(state)["selection"]["project_root"]), state,
                    authorization)["completion_id"] == recovery["completion_id"])
        else:
            from harness.human_input import AppliedHumanInputResolution
            from harness.squad_state import build_human_input_resolution_postimage
            current, resolved = state["blocked_decision"], recovery["resolution"]
            _require(current["id"] == resolved["id"] and source == {key: state["last_dispatch"][key] for key in SOURCE_FIELDS})
            if current["status"] == "resolved":
                _require(current == resolved)
                _require_resolved_effects(state, recovery, publication)
            else:
                answer = AppliedHumanInputResolution(resolved["selected_option_id"], resolved["answer_text"], resolved["resolved_by"],
                    rationale=resolved["resolution_rationale"], confidence=resolved["resolution_confidence"])
                _require(build_human_input_resolution_postimage(current, answer, resolved_at=resolved["resolved_at"]) == resolved
                    and {key: state.get(key) for key in before_keys} == recovery["before"]
                    and state["phase"] == recovery["from_phase"])
    binding = DiscoveryCompletionBinding(request, recovery, dict(history=history, artifacts={}, route=payload["route"]),
        dict(history=history, authority=authority, runtime=recovery["runtime"]), sources, baseline)
    if debt:
        from harness.discovery_debt_resolution import require_publication
        require_publication(binding)
    return binding


def require_parent(root, run, state, binding, store):
    import hashlib
    import json
    from harness.discovery_completion import _retained_input_projection, _require, _document
    from harness.discovery_quality import validate_why2_quality_effect
    from harness.proportional_quality import load_quality_candidate_manifest
    from harness.proportional_quality_effects import quality_extension_updates
    source = binding.recovery["source_completion"]
    parent, _, _ = _retained_input_projection(root, run, state, store,
        operation_id="discovery-completion-" + source["dispatch_id"], source=source, require_checkpoint=False)
    row = store.identity_publication(spec_id=binding.spec_id, operation_id=parent.operation_id)
    retained = _document(row["completion_payload"])["proof"]
    proof = retained["intent"]
    _require(parent.producer == "why2" and not parent.clarification
        and parent.recovery["operation"] == binding.recovery["operation"]
        and binding.recovery["from_phase"] == proof["route"]["to_phase"]
        and binding.request.sources.expected_operation_id == parent.result_operation_id
        and binding.source["history"] == asdict(parent.result_history))
    before = binding.recovery["before"]
    if binding.recovery["version"] == 25:
        from harness.discovery_quality import capture_quality_policy
        from harness.discovery_issue_resolution import evidence_reader, require_issue_effects
        _require(binding.recovery["from_phase"] == "terminal-blocked" and proof["quality_effect"] == {"kind": "none"}
            and parent.request.continuation_id is None and parent.source["quality_policy"] == capture_quality_policy(before)
            and before["spec_dir"] == binding.source["authority"]["managed_identity"]["spec_path"])
        require_issue_effects(evidence_reader(root), before, binding.recovery["resolution"],
            binding.recovery["resolution"]["selected_option_id"], parent, binding.recovery["effects"])
        return
    if binding.recovery["version"] == 23:
        return require_reset_parent(root, run, state, binding, store, parent, proof)
    draft = validate_why2_quality_effect(parent, proof["quality_effect"], root=root, run=run,
        checkpoint_prestate=proof["checkpoint_prestate"], state=before)
    evidence = before["proportional_quality_candidate_evidence"]
    effect = proof["quality_effect"]
    _require(draft is not None and evidence["current_candidate_id"] == draft.candidate_id
        and evidence["selected_candidate_id"] == (effect["restore_candidate_id"] or draft.candidate_id)
        and evidence["candidate_manifest"] == str(run / "quality-candidates" / (evidence["selected_candidate_id"] + ".json"))
        and evidence["candidate_manifest_sha256"] == (effect["restore_candidate_manifest_sha256"]
            if effect["restore_candidate_id"] is not None else retained["receipts"]["effects"]["quality"]["candidate"]["manifest_sha256"]))
    candidate = load_quality_candidate_manifest(Path(evidence["candidate_manifest"]),
        expected_sha256=evidence["candidate_manifest_sha256"], expected_candidate_id=evidence["selected_candidate_id"])
    evidence_path = Path(candidate.understanding_evidence)
    _require(evidence_path.is_relative_to(run / "evidence/understanding"))
    report_bytes = evidence_path.read_bytes()
    _require(hashlib.sha256(report_bytes).hexdigest() == candidate.understanding_evidence_digest)
    from harness.element_identity_json import _unique_object, _reject_number
    report = json.loads(report_bytes, object_pairs_hook=_unique_object, parse_constant=_reject_number)
    _require(candidate.run_artifact_root == str(run)
        and evidence["selected_spec_sha256"] == dict(candidate.owned_artifact_digests)["spec.md"]
        and before["understanding_evidence"] == dict(phase="phase1-why2", iteration=report["iteration"],
            status="completed", path=candidate.understanding_evidence, digest=candidate.understanding_evidence_digest,
            **{"pass": report["pass"]}, failing_gates=[name for name, _, _, passed in candidate.normalized_gates if not passed], error=None)
        and (binding.recovery["version"] == 27
            or binding.recovery["effects"]["state_updates"] == quality_extension_updates(before, candidate, "phase1-what")))
    if binding.recovery["version"] == 27:
        from harness.discovery_debt_resolution import require_authorization
        require_authorization(root, binding, candidate)


def review_understanding_parent(root, run, state, store, binding):
    """Walk released review/resolution parents, never regenerate analysis."""
    from harness.discovery_completion import _retained_input_projection, _require
    seen = set()
    while binding.producer in {"why2", "why2-policy"}:
        source = binding.recovery["source_completion"]
        _require(source["dispatch_id"] not in seen)
        seen.add(source["dispatch_id"])
        binding, _, _ = _retained_input_projection(root, run, state, store,
            operation_id="discovery-completion-" + source["dispatch_id"], source=source, require_checkpoint=False)
    _require(binding.producer == "understanding" and binding.recovery["result"]["verdict"] == "DONE")
    return binding


def require_reset_parent(root, run, state, binding, store, parent, proof):
    from harness.discovery_completion import _require
    from harness.discovery_quality import capture_quality_policy
    from harness.human_input import why2_safeguard_question
    before, decision = binding.recovery["before"], binding.recovery["resolution"]
    count = before["why2_metric_stagnation_count" if decision["reason_code"] == "why2_metric_stagnation" else "why_fail_count"]
    _require(binding.recovery["from_phase"] == "terminal-blocked" and proof["quality_effect"] == {"kind": "none"}
        and parent.request.continuation_id is None and parent.candidate["routing"]["verdict"] == "FAIL"
        and parent.source["quality_policy"] == capture_quality_policy(before)
        and decision["question"] == why2_safeguard_question(decision["reason_code"], count))
    analysis = review_understanding_parent(root, run, state, store, parent)
    _require(all(before.get(key) == value for key, value in analysis.recovery["result"]["state_updates"].items()))
    report, = (item for item in analysis.sources.files if item.path == analysis.recovery["report_path"])
    captured, = (item for item in binding.sources.files if item.path == report.path)
    _require(captured == report)


def require_resolution_receipt(state, binding, marker):
    from harness.discovery_completion import _require
    expected = dict(schema_version=1, completion_id=marker.completion_id, intent_sha256=marker.intent_sha256,
        receipts_sha256=marker.receipts_sha256, publication_binding_sha256=marker.publication_binding_sha256,
        decision_id=binding.recovery["resolution"]["id"])
    receipts = [state.get("last_human_input_completion"),
        *(item["completion"] for _, item in resolution_associations(state))]
    if binding.recovery["version"] == 27 and binding.recovery["quality_effect"]["operation"] == "debt_write":
        from harness.discovery_bootstrap_state import bootstrap_from_state
        from harness.discovery_debt_resolution import retained_debt_receipt
        authorization = state.get("spec_quality_debt_authorization")
        _require(authorization == binding.recovery["quality_effect"]["payload"]["authorization"])
        receipts.append(retained_debt_receipt(Path(bootstrap_from_state(state)["selection"]["project_root"]), state, authorization))
    _require(expected in receipts)


def state_only_effects(state, decision, selected, effects):
    """Capture native reset/extension effects without treating them as answers.

    In particular, never apply the free-text clarification budget reset to an
    extension. Candidate evidence within remediation still requires the native
    handler's proof; this function only checks its state ownership boundary.
    """
    from harness.blocked_decision import validate_blocked_decision
    from harness.discovery_completion import _require
    from harness.proportional_quality import validate_repair_state
    from harness.discovery_issue_resolution import supported_decision as issue_decision
    checked = validate_blocked_decision(decision)
    _require(checked == decision and checked["source_phase"] == "phase1-why2"
        and checked["source_kind"] == "controller_safeguard"
        and effects.completion is None and effects.resolved_at is None
        and effects.resolved_decision_postimage is None
        and effects.state_removals == (frozenset({"quality_gate_remediation"}) if issue_decision(checked) else frozenset()))
    handler = checked["resolution_handler"]
    updates = dict(effects.state_updates)
    if issue_decision(checked):
        _require(selected is not None and effects.route == selected.next_phase
            and effects.route in {"phase1-what", "phase1-discover"}
            and set(updates) == {"status", "phase", "why_fail_count", "why2_metric_stagnation_count",
                "why_failure_baseline", "selected_issue_resolution", "issue_resolution_ledger",
                "issue_resolution_repair_baseline", "issue_resolution_recovery"}
            and updates["status"] == "running" and updates["phase"] == effects.route
            and updates["selected_issue_resolution"] == selected.id
            and type(updates["why_fail_count"]) is type(updates["why2_metric_stagnation_count"]) is int
            and updates["why_fail_count"] == updates["why2_metric_stagnation_count"] == 0
            and updates["why_failure_baseline"] is None)
    elif handler in {"reset_why_fail_count", "reset_why2_stagnation"}:
        expected = dict(status="running", phase="phase1-why2", why_fail_count=0)
        if handler == "reset_why2_stagnation":
            expected["why2_metric_stagnation_count"] = 0
        _require(selected is None and effects.route == "phase1-why2" and updates == expected
            and type(updates["why_fail_count"]) is int
            and (handler != "reset_why2_stagnation" or type(updates["why2_metric_stagnation_count"]) is int))
    elif handler == "proportional_quality_debt":
        _require(selected is not None and selected.id == "extend_once"
            and checked["reason_code"] == "proportional_quality_budget_exhausted"
            and state.get("spec_authoring_mode") == "proportional"
            and effects.route == "phase1-what" and set(updates) == {"status", "phase", "phase1_quality_repair",
                "why_fail_count", "why2_metric_stagnation_count", "quality_gate_remediation"}
            and updates["status"] == "running" and updates["phase"] == effects.route
            and type(updates["why_fail_count"]) is int and updates["why_fail_count"] == 0
            and type(updates["why2_metric_stagnation_count"]) is int and updates["why2_metric_stagnation_count"] == 0
            and type(updates["quality_gate_remediation"]) is dict)
        before = validate_repair_state(state.get("phase1_quality_repair"))
        after = validate_repair_state(updates["phase1_quality_repair"])
        _require(before["extension_authorized"] == before["extension_consumed"] == 0
            and after == {**before, "extension_authorized": before["extension_limit"]})
    else:
        raise ValueError("native policy effect is not a supported state-only resolution")
    return deepcopy(dict(route=effects.route, state_updates=updates, state_removals=sorted(effects.state_removals)))
