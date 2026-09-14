"""Normal Squad entry; only model processes and Prosaic inspection are scripted."""
from dataclasses import replace
import json

import pytest

from tests.unit.test_discovery_bootstrap import case
from tests.unit.test_discovery_turns import prepared as turn_prepared, Interrupted
from tests.unit.test_discovery_operation import prepared, DiscoveryExecutor
from tests.unit.test_discovery_completion import controller


@pytest.fixture
def enrolled(case):
    # The normal run, not this fixture, must establish the selected genesis.
    return case


class FullDiscoveryExecutor(DiscoveryExecutor):
    def run_inspection_turn(self, *args, **kwargs):
        response = super().run_inspection_turn(*args, **kwargs)
        payload = self.calls[-1]
        if payload["assignment"]["step"] == "author":
            reply = json.loads(response.stdout)
            reply["artifacts"].update({
                "glossary.md": "# Glossary\nCamera: view of the scene.\n",
                "mental-model.md": "# Mental model\nSee U-000001 for the camera decision.\n",
                "boundaries.md": "# Boundaries\nInitial scene and movement only.\n",
                "reference-architectures.md": "# Reference architectures\nBrowser scene graph.\n",
            })
            return replace(response, stdout=json.dumps(reply))
        return response


def selection(prepared):
    return {"bootstrap": prepared[3], "input_tree": "inputs"}


@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize("mode", ["guided", "semi", "banzai"])
def test_normal_entry_publishes_all_discovery_and_stops_at_real_successor(prepared, provider, mode):
    state = prepared[1].load()
    state["autonomy_mode"] = mode
    prepared[1].save(state)
    executor = FullDiscoveryExecutor(provider)
    ctrl = controller(prepared, executor)
    result = ctrl.run(managed_discovery=selection(prepared), create_managed_discovery=True)
    assert result.status == "blocked"
    assert result.phase == "phase1-synthesizer"
    assert result.summary == "managed_phase_not_supported"
    saved = prepared[1].load()
    assert saved["phase"] == "phase1-synthesizer"
    assert saved["last_dispatch"]["post_dispatch_complete"] is True
    assert saved["token_usage"] == 21
    assert saved["phase_dispatch_counts"]["phase1-discover"] == 1
    assert len(executor.calls) == 3
    spec = prepared[0] / "specs/game"
    assert {p.name for p in spec.iterdir()} == {
        "unknowns.md", "assumptions.md", "glossary.md", "mental-model.md",
        "boundaries.md", "reference-architectures.md", "spec-artifact-graph.json",
    }
    assert "### U-000001: Camera choice" in (spec / "unknowns.md").read_text()
    assert "See U-000001" in (spec / "mental-model.md").read_text()
    assert "U-000001" in (prepared[1].squad_dir / "context/current-feature-context.md").read_text()
    restarted = controller(prepared, executor)
    assert restarted.run(managed_discovery=selection(prepared)).phase == "phase1-synthesizer"
    assert prepared[1].load() == saved
    assert len(executor.calls) == 3


def test_resume_cannot_create_missing_selection(prepared):
    executor = FullDiscoveryExecutor()
    before = prepared[1].load()
    result = controller(prepared, executor).run(managed_discovery=selection(prepared))
    assert result.status == "blocked"
    assert prepared[1].load() == before
    assert executor.calls == []


@pytest.mark.parametrize("point", ["accepted_operation", "sealed_completion", "routed", "handoff", "completed", "released"])
def test_normal_restart_replays_receipts_without_dispatch_or_usage_duplication(prepared, monkeypatch, point):
    from harness.element_identity_store import IdentityStore
    executor = FullDiscoveryExecutor()
    ctrl = controller(prepared, executor)
    target, method = {
        "accepted_operation": (prepared[1], "advance_discovery_operation"),
        "sealed_completion": (ctrl, "_prepare_controller_completion"),
        "routed": (prepared[1], "advance"),
        "handoff": (prepared[1], "handoff_external_publication"),
        "completed": (prepared[1], "complete_controller_completion"),
        "released": (IdentityStore, "release_identity_publication"),
    }[point]
    original = getattr(target, method)
    def stop_after(*args, **kwargs):
        value = original(*args, **kwargs)
        if point != "accepted_operation" or args[1] == "finish":
            raise Interrupted()
        return value
    with monkeypatch.context() as patch:
        patch.setattr(target, method, stop_after)
        with pytest.raises(Interrupted):
            ctrl.run(managed_discovery=selection(prepared), create_managed_discovery=True)
    calls = len(executor.calls)
    result = controller(prepared, executor).run(managed_discovery=selection(prepared))
    assert result.status == "blocked" and result.phase == "phase1-synthesizer", result
    state = prepared[1].load()
    assert state["last_dispatch"]["post_dispatch_complete"] is True
    assert state["token_usage"] == 21
    assert len(executor.calls) == calls == 3
    assert prepared[2].pending_identity_publication(spec_id="game") is None


def test_exhausted_outer_phase_budget_cannot_dispatch_managed_discovery(prepared):
    for _ in range(5):
        prepared[1].increment_phase_dispatch_count("phase1-discover")
    before = prepared[1].load()
    executor = FullDiscoveryExecutor()
    result = controller(prepared, executor).run(managed_discovery=selection(prepared), create_managed_discovery=True)
    assert result.status == "blocked"
    assert executor.calls == []
    assert prepared[1].load() == before


def test_routing_preparation_failure_does_not_charge_receipt_usage(prepared, monkeypatch):
    from harness.squad_state import StateAdvanceError
    executor = FullDiscoveryExecutor()
    ctrl = controller(prepared, executor)
    def unavailable(*args, **kwargs):
        raise StateAdvanceError("checkpoint prestate unavailable", json_path="$.checkpoint_prestate", validator="checkpoint_prestate")
    with monkeypatch.context() as patch:
        patch.setattr(ctrl, "_prepare_controller_completion", unavailable)
        result = ctrl.run(managed_discovery=selection(prepared), create_managed_discovery=True)
    assert result.status == "blocked"
    assert prepared[1].load()["token_usage"] == 0
    result = controller(prepared, executor).run(managed_discovery=selection(prepared))
    assert result.phase == "phase1-synthesizer"
    assert prepared[1].load()["token_usage"] == 21
    assert len(executor.calls) == 3


def test_failed_state_advance_does_not_charge_receipt_usage(prepared, monkeypatch):
    from harness.squad_state import StateAdvanceError
    executor = FullDiscoveryExecutor()
    def unavailable(*args, **kwargs):
        raise StateAdvanceError("state unavailable", json_path="$.state", validator="stale_state")
    with monkeypatch.context() as patch:
        patch.setattr(prepared[1], "advance", unavailable)
        result = controller(prepared, executor).run(managed_discovery=selection(prepared), create_managed_discovery=True)
    assert result.status == "blocked"
    assert prepared[1].load()["token_usage"] == 0
    assert len(executor.calls) == 3
    result = controller(prepared, executor).run(managed_discovery=selection(prepared))
    assert result.phase == "phase1-synthesizer", result
    assert prepared[1].load()["token_usage"] == 21
    assert len(executor.calls) == 3


def test_orphan_cleanup_can_resume_after_publication_stage_disposal(prepared, monkeypatch):
    from harness.squad_publication import PreparedSquadPublication
    executor = FullDiscoveryExecutor()
    ctrl = controller(prepared, executor)
    prepare = ctrl._prepare_controller_completion
    def stop_after_sealing(*args, **kwargs):
        prepare(*args, **kwargs)
        raise Interrupted()
    with monkeypatch.context() as patch:
        patch.setattr(ctrl, "_prepare_controller_completion", stop_after_sealing)
        with pytest.raises(Interrupted):
            ctrl.run(managed_discovery=selection(prepared), create_managed_discovery=True)
    discard = PreparedSquadPublication.discard
    def stop_after_disposal(*args):
        discard(*args)
        raise Interrupted()
    with monkeypatch.context() as patch:
        patch.setattr(PreparedSquadPublication, "discard", stop_after_disposal)
        with pytest.raises(Interrupted):
            controller(prepared, executor).run(managed_discovery=selection(prepared))
    result = controller(prepared, executor).run(managed_discovery=selection(prepared))
    assert result.phase == "phase1-synthesizer", result
    assert prepared[1].load()["last_dispatch"]["post_dispatch_complete"] is True
    assert len(executor.calls) == 3


@pytest.mark.parametrize("change", ["input_tree", "run_id", "spec_id", "epoch_uuid", "capture_marker"])
def test_independent_selection_drift_cannot_drain_pending_completion(prepared, monkeypatch, change):
    from copy import deepcopy
    executor = FullDiscoveryExecutor()
    original = prepared[1].advance
    def stop_after(*args, **kwargs):
        original(*args, **kwargs)
        raise Interrupted()
    with monkeypatch.context() as patch:
        patch.setattr(prepared[1], "advance", stop_after)
        with pytest.raises(Interrupted):
            controller(prepared, executor).run(managed_discovery=selection(prepared), create_managed_discovery=True)
    changed = deepcopy(selection(prepared))
    if change == "input_tree":
        changed[change] = "other-inputs"
    elif change == "capture_marker":
        changed["bootstrap"][change]["manifest_sha256"] = "f" * 64
    else:
        changed["bootstrap"][change] = "different"
    before = prepared[1].load()
    result = controller(prepared, executor).run(managed_discovery=changed)
    assert result.status == "blocked"
    assert prepared[1].load() == before
    assert list((prepared[0] / "specs/game").iterdir()) == []
    assert len(executor.calls) == 3


def test_real_checkpoint_policy_completes_before_identity_release(prepared):
    import subprocess
    root, store, _, _ = prepared
    for command in (["git", "init", "-q"], ["git", "config", "user.name", "Test"],
                    ["git", "config", "user.email", "test@example.invalid"],
                    ["git", "commit", "--allow-empty", "-m", "Initial"]):
        subprocess.run(command, cwd=root, check=True, capture_output=True)
    state = store.load()
    state.update(spec_dir="specs/game", checkpoint_policy_version=2, phase_completion_outcomes=[])
    store.save(state)
    executor = FullDiscoveryExecutor()
    result = controller(prepared, executor).run(managed_discovery=selection(prepared), create_managed_discovery=True)
    assert result.phase == "phase1-synthesizer", result
    state = store.load()
    assert state["last_dispatch"]["post_dispatch_complete"] is True, state
    assert len(state["phase_completion_outcomes"]) == 1
    assert prepared[2].pending_identity_publication(spec_id="game") is None
