"""Inactive discovery composition: selected inputs to a reviewed candidate.

The runtime caller owns execution leases and complete dependency-domain admission.
This module neither publishes artifacts nor advances accepted identity history.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import re

from harness.discovery_bootstrap_state import bootstrap_from_state
from harness.discovery_candidate import author_artifacts, build_discovery_changes, issue_report_changes
from harness.discovery_inputs import DiscoveryInputError, admit_runtime_inputs, runtime_input_paths
from harness.discovery_operation_state import operation_from_state
from harness.discovery_reservations import DiscoveryReservationJournal
from harness.discovery_semantics import DiscoveryAssignment, artifact_roles
from harness.discovery_producer import producer_component, producer_operation_id, synthesis_source, tracker_input_source
from harness.discovery_turns import read_discovery_usage, run_discovery_step
from harness.element_artifacts import parse_identity_artifact
from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope
from harness.element_identity_publication import PublicationOperation
from harness.element_identity_request_codec import encode_request
from harness.element_identity_store import IdentityStore
from harness.element_identity_snapshot import IdentityHistorySnapshot
from harness.product_inventory import CONTROL_PATHS, CONTROL_ROOTS
from harness.squad_publication import load_prepared_publication
from harness.squad_source_manifest import snapshot_source_manifest


@dataclass(frozen=True)
class ReviewedDiscoveryCandidate:
    artifacts: tuple[CandidateArtifact, ...]
    operations: tuple[PublicationOperation, ...]
    history: IdentityHistorySnapshot
    source_fingerprint: str
    review: dict
    candidate_sha256: str
    candidate_inputs: str
    source_inputs: str


@dataclass(frozen=True)
class DiscoveryOperationResult:
    status: str
    reason: str
    token_usage: int | None
    dispatch_count: int
    candidate: ReviewedDiscoveryCandidate | None = None


class _Blocked(ValueError):
    pass


def _hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def _overlap(left, right):
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def _capture(root, state_store, store, selected, input_tree, artifact_paths, *, repair_unit=None, producer="discovery", source_completion=None):
    spec_path = selected["selection"]["spec_path"]
    denied = (*CONTROL_ROOTS, *CONTROL_PATHS, str(state_store.squad_dir.relative_to(root)))
    if any(_overlap(input_tree, path) for path in (*denied, spec_path)):
        raise _Blocked("discovery_input_tree_not_admitted")
    prepared = load_prepared_publication(root, state_store.squad_dir, selected["selection"]["capture_marker"])
    template_paths = {f".echelon/runtime/templates/{path.removesuffix('.md')}-template.md": path for path in artifact_paths}
    runtime_trees, runtime_files = runtime_input_paths(root, state_store.squad_dir)
    staging_paths = tuple((state_store.staging_dir / name).relative_to(root).as_posix() for name in (
        "user-clarifications.md", "feature-policy.json", "feature-policy.md")) if producer in {"tracker", "why1"} or repair_unit is not None else ()
    reasoning_paths = ((state_store.squad_dir / "reasoning-journal.jsonl").relative_to(root).as_posix(),) if producer == "why1" or repair_unit is not None else ()
    if producer == "why1":
        template_paths = {".echelon/prosaic/agents/exploration/templates/sage-assumption-review-template.md": "assumption-review.md",
            ".echelon/prosaic/agents/exploration/templates/sage-issues-template.md": "issues.md",
            ".echelon/runtime/templates/unknowns-template.md": "unknowns.md"}
    if repair_unit is not None and state_store.load().get("managed_why1_rounds") is not None:
        template_paths.update({".echelon/prosaic/agents/exploration/templates/sage-assumption-review-template.md": "assumption-review.md",
            ".echelon/prosaic/agents/exploration/templates/sage-issues-template.md": "issues.md"})
    spec_view = runtime_view = None
    if producer in {"synthesizer", "tracker", "why1"}:
        from harness.discovery_completion import released_discovery_input_projectors
        if repair_unit is not None:
            raise _Blocked("synthesis_repair_not_admitted")
        state = state_store.load()
        spec_view, runtime_view = released_discovery_input_projectors(root, state_store.squad_dir, state,
            source=source_completion if source_completion is not None else (
                tracker_input_source(state, producer=producer) if producer in {"tracker", "why1"} else synthesis_source(state)))
    if repair_unit is not None:
        from harness.discovery_repair_state import repairs_from_state
        from harness.discovery_completion import released_discovery_input_projectors
        state = state_store.load()
        repair = repairs_from_state(state)["units"][repair_unit]["selection"]
        if tuple(repair["artifact_paths"]) != artifact_paths:
            raise _Blocked("discovery_repair_scope_changed")
        spec_view, runtime_view = released_discovery_input_projectors(root, state_store.squad_dir, state,
            source=repair["source"])
    with prepared.inspect_sources(tree_paths=(spec_path, input_tree, *runtime_trees),
            file_paths=(*template_paths, *runtime_files, *staging_paths, *reasoning_paths)) as sources:
        if sources.publication.operations:
            raise _Blocked("discovery_capture_contains_publication")
        state = state_store.load()
        if producer == "tracker":
            from harness.discovery_producer import tracker_round
            if tracker_round(state)["resolution"] is None and any(
                    item.content is not None for item in sources.files if item.path in staging_paths):
                raise _Blocked("unproven_tracker_clarification_inputs")
        runtime, documents = admit_runtime_inputs(root, state_store.squad_dir, state,
            sources if runtime_view is None else runtime_view(sources))
        if runtime_view is not None:
            # Admission used the authenticated original context. Model input
            # must instead contain the just-validated current context bytes.
            documents.update({item.path: item.content.decode("utf-8")
                for tree in sources.trees if tree.path == runtime_trees[0] for item in tree.files})
        observed = store.check_managed_context(spec_id=selected["selection"]["spec_id"],
            run_id=selected["selection"]["run_id"], record=state["managed_identity"])
        spec, = (tree for tree in sources.trees if tree.path == spec_path)
        if spec_view is not None:
            spec = spec_view(spec)
        inputs, = (tree for tree in sources.trees if tree.path == input_tree)
        if not inputs.exists:
            raise _Blocked("discovery_inputs_missing")
        manifest = snapshot_source_manifest(trees=(spec,), files=())
        if manifest.payload != observed["source_context"]["manifest"]["payload"]:
            raise _Blocked("discovery_source_baseline_changed")
        history = store.identity_history(spec_id=selected["selection"]["spec_id"])
        files = {}
        for item in spec.files:
            logical = item.path[len(spec_path) + 1:]
            if spec_view is not None and logical == "spec-artifact-graph.json":
                # Exact derived bytes were authenticated above; it is not an
                # editable Markdown artifact or provider-authored definition.
                continue
            if logical not in artifact_roles("why1" if repair_unit is not None else producer):
                raise _Blocked("unsupported_discovery_source_role")
            files[logical] = item.content.decode("utf-8")
        evidence = {item.path: item.content.decode("utf-8") for item in inputs.files}
        evidence.update(documents)
        evidence.update({item.path: item.content.decode("utf-8") for item in sources.files
            if item.path in staging_paths and item.content is not None})
        if reasoning_paths:
            from harness.reasoning_journal_store import read_reasoning_journal
            journal, = (item for item in sources.files if item.path in reasoning_paths)
            content, _ = read_reasoning_journal(root / journal.path)
            if content != (journal.content or b""):
                raise _Blocked("discovery_reasoning_context_changed")
            if journal.content is not None:
                evidence[journal.path] = journal.content.decode("utf-8")
        if any(item.content is None for item in sources.files if item.path in template_paths):
            raise _Blocked("discovery_template_missing")
        templates = {template_paths[item.path]: item.content.decode("utf-8") for item in sources.files if item.path in template_paths}
        if any("\x00" in content for content in (*files.values(), *evidence.values(), *templates.values())):
            raise _Blocked("discovery_source_not_text")
        source_inputs = dict(manifest=asdict(snapshot_source_manifest(trees=sources.trees, files=sources.files)),
            history=asdict(history), authority=observed, runtime=runtime)
        digest = _hash(source_inputs)
    # Normal inspector exit authenticates paths and membership before handoff.
    return digest, files, evidence, history, templates, runtime, sources, source_inputs


def capture_discovery_repair_inputs(project_root, state_store, unit_id):
    """Read one selected accepted baseline; caller owns execution leases.

    This grants no requesting-review provenance and does not select an operation,
    consume attempts, dispatch providers or publish. The raw snapshot is retained
    for subsequent input fingerprints and publication guards.
    """
    from harness.discovery_repair_state import repairs_from_state
    try:
        root = Path(project_root)
        state = state_store.load()
        selected = bootstrap_from_state(state)
        if (selected is None or str(root) != selected["selection"]["project_root"]
                or str(state_store.squad_dir) != selected["selection"]["run_dir"]):
            raise ValueError("independent repair selection changed")
        repair = repairs_from_state(state)["units"][unit_id]["selection"]
        operation = operation_from_state(state)
        result = _capture(root, state_store, IdentityStore.open(root), selected,
            operation["binding"]["input_tree"], tuple(repair["artifact_paths"]), repair_unit=unit_id)
        if state_store.load() != state:
            raise ValueError("repair selection changed during capture")
        return result
    except Exception:
        pass
    raise DiscoveryInputError("discovery_repair_inputs_require_reconciliation")


def _citations(artifacts, labels):
    citations = {}
    for artifact in artifacts:
        if artifact.role not in {"unknowns", "assumptions", "intent", "issues"} or artifact.after_text is None:
            continue
        parsed = parse_identity_artifact(path=artifact.path, role=artifact.role, text=artifact.after_text)
        for declaration in parsed.declarations:
            if declaration.element_id in labels:
                digest = hashlib.sha256(artifact.after_text.encode("utf-8")).hexdigest()
                citations[declaration.element_id] = f"candidate:{artifact.path}:{digest}#{declaration.element_id}"
    if set(citations) != set(labels):
        raise _Blocked("discovery_review_definition_mismatch")
    return citations


def _progress(artifacts, findings, *, routing=None):
    def normalized(text):
        # Formatting and label changes alone cannot make a failed attempt progress.
        return None if text is None else " ".join(re.sub(r"\b(?:U|A|UI|II|ISS)-[0-9]+\b", "<identity>", text).split())
    content = {key: normalized(value) for key, value in artifacts.items()}
    rows = sorted(normalized(json.dumps(row, sort_keys=True, ensure_ascii=False)) for row in findings)
    record = dict(content=content, findings=rows)
    if routing is not None:
        record["routing"] = {key: normalized(value) for key, value in routing.items()}
    return _hash(record)


def run_discovery_operation(project_root, state_store, executor, *, input_tree, artifact_paths,
        editable_revisions=(), unowned_writable_paths=(), intent, create=False,
        token_budget=None, dispatch_limit=297, replay_only=False, producer="discovery", repair_unit=None) -> DiscoveryOperationResult:
    """Compose at most three attempts; exact receipts make restart a read replay."""
    last = None
    retained_usage = read_discovery_usage(state_store, producer, repair_unit=repair_unit)
    try:
        root = Path(project_root)
        state = state_store.load()
        producer_args = {} if producer == "discovery" else {"producer": producer}
        if repair_unit is not None:
            producer_args["repair_unit"] = repair_unit
        if type(replay_only) is not bool:
            raise _Blocked("invalid_discovery_replay_mode")
        if replay_only:
            retained = operation_from_state(state, producer, repair_unit=repair_unit)
            if (create or retained is None or not retained["attempts"]
                    or (retained["attempts"][-1]["result"] or {}).get("status") != "accepted"):
                raise _Blocked("accepted_discovery_operation_required")
        selected = bootstrap_from_state(state)
        if selected is None or "managed_identity" not in state or str(root) != selected["selection"]["project_root"]:
            raise _Blocked("completed_discovery_bootstrap_required")
        if type(create) is not bool or create == (producer_component(state, producer, "operation", repair_unit=repair_unit) is not None):
            raise _Blocked("discovery_operation_selection_conflict")
        if any(type(value) is not tuple for value in (artifact_paths, editable_revisions, unowned_writable_paths)):
            raise _Blocked("invalid_discovery_scope")
        store = IdentityStore.open(root)
        fingerprint, before, evidence, retained_history, templates, runtime, _, source_inputs = _capture(root, state_store, store, selected, input_tree, artifact_paths, **producer_args)
        binding = dict(operation_id=producer_operation_id(state, producer, repair_unit=repair_unit), spec_id=selected["selection"]["spec_id"],
            run_id=selected["selection"]["run_id"], input_tree=input_tree, artifact_paths=list(artifact_paths),
            editable_revisions=[list(pair) for pair in editable_revisions], unowned_writable_paths=list(unowned_writable_paths),
            intent=deepcopy(intent), fingerprint=fingerprint)
        state = state_store.advance_discovery_operation(binding, "prepare", **producer_args)
        def check_inputs():
            return _capture(root, state_store, store, selected, input_tree, artifact_paths, **producer_args)[0]
        def verify():
            if check_inputs() != fingerprint:
                raise _Blocked("discovery_operation_inputs_changed")
        with DiscoveryReservationJournal(state_store.squad_dir, **producer_args,
                round_operation_id=binding["operation_id"] if producer in {"tracker", "why1"} else None) as journal:
            journal.select(store, spec_id=binding["spec_id"], run_id=binding["run_id"],
                operation_id=binding["operation_id"], managed_identity=state["managed_identity"], create=create)
            history_rows = json.loads(retained_history.payload)
            subjects = {row["element_id"]: row for row in history_rows["entities"]}
            for label, revision in editable_revisions:
                if label not in subjects or subjects[label]["revision"] != revision:
                    raise _Blocked("discovery_editable_revision_changed")
            feedback, prior_progress = None, None
            for number in (1, 2, 3):
                current = operation_from_state(state_store.load(), producer, repair_unit=repair_unit)
                if len(current["attempts"]) < number:
                    if replay_only:
                        raise _Blocked("discovery_attempt_receipt_missing")
                    state_store.advance_discovery_operation(binding, "begin", **producer_args)
                proposal_assignment = DiscoveryAssignment(binding["operation_id"], f"attempt-{number}-propose",
                    binding["spec_id"], binding["run_id"], "propose", fingerprint, artifact_paths, editable_revisions, producer=producer)
                common = dict(intent=deepcopy(binding["intent"]), baseline=before, evidence=evidence, templates=templates, runtime=runtime,
                    history=json.loads(retained_history.payload), feedback=feedback,
                    read_protocol=dict(roots=["inputs"], request=dict(op="read_file", root="inputs", path="relative/path", start_line=1, line_count=1)))
                def turn(assignment, context, *, fresh=False):
                    nonlocal last
                    last = run_discovery_step(root, state_store, executor, assignment, context,
                        roots={"inputs": root / input_tree}, check_inputs=check_inputs, create=fresh,
                        token_budget=token_budget, dispatch_limit=dispatch_limit, replay_only=replay_only,
                        **({"repair_unit": repair_unit} if repair_unit is not None else {}))
                    if last.reply is None:
                        raise _Blocked(last.reason)
                    return last.reply
                proposal = turn(proposal_assignment, {**common, "reply_fields": dict(
                    new_subjects=[dict(key="local-key", kind="U or ISS" if producer == "why1" else "UI or II" if producer == "tracker" else "U or A", subject="stable subject", caption="caption")],
                    revisions=[dict(id="permitted existing ID", expected_revision="assigned revision")])}, fresh=create and number == 1)
                verify()
                if repair_unit is not None and (proposal["new_subjects"] or
                        sorted((row["id"], row["expected_revision"]) for row in proposal["revisions"]) != sorted(editable_revisions)):
                    raise _Blocked("discovery_repair_proposal_outside_scope")
                mappings = journal.bind(proposal_assignment, proposal, replay_only=replay_only)
                reserved = [asdict(item) for item in mappings]
                assigned = tuple(sorted({item.element_id for item in mappings} | {item["id"] for item in proposal["revisions"]}))
                author_assignment = replace(proposal_assignment, dispatch_id=f"attempt-{number}-author", step="author", assigned_ids=assigned)
                reply_fields = dict(artifacts={path: "exact UTF-8 artifact text" for path in artifact_paths})
                if producer in {"tracker", "why1"}:
                    reply_fields["artifacts"]["issues.md" if producer == "why1" else "stakeholder-model.md"] = "exact UTF-8 text, or null only when absent before and after"
                    reply_fields["routing"] = dict(verdict="PASS, FAIL, STOP_AND_ASK or BLOCKED" if producer == "why1" else "ALIGNED, DRIFT or STOP_AND_ASK",
                        question="required nonblank question for STOP_AND_ASK; otherwise null",
                        recommended_answer="optional nonblank answer for STOP_AND_ASK; otherwise null",
                        risk_level="optional low, medium, high or critical alongside a STOP_AND_ASK recommendation; otherwise null")
                authored = turn(author_assignment, {**common, "proposal": proposal, "reservations": reserved,
                    "reply_fields": reply_fields})
                verify()
                artifacts, operations, preview, review = (), (), None, None
                try:
                    written = author_artifacts(author_assignment, authored, before={path: before.get(path) for path in artifact_paths})
                    changes = build_discovery_changes(proposal_assignment, proposal, reservations=mappings, artifacts=written,
                        existing_subjects={row["id"]: subjects[row["id"]]["subject"] for row in proposal["revisions"]})
                except ValueError as error:
                    findings = [dict(code="invalid_discovery_candidate", detail=str(error))]
                else:
                    # Receipt-authenticated generated context quotes the accepted
                    # definitions already present in `before`. It remains exact
                    # model evidence and in the raw publication read guard, not
                    # a second definition-bearing identity source. All other
                    # evidence still uses the existing reference adapter.
                    derived_context = (state_store.squad_dir / "context").relative_to(root).as_posix() + "/"
                    artifacts = tuple(sorted((*written,
                        *(CandidateArtifact(path, artifact_roles("why1" if repair_unit is not None else producer)[path], content, content) for path, content in before.items() if path not in artifact_paths),
                        *(CandidateArtifact(path, "references", content, content) for path, content in evidence.items()
                            if (producer == "discovery" and repair_unit is None) or not path.startswith(derived_context))), key=lambda item: item.path))
                    operations = (PublicationOperation("lifecycle", f"{binding['operation_id']}-attempt-{number}-lifecycle", encode_request("lifecycle", changes)),) if changes else ()
                    reports, occurrences = issue_report_changes(artifacts, changes, retained_history,
                        report_id=f"{binding['operation_id']}-attempt-{number}-issues") if producer == "why1" or repair_unit is not None else ((), ())
                    if occurrences:
                        operations += (PublicationOperation("issue_occurrences", f"{binding['operation_id']}-attempt-{number}-occurrences",
                            encode_request("issue_occurrences", occurrences)),)
                    preview = store.preview_identity_candidate(spec_id=binding["spec_id"], artifacts=artifacts,
                        scope=IdentityEditScope(tuple(path for path in artifact_paths if any(item.path == path for item in written)),
                            assigned, tuple(path for path in unowned_writable_paths if any(item.path == path for item in written))),
                        operations=operations, issue_reports=reports)
                    findings = [asdict(row) for row in preview.check.diagnostics]
                    if not findings:
                        labels = tuple(sorted(change.element_id for change in changes))
                        citations = _citations(artifacts, labels)
                        source_citations = {path: f"source:{path}:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
                            for path, content in evidence.items()}
                        review_assignment = replace(author_assignment, dispatch_id=f"attempt-{number}-review", step="review", assigned_ids=labels,
                            routing=tuple(authored["routing"].items()) if producer in {"tracker", "why1"} else None)
                        review = turn(review_assignment, {**common, "proposal": proposal, "reservations": reserved,
                            "candidate": [asdict(item) for item in artifacts], "citations": citations,
                            "source_citations": source_citations,
                            "proposed_history": asdict(preview.history), "operations": [asdict(item) for item in operations],
                            "reply_fields": dict(verdict="accept or reject", reason="candidate-wide assessment",
                                assessments=[dict(id="each assigned ID", verdict="accept or reject", reason="assessment", evidence=["its exact supplied candidate citation"])])})
                        for assessment in review["assessments"]:
                            supplied = assessment["evidence"]
                            own = citations[assessment["id"]]
                            if own not in supplied or not set(supplied) <= {own, *source_citations.values()}:
                                raise _Blocked("discovery_review_citation_mismatch")
                        if review["verdict"] == "reject":
                            findings = [dict(code="semantic_rejection", reason=review["reason"]),
                                *(dict(id=row["id"], verdict=row["verdict"], reason=row["reason"]) for row in review["assessments"])]
                verify()
                candidate_inputs = dict(artifacts=authored["artifacts"], proposal=proposal, reservations=reserved,
                    operations=[asdict(item) for item in operations], history=None if preview is None or preview.history is None else asdict(preview.history))
                if producer in {"tracker", "why1"}:
                    candidate_inputs["routing"] = authored["routing"]
                candidate_digest = _hash(candidate_inputs)
                finished = dict(status="rejected" if findings else "accepted", candidate_sha256=candidate_digest,
                    findings_sha256=_hash(sorted(findings, key=lambda row: json.dumps(row, sort_keys=True))))
                progress = _progress(authored["artifacts"], findings, routing=authored.get("routing") if producer in {"tracker", "why1"} else None)
                if repair_unit is not None:
                    finished["progress_sha256"] = progress
                saved = operation_from_state(state_store.load(), producer, repair_unit=repair_unit)["attempts"][number - 1]["result"]
                if saved is None:
                    if replay_only:
                        raise _Blocked("discovery_attempt_receipt_missing")
                    state_store.advance_discovery_operation(binding, "finish", result=finished, **producer_args)
                elif saved != finished:
                    raise _Blocked("discovery_attempt_receipt_changed")
                verify()
                if not findings:
                    canonical = dict(sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
                    candidate = ReviewedDiscoveryCandidate(artifacts, operations, preview.history, fingerprint, review, candidate_digest,
                        json.dumps(candidate_inputs, **canonical), json.dumps(source_inputs, **canonical))
                    return DiscoveryOperationResult("reviewed", "discovery_candidate_reviewed", last.token_usage, last.dispatch_count, candidate)
                if progress == prior_progress:
                    raise _Blocked("discovery_no_progress")
                prior_progress = progress
                feedback = dict(findings=findings, candidate=authored["artifacts"])
            raise _Blocked("discovery_attempts_exhausted")
    except Exception as error:
        return DiscoveryOperationResult("blocked", str(error) if isinstance(error, (_Blocked, DiscoveryInputError)) else "discovery_operation_reconciliation_required",
            retained_usage["token_usage"] if last is None else last.token_usage,
            retained_usage["dispatch_count"] if last is None else last.dispatch_count)
