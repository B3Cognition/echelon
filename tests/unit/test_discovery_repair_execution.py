"""Selected repairs reuse execution owners without replacing accepted history."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from tests.unit.test_why1_repair_admission import (
    case, enrolled, turn_prepared, prepared, checkpoint_case, controller as full_controller, selection,
    install_why1, RepairFindingExecutor,
)


def controller(prepared, executor):
    """Stop at released repair for isolated repair/input/proof tests.

    Automatic ordering is covered separately with the unmodified controller in
    test_managed_repair_refresh. This fixture still authenticates the repair and
    live sources; it only withholds selection of the next producer.
    """
    from types import MethodType
    ctrl = full_controller(prepared, executor)
    def stop_at_repair(self, selected):
        state = self._state_store.load()
        if ((state.get("last_dispatch") or {}).get("phase_id") == "phase1-discover"
                and state.get("managed_discovery_repairs") is not None):
            from harness.discovery_repair_admission import _repair_refresh_context
            try:
                _repair_refresh_context(self._project_root, self._state_store, "why1")
            except Exception:
                return self._managed_discovery_stop("managed_review_repair_requires_reconciliation")
            return self._managed_discovery_stop("managed_repair_dependency_refresh_not_supported")
        return None
    ctrl._prepare_managed_repair_refresh = MethodType(stop_at_repair, ctrl)
    return ctrl


def selected_repair(prepared):
    from tests.unit.test_discovery_repair_retention import released, repair_selection
    state, _, _ = released(prepared)
    store = prepared[1]
    store.prepare_discovery_repair(repair_selection(state))
    state = store.load()
    state["phase"] = "phase1-discover"
    store.save(state)
    unit, = state["managed_discovery_repairs"]["units"]
    claim = state["managed_discovery_repairs"]["units"][unit]["selection"]
    binding = deepcopy(state["managed_discovery_operation"]["binding"])
    binding.update(operation_id="discovery-repair-" + unit, artifact_paths=claim["artifact_paths"],
        editable_revisions=claim["editable_revisions"], unowned_writable_paths=[],
        intent=dict(kind="repair", request="Repair the selected findings.",
            origin=claim["origin"], findings=claim["findings"]))
    return store, unit, binding


def test_repair_execution_has_one_durable_attempt_authority(prepared):
    from harness.discovery_operation_state import operation_from_state
    from harness.squad_state import SquadStateStore, StateAdvanceError
    store, unit, binding = selected_repair(prepared)
    original = deepcopy(store.load()["managed_discovery_operation"])
    store.advance_discovery_operation(binding, "prepare", repair_unit=unit)
    for number in range(1, 4):
        store.advance_discovery_operation(binding, "begin", repair_unit=unit)
        reopened = SquadStateStore(store.squad_dir)
        before = reopened.load()
        reopened.advance_discovery_operation(binding, "begin", repair_unit=unit)
        assert reopened.load() == before
        assert len(operation_from_state(before, repair_unit=unit)["attempts"]) == number
        store.advance_discovery_operation(binding, "finish", repair_unit=unit, result=dict(
            status="rejected", candidate_sha256=str(number) * 64,
            findings_sha256="a" * 64, progress_sha256=str(number) * 64))
    saved = store.load()
    assert saved["managed_discovery_operation"] == original
    assert "attempts" not in saved["managed_discovery_repairs"]["units"][unit]["execution"]
    assert saved["phase_dispatch_counts"]["phase1-discover"] == 2
    with pytest.raises(StateAdvanceError):
        store.advance_discovery_operation(binding, "begin", repair_unit=unit)
    assert store.load() == saved


def test_repair_execution_binding_and_turns_cannot_change(prepared):
    from harness.squad_state import StateAdvanceError
    store, unit, binding = selected_repair(prepared)
    store.advance_discovery_operation(binding, "prepare", repair_unit=unit)
    marker = dict(schema_version=1, operation_id=binding["operation_id"], binding_sha256="d" * 64)
    store.prepare_discovery_turns(marker, repair_unit=unit)
    saved = store.load()
    for change in ("scope", "origin", "fingerprint", "operation_id"):
        altered = deepcopy(binding)
        if change == "scope": altered["editable_revisions"] = [["U-000001", "2"]]
        elif change == "origin": altered["intent"]["origin"]["review_id"] = "other"
        else: altered[change] = "e" * 64
        with pytest.raises(StateAdvanceError):
            store.advance_discovery_operation(altered, "prepare", repair_unit=unit)
        assert store.load() == saved
    with pytest.raises((StateAdvanceError, ValueError)):
        store.prepare_discovery_turns({**marker, "binding_sha256": "e" * 64}, repair_unit=unit)
    altered = deepcopy(saved)
    altered["managed_discovery_repairs"]["units"][unit]["execution"]["turns"] = None
    with pytest.raises(StateAdvanceError):
        store.save(altered)
    assert store.load() == saved


def test_repair_dispatch_count_cannot_be_reset(prepared):
    store, unit, binding = selected_repair(prepared)
    store.advance_discovery_operation(binding, "prepare", repair_unit=unit)
    changed = store.load()
    changed["phase_dispatch_counts"]["phase1-discover"] = 1
    store.save(changed)
    saved = store.load()
    with pytest.raises(ValueError):
        controller(prepared, RepairExecutor())._admit_managed_discovery(selection(prepared), False)
    assert store.load() == saved


@pytest.mark.parametrize("expansion", ["new_subject", "omitted_target"])
def test_repair_cannot_allocate_or_omit_selected_revision(prepared, expansion):
    from harness.discovery_operation import run_discovery_operation
    from tests.unit.test_discovery_turns import ScriptedExecutor
    store, unit, binding = selected_repair(prepared)
    class Expanded(ScriptedExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            response = super().run_inspection_turn(*args, **kwargs)
            assignment = self.calls[-1]["assignment"]
            fields = dict(new_subjects=[], revisions=[])
            if expansion == "new_subject":
                fields = dict(new_subjects=[dict(key="unrequested", kind="U", subject="Unrelated multiplayer", caption="Multiplayer")],
                    revisions=[dict(id="U-000001", expected_revision="1")])
            return replace(response, stdout=json.dumps({**assignment, "action": "final", **fields}))
    executor = Expanded()
    outcome = run_discovery_operation(prepared[0], store, executor, repair_unit=unit, create=True,
        input_tree="inputs", artifact_paths=("unknowns.md",), editable_revisions=(("U-000001", "1"),), intent=binding["intent"])
    assert outcome.reason == "discovery_repair_proposal_outside_scope", outcome
    assert len(executor.calls) == 1
    assert prepared[2].reserve(spec_id="game", kind="U", operation_id="next", count=1) == ("U-000002",)


def test_repair_completion_cannot_use_unreviewed_discovery_as_parent(prepared):
    from harness.discovery_operation import run_discovery_operation
    from harness.discovery_publication import prepare_discovery_publication
    from harness.discovery_completion import authenticate
    from harness.element_identity_publication import encode_publication_request
    from harness.squad_completion import CompletionError
    from tests.unit.test_discovery_turns import ScriptedExecutor
    store, unit, binding = selected_repair(prepared)
    class Reviser(ScriptedExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            response = super().run_inspection_turn(*args, **kwargs)
            assignment, context = self.calls[-1]["assignment"], self.calls[-1]["context"]
            if assignment["step"] == "propose":
                fields = dict(new_subjects=[], revisions=[dict(id="U-000001", expected_revision="1")])
            elif assignment["step"] == "author":
                fields = dict(artifacts={"unknowns.md": context["baseline"]["unknowns.md"] + "Investigate the camera prototype.\n"})
            else:
                fields = dict(verdict="accept", reason="Same subject.", assessments=[dict(id="U-000001",
                    verdict="accept", reason="Clearer question.", evidence=[context["citations"]["U-000001"]])])
            return replace(response, stdout=json.dumps({**assignment, "action": "final", **fields}))
    executor = Reviser()
    outcome = run_discovery_operation(prepared[0], store, executor, repair_unit=unit, create=True,
        input_tree="inputs", artifact_paths=("unknowns.md",), editable_revisions=(("U-000001", "1"),), intent=binding["intent"])
    assert outcome.status == "reviewed", outcome
    package = prepare_discovery_publication(prepared[0], store, executor, completion_id="a" * 32, repair_unit=unit)
    ctrl = controller(prepared, executor)
    completion = ctrl._prepare_spec_step_effects(from_phase="phase1-discover", to_phase="phase1-why1",
        snapshot=store.capture_routing_snapshot(expected_phase="phase1-discover"), manual_phase_run=False,
        conditional_skip=False, record_completion=True, publication_marker=package.publication.marker.to_dict(),
        completion_id="a" * 32, managed_discovery_request=encode_publication_request(package.request))
    with pytest.raises(CompletionError):
        authenticate(prepared[0], store.squad_dir, store.load(), completion)
    assert prepared[2].pending_identity_publication(spec_id="game") is None


class RepairExecutor(RepairFindingExecutor):
    def __init__(self, provider="codex", *, reject=False, progress=False, interrupt_step=None, assumption=False):
        super().__init__(provider)
        self.repair_reject, self.repair_progress, self.interrupt_step = reject, progress, interrupt_step
        self.assumption = assumption
        if assumption:
            self.report = self.report.replace("unknowns.md", "assumptions.md").replace("U-000001", "A-000001")

    def run_inspection_turn(self, *args, **kwargs):
        assignment = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])["assignment"]
        if not assignment["operation_id"].startswith("discovery-repair-"):
            response = super().run_inspection_turn(*args, **kwargs)
            if self.assumption and assignment["operation_id"] == "discovery":
                reply = json.loads(response.stdout)
                if assignment["step"] == "propose":
                    reply["new_subjects"].append(dict(key="controls", kind="A", subject="Prototype camera controls", caption="Prototype camera controls"))
                elif assignment["step"] == "author":
                    reply["artifacts"]["assumptions.md"] = "### A-000001: Prototype camera controls\nThe prototype uses camera-relative controls pending research.\n"
                response = replace(response, stdout=json.dumps(reply))
            return response
        if assignment["step"] == self.interrupt_step:
            from tests.unit.test_discovery_turns import Interrupted
            raise Interrupted()
        from tests.unit.test_discovery_turns import ScriptedExecutor
        response = ScriptedExecutor.run_inspection_turn(self, *args, **kwargs)
        context = self.calls[-1]["context"]
        label, revision = ("A-000001", "1") if self.assumption else ("U-000001", "2")
        path = "assumptions.md" if self.assumption else "unknowns.md"
        if assignment["step"] == "propose":
            fields = dict(new_subjects=[], revisions=[dict(id=label, expected_revision=revision)])
        elif assignment["step"] == "author":
            fields = dict(artifacts={path: context["baseline"][path] +
                "Camera research remains unresolved; verify the isometric view with a scene prototype.\n"})
            if self.repair_progress:
                fields["artifacts"][path] += {
                    "attempt-1-author": "Compare camera projections in the scene prototype.\n",
                    "attempt-2-author": "Walk through camera-relative keyboard movement.\n",
                    "attempt-3-author": "Check camera visibility through foreground occlusion.\n",
                }[assignment["dispatch_id"]]
        else:
            verdict = "reject" if self.repair_reject else "accept"
            fields = dict(verdict=verdict, reason="The missing research is explicit.",
                assessments=[dict(id=label, verdict=verdict, reason="Same camera subject, clarified evidence.",
                    evidence=[context["citations"][label]])])
        return replace(response, stdout=json.dumps({**assignment, "action": "final", **fields}))


@pytest.mark.parametrize("provider,mode,checkpoint,assumption", [("codex", "guided", True, False), ("claude", "banzai", False, False), ("codex", "semi", True, True)])
def test_repair_publishes_same_subject_revision_and_stops_before_refresh(checkpoint_case, provider, mode, checkpoint, assumption):
    root, store, identity, _ = checkpoint_case
    initial = store.load()
    initial["autonomy_mode"] = mode
    if not checkpoint:
        for key in ("spec_dir", "checkpoint_policy_version", "phase_completion_outcomes"):
            initial.pop(key)
    store.save(initial)
    install_why1(checkpoint_case)
    executor = RepairExecutor(provider, assumption=assumption)
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    assert controller(checkpoint_case, executor).run(managed_discovery=selected,
        create_managed_discovery=True).phase == "phase1-discover"
    original = store.load()
    history = json.loads(identity.identity_history(spec_id="game").payload)
    receipts = {path.name: path.read_bytes() for path in store.squad_dir.glob("*turns*.json")}
    result = controller(checkpoint_case, executor).run(managed_discovery=selected)
    assert result.phase == "phase1-why1" and result.summary == "managed_repair_dependency_refresh_not_supported", result
    saved = store.load()
    assert saved["token_usage"] == 105 and len(executor.calls) == 15
    for key in ("managed_discovery_operation", "managed_discovery_turns", "managed_synthesizer_operation",
            "managed_synthesizer_turns", "managed_tracker_rounds", "managed_why1_rounds"):
        assert saved[key] == original[key]
    assert {name: (store.squad_dir / name).read_bytes() for name in receipts} == receipts
    current = json.loads(identity.identity_history(spec_id="game").payload)
    assert current["issue_occurrences"] == history["issue_occurrences"]
    assert all(row in current["revisions"] for row in history["revisions"])
    assert all(row in current["reference_claims"] for row in history["reference_claims"])
    assert {row["element_id"]: row["subject"] for row in current["entities"]} == {
        row["element_id"]: row["subject"] for row in history["entities"]}
    expected = {("U-000001", "2"), ("A-000001", "2")} if assumption else {("U-000001", "3")}
    assert {(row["element_id"], row["revision"]) for row in current["entities"]} == expected | {("UI-000001", "1"), ("ISS-000001", "1")}
    path = "assumptions.md" if assumption else "unknowns.md"
    assert "Camera research remains unresolved" in (root / "specs/game" / path).read_text()
    assert identity.pending_identity_publication(spec_id="game") is None
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).summary == result.summary
    assert store.load() == saved and len(executor.calls) == 15


@pytest.mark.parametrize("point", ["accepted", "promoted", "released"])
def test_repair_recovery_does_not_repeat_provider_or_publication(checkpoint_case, monkeypatch, point):
    from harness.element_identity_store import IdentityStore
    from tests.unit.test_discovery_turns import Interrupted
    import harness.discovery_publication as publication
    root, store, identity, _ = checkpoint_case
    install_why1(checkpoint_case)
    executor = RepairExecutor()
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    assert controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True).phase == "phase1-discover"
    owner, method = ((publication, "prepare_discovery_publication") if point == "accepted" else
        (IdentityStore, "apply_identity_publication" if point == "promoted" else "release_identity_publication"))
    original = getattr(owner, method)
    def interrupt(*args, **kwargs):
        if point != "accepted": original(*args, **kwargs)
        raise Interrupted()
    with monkeypatch.context() as patch:
        patch.setattr(owner, method, interrupt)
        with pytest.raises(Interrupted):
            controller(checkpoint_case, executor).run(managed_discovery=selected)
    assert len(executor.calls) == 15
    attempts = deepcopy(next(iter(store.load()["managed_discovery_repairs"]["units"].values()))["attempts"])
    result = controller(checkpoint_case, executor).run(managed_discovery=selected)
    assert result.summary == "managed_repair_dependency_refresh_not_supported", result
    saved = store.load()
    assert next(iter(saved["managed_discovery_repairs"]["units"].values()))["attempts"] == attempts
    assert saved["token_usage"] == 105 and len(executor.calls) == 15
    assert identity.pending_identity_publication(spec_id="game") is None
    assert not list((store.squad_dir / ".spec-step-effects").iterdir())


@pytest.mark.parametrize("progress,attempts,reason", [(False, 2, "discovery_no_progress"), (True, 3, "discovery_attempts_exhausted")])
def test_repair_retry_budget_survives_restart(checkpoint_case, progress, attempts, reason):
    root, store, identity, _ = checkpoint_case
    install_why1(checkpoint_case)
    executor = RepairExecutor(reject=True, progress=progress)
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    assert controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True).phase == "phase1-discover"
    history = identity.identity_history(spec_id="game")
    result = controller(checkpoint_case, executor).run(managed_discovery=selected)
    assert result.summary == reason, result
    saved = store.load()
    record, = saved["managed_discovery_repairs"]["units"].values()
    assert len(record["attempts"]) == attempts and all(row["result"]["status"] == "rejected" for row in record["attempts"])
    assert len(executor.calls) == 12 + 3 * attempts
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).summary == reason
    assert store.load() == saved and len(executor.calls) == 12 + 3 * attempts
    assert identity.identity_history(spec_id="game") == history


def test_unknown_repair_provider_completion_blocks_without_reset(checkpoint_case):
    from tests.unit.test_discovery_turns import Interrupted
    from harness.discovery_turns import read_discovery_usage
    root, store, identity, _ = checkpoint_case
    install_why1(checkpoint_case)
    executor = RepairExecutor(interrupt_step="author")
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True)
    history = identity.identity_history(spec_id="game")
    with pytest.raises(Interrupted):
        controller(checkpoint_case, executor).run(managed_discovery=selected)
    saved = store.load()
    unit, = saved["managed_discovery_repairs"]["units"]
    assert read_discovery_usage(store, repair_unit=unit) == dict(token_usage=None, dispatch_count=2)
    executor.interrupt_step = None
    result = controller(checkpoint_case, executor).run(managed_discovery=selected)
    assert result.summary == "provider_completion_unknown", result
    assert store.load() == saved and len(executor.calls) == 13
    assert identity.identity_history(spec_id="game") == history


def test_accepted_repair_requires_exact_sources_and_receipts(checkpoint_case, monkeypatch):
    from tests.unit.test_discovery_turns import Interrupted
    import harness.discovery_publication as publication
    root, store, identity, _ = checkpoint_case
    install_why1(checkpoint_case)
    executor = RepairExecutor()
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    assert controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True).phase == "phase1-discover"
    def stop(*args, **kwargs): raise Interrupted()
    with monkeypatch.context() as patch:
        patch.setattr(publication, "prepare_discovery_publication", stop)
        with pytest.raises(Interrupted): controller(checkpoint_case, executor).run(managed_discovery=selected)
    saved = store.load()
    unit, = saved["managed_discovery_repairs"]["units"]
    history = identity.identity_history(spec_id="game")
    paths = [root / "specs/game/issues.md", root / "specs/game/unknowns.md",
        store.squad_dir / "context/current-feature-context.md",
        root / ".echelon/prosaic/agents/exploration/templates/sage-issues-template.md",
        store.squad_dir / f"discovery-turns-repair-{unit}.json",
        store.squad_dir / f"discovery-reservations-repair-{unit}.json"]
    checks = [(path, "corrupt") for path in paths] + [(path, "missing") for path in paths[-2:]]
    for path, damage in checks:
        before = path.read_bytes()
        try:
            if damage == "missing": path.unlink()
            else: path.write_bytes(before + b"Changed after acceptance\n")
            result = controller(checkpoint_case, executor).run(managed_discovery=selected)
            assert result.status == "blocked" and result.phase == "phase1-discover", (path, result)
            if damage == "missing": assert not path.exists()
            assert store.load() == saved and len(executor.calls) == 15
            assert identity.identity_history(spec_id="game") == history
        finally:
            path.write_bytes(before)
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).summary == "managed_repair_dependency_refresh_not_supported"
    assert len(executor.calls) == 15 and store.load()["token_usage"] == 105


def test_repair_readonly_drift_after_staging_blocks_promotion(checkpoint_case, monkeypatch):
    import harness.discovery_publication as publication
    root, store, identity, _ = checkpoint_case
    install_why1(checkpoint_case)
    executor = RepairExecutor()
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    assert controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True).phase == "phase1-discover"
    history = identity.identity_history(spec_id="game")
    target = root / "specs/game/issues.md"
    before = target.read_bytes()
    original = publication.prepare_discovery_publication
    def drift(*args, **kwargs):
        package = original(*args, **kwargs)
        target.write_bytes(before + b"Drift after staging\n")
        return package
    try:
        with monkeypatch.context() as patch:
            patch.setattr(publication, "prepare_discovery_publication", drift)
            result = controller(checkpoint_case, executor).run(managed_discovery=selected)
        assert result.status == "blocked" and result.summary != "managed_repair_dependency_refresh_not_supported", result
        assert identity.identity_history(spec_id="game") == history
        assert "Camera research remains unresolved" not in (root / "specs/game/unknowns.md").read_text()
        assert len(executor.calls) == 15
    finally:
        target.write_bytes(before)
    result = controller(checkpoint_case, executor).run(managed_discovery=selected)
    assert result.summary == "managed_repair_dependency_refresh_not_supported", result
    assert len(executor.calls) == 15 and store.load()["token_usage"] == 105
