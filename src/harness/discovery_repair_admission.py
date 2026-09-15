"""Authenticate WHY1 repair selection; never dispatch, allocate or publish.

The existing repair state is association data, not execution authority. Every
future repair dispatch must reauthenticate its selected completion and sources.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from harness.discovery_candidate import issue_report_changes
from harness.element_artifacts import parse_identity_artifact
from harness.element_artifact_markdown import _active_source, _lines
from harness.element_identity_candidate import CandidateArtifact
from harness.proportional_quality import (
    _parse_authoritative_sage_assessment_bytes, is_actionable_sage_issue, sage_issue_fields,
)


def _require(value):
    if not value:
        raise ValueError("WHY1 repair requires authenticated, unambiguous Discovery findings")


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _literal(value):
    value = value.strip()
    return value[1:-1] if value.startswith("`") and value.endswith("`") else value


def repair_findings(artifacts, history, reviewed_artifacts, reviewed_history):
    """Derive narrow association data from already authenticated captured images.

    Existing report fields identify one exact U/A declaration per finding.
    Prose cannot choose another owner, authorize whole-file edits, or redefine an
    ID. All actionable issues must fit; advisory entries confer no write scope.
    """
    report = artifacts.get("issues.md")
    _require(type(report) is str)
    lines = _lines(report)
    active, diagnostics = _active_source(report, lines, [line.start for line in lines])
    _require(not diagnostics)
    # Apply the identity parser's existing visibility rules to SAGE metadata too.
    # Quoted examples, comments and fenced code cannot select a writable scope.
    visible = "".join(char if active[index] or char in "\r\n" else " " for index, char in enumerate(report))
    verdict, issues = _parse_authoritative_sage_assessment_bytes(visible.encode("utf-8"))
    _require(verdict == "FAIL")
    parsed = parse_identity_artifact(path="issues.md", role="issues", text=report)
    _require(not parsed.diagnostics and {row.element_id for row in parsed.declarations} == {row["issue_id"] for row in issues})
    current = json.loads(history.payload)
    # Equal report bytes can belong to distinct historical occurrences. Display
    # composition may preserve an old report, but repair must not guess its origin.
    _require(len({row["report_id"] for row in current["issue_occurrences"]
        if row["report_sha256"] == parsed.content_sha256}) == 1)
    contexts, _ = issue_report_changes((CandidateArtifact("issues.md", "issues", report, report),),
        (), history, report_id="unselected")
    occurrences = {row.issue_id: row for row in contexts[0].before_occurrences}
    declarations_by_id = {row.element_id: row for row in parsed.declarations}
    reviewed = json.loads(reviewed_history.payload)
    heads = {row["element_id"]: row for row in current["entities"]}
    old_heads = {row["element_id"]: row for row in reviewed["entities"]}
    findings, paths, revisions = [], set(), set()
    for issue in issues:
        if not is_actionable_sage_issue(issue):
            continue
        occurrence = occurrences[issue["issue_id"]]
        issue_head = heads.get(occurrence.issue_id)
        _require(issue_head is not None and issue_head["status"] == "active"
            and issue_head["revision"] == occurrence.issue_revision)
        declaration = declarations_by_id[issue["issue_id"]]
        fields = sage_issue_fields(visible[declaration.span.start:declaration.span.end])
        _require(fields["Responsible agent"].strip() in {"DISCOVER", "SCOUT"})
        path, target = _literal(fields["Affected artifact"]), _literal(fields["Affected section"])
        _require(path in {"unknowns.md", "assumptions.md"} and target in old_heads and heads.get(target) == old_heads[target])
        role, kind = ("unknowns", "U") if path == "unknowns.md" else ("assumptions", "A")
        _require(old_heads[target]["kind"] == kind and path in reviewed_artifacts and path in artifacts)
        images = [parse_identity_artifact(path=path, role=role, text=items[path]) for items in (reviewed_artifacts, artifacts)]
        declarations = [[row for row in image.declarations if row.element_id == target] for image in images]
        _require(all(not image.diagnostics for image in images) and all(len(rows) == 1 for rows in declarations))
        old, new = declarations[0][0], declarations[1][0]
        _require(old.content == new.content)
        revision = old_heads[target]["revision"]
        retained = [row for row in reviewed["revisions"] if row["element_id"] == target and row["revision"] == revision]
        _require(len(retained) == 1 and retained[0]["status"] == "active" and retained[0]["content"] == old.content)
        detail = dict(occurrence=asdict(occurrence), target=dict(path=path, id=target, revision=revision,
            source_sha256=images[0].content_sha256, content_sha256=retained[0]["content_sha256"]))
        findings.append(dict(key=hashlib.sha256(_json(asdict(occurrence)).encode("ascii")).hexdigest(), detail=_json(detail)))
        paths.add(path)
        revisions.add((target, revision))
    _require(findings)
    return sorted(findings, key=lambda row: row["key"]), sorted(paths), [list(pair) for pair in sorted(revisions)]


def prepare_why1_discovery_repair(project_root, state_store):
    """Select only a released WHY1→Discovery request under caller execution leases.

    No caller-supplied origin, scope or finding is trusted. Capture the current
    accepted head with the existing owner, then compare unchanged review inputs
    against its retained preimages. Future execution must repeat this admission;
    a stored repair selection alone never grants dispatch/publication permission.
    """
    from harness.discovery_bootstrap_state import bootstrap_from_state
    from harness.discovery_completion import _retained_input_projection
    from harness.discovery_operation import _capture
    from harness.discovery_producer import SOURCE_FIELDS, producer_operation_id
    from harness.discovery_semantics import WHY1_OUTPUTS
    from harness.element_identity_snapshot import IdentityHistorySnapshot
    from harness.element_identity_store import IdentityStore

    root = Path(project_root)
    state = state_store.load()
    selected = bootstrap_from_state(state)
    _require(selected is not None and str(root) == selected["selection"]["project_root"]
        and str(state_store.squad_dir) == selected["selection"]["run_dir"]
        and state.get("phase") == "phase1-discover" and state.get("status") == "running"
        and not any(key in state for key in ("pending_controller_completion", "pending_external_publication"))
        and (state.get("blocked_decision") or {}).get("status") not in {"pending", "unresolved"})
    dispatch = state["last_dispatch"]
    _require(dispatch.get("phase_id") == "phase1-why1" and dispatch.get("post_dispatch_complete") is True)
    source = {key: dispatch[key] for key in SOURCE_FIELDS}
    store = IdentityStore.open(root)
    binding, _, project_context = _retained_input_projection(root, state_store.squad_dir, state, store,
        operation_id="discovery-completion-" + source["dispatch_id"], source=source, require_checkpoint=False,
        required_route=("phase1-why1", "phase1-discover"))
    _require(binding.producer == "why1" and not binding.clarification
        and binding.candidate["routing"]["verdict"] == "FAIL"
        and binding.recovery["review"]["verdict"] == "accept"
        and binding.recovery["operation"]["binding"]["operation_id"] == producer_operation_id(state, "why1"))
    captured = _capture(root, state_store, store, selected,
        binding.recovery["operation"]["binding"]["input_tree"], tuple(WHY1_OUTPUTS),
        producer="why1", source_completion=source)
    _, artifacts, _, history, _, _, sources, _ = captured
    prior = project_context(sources)
    spec_path = selected["selection"]["spec_path"]
    _require(prior.files == binding.sources.files
        and tuple(tree for tree in prior.trees if tree.path != spec_path)
        == tuple(tree for tree in binding.sources.trees if tree.path != spec_path))
    reviewed_spec, = (tree for tree in binding.baseline.trees if tree.path == spec_path)
    reviewed_artifacts = {item.path[len(spec_path) + 1:]: item.content.decode("utf-8") for item in reviewed_spec.files}
    findings, paths, revisions = repair_findings(artifacts, history, reviewed_artifacts,
        IdentityHistorySnapshot(**binding.source["history"]))
    selection = dict(source=source, origin=dict(review_id=source["dispatch_id"], return_phase="phase1-why1"),
        findings=findings, artifact_paths=paths, editable_revisions=revisions)
    return state_store.prepare_discovery_repair(selection, expected_state=state)


def prepare_repair_refresh_round(project_root, state_store, producer):
    """Authenticate an inactive refresh association under caller execution leases.

    This checkpoint admits the released repair as source, not refreshed producer
    output. Dependency selection, execution and re-review remain guarded. The
    state owner retains associations only; immutable completion proof supplies
    their authority and is read again even for an exact retry.
    """
    from harness.discovery_bootstrap_state import bootstrap_from_state
    from harness.discovery_completion import _retained_input_projection, released_discovery_input_projectors
    from harness.discovery_producer import SOURCE_FIELDS, tracker_rounds
    from harness.element_identity_store import IdentityStore
    from harness.squad_publication import load_prepared_publication

    try:
        _require(producer in {"synthesizer", "tracker", "why1"})
        root = Path(project_root)
        state = state_store.load()
        selected = bootstrap_from_state(state)["selection"]
        _require(str(root) == selected["project_root"] and str(state_store.squad_dir) == selected["run_dir"]
            and state.get("phase") == "phase1-why1" and state.get("status") == "running"
            and state.get("mode") == "greenfield"
            and not any(key in state for key in ("pending_controller_completion", "pending_external_publication"))
            and (state.get("blocked_decision") or {}).get("status") not in {"pending", "unresolved"})
        dispatch = state["last_dispatch"]
        _require(dispatch.get("phase_id") == "phase1-discover" and dispatch.get("post_dispatch_complete") is True)
        source = {key: dispatch[key] for key in SOURCE_FIELDS}
        identity = IdentityStore.open(root)
        binding, project_spec, project_context = _retained_input_projection(root, state_store.squad_dir, state, identity,
            operation_id="discovery-completion-" + source["dispatch_id"], source=source, require_checkpoint=False,
            required_route=("phase1-discover", "phase1-why1"))
        _require(binding.producer == "discovery" and binding.repair_unit is not None)
        # Full retained ancestry verifies the requesting WHY1 and repair findings.
        released_discovery_input_projectors(root, state_store.squad_dir, state, source=source)
        prepared = load_prepared_publication(root, state_store.squad_dir, selected["capture_marker"])
        with prepared.inspect_sources(tree_paths=tuple(tree.path for tree in binding.sources.trees),
                file_paths=tuple(item.path for item in binding.sources.files)) as sources:
            _require(not sources.publication.operations)
            spec, = (tree for tree in sources.trees if tree.path == selected["spec_path"])
            project_spec(spec)
            projected = project_context(sources)
            _require(projected.files == binding.sources.files
                and tuple(tree for tree in projected.trees if tree.path != selected["spec_path"])
                == tuple(tree for tree in binding.sources.trees if tree.path != selected["spec_path"]))
        unit = binding.repair_unit
        parent = binding.recovery["source_completion"]
        seen = set()
        while True:
            _require(parent["dispatch_id"] not in seen)
            seen.add(parent["dispatch_id"])
            previous, _, _ = _retained_input_projection(root, state_store.squad_dir, state, identity,
                operation_id="discovery-completion-" + parent["dispatch_id"], source=parent, require_checkpoint=False)
            if previous.producer == producer and not previous.clarification:
                break
            parent = previous.recovery.get("source_completion")
            _require(parent is not None)
        rounds = tracker_rounds(state, producer)
        if rounds is None:
            _require(producer == "synthesizer")
            predecessor = state["managed_synthesizer_operation"]["binding"]["operation_id"]
        else:
            active = rounds["rounds"][rounds["active"]]
            predecessor = (active["predecessor"] if rounds["active"] == producer + "-" + source["dispatch_id"]
                else rounds["active"])
        _require(predecessor == previous.recovery["operation"]["binding"]["operation_id"])
        refresh = dict(repair_unit=unit, repair_source=source, predecessor_source=parent)
    except Exception:
        raise ValueError("repair refresh requires unchanged released repair and producer ancestry") from None
    return state_store.prepare_refresh_round(producer, source, refresh, expected_state=state)
