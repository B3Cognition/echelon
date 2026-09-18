"""Closed requirement/review claims over the existing Phase 1 result contract.

These validators grant no execution, score, allocation or publication authority.
The controller still validates the native workflow and authenticates evidence.
"""
import re

from harness.echelon_result_schema import EchelonResultContract, validate_echelon_result_contract


WHAT_OUTPUTS = {"spec.md": "requirements", "requirements-overview.md": "references"}
WHY2_OUTPUTS = {"quality-gates.md": "references", "issues.md": "issues"}


def _projected_requirement_tree(sources, *, root, spec_dir):
    from pathlib import Path
    from harness.squad_source_projection import project_publication_source_images
    path = Path(spec_dir)
    if not path.is_absolute():
        path = Path(root) / path
    spec = path.relative_to(root).as_posix()
    allowed = {spec + "/" + name for name in (*WHAT_OUTPUTS, "spec-artifact-graph.json")}
    if any(op.target not in allowed or op.action != "write" for op in sources.publication.operations):
        raise ValueError("projected requirement writes exceed WHAT ownership")
    projected = project_publication_source_images(sources)
    tree, = (tree for tree in projected.trees if tree.path == spec)
    return tree


def projected_requirement_sha256(sources, *, root, spec_dir):
    """Read a sealed WHAT image; never publish to measure repair progress."""
    import hashlib
    tree = _projected_requirement_tree(sources, root=root, spec_dir=spec_dir)
    item, = (item for item in tree.files if item.path == tree.path + "/spec.md")
    if item.content is None:
        raise ValueError("projected requirement is missing")
    return hashlib.sha256(item.content).hexdigest()


def projected_requirement_progress(sources, *, root, spec_dir):
    """Review publication timestamps cannot grant another WHAT repair cycle."""
    after = _projected_requirement_tree(sources, root=root, spec_dir=spec_dir)
    before, = (tree for tree in sources.trees if tree.path == after.path)
    names = {after.path + "/" + name for name in WHAT_OUTPUTS}
    return {item.path: item.content for item in before.files if item.path in names} != {
        item.path: item.content for item in after.files if item.path in names}


def what_constitution_parent(state, source):
    """Choose a retained association; native completion proof remains required."""
    from harness.discovery_producer import tracker_round, producer_operation_id
    row = tracker_round(state, producer="what")
    if row is None:
        return None
    if row["source"] == source:
        return row.get("constitution_parent")
    if (state.get("last_dispatch") or {}).get("phase_id") != "phase1-constitution":
        return None
    selected = producer_operation_id(state, "constitution")
    if not selected.startswith("constitution-refresh-"):
        raise ValueError("later WHAT requires an actual Constitution refresh")
    return selected


def clarification_source(receipt):
    if (type(receipt) is not dict or set(receipt) != {"schema_version", "decision_id", "completion_id",
            "intent_sha256", "receipts_sha256", "publication_binding_sha256"}
            or type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1
            or type(receipt["decision_id"]) is not str or not receipt["decision_id"]):
        raise ValueError("invalid clarification completion receipt")
    for key in ("completion_id", "intent_sha256", "receipts_sha256", "publication_binding_sha256"):
        size = 32 if key == "completion_id" else 64
        if type(receipt[key]) is not str or re.fullmatch(r"[0-9a-f]{%d}" % size, receipt[key]) is None:
            raise ValueError("invalid clarification completion receipt digest")
    return dict(dispatch_id=receipt["completion_id"], completion_intent_sha256=receipt["intent_sha256"],
        completion_receipts_sha256=receipt["receipts_sha256"],
        completed_publication_binding_sha256=receipt["publication_binding_sha256"])


def current_spec_source(root, state, producer):
    """Select the actual source head; parent authentication remains mandatory."""
    from harness.discovery_producer import SOURCE_FIELDS
    from harness.element_identity_store import IdentityStore
    source = {key: state["last_dispatch"][key] for key in SOURCE_FIELDS}
    decision, receipt = state.get("blocked_decision") or {}, state.get("last_human_input_completion")
    authorization = state.get("spec_quality_debt_authorization") or {}
    if (producer == "alignment" and state["last_dispatch"]["phase_id"] == "phase2-tracker-alignment"
            and decision.get("status") == "resolved" and decision.get("source_phase") == "phase2-tracker-alignment"
            and decision.get("resolution_handler") == "clarification_resume" and receipt is not None
            and receipt.get("decision_id") == decision.get("id")):
        observed = IdentityStore.open(root).check_managed_context(spec_id=state["managed_identity"]["spec_id"],
            run_id=state["run_id"], record=state["managed_identity"])
        if observed["source_context"]["operation_id"] == "discovery-completion-" + receipt["completion_id"]:
            return clarification_source(receipt)
    if (producer in {"lexicon", "checkpoint"} and receipt is not None
            and (authorization.get("resolution_completion") or {}).get("completion_id") == receipt.get("completion_id")
            and (authorization.get("resolved_decision") or {}).get("id") == receipt.get("decision_id")):
        observed = IdentityStore.open(root).check_managed_context(spec_id=state["managed_identity"]["spec_id"],
            run_id=state["run_id"], record=state["managed_identity"])
        if observed["source_context"]["operation_id"] == "discovery-completion-" + receipt["completion_id"]:
            return clarification_source(receipt)
    if (producer in {"what", "why2", "lexicon", "checkpoint"} and state["last_dispatch"]["phase_id"] == "phase1-why2"
            and decision.get("status") == "resolved" and decision.get("source_phase") == "phase1-why2"
            and decision.get("resolution_handler") in {"clarification_resume", "proportional_quality_debt",
                "reset_why_fail_count", "reset_why2_stagnation", "banzai_issue_resolution"} and receipt is not None
            and receipt.get("decision_id") == decision.get("id")):
        observed = IdentityStore.open(root).check_managed_context(spec_id=state["managed_identity"]["spec_id"],
            run_id=state["run_id"], record=state["managed_identity"])
        if observed["source_context"]["operation_id"] == "discovery-completion-" + receipt["completion_id"]:
            return clarification_source(receipt)
    return source


def require_spec_parent(root, run, state, producer, source):
    """Authenticate a released parent; state selection alone is not authority."""
    from harness.discovery_completion import _retained_input_projection, _require
    from harness.element_identity_store import IdentityStore
    if producer not in {"what", "why2"}:
        raise ValueError("specification parent is not yet admitted")
    from harness.discovery_producer import tracker_round
    row = tracker_round(state, producer=producer)
    if producer in {"what", "why2"}:
        resolution = None if row is None or row["source"] != source else row.get("review_resolution", row["resolution"])
        if resolution is None:
            decision, receipt = state.get("blocked_decision") or {}, state.get("last_human_input_completion")
            if (decision.get("status") == "resolved" and receipt is not None
                    and receipt.get("decision_id") == decision.get("id") and source == clarification_source(receipt)):
                resolution = dict(decision=decision, completion=receipt)
        if resolution is not None:
            store = IdentityStore.open(root)
            _require(source == clarification_source(resolution["completion"]))
            policy_resolution = resolution["decision"]["resolution_handler"] != "clarification_resume"
            binding, _, _ = _retained_input_projection(root, run, state, store,
                operation_id="discovery-completion-" + source["dispatch_id"], source=source,
                require_checkpoint=False, required_route=None if policy_resolution else ("phase1-why2", "phase1-" + producer), required_origin="resolution")
            _require((binding.policy_resolution if policy_resolution else binding.recovery["version"] == 18 and binding.producer == "why2")
                and binding.candidate["route"] == "phase1-" + producer
                and binding.recovery["resolution"] == resolution["decision"])
            if producer == "what":
                if row is not None and row["source"] == source:
                    _require(row["review_parent"] == binding.recovery["operation"]["binding"]["operation_id"])
                return binding
            from harness.discovery_policy_resolution import review_understanding_parent
            binding = review_understanding_parent(root, run, state, store, binding)
            for key, value in binding.recovery["result"]["state_updates"].items():
                _require(state.get(key) == value)
            return binding
    constitution_parent = what_constitution_parent(state, source) if producer == "what" else None
    repairing = producer == "what" and row is not None and (
        row["source"] != source or row["predecessor"] is not None) and constitution_parent is None
    parent = ("why2" if repairing else "constitution") if producer == "what" else "understanding"
    binding, _, _ = _retained_input_projection(root, run, state, IdentityStore.open(root),
        operation_id="discovery-completion-" + source["dispatch_id"], source=source,
        require_checkpoint=False, required_route=("phase1-" + parent, "phase1-" + producer))
    _require(binding.producer == parent and not binding.clarification)
    if constitution_parent is not None:
        _require(binding.recovery["version"] == 16
            and binding.recovery["operation"]["binding"]["operation_id"] == constitution_parent)
    if producer == "why2":
        _require(binding.recovery["result"]["verdict"] == "DONE")
        for key, value in binding.recovery["result"]["state_updates"].items():
            _require(state.get(key) == value)
    return binding


def validate_spec_routing(value, producer):
    if producer not in {"what", "why2"} or type(value) is not dict or set(value) != {"verdict", "state_updates"}:
        raise ValueError("invalid managed specification routing")
    why2 = producer == "why2"
    verdicts = frozenset({"PASS", "FAIL", "STOP_AND_ASK"} if why2 else {"DONE", "FAIL"})
    if type(value["verdict"]) is not str or value["verdict"] not in verdicts:
        raise ValueError("specification verdict must use the exact contract encoding")
    allowed = {"evidence_resolution_status", "evidence_requests", "status", "blocked_reason"}
    allowed.update({"dependency_checks", "finding_routes", "escalation_question", "escalation_recommended_answer",
        "escalation_risk_level", "autonomous_default_candidate"} if why2 else {"spec_status"})
    types = {"evidence_resolution_status": "string", "evidence_requests": "object", "status": "string"}
    types.update({"dependency_checks": "object", "finding_routes": "object", "autonomous_default_candidate": "object"}
        if why2 else {"spec_status": "string"})
    enums = {"evidence_resolution_status": frozenset({"not_required", "pending"}), "status": frozenset({"blocked"})}
    if not why2:
        enums["spec_status"] = frozenset({"planned", "blocked"})
    validate_echelon_result_contract(value, EchelonResultContract(
        allowed_state_update_keys=frozenset(allowed),
        required_state_update_keys=frozenset({"evidence_resolution_status", *({"finding_routes"} if why2 else set())}),
        state_update_types=types, state_update_enums=enums,
        allowed_verdicts=verdicts,
        unexpected_state_updates="reject", evidence_routing="finding_routes" if why2 else "requests"))
    if value["verdict"] in {"PASS", "DONE"} and value["state_updates"]["evidence_resolution_status"] != "not_required":
        raise ValueError("successful specification result cannot conceal pending evidence")


def validate_spec_artifacts(artifacts, routing, producer):
    if any(type(content) is not str or not content.strip() for content in artifacts.values()):
        raise ValueError("specification outputs must be nonblank")
    if producer == "what":
        if any(re.search(r"\bOQ-[A-Za-z0-9-]+\b", content) for content in artifacts.values()):
            raise ValueError("open questions must reference existing U identities, not OQ aliases")
        return
    from harness.proportional_quality import _parse_authoritative_sage_assessment_bytes, is_actionable_sage_issue
    verdict, issues = _parse_authoritative_sage_assessment_bytes(artifacts["issues.md"].encode("utf-8"))
    expected = "PASS" if routing["verdict"] == "PASS" else "FAIL"
    if verdict != expected or re.findall(r"^## Verdict: ([^\n]+)$", artifacts["quality-gates.md"], re.MULTILINE) != [expected]:
        raise ValueError("WHY2 report verdict differs from structured routing")
    findings = routing["state_updates"]["finding_routes"]["findings"]
    ids = [finding["issue_id"] for finding in findings]
    actionable = {issue["issue_id"] for issue in issues if is_actionable_sage_issue(issue)}
    if len(ids) != len(set(ids)) or set(ids) != actionable or (verdict == "PASS" and actionable):
        raise ValueError("WHY2 routing must cover each actionable report issue exactly once")
