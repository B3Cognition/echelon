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
from tests.unit.test_delivery_slice_recovery import ProcessLost, _crash_after_receipt


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


def _reconstruct(controller, store, executor):
    return RalphController(
        provider=controller._provider, gitops=controller._gitops,
        state_store=StateStore(store.state_dir, "001", "default"),
        mode_controller=ModeController(store.read()["mode"]),
        escalation_handler=EscalationHandler(str(store.state_dir / "escalation")),
        spec_id="001", strategy_id="default", config=controller._config, llm_provider=executor,
    )


def _build(controller, fixture):
    return controller._exec_build(None, "echelon build", "", worktree_path=str(fixture[0]), prompt="build")


def test_reconstructed_ralph_recovers_accepted_task_and_unaccounted_usage(slice_project, tmp_path, monkeypatch):
    controller, store = _controller(slice_project, tmp_path, ScriptedExecutor())
    with monkeypatch.context() as patch:
        _crash_after_receipt(patch, 4)
        with pytest.raises(ProcessLost):
            _build(controller, slice_project)
    resumed = ScriptedExecutor()
    other = _reconstruct(controller, store, resumed)
    result = _build(other, slice_project)
    assert result["passed"] and result["task_ids"] == ["T-001"], result
    assert result["tokens"] == 28 and store.read()["tokens_used"] == 28
    assert not resumed.calls
    again = _build(_reconstruct(other, store, resumed), slice_project)
    assert again["passed"] and again["tokens"] == 0
    assert store.read()["tokens_used"] == 28 and not resumed.calls


def test_progress_application_crash_is_idempotent_then_selects_next_task(slice_project, tmp_path, monkeypatch):
    controller, store = _controller(slice_project, tmp_path, ScriptedExecutor())
    result = _build(controller, slice_project)
    original = store.write
    def stop_before_state(data):
        if data.get("build", {}).get("completed_tasks") == 1:
            raise ProcessLost()
        original(data)
    with monkeypatch.context() as patch:
        patch.setattr(store, "write", stop_before_state)
        with pytest.raises(ProcessLost):
            controller._apply_build_task_progress(worktree_path=str(slice_project[0]), task_ids=result["task_ids"])
    assert "- [x] T-001" in (slice_project[1] / "tasks.md").read_text()
    resumed = ScriptedExecutor()
    other = _reconstruct(controller, store, resumed)
    result = _build(other, slice_project)
    assert result["passed"] and result["task_ids"] == ["T-001"] and not resumed.calls, result
    for _ in range(2):
        assert other._apply_build_task_progress(worktree_path=str(slice_project[0]), task_ids=result["task_ids"]) == ["T-001"]
    assert store.read()["build"]["completed_tasks"] == 1
    state = store.read()
    state["outer_iter"] += 1  # Ralph advances only after the verification boundary.
    store.write(state)
    next_result = _build(other, slice_project)
    assert next_result["passed"] and next_result["task_ids"] == ["T-002"], next_result
    assert _steps(resumed) == ["implementer", "spec_guard", "code_reviewer", "test_guardian"]


def test_missing_pending_journal_never_starts_over(slice_project, tmp_path, monkeypatch):
    controller, store = _controller(slice_project, tmp_path, ScriptedExecutor())
    with monkeypatch.context() as patch:
        _crash_after_receipt(patch, 2)
        with pytest.raises(ProcessLost):
            _build(controller, slice_project)
    journal = next(store.state_dir.rglob("journal.json"))
    journal.rename(journal.with_name("quarantined.json"))
    resumed = ScriptedExecutor()
    result = _build(_reconstruct(controller, store, resumed), slice_project)
    assert not result["passed"] and not resumed.calls
    assert "reconciliation_required" in result["build_reason"]


def test_ralph_restart_preserves_feedback_operation_not_next_task(slice_project, tmp_path, monkeypatch):
    controller, store = _controller(slice_project, tmp_path, ScriptedExecutor())
    result = _build(controller, slice_project)
    controller._apply_build_task_progress(worktree_path=str(slice_project[0]), task_ids=result["task_ids"])
    with monkeypatch.context() as patch:
        _crash_after_receipt(patch, 2)
        with pytest.raises(ProcessLost):
            controller._exec_feedback(None, VerifyResult(passed=False), "echelon build", "",
                                      worktree_path=str(slice_project[0]), prompt="fix greeting")
    resumed = ScriptedExecutor()
    result = _build(_reconstruct(controller, store, resumed), slice_project)
    assert result["passed"] and result["task_ids"] == ["T-001"], result
    assert _steps(resumed) == ["code_reviewer", "test_guardian"]


@pytest.mark.parametrize("missing", [False, True])
def test_full_loop_reuses_pending_worktree_without_creation_or_sync(slice_project, tmp_path, monkeypatch, missing):
    _initialize_git_worktree(slice_project[0])
    controller, store = _controller(slice_project, tmp_path, ScriptedExecutor(), "banzai")
    with monkeypatch.context() as patch:
        _crash_after_receipt(patch, 2)
        with pytest.raises(ProcessLost):
            controller.run_loop(max_outer=1, max_inner=1, build_prompt="build")
    if missing:
        slice_project[0].rename(slice_project[0].with_name("retained-elsewhere"))
    resumed = ScriptedExecutor()
    other = _reconstruct(controller, store, resumed)
    def refuse_creation(*args, **kwargs):
        raise AssertionError("pending candidate must not be recreated or synchronized")
    other._gitops.create_worktree.side_effect = refuse_creation
    monkeypatch.setattr(other, "_sync_phase_a_inputs_into_worktree", refuse_creation)
    # Stop at the real progress boundary: no verifier, commit, or publication is
    # needed to observe the remaining gates and unchanged candidate lifecycle.
    monkeypatch.setattr(other, "_apply_build_task_progress", lambda **kwargs: (_ for _ in ()).throw(ProcessLost()))
    if missing:
        result = other.run_loop(max_outer=1, max_inner=1, build_prompt="build")
        assert result.status == "blocked" and not resumed.calls
        assert "reconciliation" in result.termination_reason
    else:
        with pytest.raises(ProcessLost):
            other.run_loop(max_outer=1, max_inner=1, build_prompt="build")
        assert _steps(resumed) == ["code_reviewer", "test_guardian"]
        assert "hello 1" in (slice_project[0] / "app.py").read_text()


def test_disabling_feature_with_pending_operation_cannot_fall_back(slice_project, tmp_path, monkeypatch):
    controller, store = _controller(slice_project, tmp_path, ScriptedExecutor())
    with monkeypatch.context() as patch:
        _crash_after_receipt(patch, 2)
        with pytest.raises(ProcessLost):
            _build(controller, slice_project)
    controller._config.llm.features["delivery_gate_controller"] = False
    resumed = ScriptedExecutor()
    result = _build(_reconstruct(controller, store, resumed), slice_project)
    assert not result["passed"] and not resumed.calls
    assert "pending" in result["build_reason"]


@pytest.mark.parametrize("after_progress", [False, True])
def test_resume_detects_changed_published_source_without_overwriting_candidate(slice_project, tmp_path, monkeypatch, after_progress):
    import shutil
    source = tmp_path / "published-source"
    shutil.copytree(slice_project[0], source)
    controller, store = _controller(slice_project, tmp_path, ScriptedExecutor())
    controller._gitops.base_dir = str(source)
    if after_progress:
        result = _build(controller, slice_project)
        controller._apply_build_task_progress(worktree_path=str(slice_project[0]), task_ids=result["task_ids"])
        state = store.read()
        state["outer_iter"] += 1
        store.write(state)
    else:
        with monkeypatch.context() as patch:
            _crash_after_receipt(patch, 2)
            with pytest.raises(ProcessLost):
                _build(controller, slice_project)
    (source / "specs/001-slice/spec.md").write_text("# Changed authoritative requirements\n")
    before = (slice_project[1] / "spec.md").read_text()
    resumed = ScriptedExecutor()
    result = _build(_reconstruct(controller, store, resumed), slice_project)
    assert not result["passed"] and not resumed.calls
    assert (slice_project[1] / "spec.md").read_text() == before


def test_full_loop_crash_after_progress_state_preserves_accepted_candidate(slice_project, tmp_path, monkeypatch):
    _initialize_git_worktree(slice_project[0])
    controller, store = _controller(slice_project, tmp_path, ScriptedExecutor(), "banzai")
    def process_lost(**kwargs):
        raise ProcessLost()
    with monkeypatch.context() as patch:
        patch.setattr(controller, "_try_checkpoint_progress_commit", process_lost)
        with pytest.raises(ProcessLost):
            controller.run_loop(max_outer=1, max_inner=1, build_prompt="build")
    assert store.read()["build"]["completed_tasks"] == 1
    resumed = ScriptedExecutor()
    other = _reconstruct(controller, store, resumed)
    def refuse_creation(*args, **kwargs):
        raise AssertionError("accepted but uncheckpointed candidate must survive")
    other._gitops.create_worktree.side_effect = refuse_creation
    monkeypatch.setattr(other, "_try_checkpoint_progress_commit", process_lost)
    with pytest.raises(ProcessLost):
        other.run_loop(max_outer=1, max_inner=1, build_prompt="build")
    assert not resumed.calls and store.read()["build"]["completed_tasks"] == 1


def test_visual_reentry_counts_persisted_controlled_usage_once(slice_project, tmp_path, monkeypatch):
    import shutil
    from harness.coordinator import StrategyCoordinator
    from harness.delivery_results import ImplementationResult, VisualResult
    from harness.run_intent import RunIntent
    from harness.visual_ralph import VisualRalphController
    _initialize_git_worktree(slice_project[0])
    shutil.copytree(slice_project[0] / ".echelon", tmp_path / ".echelon")
    config = HarnessConfig()
    config.llm.enabled = True
    config.llm.features["delivery_gate_controller"] = True
    config.visual_tests.enabled = True
    config.visual_tests.max_iterations = 2
    gitops = MagicMock()
    gitops.base_dir = str(slice_project[0])
    gitops.get_latest_worktree.return_value = str(slice_project[0])
    executor = ScriptedExecutor()
    monkeypatch.setattr("harness.coordinator.AICodingCliProvider", lambda config: executor)
    implementations = []
    def implementation(self, **kwargs):
        implementations.append(self)
        result = _build(self, slice_project)
        assert result["passed"], result
        self._apply_build_task_progress(worktree_path=str(slice_project[0]), task_ids=result["task_ids"])
        state = self._state_store.read()
        if len(implementations) == 2:
            state["tokens_used"] += 5  # Separate authoritative verification cost.
            self._state_store.write(state)
        return ImplementationResult("verified", "converged", 1, 0, None, state["tokens_used"], None)
    visual_runs = []
    def visual(self, **kwargs):
        visual_runs.append(True)
        if len(visual_runs) == 2:
            return VisualResult("passed", "converged", 1, 0, None)
        result = implementations[-1].run_downstream_feedback(
            handle=None, worktree_path=str(slice_project[0]), verify_result=VerifyResult(False),
            build_command="echelon build", strategy_context="", build_prompt="build", phase="visual")
        assert result["passed"] and result["tokens"] == 28, result
        return VisualResult("fix_applied", "fix_applied", 1, result["tokens"], None)
    monkeypatch.setattr(RalphController, "run_loop", implementation)
    monkeypatch.setattr(VisualRalphController, "run_loop", visual)
    coordinator = StrategyCoordinator(provider=MockProvider(), gitops=gitops, config=config, base_dir=str(tmp_path))
    result = coordinator.start(RunIntent(spec_id="001", max_outer=1, max_inner=1))[0]
    assert result.status == "converged", result
    assert result.tokens_used == 61  # 28 initial + 28 repair + 5 verification.
    assert len(executor.calls) == 8
