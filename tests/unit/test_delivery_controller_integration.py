"""The opt-in must reach real Ralph consumers without legacy gate shortcuts."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.config import HarnessConfig, ValidationError, _parse_config
from harness.escalation import EscalationHandler
from harness.mode import ModeController
from harness.ralph import RalphController
from harness.state import StateStore
from harness.verify_result import VerifyResult
from tests.unit.test_coordinator import MockProvider
from tests.unit.test_coordinator import _initialize_git_worktree
from tests.unit.test_delivery_slice_runner import slice_project, ScriptedExecutor, _steps


def _controller(fixture, tmp_path, executor, mode="semi"):
    project, spec, _ = fixture
    config = HarnessConfig()
    config.llm.enabled = True
    config.llm.features["delivery_gate_controller"] = True
    gitops = MagicMock()
    gitops.base_dir = str(project)
    gitops.create_worktree.return_value = str(project)
    store = StateStore(tmp_path / "state", "001", "default")
    store.initialize("test-run", mode)
    store.transition("running")
    controller = RalphController(
        provider=MockProvider(), gitops=gitops, state_store=store,
        mode_controller=ModeController(mode), escalation_handler=EscalationHandler(str(tmp_path / "escalation")),
        spec_id="001", strategy_id="default", config=config, llm_provider=executor,
    )
    return controller, store


def test_ralph_build_and_feedback_both_run_independent_gates(slice_project, tmp_path):
    executor = ScriptedExecutor()
    controller, store = _controller(slice_project, tmp_path, executor)
    root = str(slice_project[0])
    result = controller._exec_build(None, "echelon build", "", worktree_path=root, prompt="banzai mode")
    assert result["passed"], result
    assert result["task_ids"] == ["T-001"]
    assert store.read()["delivery_slice_task_id"] == "T-001"
    controller._apply_build_task_progress(worktree_path=root, task_ids=result["task_ids"])
    fixed = controller._exec_feedback(
        None, VerifyResult(passed=False), "echelon build", "", worktree_path=root,
        prompt="Repair the reported failure, not another task.")
    assert fixed["passed"], fixed
    assert fixed["task_ids"] == ["T-001"]
    assert _steps(executor) == ["implementer", "spec_guard", "code_reviewer", "test_guardian"] * 2
    assert {call[0]["task_id"] for call in executor.calls} == {"T-001"}


@pytest.mark.parametrize("mode", ["banzai", "semi", "guided"])
def test_gate_failure_cannot_be_promoted_by_ralph(slice_project, tmp_path, mode):
    def reject(assignment, payload, root):
        if assignment["step"] == "spec_guard":
            payload.update(verdict="FAIL", findings=["app.py:1 is incorrect"])
    executor = ScriptedExecutor(reject)
    controller, store = _controller(slice_project, tmp_path, executor, mode)
    result = controller._exec_build(None, "echelon build", "", worktree_path=str(slice_project[0]), prompt="build")
    assert result["passed"] is False and result["build_status"] == "blocked"
    assert result["task_ids"] == []
    assert _steps(executor) == ["implementer", "spec_guard"] * 3
    assert "delivery_slice_task_id" not in store.read()


@pytest.mark.parametrize("target_key", ["implementation_target", "target_repo", "target_path"])
def test_explicit_empty_target_scope_never_broadens(slice_project, tmp_path, target_key):
    executor = ScriptedExecutor()
    controller, store = _controller(slice_project, tmp_path, executor)
    state = store.read()
    state["target_task_ids"] = []
    state[target_key] = "app"
    store.write(state)
    result = controller._exec_build(None, "echelon build", "", worktree_path=str(slice_project[0]), prompt="build")
    assert not result["passed"] and not executor.calls


def test_feedback_without_accepted_task_never_selects_next_open_task(slice_project, tmp_path):
    executor = ScriptedExecutor()
    controller, store = _controller(slice_project, tmp_path, executor)
    result = controller._exec_feedback(None, VerifyResult(passed=False), "echelon build", "",
                                      worktree_path=str(slice_project[0]), prompt="repair")
    assert not result["passed"] and not executor.calls


@pytest.mark.parametrize("flag", ["true", "false", 1, 0, None, [], {}])
def test_feature_flag_is_boolean_not_a_silent_fallback(flag):
    with pytest.raises(ValidationError, match="delivery_gate_controller"):
        _parse_config({"provider": "docker", "llm": {"features": {"delivery_gate_controller": flag}}})


def test_feature_default_does_not_enable_controller():
    assert _parse_config({"provider": "docker"}).llm.features.get("delivery_gate_controller", False) is False


def test_coordinator_trial_does_not_load_legacy_manager_command(slice_project, tmp_path, monkeypatch):
    from harness.coordinator import StrategyCoordinator
    from harness.run_intent import RunIntent
    controller, store = _controller(slice_project, tmp_path, ScriptedExecutor())
    # The fixture intentionally has only subagent profiles, no echelon.build command.
    coordinator = StrategyCoordinator(
        provider=controller._provider, gitops=controller._gitops,
        config=controller._config, base_dir=str(slice_project[0]),
    )
    monkeypatch.setattr("harness.coordinator.AICodingCliProvider", lambda config: ScriptedExecutor())
    captured = []
    def stop_before_build(self, **kwargs):
        from harness.delivery_results import ImplementationResult
        captured.append(kwargs["build_prompt"])
        return ImplementationResult("blocked", "test_stop", 0, 0, None, 0, None)
    monkeypatch.setattr("harness.coordinator.RalphController.run_loop", stop_before_build)
    result = coordinator.start(RunIntent(spec_id="001", max_outer=1, max_inner=1, mode="banzai"))[0]
    assert result.termination_reason == "test_stop"
    assert captured and "banzai mode" in captured[0]
    assert "You are MANAGER" not in captured[0]


def test_banzai_outer_loop_does_not_verify_or_accept_rejected_slice(slice_project, tmp_path):
    _initialize_git_worktree(slice_project[0])
    def reject(assignment, payload, root):
        if assignment["step"] == "spec_guard":
            payload.update(verdict="FAIL", findings=["app.py:1 wrong result"])
    executor = ScriptedExecutor(reject)
    controller, store = _controller(slice_project, tmp_path, executor, "banzai")
    result = controller.run_loop(max_outer=1, max_inner=1, build_prompt="banzai mode")
    assert result.status == "blocked", result
    assert result.termination_reason == "build_blocked"
    assert result.tokens_used == 42
    assert _steps(executor) == ["implementer", "spec_guard"] * 3
    assert "- [ ] T-001" in (slice_project[1] / "tasks.md").read_text()
    assert store.read().get("build", {}).get("completed_tasks", 0) == 0
    assert "repair_limit" in store.read()["build_reason"]


def test_real_provider_facade_preserves_step_and_read_only_policy(slice_project):
    from harness.llm_provider import AICodingCliProvider
    from tests.unit.test_delivery_slice_runner import _run
    from unittest.mock import patch

    script = ScriptedExecutor()
    config = HarnessConfig()
    config.llm.cli = "codex"
    provider = AICodingCliProvider(config)
    class ExternalBackend:
        def run_agent(self, request):
            return script.run_agent_result(request.cwd, request.prompt, request_metadata=request.metadata)
    provider._backend = ExternalBackend()
    with patch("harness.llm_provider.host_workspace_synthesis_boundary_available", return_value=True):
        result = _run(slice_project, provider)
    assert result.succeeded, result.reason
    assert _steps(script) == ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    for _, metadata, _ in script.calls[1:]:
        assert metadata["tool_write_scope_exclusive"] is True
        assert metadata["tool_write_paths"] == []
        assert str(slice_project[1]) in metadata["tool_forbidden_roots"]
