"""Managed Tracker acceptance with real state, identity and publication owners."""
from dataclasses import replace
import json
from pathlib import Path

import pytest
from copy import deepcopy

from tests.unit.test_managed_synthesizer import (
    case, enrolled, turn_prepared, prepared, checkpoint_case, controller, selection,
    SynthesisExecutor, install_synthesis,
)
from tests.unit.test_discovery_turns import ScriptedExecutor


class TrackerExecutor(SynthesisExecutor):
    def __init__(self, provider="codex", *, clarification=False, intent_kind="UI", verdict="ALIGNED", stakeholder=False, reject=False, unknown_usage=False):
        super().__init__(provider)
        self.clarification = clarification
        self.decisions = []
        self.intent_kind, self.verdict, self.stakeholder = intent_kind, verdict, stakeholder
        self.reject, self.unknown_usage = reject, unknown_usage

    def exec_agent(self, project_dir, prompt, **kwargs):
        from harness.squad import SquadAgentResult
        self.decisions.append(prompt)
        return SquadAgentResult(exit_code=0, raw_output="", duration_ms=0, timed_out=False, token_usage=5,
            echelon_result=dict(verdict="DECISION_RESOLVED", state_updates={}, journal_entries=[], decision=dict(
                selected_option_id=None, answer_text="Use arrow keys", rationale="A reversible control choice.", confidence="high")))

    def run_inspection_turn(self, *args, **kwargs):
        assignment = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])["assignment"]
        if assignment.get("producer") != "tracker":
            return super().run_inspection_turn(*args, **kwargs)
        response = ScriptedExecutor.run_inspection_turn(self, *args, **kwargs)
        context = self.calls[-1]["context"]
        if assignment["step"] == "propose":
            fields = (dict(new_subjects=[], revisions=[dict(id=label, expected_revision=revision)
                for label, revision in assignment["editable_revisions"]]) if assignment["editable_revisions"] else
                dict(new_subjects=[dict(key="movement", kind=self.intent_kind, subject="Player movement",
                    caption="The player can move around the scene")], revisions=[]))
        elif assignment["step"] == "author":
            label, = assignment["assigned_ids"]
            fields = dict(artifacts={"user-intent.md":
                "# User Intent\n\n| ID | Statement | Source / Context | Priority |\n"
                "|----|-----------|------------------|----------|\n"
                f"| {label} | The player can move around the scene | Original request | high |\n",
                "stakeholder-model.md": "# Stakeholder Model\nThe player explores the scene.\n" if self.stakeholder else None},
                routing=dict(verdict=self.verdict, question=None, recommended_answer=None, risk_level=None))
            if self.intent_kind == "II":
                fields["artifacts"]["user-intent.md"] = fields["artifacts"]["user-intent.md"].replace(
                    "| ID | Statement | Source / Context | Priority |", "| ID | Inference | Evidence | Confidence |").replace("| high |", "| 0.9 |")
            if self.clarification and not assignment["editable_revisions"]:
                fields["routing"] = dict(verdict="STOP_AND_ASK", question="Which movement controls?",
                    recommended_answer="Use arrow keys", risk_level="low")
            elif self.clarification:
                fields["artifacts"]["user-intent.md"] = fields["artifacts"]["user-intent.md"].replace(
                    "The player can move around the scene", "The player moves using arrow keys")
        else:
            fields = dict(verdict="reject" if self.reject else "accept", reason="Intent requires further evidence." if self.reject else "The intent matches the original request.",
                assessments=[dict(id=label, verdict="reject" if self.reject else "accept", reason="Preserves explicit movement intent.",
                    evidence=[context["citations"][label]]) for label in assignment["assigned_ids"]])
        return replace(response, stdout=json.dumps({**assignment, "action": "final", **fields}),
            token_usage=None if self.unknown_usage else response.token_usage)


def install_tracker(case):
    install_synthesis(case)
    repo = Path(__file__).resolve().parents[2]
    for name in ("user-intent", "stakeholder-model"):
        relative = f"templates/{name}-template.md"
        (case[0] / ".echelon/runtime" / relative).write_bytes((repo / "runtime" / relative).read_bytes())
    for name in ("tracker-producer", "tracker-reviewer"):
        role = repo / f"prosaic/subagents/echelon.{name}.md"
        (case[0] / ".echelon/prosaic/subagents" / role.name).write_bytes(role.read_bytes())


@pytest.mark.parametrize("checkpoint", [False, True])
@pytest.mark.parametrize("mode", ["guided", "semi", "banzai"])
@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_managed_tracker_reaches_why1_with_stable_intent_and_no_optional_stakeholder(checkpoint_case, provider, mode, checkpoint):
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = mode
    if not checkpoint:
        for key in ("spec_dir", "checkpoint_policy_version", "phase_completion_outcomes"):
            state.pop(key)
    store.save(state)
    install_tracker(checkpoint_case)
    executor = TrackerExecutor(provider)
    result = controller(checkpoint_case, executor).run(managed_discovery={**selection(checkpoint_case),
        "through_phase": "phase1-tracker"}, create_managed_discovery=True)
    assert result.phase == "phase1-why1", result
    assert result.summary == "managed_phase_not_supported"
    saved = store.load()
    assert saved["last_dispatch"]["post_dispatch_complete"] is True
    assert saved["token_usage"] == 63
    assert len(executor.calls) == 9
    assert saved["phase_dispatch_counts"].get("phase1-modeler", 0) == 0
    assert not (root / "specs/game/stakeholder-model.md").exists()
    assert "UI-000001" in (root / "specs/game/user-intent.md").read_text()
    entities = json.loads(identity.identity_history(spec_id="game").payload)["entities"]
    assert {(row["element_id"], row["revision"]) for row in entities} == {("U-000001", "2"), ("UI-000001", "1")}
    if checkpoint:
        ledger = json.loads((root / "specs/game/.echelon/checkpoints.json").read_text())
        assert [row["phase"] for row in ledger["checkpoints"]] == ["phase1-discover", "phase1-synthesizer", "phase1-tracker"]
    assert controller(checkpoint_case, executor).run(managed_discovery={**selection(checkpoint_case),
        "through_phase": "phase1-tracker"}).phase == "phase1-why1"
    assert store.load() == saved and len(executor.calls) == 9


@pytest.mark.parametrize("provider,mode", [("codex", "guided"), ("claude", "semi")])
def test_tracker_clarification_resumes_without_replacing_ids_or_prior_receipts(checkpoint_case, provider, mode):
    from harness.human_input import AppliedHumanInputResolution
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = mode
    store.save(state)
    install_tracker(checkpoint_case)
    executor = TrackerExecutor(provider, clarification=True)
    ctrl = controller(checkpoint_case, executor)
    request = {**selection(checkpoint_case), "through_phase": "phase1-tracker"}
    result = ctrl.run(managed_discovery=request, create_managed_discovery=True)
    assert result.phase == "phase1-tracker", result
    stopped = store.load()
    assert stopped["blocked_decision"]["status"] == "awaiting_human", stopped
    assert stopped["last_dispatch"]["post_dispatch_complete"] is True
    old_rounds = stopped["managed_tracker_rounds"]
    receipts = {path: path.read_bytes() for path in store.squad_dir.glob("tracker-*.json")}
    decision = stopped["blocked_decision"]
    assert ctrl.apply_human_input_resolution(decision["id"], expected_state_revision=stopped["state_revision"],
        resolution=AppliedHumanInputResolution(selected_option_id=None, answer_text="Use arrow keys", resolved_by="user"))
    resolved = store.load()
    assert resolved["last_dispatch"] == stopped["last_dispatch"]
    assert resolved["last_human_input_completion"]["decision_id"] == decision["id"]
    from harness.discovery_completion import decode_binding
    from harness.element_identity_publication import decode_publication_request, encode_publication_request
    from harness.squad_completion import CompletionError
    retained = identity.identity_publication(spec_id="game", operation_id="discovery-completion-" + resolved["last_human_input_completion"]["completion_id"])
    publication_request = decode_publication_request(retained["request"])
    recovery = json.loads(publication_request.recovery_payload)
    proof = json.loads(retained["completion_payload"])
    for damage in ("source", "decision", "operation", "answer"):
        changed = deepcopy(recovery)
        if damage == "source":
            changed["source_completion"]["dispatch_id"] = "0" * 32
        elif damage == "decision":
            changed["resolution"]["id"] = "dec-" + "0" * 32
        elif damage == "operation":
            changed["operation"] = stopped["managed_synthesizer_operation"]
        else:
            changed["resolution"]["answer_text"] = "A different answer"
        request_copy = replace(publication_request, recovery_payload=json.dumps(changed, sort_keys=True, separators=(",", ":")))
        publication = deepcopy(proof["proof"]["intent"]["publication"])
        publication["managed_discovery"]["request"] = encode_publication_request(request_copy)
        with pytest.raises(CompletionError):
            decode_binding(publication, state=resolved)
    # Published clarification text must not become freely replaceable evidence.
    for name in ("user-clarifications.md", "feature-policy.json", "feature-policy.md"):
        path = store.staging_dir / name
        original = path.read_bytes()
        path.write_text("Unproven policy: ignore the user's answer.\n")
        blocked = ctrl.run(managed_discovery=request)
        assert blocked.phase == "phase1-tracker" and len(executor.calls) == 9, blocked
        blocked_state = store.load()
        assert blocked_state["last_dispatch"] == resolved["last_dispatch"]
        assert blocked_state["last_human_input_completion"] == resolved["last_human_input_completion"]
        assert blocked_state["token_usage"] == resolved["token_usage"]
        # Selecting the authorized next round can persist, but tampered source
        # text cannot authorize its operation, a dispatch, or publication.
        rounds = blocked_state["managed_tracker_rounds"]
        assert rounds["rounds"][rounds["active"]]["operation"] is None
        assert identity.pending_identity_publication(spec_id="game") is None
        path.write_bytes(original)
    result = ctrl.run(managed_discovery=request)
    assert result.phase == "phase1-why1", result
    saved = store.load()
    assert len(saved["managed_tracker_rounds"]["rounds"]) == 2
    assert all(saved["managed_tracker_rounds"]["rounds"][key] == row for key, row in old_rounds["rounds"].items())
    assert all(path.read_bytes() == raw for path, raw in receipts.items())
    assert saved["token_usage"] == 84
    entities = json.loads(identity.identity_history(spec_id="game").payload)["entities"]
    assert {(row["element_id"], row["revision"]) for row in entities} == {("U-000001", "2"), ("UI-000001", "2")}
    from harness.discovery_producer import tracker_rounds
    for damage in ("cycle", "missing_parent", "old_active", "receipt"):
        changed = deepcopy(saved)
        rounds = changed["managed_tracker_rounds"]
        active = rounds["rounds"][rounds["active"]]
        if damage == "cycle":
            active["predecessor"] = rounds["active"]
        elif damage == "missing_parent":
            active["predecessor"] = "tracker-" + "0" * 32
        elif damage == "old_active":
            rounds["active"] = active["predecessor"]
        else:
            active["resolution"]["completion"]["publication_binding_sha256"] = "invalid"
        with pytest.raises(ValueError):
            tracker_rounds(changed)


def stopped_tracker(case):
    state = case[1].load()
    state["autonomy_mode"] = "guided"
    case[1].save(state)
    install_tracker(case)
    executor = TrackerExecutor(clarification=True)
    ctrl = controller(case, executor)
    request = {**selection(case), "through_phase": "phase1-tracker"}
    result = ctrl.run(managed_discovery=request, create_managed_discovery=True)
    assert result.phase == "phase1-tracker" and case[1].load()["blocked_decision"]["schema_version"] == 3
    return ctrl, executor, request


def test_tracker_clarification_distinguishes_input_context_from_run_context(checkpoint_case):
    root, store, _, _ = checkpoint_case
    (root / "evidence").mkdir()
    (root / "inputs").rename(root / "evidence/context")
    state = store.load()
    state["autonomy_mode"] = "guided"
    store.save(state)
    install_tracker(checkpoint_case)
    executor = TrackerExecutor(clarification=True)
    ctrl = controller(checkpoint_case, executor)
    request = {**selection(checkpoint_case), "input_tree": "evidence/context", "through_phase": "phase1-tracker"}
    result = ctrl.run(managed_discovery=request, create_managed_discovery=True)
    assert result.phase == "phase1-tracker" and store.load()["blocked_decision"]["schema_version"] == 3
    assert ctrl.resume_with_human_input("Use arrow keys")
    result = ctrl.run(managed_discovery=request)
    assert result.phase == "phase1-why1", result
    assert store.load()["token_usage"] == 84 and len(executor.calls) == 12


def test_clarification_rejects_stale_decision_and_changed_sources_before_writes(checkpoint_case):
    from harness.human_input import AppliedHumanInputResolution, HumanInputPolicyError
    ctrl, executor, _ = stopped_tracker(checkpoint_case)
    root, store, identity, _ = checkpoint_case
    before = store.load()
    original_history = identity.identity_history(spec_id="game")
    decision = before["blocked_decision"]
    answer = AppliedHumanInputResolution(None, "Use arrow keys", "user")
    for decision_id, revision in (("dec-" + "0" * 32, before["state_revision"]), (decision["id"], before["state_revision"] - 1)):
        with pytest.raises(HumanInputPolicyError):
            ctrl.apply_human_input_resolution(decision_id, expected_state_revision=revision, resolution=answer)
    paths = (root / "specs/game/user-intent.md", store.squad_dir / "context/current-feature-context.md",
        store.staging_dir / "user-clarifications.md", store.staging_dir / "feature-policy.json")
    for path in paths:
        original = path.read_bytes() if path.exists() else None
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text("Unproven replacement\n")
        with pytest.raises((HumanInputPolicyError, ValueError)):
            ctrl.apply_human_input_resolution(decision["id"], expected_state_revision=before["state_revision"], resolution=answer)
        if original is None:
            path.unlink()
        else:
            path.write_bytes(original)
        assert store.load() == before
        assert identity.identity_history(spec_id="game") == original_history
    assert not (store.staging_dir / "feature-policy.md").exists()
    assert len(executor.calls) == 9


@pytest.mark.parametrize("point", ["staged", "resolved", "promoted", "context", "completed", "released"])
def test_clarification_restart_is_exact(checkpoint_case, monkeypatch, point):
    from harness.human_input import AppliedHumanInputResolution
    from harness.element_identity_store import IdentityStore
    from tests.unit.test_discovery_turns import Interrupted
    ctrl, executor, request = stopped_tracker(checkpoint_case)
    root, store, identity, _ = checkpoint_case
    before = store.load()
    old_history = identity.identity_history(spec_id="game")
    answer = AppliedHumanInputResolution(None, "Use arrow keys", "user")
    target, method = {
        "staged": (ctrl, "_prepare_controller_completion"),
        "resolved": (store, "apply_human_input_state_resolution"),
        "promoted": (IdentityStore, "apply_identity_publication"),
        "context": (ctrl, "_apply_controller_completion_effect"),
        "completed": (store, "complete_controller_completion"),
        "released": (IdentityStore, "release_identity_publication"),
    }[point]
    original = getattr(target, method)
    def interrupt(*args, **kwargs):
        value = original(*args, **kwargs)
        if point == "staged":
            assert store.load() == before
            assert not (store.staging_dir / "user-clarifications.md").exists()
        raise Interrupted()
    with monkeypatch.context() as patch:
        patch.setattr(target, method, interrupt)
        with pytest.raises(Interrupted):
            ctrl.apply_human_input_resolution(before["blocked_decision"]["id"],
                expected_state_revision=before["state_revision"], resolution=answer)
    assert identity.identity_history(spec_id="game") == old_history
    restarted = controller(checkpoint_case, executor)
    if point == "staged":
        assert restarted.run(managed_discovery=request).phase == "phase1-tracker"
        current = store.load()
        assert restarted.apply_human_input_resolution(current["blocked_decision"]["id"],
            expected_state_revision=current["state_revision"], resolution=answer)
    result = restarted.run(managed_discovery=request)
    assert result.phase == "phase1-why1", result
    saved = store.load()
    assert saved["last_dispatch"]["post_dispatch_complete"] is True, saved
    assert saved["token_usage"] == 84 and len(executor.calls) == 12
    receipt = (store.staging_dir / "user-clarifications.md").read_text()
    assert receipt.count("## Decision ") == 1 and "Use arrow keys" in receipt
    assert identity.pending_identity_publication(spec_id="game") is None
    ledger = json.loads((root / "specs/game/.echelon/checkpoints.json").read_text())
    assert [row["phase"] for row in ledger["checkpoints"]] == ["phase1-discover", "phase1-synthesizer", "phase1-tracker", "phase1-tracker"]


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_banzai_tracker_uses_existing_sealed_decision_policy(checkpoint_case, provider):
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "banzai"
    store.save(state)
    install_tracker(checkpoint_case)
    executor = TrackerExecutor(provider, clarification=True)
    result = controller(checkpoint_case, executor).run(managed_discovery={**selection(checkpoint_case),
        "through_phase": "phase1-tracker"}, create_managed_discovery=True)
    assert result.phase == "phase1-why1", (result, store.load().get("blocked_decision"))
    saved = store.load()
    assert saved["blocked_decision"]["status"] == "resolved"
    assert saved["blocked_decision"]["automatic_eligible"] is True
    assert saved["blocked_decision"]["resolved_by"] == "COMMANDER"
    assert len(executor.decisions) == 1 and len(executor.calls) == 12
    assert saved["token_usage"] == 89


def test_managed_tracker_human_resume_entry_is_scoped(checkpoint_case):
    ctrl, executor, request = stopped_tracker(checkpoint_case)
    assert ctrl.resume_with_human_input("Use arrow keys")
    result = ctrl.run(managed_discovery=request)
    assert result.phase == "phase1-why1", result
    assert len(executor.calls) == 12


def test_fresh_tracker_cannot_inherit_unexplained_dispatches(prepared):
    prepared[1].increment_phase_dispatch_count("phase1-tracker")
    before = prepared[1].load()
    executor = TrackerExecutor()
    result = controller(prepared, executor).run(managed_discovery={**selection(prepared),
        "through_phase": "phase1-tracker"}, create_managed_discovery=True)
    assert result.summary == "managed_discovery_selection_requires_reconciliation"
    assert prepared[1].load() == before and executor.calls == []


@pytest.mark.parametrize("point", ["accepted", "staged", "routed", "promoted", "context", "completed", "released"])
def test_tracker_stop_restart_preserves_decision_and_charge(checkpoint_case, monkeypatch, point):
    from harness.element_identity_store import IdentityStore
    from tests.unit.test_discovery_turns import Interrupted
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "guided"
    store.save(state)
    install_tracker(checkpoint_case)
    executor = TrackerExecutor(clarification=True)
    ctrl = controller(checkpoint_case, executor)
    request = {**selection(checkpoint_case), "through_phase": "phase1-tracker"}
    target, method = {
        "accepted": (store, "advance_discovery_operation"), "staged": (ctrl, "_prepare_controller_completion"),
        "routed": (store, "advance"), "promoted": (IdentityStore, "apply_identity_publication"),
        "context": (ctrl, "_apply_controller_completion_effect"), "completed": (store, "complete_controller_completion"),
        "released": (IdentityStore, "release_identity_publication"),
    }[point]
    original = getattr(target, method)
    def interrupt(*args, **kwargs):
        value = original(*args, **kwargs)
        if (store.load().get("last_dispatch") or {}).get("phase_id") == "phase1-tracker" or (
                point == "accepted" and kwargs.get("producer") == "tracker" and args[1] == "finish") or (
                point == "staged" and kwargs.get("from_phase") == "phase1-tracker"):
            raise Interrupted()
        return value
    with monkeypatch.context() as patch:
        patch.setattr(target, method, interrupt)
        with pytest.raises(Interrupted):
            ctrl.run(managed_discovery=request, create_managed_discovery=True)
    prior_decision = deepcopy(store.load().get("blocked_decision"))
    result = controller(checkpoint_case, executor).run(managed_discovery=request)
    saved = store.load()
    assert result.phase == "phase1-tracker" and saved["last_dispatch"]["post_dispatch_complete"] is True, result
    assert saved["blocked_decision"]["status"] == "awaiting_human"
    if prior_decision is not None:
        assert saved["blocked_decision"] == prior_decision
    assert saved["token_usage"] == 63 and len(executor.calls) == 9
    assert identity.pending_identity_publication(spec_id="game") is None


def test_tracker_drift_publishes_inference_and_optional_stakeholder(checkpoint_case):
    install_tracker(checkpoint_case)
    executor = TrackerExecutor("claude", intent_kind="II", verdict="DRIFT", stakeholder=True)
    result = controller(checkpoint_case, executor).run(managed_discovery={**selection(checkpoint_case),
        "through_phase": "phase1-tracker"}, create_managed_discovery=True)
    assert result.phase == "phase1-why1", result
    state = checkpoint_case[1].load()
    assert state["last_dispatch"]["verdict"] == "DRIFT" and state["last_dispatch"]["post_dispatch_complete"] is True
    assert "II-000001" in (checkpoint_case[0] / "specs/game/user-intent.md").read_text()
    assert (checkpoint_case[0] / "specs/game/stakeholder-model.md").read_text().startswith("# Stakeholder Model")
    entities = json.loads(checkpoint_case[2].identity_history(spec_id="game").payload)["entities"]
    assert {(row["element_id"], row["revision"]) for row in entities} == {("U-000001", "2"), ("II-000001", "1")}


@pytest.mark.parametrize("failure", ["rejection", "unknown_usage", "missing_receipt"])
def test_tracker_rejection_or_uncertain_receipt_cannot_publish_or_reset(checkpoint_case, monkeypatch, failure):
    from tests.unit.test_discovery_turns import Interrupted
    install_tracker(checkpoint_case)
    root, store, identity, _ = checkpoint_case
    executor = TrackerExecutor(reject=failure == "rejection", unknown_usage=failure == "unknown_usage")
    ctrl = controller(checkpoint_case, executor)
    request = {**selection(checkpoint_case), "through_phase": "phase1-tracker"}
    if failure == "missing_receipt":
        original = store.advance_discovery_operation
        def interrupt(*args, **kwargs):
            result = original(*args, **kwargs)
            if kwargs.get("producer") == "tracker" and args[1] == "finish":
                raise Interrupted()
            return result
        with monkeypatch.context() as patch:
            patch.setattr(store, "advance_discovery_operation", interrupt)
            with pytest.raises(Interrupted):
                ctrl.run(managed_discovery=request, create_managed_discovery=True)
        path, = store.squad_dir.glob("tracker-turns-*.json")
        path.unlink()
    else:
        ctrl.run(managed_discovery=request, create_managed_discovery=True)
    before = store.load()
    calls = len(executor.calls)
    result = ctrl.run(managed_discovery=request)
    assert result.phase == "phase1-tracker" and result.status == "blocked", result
    assert not (root / "specs/game/user-intent.md").exists()
    assert len(executor.calls) == calls and store.load() == before
    assert len(json.loads(identity.identity_history(spec_id="game").payload)["entities"]) == 1
    assert identity.pending_identity_publication(spec_id="game") is None


def test_multiple_clarifications_preserve_full_round_ancestry(checkpoint_case):
    from harness.human_input import AppliedHumanInputResolution
    class TwoQuestions(TrackerExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            response = super().run_inspection_turn(*args, **kwargs)
            payload = self.calls[-1]
            assignment = payload["assignment"]
            if assignment.get("producer") == "tracker" and assignment["step"] == "author" and assignment["editable_revisions"]:
                reply = json.loads(response.stdout)
                if assignment["editable_revisions"][0][1] == "1":
                    reply["routing"] = dict(verdict="STOP_AND_ASK", question="Should lighting stay steady while moving?",
                        recommended_answer="Keep lighting steady", risk_level="low")
                else:
                    reply["artifacts"]["user-intent.md"] = reply["artifacts"]["user-intent.md"].replace(
                        "using arrow keys", "using arrow keys under steady lighting")
                response = replace(response, stdout=json.dumps(reply))
            return response
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "guided"
    store.save(state)
    install_tracker(checkpoint_case)
    executor = TwoQuestions(clarification=True)
    ctrl = controller(checkpoint_case, executor)
    request = {**selection(checkpoint_case), "through_phase": "phase1-tracker"}
    assert ctrl.run(managed_discovery=request, create_managed_discovery=True).phase == "phase1-tracker"
    prior_rows, prior_receipts = {}, {}
    decisions = []
    for answer in ("Use arrow keys", "Keep lighting steady"):
        before = store.load()
        assert before["blocked_decision"]["status"] == "awaiting_human"
        decisions.append(before["blocked_decision"]["id"])
        assert ctrl.apply_human_input_resolution(decisions[-1], expected_state_revision=before["state_revision"],
            resolution=AppliedHumanInputResolution(None, answer, "user"))
        prior_rows.update(deepcopy(before["managed_tracker_rounds"]["rounds"]))
        prior_receipts.update({path: path.read_bytes() for path in store.squad_dir.glob("tracker-*.json")})
        result = ctrl.run(managed_discovery=request)
        assert all(store.load()["managed_tracker_rounds"]["rounds"][key] == row for key, row in prior_rows.items())
        assert all(path.read_bytes() == raw for path, raw in prior_receipts.items())
    assert result.phase == "phase1-why1", result
    saved = store.load()
    assert len(saved["managed_tracker_rounds"]["rounds"]) == 3
    assert len(executor.calls) == 15 and saved["token_usage"] == 105
    text = (store.staging_dir / "user-clarifications.md").read_text()
    assert all(text.count("## Decision " + decision_id) == 1 for decision_id in decisions)
    entities = json.loads(identity.identity_history(spec_id="game").payload)["entities"]
    assert {(row["element_id"], row["revision"]) for row in entities} == {("U-000001", "2"), ("UI-000001", "3")}


def test_tracker_next_round_honors_existing_dispatch_cap(checkpoint_case, monkeypatch):
    from harness import squad
    ctrl, executor, request = stopped_tracker(checkpoint_case)
    assert ctrl.resume_with_human_input("Use arrow keys")
    with monkeypatch.context() as patch:
        patch.setattr(squad, "MAX_PHASE_DISPATCHES", 1)
        result = ctrl.run(managed_discovery=request)
    assert result.summary == "phase_dispatch_limit"
    assert len(executor.calls) == 9 and checkpoint_case[1].load()["token_usage"] == 63


def test_banzai_tracker_without_recommendation_still_requires_human(checkpoint_case):
    class Unrecommended(TrackerExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            response = super().run_inspection_turn(*args, **kwargs)
            assignment = self.calls[-1]["assignment"]
            if assignment.get("producer") == "tracker" and assignment["step"] == "author":
                reply = json.loads(response.stdout)
                reply["routing"].update(recommended_answer=None, risk_level=None)
                return replace(response, stdout=json.dumps(reply))
            return response
    install_tracker(checkpoint_case)
    executor = Unrecommended(clarification=True)
    request = {**selection(checkpoint_case), "through_phase": "phase1-tracker"}
    ctrl = controller(checkpoint_case, executor)
    result = ctrl.run(managed_discovery=request, create_managed_discovery=True)
    state = checkpoint_case[1].load()
    assert result.phase == "phase1-tracker" and result.summary == "human_clarification_required"
    assert state["blocked_decision"]["automatic_eligible"] is False
    assert state["blocked_decision"]["status"] == "awaiting_human"
    assert not executor.decisions and len(executor.calls) == 9
    assert ctrl.run(managed_discovery=request).summary == "human_clarification_required"
    assert checkpoint_case[1].load() == state and len(executor.calls) == 9


def test_initial_tracker_will_not_adopt_unproven_clarifications(checkpoint_case):
    install_tracker(checkpoint_case)
    store = checkpoint_case[1]
    store.staging_dir.mkdir(parents=True, exist_ok=True)
    (store.staging_dir / "feature-policy.md").write_text("Unproven prior policy\n")
    executor = TrackerExecutor()
    result = controller(checkpoint_case, executor).run(managed_discovery={**selection(checkpoint_case),
        "through_phase": "phase1-tracker"}, create_managed_discovery=True)
    assert result.phase == "phase1-tracker" and result.summary == "unproven_tracker_clarification_inputs"
    assert len(executor.calls) == 6 and not (checkpoint_case[0] / "specs/game/user-intent.md").exists()


def test_clarification_source_change_after_staging_cannot_promote(checkpoint_case, monkeypatch):
    from harness.human_input import AppliedHumanInputResolution
    ctrl, executor, request = stopped_tracker(checkpoint_case)
    root, store, identity, _ = checkpoint_case
    before = store.load()
    artifact = root / "specs/game/user-intent.md"
    original_text = artifact.read_bytes()
    history = identity.identity_history(spec_id="game")
    original_prepare = ctrl._prepare_controller_completion
    def changed_source(*args, **kwargs):
        completion = original_prepare(*args, **kwargs)
        artifact.write_text("Unproven replacement\n")
        return completion
    with monkeypatch.context() as patch:
        patch.setattr(ctrl, "_prepare_controller_completion", changed_source)
        assert not ctrl.apply_human_input_resolution(before["blocked_decision"]["id"],
            expected_state_revision=before["state_revision"], resolution=AppliedHumanInputResolution(None, "Use arrow keys", "user"))
    assert not (store.staging_dir / "user-clarifications.md").exists()
    assert identity.identity_history(spec_id="game") == history
    assert len(executor.calls) == 9
    artifact.write_bytes(original_text)
    result = controller(checkpoint_case, executor).run(managed_discovery=request)
    assert result.phase == "phase1-why1", result
    assert len(executor.calls) == 12 and store.load()["token_usage"] == 84


def test_clarification_repair_route_preserves_original_requirements(checkpoint_case):
    class PersistenceQuestion(TrackerExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            response = super().run_inspection_turn(*args, **kwargs)
            assignment = self.calls[-1]["assignment"]
            if assignment.get("producer") == "tracker" and assignment["step"] == "author":
                reply = json.loads(response.stdout)
                reply["artifacts"]["user-intent.md"] += "\nDesign assumption: movement uses a database.\n"
                reply["routing"] = dict(verdict="STOP_AND_ASK", question="Should movement use database persistence?",
                    recommended_answer=None, risk_level=None)
                return replace(response, stdout=json.dumps(reply))
            return response
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "guided"
    store.save(state)
    install_tracker(checkpoint_case)
    executor = PersistenceQuestion(clarification=True)
    request = {**selection(checkpoint_case), "through_phase": "phase1-tracker"}
    ctrl = controller(checkpoint_case, executor)
    assert ctrl.run(managed_discovery=request, create_managed_discovery=True).phase == "phase1-tracker"
    originals = {path: path.read_bytes() for path in (root / "specs/game").glob("*.md")}
    history = identity.identity_history(spec_id="game")
    assert ctrl.resume_with_human_input("No database")
    assert store.load()["feature_policy_reconciliation"]["requires_repair"] is True
    assert all(path.read_bytes() == data for path, data in originals.items())
    assert identity.identity_history(spec_id="game") == history
    result = ctrl.run(managed_discovery=request)
    assert result.phase == "phase1-what" and result.summary == "managed_phase_not_supported"
    assert len(executor.calls) == 9
