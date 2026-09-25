"""Authenticate review-owned repair selection; never dispatch, allocate or publish.

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
        raise ValueError("review repair requires authenticated, unambiguous Discovery findings")


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _literal(value):
    value = value.strip()
    return value[1:-1] if value.startswith("`") and value.endswith("`") else value


def repair_findings(artifacts, history, reviewed_artifacts, reviewed_history, *, review_producer="why1"):
    """Derive narrow association data from already authenticated captured images.

    Existing report fields identify one exact U/A declaration per finding.
    Prose cannot choose another owner, authorize whole-file edits, or redefine an
    ID. WHY2 may also retain WHAT debt: those proven occurrences remain in the
    unchanged report/history but confer no Discovery write scope. The caller
    authenticates the requesting review's native Discovery route separately.
    Advisory entries confer no write scope.
    """
    _require(review_producer in {"why1", "why2"})
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
        owner = fields["Responsible agent"].strip()
        path, target = _literal(fields["Affected artifact"]), _literal(fields["Affected section"])
        if review_producer == "why2" and owner in {"WHAT", "CARTOGRAPHER"}:
            _require(path in {"spec.md", "requirements-overview.md"})
            continue
        _require(owner in {"DISCOVER", "SCOUT"})
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
    """Select a released WHY1/WHY2→Discovery request under execution leases.

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
        and not any(key in state for key in ("_spec_step_effect_plan", "_spec_step_publication_plan"))
        and (state.get("blocked_decision") or {}).get("status") not in {"pending", "unresolved"})
    dispatch = state["last_dispatch"]
    _require(dispatch.get("phase_id") in {"phase1-why1", "phase1-why2"} and dispatch.get("post_dispatch_complete") is True)
    producer = dispatch["phase_id"].removeprefix("phase1-")
    source = {key: dispatch[key] for key in SOURCE_FIELDS}
    store = IdentityStore.open(root)
    binding, project_spec, project_context = _retained_input_projection(root, state_store.squad_dir, state, store,
        operation_id="discovery-completion-" + source["dispatch_id"], source=source, require_checkpoint=False,
        required_route=(dispatch["phase_id"], "phase1-discover"))
    _require(binding.producer == producer and not binding.clarification and binding.restoration is None
        and binding.candidate["routing"]["verdict"] == "FAIL"
        and binding.recovery["review"]["verdict"] == "accept"
        and binding.recovery["operation"]["binding"]["operation_id"] == producer_operation_id(state, producer))
    if producer == "why1":
        captured = _capture(root, state_store, store, selected,
            binding.recovery["operation"]["binding"]["input_tree"], tuple(WHY1_OUTPUTS),
            producer="why1", source_completion=source)
        _, artifacts, _, history, _, _, sources, _ = captured
        prior = project_context(sources)
    else:
        # Capture the released review itself, not WHY2's earlier Understanding
        # parent. This is selection only; repair execution reauthenticates it.
        artifacts, history, prior = _capture_requesting_why2(root, state_store, state, selected, store,
            binding, source, project_spec, project_context)
    spec_path = selected["selection"]["spec_path"]
    _require(prior.files == binding.sources.files
        and tuple(tree for tree in prior.trees if tree.path != spec_path)
        == tuple(tree for tree in binding.sources.trees if tree.path != spec_path))
    reviewed_spec, = (tree for tree in binding.baseline.trees if tree.path == spec_path)
    reviewed_artifacts = {item.path[len(spec_path) + 1:]: item.content.decode("utf-8") for item in reviewed_spec.files}
    findings, paths, revisions = repair_findings(artifacts, history, reviewed_artifacts,
        IdentityHistorySnapshot(**binding.source["history"]), review_producer=producer)
    selection = dict(source=source, origin=dict(review_id=source["dispatch_id"], return_phase=dispatch["phase_id"]),
        findings=findings, artifact_paths=paths, editable_revisions=revisions)
    return state_store.prepare_discovery_repair(selection, expected_state=state)


def _capture_requesting_why2(root, state_store, state, selected, store, binding, source, project_spec, project_context):
    from harness.discovery_completion import released_discovery_input_projectors
    from harness.discovery_inputs import admit_runtime_inputs
    from harness.squad_publication import load_prepared_publication
    from harness.squad_source_manifest import snapshot_source_manifest
    _, runtime_view = released_discovery_input_projectors(root, state_store.squad_dir, state, source=source)
    selection = selected["selection"]
    publication = load_prepared_publication(root, state_store.squad_dir, selection["capture_marker"])
    with publication.inspect_sources(tree_paths=tuple(tree.path for tree in binding.sources.trees),
            file_paths=tuple(item.path for item in binding.sources.files)) as sources:
        _require(not sources.publication.operations)
        tree, = (tree for tree in sources.trees if tree.path == selection["spec_path"])
        tree = project_spec(tree)
        prior = project_context(sources)
        runtime, _ = admit_runtime_inputs(root, state_store.squad_dir, state, runtime_view(sources))
        _require(runtime == binding.source["runtime"])
        observed = store.check_managed_context(spec_id=selection["spec_id"], run_id=selection["run_id"],
            record=state["managed_identity"])
        _require(observed["source_context"]["manifest"]["payload"]
            == snapshot_source_manifest(trees=(tree,), files=()).payload)
        history = store.identity_history(spec_id=selection["spec_id"])
        _require(asdict(history) == binding.candidate["history"])
        artifacts = {item.path[len(tree.path) + 1:]: item.content.decode("utf-8")
            for item in tree.files if item.path.endswith(".md")}
        _require(state_store.load() == state)
    return artifacts, history, prior


def prepare_repair_refresh_round(project_root, state_store, producer):
    """Authenticate an inactive refresh association under caller execution leases.

    This checkpoint admits the released repair as source, not refreshed producer
    output. Dependency selection, execution and re-review remain guarded. The
    state owner retains associations only; immutable completion proof supplies
    their authority and is read again even for an exact retry.
    """
    state, source, refresh, *_ = _repair_refresh_context(project_root, state_store, producer)
    return state_store.prepare_refresh_round(producer, source, refresh, expected_state=state)


def _repair_refresh_context(project_root, state_store, producer):
    """Authenticate existing repair/predecessor owners without mutating state."""
    from harness.discovery_bootstrap_state import bootstrap_from_state
    from harness.discovery_completion import _retained_input_projection, released_discovery_input_projectors
    from harness.discovery_producer import SOURCE_FIELDS, tracker_rounds, repair_return_phase
    from harness.element_identity_store import IdentityStore
    from harness.squad_publication import load_prepared_publication

    try:
        _require(producer in {"synthesizer", "tracker", "why1"})
        root = Path(project_root)
        state = state_store.load()
        selected = bootstrap_from_state(state)["selection"]
        _require(str(root) == selected["project_root"] and str(state_store.squad_dir) == selected["run_dir"]
            and state.get("phase") in {"phase1-why1", "phase1-why2"} and state.get("status") == "running"
            and state.get("mode") == "greenfield"
            and not any(key in state for key in ("_spec_step_effect_plan", "_spec_step_publication_plan"))
            and (state.get("blocked_decision") or {}).get("status") not in {"pending", "unresolved"})
        dispatch = state["last_dispatch"]
        _require(dispatch.get("phase_id") == "phase1-discover" and dispatch.get("post_dispatch_complete") is True)
        source = {key: dispatch[key] for key in SOURCE_FIELDS}
        identity = IdentityStore.open(root)
        binding, project_spec, project_context = _retained_input_projection(root, state_store.squad_dir, state, identity,
            operation_id="discovery-completion-" + source["dispatch_id"], source=source, require_checkpoint=False,
            required_route=("phase1-discover", state["phase"]))
        _require(binding.producer == "discovery" and binding.repair_unit is not None
            and repair_return_phase(state, binding.repair_unit) == state["phase"])
        # Full retained ancestry verifies the actual requesting review and findings.
        _, runtime_view = released_discovery_input_projectors(root, state_store.squad_dir, state, source=source)
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
    return state, source, refresh, binding, previous, project_spec, project_context, runtime_view


def pin_why1_tracker_history(project_root, state_store):
    """Bind a legacy WHY1 root to its proven Tracker before refreshed questions.

    Caller owns execution leases. No historical proof or answer is rewritten;
    state CAS adds only the immutable root association after full authentication.
    """
    from harness.discovery_completion import _retained_input_projection
    from harness.discovery_producer import tracker_rounds
    from harness.element_identity_store import IdentityStore

    try:
        root = Path(project_root)
        state, _, _, repair, *_ = _repair_refresh_context(root, state_store, "why1")
        rounds = tracker_rounds(state, "why1")
        operation_id, = (key for key, row in rounds["rounds"].items() if row["predecessor"] is None)
        row = rounds["rounds"][operation_id]
        source = row["source"]
        parent, _, _ = _retained_input_projection(root, state_store.squad_dir, state, IdentityStore.open(root),
            operation_id="discovery-completion-" + source["dispatch_id"], source=source,
            require_checkpoint=False, required_route=("phase1-tracker", "phase1-why1"))
        _require(parent.producer == "tracker" and not parent.clarification)
        tracker_parent = parent.recovery["operation"]["binding"]["operation_id"]
        _require(state_store.load() == state)
    except Exception:
        raise ValueError("WHY1 history requires its authenticated accepted Tracker parent") from None
    return state_store.pin_why1_tracker_parent(operation_id, tracker_parent, source=source, expected_state=state,
        repair_unit=repair.repair_unit)


def _tracker_refresh_context(root, state_store, producer="tracker"):
    """Authenticate a refresh's accepted upstream output and retained origin."""
    from harness.discovery_bootstrap_state import bootstrap_from_state
    from harness.discovery_completion import _retained_input_projection, _refresh_predecessor, released_discovery_input_projectors
    from harness.discovery_producer import SOURCE_FIELDS, tracker_round, tracker_rounds
    from harness.element_identity_store import IdentityStore
    from harness.tracker_clarification import previous_records

    state = state_store.load()
    selected = bootstrap_from_state(state)["selection"]
    _require(str(root) == selected["project_root"] and str(state_store.squad_dir) == selected["run_dir"]
        and state.get("phase") == "phase1-why1" and state.get("status") == "running"
        and state.get("mode") == "greenfield"
        and not any(key in state for key in ("_spec_step_effect_plan", "_spec_step_publication_plan"))
        and (state.get("blocked_decision") or {}).get("status") not in {"pending", "unresolved", "awaiting_human"})
    dispatch = state["last_dispatch"]
    _require(producer in {"tracker", "why1"})
    parent_producer = "tracker" if producer == "why1" else "synthesizer"
    _require(dispatch.get("phase_id") == "phase1-" + parent_producer and dispatch.get("post_dispatch_complete") is True)
    source = {key: dispatch[key] for key in SOURCE_FIELDS}
    binding, project_spec, project_context = _retained_input_projection(root, state_store.squad_dir, state,
        IdentityStore.open(root), operation_id="discovery-completion-" + source["dispatch_id"], source=source,
        require_checkpoint=False, required_route=("phase1-" + parent_producer, "phase1-why1"))
    row = tracker_round(state, producer=producer)
    parent = tracker_round(state, producer=parent_producer)
    _require(row is not None and "refresh" in row and not binding.clarification
        and binding.producer == parent_producer and parent["operation"] == binding.recovery["operation"])
    parents = tracker_rounds(state, parent_producer)["rounds"]
    while "refresh" not in parent and parent["predecessor"] is not None:
        parent = parents[parent["predecessor"]]
    _require("refresh" in parent and all(row["refresh"][key] == parent["refresh"][key]
        for key in ("repair_unit", "repair_source")))
    if producer == "tracker":
        _require(binding.recovery["version"] == 9)
    _, runtime_view = released_discovery_input_projectors(root, state_store.squad_dir, state, source=source)
    previous = _refresh_predecessor(root, state_store.squad_dir, state, row, producer=producer)
    why1 = tracker_rounds(state, "why1")
    _require(why1 is not None and all("tracker_parent" in item for item in why1["rounds"].values()
        if item["predecessor"] is None))
    previous_records(state, state["managed_tracker_rounds"]["active"])
    return state, source, row["refresh"], binding, previous, project_spec, project_context, runtime_view


def bind_repair_refresh_input(project_root, state_store, producer):
    """Bind the first refresh's accepted inputs under caller execution leases.

    Repair origin and execution input are separate retained facts. Synthesis
    consumes this repair; Tracker must wait for ordered Synthesis execution (or
    an authenticated unchanged-input decision). Never pre-bind stale Tracker.
    """
    from harness.discovery_bootstrap_state import bootstrap_from_state
    from harness.discovery_inputs import admit_runtime_inputs
    from harness.discovery_producer import tracker_round
    from harness.discovery_refresh_inputs import refresh_dependency_comparison
    from harness.element_identity_snapshot import IdentityHistorySnapshot
    from harness.squad_publication import load_prepared_publication
    from harness.squad_source_projection import project_publication_source_images

    try:
        _require(producer in {"synthesizer", "tracker", "why1"})
        root = Path(project_root)
        context = (_tracker_refresh_context(root, state_store, producer) if producer in {"tracker", "why1"}
            else _repair_refresh_context(root, state_store, producer))
        state, source, refresh, binding, previous, project_spec, project_context, runtime_view = context
        row = tracker_round(state, producer=producer)
        _require(row is not None and row.get("refresh") == refresh)
        selected = bootstrap_from_state(state)["selection"]
        spec_path = selected["spec_path"]
        run_path = state_store.squad_dir.relative_to(root).as_posix()
        before = project_publication_source_images(previous.sources)
        previous_trees = {tree.path: tree for tree in before.trees}
        previous_files = {item.path: item for item in before.files}
        repair_trees = {tree.path: tree for tree in binding.sources.trees}
        repair_files = {item.path: item for item in binding.sources.files}
        prepared = load_prepared_publication(root, state_store.squad_dir, selected["capture_marker"])
        with prepared.inspect_sources(tree_paths=tuple(sorted(previous_trees.keys() | repair_trees.keys())),
                file_paths=tuple(sorted(previous_files.keys() | repair_files.keys()))) as sources:
            _require(not sources.publication.operations)
            spec, = (tree for tree in sources.trees if tree.path == spec_path)
            project_spec(spec)
            projected = project_context(sources)
            # Authenticated repair captures are authoritative for their domains;
            # additionally retained Synthesis templates must still be exact.
            _require(all(tree == repair_trees.get(tree.path, previous_trees.get(tree.path))
                for tree in projected.trees if tree.path != spec_path))
            _require(all(item == repair_files.get(item.path, previous_files.get(item.path))
                for item in projected.files))
            runtime, _ = admit_runtime_inputs(root, state_store.squad_dir, state, runtime_view(sources))
            dependencies = refresh_dependency_comparison(previous, sources,
                history=IdentityHistorySnapshot(**binding.candidate["history"]),
                spec_path=spec_path, run_path=run_path, runtime=runtime)
            execution_input = dict(source=source, dependencies=dependencies)
        _require(state_store.load() == state)
    except Exception:
        raise ValueError("refresh input requires unchanged accepted dependencies") from None
    return state_store.bind_refresh_input(producer, execution_input, expected_state=state)
