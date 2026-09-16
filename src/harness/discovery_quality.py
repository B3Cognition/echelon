"""Bind native quality effects to the managed review's captured evidence."""
import hashlib
import json
from pathlib import Path

from harness.element_identity_json import _unique_object, _reject_number
from harness.proportional_quality import (
    quality_candidate_from_effect_payload, project_authoritative_sage_evidence_snapshot,
    require_projected_authoritative_sage_evidence_snapshot, _authoritative_gates,
    _normalize_finding_routes,
    initialize_repair_state, validate_repair_state, _normalize_eligibility_reasons,
)


def capture_quality_policy(state):
    """Detached native policy inputs, included in the accepted source fingerprint."""
    from echelon.spec_authoring import normalize_spec_authoring_mode
    return dict(authoring_mode=normalize_spec_authoring_mode(state.get("spec_authoring_mode")),
        repair=initialize_repair_state(state), product_input_mapping_repair=bool(state.get("product_input_mapping_repair")))


def validate_quality_policy(value):
    from harness.discovery_completion import _require, _closed
    _closed(value, ("authoring_mode", "repair", "product_input_mapping_repair"))
    _require(value["authoring_mode"] in {"proportional", "perfectionist"}
        and type(value["product_input_mapping_repair"]) is bool)
    if value["authoring_mode"] == "perfectionist":
        _require(value["repair"] is None)
    else:
        _require(validate_repair_state(value["repair"]) == value["repair"])
    return value


def validate_why2_quality_effect(binding, effect, *, root, run, checkpoint_prestate, state=None):
    from harness.discovery_completion import _require, _closed
    _require(binding.producer == "why2")
    policy = validate_quality_policy(binding.source["quality_policy"])
    declared = getattr(getattr(binding, "request", None), "continuation_id", None)
    if effect == {"kind": "none"}:
        _require(declared is None)
        if state is not None:
            _require(capture_quality_policy(state) == policy)
        return None
    _closed(effect, ("kind", "operation", "spec_dir", "run_id", "spec_id", "candidate",
        "checkpoint_prestate", "restore_candidate_id", "restore_candidate_manifest_sha256",
        "restore_artifact_preimage_digests"))
    spec_path = binding.source["authority"]["managed_identity"]["spec_path"]
    _require(effect["kind"] == "proportional_quality" and effect["operation"] == "candidate"
        and effect["spec_dir"] == spec_path and effect["spec_id"] == binding.spec_id
        and effect["run_id"] == binding.recovery["operation"]["binding"]["run_id"]
        and effect["checkpoint_prestate"] == checkpoint_prestate)
    draft = quality_candidate_from_effect_payload(effect["candidate"])
    repair = validate_repair_state(policy["repair"])
    _require(policy["authoring_mode"] == "proportional"
        and draft.repair_number == repair["automatic_consumed"] + repair["extension_consumed"]
        and draft.assessment_index == len(repair["candidate_ids"]))
    if effect["restore_candidate_id"] is None:
        _require(declared is None and effect["restore_candidate_manifest_sha256"] is None
            and effect["restore_artifact_preimage_digests"] is None)
    else:
        from harness.discovery_restoration_completion import continuation_id
        from harness.proportional_quality import (preflight_quality_candidate_restore,
            candidate_artifact_preimage_digests, _validate_restore_candidate)
        _require(declared == continuation_id(binding.recovery["completion_id"])
            and effect["restore_candidate_id"] in repair["candidate_ids"])
        selected = preflight_quality_candidate_restore(project_root=root, spec_dir=root / spec_path,
            manifest_path=run / "quality-candidates" / (effect["restore_candidate_id"] + ".json"),
            expected_candidate_id=effect["restore_candidate_id"],
            expected_manifest_sha256=effect["restore_candidate_manifest_sha256"])
        _validate_restore_candidate(root, selected.snapshot.manifest, run_id=effect["run_id"], spec_id=binding.spec_id)
        _require(selected.snapshot.manifest.run_artifact_root == str(run)
            and effect["restore_artifact_preimage_digests"] == candidate_artifact_preimage_digests(
                root / spec_path, selected.snapshot.manifest, current_candidate=draft))
        if state is not None:
            evidence = state.get("proportional_quality_candidate_evidence", {})
            _require(evidence.get("selected_candidate_id") == effect["restore_candidate_id"]
                and evidence.get("candidate_manifest_sha256") == effect["restore_candidate_manifest_sha256"])
    repair["candidate_ids"] = [*repair["candidate_ids"], draft.candidate_id]
    if repair["baseline_candidate_id"] is None:
        repair["baseline_candidate_id"] = draft.candidate_id
    if state is not None:
        _require(capture_quality_policy(state) == {**policy, "repair": validate_repair_state(repair)})
    sage = project_authoritative_sage_evidence_snapshot(binding.sources, root / spec_path / "issues.md", project_root=root)
    contents = require_projected_authoritative_sage_evidence_snapshot(sage, root / spec_path / "issues.md", project_root=root)
    names = ("spec.md", "requirements-overview.md", "quality-gates.md", "issues.md")
    digests = {name: hashlib.sha256(contents[name]).hexdigest() for name in names if name in contents}
    _require(dict(draft.owned_artifact_digests) == digests and draft.byte_count == len(contents["spec.md"])
        and draft.run_artifact_root == str(run))
    report_path = Path(draft.understanding_evidence).relative_to(root).as_posix()
    report, = (item for item in binding.sources.files if item.path == report_path)
    _require(report.content is not None and report_path.startswith(run.relative_to(root).as_posix() + "/evidence/understanding/")
        and hashlib.sha256(report.content).hexdigest() == draft.understanding_evidence_digest)
    payload = json.loads(report.content, object_pairs_hook=_unique_object, parse_constant=_reject_number)
    _require(payload["status"] == "completed" and payload["phase"] == "phase1-why2"
        and payload["spec"] == dict(path=spec_path + "/spec.md", sha256=digests["spec.md"])
        and draft.normalized_gates == _authoritative_gates(payload)
        and draft.formal_statement_count == payload["requirement_count"])
    issues = {item["issue_id"]: item for item in sage.issues}
    routes = binding.candidate["routing"]["state_updates"]["finding_routes"]["findings"]
    expected = _normalize_finding_routes([{**route, **dict(issues[route["issue_id"]])} for route in routes])
    _require(draft.sage_finding_routes == expected)
    from harness.squad import SquadController
    reasons = SquadController._proportional_candidate_ineligibility(
        {**binding.candidate["routing"]["state_updates"],
            "product_input_mapping_repair": policy["product_input_mapping_repair"]}, expected, sage.issues)
    _require(draft.eligibility_reasons == _normalize_eligibility_reasons(reasons))
    return draft
