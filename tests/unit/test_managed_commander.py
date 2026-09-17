"""COMMANDER transport keeps native choices and durable claim/replay ownership."""
from pathlib import Path
import json
import subprocess
import shutil

import pytest
import yaml

from harness.ai_cli_backend import CliRunResult
from tests.integration.test_human_input_routing import _choice_policy, _controller, _request


class CommanderExecutor:
    supports_inspection_turn = True
    constrained_execution_configuration_id = "inspection-v1"

    def __init__(self, provider="codex", answer="reject", failure=None):
        self.cli = self.provider_id = provider
        self.answer, self.failure, self.calls = answer, failure, []

    def run_inspection_turn(self, private, prompt, *, frontmatter, timeout_ms):
        assert list(Path(private).iterdir()) == []
        assert frontmatter == {"model_tier": "strong", "effort": "medium"}
        assert 0 < timeout_ms <= 300000
        assert "# COMMANDER DECISION RESOLUTION" in prompt
        assert "You are COMMANDER" in prompt
        self.calls.append(prompt)
        if self.failure == "exception":
            raise RuntimeError("Unknown provider completion")
        if self.failure == "oversized":
            return CliRunResult(0, "x" * 65537, "", token_usage=7)
        body = dict(verdict="DECISION_RESOLVED", state_updates={}, journal_entries=[],
            decision=dict(selected_option_id=self.answer, answer_text=None,
                rationale="The available evidence does not justify approval.", confidence="high"))
        if self.failure == "mutation":
            body["state_updates"] = {"phase": "phase2-decide"}
        return CliRunResult(0, yaml.safe_dump({"echelon_result": body}, sort_keys=False), "", token_usage=7)


@pytest.fixture
def commander(tmp_path, monkeypatch):
    policy = _choice_policy()
    executor = CommanderExecutor()
    ctrl, store, _ = _controller(tmp_path, autonomy_mode="banzai", policy=policy, provider=executor)
    store.set_human_input_decision(_request(ctrl, store, policy), initial_status="pending")
    bundle = tmp_path / ".echelon/prosaic/subagents"
    bundle.mkdir(parents=True)
    repo = Path(__file__).resolve().parents[2]
    shutil.copytree(repo / "prosaic", bundle.parent, dirs_exist_ok=True)
    shutil.copytree(repo / "runtime", tmp_path / ".echelon/runtime")
    actual = subprocess.run
    def inspect(command, **kwargs):
        if command[:2] != ["prosaic", "inspect"]:
            return actual(command, **kwargs)
        _, metadata, body = (Path(command[4]) / command[2]).read_text().split("---", 2)
        return subprocess.CompletedProcess(command, 0, json.dumps({"type": "subagent",
            "frontmatter": yaml.safe_load(metadata), "body": body}), "")
    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", inspect)
    return ctrl, store, policy


def run(case, executor, **kwargs):
    from harness.managed_commander import run_commander_turn
    ctrl, store, policy = case
    ctrl._provider = executor
    return run_commander_turn(ctrl, store.load(), policy, check_inputs=lambda: None, **kwargs)


@pytest.mark.parametrize("explicit_null", [False, True])
def test_resume_without_a_decision_is_a_noop(tmp_path, explicit_null):
    executor = CommanderExecutor()
    ctrl, store, _ = _controller(tmp_path, autonomy_mode="banzai",
        policy=_choice_policy(), provider=executor)
    state = store.load()
    if explicit_null:
        state["blocked_decision"] = None
        store.save(state)
        state = store.load()
    assert ctrl.resume_pending_human_input() is False
    assert store.load() == state
    assert executor.calls == []


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_judgment_can_reject_recommendation_and_replays_same_native_claim(commander, provider):
    ctrl, store, _ = commander
    before = store.load()
    executor = CommanderExecutor(provider)
    first = run(commander, executor)
    assert first.resolution is not None, first.reason
    assert first.resolution.selected_option_id == "reject"
    assert first.resolution.resolved_by == "COMMANDER"
    assert first.token_usage == 7
    claimed = store.load()
    assert claimed["blocked_decision"]["status"] == "resolving"
    assert claimed["blocked_decision"]["attempts"] == 1
    assert claimed["token_usage"] == before["token_usage"]
    assert claimed["phase"] == before["phase"]
    assert run(commander, executor) == first
    assert store.load() == claimed and len(executor.calls) == 1


@pytest.mark.parametrize("failure", ["exception", "mutation"])
def test_unknown_or_invalid_judgment_does_not_become_approval_or_another_call(commander, failure):
    executor = CommanderExecutor(failure=failure)
    result = run(commander, executor)
    assert result.resolution is None
    assert result.token_usage == (None if failure == "exception" else 7)
    executor.failure = None
    retry = run(commander, executor)
    assert retry.resolution is None and len(executor.calls) == 1


@pytest.mark.parametrize("drift", ["provider", "role", "context", "missing_receipt"])
def test_retained_judgment_cannot_be_rebound(commander, drift):
    ctrl, store, _ = commander
    executor = CommanderExecutor()
    assert run(commander, executor).resolution is not None
    if drift == "provider":
        executor.provider_id = executor.cli = "claude"
    elif drift == "role":
        path = ctrl._project_root / ".echelon/prosaic/subagents/echelon.commander.md"
        path.write_text(path.read_text() + "\nChanged role.\n")
    elif drift == "context":
        state = store.load()
        state["user_message"] = "Changed intent"
        store.save(state)
    else:
        path, = store.squad_dir.glob("commander-turns-*.json")
        path.unlink()
    assert run(commander, executor).resolution is None
    assert len(executor.calls) == 1


def test_exhausted_budget_does_not_claim_or_call(commander):
    executor = CommanderExecutor()
    before = commander[1].load()
    result = run(commander, executor, token_budget=0)
    assert result.resolution is None and executor.calls == []
    assert commander[1].load() == before


def test_oversized_completed_reply_retains_usage_and_native_retry_eligibility(commander):
    executor = CommanderExecutor(failure="oversized")
    result = run(commander, executor)
    assert result.resolution is None and result.token_usage == 7 and result.retryable
    assert run(commander, executor) == result
    assert len(executor.calls) == 1


def test_overbudget_judgment_is_charged_once_without_approval_or_retry(commander, monkeypatch):
    ctrl, store, policy = commander
    executor = CommanderExecutor()
    ctrl._provider, ctrl._token_budget = executor, 3
    # Test the native failure/accounting owner independently of the expensive
    # spec ancestry, covered by the full managed checkpoint corridor.
    monkeypatch.setattr(ctrl, "_managed_checkpoint_human_input", lambda state: True)
    assert ctrl._dispatch_managed_checkpoint_commander(store.load(), policy) is False
    saved = store.load()
    assert saved["token_usage"] == 7
    assert saved["blocked_decision"]["status"] == "failed"
    assert saved["blocked_decision"]["attempts"] == 1
    assert saved["blocked_decision"]["selected_option_id"] is None
    assert ctrl.resume_pending_human_input() is False
    assert store.load() == saved and len(executor.calls) == 1


@pytest.mark.parametrize("failure", ["mutation", "oversized"])
def test_completed_invalid_judgments_keep_native_two_attempt_limit_and_charges(commander, monkeypatch, failure):
    ctrl, store, policy = commander
    executor = CommanderExecutor(failure=failure)
    ctrl._provider = executor
    monkeypatch.setattr(ctrl, "_managed_checkpoint_human_input", lambda state: True)
    assert ctrl._dispatch_managed_checkpoint_commander(store.load(), policy) is False
    saved = store.load()
    assert saved["token_usage"] == 14
    assert saved["blocked_decision"]["attempts"] == 2
    assert saved["blocked_decision"]["status"] == "failed"
    assert ctrl.resume_pending_human_input() is False
    assert store.load() == saved and len(executor.calls) == 2


@pytest.mark.parametrize("point", ["claim", "before_response", "response", "accepted"])
def test_interrupted_claim_never_dispatches_twice_and_reuses_durable_response(commander, monkeypatch, point):
    from harness.discovery_receipts import DiscoveryReceiptFile
    class Interrupted(BaseException):
        pass
    ctrl, store, _ = commander
    executor = CommanderExecutor()
    original_write = DiscoveryReceiptFile._write
    original_claim = store.claim_human_input_decision
    with monkeypatch.context() as patch:
        def claim(*args, **kwargs):
            state = original_claim(*args, **kwargs)
            if point == "claim":
                raise Interrupted()
            return state
        def write(file, raw):
            value = json.loads(raw)["payload"]
            response = value["response"] is not None
            if point == "before_response" and response:
                raise Interrupted()
            original_write(file, raw)
            if (point == "response" and response) or (point == "accepted" and value["accepted"]):
                raise Interrupted()
        patch.setattr(store, "claim_human_input_decision", claim)
        patch.setattr(DiscoveryReceiptFile, "_write", write)
        with pytest.raises(Interrupted):
            run(commander, executor)
    saved = store.load()
    assert saved["blocked_decision"]["attempts"] == 1
    result = run(commander, executor)
    assert (result.resolution is not None) is (point in {"response", "accepted"})
    assert len(executor.calls) == (0 if point == "claim" else 1)
    assert store.load() == saved


@pytest.mark.parametrize("damage", ["choice", "rationale", "state", "policy", "receipt"])
def test_completion_provenance_requires_actual_retained_commander_choice(commander, damage):
    from dataclasses import replace
    from copy import deepcopy
    from harness.managed_commander import resolution_receipt
    from harness.squad_state import build_human_input_resolution_postimage
    ctrl, store, policy = commander
    answer = run(commander, CommanderExecutor()).resolution
    before = store.load()
    resolved = build_human_input_resolution_postimage(before["blocked_decision"], answer,
        resolved_at="2026-09-17T12:00:00+00:00")
    receipt = resolution_receipt(store.squad_dir, before, resolved, policy)
    assert receipt["token_usage"] == 7
    if damage == "choice":
        resolved = build_human_input_resolution_postimage(before["blocked_decision"], replace(answer, selected_option_id="approve"),
            resolved_at=resolved["resolved_at"])
    elif damage == "rationale":
        resolved["resolution_rationale"] = "Invented justification"
    elif damage == "state":
        before = deepcopy(before)
        before["user_message"] = "Different intent"
    elif damage == "policy":
        policy = replace(policy, context_state_keys=("phase",))
    else:
        path, = store.squad_dir.glob("commander-turns-*.json")
        path.unlink()
    with pytest.raises(ValueError):
        resolution_receipt(store.squad_dir, before, resolved, policy)


@pytest.mark.parametrize("point", ["before", "after"])
def test_interrupted_failure_accounting_is_charged_once_per_native_attempt(commander, monkeypatch, point):
    class Interrupted(BaseException):
        pass
    ctrl, store, policy = commander
    executor = CommanderExecutor(failure="mutation")
    ctrl._provider = executor
    monkeypatch.setattr(ctrl, "_managed_checkpoint_human_input", lambda state: True)
    original = store._commit_human_input_state_unlocked
    with monkeypatch.context() as patch:
        def commit(before, desired):
            failing = before["blocked_decision"]["status"] == "resolving" and desired["blocked_decision"]["status"] in {"pending", "failed"}
            if failing and point == "before":
                raise Interrupted()
            saved = original(before, desired)
            if failing:
                raise Interrupted()
            return saved
        patch.setattr(store, "_commit_human_input_state_unlocked", commit)
        with pytest.raises(Interrupted):
            ctrl._dispatch_managed_checkpoint_commander(store.load(), policy)
    assert len(executor.calls) == 1
    assert ctrl.resume_pending_human_input() is False
    saved = store.load()
    assert saved["token_usage"] == 14 and saved["blocked_decision"]["attempts"] == 2
    assert saved["blocked_decision"]["status"] == "failed" and len(executor.calls) == 2
    assert ctrl.resume_pending_human_input() is False
    assert store.load() == saved and len(executor.calls) == 2


@pytest.mark.parametrize("failure", ["mutation", "oversized"])
def test_invalid_reply_cannot_spend_second_attempt_after_exhausting_budget(commander, monkeypatch, failure):
    ctrl, store, policy = commander
    executor = CommanderExecutor(failure=failure)
    ctrl._provider, ctrl._token_budget = executor, 3
    monkeypatch.setattr(ctrl, "_managed_checkpoint_human_input", lambda state: True)
    assert ctrl._dispatch_managed_checkpoint_commander(store.load(), policy) is False
    saved = store.load()
    assert saved["token_usage"] == 7 and saved["blocked_decision"]["attempts"] == 1
    assert saved["blocked_decision"]["selected_option_id"] is None
    assert ctrl.resume_pending_human_input() is False
    assert store.load() == saved and len(executor.calls) == 1


def test_public_resume_does_not_reset_uncertain_managed_claim_or_use_legacy_dispatch(commander, monkeypatch):
    ctrl, store, _ = commander
    executor = CommanderExecutor(failure="exception")
    assert run(commander, executor).resolution is None
    saved = store.load()
    monkeypatch.setattr(ctrl, "_managed_checkpoint_human_input", lambda state: True)
    def forbidden(*args, **kwargs):
        pytest.fail("Managed COMMANDER recovery must not reset or bypass its retained claim")
    monkeypatch.setattr(store, "recover_interrupted_human_input_decision", forbidden)
    monkeypatch.setattr(ctrl, "_dispatch_commander_human_input", forbidden)
    assert ctrl.resume_pending_human_input() is False
    assert store.load() == saved and len(executor.calls) == 1


def test_checkpoint_effect_codec_refuses_controller_only_approval(commander):
    from harness.blocked_decision import validate_blocked_decision
    from harness.discovery_checkpoint_resolution import state_effects
    from harness.human_input import AppliedHumanInputResolution
    from harness.squad_state import build_human_input_resolution_postimage
    # A structurally valid native automatic resolution is not necessarily a
    # valid checkpoint resolution. This is a negative codec test, not authority.
    before = commander[1].load()["blocked_decision"]
    before.update(producer_id="checkpoint-assess", source_phase="checkpoint-assess",
        reason_code="checkpoint_assess_decision_required")
    before["options"][0]["next_phase"] = "phase2-decide"
    decision = build_human_input_resolution_postimage(before,
        AppliedHumanInputResolution("approve", None, "controller", rationale="Evidence passes", confidence="high"),
        resolved_at="2026-09-17T12:00:00+00:00")
    assert validate_blocked_decision(decision) == decision
    with pytest.raises(ValueError):
        state_effects(decision)
