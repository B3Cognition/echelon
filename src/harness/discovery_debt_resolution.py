"""Bind native debt authority to the existing managed publication owner.

Publication alone mutates the debt file. Native quality builds the authorization
and verifies the resulting effect; neither this association nor prose grants a
new repair, acceptance, or resolver permission.
"""
import hashlib
from pathlib import Path


def state_effects(decision, effects, quality_effect):
    from harness.discovery_completion import _require
    from harness.discovery_policy_resolution import supported_decision
    _require(supported_decision(decision) and effects.completion is None and effects.legacy_completion is None
        and effects.resolved_at is None and effects.resolved_decision_postimage is None)
    choice = decision["selected_option_id"]
    if choice == "continue_with_debt":
        expected = dict(status="running", phase=effects.route, spec_status="accepted_with_debt",
            spec_quality_debt_authorization=quality_effect["payload"]["authorization"])
        removals = {"quality_gate_remediation"}
        _require(effects.route in {"phase1-lexicon-derive", "checkpoint-assess"}
            and quality_effect["operation"] == "debt_write")
    else:
        _require(choice == "stop" and effects.route == "terminal-blocked"
            and quality_effect["operation"] == "debt_remove")
        expected = dict(status="blocked", phase=effects.route, blocked_reason="proportional_quality_debt_declined")
        removals = {"quality_gate_remediation", "spec_quality_debt_authorization"}
    _require(quality_effect["kind"] == "proportional_quality"
        and set(quality_effect) == {"kind", "operation", "payload"}
        and effects.state_updates == expected and effects.state_removals == frozenset(removals))
    return dict(route=effects.route, state_updates=expected, state_removals=sorted(removals))


def publication(root, run, completion_id, quality_effect):
    from harness.squad_publication import SquadPublicationTransaction
    from harness.phase1_quality_debt import quality_debt_bytes
    effect = quality_effect["payload"]
    target = Path(effect["debt_path"])
    transaction = SquadPublicationTransaction.begin(root, run, completion_id)
    if quality_effect["operation"] == "debt_write":
        staged = transaction.build_path("quality-debt.json")
        staged.write_bytes(quality_debt_bytes(effect["debt"]))
        staged.chmod(0o600)
        transaction.add_write(target, staged, owned_paths={target})
    else:
        transaction.add_delete(target, owned_paths={target})
    return transaction.seal()


def require_publication(binding):
    from harness.discovery_completion import _require
    from harness.phase1_quality_debt import quality_debt_bytes
    effect = binding.recovery["quality_effect"]
    payload = effect["payload"]
    path = binding.source["authority"]["managed_identity"]["spec_path"] + "/quality-debt.json"
    _require(payload["operation"] == effect["operation"] and payload["debt_path"] == path)
    operation, = binding.sources.publication.operations
    _require(operation.target == path)
    if effect["operation"] == "debt_write":
        _require(set(payload) == {"operation", "debt_path", "debt", "authorization", "previous_debt_artifact_sha256"})
        content = quality_debt_bytes(payload["debt"])
        _require(operation.action == "write" and operation.postimage_bytes == content
            and operation.postimage.mode == 0o600
            and operation.preimage.sha256 == payload["previous_debt_artifact_sha256"]
            and operation.postimage.sha256 == hashlib.sha256(content).hexdigest())
    else:
        _require(set(payload) == {"operation", "debt_path"} and effect["operation"] == "debt_remove"
            and operation.action == "delete" and operation.postimage.kind == "missing")


def require_authorization(root, binding, candidate):
    from harness.discovery_completion import _require
    from harness.phase1_quality_debt import build_quality_debt_authorization
    require_publication(binding)
    before, decision = binding.recovery["before"], binding.recovery["resolution"]
    if decision["selected_option_id"] == "continue_with_debt":
        prepared = build_quality_debt_authorization(project_root=root,
            spec_dir=root / binding.source["authority"]["managed_identity"]["spec_path"], candidate=candidate,
            candidate_manifest=Path(before["proportional_quality_candidate_evidence"]["candidate_manifest"]),
            repair_state=before["phase1_quality_repair"], understanding_state=before["understanding_evidence"],
            candidate_evidence_state=before["proportional_quality_candidate_evidence"], decision=decision,
            decision_id=decision["id"], resolved_by=decision["resolved_by"], resolved_at=decision["resolved_at"],
            completion_id=binding.recovery["completion_id"], from_phase=binding.recovery["from_phase"],
            to_phase=binding.candidate["route"], publication_sources=binding.sources)
        _require(prepared.effect_payload() == binding.recovery["quality_effect"]["payload"])


def require_effect(binding, intent):
    from harness.discovery_completion import _require
    _require(binding.recovery["version"] == 27 and intent.effect_plan == ("quality", "context")
        and intent.quality_effect == binding.recovery["quality_effect"]
        and intent.origin == "resolution" and intent.route["decision_id"] == binding.recovery["resolution"]["id"]
        and intent.route["from_phase"] == binding.recovery["from_phase"]
        and intent.route["to_phase"] == binding.candidate["route"])


def require_resolution_link(root, state, authorization, debt):
    """Read the existing released proof; never reconstruct a new receipt."""
    from harness.discovery_bootstrap_state import bootstrap_from_state
    from harness.discovery_completion import _require, _retained_input_projection, _document
    from harness.discovery_spec import clarification_source
    from harness.element_identity_store import IdentityStore
    from harness.phase1_quality_debt import apply_or_verify_quality_debt_effect
    selection = bootstrap_from_state(state)["selection"]
    _require(root == Path(selection["project_root"]))
    run = Path(selection["run_dir"])
    store = IdentityStore.open(root)
    expected = authorization["resolution_completion"]
    receipt = retained_debt_receipt(root, state, authorization)
    source = clarification_source(receipt)
    binding, _, _ = _retained_input_projection(root, run, state, store,
        operation_id="discovery-completion-" + source["dispatch_id"], source=source,
        require_checkpoint=False, required_origin="resolution",
        required_route=(expected["from_phase"], expected["to_phase"]))
    _require(binding.recovery["version"] == 27 and binding.recovery["completion_id"] == expected["completion_id"]
        and binding.recovery["resolution"] == authorization["resolved_decision"])
    effect = binding.recovery["quality_effect"]
    _require(effect["operation"] == "debt_write" and effect["payload"]["authorization"] == authorization
        and effect["payload"]["debt"] == debt)
    row = store.identity_publication(spec_id=binding.spec_id, operation_id=binding.operation_id)
    proof = _document(row["completion_payload"])["proof"]
    receipt = apply_or_verify_quality_debt_effect(root, effect["payload"], verify_only=True)
    _require(proof["receipts"]["effects"]["quality"] == dict(schema_version=1, operation="debt_write", debt=receipt))


def retained_debt_receipt(root, state, authorization):
    """A later checkpoint receipt cannot replace the original debt resolution."""
    from harness.discovery_completion import _require, _document
    from harness.element_identity_store import IdentityStore
    from harness.squad_completion import validate_retained_completion_proof
    completion_id = authorization["resolution_completion"]["completion_id"]
    row = IdentityStore.open(root).identity_publication(spec_id=state["managed_identity"]["spec_id"],
        operation_id="discovery-completion-" + completion_id)
    _require(row is not None and row["state"] == "released")
    retained = _document(row["completion_payload"])
    marker, intent, _ = validate_retained_completion_proof(retained["completion"],
        retained["proof"]["intent"], retained["proof"]["receipts"])
    _require(intent.origin == "resolution" and marker.completion_id == completion_id
        and intent.route["decision_id"] == authorization["resolved_decision"]["id"])
    receipt = dict(schema_version=1, decision_id=intent.route["decision_id"], completion_id=completion_id,
        intent_sha256=marker.intent_sha256, receipts_sha256=marker.receipts_sha256,
        publication_binding_sha256=marker.publication_binding_sha256)
    current = state.get("last_human_input_completion")
    if current is not None and current.get("completion_id") == completion_id:
        _require(current == receipt)
    return receipt
