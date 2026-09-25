"""Managed WHY2 uses real completion and quality owners, scripted providers only."""
from dataclasses import replace
import json
from pathlib import Path

import pytest
import yaml

from tests.unit.test_managed_what import (case, enrolled, turn_prepared, prepared,
    checkpoint_case, controller, selection, install_what, WhatExecutor, ScriptedExecutor)
from tests.unit.test_managed_spec_contract import PASS_ISSUES, routing


REPAIR_ISSUES = """# Issues — WHY2

## Summary
- **CRITICAL:** 0
- **HIGH:** 0
- **MEDIUM:** 0
- **LOW:** 1
- **Verdict:** FAIL

## Issues

### ISS-000001: Movement controls
- **Severity:** LOW
- **Type:** incompleteness
- **Description:** The movement requirement does not identify its controls.
- **Affected artifact:** spec.md
- **Affected section:** FR-000001
- **Evidence:** AC-000001 already identifies arrow keys.
- **Recommendation:** Align the movement requirement with its acceptance criterion.
- **Responsible agent:** WHAT
- **Action Required:** Amend FR-000001 without changing its identity.

### Resolution Guidance
- **Decision required:** No user decision — agent repair
- **Suggested option:** Use the existing arrow-key acceptance criterion.
- **Evidence basis:** AC-000001
- **Values not inferable:** None
- **Banzai eligible:** no
"""

RESOLVED_ISSUES = REPAIR_ISSUES.replace("**Verdict:** FAIL", "**Verdict:** PASS").replace(
    "The movement requirement does not identify its controls.",
    "Resolved: FR-000001 now identifies the arrow keys already specified by AC-000001.").replace(
    "**Action Required:** Amend FR-000001 without changing its identity.",
    "**Action Required:** None — advisory: repair verified against the current specification.")


@pytest.mark.parametrize("restart", [False, True])
def test_why2_controller_continues_discovery_refresh_before_selecting_worker(monkeypatch, restart):
    """Orchestration only: proof owners are exercised by the full corridor test."""
    from types import SimpleNamespace
    from harness.squad import SquadController
    ctrl = object.__new__(SquadController)
    ctrl._cancelled = False
    state = dict(phase="phase1-why2", status="running", managed_discovery_repairs={},
        last_dispatch=dict(phase_id="phase1-discover" if restart else "phase1-understanding"))
    ctrl._state_store = SimpleNamespace(load=lambda: dict(state))
    seen = []
    def refresh(selected):
        assert state["phase"] == "phase1-why2" and state["last_dispatch"]["phase_id"] == "phase1-discover"
        seen.append("refresh")
        state["phase"] = "phase1-synthesizer"
    def worker(selected):
        seen.append((state["phase"], selected["through_phase"]))
        if state["phase"] == "phase1-why2":
            state.update(phase="phase1-discover", last_dispatch=dict(phase_id="phase1-why2"))
        elif state["phase"] == "phase1-discover":
            state.update(phase="phase1-why2", last_dispatch=dict(phase_id="phase1-discover"))
            return ctrl._run_managed_discovery_locked(dict(through_phase="phase1-why2"))
        else:
            assert state["phase"] == "phase1-synthesizer"
            state["phase"] = "checkpoint-assess"
        return "boundary"
    monkeypatch.setattr(ctrl, "_prepare_managed_repair_refresh", refresh)
    monkeypatch.setattr(ctrl, "_run_managed_discovery_phase_locked", worker)
    monkeypatch.setattr(ctrl, "_managed_discovery_stop", lambda reason: reason)
    assert ctrl._run_managed_discovery_locked(dict(through_phase="phase1-why2")) == "boundary"
    assert state["phase"] == "checkpoint-assess"
    assert seen == ([] if restart else [("phase1-why2", "phase1-why2"), ("phase1-discover", "phase1-what")]) + [
        "refresh", ("phase1-synthesizer", "phase1-what")]


@pytest.mark.parametrize("cancel", ["controller", "state"])
def test_cancelled_why2_return_cannot_select_or_activate_refresh(monkeypatch, cancel):
    from copy import deepcopy
    from types import SimpleNamespace
    from harness.squad import SquadController
    ctrl = object.__new__(SquadController)
    ctrl._cancelled = cancel == "controller"
    state = dict(phase="phase1-why2", status="running", managed_discovery_repairs={},
        last_dispatch=dict(phase_id="phase1-discover"), cancel_requested=cancel == "state")
    before = deepcopy(state)
    ctrl._state_store = SimpleNamespace(load=lambda: deepcopy(state))
    def forbidden(*args):
        pytest.fail("Cancelled run must not enter a mutating refresh or worker")
    monkeypatch.setattr(ctrl, "_prepare_managed_repair_refresh", forbidden)
    monkeypatch.setattr(ctrl, "_run_managed_discovery_phase_locked", forbidden)
    monkeypatch.setattr(ctrl, "_managed_discovery_stop", lambda reason: reason)
    assert ctrl._run_managed_discovery_locked(dict(through_phase="phase1-why2")) == "managed_discovery_not_running"
    assert state == before


@pytest.mark.parametrize("dispatch", ["phase1-discover", "phase1-understanding"])
def test_why2_refresh_entry_uses_existing_repair_owners(monkeypatch, dispatch):
    from types import SimpleNamespace
    from harness.squad import SquadController
    import harness.discovery_repair_admission as admission
    ctrl = object.__new__(SquadController)
    ctrl._project_root = Path("/unused")
    state = dict(phase="phase1-why2", managed_discovery_repairs={}, last_dispatch=dict(phase_id=dispatch))
    seen = []
    ctrl._state_store = SimpleNamespace(load=lambda: state,
        activate_refresh_round=lambda producer, **kwargs: seen.append(("activate", producer)))
    monkeypatch.setattr(admission, "pin_why1_tracker_history", lambda *args: seen.append("pin"))
    monkeypatch.setattr(admission, "prepare_repair_refresh_round", lambda root, store, producer: seen.append(("prepare", producer)))
    monkeypatch.setattr(admission, "bind_repair_refresh_input", lambda root, store, producer: seen.append(("bind", producer)) or state)
    monkeypatch.setattr(ctrl, "_managed_discovery_stop", lambda reason: reason)
    assert ctrl._prepare_managed_repair_refresh(dict(through_phase="phase1-why2")) is None
    assert seen == (["pin", ("prepare", "synthesizer"), ("prepare", "tracker"), ("prepare", "why1"),
        ("bind", "synthesizer"), ("activate", "synthesizer")] if dispatch == "phase1-discover" else [])


def test_new_why2_question_enters_existing_resolution_owner_before_return(monkeypatch):
    from types import SimpleNamespace
    from harness.squad import SquadController
    ctrl = object.__new__(SquadController)
    ctrl._cancelled = False
    state = dict(phase="phase1-why2", status="running")
    ctrl._state_store = SimpleNamespace(load=lambda: dict(state))
    seen = []
    monkeypatch.setattr(ctrl, "_unresolved_human_input_decision", lambda current: current.get("question"))
    monkeypatch.setattr(ctrl, "_unresolved_human_input_result", lambda current: "human-checkpoint")
    def worker(selected):
        seen.append("review")
        state.update(question={"resolution_handler": "clarification_resume"}, status="blocked")
        return "worker-boundary"
    def resume():
        seen.append("native-resolution")
        return False
    monkeypatch.setattr(ctrl, "_run_managed_discovery_phase_locked", worker)
    monkeypatch.setattr(ctrl, "resume_pending_human_input", resume)
    assert ctrl._run_managed_discovery_locked(dict(through_phase="phase1-why2")) == "human-checkpoint"
    assert seen == ["review", "native-resolution"]


@pytest.mark.parametrize("publication_state", ["applied", "released"])
@pytest.mark.parametrize("damage", [None, "receipt", "producer", "clarification", "unfinished"])
def test_why2_wait_recovers_exact_completed_stage_before_release(tmp_path, monkeypatch, publication_state, damage):
    """Admission chooses the correct proof owner; neither path resolves a decision."""
    from copy import deepcopy
    from types import SimpleNamespace
    import harness.discovery_completion as completion
    import harness.squad as squad
    from harness.element_identity_store import IdentityStore
    from tests.unit.test_phase1_quality_debt import _sealed_decision
    controller = object.__new__(squad.SquadController)
    controller._project_root, controller._squad_dir = tmp_path, tmp_path / "run"
    source = dict(dispatch_id="a" * 32, completion_intent_sha256="b" * 64,
        completion_receipts_sha256="c" * 64, completed_publication_binding_sha256="d" * 64)
    state = dict(blocked_decision=_sealed_decision(), managed_identity={"spec_id": "game"},
        last_dispatch=dict(source, phase_id="phase1-why2", post_dispatch_complete=damage != "unfinished"))
    if damage == "receipt":
        state["last_dispatch"]["completion_receipts_sha256"] = "e" * 64
    before = deepcopy(state)
    binding = SimpleNamespace(producer="what" if damage == "producer" else "why2", clarification=damage == "clarification")
    prepared, seen = object(), []
    def retained(**kwargs):
        assert kwargs == dict(spec_id="game", operation_id="discovery-completion-" + source["dispatch_id"])
        return dict(state=publication_state)
    monkeypatch.setattr(IdentityStore, "open", lambda root: SimpleNamespace(identity_publication=retained))
    def load(root, run, marker):
        assert marker == dict(schema_version=1, completion_id=source["dispatch_id"],
            intent_sha256=source["completion_intent_sha256"], receipts_sha256=source["completion_receipts_sha256"],
            publication_binding_sha256=source["completed_publication_binding_sha256"], origin="routed", step="complete")
        seen.append("stage")
        return prepared
    monkeypatch.setattr(squad, "load_prepared_spec_step_effects", load)
    def authenticate(root, run, current, value):
        assert value is prepared and current == state
        seen.append("authenticate")
        return binding
    monkeypatch.setattr(completion, "authenticate", authenticate)
    def project(root, run, current, store, **kwargs):
        assert publication_state == "released"
        assert kwargs["source"] == source
        seen.append("released")
        return binding, None, None
    monkeypatch.setattr(completion, "_retained_input_projection", project)
    assert controller._managed_why2_completion_wait(state) is (damage is None)
    if damage is None:
        assert seen == (["released"] if publication_state == "released" else ["stage", "authenticate"])
    assert state == before


class RepairExecutor(WhatExecutor):
    """Script provider claims; all repair routing and publication remain real."""
    def run_inspection_turn(self, *args, **kwargs):
        payload = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])
        assignment, context = payload["assignment"], payload["context"]
        producer = assignment.get("producer")
        if producer == "what" and assignment["editable_revisions"]:
            from tests.unit.test_managed_spec_contract import SPEC
            response = ScriptedExecutor.run_inspection_turn(self, *args, **kwargs)
            if assignment["step"] == "propose":
                fields = dict(new_subjects=[], revisions=[dict(id=label, expected_revision=revision)
                    for label, revision in assignment["editable_revisions"] if label == "FR-000001"])
            elif assignment["step"] == "author":
                fields = dict(artifacts={"spec.md": SPEC.replace("across the generated scene.",
                    "across the generated scene using arrow keys."),
                    "requirements-overview.md": context["baseline"]["requirements-overview.md"]}, routing=routing())
            else:
                fields = dict(verdict="accept", reason="Existing acceptance criterion grounds the repair.",
                    assessments=[dict(id=label, verdict="accept", reason="Controls now match acceptance.",
                        evidence=[context["citations"][label]]) for label in assignment["assigned_ids"]])
        elif producer == "why2":
            response = ScriptedExecutor.run_inspection_turn(self, *args, **kwargs)
            repaired = "using arrow keys." in context["baseline"]["spec.md"]
            if assignment["step"] == "propose":
                fields = dict(new_subjects=[] if repaired else [dict(key="controls", kind="ISS",
                    subject="Movement controls", caption="Movement controls")],
                    revisions=[dict(id=label, expected_revision=revision)
                        for label, revision in assignment["editable_revisions"]] if repaired else [])
            elif assignment["step"] == "author":
                claim = routing("why2")
                if not repaired:
                    claim["verdict"] = "FAIL"
                    claim["state_updates"]["finding_routes"]["findings"] = [dict(issue_id="ISS-000001",
                        route="spec_repair", rationale="Align FR-000001 with the existing acceptance criterion.")]
                fields = dict(artifacts={"issues.md": RESOLVED_ISSUES if repaired else REPAIR_ISSUES,
                    "quality-gates.md": "# Quality Gates — WHY2\n\n## Verdict: " + claim["verdict"] + "\n"}, routing=claim)
            else:
                fields = dict(verdict="accept", reason="Review agrees with captured requirements.",
                    assessments=[dict(id=label, verdict="accept", reason="Requirement and criterion differ.",
                        evidence=[context["citations"][label]]) for label in assignment["assigned_ids"]])
        else:
            return super().run_inspection_turn(*args, **kwargs)
        return replace(response, stdout=json.dumps({**assignment, "action": "final", **fields}))


class Why2Executor(WhatExecutor):
    def run_inspection_turn(self, *args, **kwargs):
        assignment = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])["assignment"]
        if assignment.get("producer") != "why2":
            return super().run_inspection_turn(*args, **kwargs)
        response = ScriptedExecutor.run_inspection_turn(self, *args, **kwargs)
        if assignment["step"] == "propose":
            fields = dict(new_subjects=[], revisions=[])
        elif assignment["step"] == "author":
            fields = dict(artifacts={"issues.md": PASS_ISSUES,
                "quality-gates.md": "# Quality Gates — WHY2\n\n## Verdict: PASS\n"}, routing=routing("why2"))
        else:
            fields = dict(verdict="accept", reason="No unresolved semantic findings.", assessments=[])
        return replace(response, stdout=json.dumps({**assignment, "action": "final", **fields}))


class DefaultChoiceExecutor(RepairExecutor):
    def run_inspection_turn(self, *args, **kwargs):
        response = super().run_inspection_turn(*args, **kwargs)
        payload = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])
        assignment, context = payload["assignment"], payload["context"]
        if (assignment.get("producer") != "why2" or assignment["step"] != "author"
                or "using arrow keys." in context["baseline"]["spec.md"]):
            return response
        reply = json.loads(response.stdout)
        reply["routing"]["verdict"] = "STOP_AND_ASK"
        updates = reply["routing"]["state_updates"]
        updates.update(status="blocked", blocked_reason="human_clarification_required",
            escalation_question="Which controls?", autonomous_default_candidate=dict(
                issue_id="ISS-000001", authority_capability="banzai_default", question="Which controls?",
                affected_requirements=["FR-000001"], alternatives=["Use arrow keys", "Use WASD"],
                constraints=["Use one keyboard scheme"], source_references=["spec.md#FR-000001", "spec.md#AC-000001"]))
        updates["finding_routes"]["findings"][0]["route"] = "autonomous_default_candidate"
        return replace(response, stdout=json.dumps(reply))


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_banzai_default_choice_requires_what_and_new_understanding(checkpoint_case, provider):
    from harness.phase1_quality import has_current_phase1_quality_certificate
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "banzai"
    store.save(state)
    install_why2(checkpoint_case)
    config = root / ".echelon/config.yml"
    value = yaml.safe_load(config.read_text())
    value["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.write_text(yaml.safe_dump(value))
    executor = DefaultChoiceExecutor(provider)
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why2"}
    result = controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True)
    assert result.phase in {"checkpoint-assess", "phase1-lexicon-derive"}, result
    saved, history = store.load(), identity.identity_history(spec_id="game")
    assert has_current_phase1_quality_certificate(saved, project_root=root)
    assert saved["feature_policy_reconciliation"]["requires_repair"] is False
    assert identity.lookup(spec_id="game", element_id="FR-000001")["revision"] == "2"
    assert identity.lookup(spec_id="game", element_id="ISS-000001")["revision"] == "2"
    assert len(saved["managed_what_rounds"]["rounds"]) == 2
    assert len(list((store.squad_dir / "evidence/understanding").glob("*.json"))) == 2
    entry, = saved["autonomous_default_ledger"]
    assert entry["selected_answer"] == "Use arrow keys" and entry["decision_id"] == saved["blocked_decision"]["id"]
    assert len(executor.calls) == 27 and len(executor.decisions) == 1 and saved["token_usage"] == 194
    assert identity.pending_identity_publication(spec_id="game") is None
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == result.phase
    assert store.load() == saved and identity.identity_history(spec_id="game") == history
    assert len(executor.calls) == 27 and len(executor.decisions) == 1
    assert_answer_binding_tamper_rejected(checkpoint_case, {18, 20})


class ClarificationExecutor(Why2Executor):
    question = "Which audience?"
    risk = "low"

    def run_inspection_turn(self, *args, **kwargs):
        response = super().run_inspection_turn(*args, **kwargs)
        payload = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])
        assignment, context = payload["assignment"], payload["context"]
        if assignment.get("producer") != "why2" or assignment["step"] != "author":
            return response
        if any("user-clarifications.md" in path and "**Question:** " + self.question in text
                for path, text in context["evidence"].items()):
            return response
        reply = json.loads(response.stdout)
        reply["artifacts"] = {"issues.md": PASS_ISSUES.replace("**Verdict:** PASS", "**Verdict:** FAIL"),
            "quality-gates.md": "# Quality Gates — WHY2\n\n## Verdict: FAIL\n"}
        reply["routing"]["verdict"] = "STOP_AND_ASK"
        reply["routing"]["state_updates"].update(status="blocked", blocked_reason="human_clarification_required",
            escalation_question=self.question, escalation_recommended_answer="Single player", escalation_risk_level=self.risk)
        return replace(response, stdout=json.dumps(reply))


class ClarificationRepairExecutor(ClarificationExecutor):
    question = "Is deployment required?"

    def run_inspection_turn(self, *args, **kwargs):
        from tests.unit.test_managed_spec_contract import SPEC
        payload = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])
        assignment, context = payload["assignment"], payload["context"]
        if assignment.get("producer") == "what" and assignment["editable_revisions"]:
            response = ScriptedExecutor.run_inspection_turn(self, *args, **kwargs)
            if assignment["step"] == "propose":
                fields = dict(new_subjects=[], revisions=[dict(id=label, expected_revision=revision)
                    for label, revision in assignment["editable_revisions"] if label == "FR-000001"])
            elif assignment["step"] == "author":
                fields = dict(artifacts={"spec.md": SPEC, "requirements-overview.md": context["baseline"]["requirements-overview.md"]}, routing=routing())
            else:
                fields = dict(verdict="accept", reason="Same requirement no longer adds deployment.",
                    assessments=[dict(id=label, verdict="accept", reason="Human answer scopes out deployment.",
                        evidence=[context["citations"][label]]) for label in assignment["assigned_ids"]])
            return replace(response, stdout=json.dumps({**assignment, "action": "final", **fields}))
        response = super().run_inspection_turn(*args, **kwargs)
        if assignment.get("producer") == "what" and assignment["step"] == "author":
            reply = json.loads(response.stdout)
            reply["artifacts"]["spec.md"] = SPEC.replace("across the generated scene.", "across the generated scene after deployment.")
            return replace(response, stdout=json.dumps(reply))
        if assignment.get("producer") == "why2" and assignment["step"] == "author":
            reply = json.loads(response.stdout)
            if reply["routing"]["verdict"] == "STOP_AND_ASK":
                reply["routing"]["state_updates"]["escalation_recommended_answer"] = "No deployment."
                return replace(response, stdout=json.dumps(reply))
        return response


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_why2_clarification_requiring_what_repair_retains_answer_and_reanalyzes(checkpoint_case, provider):
    from harness.phase1_quality import has_current_phase1_quality_certificate
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "guided"
    store.save(state)
    install_why2(checkpoint_case)
    config = root / ".echelon/config.yml"
    value = yaml.safe_load(config.read_text())
    value["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.write_text(yaml.safe_dump(value))
    executor = ClarificationRepairExecutor(provider)
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why2"}
    assert controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True).phase == "phase1-why2"
    before = store.load()
    assert controller(checkpoint_case, executor).resume_with_human_input("No deployment.")
    assert store.load()["phase"] == "phase1-what" and store.load()["feature_policy_reconciliation"]["requires_repair"]
    result = controller(checkpoint_case, executor).run(managed_discovery=selected)
    assert result.phase in {"checkpoint-assess", "phase1-lexicon-derive"}, result
    saved, history = store.load(), identity.identity_history(spec_id="game")
    assert has_current_phase1_quality_certificate(saved, project_root=root)
    assert identity.lookup(spec_id="game", element_id="FR-000001")["revision"] == "2"
    assert saved["understanding_evidence"] != before["understanding_evidence"]
    assert len(executor.calls) == 27 and saved["token_usage"] == 189
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == result.phase
    assert store.load() == saved and identity.identity_history(spec_id="game") == history and len(executor.calls) == 27
    assert_answer_binding_tamper_rejected(checkpoint_case, {18, 20})


@pytest.mark.parametrize("provider,mode,authoring_mode", [("codex", "guided", "proportional"),
    ("claude", "semi", "perfectionist"), ("codex", "banzai", "proportional")])
def test_why2_clarification_releases_answer_and_reassesses(checkpoint_case, monkeypatch, provider, mode, authoring_mode):
    from harness.phase1_quality import has_current_phase1_quality_certificate
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state.update(autonomy_mode=mode, spec_authoring_mode=authoring_mode)
    if authoring_mode == "perfectionist":
        # The shared checkpoint fixture starts proportional. Configure a fresh
        # perfectionist run, not an invalid mid-run policy conversion.
        state.pop("phase1_quality_repair")
    store.save(state)
    install_why2(checkpoint_case)
    config = root / ".echelon/config.yml"
    value = yaml.safe_load(config.read_text())
    value["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.write_text(yaml.safe_dump(value))
    executor = ClarificationExecutor(provider)
    if mode == "banzai":
        executor.risk = "high"
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why2"}
    result = controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True)
    assert result.phase == "phase1-why2" and result.status == "blocked", result
    before, history = store.load(), identity.identity_history(spec_id="game")
    assert before["blocked_decision"]["question"] == "Which audience?"
    assert before["blocked_decision"]["status"] == "awaiting_human"
    if mode == "banzai":
        assert before["blocked_decision"]["automatic_eligible"] is False
        assert executor.decisions == []
    assert len(executor.calls) == 21
    if provider == "codex" and mode == "guided":
        interrupt_answer_publication(checkpoint_case, executor, monkeypatch, "Single player")
    else:
        assert controller(checkpoint_case, executor).resume_with_human_input("Single player")
    assert identity.identity_history(spec_id="game") == history and len(executor.calls) == 21
    assert identity.pending_identity_publication(spec_id="game") is None
    result = controller(checkpoint_case, executor).run(managed_discovery=selected)
    assert result.phase in {"checkpoint-assess", "phase1-lexicon-derive"}, result
    saved = store.load()
    assert has_current_phase1_quality_certificate(saved, project_root=root)
    assert len(executor.calls) == 24 and saved["token_usage"] == 168
    original = before["managed_why2_rounds"]["active"]
    assert saved["managed_why2_rounds"]["rounds"][original] == before["managed_why2_rounds"]["rounds"][original]
    assert len(saved["managed_why2_rounds"]["rounds"]) == 2
    if authoring_mode == "perfectionist":
        assert saved.get("phase1_quality_repair") is None
        assert saved.get("proportional_quality_candidate_evidence") is None
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == result.phase
    assert store.load() == saved and len(executor.calls) == 24
    assert_answer_binding_tamper_rejected(checkpoint_case, {18, 19})


def interrupt_answer_publication(case, executor, monkeypatch, answer=None, *, option=None, quality=False, already_seen=()):
    """Crash each native resolution boundary without repeating provider work."""
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    from harness.element_identity_store import IdentityStore
    from harness.squad_completion import CompletionError
    from tests.unit.test_discovery_turns import Interrupted
    root, store, identity, _ = case
    history, calls = identity.identity_history(spec_id="game"), len(executor.calls)
    selected = {**selection(case), "through_phase": "phase1-why2"}
    points = ("staged", "resolved", "promoted", *(("quality",) if quality else ()), "context", "completed", "released")
    assert tuple(already_seen) == points[:len(already_seen)]
    for point in points[len(already_seen):]:
        ctrl = controller(case, executor)
        target, method = {
            "staged": (ctrl, "_prepare_spec_step_effects"),
            "resolved": (store, "apply_human_input_state_resolution"),
            "promoted": (IdentityStore, "apply_identity_publication"),
            "quality": (ctrl, "_apply_controller_completion_effect"),
            "context": (ctrl, "_apply_controller_completion_effect"),
            "completed": (store, "complete_controller_completion"),
            "released": (IdentityStore, "release_identity_publication"),
        }[point]
        original = getattr(target, method)
        def interrupt(*args, **kwargs):
            value = original(*args, **kwargs)
            if point not in {"quality", "context"} or args[0].marker.step == point:
                if point == "quality":
                    raise CompletionError("stage_io")
                raise Interrupted()
            return value
        with monkeypatch.context() as patch:
            patch.setattr(target, method, interrupt)
            def resume():
                current = store.load()
                if current["blocked_decision"]["status"] != "resolved":
                    with PhaseAExecutionLock.acquire(root, "test-resolution-fault"):
                        with SpecRunExecutionLock.acquire(store.squad_dir, "test-resolution-fault"):
                            return ctrl.resume_with_human_input(option if option is not None else answer)
                else:
                    return ctrl.run(managed_discovery=selected)
            if point == "quality":
                # Exercise the native recorded failure overlay after handoff,
                # not merely an exception that leaves the lifecycle unchanged.
                resume()
                failed = store.load()
                assert failed["spec_step_effect_failure"]["code"] == "stage_io"
                assert failed["_spec_step_effect_plan"]["step"] == "quality"
                assert "_spec_step_publication_plan" not in failed
            else:
                with pytest.raises(Interrupted):
                    resume()
        assert identity.identity_history(spec_id="game") == history and len(executor.calls) == calls
    if store.load()["blocked_decision"]["resolution_handler"] == "clarification_resume":
        assert (store.staging_dir / "user-clarifications.md").read_text().count("## Decision ") == 1
    else:
        assert not (store.staging_dir / "user-clarifications.md").exists()


def assert_answer_binding_tamper_rejected(case, expected_versions):
    """Tamper detached copies of actual retained answer/consumer envelopes."""
    from copy import deepcopy
    from harness.discovery_completion import decode_binding
    from harness.element_identity_publication import encode_publication_request
    from harness.squad_completion import CompletionError
    root, store, identity, _ = case
    state, history = store.load(), identity.identity_history(spec_id="game")
    completion_id = state["last_dispatch"]["dispatch_id"]
    seen, tested = set(), set()
    while completion_id not in seen:
        seen.add(completion_id)
        row = identity.identity_publication(spec_id="game", operation_id="discovery-completion-" + completion_id)
        retained = json.loads(row["completion_payload"])
        publication = retained["proof"]["intent"]["publication"]
        binding = decode_binding(publication, completion_id=completion_id, state=state)
        version = binding.recovery["version"]
        if version in {18, 19, 20}:
            tested.add(version)
            for damage in ("version", "source", "answer", "association"):
                recovery = deepcopy(binding.recovery)
                if damage == "version": recovery["version"] = True
                elif damage == "source": recovery["source_completion"]["dispatch_id"] = "0" * 32
                elif damage == "answer":
                    association = recovery["review_resolution"] if version == 20 else recovery["resolution"]
                    (association if version == 18 else association["decision"])["answer_text"] = "Substituted answer"
                elif version == 18:
                    recovery["previous"].append(dict(decision_id="unproven", question="Injected?", answer="Injected"))
                elif version == 19: recovery["predecessor"] = "why2-" + "0" * 32
                else: recovery["review_parent"] = "why2-" + "0" * 32
                changed = deepcopy(publication)
                changed["managed_discovery"]["request"] = encode_publication_request(replace(binding.request,
                    recovery_payload=json.dumps(recovery, sort_keys=True, separators=(",", ":"))))
                with pytest.raises(CompletionError):
                    decode_binding(changed, completion_id=completion_id, state=state)
        source = binding.recovery.get("source_completion")
        if source is None:
            break
        completion_id = source["dispatch_id"]
    assert tested == expected_versions
    assert store.load() == state and identity.identity_history(spec_id="game") == history


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_why2_banzai_low_risk_answer_uses_existing_automatic_policy(checkpoint_case, provider):
    from harness.phase1_quality import has_current_phase1_quality_certificate
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "banzai"
    store.save(state)
    install_why2(checkpoint_case)
    config = root / ".echelon/config.yml"
    value = yaml.safe_load(config.read_text())
    value["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.write_text(yaml.safe_dump(value))
    executor = ClarificationExecutor(provider)
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why2"}
    result = controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True)
    assert result.phase in {"checkpoint-assess", "phase1-lexicon-derive"}, result
    saved, history = store.load(), identity.identity_history(spec_id="game")
    assert saved["blocked_decision"]["status"] == "resolved"
    assert saved["blocked_decision"]["answer_text"] == "Single player"
    assert saved["blocked_decision"]["automatic_eligible"] is True
    assert len(executor.decisions) == 1 and len(executor.calls) == 24 and saved["token_usage"] == 173
    assert has_current_phase1_quality_certificate(saved, project_root=root)
    assert identity.pending_identity_publication(spec_id="game") is None
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == result.phase
    assert store.load() == saved and identity.identity_history(spec_id="game") == history
    assert len(executor.decisions) == 1 and len(executor.calls) == 24


class DiscoveryFindingExecutor(Why2Executor):
    def run_inspection_turn(self, *args, **kwargs):
        from tests.unit.test_why1_repair_admission import REPORT
        payload = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])
        assignment, context = payload["assignment"], payload["context"]
        if assignment.get("producer") != "why2":
            return super().run_inspection_turn(*args, **kwargs)
        response = ScriptedExecutor.run_inspection_turn(self, *args, **kwargs)
        if assignment["step"] == "propose":
            fields = dict(new_subjects=[dict(key="camera", kind="ISS", subject="Audience", caption="Audience")], revisions=[])
        elif assignment["step"] == "author":
            claim = routing("why2")
            claim["verdict"] = "FAIL"
            claim["state_updates"]["finding_routes"]["findings"] = [dict(issue_id="ISS-000001",
                route="spec_repair", rationale="Repair the existing Discovery-owned camera question.")]
            fields = dict(artifacts={"issues.md": REPORT.replace("WHY1", "WHY2"),
                "quality-gates.md": "# Quality Gates — WHY2\n\n## Verdict: FAIL\n"}, routing=claim)
        else:
            fields = dict(verdict="accept", reason="Finding is bound to the existing camera question.",
                assessments=[dict(id=label, verdict="accept", reason="Discovery must repair the captured question.",
                    evidence=[context["citations"][label]]) for label in assignment["assigned_ids"]])
        return replace(response, stdout=json.dumps({**assignment, "action": "final", **fields}))


class DiscoveryRepairExecutor(DiscoveryFindingExecutor):
    def run_inspection_turn(self, *args, **kwargs):
        payload = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])
        assignment, context = payload["assignment"], payload["context"]
        if not assignment["operation_id"].startswith("discovery-repair-"):
            response = super().run_inspection_turn(*args, **kwargs)
            reply = json.loads(response.stdout)
            if assignment["operation_id"].startswith("synthesizer-") and assignment["step"] == "propose":
                reply["revisions"] = [dict(id=label, expected_revision=revision)
                    for label, revision in assignment["editable_revisions"]]
            if assignment.get("producer") == "why1" and assignment["step"] == "author" and "issues.md" in context["baseline"]:
                # WHY1 rechecks assumptions; the requesting WHY2 retains its
                # findings until the refreshed specification reaches that review.
                reply["artifacts"]["issues.md"] = context["baseline"]["issues.md"]
            if assignment.get("producer") == "what" and assignment["editable_revisions"]:
                if assignment["step"] == "propose":
                    reply.update(new_subjects=[], revisions=[])
                elif assignment["step"] == "author":
                    reply["artifacts"] = {name: context["baseline"][name] for name in assignment["artifact_paths"]}
            if assignment.get("producer") == "why2" and "Camera research remains unresolved" in context["baseline"]["unknowns.md"]:
                if assignment["step"] == "propose":
                    reply.update(new_subjects=[], revisions=[dict(id=label, expected_revision=revision)
                        for label, revision in assignment["editable_revisions"]])
                elif assignment["step"] == "author":
                    report = context["baseline"]["issues.md"].replace("**HIGH:** 1", "**HIGH:** 0").replace(
                        "**LOW:** 0", "**LOW:** 1").replace("**Severity:** HIGH", "**Severity:** LOW").replace(
                        "**Verdict:** FAIL", "**Verdict:** PASS").replace("Camera evidence is incomplete.",
                        "Resolved: the camera research gap and prototype evidence step are explicitly recorded.").replace(
                        "**Action Required:** Investigate the camera question.", "**Action Required:** None — advisory: tracked prototype evidence.")
                    reply.update(artifacts={"issues.md": report, "quality-gates.md": "# Quality Gates — WHY2\n\n## Verdict: PASS\n"},
                        routing=routing("why2"))
            return replace(response, stdout=json.dumps(reply))
        response = ScriptedExecutor.run_inspection_turn(self, *args, **kwargs)
        if assignment["step"] == "propose":
            fields = dict(new_subjects=[], revisions=[dict(id=label, expected_revision=revision)
                for label, revision in assignment["editable_revisions"]])
        elif assignment["step"] == "author":
            fields = dict(artifacts={"unknowns.md": context["baseline"]["unknowns.md"] +
                "Camera research remains unresolved; verify the isometric view with a scene prototype.\n"})
        else:
            fields = dict(verdict="accept", reason="The same camera question now identifies the missing evidence.",
                assessments=[dict(id=label, verdict="accept", reason="Same subject; research gap is explicit.",
                    evidence=[context["citations"][label]]) for label in assignment["assigned_ids"]])
        return replace(response, stdout=json.dumps({**assignment, "action": "final", **fields}))


class CrossPhaseAnswerExecutor(DiscoveryRepairExecutor):
    """Questions at WHY2, then refreshed Tracker and WHY1 share one history."""
    def run_inspection_turn(self, *args, **kwargs):
        payload = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])
        assignment, context = payload["assignment"], payload["context"]
        receipts = "\n".join(text for path, text in context["evidence"].items() if "user-clarifications.md" in path)
        producer = assignment.get("producer")
        question = {"why2": "Which audience?", "tracker": "Which visual style?", "why1": "Which session length?"}.get(producer)
        initial_question = producer == "why2" and "**Question:** Which audience?" not in receipts
        # Do not allocate an issue until the later, actual Discovery finding.
        response = (Why2Executor.run_inspection_turn(self, *args, **kwargs) if initial_question else
            super().run_inspection_turn(*args, **kwargs))
        if assignment["step"] != "author" or question is None or "**Question:** " + question in receipts:
            return response
        if not initial_question and "Camera research remains unresolved" not in context["baseline"]["unknowns.md"]:
            return response
        reply = json.loads(response.stdout)
        if producer == "why2":
            reply["artifacts"] = {"issues.md": PASS_ISSUES.replace("**Verdict:** PASS", "**Verdict:** FAIL"),
                "quality-gates.md": "# Quality Gates — WHY2\n\n## Verdict: FAIL\n"}
            reply["routing"]["verdict"] = "STOP_AND_ASK"
            reply["routing"]["state_updates"].update(status="blocked", blocked_reason="human_clarification_required",
                escalation_question=question, escalation_recommended_answer="Single player", escalation_risk_level="low")
        else:
            reply["routing"] = dict(verdict="STOP_AND_ASK", question=question, recommended_answer="Simple prototype", risk_level="low")
            if producer == "why1":
                reply["artifacts"]["assumption-review.md"] = reply["artifacts"]["assumption-review.md"].replace("Verdict: PASS", "Verdict: FAIL")
        return replace(response, stdout=json.dumps(reply))


class BanzaiDiscoveryIssueExecutor(DiscoveryRepairExecutor):
    def run_inspection_turn(self, *args, **kwargs):
        response = super().run_inspection_turn(*args, **kwargs)
        payload = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])
        if payload["assignment"].get("producer") == "why2" and payload["assignment"]["step"] == "author":
            reply = json.loads(response.stdout)
            if reply["routing"]["verdict"] == "FAIL":
                reply["artifacts"]["issues.md"] += ("\n### Resolution Guidance\n"
                    "- **Decision required:** Record the existing camera evidence gap.\n"
                    "- **Suggested option:** Keep U-000001 and record the missing prototype evidence.\n"
                    "- **Evidence basis:** U-000001 already owns the camera research question.\n"
                    "- **Values not inferable:** None\n"
                    "- **Banzai eligible:** yes\n")
                return replace(response, stdout=json.dumps(reply))
        return response


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_banzai_native_discovery_owner_route_refreshes_dependencies(checkpoint_case, provider):
    from harness.phase1_quality import has_current_phase1_quality_certificate
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "banzai"
    store.save(state)
    install_why2(checkpoint_case)
    config = root / ".echelon/config.yml"
    value = yaml.safe_load(config.read_text())
    value["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.write_text(yaml.safe_dump(value))
    executor = BanzaiDiscoveryIssueExecutor(provider)
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why2"}
    result = controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True)
    assert result.phase in {"checkpoint-assess", "phase1-lexicon-derive"}, result
    saved, history = store.load(), identity.identity_history(spec_id="game")
    # Discovery owner routing precedes proportional issue-choice policy, even
    # for an explicitly eligible issue. Do not invent a decision to reach it.
    assert not saved.get("blocked_decision")
    assert not saved.get("selected_issue_resolution")
    assert saved["phase1_quality_repair"]["automatic_consumed"] == 0
    assert has_current_phase1_quality_certificate(saved, project_root=root)
    assert not (store.staging_dir / "user-clarifications.md").exists()
    assert len(executor.calls) == 42 and saved["token_usage"] == 294
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == result.phase
    assert store.load() == saved and identity.identity_history(spec_id="game") == history and len(executor.calls) == 42


def test_answers_survive_why2_discovery_refresh_and_later_tracker_why1(checkpoint_case):
    from harness.phase1_quality import has_current_phase1_quality_certificate
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    from harness.tracker_clarification import retained_clarification_records
    from harness.discovery_producer import SOURCE_FIELDS
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "guided"
    store.save(state)
    install_why2(checkpoint_case)
    config = root / ".echelon/config.yml"
    value = yaml.safe_load(config.read_text())
    value["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.write_text(yaml.safe_dump(value))
    executor = CrossPhaseAnswerExecutor()
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why2"}
    answers = [("why2", "Which audience?", "Single player"),
        ("tracker", "Which visual style?", "Simple prototype"), ("why1", "Which session length?", "Short sessions")]
    decisions = []
    for index, (producer, question, answer) in enumerate(answers):
        result = controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=index == 0)
        assert result.phase == "phase1-" + producer, result
        before, history, calls = store.load(), identity.identity_history(spec_id="game"), len(executor.calls)
        decision = before["blocked_decision"]
        assert decision["question"] == question and decision["status"] == "awaiting_human"
        decisions.append(decision["id"])
        assert controller(checkpoint_case, executor).resume_with_human_input(answer)
        assert identity.identity_history(spec_id="game") == history and len(executor.calls) == calls
        saved = store.load()
        receipt = saved["last_human_input_completion"]
        retained = identity.identity_publication(spec_id="game", operation_id="discovery-completion-" + receipt["completion_id"])
        from harness.element_identity_publication import decode_publication_request
        recovery = json.loads(decode_publication_request(retained["request"]).recovery_payload)
        assert recovery["version"] == 18 and recovery["producer"] == producer
        assert [record["decision_id"] for record in recovery["previous"]] == decisions[:-1]
        assert identity.pending_identity_publication(spec_id="game") is None
    result = controller(checkpoint_case, executor).run(managed_discovery=selected)
    assert result.phase in {"checkpoint-assess", "phase1-lexicon-derive"}, result
    saved, history = store.load(), identity.identity_history(spec_id="game")
    assert has_current_phase1_quality_certificate(saved, project_root=root)
    assert len(executor.calls) == 51 and saved["token_usage"] == 357
    records = retained_clarification_records(identity, spec_id="game",
        source={key: saved["last_dispatch"][key] for key in SOURCE_FIELDS})
    assert [record.decision_id for record in records] == decisions
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == result.phase
    assert store.load() == saved and identity.identity_history(spec_id="game") == history and len(executor.calls) == 51


def test_why2_discovery_repair_admission_preserves_requesting_review(checkpoint_case):
    from types import MethodType
    from tests.unit.test_why1_repair_admission import select_only
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    root, store, identity, _ = checkpoint_case
    install_why2(checkpoint_case)
    config = root / ".echelon/config.yml"
    value = yaml.safe_load(config.read_text())
    value["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.write_text(yaml.safe_dump(value))
    executor = DiscoveryRepairExecutor()
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why2"}
    ctrl = controller(checkpoint_case, executor)
    run = ctrl._run_managed_discovery_locked
    def stop_at_request(self, admitted):
        state = store.load()
        if state["phase"] == "phase1-discover" and (state.get("last_dispatch") or {}).get("phase_id") == "phase1-why2":
            return self._managed_discovery_stop("test_discovery_requested")
        return run(admitted)
    ctrl._run_managed_discovery_locked = MethodType(stop_at_request, ctrl)
    result = ctrl.run(managed_discovery=selected, create_managed_discovery=True)
    assert result.phase == "phase1-discover", result
    assert_why2_repair_selection(checkpoint_case, executor)
    assert_why2_repair_execution(checkpoint_case, executor)
    assert_why2_refresh_selection(checkpoint_case, executor)
    assert_why2_refresh_activation(checkpoint_case, executor)
    assert_why2_upstream_refresh(checkpoint_case, executor)
    assert_why2_constitution_refresh(checkpoint_case, executor)
    assert_why2_refreshed_specification(checkpoint_case, executor)


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_why2_discovery_repair_automatically_refreshes_and_certifies(checkpoint_case, provider):
    from harness.phase1_quality import has_current_phase1_quality_certificate
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    root, store, identity, _ = checkpoint_case
    install_why2(checkpoint_case)
    config = root / ".echelon/config.yml"
    value = yaml.safe_load(config.read_text())
    value["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.write_text(yaml.safe_dump(value))
    executor = DiscoveryRepairExecutor(provider)
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why2"}
    result = controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True)
    assert result.phase in {"checkpoint-assess", "phase1-lexicon-derive"}, result
    saved, history = store.load(), identity.identity_history(spec_id="game")
    assert has_current_phase1_quality_certificate(saved, project_root=root)
    assert len(executor.calls) == 42 and saved["token_usage"] == 294
    # Discovery repairs revision 2 -> 3; refreshed Synthesis then accepts its
    # own same-ID revision 4. Neither revision is a reallocation or rewind.
    assert identity.lookup(spec_id="game", element_id="U-000001")["revision"] == "4"
    assert identity.lookup(spec_id="game", element_id="FR-000001")["revision"] == "1"
    assert identity.lookup(spec_id="game", element_id="ISS-000001")["revision"] == "2"
    assert len(json.loads(history.payload)["issue_occurrences"]) == 2
    assert saved["phase1_quality_repair"]["automatic_consumed"] == 0
    assert len(saved["phase1_quality_repair"]["candidate_ids"]) == 1
    for producer in ("what", "why2"):
        assert len(saved["managed_" + producer + "_rounds"]["rounds"]) == 2
    assert len(saved["managed_constitution_rounds"]["rounds"]) == 1
    assert identity.pending_identity_publication(spec_id="game") is None
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == result.phase
    assert store.load() == saved and identity.identity_history(spec_id="game") == history and len(executor.calls) == 42


def assert_why2_repair_execution(case, executor):
    """Stop only after real repair release, before dependency refresh is selected."""
    from types import MethodType
    from harness.discovery_completion import released_discovery_input_projectors
    from harness.discovery_producer import SOURCE_FIELDS
    root, store, identity, _ = case
    original = store.load()
    history = json.loads(identity.identity_history(spec_id="game").payload)
    spec = (root / "specs/game/spec.md").read_bytes()
    calls = len(executor.calls)
    ctrl = controller(case, executor)
    run = ctrl._run_managed_discovery_locked
    def stop_after_repair(self, selected):
        state = store.load()
        if state["phase"] == "phase1-why2" and state["last_dispatch"]["phase_id"] == "phase1-discover":
            return self._managed_discovery_stop("test_repair_released")
        return run(selected)
    ctrl._run_managed_discovery_locked = MethodType(stop_after_repair, ctrl)
    selected = {**selection(case), "through_phase": "phase1-why2"}
    result = ctrl.run(managed_discovery=selected)
    assert result.summary == "test_repair_released", result
    saved = store.load()
    assert len(executor.calls) == calls + 3 and saved["token_usage"] == original["token_usage"] + 21
    assert identity.lookup(spec_id="game", element_id="U-000001")["revision"] == "3"
    assert identity.lookup(spec_id="game", element_id="FR-000001")["revision"] == "1"
    assert (root / "specs/game/spec.md").read_bytes() == spec
    current = json.loads(identity.identity_history(spec_id="game").payload)
    assert current["issue_occurrences"] == history["issue_occurrences"]
    assert all(row in current["revisions"] for row in history["revisions"])
    for key in ("managed_discovery_operation", "managed_discovery_turns", "managed_why1_rounds", "managed_why2_rounds",
            "managed_what_rounds", "managed_constitution_source", "phase1_quality_repair"):
        assert saved.get(key) == original.get(key)
    assert identity.pending_identity_publication(spec_id="game") is None
    released_discovery_input_projectors(root, store.squad_dir, saved,
        source={key: saved["last_dispatch"][key] for key in SOURCE_FIELDS})
    assert ctrl.run(managed_discovery=selected).summary == result.summary
    assert store.load() == saved and len(executor.calls) == calls + 3


def assert_why2_refresh_selection(case, executor):
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    from harness.discovery_repair_admission import pin_why1_tracker_history, prepare_repair_refresh_round
    from harness.discovery_producer import tracker_round
    root, store, identity, _ = case
    before, history, calls = store.load(), identity.identity_history(spec_id="game"), len(executor.calls)
    with PhaseAExecutionLock.acquire(root, "test-why2-refresh"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-why2-refresh"):
            pin_why1_tracker_history(root, store)
            for producer in ("synthesizer", "tracker", "why1"):
                saved = prepare_repair_refresh_round(root, store, producer)
                current = tracker_round(saved, producer=producer)
                assert current["operation"] is current["turns"] is None
                assert current["source"]["dispatch_id"] == before["last_dispatch"]["dispatch_id"]
                claim = saved["managed_discovery_repairs"]["units"][current["refresh"]["repair_unit"]]["selection"]
                assert claim["origin"]["return_phase"] == "phase1-why2"
                assert current["refresh"]["predecessor_source"] != claim["source"]
                assert prepare_repair_refresh_round(root, store, producer) == saved
    for key in ("phase", "token_usage", "phase_dispatch_counts", "last_dispatch", "managed_why2_rounds", "phase1_quality_repair"):
        assert saved.get(key) == before.get(key)
    for producer in ("tracker", "why1"):
        assert all(saved["managed_" + producer + "_rounds"]["rounds"][key] == row
            for key, row in before["managed_" + producer + "_rounds"]["rounds"].items())
    assert identity.identity_history(spec_id="game") == history and len(executor.calls) == calls


def assert_why2_refresh_activation(case, executor):
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    from harness.discovery_repair_admission import bind_repair_refresh_input
    from harness.discovery_producer import tracker_round
    root, store, identity, _ = case
    before, history, calls = store.load(), identity.identity_history(spec_id="game"), len(executor.calls)
    with PhaseAExecutionLock.acquire(root, "test-why2-refresh-input"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-why2-refresh-input"):
            bound = bind_repair_refresh_input(root, store, "synthesizer")
            row = tracker_round(bound, producer="synthesizer")
            assert row["execution_input"]["source"] == row["refresh"]["repair_source"]
            assert row["execution_input"]["dependencies"]["changed"]
            assert bind_repair_refresh_input(root, store, "synthesizer") == bound
            saved = store.activate_refresh_round("synthesizer", expected_state=bound)
    assert saved["phase"] == "phase1-synthesizer"
    for key in ("token_usage", "phase_dispatch_counts", "last_dispatch", "managed_why2_rounds", "phase1_quality_repair"):
        assert saved.get(key) == before.get(key)
    assert row["operation"] is row["turns"] is None
    assert identity.identity_history(spec_id="game") == history and len(executor.calls) == calls


def assert_why2_upstream_refresh(case, executor):
    root, store, identity, _ = case
    before, calls = store.load(), len(executor.calls)
    result = controller(case, executor).run(managed_discovery={**selection(case), "through_phase": "phase1-why1"})
    assert result.phase == "phase1-constitution", result
    saved = store.load()
    assert len(executor.calls) == calls + 9 and saved["token_usage"] == before["token_usage"] + 63
    for producer in ("tracker", "why1"):
        for key, row in before["managed_" + producer + "_rounds"]["rounds"].items():
            if key != before["managed_" + producer + "_rounds"]["active"]:
                assert saved["managed_" + producer + "_rounds"]["rounds"][key] == row
    assert saved["managed_why2_rounds"] == before["managed_why2_rounds"]
    assert identity.pending_identity_publication(spec_id="game") is None


def assert_why2_constitution_refresh(case, executor):
    from harness.discovery_completion import released_discovery_input_projectors, _retained_input_projection, _released_discovery_projections
    from harness.discovery_producer import SOURCE_FIELDS, tracker_round
    from harness.squad_completion import CompletionError
    root, store, identity, _ = case
    before, history, calls = store.load(), identity.identity_history(spec_id="game"), len(executor.calls)
    policy = (root / ".echelon/constitution.md").read_bytes()
    original_receipts = {path: path.read_bytes() for path in store.squad_dir.glob("constitution-*.json")}
    result = controller(case, executor).run(managed_discovery={**selection(case), "through_phase": "phase1-constitution"})
    assert result.phase == "phase1-what", result
    saved = store.load()
    assert len(executor.calls) == calls + 3 and saved["token_usage"] == before["token_usage"] + 21
    assert (root / ".echelon/constitution.md").read_bytes() == policy
    assert identity.identity_history(spec_id="game") == history
    for key in ("managed_constitution_source", "managed_constitution_operation", "managed_constitution_turns"):
        assert saved.get(key) == before.get(key)
    assert all(path.read_bytes() == raw for path, raw in original_receipts.items())
    assert tracker_round(saved, producer="constitution")["operation"] is not None
    released_discovery_input_projectors(root, store.squad_dir, saved,
        source={key: saved["last_dispatch"][key] for key in SOURCE_FIELDS})
    assert identity.pending_identity_publication(spec_id="game") is None
    source = {key: saved["last_dispatch"][key] for key in SOURCE_FIELDS}
    binding, _, _ = _retained_input_projection(root, store.squad_dir, saved, identity,
        operation_id="discovery-completion-" + source["dispatch_id"], source=source, require_checkpoint=False)
    assert binding.recovery["version"] == 16
    assert binding.recovery["predecessor"] == before["managed_constitution_operation"]["binding"]["operation_id"]
    wrong = replace(binding, recovery={**binding.recovery, "predecessor": "constitution-" + "0" * 32})
    with pytest.raises(CompletionError):
        _released_discovery_projections(root, store.squad_dir, saved, source=binding.recovery["source_completion"],
            historical=True, constitution_child=wrong)
    assert controller(case, executor).run(managed_discovery={**selection(case), "through_phase": "phase1-constitution"}).phase == result.phase
    assert store.load() == saved and identity.identity_history(spec_id="game") == history and len(executor.calls) == calls + 3


def assert_why2_refreshed_specification(case, executor):
    from harness.phase1_quality import has_current_phase1_quality_certificate
    from copy import deepcopy
    import harness.discovery_publication as publication
    from harness.discovery_completion import decode_binding, _released_discovery_projections
    from harness.element_identity_publication import encode_publication_request
    from harness.squad_completion import CompletionError
    root, store, identity, _ = case
    before, calls = store.load(), len(executor.calls)
    prepare, checked = publication.prepare_discovery_publication, []
    def verify(*args, **kwargs):
        package = prepare(*args, **kwargs)
        if kwargs.get("producer") != "what":
            return package
        state = store.load()
        envelope = dict(kind="external", marker=package.publication.marker.to_dict(),
            managed_discovery=dict(version=1, request=encode_publication_request(package.request)))
        binding = decode_binding(envelope, state=state)
        assert binding.recovery["version"] == 17
        assert binding.recovery["constitution_parent"] == before["managed_constitution_rounds"]["active"]
        for damage in ("downgrade", "parent", "predecessor"):
            recovery = deepcopy(binding.recovery)
            if damage == "downgrade":
                recovery["version"] = 13
                del recovery["constitution_parent"]
            elif damage == "parent":
                recovery["constitution_parent"] = "constitution-refresh-" + "0" * 32
            else:
                recovery["predecessor"] = "what-" + "0" * 32
            forged = replace(package.request, recovery_payload=json.dumps(recovery, sort_keys=True, separators=(",", ":")))
            with pytest.raises(CompletionError):
                decode_binding({**envelope, "managed_discovery": dict(version=1, request=encode_publication_request(forged))}, state=state)
        wrong = replace(binding, recovery={**binding.recovery, "constitution_parent": "constitution-refresh-" + "0" * 32})
        with pytest.raises(CompletionError):
            _released_discovery_projections(root, store.squad_dir, state, source=binding.recovery["source_completion"],
                historical=True, spec_child=wrong)
        checked.append(binding.recovery)
        return package
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(publication, "prepare_discovery_publication", verify)
        result = controller(case, executor).run(managed_discovery={**selection(case), "through_phase": "phase1-why2"})
    assert result.phase in {"checkpoint-assess", "phase1-lexicon-derive"}, result
    saved = store.load()
    assert has_current_phase1_quality_certificate(saved, project_root=root)
    assert len(checked) == 1
    assert len(executor.calls) == calls + 6 and saved["token_usage"] == before["token_usage"] + 42
    assert identity.lookup(spec_id="game", element_id="FR-000001")["revision"] == "1"
    assert identity.lookup(spec_id="game", element_id="ISS-000001")["revision"] == "2"
    history = identity.identity_history(spec_id="game")
    assert len(json.loads(history.payload)["issue_occurrences"]) == 2
    assert saved["phase1_quality_repair"]["automatic_consumed"] == 0
    assert len(saved["phase1_quality_repair"]["candidate_ids"]) == 1
    for producer in ("what", "why2"):
        assert all(saved["managed_" + producer + "_rounds"]["rounds"][key] == row
            for key, row in before["managed_" + producer + "_rounds"]["rounds"].items())
    assert controller(case, executor).run(managed_discovery={**selection(case), "through_phase": "phase1-why2"}).phase == result.phase
    assert store.load() == saved and identity.identity_history(spec_id="game") == history and len(executor.calls) == calls + 6


def assert_why2_repair_selection(checkpoint_case, executor):
    from tests.unit.test_why1_repair_admission import select_only
    root, store, identity, _ = checkpoint_case
    before, history, calls = store.load(), identity.identity_history(spec_id="game"), len(executor.calls)
    after = select_only(checkpoint_case)
    record, = after["managed_discovery_repairs"]["units"].values()
    assert record["selection"]["origin"] == dict(review_id=before["last_dispatch"]["dispatch_id"], return_phase="phase1-why2")
    assert record["selection"]["artifact_paths"] == ["unknowns.md"]
    assert record["selection"]["editable_revisions"] == [["U-000001", "2"]]
    assert after.get("phase1_quality_repair") == before.get("phase1_quality_repair")
    assert identity.identity_history(spec_id="game") == history and len(executor.calls) == calls
    assert select_only(checkpoint_case) == after
    from harness.squad_completion import CompletionError
    for path in (root / "specs/game/spec.md", root / "specs/game/issues.md",
            root / "specs/game/spec-artifact-graph.json", root / "specs/game/.echelon/checkpoints.json",
            root / ".echelon/config.yml", store.squad_dir / "context/current-feature-context.md"):
        original = path.read_bytes()
        try:
            path.write_bytes(original + b"\nChanged after review\n")
            with pytest.raises((ValueError, CompletionError)):
                select_only(checkpoint_case)
            assert store.load() == after and identity.identity_history(spec_id="game") == history
            assert len(executor.calls) == calls
        finally:
            path.write_bytes(original)
    assert_review_runtime_drift_rejected(checkpoint_case)


def assert_review_runtime_drift_rejected(case):
    from tests.unit.test_why1_repair_admission import select_only
    from harness.squad_completion import CompletionError
    _, store, identity, _ = case
    history = identity.identity_history(spec_id="game")
    for key, value in (("calibration_map", {"different": "input"}), ("stack_contract", {"changed": True}),
            ("autonomy_mode", "guided")):
        original = store.load()
        if original.get(key) == value:
            value = "banzai"
        try:
            store.save({**original, key: value})
            changed = store.load()
            with pytest.raises((ValueError, CompletionError)):
                select_only(case)
            assert store.load() == changed and identity.identity_history(spec_id="game") == history
        finally:
            restored = store.load()
            if key in original:
                restored[key] = original[key]
            else:
                restored.pop(key, None)
            store.save(restored)


class UnresolvedRepairExecutor(RepairExecutor):
    """Three genuine changed revisions; qualitative review keeps requiring repair."""
    def __init__(self, provider="codex", *, add_lighting=True):
        super().__init__(provider)
        self.add_lighting = add_lighting

    def run_inspection_turn(self, *args, **kwargs):
        payload = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])
        assignment, context = payload["assignment"], payload["context"]
        producer = assignment.get("producer")
        if producer == "what" and assignment["editable_revisions"]:
            response = ScriptedExecutor.run_inspection_turn(self, *args, **kwargs)
            baseline = context["baseline"]["spec.md"]
            new_light = self.add_lighting and "FR-000002" not in baseline
            if assignment["step"] == "propose":
                fields = dict(new_subjects=[dict(key="lighting", kind="FR", subject="Lighting", caption="Lighting")] if new_light else [],
                    revisions=[dict(id=label, expected_revision=revision) for label, revision in assignment["editable_revisions"]
                        if label == "FR-000001"])
            elif assignment["step"] == "author":
                amended = unresolved_spec(baseline, add_lighting=self.add_lighting)
                fields = dict(artifacts={"spec.md": amended,
                    "requirements-overview.md": context["baseline"]["requirements-overview.md"]}, routing=routing())
            else:
                fields = dict(verdict="accept", reason="Review the proposed revision without certifying quality.",
                    assessments=[dict(id=label, verdict="accept", reason="The assigned identity is retained.",
                        evidence=[context["citations"][label]]) for label in assignment["assigned_ids"]])
        elif producer == "why2":
            response = ScriptedExecutor.run_inspection_turn(self, *args, **kwargs)
            existing = bool(assignment["editable_revisions"])
            if assignment["step"] == "propose":
                fields = dict(new_subjects=[] if existing else [dict(key="controls", kind="ISS", subject="Movement controls", caption="Movement controls")],
                    revisions=[dict(id=label, expected_revision=revision) for label, revision in assignment["editable_revisions"]])
            elif assignment["step"] == "author":
                claim = routing("why2")
                claim["verdict"] = "FAIL"
                claim["state_updates"]["finding_routes"]["findings"] = [dict(issue_id="ISS-000001", route="spec_repair",
                    rationale="The movement requirement still omits the existing arrow-key criterion.")]
                fields = dict(artifacts={"issues.md": unresolved_issues(context["baseline"]["spec.md"]),
                    "quality-gates.md": "# Quality Gates — WHY2\n\n## Verdict: FAIL\n"}, routing=claim)
            else:
                fields = dict(verdict="accept", reason="The unresolved finding is still supported.",
                    assessments=[dict(id=label, verdict="accept", reason="The controls remain unspecified.",
                        evidence=[context["citations"][label]]) for label in assignment["assigned_ids"]])
        else:
            return super().run_inspection_turn(*args, **kwargs)
        return replace(response, stdout=json.dumps({**assignment, "action": "final", **fields}))


class BanzaiIssueExecutor(RepairExecutor):
    """Offer an explicitly eligible native issue, not a free-text default."""
    def run_inspection_turn(self, *args, **kwargs):
        response = super().run_inspection_turn(*args, **kwargs)
        payload = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])
        if payload["assignment"].get("producer") == "why2" and payload["assignment"]["step"] == "author":
            reply = json.loads(response.stdout)
            if reply["routing"]["verdict"] == "FAIL":
                reply["artifacts"]["issues.md"] = reply["artifacts"]["issues.md"].replace(
                    "**Banzai eligible:** no", "**Banzai eligible:** yes")
                return replace(response, stdout=json.dumps(reply))
        return response


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_banzai_native_issue_selection_repairs_without_spending_quality_budget(checkpoint_case, provider):
    from harness.phase1_quality import has_current_phase1_quality_certificate
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "banzai"
    store.save(state)
    install_why2(checkpoint_case)
    config = root / ".echelon/config.yml"
    value = yaml.safe_load(config.read_text())
    value["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.write_text(yaml.safe_dump(value))
    executor = BanzaiIssueExecutor(provider)
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why2"}
    result = controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True)
    assert result.phase in {"checkpoint-assess", "phase1-lexicon-derive"}, result
    saved, history = store.load(), identity.identity_history(spec_id="game")
    assert saved["blocked_decision"]["resolved_by"] == "controller"
    assert saved["blocked_decision"]["selected_option_id"] == "ISS-000001"
    assert saved["phase1_quality_repair"]["automatic_consumed"] == 0
    assert has_current_phase1_quality_certificate(saved, project_root=root)
    assert not (store.staging_dir / "user-clarifications.md").exists()
    assert len(executor.calls) == 27 and saved["token_usage"] == 189
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == result.phase
    assert store.load() == saved and identity.identity_history(spec_id="game") == history and len(executor.calls) == 27
    assert_policy_binding_tamper_rejected(checkpoint_case, {25, 26})


class StagnantRepairExecutor(UnresolvedRepairExecutor):
    """Leave WHAT unchanged so native certified-metric stagnation is real."""
    def run_inspection_turn(self, *args, **kwargs):
        payload = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])
        assignment, context = payload["assignment"], payload["context"]
        if assignment.get("producer") == "what" and assignment["editable_revisions"]:
            response = ScriptedExecutor.run_inspection_turn(self, *args, **kwargs)
            if assignment["step"] == "propose":
                fields = dict(new_subjects=[], revisions=[])
            elif assignment["step"] == "author":
                fields = dict(artifacts={name: context["baseline"][name] for name in ("spec.md", "requirements-overview.md")}, routing=routing())
            else:
                fields = dict(verdict="accept", reason="The selected inputs remain unchanged.",
                    assessments=[dict(id=label, verdict="accept", reason="Existing identity is preserved.",
                        evidence=[context["citations"][label]]) for label in assignment["assigned_ids"]])
            return replace(response, stdout=json.dumps({**assignment, "action": "final", **fields}))
        response = super().run_inspection_turn(*args, **kwargs)
        if assignment.get("producer") == "why2" and assignment["step"] == "author":
            reply = json.loads(response.stdout)
            revision = dict(assignment["editable_revisions"]).get("ISS-000001", "0")
            reply["artifacts"]["issues.md"] = reply["artifacts"]["issues.md"].replace(
                "The movement requirement does not identify its controls.",
                "Reassessment " + str(int(revision) + 1) + ": the movement requirement still does not identify its controls.")
            return replace(response, stdout=json.dumps(reply))
        return response


class PostResetRepairExecutor(RepairExecutor):
    def run_inspection_turn(self, *args, **kwargs):
        payload = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])
        if payload["assignment"].get("producer") == "why2" and "using arrow keys." not in payload["context"]["baseline"]["spec.md"]:
            return UnresolvedRepairExecutor.run_inspection_turn(self, *args, **kwargs)
        return super().run_inspection_turn(*args, **kwargs)


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_perfectionist_stagnation_reset_preserves_analysis_then_repairs(checkpoint_case, monkeypatch, provider):
    from harness.phase1_quality import has_current_phase1_quality_certificate
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state.update(autonomy_mode="guided", spec_authoring_mode="perfectionist")
    state.pop("phase1_quality_repair")
    store.save(state)
    install_why2(checkpoint_case)
    config = root / ".echelon/config.yml"
    value = yaml.safe_load(config.read_text())
    value["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.write_text(yaml.safe_dump(value))
    executor = StagnantRepairExecutor(provider)
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why2"}
    result = controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True)
    assert result.phase == "terminal-blocked", result
    before, history = store.load(), identity.identity_history(spec_id="game")
    assert before["blocked_decision"]["resolution_handler"] == "reset_why2_stagnation"
    assert before["why2_metric_stagnation_count"] == 2 and len(executor.calls) == 33
    interrupt_answer_publication(checkpoint_case, executor, monkeypatch,
        "Reassess, then repair the existing controls requirement.")
    resumed = store.load()
    assert resumed["phase"] == "phase1-why2" and resumed["why_fail_count"] == resumed["why2_metric_stagnation_count"] == 0
    assert resumed["understanding_evidence"] == before["understanding_evidence"] and resumed["quality_scores"] == before["quality_scores"]
    assert identity.identity_history(spec_id="game") == history and "phase1_quality_repair" not in resumed
    final_executor = PostResetRepairExecutor(provider)
    result = controller(checkpoint_case, final_executor).run(managed_discovery=selected)
    assert result.phase in {"checkpoint-assess", "phase1-lexicon-derive"}, result
    saved = store.load()
    assert has_current_phase1_quality_certificate(saved, project_root=root)
    assert len(final_executor.calls) == 9 and saved["token_usage"] == 294 and "phase1_quality_repair" not in saved
    assert controller(checkpoint_case, final_executor).run(managed_discovery=selected).phase == result.phase
    assert store.load() == saved and len(final_executor.calls) == 9
    assert_policy_binding_tamper_rejected(checkpoint_case, {23, 24})


def unresolved_spec(baseline, *, add_lighting=True):
    import re
    statement = "The system SHALL " + "perhaps " * (baseline.count("perhaps") + 1) + "do various things somehow."
    amended = re.sub(r"(### FR-000001: Player movement\n- \*\*Statement\*\*: )[^\n]+",
        lambda match: match[1] + statement, baseline, count=1)
    if add_lighting and "FR-000002" not in baseline:
        amended = amended.replace("## Quality requirements", "### FR-000002: Lighting\n"
            "- **Statement**: The system SHALL do it somehow.\n\n## Quality requirements")
    return amended


def unresolved_issues(baseline):
    number = baseline.count("perhaps")
    if not number:
        return REPAIR_ISSUES
    return REPAIR_ISSUES.replace("The movement requirement does not identify its controls.",
        f"After repair {number}, the movement requirement still does not identify its controls.")


def test_restoration_fixture_really_ranks_original_above_its_repairs(tmp_path):
    from understanding.service import analyze_spec_bundle
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    from tests.unit.test_managed_spec_contract import SPEC
    thresholds = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    scores = []
    candidate = SPEC
    for index in range(4):
        path = tmp_path / f"candidate-{index}.md"
        path.write_text(candidate)
        report = analyze_spec_bundle(path, thresholds=thresholds).to_dict()
        scores.append(report["scores"]["overall"])
        candidate = unresolved_spec(candidate)
    assert all(scores[0] > score for score in scores[1:]), scores


def test_restoration_fixture_really_retains_four_distinct_issue_occurrences(tmp_path):
    from harness.element_identity_store import IdentityStore
    from harness.element_identity_lifecycle import ElementCreate, ElementRevision
    from harness.element_identity_candidate import CandidateArtifact
    from harness.discovery_candidate import issue_report_changes
    from harness.element_artifacts import parse_identity_artifact
    from tests.unit.test_managed_spec_contract import SPEC
    identity = IdentityStore.initialize(tmp_path)
    identity.reserve(spec_id="game", kind="ISS", operation_id="reserve", count=1)
    baseline, previous = SPEC, None
    for index in range(4):
        report = unresolved_issues(baseline)
        content = parse_identity_artifact(path="issues.md", role="issues", text=report).declarations[0].content.split("\n", 1)[1]
        change = (ElementCreate("ISS-000001", "Movement controls", content, "reserve") if index == 0
            else ElementRevision("ISS-000001", str(index), "Movement controls", content))
        _, occurrences = issue_report_changes((CandidateArtifact("issues.md", "issues", previous, report),),
            (change,), identity.identity_history(spec_id="game"), report_id="review-" + str(index))
        identity.apply_lifecycle(spec_id="game", operation_id="revision-" + str(index), changes=(change,))
        identity.record_issue_occurrences(spec_id="game", operation_id="review-" + str(index), occurrences=occurrences)
        previous, baseline = report, unresolved_spec(baseline)
    history = json.loads(identity.identity_history(spec_id="game").payload)
    assert len(history["issue_occurrences"]) == 4
    assert len({row["report_sha256"] for row in history["issue_occurrences"]}) == 4
    assert identity.lookup(spec_id="game", element_id="ISS-000001")["revision"] == "4"


def install_why2(case):
    install_what(case)
    repo = Path(__file__).resolve().parents[2]
    for relative in ("subagents/echelon.why2-producer.md", "subagents/echelon.why2-reviewer.md",
            "agents/exploration/templates/sage-quality-gates-template.md",
            "agents/exploration/templates/sage-issues-template.md"):
        destination = case[0] / ".echelon/prosaic" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((repo / "prosaic" / relative).read_bytes())


def restoration_interruptions(monkeypatch, *, already_seen=()):
    """Crash only restoration owners; never fake an accepted provider result."""
    import harness.discovery_restoration_completion as continuation
    import harness.git_first_restore as native
    import harness.squad as squad
    from harness.element_identity_store import IdentityStore
    from tests.unit.test_discovery_turns import Interrupted
    expected = ["child_prepared", "after_journal", "after_all_exchanges", "after_ref_update",
        "before_receipt", "before_child_apply", "after_child_apply", "before_quality_receipt",
        "after_quality_receipt", "before_release", "after_release"]
    assert list(already_seen) == expected[:len(already_seen)]
    seen = list(already_seen)
    def hit(point):
        if len(seen) < len(expected) and point == expected[len(seen)]:
            seen.append(point)
            raise Interrupted()
    prepare = continuation._prepare_continuation
    def prepared(*args, **kwargs):
        result = prepare(*args, **kwargs)
        hit("child_prepared")
        return result
    monkeypatch.setattr(continuation, "_prepare_continuation", prepared)
    monkeypatch.setattr(native, "_restore_fault", hit)
    apply = IdentityStore.apply_identity_publication
    def applied(self, **kwargs):
        restoring = kwargs["operation_id"].startswith("discovery-restore-")
        if restoring:
            hit("before_child_apply")
        result = apply(self, **kwargs)
        if restoring:
            hit("after_child_apply")
        return result
    monkeypatch.setattr(IdentityStore, "apply_identity_publication", applied)
    persist = squad.persist_completion_effect_receipt
    def persisted(prepared, effect, receipt):
        restoring = effect == "quality" and prepared.intent.quality_effect.get("restore_candidate_id") is not None
        if restoring:
            hit("before_quality_receipt")
        result = persist(prepared, effect, receipt)
        if restoring:
            hit("after_quality_receipt")
        return result
    monkeypatch.setattr(squad, "persist_completion_effect_receipt", persisted)
    release = IdentityStore.release_identity_publication
    def released(self, **kwargs):
        row = self.identity_publication(spec_id=kwargs["spec_id"], operation_id=kwargs["operation_id"])
        from harness.element_identity_publication import decode_publication_request
        restoring = decode_publication_request(row["request"]).continuation_id is not None
        if restoring:
            hit("before_release")
        result = release(self, **kwargs)
        if restoring:
            hit("after_release")
        return result
    monkeypatch.setattr(IdentityStore, "release_identity_publication", released)
    return expected, seen


def run_restoration_interruptions(case, executor, selected, monkeypatch, *, already_seen=()):
    from tests.unit.test_discovery_turns import Interrupted
    store = case[1]
    expected, seen = restoration_interruptions(monkeypatch, already_seen=already_seen)
    charged_calls = (len(executor.calls), store.load()["token_usage"]) if already_seen else None
    for attempt in range(len(seen), len(expected) + 1):
        try:
            result = controller(case, executor).run(managed_discovery=selected,
                create_managed_discovery=attempt == 0)
            break
        except Interrupted:
            assert len(seen) == attempt + 1
            if charged_calls is None:
                charged_calls = len(executor.calls), store.load()["token_usage"]
            assert (len(executor.calls), store.load()["token_usage"]) == charged_calls
    assert seen == expected, result
    return result


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_managed_why2_restores_best_candidate_with_forward_history(checkpoint_case, provider, monkeypatch):
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    from tests.unit.test_managed_spec_contract import SPEC
    root, store, identity, _ = checkpoint_case
    install_why2(checkpoint_case)
    config = root / ".echelon/config.yml"
    value = yaml.safe_load(config.read_text())
    value["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.write_text(yaml.safe_dump(value))
    executor = UnresolvedRepairExecutor(provider)
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why2"}
    result = run_restoration_interruptions(checkpoint_case, executor, selected, monkeypatch)
    state = store.load()
    assert result.phase == "terminal-blocked", (result, state.get("controller_contract_error"))
    assert "_spec_step_effect_plan" not in state, result
    assert state["blocked_reason"] == "proportional_quality_budget_exhausted"
    assert state["phase1_quality_repair"]["automatic_consumed"] == 3
    assert len(state["phase1_quality_repair"]["candidate_ids"]) == 4
    assert (root / "specs/game/spec.md").read_text() == SPEC
    assert (root / "specs/game/issues.md").read_text() == REPAIR_ISSUES
    assert identity.lookup(spec_id="game", element_id="FR-000001")["revision"] == "5"
    assert identity.lookup(spec_id="game", element_id="FR-000002")["present"] is False
    history = identity.identity_history(spec_id="game")
    assert len(json.loads(history.payload)["issue_occurrences"]) == 4
    assert identity.pending_identity_publication(spec_id="game") is None
    calls = len(executor.calls)
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == result.phase
    assert store.load() == state and identity.identity_history(spec_id="game") == history and len(executor.calls) == calls
    ledger = json.loads((root / "specs/game/.echelon/checkpoints.json").read_text())
    assert len([row for row in ledger["checkpoints"] if row["phase"] == "phase1-quality-candidate-restored"]) == 1
    from harness.element_identity_publication import decode_publication_request
    parent = identity.identity_publication(spec_id="game",
        operation_id="discovery-completion-" + state["last_dispatch"]["dispatch_id"])
    request = decode_publication_request(parent["request"])
    child = identity.identity_publication(spec_id="game", operation_id=request.continuation_id)
    assert parent["state"] == child["state"] == "released"
    assert identity.reserve(spec_id="game", kind="FR", operation_id="post-restoration-counter", count=1) == ("FR-000003",)


@pytest.mark.parametrize("choice", ["continue_with_debt", "stop"])
@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_managed_quality_debt_choice_preserves_history_and_restarts(checkpoint_case, choice, provider, monkeypatch):
    from harness.phase1_quality_debt import has_current_quality_debt_authorization
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "guided"
    store.save(state)
    install_why2(checkpoint_case)
    config = root / ".echelon/config.yml"
    value = yaml.safe_load(config.read_text())
    value["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.write_text(yaml.safe_dump(value))
    executor = UnresolvedRepairExecutor(provider)
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why2"}
    assert controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True).phase == "terminal-blocked"
    before, history = store.load(), identity.identity_history(spec_id="game")
    assert before["blocked_reason"] == "proportional_quality_budget_exhausted" and len(executor.calls) == 39
    interrupt_answer_publication(checkpoint_case, executor, monkeypatch, option=choice, quality=True)
    controller(checkpoint_case, executor).run(managed_discovery=selected)
    resolved = store.load()
    assert resolved["blocked_decision"]["selected_option_id"] == choice
    assert resolved["phase1_quality_repair"] == before["phase1_quality_repair"]
    assert identity.identity_history(spec_id="game") == history
    assert identity.pending_identity_publication(spec_id="game") is None
    assert len(executor.calls) == 39 and resolved["token_usage"] == 273
    if choice == "continue_with_debt":
        assert resolved["phase"] in {"checkpoint-assess", "phase1-lexicon-derive"}
        assert has_current_quality_debt_authorization(resolved, project_root=root)
        from copy import deepcopy
        downstream = deepcopy(resolved)
        downstream.update(phase="phase2-decide", status="running", last_dispatch={"phase_id": "phase2-analyze"})
        downstream.pop("blocked_decision", None)
        assert has_current_quality_debt_authorization(downstream, project_root=root)
    else:
        assert resolved["status"] == "blocked" and resolved["blocked_reason"] == "proportional_quality_debt_declined"
        assert not (root / "specs/game/quality-debt.json").exists()
    controller(checkpoint_case, executor).run(managed_discovery=selected)
    saved = store.load()
    controller(checkpoint_case, executor).run(managed_discovery=selected)
    assert store.load() == saved and identity.identity_history(spec_id="game") == history and len(executor.calls) == 39
    assert_policy_binding_tamper_rejected(checkpoint_case, {27})


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_managed_banzai_quality_debt_retains_native_controller_choice(checkpoint_case, provider):
    from harness.phase1_quality_debt import has_current_quality_debt_authorization
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "banzai"
    store.save(state)
    install_why2(checkpoint_case)
    config = root / ".echelon/config.yml"
    value = yaml.safe_load(config.read_text())
    value["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.write_text(yaml.safe_dump(value))
    executor = UnresolvedRepairExecutor(provider)
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why2"}
    result = controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True)
    saved = store.load()
    assert result.phase in {"phase1-lexicon-derive", "checkpoint-assess"}, result
    assert saved["blocked_decision"]["selected_option_id"] == "continue_with_debt"
    assert saved["blocked_decision"]["resolved_by"] == "controller"
    assert saved["phase1_quality_repair"]["automatic_consumed"] == 3
    assert len(executor.calls) == 39 and saved["token_usage"] == 273
    assert has_current_quality_debt_authorization(saved, project_root=root)
    history = identity.identity_history(spec_id="game")
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == result.phase
    assert store.load() == saved and identity.identity_history(spec_id="game") == history and len(executor.calls) == 39


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_managed_quality_extension_preserves_restored_history_and_native_budget(checkpoint_case, monkeypatch, repair_succeeds):
    from harness.phase1_quality import has_current_phase1_quality_certificate
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "guided"
    store.save(state)
    install_why2(checkpoint_case)
    config = root / ".echelon/config.yml"
    value = yaml.safe_load(config.read_text())
    value["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.write_text(yaml.safe_dump(value))
    executor = UnresolvedRepairExecutor("codex" if repair_succeeds else "claude")
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why2"}
    result = controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True)
    assert result.phase == "terminal-blocked", result
    before, history = store.load(), identity.identity_history(spec_id="game")
    assert before["blocked_reason"] == "proportional_quality_budget_exhausted"
    assert before["phase1_quality_repair"]["automatic_consumed"] == 3
    assert len(executor.calls) == 39
    interrupt_answer_publication(checkpoint_case, executor, monkeypatch, option="extend_once")
    authorized = store.load()
    assert authorized["phase"] == "phase1-what"
    assert authorized["phase1_quality_repair"] == {**before["phase1_quality_repair"], "extension_authorized": 1}
    assert identity.identity_history(spec_id="game") == history and len(executor.calls) == 39
    assert identity.pending_identity_publication(spec_id="game") is None
    final_executor = RepairExecutor() if repair_succeeds else UnresolvedRepairExecutor("claude", add_lighting=False)
    result = controller(checkpoint_case, final_executor).run(managed_discovery=selected)
    saved = store.load()
    assert saved["phase1_quality_repair"]["automatic_consumed"] == 3
    assert saved["phase1_quality_repair"]["extension_authorized"] == saved["phase1_quality_repair"]["extension_consumed"] == 1
    assert len(final_executor.calls) == 6 and saved["token_usage"] == 315
    if repair_succeeds:
        assert result.phase in {"checkpoint-assess", "phase1-lexicon-derive"}, result
        assert has_current_phase1_quality_certificate(saved, project_root=root)
    else:
        from harness.phase1_quality_debt import has_current_quality_debt_authorization
        assert result.phase == "terminal-blocked", result
        assert saved["blocked_reason"] == "proportional_quality_extension_exhausted"
        assert {option["id"] for option in saved["blocked_decision"]["options"]} == {"continue_with_debt", "stop"}
        budget = saved["phase1_quality_repair"]
        interrupt_answer_publication(checkpoint_case, final_executor, monkeypatch, option="continue_with_debt", quality=True)
        result = controller(checkpoint_case, final_executor).run(managed_discovery=selected)
        saved = store.load()
        assert result.phase in {"checkpoint-assess", "phase1-lexicon-derive"}, result
        assert has_current_quality_debt_authorization(saved, project_root=root)
        assert saved["phase1_quality_repair"] == budget and saved["token_usage"] == 315
    assert (store.staging_dir / "user-clarifications.md").exists() is False
    current_history = identity.identity_history(spec_id="game")
    assert controller(checkpoint_case, final_executor).run(managed_discovery=selected).phase == result.phase
    assert store.load() == saved and identity.identity_history(spec_id="game") == current_history and len(final_executor.calls) == 6
    assert_policy_binding_tamper_rejected(checkpoint_case, {21, 22} if repair_succeeds else {21, 22, 27})


def assert_policy_binding_tamper_rejected(case, expected_versions=frozenset({21, 22})):
    """Detached rehashing never supplies native policy or predecessor authority."""
    from copy import deepcopy
    from harness.discovery_completion import decode_binding, _released_discovery_projections
    from harness.discovery_policy_resolution import require_parent
    from harness.element_identity_publication import encode_publication_request
    from harness.squad_completion import CompletionError
    root, store, identity, _ = case
    state, history = store.load(), identity.identity_history(spec_id="game")
    completion_id = (state["last_human_input_completion"]["completion_id"] if 27 in expected_versions
        else state["last_dispatch"]["dispatch_id"])
    seen, tested = set(), set()
    while completion_id not in seen:
        seen.add(completion_id)
        row = identity.identity_publication(spec_id="game", operation_id="discovery-completion-" + completion_id)
        publication = json.loads(row["completion_payload"])["proof"]["intent"]["publication"]
        binding = decode_binding(publication, completion_id=completion_id, state=state)
        version = binding.recovery["version"]
        if version in {21, 22, 23, 24, 25, 26, 27}:
            tested.add(version)
            for damage in ("version", "source", "choice", "authority"):
                recovery = deepcopy(binding.recovery)
                if damage == "version": recovery["version"] = True
                elif damage == "source": recovery["source_completion"]["dispatch_id"] = "0" * 32
                elif damage == "choice":
                    decision = recovery["resolution"] if version in {21, 23, 25, 27} else (
                        recovery["resolution"]["decision"] if version == 24 else recovery["review_resolution"]["decision"])
                    decision["selected_option_id"] = "stop" if decision["selected_option_id"] == "continue_with_debt" else "continue_with_debt"
                elif version == 21:
                    recovery["before"]["phase1_quality_repair"]["automatic_consumed"] = 0
                    recovery["effects"]["state_updates"]["phase1_quality_repair"]["automatic_consumed"] = 0
                elif version in {22, 26}:
                    recovery["review_parent"] = "why2-" + "0" * 32
                elif version == 23:
                    recovery["before"]["why2_metric_stagnation_count"] += 1
                elif version == 25:
                    ledger = deepcopy(recovery["effects"]["state_updates"]["issue_resolution_ledger"])
                    ledger[recovery["resolution"]["selected_option_id"]]["status"] = "validated"
                    recovery["before"]["issue_resolution_ledger"] = ledger
                elif version == 27:
                    recovery["quality_effect"]["payload"]["debt_path"] = "specs/game/spec.md"
                else:
                    recovery["predecessor"] = "why2-" + "0" * 32
                changed = deepcopy(publication)
                changed["managed_discovery"]["request"] = encode_publication_request(replace(binding.request,
                    recovery_payload=json.dumps(recovery, sort_keys=True, separators=(",", ":"))))
                with pytest.raises((CompletionError, ValueError)):
                    altered = decode_binding(changed, completion_id=completion_id, state=state)
                    if version in {21, 23, 25, 27}:
                        require_parent(root, store.squad_dir, state, altered, identity)
                    else:
                        _released_discovery_projections(root, store.squad_dir, state, historical=True,
                            source=altered.recovery["source_completion"], spec_child=altered)
        source = binding.recovery.get("source_completion")
        if source is None:
            break
        completion_id = source["dispatch_id"]
    assert tested == expected_versions
    assert store.load() == state and identity.identity_history(spec_id="game") == history


def test_managed_why2_repairs_same_requirement_and_reassesses(checkpoint_case):
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    from harness.phase1_quality import has_current_phase1_quality_certificate
    root, store, identity, _ = checkpoint_case
    install_why2(checkpoint_case)
    config = root / ".echelon/config.yml"
    value = yaml.safe_load(config.read_text())
    value["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.write_text(yaml.safe_dump(value))
    executor = RepairExecutor("codex")
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why2"}
    result = controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True)
    assert result.phase in {"checkpoint-assess", "phase1-lexicon-derive"}, (result, store.load().get("controller_contract_error"))
    state = store.load()
    assert has_current_phase1_quality_certificate(state, project_root=root)
    assert state["phase1_quality_repair"]["automatic_consumed"] == 1
    assert len(state["phase1_quality_repair"]["candidate_ids"]) == 2
    assert state["token_usage"] == 189 and len(executor.calls) == 27
    history = identity.identity_history(spec_id="game")
    fr, = [row for row in json.loads(history.payload)["entities"] if row["kind"] == "FR"]
    assert (fr["element_id"], fr["revision"]) == ("FR-000001", "2")
    issue, = [row for row in json.loads(history.payload)["entities"] if row["kind"] == "ISS"]
    assert (issue["element_id"], issue["revision"]) == ("ISS-000001", "2")
    assert len(json.loads(history.payload)["issue_occurrences"]) == 2
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == result.phase
    assert store.load() == state and identity.identity_history(spec_id="game") == history
    assert len(executor.calls) == 27
    from harness.discovery_restoration import retained_quality_candidate_history
    from harness.proportional_quality import load_quality_candidate_snapshot, preflight_quality_candidate_restore
    candidate_id = state["phase1_quality_repair"]["candidate_ids"][0]
    path = store.squad_dir / "quality-candidates" / (candidate_id + ".json")
    snapshot = load_quality_candidate_snapshot(path)
    selected_restore = preflight_quality_candidate_restore(project_root=root, spec_dir=root / "specs/game",
        manifest_path=path, expected_candidate_id=candidate_id, expected_manifest_sha256=snapshot.sha256)
    dispatch = state["last_dispatch"]
    source = {key: dispatch[key] for key in ("dispatch_id", "completion_intent_sha256",
        "completion_receipts_sha256", "completed_publication_binding_sha256")}
    selected_history, selected_source = retained_quality_candidate_history(root, store.squad_dir, state,
        source=source, selected=selected_restore)
    original_heads = {row["element_id"]: row["revision"] for row in json.loads(selected_history.payload)["entities"]}
    assert original_heads["FR-000001"] == "1" and original_heads["ISS-000001"] == "1"
    assert selected_source["dispatch_id"] != source["dispatch_id"]
    assert identity.identity_history(spec_id="game") == history and store.load() == state


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_managed_why2_certifies_passing_analysis_and_review(checkpoint_case, provider):
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    from harness.phase1_quality import has_current_phase1_quality_certificate
    root, store, identity, _ = checkpoint_case
    install_why2(checkpoint_case)
    config = root / ".echelon/config.yml"
    value = yaml.safe_load(config.read_text())
    # A fixture policy fixed before discovery/analysis, never lowered by SAGE.
    value["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.write_text(yaml.safe_dump(value))
    executor = Why2Executor(provider)
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why2"}
    result = controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True)
    assert result.phase in {"checkpoint-assess", "phase1-lexicon-derive"}, (result, store.load().get("controller_contract_error"))
    state = store.load()
    assert has_current_phase1_quality_certificate(state, project_root=root)
    assert state["token_usage"] == 147 and len(executor.calls) == 21
    assert state["last_dispatch"]["phase_id"] == "phase1-why2"
    assert state["last_dispatch"]["post_dispatch_complete"]
    history = identity.identity_history(spec_id="game")
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == result.phase
    assert store.load() == state and identity.identity_history(spec_id="game") == history
    assert len(executor.calls) == 21
    # Selection must recover the history of this exact retained assessment,
    # not the current mutable history or a candidate-ID-only database search.
    from harness import discovery_restoration
    from harness.proportional_quality import load_quality_candidate_snapshot, preflight_quality_candidate_restore
    lookup = getattr(discovery_restoration, "retained_quality_candidate_history", None)
    assert callable(lookup), "Native selection requires its retained managed history"
    candidate_id, = state["phase1_quality_repair"]["candidate_ids"]
    path = store.squad_dir / "quality-candidates" / (candidate_id + ".json")
    snapshot = load_quality_candidate_snapshot(path)
    selected_restore = preflight_quality_candidate_restore(project_root=root, spec_dir=root / "specs/game",
        manifest_path=path, expected_candidate_id=candidate_id, expected_manifest_sha256=snapshot.sha256)
    dispatch = state["last_dispatch"]
    source = {key: dispatch[key] for key in ("dispatch_id", "completion_intent_sha256",
        "completion_receipts_sha256", "completed_publication_binding_sha256")}
    selected_history, selected_source = lookup(root, store.squad_dir, state,
        source=source, selected=selected_restore)
    assert selected_history == history and selected_source == source
    for changed in (
        replace(selected_restore, snapshot=replace(snapshot, sha256="0" * 64)),
        replace(selected_restore, snapshot=replace(snapshot, manifest=replace(snapshot.manifest, assessment_index=9))),
        replace(selected_restore, entries=selected_restore.entries[:-1]),
    ):
        with pytest.raises(ValueError):
            lookup(root, store.squad_dir, state, source=source, selected=changed)
    assert store.load() == state and identity.identity_history(spec_id="game") == history
