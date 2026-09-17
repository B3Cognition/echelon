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
    _require(gate.producer == "feasibility_gate" and gate.recovery["version"] == 32)
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
