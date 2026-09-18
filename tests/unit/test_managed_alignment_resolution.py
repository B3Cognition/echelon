"""Alignment answers retain the question, native resolver and publication proof."""
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.unit.test_managed_alignment_question import (
    case, enrolled, turn_prepared, prepared, checkpoint_case, question,
    assert_question_publication, assert_question_handoff, complete_strategy, assert_reviewed_alignment,
)


@pytest.mark.parametrize("mode,resolver,status", [
    ("guided", "user", "awaiting_human"), ("semi", "user", "awaiting_human"),
    ("banzai", "COMMANDER", "resolving"),
])
def test_alignment_answer_retains_native_question_and_resolver(checkpoint_case, mode, resolver, status):
    from harness import discovery_assessment as assessment
    from harness.blocked_decision import build_blocked_decision_v3
    from harness.human_input import AppliedHumanInputResolution
    from harness.phase_graph import load_workspace_phase_graph
    from harness.squad_state import build_human_input_resolution_postimage
    from tests.unit.test_managed_checkpoint_assess import install_commander
    root = checkpoint_case[0]
    install_commander(root)
    registry = load_workspace_phase_graph(root)[0].human_input_policy_registry()
    request = registry.prepare(source_kind="provider_escalation", producer_id="phase2-tracker-alignment",
        phase_id="phase2-tracker-alignment", reason_code="human_clarification_required",
        question="Which movement controls?", recommended_answer="Use arrow keys", risk_level="low",
        source_state_revision=12)
    decision = build_blocked_decision_v3(prepared=request, decision_id="dec-alignment-answer", status=status,
        autonomy_mode=mode, attempts=1 if resolver == "COMMANDER" else 0,
        created_at="2026-09-18T00:00:00+00:00")
    before = dict(phase="phase2-tracker-alignment", autonomy_mode=mode, blocked_decision=decision)
    answer = AppliedHumanInputResolution(None, "Use WASD", resolver,
        rationale="WASD fits the accepted keyboard scope.", confidence="high")
    resolved = build_human_input_resolution_postimage(decision, answer, resolved_at="2026-09-18T01:00:00+00:00")
    check = getattr(assessment, "require_alignment_answer", None)
    assert callable(check), "Alignment answers need exact native question and resolver validation"
    saved = deepcopy(before)
    check(root, before, resolved, question())
    for key, value in (("question", "Different question"), ("source_phase", "phase1-why2"),
            ("recommended_answer", "Use WASD"), ("risk_level", "high"),
            ("automatic_eligible", not decision["automatic_eligible"]),
            ("resolved_by", "COMMANDER" if resolver == "user" else "user"), ("attempts", False)):
        changed = deepcopy(resolved)
        changed[key] = value
        with pytest.raises(ValueError): check(root, before, changed, question())
    assert before == saved


class CommanderAnswerExecutor:
    """Use the same constrained COMMANDER boundary with a free-text judgment."""
    supports_inspection_turn = True
    constrained_execution_configuration_id = "inspection-v1"

    def __init__(self, provider):
        from tests.unit.test_managed_commander import CommanderExecutor
        self._delegate = CommanderExecutor(provider)
        self.cli = self.provider_id = provider
        self.calls = self._delegate.calls

    def run_inspection_turn(self, *args, **kwargs):
        import yaml
        result = self._delegate.run_inspection_turn(*args, **kwargs)
        assert "Which movement controls?" in self.calls[-1]
        body = yaml.safe_load(result.stdout)
        body["echelon_result"]["decision"].update(selected_option_id=None, answer_text="Use WASD",
            rationale="WASD fits the accepted keyboard scope.", confidence="high")
        return replace(result, stdout=yaml.safe_dump(body, sort_keys=False))


def retain_commander_answer(case, provider):
    from harness.discovery_assessment import require_alignment_question_parent
    from harness.discovery_producer import SOURCE_FIELDS
    from harness.managed_commander import run_commander_turn
    from tests.unit.test_discovery_completion import controller
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    executor = CommanderAnswerExecutor(provider)
    ctrl = controller(case, executor)
    policy = ctrl._policy_for_human_input_decision(before["blocked_decision"])
    def check_inputs():
        current = store.load()
        require_alignment_question_parent(root, store.squad_dir, current,
            {key: current["last_dispatch"][key] for key in SOURCE_FIELDS})
    result = run_commander_turn(ctrl, before, policy, check_inputs=check_inputs)
    assert result.resolution is not None, result.reason
    assert result.resolution.resolved_by == "COMMANDER" and result.resolution.answer_text == "Use WASD"
    assert result.token_usage == 7 and len(executor.calls) == 1
    claimed = store.load()
    assert claimed["blocked_decision"]["status"] == "resolving" and claimed["blocked_decision"]["attempts"] == 1
    assert claimed["blocked_decision"]["answer_text"] is None
    assert claimed["token_usage"] == before["token_usage"]
    assert run_commander_turn(ctrl, claimed, policy, check_inputs=check_inputs) == result
    assert store.load() == claimed and len(executor.calls) == 1
    assert identity.identity_history(spec_id="game") == history


def assert_answer_publication(case, *, resolver="user"):
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    from harness.discovery_completion import decode_binding
    from harness.human_input import AppliedHumanInputResolution
    from harness.squad_state import build_human_input_resolution_postimage
    from harness.tracker_clarification import prepare
    from tests.unit.test_managed_alignment_publication import envelope
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    def documents():
        return {p.relative_to(root).as_posix(): p.read_bytes()
            for tree in (root / "specs/game", store.staging_dir) for p in tree.rglob("*") if p.is_file()}
    originals = documents()
    answer = AppliedHumanInputResolution(None, "Use WASD", resolver,
        rationale="WASD fits the accepted keyboard scope.", confidence="high")
    resolved = build_human_input_resolution_postimage(before["blocked_decision"], answer,
        resolved_at="2026-09-18T01:00:00+00:00")
    with PhaseAExecutionLock.acquire(root, "test-alignment-answer"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-alignment-answer"):
            publication, request, candidate = prepare(root, store, state=before, resolved=resolved,
                completion_id=uuid4().hex, producer="alignment")
    package = SimpleNamespace(publication=publication, request=request, candidate=candidate)
    binding = decode_binding(envelope(package), state=before)
    assert binding.recovery["version"] == 40 and binding.clarification
    assert binding.recovery["resolution"] == resolved
    assert binding.candidate["route"] == "phase2-tracker-alignment"
    assert request.operations == () and binding.candidate["history"] == binding.source["history"]
    assert {op.target for op in binding.sources.publication.operations} == {
        "runs/first/staging/user-clarifications.md", "runs/first/staging/feature-policy.json",
        "runs/first/staging/feature-policy.md", "specs/game/feature-policy-reconciliation.md",
        "specs/game/spec-artifact-graph.json"}
    assert store.load() == before and identity.identity_history(spec_id="game") == history
    assert identity.pending_identity_publication(spec_id="game") is None
    if resolver == "COMMANDER":
        # An otherwise valid answer with a different judgment cannot borrow
        # the accepted response receipt, even for the exact same question.
        substituted = replace(answer, answer_text="Use arrow keys")
        forged = build_human_input_resolution_postimage(before["blocked_decision"], substituted,
            resolved_at=resolved["resolved_at"])
        with PhaseAExecutionLock.acquire(root, "test-alignment-answer-forgery"):
            with SpecRunExecutionLock.acquire(store.squad_dir, "test-alignment-answer-forgery"):
                with pytest.raises(ValueError, match="commander_resolution_receipt_changed"):
                    prepare(root, store, state=before, resolved=forged,
                        completion_id=uuid4().hex, producer="alignment")
    from harness.discovery_completion import _json, CompletionError
    for damage in ("version", "source", "question", "answer", "resolver", "before", "commander", "writes"):
        recovery = json.loads(request.recovery_payload)
        if damage == "version": recovery["version"] = 18
        elif damage == "source": recovery["source_completion"]["dispatch_id"] = "0" * 32
        elif damage == "question": recovery["resolution"]["question"] = "Different question"
        elif damage == "answer": recovery["resolution"]["answer_text"] = "Changed answer"
        elif damage == "resolver": recovery["resolution"]["resolved_by"] = "controller"
        elif damage == "before": recovery["before"]["iteration"] += 1
        elif damage == "commander": recovery["commander_receipt"] = {} if resolver == "user" else None
        else:
            candidate = json.loads(recovery["candidate_inputs"])
            candidate["artifacts"]["specs/game/spec.md"] = "Unauthorized requirements"
            recovery["candidate_inputs"] = _json(candidate)
        with pytest.raises(CompletionError):
            decode_binding(envelope(package, replace(request, recovery_payload=_json(recovery))), state=before)
    assert (binding.recovery["commander_receipt"] is None) == (resolver == "user")
    if resolver == "COMMANDER": assert binding.recovery["commander_receipt"]["token_usage"] == 7
    with pytest.raises(CompletionError):
        decode_binding(envelope(package), state={**before, "blocked_decision": resolved})
    # Native application is a subsequent checkpoint; detached preparation
    # cannot grant resolution authority or dispatch through the legacy route.
    from harness.human_input import HumanInputPolicyError
    from tests.unit.test_discovery_completion import controller
    from tests.unit.test_managed_alignment_execution import AlignmentExecutor
    executor = AlignmentExecutor("codex")
    with pytest.raises(HumanInputPolicyError): controller(case, executor).resume_with_human_input("Use WASD")
    with pytest.raises(HumanInputPolicyError): controller(case, executor).resume_pending_human_input()
    assert not executor.calls and store.load() == before and documents() == originals
    return package


def assert_answer_source_refusals(case):
    from harness.discovery_assessment import require_alignment_question_parent
    from harness.discovery_completion import CompletionError
    from harness.discovery_producer import SOURCE_FIELDS
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    source = {key: before["last_dispatch"][key] for key in SOURCE_FIELDS}
    for damage in ("phase", "status", "cancelled", "unfinished", "pending", "source", "question", "typed_budget"):
        state, selected = deepcopy(before), dict(source)
        if damage == "phase": state["phase"] = "phase3-specialists"
        elif damage == "status": state["status"] = "running"
        elif damage == "cancelled": state["cancel_requested"] = True
        elif damage == "unfinished": state["last_dispatch"]["post_dispatch_complete"] = False
        elif damage == "pending": state["pending_controller_completion"] = {}
        elif damage == "source": selected["completion_receipts_sha256"] = "0" * 64
        elif damage == "question": state["blocked_decision"]["question"] = "Forged question"
        else: state["iteration"] = float(before["iteration"])
        with pytest.raises((ValueError, CompletionError)):
            require_alignment_question_parent(root, store.squad_dir, state, selected)
    assert store.load() == before and identity.identity_history(spec_id="game") == history


@pytest.mark.parametrize("provider,mode", [("codex", "guided"), ("claude", "banzai")])
def test_alignment_answer_prepares_without_publishing(checkpoint_case, provider, mode):
    complete_strategy(checkpoint_case, provider, mode, mode == "banzai", "warn" if mode == "banzai" else "disabled")
    assert_reviewed_alignment(checkpoint_case, provider, routing=question())
    assert_question_handoff(checkpoint_case, assert_question_publication(checkpoint_case, provider), provider)
    assert_answer_source_refusals(checkpoint_case)
    if mode == "banzai": retain_commander_answer(checkpoint_case, provider)
    package = assert_answer_publication(checkpoint_case, resolver="COMMANDER" if mode == "banzai" else "user")
    package.publication.discard()
