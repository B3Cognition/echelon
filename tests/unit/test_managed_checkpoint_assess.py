"""Native managed checkpoint decisions stop before Phase 2 execution."""
from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest
import yaml

from tests.unit.test_managed_lexicon_gate import (case, enrolled, turn_prepared, prepared,
    checkpoint_case, controller, selection, install_lexicon, PassingLexiconExecutor)
from tests.unit.test_managed_commander import CommanderExecutor


def install_commander(root):
    repo = Path(__file__).resolve().parents[2]
    shutil.copytree(repo / "prosaic", root / ".echelon/prosaic", dirs_exist_ok=True)
    shutil.copytree(repo / "runtime", root / ".echelon/runtime", dirs_exist_ok=True)


def continue_checkpoint(case, provider="codex", *, answer="approve", fault=None):
    root, store, identity, _ = case
    before = store.load()
    assert before["phase"] == "checkpoint-assess"
    history = identity.identity_history(spec_id="game")
    executor = CommanderExecutor(provider, answer=answer)
    selected = {**selection(case), "through_phase": "checkpoint-assess"}
    ctrl = controller(case, executor)
    if fault is not None:
        from tests.unit.test_discovery_turns import Interrupted
        original = store.apply_human_input_state_resolution
        with pytest.MonkeyPatch.context() as patch:
            def apply(*args, **kwargs):
                if fault == "before_state":
                    raise Interrupted()
                original(*args, **kwargs)
                raise Interrupted()
            patch.setattr(store, "apply_human_input_state_resolution", apply)
            with pytest.raises(Interrupted):
                ctrl.run(managed_discovery=selected)
        assert len(executor.calls) == 1
        ctrl = controller(case, executor)
    result = ctrl.run(managed_discovery=selected)
    state = store.load()
    if state["phase"] == "checkpoint-assess":
        assert state["blocked_decision"]["status"] == "awaiting_human", result
        assert ctrl.resume_with_human_input(answer) is (answer == "approve")
        controller(case, executor).run(managed_discovery=selected)
        state = store.load()
    want = "phase2-decide" if answer == "approve" else "terminal-blocked"
    assert state["phase"] == want, (result, state.get("controller_contract_error"))
    decision = state["blocked_decision"]
    assert decision["status"] == "resolved" and decision["selected_option_id"] == answer
    banzai = before["autonomy_mode"] == "banzai"
    assert decision["resolved_by"] == ("COMMANDER" if banzai else "user")
    assert not state["phase_dispatch_counts"].get("phase2-decide")
    assert state["token_usage"] == before["token_usage"] + (7 if banzai else 0)
    assert len(executor.calls) == (1 if banzai else 0)
    assert identity.identity_history(spec_id="game") == history
    receipt = state["last_human_input_completion"]
    row = identity.identity_publication(spec_id="game", operation_id="discovery-completion-" + receipt["completion_id"])
    assert row["state"] == "released"
    proof = json.loads(row["completion_payload"])["proof"]
    assert proof["intent"]["origin"] == "resolution" and proof["intent"]["effect_plan"] == ["context"]
    from harness.discovery_completion import decode_binding, released_discovery_input_projectors
    from harness.discovery_spec import clarification_source
    binding = decode_binding(proof["intent"]["publication"], state=state)
    assert binding.recovery["version"] == 30 and not binding.request.operations
    released_discovery_input_projectors(root, store.squad_dir, state, source=clarification_source(receipt))
    controller(case, executor).run(managed_discovery=selected)
    assert store.load() == state and len(executor.calls) == (1 if banzai else 0)
    if before.get("spec_quality_debt_authorization"):
        from harness.phase1_quality_debt import has_current_quality_debt_authorization
        assert state["spec_quality_debt_authorization"] == before["spec_quality_debt_authorization"]
        assert has_current_quality_debt_authorization(state, project_root=root)


def continue_debt_checkpoint(case, provider="codex"):
    root, store, identity, _ = case
    before = store.load()
    history = identity.identity_history(spec_id="game")
    assert before["phase"] == "phase1-lexicon-derive"
    debt = deepcopy(before["spec_quality_debt_authorization"])
    install_lexicon(case)
    install_commander(root)
    executor = PassingLexiconExecutor(provider)
    result = controller(case, executor).run(managed_discovery={**selection(case), "through_phase": "phase1-lexicon"})
    assert result.phase == "checkpoint-assess", (result, store.load().get("controller_contract_error"))
    assert store.load()["spec_quality_debt_authorization"] == debt
    assert len(executor.calls) == 3 and store.load()["token_usage"] == before["token_usage"] + 21
    continue_checkpoint(case, provider)
    assert store.load()["spec_quality_debt_authorization"] == debt
    assert identity.identity_history(spec_id="game") == history


def test_accepted_debt_survives_lexicon_and_later_checkpoint_receipt(checkpoint_case, monkeypatch):
    from tests.unit.test_managed_why2 import test_managed_quality_debt_choice_preserves_history_and_restarts
    test_managed_quality_debt_choice_preserves_history_and_restarts(checkpoint_case, "continue_with_debt", "codex", monkeypatch)
    continue_debt_checkpoint(checkpoint_case)


@pytest.mark.parametrize("cancelled,state_cancelled", [(True, False), (False, True)])
def test_cancelled_checkpoint_does_not_resume_decision(cancelled, state_cancelled):
    from types import SimpleNamespace
    from harness.squad import SquadController
    ctrl = object.__new__(SquadController)
    ctrl._cancelled = cancelled
    ctrl._state_store = SimpleNamespace(load=lambda: dict(phase="checkpoint-assess", status="blocked", cancel_requested=state_cancelled))
    ctrl._managed_discovery_stop = lambda reason: reason
    ctrl._managed_checkpoint_human_input = lambda state: True
    ctrl.resume_pending_human_input = lambda: pytest.fail("Cancellation must precede resolution")
    assert ctrl._run_managed_discovery_locked(dict(through_phase="checkpoint-assess")) == "managed_discovery_not_running"


@pytest.mark.parametrize("provider,mode,enabled,answer", [
    ("codex", "guided", False, "approve"),
    ("claude", "semi", True, "reject"),
    ("codex", "banzai", True, "approve"),
    ("claude", "banzai", True, "reject"),
])
def test_managed_checkpoint_uses_native_policy_and_stops_before_phase2(checkpoint_case, provider, mode, enabled, answer):
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    root, store, _, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = mode
    store.save(state)
    install_lexicon(checkpoint_case)
    install_commander(root)
    path = root / ".echelon/config.yml"
    config = yaml.safe_load(path.read_text())
    config["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.setdefault("lexicon_gate", {})["enabled"] = enabled
    path.write_text(yaml.safe_dump(config))
    selected = {**selection(checkpoint_case), "through_phase": "phase1-lexicon"}
    result = controller(checkpoint_case, PassingLexiconExecutor(provider)).run(managed_discovery=selected, create_managed_discovery=True)
    assert result.phase == "checkpoint-assess", result
    continue_checkpoint(checkpoint_case, provider, answer=answer,
        fault="after_state" if provider == "claude" and mode == "banzai" else None)
