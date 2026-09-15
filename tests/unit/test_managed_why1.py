"""WHY1 controller acceptance; external processes only are scripted."""
from dataclasses import replace
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.unit.test_managed_tracker import case, enrolled, turn_prepared, prepared, checkpoint_case, controller, selection, install_tracker, TrackerExecutor
from tests.unit.test_discovery_turns import ScriptedExecutor


class Why1Executor(TrackerExecutor):
    def __init__(self, provider="codex", *, finding=False, why_verdict="PASS"):
        super().__init__(provider)
        self.finding, self.why_verdict = finding, why_verdict

    def exec_agent(self, *args, **kwargs):
        response = super().exec_agent(*args, **kwargs)
        if "Which audience?" in args[1]:
            response.echelon_result["decision"].update(answer_text="Single player", rationale="A reversible initial audience choice.")
        return response

    def run_inspection_turn(self, *args, **kwargs):
        assignment = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])["assignment"]
        if assignment.get("producer") != "why1":
            return super().run_inspection_turn(*args, **kwargs)
        response = ScriptedExecutor.run_inspection_turn(self, *args, **kwargs)
        context = self.calls[-1]["context"]
        if assignment["step"] == "propose":
            fields = dict(new_subjects=[dict(key="audience", kind="ISS", subject="Audience", caption="Audience")]
                if self.finding and "issues.md" not in context["baseline"] else [], revisions=[])
        elif assignment["step"] == "author":
            fields = dict(artifacts={"assumption-review.md": "# Assumption Review — WHY1\n\n## Verdict: PASS\n\n## Summary\nMovement intent is explicit. Camera uncertainty remains tracked by U-000001.\n",
                "issues.md": None, "unknowns.md": context["baseline"]["unknowns.md"]},
                routing=dict(verdict="PASS", question=None, recommended_answer=None, risk_level=None))
            verdict = self.why_verdict
            if verdict == "STOP_AND_ASK" and any("user-clarifications.md" in path and "**Question:** Which audience?" in text
                    for path, text in context["evidence"].items()):
                verdict = "PASS"
            fields["routing"]["verdict"] = verdict
            fields["artifacts"]["assumption-review.md"] = fields["artifacts"]["assumption-review.md"].replace(
                "Verdict: PASS", "Verdict: " + ("PASS" if verdict == "PASS" else "FAIL"))
            if self.finding:
                fields["artifacts"]["issues.md"] = context["baseline"].get("issues.md",
                    "# Issues\n\n### ISS-000001: Audience\nClarify audience.\n")
            if verdict == "STOP_AND_ASK":
                fields["routing"].update(question="Which audience?", recommended_answer="Single player", risk_level="low")
        else:
            fields = dict(verdict="accept", reason="Assumptions were challenged and remaining uncertainty is explicit.",
                assessments=[dict(id=label, verdict="accept", reason="Finding supported by captured evidence.",
                    evidence=[context["citations"][label]]) for label in assignment["assigned_ids"]])
        return replace(response, stdout=json.dumps({**assignment, "action": "final", **fields}))


def install_why1(case):
    install_tracker(case)
    repo = Path(__file__).resolve().parents[2]
    relative_paths = ["subagents/echelon.why1-producer.md", "subagents/echelon.why1-reviewer.md",
        "agents/exploration/templates/sage-assumption-review-template.md", "agents/exploration/templates/sage-issues-template.md"]
    for relative in relative_paths:
        destination = case[0] / ".echelon/prosaic" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((repo / "prosaic" / relative).read_bytes())


@pytest.mark.parametrize("provider", ["codex", "claude"])
@pytest.mark.parametrize("mode", ["guided", "semi", "banzai"])
@pytest.mark.parametrize("checkpoint", [False, True])
def test_managed_why1_reaches_constitution_without_rewriting_upstream(checkpoint_case, provider, mode, checkpoint):
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = mode
    if not checkpoint:
        for key in ("spec_dir", "checkpoint_policy_version", "phase_completion_outcomes"):
            state.pop(key)
    store.save(state)
    install_why1(checkpoint_case)
    executor = Why1Executor(provider)
    result = controller(checkpoint_case, executor).run(managed_discovery={**selection(checkpoint_case),
        "through_phase": "phase1-why1"}, create_managed_discovery=True)
    assert result.phase == "phase1-constitution", result
    assert store.load()["token_usage"] == 84 and len(executor.calls) == 12
    assert not (root / "specs/game/issues.md").exists()
    assert "## Verdict: PASS" in (root / "specs/game/assumption-review.md").read_text()
    entities = json.loads(identity.identity_history(spec_id="game").payload)["entities"]
    assert {(row["element_id"], row["revision"]) for row in entities} == {("U-000001", "2"), ("UI-000001", "1")}
    captured = next(call["context"] for call in executor.calls if call["assignment"].get("producer") == "why1")
    for path, content in captured["baseline"].items():
        assert (root / "specs/game" / path).read_bytes() == content.encode("utf-8")
    saved = store.load()
    assert saved["quality_scores"][-1]["pass"] is True
    assert "completeness" not in saved["quality_scores"][-1]
    assert controller(checkpoint_case, executor).run(managed_discovery={**selection(checkpoint_case),
        "through_phase": "phase1-why1"}).phase == "phase1-constitution"
    assert store.load() == saved and len(executor.calls) == 12


def test_why1_publishes_stable_issue_with_exact_occurrence(checkpoint_case):
    root, store, identity, _ = checkpoint_case
    install_why1(checkpoint_case)
    executor = Why1Executor(finding=True)
    result = controller(checkpoint_case, executor).run(managed_discovery={**selection(checkpoint_case),
        "through_phase": "phase1-why1"}, create_managed_discovery=True)
    assert result.phase == "phase1-constitution", result
    history = json.loads(identity.identity_history(spec_id="game").payload)
    issue, = [row for row in history["entities"] if row["kind"] == "ISS"]
    assert (issue["element_id"], issue["subject"], issue["revision"]) == ("ISS-000001", "Audience", "1")
    occurrence, = history["issue_occurrences"]
    assert occurrence["issue_id"] == "ISS-000001" and occurrence["body"] == "Clarify audience.\n"


@pytest.mark.parametrize("provider,mode", [("codex", "guided"), ("claude", "semi")])
def test_why1_clarification_resumes_same_issue_without_reallocating(checkpoint_case, provider, mode):
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = mode
    store.save(state)
    install_why1(checkpoint_case)
    executor = Why1Executor(provider, finding=True, why_verdict="STOP_AND_ASK")
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    result = controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True)
    assert result.phase == "phase1-why1" and store.load()["blocked_decision"]["question"] == "Which audience?", result
    previous = store.load()["managed_why1_rounds"]
    assert controller(checkpoint_case, executor).resume_with_human_input("Single player")
    result = controller(checkpoint_case, executor).run(managed_discovery=selected)
    assert result.phase == "phase1-constitution", result
    saved = store.load()
    assert len(saved["managed_why1_rounds"]["rounds"]) == 2
    assert saved["managed_why1_rounds"]["rounds"][previous["active"]] == previous["rounds"][previous["active"]]
    assert saved["token_usage"] == 105 and len(executor.calls) == 15
    history = json.loads(identity.identity_history(spec_id="game").payload)
    assert len(history["issue_occurrences"]) == 1


@pytest.mark.parametrize("verdict,iteration,destination", [
    ("FAIL", 0, "phase1-discover"), ("BLOCKED", 0, "phase1-discover"),
    ("FAIL", 3, "phase1-constitution")])
def test_why1_failure_uses_native_iteration_route_without_running_repair(checkpoint_case, verdict, iteration, destination):
    root, store, identity, _ = checkpoint_case
    install_why1(checkpoint_case)
    state = store.load()
    state.update(iteration=iteration, max_iterations=3)
    store.save(state)
    executor = Why1Executor(finding=True, why_verdict=verdict)
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    result = controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True)
    assert result.phase == destination, result
    assert store.load()["quality_scores"][-1]["pass"] is False
    assert store.load()["iteration"] == (iteration + 1 if destination == "phase1-discover" else iteration)
    assert "## Verdict: FAIL" in (root / "specs/game/assumption-review.md").read_text()
    assert len(executor.calls) == 12
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == destination
    assert len(executor.calls) == 12


def test_why1_captures_existing_reasoning_context(checkpoint_case):
    root, store, identity, _ = checkpoint_case
    install_why1(checkpoint_case)
    journal = store.squad_dir / "reasoning-journal.jsonl"
    raw = '{"phase_id":"phase1-discover","reasoning":"Camera choice requires review."}\n'
    journal.write_text(raw)
    executor = Why1Executor()
    result = controller(checkpoint_case, executor).run(managed_discovery={**selection(checkpoint_case),
        "through_phase": "phase1-why1"}, create_managed_discovery=True)
    assert result.phase == "phase1-constitution", result
    context = next(call["context"] for call in executor.calls if call["assignment"].get("producer") == "why1")
    assert context["evidence"][journal.relative_to(root).as_posix()] == raw
    assert journal.read_text() == raw


@pytest.mark.parametrize("point", ["accepted", "staged", "routed", "promoted", "context", "completed", "released"])
def test_why1_stop_restart_preserves_decision_ids_and_usage(checkpoint_case, monkeypatch, point):
    from harness.element_identity_store import IdentityStore
    from tests.unit.test_discovery_turns import Interrupted
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "guided"
    store.save(state)
    install_why1(checkpoint_case)
    executor = Why1Executor(finding=True, why_verdict="STOP_AND_ASK")
    ctrl = controller(checkpoint_case, executor)
    request = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    target, method = {
        "accepted": (store, "advance_discovery_operation"), "staged": (ctrl, "_prepare_controller_completion"),
        "routed": (store, "advance"), "promoted": (IdentityStore, "apply_identity_publication"),
        "context": (ctrl, "_apply_controller_completion_effect"), "completed": (store, "complete_controller_completion"),
        "released": (IdentityStore, "release_identity_publication"),
    }[point]
    original = getattr(target, method)
    def interrupt(*args, **kwargs):
        value = original(*args, **kwargs)
        if (store.load().get("last_dispatch") or {}).get("phase_id") == "phase1-why1" or (
                point == "accepted" and kwargs.get("producer") == "why1" and args[1] == "finish") or (
                point == "staged" and kwargs.get("from_phase") == "phase1-why1"):
            raise Interrupted()
        return value
    with monkeypatch.context() as patch:
        patch.setattr(target, method, interrupt)
        with pytest.raises(Interrupted):
            ctrl.run(managed_discovery=request, create_managed_discovery=True)
    decision = deepcopy(store.load().get("blocked_decision"))
    result = controller(checkpoint_case, executor).run(managed_discovery=request)
    saved = store.load()
    assert result.phase == "phase1-why1" and saved["last_dispatch"]["post_dispatch_complete"] is True, result
    assert saved["blocked_decision"]["status"] == "awaiting_human"
    if decision is not None:
        assert saved["blocked_decision"] == decision
    assert saved["token_usage"] == 84 and len(executor.calls) == 12
    assert len(json.loads(identity.identity_history(spec_id="game").payload)["issue_occurrences"]) == 1
    assert identity.pending_identity_publication(spec_id="game") is None


@pytest.mark.parametrize("point", ["staged", "resolved", "promoted", "context", "completed", "released"])
def test_why1_clarification_restart_is_exact(checkpoint_case, monkeypatch, point):
    from harness.human_input import AppliedHumanInputResolution
    from harness.element_identity_store import IdentityStore
    from tests.unit.test_discovery_turns import Interrupted
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "guided"
    store.save(state)
    install_why1(checkpoint_case)
    executor = Why1Executor(finding=True, why_verdict="STOP_AND_ASK")
    ctrl = controller(checkpoint_case, executor)
    request = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    assert ctrl.run(managed_discovery=request, create_managed_discovery=True).phase == "phase1-why1"
    before = store.load()
    history = identity.identity_history(spec_id="game")
    answer = AppliedHumanInputResolution(None, "Single player", "user")
    target, method = {
        "staged": (ctrl, "_prepare_controller_completion"), "resolved": (store, "apply_human_input_state_resolution"),
        "promoted": (IdentityStore, "apply_identity_publication"), "context": (ctrl, "_apply_controller_completion_effect"),
        "completed": (store, "complete_controller_completion"), "released": (IdentityStore, "release_identity_publication"),
    }[point]
    original = getattr(target, method)
    def interrupt(*args, **kwargs):
        value = original(*args, **kwargs)
        raise Interrupted()
    with monkeypatch.context() as patch:
        patch.setattr(target, method, interrupt)
        with pytest.raises(Interrupted):
            ctrl.apply_human_input_resolution(before["blocked_decision"]["id"],
                expected_state_revision=before["state_revision"], resolution=answer)
    assert identity.identity_history(spec_id="game") == history
    restarted = controller(checkpoint_case, executor)
    if point == "staged":
        assert restarted.run(managed_discovery=request).phase == "phase1-why1"
        assert restarted.resume_with_human_input("Single player")
    result = restarted.run(managed_discovery=request)
    assert result.phase == "phase1-constitution", result
    assert store.load()["token_usage"] == 105 and len(executor.calls) == 15
    assert (store.staging_dir / "user-clarifications.md").read_text().count("## Decision ") == 1
    assert identity.pending_identity_publication(spec_id="game") is None


@pytest.mark.parametrize("provider", ["codex", "claude"])
@pytest.mark.parametrize("recommended", [False, True])
def test_why1_banzai_preserves_existing_answer_eligibility(checkpoint_case, provider, recommended):
    class Recommendation(Why1Executor):
        def run_inspection_turn(self, *args, **kwargs):
            response = super().run_inspection_turn(*args, **kwargs)
            assignment = self.calls[-1]["assignment"]
            if not recommended and assignment.get("producer") == "why1" and assignment["step"] == "author":
                reply = json.loads(response.stdout)
                reply["routing"].update(recommended_answer=None, risk_level=None)
                return replace(response, stdout=json.dumps(reply))
            return response
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "banzai"
    store.save(state)
    install_why1(checkpoint_case)
    executor = Recommendation(provider, why_verdict="STOP_AND_ASK")
    request = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    result = controller(checkpoint_case, executor).run(managed_discovery=request, create_managed_discovery=True)
    saved = store.load()
    assert saved["blocked_decision"]["automatic_eligible"] is recommended, result
    assert result.phase == ("phase1-constitution" if recommended else "phase1-why1"), result
    assert saved["blocked_decision"]["status"] == ("resolved" if recommended else "awaiting_human")
    assert len(executor.decisions) == (1 if recommended else 0)
    assert saved["token_usage"] == (110 if recommended else 84)


def test_why1_retains_tracker_and_multiple_why1_clarifications(checkpoint_case):
    class TwoQuestions(Why1Executor):
        def run_inspection_turn(self, *args, **kwargs):
            response = super().run_inspection_turn(*args, **kwargs)
            assignment = self.calls[-1]["assignment"]
            if assignment.get("producer") == "why1" and assignment["step"] == "author":
                reply = json.loads(response.stdout)
                evidence = self.calls[-1]["context"]["evidence"]
                receipt = next((text for path, text in evidence.items() if path.endswith("user-clarifications.md")), "")
                if "**Question:** Which audience?" in receipt and "**Question:** Which lighting style?" not in receipt:
                    reply["routing"] = dict(verdict="STOP_AND_ASK", question="Which lighting style?", recommended_answer=None, risk_level=None)
                    reply["artifacts"]["assumption-review.md"] = reply["artifacts"]["assumption-review.md"].replace("Verdict: PASS", "Verdict: FAIL")
                    return replace(response, stdout=json.dumps(reply))
            return response
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "guided"
    store.save(state)
    install_why1(checkpoint_case)
    executor = TwoQuestions(finding=True, why_verdict="STOP_AND_ASK")
    executor.clarification = True
    request = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    ctrl = controller(checkpoint_case, executor)
    assert ctrl.run(managed_discovery=request, create_managed_discovery=True).phase == "phase1-tracker"
    for question, answer, phase in (("Which movement controls?", "Use arrow keys", "phase1-why1"),
            ("Which audience?", "Single player", "phase1-why1"),
            ("Which lighting style?", "Daylight", "phase1-constitution")):
        assert store.load()["blocked_decision"]["question"] == question
        assert ctrl.resume_with_human_input(answer)
        result = ctrl.run(managed_discovery=request)
        assert result.phase == phase, result
    saved = store.load()
    assert len(saved["managed_tracker_rounds"]["rounds"]) == 2
    assert len(saved["managed_why1_rounds"]["rounds"]) == 3
    assert saved["token_usage"] == 147 and len(executor.calls) == 21
    assert (store.staging_dir / "user-clarifications.md").read_text().count("## Decision ") == 3
    history = json.loads(identity.identity_history(spec_id="game").payload)
    assert len(history["issue_occurrences"]) == 1


@pytest.mark.parametrize("failure", ["rejection", "unknown_usage", "missing_receipt", "source_changed"])
def test_why1_uncertain_or_changed_candidate_cannot_publish(checkpoint_case, monkeypatch, failure):
    from tests.unit.test_discovery_turns import Interrupted
    class FailedReview(Why1Executor):
        def run_inspection_turn(self, *args, **kwargs):
            response = super().run_inspection_turn(*args, **kwargs)
            assignment = self.calls[-1]["assignment"]
            if assignment.get("producer") != "why1":
                return response
            if failure == "unknown_usage":
                return replace(response, token_usage=None)
            if failure == "source_changed" and assignment["step"] == "author":
                (checkpoint_case[0] / "specs/game/assumptions.md").write_text("Changed upstream source.\n")
            if failure == "rejection" and assignment["step"] == "review":
                reply = json.loads(response.stdout)
                reply.update(verdict="reject", reason="Finding unsupported by evidence.")
                for assessment in reply["assessments"]:
                    assessment["verdict"] = "reject"
                return replace(response, stdout=json.dumps(reply))
            return response
    root, store, identity, _ = checkpoint_case
    install_why1(checkpoint_case)
    executor = FailedReview(finding=True)
    ctrl = controller(checkpoint_case, executor)
    request = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    if failure == "missing_receipt":
        original = store.advance_discovery_operation
        def interrupt(*args, **kwargs):
            value = original(*args, **kwargs)
            if kwargs.get("producer") == "why1" and args[1] == "finish":
                raise Interrupted()
            return value
        with monkeypatch.context() as patch:
            patch.setattr(store, "advance_discovery_operation", interrupt)
            with pytest.raises(Interrupted):
                ctrl.run(managed_discovery=request, create_managed_discovery=True)
        path, = store.squad_dir.glob("why1-turns-*.json")
        path.unlink()
    else:
        ctrl.run(managed_discovery=request, create_managed_discovery=True)
    before, calls = store.load(), len(executor.calls)
    result = ctrl.run(managed_discovery=request)
    assert result.phase == "phase1-why1" and result.status == "blocked", result
    assert not (root / "specs/game/assumption-review.md").exists()
    assert not (root / "specs/game/issues.md").exists()
    assert len(executor.calls) == calls and store.load() == before
    assert identity.lookup(spec_id="game", element_id="ISS-000001") is None
    assert identity.pending_identity_publication(spec_id="game") is None


def test_why1_new_round_keeps_existing_dispatch_cap(checkpoint_case):
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "guided"
    store.save(state)
    install_why1(checkpoint_case)
    executor = Why1Executor(why_verdict="STOP_AND_ASK")
    ctrl = controller(checkpoint_case, executor)
    request = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    assert ctrl.run(managed_discovery=request, create_managed_discovery=True).phase == "phase1-why1"
    assert ctrl.resume_with_human_input("Single player")
    # WHY1 is iterative: its native limit is max_iterations + the initial pass,
    # not Tracker's MAX_PHASE_DISPATCHES. Zero additional iterations gives one.
    restarted = type(ctrl)(executor, store, ctrl._graph, ctrl._ext_dir, root,
        max_iterations=0, squad_dir=store.squad_dir)
    result = restarted.run(managed_discovery=request)
    assert result.summary == "phase_dispatch_limit", result
    assert len(executor.calls) == 12 and store.load()["token_usage"] == 84


def test_why1_new_unknown_appends_without_rewriting_old_evidence(checkpoint_case):
    class NewUnknown(Why1Executor):
        def run_inspection_turn(self, *args, **kwargs):
            response = super().run_inspection_turn(*args, **kwargs)
            assignment = self.calls[-1]["assignment"]
            if assignment.get("producer") == "why1":
                reply = json.loads(response.stdout)
                if assignment["step"] == "propose":
                    reply["new_subjects"] = [dict(key="audience", kind="U", subject="Audience uncertainty", caption="Audience scope")]
                elif assignment["step"] == "author":
                    label, = assignment["assigned_ids"]
                    reply["artifacts"]["unknowns.md"] += f"### {label}: Audience scope\nInvestigate intended player count.\n"
                return replace(response, stdout=json.dumps(reply))
            return response
    root, store, identity, _ = checkpoint_case
    install_why1(checkpoint_case)
    executor = NewUnknown()
    result = controller(checkpoint_case, executor).run(managed_discovery={**selection(checkpoint_case),
        "through_phase": "phase1-why1"}, create_managed_discovery=True)
    assert result.phase == "phase1-constitution", result
    context = next(call["context"] for call in executor.calls if call["assignment"].get("producer") == "why1")
    assert (root / "specs/game/unknowns.md").read_bytes().startswith(context["baseline"]["unknowns.md"].encode("utf-8"))
    assert identity.lookup(spec_id="game", element_id="U-000001")["revision"] == "2"
    assert identity.lookup(spec_id="game", element_id="U-000002")["subject"] == "Audience uncertainty"


def test_why1_clarification_rejects_changed_reports_and_forged_bindings(checkpoint_case):
    from harness.discovery_completion import decode_binding
    from harness.element_identity_publication import decode_publication_request, encode_publication_request
    from harness.human_input import AppliedHumanInputResolution, HumanInputPolicyError
    from harness.squad_completion import CompletionError
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "guided"
    store.save(state)
    install_why1(checkpoint_case)
    executor = Why1Executor(finding=True, why_verdict="STOP_AND_ASK")
    ctrl = controller(checkpoint_case, executor)
    request = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    assert ctrl.run(managed_discovery=request, create_managed_discovery=True).phase == "phase1-why1"
    before = store.load()
    history = identity.identity_history(spec_id="game")
    decision = before["blocked_decision"]
    answer = AppliedHumanInputResolution(None, "Single player", "user")
    for decision_id, revision in (("dec-" + "0" * 32, before["state_revision"]), (decision["id"], before["state_revision"] - 1)):
        with pytest.raises(HumanInputPolicyError):
            ctrl.apply_human_input_resolution(decision_id, expected_state_revision=revision, resolution=answer)
    for path in (root / "specs/game/assumption-review.md", root / "specs/game/issues.md"):
        original = path.read_bytes()
        path.write_text("Unproven replacement\n")
        with pytest.raises((HumanInputPolicyError, ValueError)):
            ctrl.apply_human_input_resolution(decision["id"], expected_state_revision=before["state_revision"], resolution=answer)
        path.write_bytes(original)
        assert store.load() == before and identity.identity_history(spec_id="game") == history
    # As with Tracker, a released completion is the retained authority. A
    # damaged process journal cannot replace that accepted candidate or alter
    # the sealed question/answer. Pre-release missing journals are tested above.
    parent_id = "discovery-completion-" + before["last_dispatch"]["dispatch_id"]
    parent = identity.identity_publication(spec_id="game", operation_id=parent_id)
    turns, = store.squad_dir.glob("why1-turns-*.json")
    original_turns = turns.read_bytes()
    turns.write_text("Unproven replacement\n")
    assert ctrl.resume_with_human_input("Single player")
    assert identity.identity_publication(spec_id="game", operation_id=parent_id) == parent
    turns.write_bytes(original_turns)
    resolved = store.load()
    assert resolved["blocked_decision"]["question"] == "Which audience?"
    assert resolved["blocked_decision"]["answer_text"] == "Single player"
    retained = identity.identity_publication(spec_id="game", operation_id="discovery-completion-" + resolved["last_human_input_completion"]["completion_id"])
    publication_request = decode_publication_request(retained["request"])
    recovery = json.loads(publication_request.recovery_payload)
    publication = json.loads(retained["completion_payload"])["proof"]["intent"]["publication"]
    assert decode_binding(publication, state=resolved).producer == "why1"
    for damage in ("producer", "source", "answer", "operation"):
        changed = deepcopy(recovery)
        if damage == "producer": changed["producer"] = "tracker"
        elif damage == "source": changed["source_completion"]["dispatch_id"] = "0" * 32
        elif damage == "answer": changed["resolution"]["answer_text"] = "Different answer"
        else: changed["operation"] = resolved["managed_tracker_rounds"]["rounds"][resolved["managed_tracker_rounds"]["active"]]["operation"]
        altered = replace(publication_request, recovery_payload=json.dumps(changed, sort_keys=True, separators=(",", ":")))
        value = deepcopy(publication)
        value["managed_discovery"]["request"] = encode_publication_request(altered)
        with pytest.raises(CompletionError):
            decode_binding(value, state=resolved)
    assert len(executor.calls) == 12 and identity.identity_history(spec_id="game") == history
