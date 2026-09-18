"""Closed Phase 2 claims and parent authorization; no identity edits or publication."""

from harness.echelon_result_schema import EchelonResultContract, validate_echelon_result_contract


ASSESSMENT_OUTPUTS = {
    "feasibility": {name: "references" for name in (
        "feasibility.md", "prioritization.md", "estimates.md", "mvp-scope.md", "kill-report.md")},
    "strategy": {"strategic-overview.md": "references"},
    "alignment": {"intent-alignment-check.md": "references"},
}
ASSESSMENT_VERSIONS = {"feasibility": 9, "strategy": 10, "alignment": 11}


def require_feasibility_repair(root, run, state, source, predecessor):
    """Authenticate the historical gate and the accepted author it sent to repair."""
    from harness.discovery_completion import _require, _retained_input_projection
    from harness.discovery_assessment_gate import require_feasibility_gate_parent, feasibility_gate_route
    from harness.element_identity_store import IdentityStore
    gate, _, _ = _retained_input_projection(root, run, state, IdentityStore.open(root),
        operation_id="discovery-completion-" + source["dispatch_id"], source=source,
        require_checkpoint=False, required_route=("phase2-feasibility-structural", "phase2-decide"))
    _require(gate.producer == "feasibility_gate" and gate.recovery["version"] in {32, 34})
    updates = gate.recovery["result"]["state_updates"]
    _require(updates["structural_action"] == "repair"
        and feasibility_gate_route(gate.recovery["routing_state"], updates) == "phase2-decide")
    author = require_feasibility_gate_parent(root, run, state, gate.recovery["source_completion"])
    _require(author.recovery["operation"]["binding"]["operation_id"] == predecessor)
    return gate


def require_feasibility_parent(root, run, state, source):
    """Authenticate current approval or released repair; never reset native budgets."""
    from harness.discovery_completion import _require, _retained_input_projection, _json
    from harness.discovery_spec import clarification_source
    from harness.element_identity_store import IdentityStore
    from harness.phase1_quality import has_current_phase1_quality_certificate
    from harness.phase1_quality_debt import has_current_quality_debt_authorization
    _require(type(state) is dict and state.get("phase") == "phase2-decide"
        and state.get("status") == "running" and not state.get("cancel_requested")
        and type(state.get("last_human_input_completion")) is dict)
    from harness.discovery_producer import tracker_rounds, SOURCE_FIELDS
    rounds = tracker_rounds(state, "feasibility")
    selected = None if rounds is None else rounds["rounds"].get("feasibility-" + source["dispatch_id"])
    if selected is not None:
        _require(rounds["active"] == "feasibility-" + source["dispatch_id"])
    predecessor = None if rounds is None else (selected["predecessor"] if selected is not None else rounds["active"])
    store = IdentityStore.open(root)
    if predecessor is not None:
        from harness.config import get_full_resolved_config
        dispatch = state.get("last_dispatch") or {}
        _require(dispatch.get("phase_id") == "phase2-feasibility-structural"
            and dispatch.get("post_dispatch_complete") is True
            and source == {key: dispatch.get(key) for key in SOURCE_FIELDS}
            and not any(key in state for key in ("pending_controller_completion", "pending_external_publication", "product_input_mutation", "governance")))
        if selected is not None:
            _require(selected["resolution"] is None and selected["source"] == source)
        binding = require_feasibility_repair(root, run, state, source, predecessor)
        routing, updates = binding.recovery["routing_state"], binding.recovery["result"]["state_updates"]
        _require(_json({key: state.get(key) for key in updates}) == _json(updates)
            and type(state.get("iteration")) is int and state["iteration"] == routing["iteration"] + 1
            and type(state.get("max_iterations")) is int and state["max_iterations"] == routing["max_iterations"]
            and state.get("feasibility_verdict") == routing["feasibility_verdict"]
            and get_full_resolved_config(root) == binding.recovery["config"])
    else:
        _require(source == clarification_source(state["last_human_input_completion"]))
        if selected is not None:
            _require(selected["source"] == source and selected["resolution"] == dict(
                decision=state.get("blocked_decision"), completion=state["last_human_input_completion"]))
        binding, _, _ = _retained_input_projection(root, run, state, store,
            operation_id="discovery-completion-" + source["dispatch_id"], source=source,
            require_checkpoint=False, required_origin="resolution",
            required_route=("checkpoint-assess", "phase2-decide"))
        _require(binding.producer == "checkpoint" and binding.recovery["version"] == 30
            and binding.recovery["resolution"] == state.get("blocked_decision")
            and binding.recovery["resolution"]["selected_option_id"] == "approve"
            and binding.candidate["route"] == "phase2-decide")
    authority = store.check_managed_context(spec_id=binding.spec_id,
        run_id=state["run_id"], record=state["managed_identity"])
    _require(authority["source_context"]["operation_id"] == binding.operation_id
        and (has_current_phase1_quality_certificate(state, project_root=root)
            or has_current_quality_debt_authorization(state, project_root=root)))
    return binding


def require_strategy_parent(root, run, state, source):
    """Authenticate the current released gate, not an author verdict or phase label."""
    from types import SimpleNamespace
    from harness.discovery_completion import _require, _retained_input_projection, _document, authenticate
    from harness.discovery_producer import SOURCE_FIELDS
    from harness.element_identity_store import IdentityStore
    from harness.phase1_quality import has_current_phase1_quality_certificate
    from harness.phase1_quality_debt import has_current_quality_debt_authorization
    from harness.squad_completion import validate_retained_completion_proof
    _require(type(state) is dict and state.get("phase") == "phase2-strategic-overview"
        and state.get("status") == "running" and not state.get("cancel_requested")
        and not any(key in state for key in ("pending_controller_completion",
            "pending_external_publication", "product_input_mutation", "governance")))
    dispatch = state.get("last_dispatch") or {}
    _require(dispatch.get("phase_id") == "phase2-feasibility-structural"
        and dispatch.get("post_dispatch_complete") is True
        and source == {key: dispatch.get(key) for key in SOURCE_FIELDS})
    store = IdentityStore.open(root)
    binding, _, _ = _retained_input_projection(root, run, state, store,
        operation_id="discovery-completion-" + source["dispatch_id"], source=source,
        require_checkpoint=False,
        required_route=("phase2-feasibility-structural", "phase2-strategic-overview"))
    _require(binding.producer == "feasibility_gate" and binding.recovery["version"] in {32, 34}
        and binding.recovery["routing_state"]["feasibility_verdict"] == "PASS"
        and binding.recovery["result"]["state_updates"]["structural_action"] in {"proceed", "proceed_with_warning"})
    # Reuse live completion authentication, including exact native counters,
    # configuration and released ancestry, with the actual stored proof.
    row = store.identity_publication(spec_id=binding.spec_id, operation_id=binding.operation_id)
    proof = _document(row["completion_payload"])
    marker, intent, receipts = validate_retained_completion_proof(proof["completion"],
        proof["proof"]["intent"], proof["proof"]["receipts"])
    authenticate(root, run, state, SimpleNamespace(marker=marker, intent=intent, receipts=receipts))
    authority = store.check_managed_context(spec_id=binding.spec_id,
        run_id=state["run_id"], record=state["managed_identity"])
    _require(authority["source_context"]["operation_id"] == binding.operation_id
        and store.pending_identity_publication(spec_id=binding.spec_id) is None
        and (has_current_phase1_quality_certificate(state, project_root=root)
            or has_current_quality_debt_authorization(state, project_root=root)))
    return binding


def require_alignment_repair(root, run, state, source, predecessor):
    """Authenticate the released failure and the accepted author it sent to repair."""
    from harness.discovery_completion import _require, _retained_input_projection
    from harness.discovery_assessment_gate import require_alignment_gate_parent, alignment_gate_route
    from harness.element_identity_store import IdentityStore
    gate, _, _ = _retained_input_projection(root, run, state, IdentityStore.open(root),
        operation_id="discovery-completion-" + source["dispatch_id"], source=source,
        require_checkpoint=False,
        required_route=("phase2-intent-alignment-structural", "phase2-tracker-alignment"))
    _require(gate.producer == "alignment_gate" and gate.recovery["version"] in {37, 39})
    updates = gate.recovery["result"]["state_updates"]
    _require(updates["structural_action"] == "repair"
        and alignment_gate_route(gate.recovery["routing_state"], updates) == "phase2-tracker-alignment")
    author = require_alignment_gate_parent(root, run, state, gate.recovery["source_completion"])
    _require(author.recovery["operation"]["binding"]["operation_id"] == predecessor)
    return gate


def require_alignment_parent(root, run, state, source):
    """Require released strategy or the exact failed gate; preserve native budgets."""
    from types import SimpleNamespace
    from harness.discovery_completion import _require, _retained_input_projection, _document, authenticate
    from harness.discovery_producer import SOURCE_FIELDS, tracker_rounds
    from harness.element_identity_store import IdentityStore
    from harness.phase1_quality import has_current_phase1_quality_certificate
    from harness.phase1_quality_debt import has_current_quality_debt_authorization
    from harness.squad_completion import validate_retained_completion_proof
    _require(type(state) is dict and state.get("phase") == "phase2-tracker-alignment"
        and state.get("status") == "running" and not state.get("cancel_requested")
        and not any(key in state for key in ("pending_controller_completion",
            "pending_external_publication", "product_input_mutation", "governance")))
    dispatch = state.get("last_dispatch") or {}
    rounds = tracker_rounds(state, "alignment")
    operation_id = "alignment-" + source.get("dispatch_id", "")
    selected = None if rounds is None else rounds["rounds"].get(operation_id)
    if selected is not None:
        _require(rounds["active"] == operation_id and selected["source"] == source
            and selected["resolution"] is None)
    predecessor = None if rounds is None else (selected["predecessor"] if selected is not None else rounds["active"])
    _require(dispatch.get("phase_id") == ("phase2-strategic-overview" if predecessor is None
            else "phase2-intent-alignment-structural")
        and dispatch.get("post_dispatch_complete") is True
        and source == {key: dispatch.get(key) for key in SOURCE_FIELDS})
    store = IdentityStore.open(root)
    if predecessor is None:
        binding, _, _ = _retained_input_projection(root, run, state, store,
            operation_id="discovery-completion-" + source["dispatch_id"], source=source,
            require_checkpoint=False,
            required_route=("phase2-strategic-overview", "phase2-tracker-alignment"))
        _require(binding.producer == "strategy" and binding.recovery["version"] == 35
            and binding.candidate["routing"] == dict(verdict="DONE", state_updates={}))
    else:
        binding = require_alignment_repair(root, run, state, source, predecessor)
    row = store.identity_publication(spec_id=binding.spec_id, operation_id=binding.operation_id)
    proof = _document(row["completion_payload"])
    marker, intent, receipts = validate_retained_completion_proof(proof["completion"],
        proof["proof"]["intent"], proof["proof"]["receipts"])
    authenticate(root, run, state, SimpleNamespace(marker=marker, intent=intent, receipts=receipts))
    authority = store.check_managed_context(spec_id=binding.spec_id,
        run_id=state["run_id"], record=state["managed_identity"])
    _require(authority["source_context"]["operation_id"] == binding.operation_id
        and store.pending_identity_publication(spec_id=binding.spec_id) is None
        and (has_current_phase1_quality_certificate(state, project_root=root)
            or has_current_quality_debt_authorization(state, project_root=root)))
    return binding


def _alignment_question_policy(root, state, routing):
    from harness.blocked_decision import validate_blocked_decision
    from harness.discovery_completion import _require
    from harness.phase_graph import load_workspace_phase_graph
    from harness.tracker_clarification import question_claim
    claim = question_claim(routing, "alignment")
    _require(claim is not None and state.get("phase") == "phase2-tracker-alignment"
        and "intent_alignment_verdict" not in state)
    decision = validate_blocked_decision(state["blocked_decision"])
    _require(decision["autonomy_mode"] == state["autonomy_mode"])
    registry = load_workspace_phase_graph(root)[0].human_input_policy_registry()
    request = registry.prepare(source_kind="provider_escalation", producer_id="phase2-tracker-alignment",
        phase_id="phase2-tracker-alignment", reason_code="human_clarification_required", **claim,
        source_state_revision=decision["source_state_revision"])
    policy = registry.lookup("provider_escalation", "phase2-tracker-alignment", "human_clarification_required")
    return request, policy


def require_alignment_question(root, state, routing):
    """Bind a pending question to native policy; grant no answer authority."""
    from harness.blocked_decision import build_blocked_decision_v3
    from harness.discovery_completion import _require, _json
    from harness.human_input import select_initial_decision_status
    request, policy = _alignment_question_policy(root, state, routing)
    decision = state["blocked_decision"]
    expected = build_blocked_decision_v3(prepared=request, decision_id=decision["id"],
        status=select_initial_decision_status(state["autonomy_mode"], policy, request),
        autonomy_mode=state["autonomy_mode"], created_at=decision["created_at"])
    _require(_json(expected) == _json(state["blocked_decision"]))


def require_alignment_answer(root, before, resolved, routing):
    """Validate native resolver/answer semantics, not source or dispatch authority."""
    from harness.discovery_completion import _require, _json
    from harness.discovery_policy_resolution import require_native_decision
    from harness.human_input import AppliedHumanInputResolution
    from harness.squad import SquadController
    from harness.squad_state import build_human_input_resolution_postimage
    from harness.tracker_clarification import _record
    request, policy = _alignment_question_policy(root, before, routing)
    decision = before["blocked_decision"]
    require_native_decision(request, decision)
    _record(resolved, "alignment")
    answer = AppliedHumanInputResolution(None, resolved["answer_text"], resolved["resolved_by"],
        rationale=resolved["resolution_rationale"], confidence=resolved["resolution_confidence"])
    _require(resolved["resolved_by"] in {"user", "COMMANDER"}
        and (resolved["resolved_by"] != "COMMANDER" or decision["automatic_eligible"] is True)
        and not (resolved["resolved_by"] == "user" and decision["autonomy_mode"] == "banzai"
            and decision["automatic_eligible"] is True))
    SquadController._validate_human_input_resolver(decision, answer)
    reader = object.__new__(SquadController)
    reader._validate_human_input_resolution_answer(decision, answer)
    _require(_json(build_human_input_resolution_postimage(decision, answer,
        resolved_at=resolved["resolved_at"])) == _json(resolved))
    return policy


def require_alignment_question_parent(root, run, state, source):
    """Authenticate the released initial question before preparing its answer."""
    from harness.discovery_completion import _require
    from harness.element_identity_store import IdentityStore
    parent = require_alignment_question_evidence(root, run, state, source)
    store = IdentityStore.open(root)
    authority = store.check_managed_context(spec_id=parent.spec_id, run_id=state["run_id"], record=state["managed_identity"])
    _require(authority["source_context"]["operation_id"] == parent.operation_id
        and store.pending_identity_publication(spec_id=parent.spec_id) is None)
    return parent


def require_alignment_question_evidence(root, run, state, source):
    """Historical question proof; live-head authority is checked separately."""
    from harness.blocked_decision import build_blocked_decision_v3
    from harness.discovery_completion import _require, _retained_input_projection, require_assessment_entry_state, _receipts
    from harness.discovery_policy_resolution import require_native_decision
    from harness.discovery_producer import SOURCE_FIELDS
    from harness.element_identity_store import IdentityStore
    from harness.human_input import select_initial_decision_status
    _require(state.get("phase") == "phase2-tracker-alignment" and state.get("status") == "blocked"
        and not state.get("cancel_requested") and not any(key in state for key in (
            "pending_controller_completion", "pending_external_publication", "product_input_mutation", "governance")))
    dispatch = state.get("last_dispatch") or {}
    _require(dispatch.get("phase_id") == "phase2-tracker-alignment" and dispatch.get("post_dispatch_complete") is True
        and source == {key: dispatch.get(key) for key in SOURCE_FIELDS})
    store = IdentityStore.open(root)
    parent, _, _ = _retained_input_projection(root, run, state, store,
        operation_id="discovery-completion-" + source["dispatch_id"], source=source,
        require_checkpoint=False, required_route=("phase2-tracker-alignment", "phase2-tracker-alignment"))
    _require(parent.producer == "alignment" and parent.recovery["version"] == 36
        and parent.candidate["routing"]["verdict"] == "STOP_AND_ASK")
    request, policy = _alignment_question_policy(root, state, parent.candidate["routing"])
    decision = state["blocked_decision"]
    _require(decision["status"] in {"pending", "resolving", "awaiting_human"})
    require_native_decision(request, decision)
    # The released question seals initial status; native claim/failure fields
    # may now have advanced. Project only those fields for historical checking.
    initial = build_blocked_decision_v3(prepared=request, decision_id=decision["id"],
        status=select_initial_decision_status(state["autonomy_mode"], policy, request),
        autonomy_mode=state["autonomy_mode"], created_at=decision["created_at"])
    require_assessment_entry_state(root, run, {**state, "blocked_decision": initial}, parent, store)
    _receipts(root, run, state, parent, store)
    return parent


def validate_assessment_routing(value, producer):
    """Validate author claims through the native result contract, not gate policy."""
    verdicts = {"feasibility": {"PASS", "KILL", "DEFER"}, "strategy": {"DONE"},
                "alignment": {"ALIGNED", "DRIFT", "STOP_AND_ASK"}}
    if (producer not in verdicts or type(value) is not dict or set(value) != {"verdict", "state_updates"}
            or type(value["verdict"]) is not str or value["verdict"] not in verdicts[producer]
            or type(value["state_updates"]) is not dict):
        raise ValueError("invalid managed assessment routing")
    allowed = set() if producer == "strategy" else {"status"}
    if producer == "alignment":
        allowed.update({"blocked_reason", "escalation_question", "escalation_recommended_answer",
                        "escalation_risk_level"})
    validate_echelon_result_contract(value, EchelonResultContract(
        allowed_state_update_keys=frozenset(allowed),
        state_update_types={key: "string" for key in allowed},
        state_update_enums={"status": frozenset({"blocked", "killed"} if producer == "feasibility" else {"blocked"})},
        allowed_verdicts=frozenset(verdicts[producer]), unexpected_state_updates="reject"))
    updates = value["state_updates"]
    if producer == "alignment":
        if value["verdict"] == "STOP_AND_ASK":
            if updates["blocked_reason"] != "human_clarification_required":
                raise ValueError("alignment clarification must use the native decision reason")
            if ("escalation_recommended_answer" in updates) != ("escalation_risk_level" in updates):
                raise ValueError("alignment recommendation and risk must be supplied together")
        elif updates:
            raise ValueError("ordinary alignment cannot carry clarification state")


def validate_assessment_artifacts(artifacts, routing, producer):
    if type(artifacts) is not dict or set(artifacts) != set(ASSESSMENT_OUTPUTS[producer]):
        raise ValueError("assessment must supply its exact canonical outputs")
    for name, content in artifacts.items():
        if name == "kill-report.md" and content is None and routing["verdict"] != "KILL":
            continue
        if type(content) is not str or not content.strip() or "\x00" in content:
            raise ValueError("assessment outputs must be nonblank UTF-8 text")
        content.encode("utf-8")


def validate_assessment_baseline(artifacts, routing, producer, before):
    """Conditional output absence cannot erase an earlier captured kill report."""
    if (producer == "feasibility" and routing["verdict"] != "KILL"
            and artifacts["kill-report.md"] != before["kill-report.md"]):
        raise ValueError("non-KILL assessment must preserve the captured kill-report slot")
