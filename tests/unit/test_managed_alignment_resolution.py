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


@pytest.mark.parametrize("damage", ["integer_as_float", "boolean_as_integer"])
def test_native_alignment_effect_guard_rejects_equal_valued_type_changes(tmp_path, monkeypatch, damage):
    """Shape-only CAS guard: proof admission is stubbed and persistence forbidden."""
    from contextlib import nullcontext
    from pathlib import Path
    from harness import squad_state, discovery_completion
    from harness.blocked_decision import build_blocked_decision_v3
    from harness.human_input import AppliedHumanInputResolution
    from harness.phase_graph import PhaseGraph
    registry = PhaseGraph(Path(__file__).resolve().parents[2] / "runtime/workflow/definition.yaml").human_input_policy_registry()
    phase = "phase2-tracker-alignment"
    request = registry.prepare(source_kind="provider_escalation", producer_id=phase, phase_id=phase,
        reason_code="human_clarification_required", question="Which movement controls?",
        recommended_answer="Use arrow keys", risk_level="low", source_state_revision=1)
    decision = build_blocked_decision_v3(prepared=request, decision_id="dec-type-check",
        status="awaiting_human", autonomy_mode="guided", created_at="2026-09-18T00:00:00+00:00")
    before = dict(phase=phase, status="blocked", state_revision=2, token_usage=0, autonomy_mode="guided")
    store = squad_state.SquadStateStore(tmp_path / "run")
    store._replace_human_input_decision_unlocked(before, decision)
    answer = AppliedHumanInputResolution(None, "Use WASD", "user")
    resolved_at = "2026-09-18T01:00:00+00:00"
    resolved = squad_state.build_human_input_resolution_postimage(decision, answer, resolved_at=resolved_at)
    effects = dict(status="running", phase=phase, feature_policy={"schema_version": 1},
        feature_policy_reconciliation={"requires_repair": False})
    changed = deepcopy(effects)
    if damage == "integer_as_float": changed["feature_policy"]["schema_version"] = 1.0
    else: changed["feature_policy_reconciliation"]["requires_repair"] = 0
    assert changed == effects  # Python equality is insufficient for the bound JSON proof.
    binding = SimpleNamespace(resolution_publication=True, policy_resolution=False,
        recovery=dict(version=41, resolution=resolved, commander_receipt=None,
            effects=dict(state_updates=effects, state_removals=[])))
    marker = dict(origin="resolution", step="awaiting_publication", completion_id="a" * 32)
    intent = dict(route=dict(kind="resolution", decision_id=decision["id"], from_phase=phase, to_phase=phase),
        publication=dict(managed_discovery={}, marker={}))
    monkeypatch.setattr(squad_state, "_validate_prepared_controller_completion",
        lambda prepared: (marker, intent, {}, "", "bound"))
    monkeypatch.setattr(discovery_completion, "decode_binding", lambda *args, **kwargs: binding)
    monkeypatch.setattr(store, "_lock", lambda **kwargs: nullcontext())
    monkeypatch.setattr(store, "_load_unlocked", lambda: deepcopy(before))
    commits = []
    def forbidden_commit(old, desired):
        commits.append(desired)
        raise AssertionError("effects reached intercepted persistence")
    monkeypatch.setattr(store, "_commit_human_input_state_unlocked", forbidden_commit)
    with pytest.raises(squad_state.StateAdvanceError, match="native.*effects changed"):
        store.apply_human_input_state_resolution(decision["id"], expected_state_revision=2,
            resolution=answer, state_updates=changed, state_removals=(), prepared_completion=object(),
            resolved_at=resolved_at, resolved_decision_postimage=resolved)
    assert not commits
    # The same transaction with correctly typed effects must reach the native
    # persistence boundary; this guard must not merely reject every v41 answer.
    with pytest.raises(AssertionError, match="effects reached intercepted persistence"):
        store.apply_human_input_state_resolution(decision["id"], expected_state_revision=2,
            resolution=answer, state_updates=effects, state_removals=(), prepared_completion=object(),
            resolved_at=resolved_at, resolved_decision_postimage=resolved)
    assert len(commits) == 1 and commits[0]["blocked_decision"] == resolved


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
    from harness.element_identity_publication import encode_publication_request
    from harness.squad_state import StateAdvanceError
    from tests.unit.test_discovery_completion import controller
    ctrl = controller(case, CommanderAnswerExecutor("claude" if resolver == "COMMANDER" else "codex"))
    with pytest.raises(StateAdvanceError, match="controller completion preparation failed"):
        ctrl._prepare_controller_completion(from_phase=before["phase"], to_phase=before["phase"],
            snapshot=store.capture_routing_snapshot(expected_phase=before["phase"]),
            manual_phase_run=False, conditional_skip=False, record_completion=True,
            publication_marker=publication.marker.to_dict(), origin="resolution",
            resolution_decision_id=resolved["id"], completion_id=binding.recovery["completion_id"],
            managed_discovery_request=encode_publication_request(request))
    assert store.load() == before and documents() == originals
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


def assert_answer_application(case, provider, *, commander=False):
    """Exercise the public answer API and durable completion, without an author."""
    from harness.discovery_completion import authenticate
    from harness.squad_completion import load_prepared_controller_completion
    from harness.squad_publication import PreparedSquadPublication
    from harness.element_identity_store import IdentityStore
    from tests.unit.test_discovery_completion import controller, drain
    from tests.unit.test_managed_alignment_question import Interrupted
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    executor = CommanderAnswerExecutor(provider)
    ctrl = controller(case, executor)
    def interrupted(*args, **kwargs):
        raise Interrupted()
    apply_answer = store.apply_human_input_state_resolution
    def checked_apply(*args, **kwargs):
        from harness.squad_state import StateAdvanceError
        unchanged = store.load()
        for damage in ("charge", "effects", "removals"):
            changed = dict(kwargs)
            if damage == "charge": changed["token_usage_delta"] += 1
            elif damage == "effects": changed["state_updates"] = {**kwargs["state_updates"], "iteration": 77}
            else: changed["state_removals"] = {*kwargs["state_removals"], "governance_gate_exhausted"}
            with pytest.raises(StateAdvanceError): apply_answer(*args, **changed)
            assert store.load() == unchanged
        return apply_answer(*args, **kwargs)
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    with PhaseAExecutionLock.acquire(root, "test-alignment-answer-application"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-alignment-answer-application"):
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(ctrl, "_drain_pending_controller_completion", interrupted)
                patch.setattr(store, "apply_human_input_state_resolution", checked_apply)
                with pytest.raises(Interrupted):
                    if commander:
                        ctrl.resume_pending_human_input()
                    else:
                        ctrl.resume_with_human_input("Use WASD")
    pending = store.load()
    assert pending["blocked_decision"]["status"] == "resolved"
    assert pending["blocked_decision"]["answer_text"] == "Use WASD"
    assert pending["blocked_decision"]["resolved_by"] == ("COMMANDER" if commander else "user")
    assert pending["token_usage"] == before["token_usage"] + (7 if commander else 0)
    completion = load_prepared_controller_completion(root, store.squad_dir, pending["pending_controller_completion"])
    binding = authenticate(root, store.squad_dir, pending, completion)
    assert_native_answer_guards(case, completion.intent.publication)
    assert binding.clarification and binding.recovery["version"] == 41
    assert completion.intent.effect_plan == ("context",)
    promote = PreparedSquadPublication._promote
    positions = []
    def partial(*args, **kwargs):
        def fault(position):
            if position == 1:
                positions.append(position)
                raise Interrupted()
        return promote(*args, **{**kwargs, "fault_hook": fault})
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(PreparedSquadPublication, "_promote", partial)
        with pytest.raises(Interrupted): drain(ctrl)
    assert positions == [1]
    apply = IdentityStore.apply_identity_publication
    def applied(*args, **kwargs):
        apply(*args, **kwargs)
        raise Interrupted()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(IdentityStore, "apply_identity_publication", applied)
        with pytest.raises(Interrupted): drain(ctrl)
    from harness import discovery_completion
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(discovery_completion, "release", interrupted)
        with pytest.raises(Interrupted): drain(ctrl)
    assert "pending_controller_completion" not in store.load()
    assert identity.pending_identity_publication(spec_id="game")["state"] == "applied"
    with PhaseAExecutionLock.acquire(root, "test-alignment-answer-release"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-alignment-answer-release"):
            assert ctrl.resume_pending_human_input()
    after = store.load()
    assert after["phase"] == "phase2-tracker-alignment" and after["status"] == "running"
    assert after["blocked_decision"] == pending["blocked_decision"]
    for key in ("token_usage", "iteration", "max_iterations", "phase_dispatch_counts", "last_dispatch",
            "feasibility_structural_attempts", "structural_action", "governance_gate_exhausted"):
        assert (key in after, after.get(key)) == (key in pending, pending.get(key))
    assert identity.identity_history(spec_id="game") == history
    assert identity.pending_identity_publication(spec_id="game") is None
    assert identity.identity_publication(spec_id="game", operation_id=binding.operation_id)["state"] == "released"
    expected_calls = 1 if commander and before["blocked_decision"]["status"] == "pending" else 0
    assert len(executor.calls) == expected_calls
    assert not after["phase_dispatch_counts"].get("phase3-specialists")
    for op in binding.sources.publication.operations:
        assert (root / op.target).read_bytes() == op.postimage_bytes
    drain(ctrl)
    assert store.load() == after and len(executor.calls) == expected_calls
    from harness.human_input import HumanInputPolicyError
    with PhaseAExecutionLock.acquire(root, "test-alignment-answer-replay"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-alignment-answer-replay"):
            assert ctrl.resume_pending_human_input() is False
            with pytest.raises(HumanInputPolicyError, match="not awaiting a human answer"):
                ctrl.resume_with_human_input("Use a different answer")
    from harness.discovery_spec import clarification_source
    from harness.squad_state import StateAdvanceError
    with pytest.raises(StateAdvanceError):
        store.prepare_spec_round("alignment", clarification_source(after["last_human_input_completion"]),
            expected_state=after)
    assert store.load() == after and len(executor.calls) == expected_calls


def assert_native_answer_guards(case, publication):
    from harness.discovery_completion import decode_binding, _json, CompletionError
    from harness.element_identity_publication import encode_publication_request
    from harness.tracker_clarification import require_parent
    root, store, identity, _ = case
    state = store.load()
    binding = decode_binding(publication, state=state)
    # An actual pending/resolving alignment question still has the checkpoint
    # as its latest completed answer. Relabeling that receipt is not supersession.
    from harness.discovery_completion import _retained_input_projection
    from harness.discovery_spec import clarification_source
    historical = deepcopy(binding.recovery["before"])
    checkpoint_source = clarification_source(historical["last_human_input_completion"])
    historical["last_human_input_completion"]["decision_id"] = historical["blocked_decision"]["id"]
    with pytest.raises((CompletionError, ValueError)):
        _retained_input_projection(root, store.squad_dir, historical, identity,
            operation_id="discovery-completion-" + checkpoint_source["dispatch_id"],
            source=checkpoint_source, require_checkpoint=False)
    for key, value in (("token_usage", state["token_usage"] + 1),
            ("token_usage", state["token_usage"] - 1), ("iteration", state["iteration"] + 1),
            ("iteration", float(state["iteration"])), ("max_iterations", state["max_iterations"] + 1),
            ("feasibility_structural_attempts", 77), ("last_dispatch", {}),
            ("managed_alignment_rounds", {}), ("feature_policy", {})):
        with pytest.raises(CompletionError):
            decode_binding(publication, state={**state, key: value})
    for damage in ("effects", "route", "removals", "before", "answer"):
        recovery = deepcopy(binding.recovery)
        if damage == "effects": recovery["effects"]["state_updates"]["iteration"] = 77
        elif damage == "route": recovery["effects"]["route"] = "phase3-specialists"
        elif damage == "removals": recovery["effects"]["state_removals"].append("governance_gate_exhausted")
        elif damage == "before": recovery["before"]["max_iterations"] += 1
        else: recovery["resolution"]["answer_text"] = "Different answer"
        changed = deepcopy(publication)
        changed["managed_discovery"]["request"] = encode_publication_request(replace(
            binding.request, recovery_payload=_json(recovery)))
        with pytest.raises(CompletionError): decode_binding(changed, state=state)
    if binding.recovery["commander_receipt"] is not None:
        recovery = deepcopy(binding.recovery)
        recovery["commander_receipt"]["sha256"] = "0" * 64
        with pytest.raises(ValueError):
            require_parent(state, replace(binding, recovery=recovery), identity, root=root, run=store.squad_dir)
    from harness.prosaic_prompt_loader import ProsaicPromptLoader
    from harness.discovery_producer import producer_role
    from harness.discovery_assessment import require_alignment_question_evidence
    load = ProsaicPromptLoader.load_subagent
    def changed_role(self, role):
        artifact = load(self, role)
        return replace(artifact, body=artifact.body + "\nChanged role") if role == producer_role("alignment", "producer") else artifact
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ProsaicPromptLoader, "load_subagent", changed_role)
        with pytest.raises(ValueError):
            require_alignment_question_evidence(root, store.squad_dir, binding.recovery["before"],
                binding.recovery["source_completion"])
    from harness import discovery_completion
    read = discovery_completion._read_receipt
    def missing_receipt(run, name, producer="discovery", **kwargs):
        if producer == "alignment": raise FileNotFoundError("missing retained alignment evidence")
        return read(run, name, producer, **kwargs)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(discovery_completion, "_read_receipt", missing_receipt)
        with pytest.raises(FileNotFoundError):
            require_alignment_question_evidence(root, store.squad_dir, binding.recovery["before"],
                binding.recovery["source_completion"])
    assert store.load() == state


@pytest.mark.parametrize("provider,mode", [("codex", "guided"), ("claude", "banzai")])
def test_alignment_answer_application_recovers_without_redispatch(checkpoint_case, provider, mode):
    complete_strategy(checkpoint_case, provider, mode, mode == "banzai", "warn" if mode == "banzai" else "disabled")
    assert_reviewed_alignment(checkpoint_case, provider, routing=question())
    assert_question_handoff(checkpoint_case, assert_question_publication(checkpoint_case, provider), provider)
    assert_answer_source_refusals(checkpoint_case)
    if mode != "banzai":
        package = assert_answer_publication(checkpoint_case)
        package.publication.discard()
    assert_answer_application(checkpoint_case, provider, commander=mode == "banzai")
