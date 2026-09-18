"""Managed Tracker/WHY1 bridge to the existing human-input and publication owners.

No decision is inferred from Markdown. Preparation is detached; only the normal
resolution CAS and completion transaction may publish its candidate.
"""
from dataclasses import asdict
import hashlib
import json

from harness.blocked_decision import validate_blocked_decision
from harness.clarification_candidate import ClarificationRecord, prepare_clarification_candidate
from harness.discovery_bootstrap_state import bootstrap_from_state
from harness.discovery_operation import _capture
from harness.discovery_operation_state import operation_from_state
from harness.discovery_producer import SOURCE_FIELDS, tracker_rounds, identity_spec_tree, producer_phase
from harness.discovery_publication import _seal, _inspect, _graph
from harness.discovery_semantics import captured_artifact_roles
from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope
from harness.element_identity_publication import PublicationIntentRequest, PublicationSourceClaim
from harness.element_identity_snapshot import IdentityHistorySnapshot
from harness.element_identity_store import IdentityStore
from harness.squad_source_baseline_codec import encode_initial_publication_sources, decode_initial_publication_sources
from harness.squad_source_manifest import snapshot_source_manifest
from harness.squad_source_snapshot import PublicationSourcesSnapshot


def question_claim(routing, producer):
    """Read an exact reviewed question; this grants no resolution authority."""
    if producer in {"why2", "alignment"}:
        if producer == "alignment":
            from harness.discovery_assessment import validate_assessment_routing
            validate_assessment_routing(routing, producer)
        else:
            from harness.discovery_spec import validate_spec_routing
            validate_spec_routing(routing, producer)
        updates = routing["state_updates"]
        claim = dict(question=updates.get("escalation_question"),
            recommended_answer=updates.get("escalation_recommended_answer"), risk_level=updates.get("escalation_risk_level"))
    elif producer in {"tracker", "why1"}:
        from harness.discovery_semantics import _tracker_routing
        _tracker_routing(routing, producer)
        claim = {key: routing[key] for key in ("question", "recommended_answer", "risk_level")}
    else:
        raise ValueError("unsupported clarification producer")
    return claim if routing["verdict"] == "STOP_AND_ASK" else None


def _record(decision, producer="tracker"):
    checked = validate_blocked_decision(decision)
    if (checked != decision or checked["status"] != "resolved"
            or checked["source_phase"] != producer_phase(producer) or checked["resolution_handler"] != "clarification_resume"
            or checked["selected_option_id"] is not None):
        raise ValueError("exact free-text Tracker resolution required")
    return ClarificationRecord(checked["id"], checked["question"], checked["answer_text"])


def clarification_target(producer, decision, *, requires_repair):
    """Derive a target from a sealed decision, never grant default authority.

    The parent proof must separately authenticate the actual default envelope
    with require_question_default before this target can be used.
    """
    from harness.human_input import BANZAI_DEFAULT_RECOMMENDED_ACTION
    evidence = [item for item in decision.get("recommendation_evidence", ())
        if item.get("kind") == "banzai_default_candidate"]
    if evidence and (producer != "why2" or len(evidence) != 1
            or decision.get("source_phase") != "phase1-why2" or decision.get("autonomy_mode") != "banzai"
            or decision.get("automatic_eligible") is not True
            or decision.get("recommendation_authority") != "controller_evidence"
            or decision.get("recommended_action") != BANZAI_DEFAULT_RECOMMENDED_ACTION):
        raise ValueError("invalid native default decision")
    return "phase1-what" if requires_repair or evidence else producer_phase(producer)


def require_question_default(routing, producer, decision):
    """Recheck the default against the exact retained provider question."""
    from harness.squad import SquadController
    from harness.human_input import AutonomousDefaultCandidate
    clarification_target(producer, decision, requires_repair=False)
    pending = None
    if producer == "why2":
        question_claim(routing, producer)
        payload = routing["state_updates"].get("autonomous_default_candidate")
        if payload is not None:
            candidate = AutonomousDefaultCandidate.from_provider_payload(payload)
            SquadController._validate_banzai_default_candidate_finding_route(routing["state_updates"], candidate)
            # Native preparation validates but does not seal a default outside
            # Banzai. Forged Banzai evidence in those modes was rejected above.
            if decision.get("autonomy_mode") not in {"guided", "semi"}:
                pending = candidate.to_dict()
    return SquadController._banzai_default_candidate_for_decision(
        {"autonomous_default_candidate": pending}, decision)


def validate_clarification_history(newest_first, *, pending=None):
    """Check prefixes after full native ancestry traversal, without decoding again.

    Bindings must be supplied in their authenticated source-chain order. The
    pending child is not released yet and must not appear in its own history.
    This check establishes no source or publication authority on its own.
    """
    chronological = tuple(reversed(newest_first)) + (() if pending is None else (pending,))
    records, seen = [], set()
    for binding in chronological:
        version, producer = binding.recovery["version"], binding.producer
        if type(version) is not int or (version, producer) not in {
                (5, "tracker"), (7, "why1"), (18, "tracker"), (18, "why1"), (18, "why2"), (40, "alignment"), (41, "alignment")}:
            raise ValueError("unsupported clarification history binding")
        if binding.recovery["previous"] != [asdict(item) for item in records]:
            raise ValueError("clarification prefix differs from native source ancestry")
        record = _record(binding.recovery["resolution"], producer)
        if record.decision_id in seen:
            raise ValueError("duplicate clarification decision in source ancestry")
        seen.add(record.decision_id)
        records.append(record)
    return tuple(records)


def retained_clarification_records(store, *, spec_id, source):
    """Extract records without decoder recursion, after full source authentication.

    Native proof/request equality guards this walk; the caller must also run the
    complete discovery ancestry validator. This is not an admission API.
    """
    from types import SimpleNamespace
    from harness.discovery_completion import _document, _require, _closed
    from harness.squad_completion import validate_retained_completion_proof
    from harness.element_identity_publication import decode_publication_request
    records, seen = [], set()
    while True:
        _closed(source, SOURCE_FIELDS)
        operation_id = "discovery-completion-" + source["dispatch_id"]
        _require(operation_id not in seen)
        seen.add(operation_id)
        row = store.identity_publication(spec_id=spec_id, operation_id=operation_id)
        _require(row is not None and row["state"] == "released")
        proof = _document(row["completion_payload"])
        _require(type(proof["version"]) is int and proof["version"] in {2, 3})
        field = "checkpoint" if proof["version"] == 2 else "proof"
        _closed(proof, ("version", "completion", field))
        _closed(proof[field], ("intent", "receipts"))
        marker, intent, _ = validate_retained_completion_proof(proof["completion"],
            proof[field]["intent"], proof[field]["receipts"])
        _require(source == dict(dispatch_id=marker.completion_id, completion_intent_sha256=marker.intent_sha256,
            completion_receipts_sha256=marker.receipts_sha256, completed_publication_binding_sha256=marker.publication_binding_sha256))
        _require(intent.publication["managed_discovery"] == dict(version=1, request=row["request"]))
        request = decode_publication_request(row["request"])
        recovery = _document(request.recovery_payload)
        _require(recovery["completion_id"] == source["dispatch_id"])
        producer, version = recovery.get("producer", "discovery"), recovery["version"]
        versions = {"discovery": {2, 8}, "synthesizer": {3, 9}, "tracker": {4, 5, 10, 18},
            "why1": {6, 7, 11, 18}, "constitution": {12, 16}, "what": {13, 17, 20, 22, 26},
            "understanding": {14}, "why2": {15, 18, 19, 24}, "why2-policy": {21, 23, 25, 27},
            "lexicon": {28}, "lexicon_gate": {29}, "checkpoint": {30}, "feasibility": {31, 33},
            "feasibility_gate": {32, 34}, "strategy": {35}, "alignment": {36, 38, 40, 41}, "alignment_gate": {37, 39}}
        _require(type(version) is int and version in versions.get(producer, set()))
        if version in {5, 7, 18, 40, 41}:
            _require(intent.origin == "resolution" and intent.route["decision_id"] == recovery["resolution"]["id"])
            records.append(SimpleNamespace(producer=producer, recovery=recovery))
        source = recovery.get("source_completion")
        if source is None:
            _require(producer == "discovery" and type(version) is int and version == 2)
            return validate_clarification_history(records)


def previous_records(state, operation_id, producer="tracker"):
    return _previous_records(state, operation_id, producer, set())


def _resolution_rows(state, producer):
    """Existing round associations, including WHAT consuming a WHY2 answer."""
    rounds = tracker_rounds(state, producer)
    result = [(row, row["resolution"]) for row in (() if rounds is None else rounds["rounds"].values())
        if row["resolution"] is not None]
    if producer == "why2":
        requirements = tracker_rounds(state, "what")
        result.extend((row, row["review_resolution"]) for row in (
            () if requirements is None else requirements["rounds"].values()) if "review_resolution" in row)
    return tuple((row, association) for row, association in result
        if association["decision"]["resolution_handler"] == "clarification_resume")


def capture_clarification_history(state, operation_id, producer, native_previous):
    """Keep original formats unless the authenticated history crosses WHY2."""
    if producer == "alignment":
        return 40, native_previous
    if producer not in {"tracker", "why1", "why2"}:
        raise ValueError("unsupported clarification producer")
    why2_answers = {association["decision"]["id"] for _, association in _resolution_rows(state, "why2")}
    if producer == "why2" or any(record.decision_id in why2_answers for record in native_previous):
        return 18, native_previous
    previous = previous_records(state, operation_id, producer)
    if previous != native_previous:
        raise ValueError("legacy clarification history differs from authenticated native ancestry")
    return (5 if producer == "tracker" else 7), previous


def _previous_records(state, operation_id, producer, seen):
    rounds = tracker_rounds(state, producer)["rounds"]
    # Follow protected round ancestry, not JSON object ordering.
    records = []
    while True:
        if (producer, operation_id) in seen or operation_id not in rounds:
            raise ValueError("invalid clarification ancestry")
        seen.add((producer, operation_id))
        row = rounds[operation_id]
        if "refresh" in row:
            if producer == "why1" and "execution_input" in row:
                previous = _previous_records(state, row["tracker_parent"], "tracker", seen)
                return previous + tuple(reversed(records))
            if producer == "tracker":
                why1 = tracker_rounds(state, "why1")
                matches = [] if why1 is None else [item for item in why1["rounds"].values()
                    if item.get("refresh", {}).get("repair_unit") == row["refresh"]["repair_unit"]]
                if len(matches) != 1:
                    raise ValueError("Tracker refresh requires its requesting WHY1 history")
                previous = _previous_records(state, matches[0]["predecessor"], "why1", seen)
                return previous + tuple(reversed(records))
            # An inactive refresh is not a human answer or a new history root.
            operation_id = row["predecessor"]
            continue
        resolution = row["resolution"]
        if resolution is None:
            break
        records.append(_record(resolution["decision"], producer))
        operation_id = row["predecessor"]
    previous = ()
    if producer == "why1":
        tracker = tracker_rounds(state)
        if tracker is None:
            raise ValueError("WHY1 requires retained Tracker ancestry")
        parent = row.get("tracker_parent")
        if parent is None:
            # Legacy roots remain readable before refresh execution. An empty
            # refresh association is not new history; never guess after one ran.
            if any("refresh" in item and item["operation"] is not None for item in tracker["rounds"].values()):
                raise ValueError("historical WHY1 Tracker parent must be pinned")
            parent = tracker["active"]
            while "refresh" in tracker["rounds"][parent]:
                parent = tracker["rounds"][parent]["predecessor"]
        previous = _previous_records(state, parent, "tracker", seen)
    return previous + tuple(reversed(records))


def _candidate(sources, spec_path, run_path, decision, previous, producer="tracker"):
    spec, = (tree for tree in sources.trees if tree.path == spec_path)
    texts = {item.path[len(spec_path) + 1:]: item.content.decode("utf-8")
        for item in identity_spec_tree(spec).files if item.path.endswith(".md")}
    staging = run_path + "/staging/"
    files = {item.path: None if item.content is None else item.content.decode("utf-8") for item in sources.files
        if item.path.startswith(staging)}
    candidate = prepare_clarification_candidate(decision=_record(decision, producer), previous=previous,
        receipt_before=files[staging + "user-clarifications.md"],
        policy_before=files[staging + "feature-policy.json"], artifacts=texts)
    writes = {staging + "user-clarifications.md": candidate.receipt_text,
        staging + "feature-policy.json": candidate.policy_text,
        staging + "feature-policy.md": candidate.policy_context_text,
        spec_path + "/feature-policy-reconciliation.md": candidate.reconciliation_text}
    return candidate, writes, texts


def prepare(root, state_store, *, state, resolved, completion_id, producer="tracker"):
    from harness.discovery_completion import _json, _hash, decode_binding
    selected = bootstrap_from_state(state)
    operation = operation_from_state(state, producer)
    selection = selected["selection"]
    source = {key: state["last_dispatch"][key] for key in SOURCE_FIELDS}
    store = IdentityStore.open(root)
    commander = None
    if producer == "alignment":
        from harness.discovery_assessment import require_alignment_question_parent, require_alignment_answer
        from harness.managed_commander import resolution_receipt
        parent = require_alignment_question_parent(root, state_store.squad_dir, state, source)
        policy = require_alignment_answer(root, state, resolved, parent.candidate["routing"])
        commander = resolution_receipt(state_store.squad_dir, state, resolved, policy)
    _, _, _, history, _, _, original, source_inputs = _capture(root, state_store, store, selected,
        operation["binding"]["input_tree"], tuple(operation["binding"]["artifact_paths"]),
        producer=producer, source_completion=source, clarification=producer in {"why2", "alignment"})
    native_previous = retained_clarification_records(store, spec_id=selection["spec_id"], source=source)
    version, previous = capture_clarification_history(state, operation["binding"]["operation_id"], producer, native_previous)
    candidate, texts, before = _candidate(original, selection["spec_path"],
        state_store.squad_dir.relative_to(root).as_posix(), resolved, previous, producer)
    spec_path = selection["spec_path"]
    report = "feature-policy-reconciliation.md"
    from harness.discovery_producer import post_why1_context
    post_review = post_why1_context(state, producer)
    roles = captured_artifact_roles(producer, after_review=post_review)
    artifacts = tuple(CandidateArtifact(name, roles[name], text,
        candidate.reconciliation_text if name == report else text) for name, text in before.items())
    if report not in before:
        artifacts += (CandidateArtifact(report, "references", None, candidate.reconciliation_text),)
    artifacts += tuple(CandidateArtifact(path, "references", None, text)
        for path, text in texts.items() if path != spec_path + "/" + report)
    scope_paths = (report, *(path for path in texts if path != spec_path + "/" + report))
    from harness.discovery_candidate import issue_report_changes
    reports, _ = issue_report_changes(artifacts, (), history, report_id=completion_id) if producer in {"why1", "why2", "alignment"} or post_review else ((), ())
    preview = store.preview_identity_candidate(spec_id=selection["spec_id"], artifacts=artifacts,
        scope=IdentityEditScope(scope_paths, (), scope_paths), operations=(), issue_reports=reports)
    if preview.check.diagnostics or preview.history != history:
        raise ValueError("clarification identity reconciliation required")
    writes = {path: text.encode("utf-8") for path, text in texts.items()}
    modes = {item.path: item.image.mode for tree in original.trees for item in tree.files}
    modes.update({item.path: item.image.mode for item in original.files if item.content is not None})
    provisional = _seal(root, state_store.squad_dir, writes, modes)
    staged = _inspect(provisional, original, writes, modes)
    graph = _graph(staged, history, selection)
    writes[spec_path + "/spec-artifact-graph.json"] = graph
    publication = _seal(root, state_store.squad_dir, writes, modes)
    sources = _inspect(publication, original, writes, modes)
    if _graph(sources, history, selection) != graph or state_store.load() != state:
        raise ValueError("clarification inputs changed")
    spec, = (tree for tree in sources.trees if tree.path == spec_path)
    baseline = PublicationSourcesSnapshot(sources.publication, (identity_spec_tree(spec),), ())
    recovery = dict(version=version, producer=producer, completion_id=completion_id, operation=operation,
        source_completion=source, resolution=resolved, previous=[asdict(row) for row in previous],
        source_inputs=_json(source_inputs), source_fingerprint=_hash(source_inputs),
        candidate_inputs=_json(dict(artifacts=texts, history=asdict(history))),
        sources=encode_initial_publication_sources(sources), graph_sha256=hashlib.sha256(graph).hexdigest())
    if producer == "alignment":
        recovery.update(before=state, commander_receipt=commander)
    context = source_inputs["authority"]["source_context"]
    request = PublicationIntentRequest(publication.marker.manifest_sha256, _json(recovery), (),
        PublicationSourceClaim(context["context_id"], context["operation_id"], encode_initial_publication_sources(baseline)),
        proposed_history_sha256=history.sha256)
    from harness.element_identity_publication import encode_publication_request
    decode_binding(dict(kind="external", marker=publication.marker.to_dict(),
        managed_discovery=dict(version=1, request=encode_publication_request(request))), completion_id=completion_id, state=state)
    provisional.discard()
    return publication, request, candidate


def bind_alignment_effects(publication, request, effects, state):
    """Bind the existing native effects; v40 remains a detached-only draft."""
    from dataclasses import replace
    from harness.discovery_completion import _document, _require, _json, decode_binding
    from harness.element_identity_publication import encode_publication_request
    recovery = _document(request.recovery_payload)
    _require(recovery["version"] == 40)
    recovery.update(version=41, effects=dict(route=effects.route, state_updates=effects.state_updates,
        state_removals=sorted(effects.state_removals)))
    request = replace(request, recovery_payload=_json(recovery))
    decode_binding(dict(kind="external", marker=publication.marker.to_dict(),
        managed_discovery=dict(version=1, request=encode_publication_request(request))), state=state)
    return request


def _require_alignment_effects(recovery, prepared, run_path, publication, state):
    from pathlib import Path
    from harness.discovery_completion import _require, _json
    from harness.discovery_policy_resolution import _require_resolved_effects
    from harness.squad import SquadController
    before = recovery["before"]
    reader = object.__new__(SquadController)
    reader._squad_dir = Path(bootstrap_from_state(before)["selection"]["project_root"]) / run_path
    report = json.loads(prepared.reconciliation_json)
    route = clarification_target("alignment", recovery["resolution"], requires_repair=report["requires_repair"])
    effects = reader._clarification_state_effects(before, route, json.loads(prepared.policy_text), report)
    _require(_json(recovery["effects"]) == _json(dict(route=effects.route,
        state_updates=effects.state_updates, state_removals=sorted(effects.state_removals))))
    if state is None or _json(state) == _json(before):
        return
    _require(_json(state["blocked_decision"]) == _json(recovery["resolution"]))
    _require_resolved_effects(state, recovery, publication)
    _require(_json({key: state.get(key) for key in effects.state_updates if key != "status"})
        == _json({key: value for key, value in effects.state_updates.items() if key != "status"}))
    charge = (recovery["commander_receipt"] or {}).get("token_usage", 0)
    _require(type(state["token_usage"]) is int and state["token_usage"] == before["token_usage"] + charge)
    # Native answer/completion owns these lifecycle fields. Every other field
    # (including budgets, ancestry, dispatch and gate evidence) stays unchanged.
    changing = set(effects.state_updates) | set(effects.state_removals) | {
        "blocked_decision", "recovery_instruction", "token_usage", "state_revision", "updated_at",
        "blocked_reason", "escalation_question", "escalation_options", "escalation_resolved",
        "autonomous_default_candidate", "pending_controller_completion", "pending_external_publication",
        "external_publication_failure", "controller_completion_failure", "last_human_input_completion"}
    _require(_json({key: value for key, value in state.items() if key not in changing})
        == _json({key: value for key, value in before.items() if key not in changing}))


def decode_clarification_binding(publication, request, recovery, completion_id, state):
    from harness.discovery_completion import _closed, _require, _document, _hash, DiscoveryCompletionBinding
    _closed(recovery, ("version", "producer", "completion_id", "operation", "source_completion", "resolution",
        "previous", "source_inputs", "source_fingerprint", "candidate_inputs", "sources", "graph_sha256",
        *(("before", "commander_receipt") if recovery.get("version") in {40, 41} else ()),
        *(("effects",) if recovery.get("version") == 41 else ())))
    producer = recovery["producer"]
    _require(type(recovery["version"]) is int and ((recovery["version"], producer) in {
            (5, "tracker"), (7, "why1"), (18, "tracker"), (18, "why1"), (18, "why2"), (40, "alignment"), (41, "alignment")})
        and (completion_id is None or completion_id == recovery["completion_id"]) and request.operations == ())
    source = _document(recovery["source_inputs"])
    _closed(source, ("manifest", "history", "authority", "runtime", *(("quality_policy",) if producer == "why2" else ())))
    if producer == "why2":
        from harness.discovery_quality import validate_quality_policy
        validate_quality_policy(source["quality_policy"])
    _require(_hash(source) == recovery["source_fingerprint"])
    candidate = _document(recovery["candidate_inputs"])
    _closed(candidate, ("artifacts", "history"))
    _require(candidate["history"] == source["history"] and candidate["history"]["sha256"] == request.proposed_history_sha256)
    history = IdentityHistorySnapshot(**source["history"])
    _require(hashlib.sha256(history.payload.encode("ascii")).hexdigest() == history.sha256)
    sources = decode_initial_publication_sources(recovery["sources"])
    baseline = decode_initial_publication_sources(request.sources.baseline_payload)
    _require(sources.publication == baseline.publication and sources.publication.marker.to_dict() == publication["marker"]
        and request.manifest_sha256 == sources.publication.marker.manifest_sha256
        and asdict(snapshot_source_manifest(trees=sources.trees, files=sources.files)) == source["manifest"])
    genesis, context = source["authority"]["managed_identity"], source["authority"]["source_context"]
    spec_path = genesis["spec_path"]
    spec, = (tree for tree in sources.trees if tree.path == spec_path)
    _require(baseline.trees == (identity_spec_tree(spec),) and baseline.files == ()
        and request.sources.context_id == genesis["context_id"] == context["context_id"]
        and request.sources.expected_operation_id == context["operation_id"]
        and asdict(snapshot_source_manifest(trees=baseline.trees, files=())) == context["manifest"])
    _closed(recovery["source_completion"], SOURCE_FIELDS)
    _require(request.sources.expected_operation_id == "discovery-completion-" + recovery["source_completion"]["dispatch_id"])
    selected = recovery["operation"]["binding"]
    # The selected spec/input trees may also be named context. Only the
    # separately captured runtime context identifies the run's staging owner.
    context_tree, = (tree for tree in sources.trees if tree.path.endswith("/context")
        and tree.path not in {spec_path, selected["input_tree"]})
    run_path = context_tree.path.removesuffix("/context")
    previous = tuple(ClarificationRecord(**row) for row in recovery["previous"])
    prepared, texts, _ = _candidate(sources, spec_path, run_path, recovery["resolution"], previous, producer)
    if producer == "alignment":
        from harness.discovery_completion import _json
        from harness.human_input import AppliedHumanInputResolution
        from harness.squad import SquadController
        from harness.squad_state import build_human_input_resolution_postimage
        before, resolved, commander = recovery["before"], recovery["resolution"], recovery["commander_receipt"]
        decision = validate_blocked_decision(before["blocked_decision"])
        answer = AppliedHumanInputResolution(None, resolved["answer_text"], resolved["resolved_by"],
            rationale=resolved["resolution_rationale"], confidence=resolved["resolution_confidence"])
        _require(before["phase"] == "phase2-tracker-alignment" and before["status"] == "blocked"
            and before["autonomy_mode"] == resolved["autonomy_mode"] and before["managed_identity"] == genesis
            and before["last_dispatch"]["post_dispatch_complete"] is True
            and recovery["source_completion"] == {key: before["last_dispatch"][key] for key in SOURCE_FIELDS}
            and _json(build_human_input_resolution_postimage(decision, answer,
                resolved_at=resolved["resolved_at"])) == _json(resolved)
            and resolved["resolved_by"] in {"user", "COMMANDER"})
        SquadController._validate_human_input_resolver(decision, answer)
        if resolved["resolved_by"] == "COMMANDER":
            import re
            _closed(commander, ("sha256", "token_usage"))
            _require(decision["automatic_eligible"] is True and type(commander["sha256"]) is str
                and re.fullmatch(r"[0-9a-f]{64}", commander["sha256"])
                and type(commander["token_usage"]) is int and commander["token_usage"] >= 0)
        else:
            _require(commander is None and not (decision["autonomy_mode"] == "banzai" and decision["automatic_eligible"] is True))
        if recovery["version"] == 40:
            # Detached drafts never acquire native application authority.
            _require(state is None or _json(state) == _json(before))
        else:
            _require_alignment_effects(recovery, prepared, run_path, publication, state)
    _require(candidate["artifacts"] == texts)
    writes = {path: text.encode("utf-8") for path, text in texts.items()}
    graph = _graph(sources, history, dict(spec_id=selected["spec_id"], spec_path=spec_path))
    _require(hashlib.sha256(graph).hexdigest() == recovery["graph_sha256"])
    writes[spec_path + "/spec-artifact-graph.json"] = graph
    modes = {item.path: item.image.mode for tree in sources.trees for item in tree.files}
    modes.update({item.path: item.image.mode for item in sources.files if item.content is not None})
    operations = sources.publication.operations
    _require(sources.publication.promoted_prefix == 0 and len(operations) == len(writes)
        and {op.target for op in operations} == set(writes)
        and all(op.action == "write" and op.postimage_bytes == writes[op.target]
            and op.postimage.mode == modes.get(op.target, 0o644) for op in operations))
    if state is not None:
        bootstrap = bootstrap_from_state(state)
        _require(bootstrap is not None and state["managed_identity"] == genesis
            and selected["run_id"] == bootstrap["selection"]["run_id"]
            and selected["spec_id"] == bootstrap["selection"]["spec_id"]
            and operation_from_state(state, producer, operation_id=selected["operation_id"]) == recovery["operation"])
        if recovery["version"] in {18, 40, 41}:
            # Chronology/completeness is checked against native ancestry by
            # authenticate and retained reads, never inferred from this set.
            known = {}
            for owner in ("tracker", "why1", "why2", "alignment"):
                for _, association in _resolution_rows(state, owner):
                    record = _record(association["decision"], owner)
                    _require(record.decision_id not in known or known[record.decision_id] == record)
                    known[record.decision_id] = record
            _require(len({record.decision_id for record in previous}) == len(previous)
                and all(known.get(record.decision_id) == record for record in previous))
        else:
            _require(previous_records(state, selected["operation_id"], producer) == previous)
        associations = _resolution_rows(state, producer)
        decisions = [state.get("blocked_decision"), *(association["decision"] for _, association in associations)]
        current = next((item for item in decisions if item and item["id"] == recovery["resolution"]["id"]), None)
        _require(current is not None)
        rounds = tracker_rounds(state, producer)
        successors = [(row, association) for row, association in associations
            if association["decision"]["id"] == recovery["resolution"]["id"]]
        if successors:
            (successor, association), = successors
            from harness.discovery_spec import clarification_source
            _require(successor.get("review_parent", successor["predecessor"]) == selected["operation_id"]
                and successor["source"] == (clarification_source(association["completion"])
                    if producer == "why2" else recovery["source_completion"])
                and association["completion"]["completion_id"] == recovery["completion_id"])
        else:
            dispatch = state.get("last_dispatch") or {}
            _require(rounds["active"] == selected["operation_id"] and state["blocked_decision"]["id"] == current["id"]
                and dispatch.get("phase_id") == producer_phase(producer) and dispatch.get("post_dispatch_complete") is True
                and {key: dispatch.get(key) for key in SOURCE_FIELDS} == recovery["source_completion"])
        if current["status"] == "resolved":
            _require(current == recovery["resolution"])
        else:
            from harness.squad_state import build_human_input_resolution_postimage
            from harness.human_input import AppliedHumanInputResolution
            resolved = recovery["resolution"]
            answer = AppliedHumanInputResolution(None, resolved["answer_text"], resolved["resolved_by"],
                rationale=resolved.get("resolution_rationale"), confidence=resolved.get("resolution_confidence"))
            _require(build_human_input_resolution_postimage(current, answer, resolved_at=resolved["resolved_at"]) == resolved)
    # Derived from the authenticated report; never accepted from provider prose
    # or a caller-supplied destination. Preserve the legacy reconciliation route.
    candidate["route"] = clarification_target(producer, recovery["resolution"],
        requires_repair=json.loads(prepared.reconciliation_json)["requires_repair"])
    return DiscoveryCompletionBinding(request, recovery, candidate, source, sources, baseline)


def require_parent(state, binding, store, *, root=None, run=None):
    """Authenticate the exact retained Tracker result that asked this question."""
    from harness.discovery_completion import _document, _require, decode_binding
    from harness.squad_completion import validate_retained_completion_proof
    from harness.element_identity_publication import encode_publication_request
    source = binding.recovery["source_completion"]
    retained = store.identity_publication(spec_id=binding.spec_id,
        operation_id="discovery-completion-" + source["dispatch_id"])
    _require(retained is not None and retained["state"] == "released")
    proof = _document(retained["completion_payload"])
    marker, intent, _ = validate_retained_completion_proof(proof["completion"], proof["proof"]["intent"], proof["proof"]["receipts"])
    _require(source == dict(dispatch_id=marker.completion_id, completion_intent_sha256=marker.intent_sha256,
        completion_receipts_sha256=marker.receipts_sha256, completed_publication_binding_sha256=marker.publication_binding_sha256))
    parent = decode_binding(intent.publication, completion_id=marker.completion_id, state=state)
    _require(parent is not None and parent.producer == binding.producer and not parent.clarification
        and parent.recovery["operation"] == binding.recovery["operation"]
        and retained["request"] == encode_publication_request(parent.request))
    decision = binding.recovery["resolution"]
    _require(question_claim(parent.candidate["routing"], binding.producer) == {
        key: decision[key] for key in ("question", "recommended_answer", "risk_level")})
    require_question_default(parent.candidate["routing"], binding.producer, decision)
    if binding.producer == "alignment":
        from harness.discovery_assessment import require_alignment_answer, require_alignment_question_evidence
        from harness.managed_commander import resolution_receipt
        before = binding.recovery["before"]
        require_alignment_question_evidence(root, run, before, source)
        policy = require_alignment_answer(root, before, decision, parent.candidate["routing"])
        _require(resolution_receipt(run, before, decision, policy) == binding.recovery["commander_receipt"])


def require_resolution_receipt(state, binding, marker):
    from harness.discovery_completion import _require
    expected = dict(schema_version=1, completion_id=marker.completion_id, intent_sha256=marker.intent_sha256,
        receipts_sha256=marker.receipts_sha256, publication_binding_sha256=marker.publication_binding_sha256,
        decision_id=binding.recovery["resolution"]["id"])
    producer = binding.producer
    receipts = [state.get("last_human_input_completion"), *(association["completion"]
        for _, association in _resolution_rows(state, producer))]
    _require(expected in receipts)
