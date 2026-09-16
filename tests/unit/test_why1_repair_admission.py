"""WHY1 repair selection authenticates real findings without running repairs."""
from copy import deepcopy
from dataclasses import asdict, replace
import json

import pytest

from tests.unit.test_managed_why1 import (
    case, enrolled, turn_prepared, prepared, checkpoint_case, controller,
    selection, install_why1, Why1Executor,
)


REPORT = """# Issues — WHY1

## Summary
- **CRITICAL:** 0
- **HIGH:** 1
- **MEDIUM:** 0
- **LOW:** 0
- **Verdict:** FAIL

## Issues

### ISS-000001: Audience
- **Severity:** HIGH
- **Type:** incompleteness
- **Description:** Camera evidence is incomplete.
- **Affected artifact:** unknowns.md
- **Affected section:** U-000001
- **Evidence:** The captured camera question has no research source.
- **Recommendation:** Record the missing camera evidence.
- **Responsible agent:** DISCOVER
- **Action Required:** Investigate the camera question.
"""


def select_only(case):
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    from harness.discovery_repair_admission import prepare_why1_discovery_repair
    with PhaseAExecutionLock.acquire(case[0], "test-repair-admission"):
        with SpecRunExecutionLock.acquire(case[1].squad_dir, "test-repair-admission"):
            return prepare_why1_discovery_repair(case[0], case[1])


class RepairFindingExecutor(Why1Executor):
    def __init__(self, provider="codex", *, report=REPORT, verdict="FAIL"):
        super().__init__(provider, finding=True, why_verdict=verdict)
        self.report = report

    def run_inspection_turn(self, *args, **kwargs):
        response = super().run_inspection_turn(*args, **kwargs)
        assignment = self.calls[-1]["assignment"]
        if assignment.get("producer") == "why1" and assignment["step"] == "author":
            reply = json.loads(response.stdout)
            reply["artifacts"]["issues.md"] = self.report
            return replace(response, stdout=json.dumps(reply))
        return response


@pytest.fixture
def finding(tmp_path):
    from harness.element_identity_store import IdentityStore
    from harness.element_identity_lifecycle import ElementCreate
    from harness.discovery_candidate import issue_report_changes
    from harness.element_identity_candidate import CandidateArtifact
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="game", kind="U", operation_id="unknown", count=1)
    artifacts = {"unknowns.md": "# Unknowns\n\n### U-000001: Camera choice\nInvestigate camera.\n"}
    store.apply_lifecycle(spec_id="game", operation_id="create-unknown", changes=(
        ElementCreate(label, "Camera choice", artifacts["unknowns.md"].split("\n\n", 1)[1], "unknown"),))
    reviewed = store.identity_history(spec_id="game")
    label, = store.reserve(spec_id="game", kind="ISS", operation_id="issue", count=1)
    change = ElementCreate(label, "Audience", REPORT.split("### ISS-000001: Audience\n", 1)[1], "issue")
    _, occurrences = issue_report_changes((CandidateArtifact("issues.md", "issues", None, REPORT),),
        (change,), reviewed, report_id="why1-report")
    store.apply_lifecycle(spec_id="game", operation_id="create-issue", changes=(change,))
    store.record_issue_occurrences(spec_id="game", operation_id="report", occurrences=occurrences)
    return artifacts, reviewed, store, occurrences[0]


def test_scope_uses_exact_occurrence_and_reviewed_target_without_widening(finding):
    from harness.discovery_repair_admission import repair_findings
    artifacts, reviewed, store, occurrence = finding
    before = store.identity_history(spec_id="game")
    findings, paths, revisions = repair_findings({**artifacts, "issues.md": REPORT}, before, artifacts, reviewed)
    assert paths == ["unknowns.md"] and revisions == [["U-000001", "1"]]
    assert len(findings) == 1
    detail = json.loads(findings[0]["detail"])
    assert detail["occurrence"] == asdict(occurrence)
    assert detail["target"]["id"] == "U-000001" and detail["target"]["revision"] == "1"
    assert detail["target"]["path"] == "unknowns.md"
    assert store.identity_history(spec_id="game") == before


@pytest.mark.parametrize("producer,damage", [(producer, damage) for producer in ("why1", "why2")
    for damage in (None, "origin", "accepted_review", "verdict", "findings")] + [("why2", "runtime")])
def test_repair_replay_binds_exact_requesting_review(finding, producer, damage):
    """The enclosing completion authenticates these captured images first."""
    from types import SimpleNamespace
    from harness.discovery_completion import _require_repair_origin
    from harness.discovery_repair_admission import repair_findings
    artifacts, reviewed, identity, _ = finding
    history = identity.identity_history(spec_id="game")
    current = {**artifacts, "issues.md": REPORT}
    findings, paths, revisions = repair_findings(current, history, artifacts, reviewed)
    source = dict(review_id="a" * 32, return_phase="phase1-" + producer)
    claim = dict(origin=source, findings=findings, artifact_paths=paths, editable_revisions=revisions)
    def baseline(items):
        return SimpleNamespace(trees=(SimpleNamespace(path="specs/game", files=tuple(
            SimpleNamespace(path="specs/game/" + path, content=text.encode()) for path, text in items.items())),))
    parent = SimpleNamespace(producer=producer, clarification=False,
        candidate={"routing": {"verdict": "FAIL"}}, recovery={"completion_id": "a" * 32, "review": {"verdict": "accept"}},
        baseline=baseline(artifacts), source={"history": asdict(reviewed), "runtime": {"autonomy_mode": "semi"}})
    child = SimpleNamespace(repair_unit="b" * 64, baseline=baseline(current),
        source={"history": asdict(history), "runtime": {"autonomy_mode": "semi"}})
    state = {"managed_discovery_repairs": {"units": {child.repair_unit: {"selection": claim}}}}
    if damage == "origin":
        claim["origin"] = {**source, "return_phase": "phase1-why2" if producer == "why1" else "phase1-why1"}
    elif damage == "accepted_review":
        parent.recovery["review"]["verdict"] = "reject"
    elif damage == "verdict":
        parent.candidate["routing"]["verdict"] = "PASS"
    elif damage == "findings":
        claim["findings"] = []
    elif damage == "runtime":
        child.source["runtime"] = {"autonomy_mode": "banzai"}
    if damage is None:
        _require_repair_origin(state, child, parent)
    else:
        with pytest.raises(ValueError):
            _require_repair_origin(state, child, parent)


@pytest.mark.parametrize("producer", ["why1", "why2"])
def test_why2_discovery_scope_preserves_other_owner_findings(finding, producer):
    from harness.discovery_repair_admission import repair_findings
    from harness.discovery_candidate import issue_report_changes
    from harness.element_identity_candidate import CandidateArtifact
    from harness.element_identity_lifecycle import ElementCreate
    artifacts, reviewed, identity, _ = finding
    label, = identity.reserve(spec_id="game", kind="ISS", operation_id="what-issue", count=1)
    body = ("- **Severity:** HIGH\n- **Type:** incompleteness\n- **Description:** Movement lacks controls.\n"
        "- **Affected artifact:** spec.md\n- **Affected section:** FR-000001\n"
        "- **Evidence:** Controls are unspecified.\n- **Recommendation:** Define controls.\n"
        "- **Responsible agent:** WHAT\n- **Action Required:** Clarify controls.\n")
    report = REPORT.replace("**HIGH:** 1", "**HIGH:** 2") + f"### {label}: Controls\n" + body
    change = ElementCreate(label, "Controls", body, "what-issue")
    _, occurrences = issue_report_changes((CandidateArtifact("issues.md", "issues", REPORT, report),),
        (change,), identity.identity_history(spec_id="game"), report_id="mixed-review")
    identity.apply_lifecycle(spec_id="game", operation_id="mixed-create", changes=(change,))
    identity.record_issue_occurrences(spec_id="game", operation_id="mixed-report", occurrences=occurrences)
    before = identity.identity_history(spec_id="game")
    if producer == "why1":
        with pytest.raises(ValueError):
            repair_findings({**artifacts, "issues.md": report}, before, artifacts, reviewed, review_producer=producer)
    else:
        findings, paths, revisions = repair_findings({**artifacts, "issues.md": report}, before,
            artifacts, reviewed, review_producer=producer)
        assert len(findings) == 1 and paths == ["unknowns.md"] and revisions == [["U-000001", "1"]]
        assert json.loads(findings[0]["detail"])["occurrence"]["issue_id"] == "ISS-000001"
    assert identity.identity_history(spec_id="game") == before


@pytest.mark.parametrize("target,path", [
    ("A-003", "assumptions.md"),
    ("U-10000000000000000000001", "unknowns.md"),
])
def test_selection_preserves_exact_legacy_and_wide_target_ids(tmp_path, target, path):
    from harness.discovery_repair_admission import repair_findings
    from harness.discovery_candidate import issue_report_changes
    from harness.element_identity_candidate import CandidateArtifact
    from harness.element_identity_lifecycle import ElementAdopt, ElementCreate
    from harness.element_identity_store import IdentityStore
    store = IdentityStore.initialize(tmp_path)
    text = f"### {target}: Camera choice\nInvestigate camera.\n"
    store.import_identities(spec_id="game", operation_id="legacy", definitions=((target, "Camera choice"),))
    store.apply_lifecycle(spec_id="game", operation_id="adopt", changes=(ElementAdopt(target, "Camera choice", text),))
    reviewed = store.identity_history(spec_id="game")
    report = REPORT.replace("U-000001", target).replace("unknowns.md", path)
    label, = store.reserve(spec_id="game", kind="ISS", operation_id="reserve", count=1)
    change = ElementCreate(label, "Audience", report.split("### ISS-000001: Audience\n", 1)[1], "reserve")
    _, occurrences = issue_report_changes((CandidateArtifact("issues.md", "issues", None, report),),
        (change,), reviewed, report_id="why1-report")
    store.apply_lifecycle(spec_id="game", operation_id="create", changes=(change,))
    store.record_issue_occurrences(spec_id="game", operation_id="report", occurrences=occurrences)
    findings, paths, revisions = repair_findings({path: text, "issues.md": report},
        store.identity_history(spec_id="game"), {path: text}, reviewed)
    assert paths == [path] and revisions == [[target, "1"]]
    assert json.loads(findings[0]["detail"])["target"]["id"] == target


@pytest.mark.parametrize("damage", ["report", "missing_occurrence", "target_content", "target_revision", "missing_reviewed_target"])
def test_scope_rejects_unproven_occurrences_and_changed_targets(finding, damage):
    from harness.discovery_repair_admission import repair_findings
    from harness.element_identity_lifecycle import ElementRevision
    artifacts, reviewed, store, _ = finding
    current = {**artifacts, "issues.md": REPORT}
    if damage == "report": current["issues.md"] += "Changed report\n"
    elif damage == "target_content": current["unknowns.md"] += "Changed target\n"
    elif damage == "target_revision":
        current["unknowns.md"] += "Changed target\n"
        store.apply_lifecycle(spec_id="game", operation_id="revise", changes=(ElementRevision(
            "U-000001", "1", "Camera choice", current["unknowns.md"].split("\n\n", 1)[1]),))
    elif damage == "missing_reviewed_target": artifacts = {}
    history = reviewed if damage == "missing_occurrence" else store.identity_history(spec_id="game")
    with pytest.raises(ValueError):
        repair_findings(current, history, artifacts, reviewed)


@pytest.mark.parametrize("review_producer", ["why1", "why2"])
@pytest.mark.parametrize("old,new", [
    ("DISCOVER", "WHAT"), ("unknowns.md", "../unknowns.md"),
    ("unknowns.md", "assumptions.md"), ("U-000001", "Camera choice"),
    ("U-000001", "U-000001, U-000002"),
    ("- **Action Required:** Investigate the camera question.", "- **Action Required:** None"),
    ("- **Affected section:** U-000001", "- **Affected section:** U-000001\n- **Affected section:** U-000001"),
    ("- **Affected section:** U-000001", "```\n- **Affected section:** U-000001\n```\nEvidence mentions U-000001."),
    ("- **Affected section:** U-000001", "<!--\n- **Affected section:** U-000001\n-->\nEvidence mentions U-000001."),
])
def test_authentic_but_ambiguous_or_cross_owner_report_cannot_widen_scope(finding, old, new, review_producer):
    from harness.discovery_repair_admission import repair_findings
    from harness.proportional_quality import QualityCandidateIntegrityError
    from harness.discovery_candidate import issue_report_changes
    from harness.element_identity_candidate import CandidateArtifact
    from harness.element_identity_lifecycle import ElementRevision
    artifacts, reviewed, store, _ = finding
    report = REPORT.replace(old, new)
    change = ElementRevision("ISS-000001", "1", "Audience", report.split("### ISS-000001: Audience\n", 1)[1])
    _, occurrences = issue_report_changes((CandidateArtifact("issues.md", "issues", REPORT, report),),
        (change,), store.identity_history(spec_id="game"), report_id="next-report")
    store.apply_lifecycle(spec_id="game", operation_id="revise-issue", changes=(change,))
    store.record_issue_occurrences(spec_id="game", operation_id="next-report", occurrences=occurrences)
    with pytest.raises((ValueError, QualityCandidateIntegrityError)):
        repair_findings({**artifacts, "issues.md": report}, store.identity_history(spec_id="game"), artifacts, reviewed,
            review_producer=review_producer)


@pytest.mark.parametrize("ambiguous_report", [False, "restored", True])
def test_old_issue_occurrence_cannot_authorize_current_repair(finding, ambiguous_report):
    from harness.discovery_repair_admission import repair_findings
    from harness.element_identity_lifecycle import ElementRevision
    artifacts, reviewed, store, occurrence = finding
    store.apply_lifecycle(spec_id="game", operation_id="issue-changed", changes=(
        ElementRevision("ISS-000001", "1", "Audience", "A different finding.\n"),))
    if ambiguous_report:
        store.apply_lifecycle(spec_id="game", operation_id="issue-restored", changes=(
            ElementRevision("ISS-000001", "2", "Audience", occurrence.body),))
    if ambiguous_report is True:
        store.record_issue_occurrences(spec_id="game", operation_id="repeated-report", occurrences=(
            replace(occurrence, issue_revision="3", report_id="zzz-current-report"),))
    with pytest.raises(ValueError):
        repair_findings({**artifacts, "issues.md": REPORT}, store.identity_history(spec_id="game"), artifacts, reviewed)


def test_repair_selection_compare_and_swap_rejects_state_changed_after_authentication(prepared):
    from harness.squad_state import StateAdvanceError
    from tests.unit.test_discovery_repair_retention import released, repair_selection
    state, _, _ = released(prepared)
    store = prepared[1]
    changed = deepcopy(state)
    changed["user_message"] = "A concurrent clarification"
    store.save(changed)
    saved = store.load()
    with pytest.raises(StateAdvanceError):
        store.prepare_discovery_repair(repair_selection(state), expected_state=state)
    assert store.load() == saved and "managed_discovery_repairs" not in saved


@pytest.mark.parametrize("provider,mode,checkpoint", [("codex", "guided", True), ("claude", "banzai", False)])
def test_admission_selects_real_why1_finding_without_dispatching_repair(checkpoint_case, provider, mode, checkpoint):
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = mode
    if not checkpoint:
        for key in ("spec_dir", "checkpoint_policy_version", "phase_completion_outcomes"):
            state.pop(key)
    store.save(state)
    install_why1(checkpoint_case)
    executor = RepairFindingExecutor(provider)
    request = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    assert controller(checkpoint_case, executor).run(managed_discovery=request,
        create_managed_discovery=True).phase == "phase1-discover"
    original = store.load()
    history = identity.identity_history(spec_id="game")
    files = {path: path.read_bytes() for path in (root / "specs/game").rglob("*") if path.is_file()}
    receipts = {path: path.read_bytes() for path in store.squad_dir.glob("*turns*.json")}
    select_only(checkpoint_case)
    saved = store.load()
    assert "managed_discovery_repairs" in saved
    unit, = saved["managed_discovery_repairs"]["units"].values()
    assert unit["attempts"] == []
    selected = unit["selection"]
    assert selected["artifact_paths"] == ["unknowns.md"]
    assert selected["editable_revisions"] == [["U-000001", "2"]]
    assert selected["origin"] == {"review_id": original["last_dispatch"]["dispatch_id"], "return_phase": "phase1-why1"}
    assert selected["source"]["dispatch_id"] == original["last_dispatch"]["dispatch_id"]
    for key in original:
        if key not in {"state_revision", "updated_at"}: assert saved[key] == original[key]
    assert identity.identity_history(spec_id="game") == history
    assert all(path.read_bytes() == content for path, content in {**files, **receipts}.items())
    assert len(executor.calls) == 12 and saved["token_usage"] == 84
    select_only(checkpoint_case)
    assert store.load() == saved and len(executor.calls) == 12


def test_controller_refuses_changed_review_inputs_and_preserves_selected_attempts(checkpoint_case):
    from harness.squad_state import SquadStateStore
    root, store, identity, _ = checkpoint_case
    install_why1(checkpoint_case)
    executor = RepairFindingExecutor()
    request = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    assert controller(checkpoint_case, executor).run(managed_discovery=request,
        create_managed_discovery=True).phase == "phase1-discover"
    original = store.load()
    input_tree = root / original["managed_discovery_operation"]["binding"]["input_tree"]
    input_file = next(path for path in input_tree.rglob("*") if path.is_file())
    paths = [root / "specs/game/issues.md", root / "specs/game/assumption-review.md",
        root / "specs/game/unknowns.md", input_file,
        store.squad_dir / "context/current-feature-context.md",
        store.squad_dir / "reasoning-journal.jsonl",
        root / ".echelon/prosaic/agents/exploration/templates/sage-issues-template.md"]
    for path in paths:
        before = path.read_bytes() if path.exists() else None
        try:
            path.write_bytes((before or b"") + b"Changed after review\n")
            result = controller(checkpoint_case, executor).run(managed_discovery=request)
            assert result.summary == "managed_review_repair_requires_reconciliation", (path, result)
            assert store.load() == original and len(executor.calls) == 12
        finally:
            if before is None: path.unlink()
            else: path.write_bytes(before)
    select_only(checkpoint_case)
    unit_id, = store.load()["managed_discovery_repairs"]["units"]
    store.advance_discovery_repair(unit_id, "begin")
    saved = store.load()
    select_only(checkpoint_case)
    assert SquadStateStore(store.squad_dir).load() == saved
    assert len(saved["managed_discovery_repairs"]["units"][unit_id]["attempts"]) == 1
    assert len(executor.calls) == 12 and identity.pending_identity_publication(spec_id="game") is None


def test_forced_convergence_cannot_be_relabelled_as_repair(checkpoint_case):
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state.update(iteration=3, max_iterations=3)
    store.save(state)
    install_why1(checkpoint_case)
    executor = RepairFindingExecutor()
    request = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    assert controller(checkpoint_case, executor).run(managed_discovery=request,
        create_managed_discovery=True).phase == "phase1-constitution"
    damaged = store.load()
    damaged["phase"] = "phase1-discover"
    store.save(damaged)
    saved = store.load()
    result = controller(checkpoint_case, executor).run(managed_discovery=request)
    assert result.summary == "managed_review_repair_requires_reconciliation", result
    assert store.load() == saved and "managed_discovery_repairs" not in saved
    assert len(executor.calls) == 12 and identity.pending_identity_publication(spec_id="game") is None
