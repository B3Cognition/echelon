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
from harness.discovery_candidate import author_artifacts, build_discovery_changes
from harness.discovery_inputs import DiscoveryInputError, admit_runtime_inputs, runtime_input_paths
from harness.discovery_operation_state import DISCOVERY_OPERATION_KEY, operation_from_state
from harness.discovery_reservations import DiscoveryReservationJournal
from harness.discovery_semantics import DISCOVERY_ROLES, DiscoveryAssignment
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


def _capture(root, state_store, store, selected, input_tree, artifact_paths):
    spec_path = selected["selection"]["spec_path"]
    denied = (*CONTROL_ROOTS, *CONTROL_PATHS, str(state_store.squad_dir.relative_to(root)))
    if any(_overlap(input_tree, path) for path in (*denied, spec_path)):
        raise _Blocked("discovery_input_tree_not_admitted")
    prepared = load_prepared_publication(root, state_store.squad_dir, selected["selection"]["capture_marker"])
    template_paths = {f".echelon/runtime/templates/{path.removesuffix('.md')}-template.md": path for path in artifact_paths}
    runtime_trees, runtime_files = runtime_input_paths(root, state_store.squad_dir)
    with prepared.inspect_sources(tree_paths=(spec_path, input_tree, *runtime_trees),
            file_paths=(*template_paths, *runtime_files)) as sources:
        if sources.publication.operations:
            raise _Blocked("discovery_capture_contains_publication")
        state = state_store.load()
        runtime, documents = admit_runtime_inputs(root, state_store.squad_dir, state, sources)
        observed = store.check_managed_context(spec_id=selected["selection"]["spec_id"],
            run_id=selected["selection"]["run_id"], record=state["managed_identity"])
        spec, = (tree for tree in sources.trees if tree.path == spec_path)
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
            if logical not in DISCOVERY_ROLES:
                raise _Blocked("unsupported_discovery_source_role")
            files[logical] = item.content.decode("utf-8")
        evidence = {item.path: item.content.decode("utf-8") for item in inputs.files}
        evidence.update(documents)
        if any(item.content is None for item in sources.files if item.path in template_paths):
            raise _Blocked("discovery_template_missing")
        templates = {template_paths[item.path]: item.content.decode("utf-8") for item in sources.files if item.path in template_paths}
        if any("\x00" in content for content in (*files.values(), *evidence.values(), *templates.values())):
            raise _Blocked("discovery_source_not_text")
        digest = _hash(dict(manifest=asdict(snapshot_source_manifest(trees=sources.trees, files=sources.files)),
            history=asdict(history), authority=observed, runtime=runtime))
    # Normal inspector exit authenticates paths and membership before handoff.
    return digest, files, evidence, history, templates, runtime


def _citations(artifacts, labels):
    citations = {}
    for artifact in artifacts:
        if artifact.role not in {"unknowns", "assumptions"} or artifact.after_text is None:
            continue
        parsed = parse_identity_artifact(path=artifact.path, role=artifact.role, text=artifact.after_text)
        for declaration in parsed.declarations:
            if declaration.element_id in labels:
                digest = hashlib.sha256(artifact.after_text.encode("utf-8")).hexdigest()
                citations[declaration.element_id] = f"candidate:{artifact.path}:{digest}#{declaration.element_id}"
    if set(citations) != set(labels):
        raise _Blocked("discovery_review_definition_mismatch")
    return citations


def _progress(artifacts, findings):
    def normalized(text):
        # Formatting and label changes alone cannot make a failed attempt progress.
        return " ".join(re.sub(r"\b(?:U|A)-[0-9]+\b", "<identity>", text).split())
    content = {key: normalized(value) for key, value in artifacts.items()}
    rows = sorted(normalized(json.dumps(row, sort_keys=True, ensure_ascii=False)) for row in findings)
    return _hash(dict(content=content, findings=rows))


def run_discovery_operation(project_root, state_store, executor, *, input_tree, artifact_paths,
        editable_revisions=(), unowned_writable_paths=(), intent, create=False,
        token_budget=None, dispatch_limit=297) -> DiscoveryOperationResult:
    """Compose at most three attempts; exact receipts make restart a read replay."""
    last = None
    retained_usage = read_discovery_usage(state_store)
    try:
        root = Path(project_root)
        state = state_store.load()
        selected = bootstrap_from_state(state)
        if selected is None or "managed_identity" not in state or str(root) != selected["selection"]["project_root"]:
            raise _Blocked("completed_discovery_bootstrap_required")
        if type(create) is not bool or create == (DISCOVERY_OPERATION_KEY in state):
            raise _Blocked("discovery_operation_selection_conflict")
        if any(type(value) is not tuple for value in (artifact_paths, editable_revisions, unowned_writable_paths)):
            raise _Blocked("invalid_discovery_scope")
        store = IdentityStore.open(root)
        fingerprint, before, evidence, retained_history, templates, runtime = _capture(root, state_store, store, selected, input_tree, artifact_paths)
        binding = dict(operation_id=selected["selection"]["operation_id"], spec_id=selected["selection"]["spec_id"],
            run_id=selected["selection"]["run_id"], input_tree=input_tree, artifact_paths=list(artifact_paths),
            editable_revisions=[list(pair) for pair in editable_revisions], unowned_writable_paths=list(unowned_writable_paths),
            intent=deepcopy(intent), fingerprint=fingerprint)
        state = state_store.advance_discovery_operation(binding, "prepare")
        def check_inputs():
            return _capture(root, state_store, store, selected, input_tree, artifact_paths)[0]
        def verify():
            if check_inputs() != fingerprint:
                raise _Blocked("discovery_operation_inputs_changed")
        with DiscoveryReservationJournal(state_store.squad_dir) as journal:
            journal.select(store, spec_id=binding["spec_id"], run_id=binding["run_id"],
                operation_id=binding["operation_id"], managed_identity=state["managed_identity"], create=create)
            history_rows = json.loads(retained_history.payload)
            subjects = {row["element_id"]: row for row in history_rows["entities"]}
            for label, revision in editable_revisions:
                if label not in subjects or subjects[label]["revision"] != revision:
                    raise _Blocked("discovery_editable_revision_changed")
            feedback, prior_progress = None, None
            for number in (1, 2, 3):
                current = operation_from_state(state_store.load())
                if len(current["attempts"]) < number:
                    state_store.advance_discovery_operation(binding, "begin")
                proposal_assignment = DiscoveryAssignment(binding["operation_id"], f"attempt-{number}-propose",
                    binding["spec_id"], binding["run_id"], "propose", fingerprint, artifact_paths, editable_revisions)
                common = dict(intent=deepcopy(binding["intent"]), baseline=before, evidence=evidence, templates=templates, runtime=runtime,
                    history=json.loads(retained_history.payload), feedback=feedback,
                    read_protocol=dict(roots=["inputs"], request=dict(op="read_file", root="inputs", path="relative/path", start_line=1, line_count=1)))
                def turn(assignment, context, *, fresh=False):
                    nonlocal last
                    last = run_discovery_step(root, state_store, executor, assignment, context,
                        roots={"inputs": root / input_tree}, check_inputs=check_inputs, create=fresh,
                        token_budget=token_budget, dispatch_limit=dispatch_limit)
                    if last.reply is None:
                        raise _Blocked(last.reason)
                    return last.reply
                proposal = turn(proposal_assignment, {**common, "reply_fields": dict(
                    new_subjects=[dict(key="local-key", kind="U or A", subject="stable subject", caption="caption")],
                    revisions=[dict(id="permitted existing ID", expected_revision="assigned revision")])}, fresh=create and number == 1)
                verify()
                mappings = journal.bind(proposal_assignment, proposal)
                reserved = [asdict(item) for item in mappings]
                assigned = tuple(sorted({item.element_id for item in mappings} | {item["id"] for item in proposal["revisions"]}))
                author_assignment = replace(proposal_assignment, dispatch_id=f"attempt-{number}-author", step="author", assigned_ids=assigned)
                authored = turn(author_assignment, {**common, "proposal": proposal, "reservations": reserved,
                    "reply_fields": dict(artifacts={path: "exact UTF-8 artifact text" for path in artifact_paths})})
                verify()
                artifacts, operations, preview, review = (), (), None, None
                try:
                    written = author_artifacts(author_assignment, authored, before={path: before.get(path) for path in artifact_paths})
                    changes = build_discovery_changes(proposal_assignment, proposal, reservations=mappings, artifacts=written,
                        existing_subjects={row["id"]: subjects[row["id"]]["subject"] for row in proposal["revisions"]})
                except ValueError as error:
                    findings = [dict(code="invalid_discovery_candidate", detail=str(error))]
                else:
                    artifacts = tuple(sorted((*written,
                        *(CandidateArtifact(path, DISCOVERY_ROLES[path], content, content) for path, content in before.items() if path not in artifact_paths),
                        *(CandidateArtifact(path, "references", content, content) for path, content in evidence.items())), key=lambda item: item.path))
                    operations = (PublicationOperation("lifecycle", f"{binding['operation_id']}-attempt-{number}-lifecycle", encode_request("lifecycle", changes)),) if changes else ()
                    preview = store.preview_identity_candidate(spec_id=binding["spec_id"], artifacts=artifacts,
                        scope=IdentityEditScope(artifact_paths, assigned, unowned_writable_paths), operations=operations)
                    findings = [asdict(row) for row in preview.check.diagnostics]
                    if not findings:
                        labels = tuple(sorted(change.element_id for change in changes))
                        citations = _citations(artifacts, labels)
                        source_citations = {path: f"source:{path}:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
                            for path, content in evidence.items()}
                        review_assignment = replace(author_assignment, dispatch_id=f"attempt-{number}-review", step="review", assigned_ids=labels)
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
                candidate_digest = _hash(dict(artifacts=authored["artifacts"], proposal=proposal, reservations=reserved,
                    operations=[asdict(item) for item in operations], history=None if preview is None or preview.history is None else asdict(preview.history)))
                finished = dict(status="rejected" if findings else "accepted", candidate_sha256=candidate_digest,
                    findings_sha256=_hash(sorted(findings, key=lambda row: json.dumps(row, sort_keys=True))))
                saved = operation_from_state(state_store.load())["attempts"][number - 1]["result"]
                if saved is None:
                    state_store.advance_discovery_operation(binding, "finish", result=finished)
                elif saved != finished:
                    raise _Blocked("discovery_attempt_receipt_changed")
                verify()
                if not findings:
                    candidate = ReviewedDiscoveryCandidate(artifacts, operations, preview.history, fingerprint, review, candidate_digest)
                    return DiscoveryOperationResult("reviewed", "discovery_candidate_reviewed", last.token_usage, last.dispatch_count, candidate)
                progress = _progress(authored["artifacts"], findings)
                if progress == prior_progress:
                    raise _Blocked("discovery_no_progress")
                prior_progress = progress
                feedback = dict(findings=findings, candidate=authored["artifacts"])
            raise _Blocked("discovery_attempts_exhausted")
    except Exception as error:
        return DiscoveryOperationResult("blocked", str(error) if isinstance(error, (_Blocked, DiscoveryInputError)) else "discovery_operation_reconciliation_required",
            retained_usage["token_usage"] if last is None else last.token_usage,
            retained_usage["dispatch_count"] if last is None else last.dispatch_count)
