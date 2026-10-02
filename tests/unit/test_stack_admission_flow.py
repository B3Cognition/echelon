"""Production publication/admission and journal recovery use owner capabilities."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from harness.config import HarnessConfig
from harness.delivery_controller import DeliveryController, _delivery_stack_snapshot
from harness.delivery_errors import DeliveryConfigurationError
from harness.run_intent import RunIntent
from harness.verification_stack_runtime import resolve_verification_stacks
from tests.unit.test_spec_stack_prerequisites import controller as squad_controller
from tests.unit.test_verification_capability_preflight import custom_stack, select, spec
from tests.unit.test_delivery_slice_runner import slice_project, ScriptedExecutor, _run, _steps


def test_service_rejects_generic_before_allocating_delivery(tmp_path, capsys):
    from echelon.delivery_service import _block_if_harness_phase_a_not_ready

    select(tmp_path, ["generic"])
    directory = spec(tmp_path)
    before = (directory / "tasks.md").read_bytes()
    with pytest.raises(SystemExit):
        _block_if_harness_phase_a_not_ready(directory, directory.name, project_root=tmp_path)
    assert "coverage_observer_unavailable" in capsys.readouterr().err
    assert (directory / "tasks.md").read_bytes() == before
    assert not (tmp_path / "runs").exists()


def test_service_rejects_unowned_required_runnability_before_allocating_delivery(tmp_path, capsys):
    from echelon.delivery_service import _block_if_harness_phase_a_not_ready

    custom_stack(tmp_path, types=("e2e",), browser=True)
    select(tmp_path, ["custom"])
    directory = spec(tmp_path, types=("e2e",))
    before = (directory / "tasks.md").read_bytes()

    with pytest.raises(SystemExit):
        _block_if_harness_phase_a_not_ready(directory, directory.name, project_root=tmp_path)

    assert "runnability_contract_owner_required" in capsys.readouterr().err
    assert (directory / "tasks.md").read_bytes() == before
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize("reverse", [False, True])
def test_all_target_admission_reports_unsupported_sibling(tmp_path, capsys, reverse, monkeypatch):
    from echelon.delivery_service import _run_delivery
    from tests.unit.test_delivery_controller import _initialize_git_worktree

    custom_stack(tmp_path)
    targets = ["sources/a", "sources/b"]
    if reverse:
        targets.reverse()
    select(tmp_path / "sources/a", ["custom"])
    select(tmp_path / "sources/b", ["generic"])
    directory = spec(tmp_path, targets=targets, types=("unit", "unit"))
    _initialize_git_worktree(tmp_path)
    monkeypatch.setattr("echelon.cli._require_provider_capability", lambda *a, **k: None)
    launches = []
    monkeypatch.setattr("echelon.orchestrator.run_multi_target", lambda *a, **k: launches.append(k))
    before = (directory / "tasks.md").read_bytes()
    with pytest.raises(SystemExit):
        _run_delivery(tmp_path, [directory.name])
    output = capsys.readouterr().err
    assert "sources/b: coverage_observer_unavailable" in output
    assert launches == []
    assert (directory / "tasks.md").read_bytes() == before
    assert not list(tmp_path.rglob("delivery.json"))


def test_pending_spec_effects_settle_before_selection_blocks_new_dispatch(tmp_path, monkeypatch):
    from tests.unit.test_spec_step_kernel import _fixture

    monkeypatch.setenv("ECHELON_SQUAD_ACTIVE", "")
    pending = _fixture(tmp_path, effects=())
    before = pending.store.load()["pending_spec_step"]
    sealed_files = {p: p.read_bytes() for p in pending.squad_dir.rglob("*") if p.is_file() and "spec-step" in str(p)}
    ctrl, _, provider = squad_controller(tmp_path)
    ctrl._state_store = pending.store
    ctrl._squad_dir = pending.squad_dir
    result = ctrl.run(user_message="Continue discovery")
    assert result.status == "blocked"
    assert "stack_selection_required" in result.summary
    after = pending.store.load()
    assert "pending_spec_step" not in after
    assert after["last_dispatch"]["dispatch_id"] == before["step_id"]
    assert provider.exec_agent.call_count == 0
    for path, data in sealed_files.items():
        if path.exists():
            assert path.read_bytes() == data


def delivery(root):
    config = HarnessConfig()
    config.llm.enabled = True
    config.review_loop.enabled = False
    # Ralph performs real filesystem/Git operations on this result. An
    # unconfigured MagicMock becomes a relative path inside the harness checkout.
    gitops = MagicMock()
    gitops.base_dir = root
    gitops.create_worktree.return_value = str(root.resolve())
    return DeliveryController(provider=MagicMock(), gitops=gitops, config=config, base_dir=str(root))


def test_direct_delivery_rejects_missing_capability_before_dispatch(tmp_path):
    select(tmp_path, ["generic"])
    directory = spec(tmp_path)
    ctrl = delivery(tmp_path)
    with pytest.raises(DeliveryConfigurationError, match="coverage_observer_unavailable"):
        ctrl.run(RunIntent(spec_id=directory.name))
    assert not ctrl.state().get("delivery_slice_operation")


@pytest.mark.unit
@pytest.mark.parametrize(("status", "phase"), [
    ("interrupted", "implementation"), ("interrupted", "visual"), ("interrupted", "review"),
    ("blocked", "implementation"), ("blocked", "visual"), ("blocked", "review"),
    ("blocked", "finalization"),
])
@pytest.mark.parametrize("reset", [False, True])
def test_paused_delivery_admission_failure_preserves_checkpoint(tmp_path, monkeypatch, status, phase, reset):
    """Rejected admission must not crash, restart work, or change its saved phase."""
    from harness.state import StateStore

    custom_stack(tmp_path)
    select(tmp_path, ["custom"])
    directory = spec(tmp_path)
    ctrl = delivery(tmp_path)
    store = StateStore(ctrl._state_dir, directory.name)
    store.initialize(
        "retained-run", "semi", token_budget=1000,
        enabled_phases=["implementation", "visual", "review", "finalization"],
        delivery_stack_snapshot=_delivery_stack_snapshot(resolve_verification_stacks(tmp_path, tmp_path)),
    )
    store.transition("running")
    for active in {
        "implementation": [],
        "visual": ["verified", "validating"],
        "review": ["verified", "validating", "reviewing"],
        "finalization": ["verified", "validating", "reviewing", "finalizing"],
    }[phase]:
        store.transition(active)
    store.transition(status, updates={
        f"{status}_phase": phase, "outer_iter": 2, "inner_iter": 3, "tokens_used": 91,
        "last_verify_result": {"passed": True, "failures": [], "duration_s": 0.0, "token_usage": 0},
        "delivery_slice_operation": {"id": "accepted-operation", "progress_applied": True},
    })
    before = store.read()
    receipt = store.state_dir / "retained-receipt.json"
    receipt.write_text('{"operation_id":"accepted-operation","accepted":true}\n')
    receipt_bytes = receipt.read_bytes()
    select(tmp_path, ["generic"])

    def forbidden_execution(*args, **kwargs):
        raise AssertionError("Rejected admission must not execute Delivery effects")

    monkeypatch.setattr("harness.llm_provider.AICodingCliProvider.run_agent_result", forbidden_execution)
    ctrl._gitops.create_worktree.side_effect = forbidden_execution
    ctrl._gitops.create_draft_pr.side_effect = forbidden_execution
    ctrl._provider.create.side_effect = forbidden_execution

    for _ in range(2):
        result = ctrl.run(RunIntent(spec_id=directory.name, resume=True, reset=reset))

        assert result.status == "blocked"
        assert result.termination_reason == "delivery_configuration_invalid"
        assert result.blocked_phase == phase
        after = store.read()
        assert after["status"] == "blocked"
        assert after["blocked_phase"] == phase
        assert after["interrupted_phase"] is None
        assert "coverage_observer_unavailable" in after["build_reason"]
        for field in ("run_id", "outer_iter", "inner_iter", "tokens_used", "token_budget",
                      "last_verify_result", "delivery_stack_snapshot", "delivery_slice_operation"):
            assert after[field] == before[field]
        assert receipt.read_bytes() == receipt_bytes


def test_spec_terminal_readiness_does_not_trust_stale_ready_status(tmp_path):
    from echelon.spec_service import _phase_a_ready_to_build

    select(tmp_path, ["generic"])
    directory = spec(tmp_path)
    (tmp_path / ".echelon/constitution.md").write_text("# Constitution\nOwner rules\n")
    state = {"status": "done", "completed_phases": ["phase1-constitution"],
             "published_spec_dir": str(directory), "spec_dir": str(directory), "spec_id": directory.name}
    assert not _phase_a_ready_to_build(tmp_path, state)


def test_new_dispatch_guard_does_not_rewrite_recovered_slice_receipt(slice_project):
    first = ScriptedExecutor()
    stopped = _run(slice_project, first, operation_id="retained", stop_requested=lambda: bool(first.calls))
    assert stopped.reason == "delivery_slice_cancelled"
    journal = next(slice_project[2].rglob("journal.json"))
    before = json.loads(journal.read_text())
    resumed = ScriptedExecutor()
    result = _run(slice_project, resumed, operation_id="retained", journal_required=True,
                  dispatch_admission=lambda: "coverage_observer_unavailable: owner config changed")
    after = json.loads(journal.read_text())
    assert result.status == "blocked"
    assert "coverage_observer_unavailable" in result.reason
    assert resumed.calls == []
    assert after["records"] == before["records"]
    assert after["input_fingerprint"] == before["input_fingerprint"]
    assert after["binding"] == before["binding"]


def test_pending_prerequisite_can_return_to_native_recovery(tmp_path):
    from harness.delivery_controller import pending_slice_resume_supported

    state = {
        "status": "blocked", "termination_reason": "verification_prerequisite",
        "blocked_phase": "implementation", "build_status": "blocked",
        "build_reason": "verification_prerequisite: source contract changed",
        "delivery_slice_operation": {"id": "retained", "worktree_path": str(tmp_path), "progress_applied": False},
    }
    assert pending_slice_resume_supported(state)
    state["delivery_slice_operation"]["progress_applied"] = True
    assert not pending_slice_resume_supported(state)


@pytest.mark.parametrize("supported", [False, True])
def test_publication_preparation_checks_capabilities_before_sealing(tmp_path, supported):
    from harness.squad_publication import SquadPublicationTransaction

    custom_stack(tmp_path)
    select(tmp_path, ["custom"] if supported else ["generic"])
    ctrl, store, _ = squad_controller(tmp_path)
    active = spec(store.squad_dir)
    state = {"status": "done", "run_id": store.squad_dir.name, "spec_id": active.name,
             "spec_dir": str(active), "published_spec_dir": f"specs/{active.name}"}
    transaction = SquadPublicationTransaction.begin(tmp_path, store.squad_dir, "b" * 32)
    count, readiness = ctrl._stage_phase_a_effects(transaction, state)
    assert readiness.ready is supported, readiness.blockers
    assert (count > 0) is supported
    assert not (tmp_path / "specs" / active.name).exists()
    if not supported:
        assert "coverage_observer_unavailable" in "\n".join(readiness.blockers)


def test_complete_generic_spec_requests_owner_capabilities_not_agent_repair(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHELON_SQUAD_ACTIVE", "")
    select(tmp_path, ["generic"])
    ctrl, store, provider = squad_controller(tmp_path)
    directory = spec(tmp_path)
    store.initialize(store.squad_dir.name, "greenfield", "request", 0, "phase1-constitution")
    state = store.load()
    state.update(spec_dir=str(directory), spec_id=directory.name)
    store.save(state)
    result = ctrl.run(user_message="Continue")
    assert result.status == "blocked"
    assert "coverage_observer_unavailable" in result.summary
    assert provider.exec_agent.call_count == 0


def test_documentation_recovery_retains_saved_runnability_requirement(slice_project, tmp_path):
    from tests.unit.test_delivery_controller_integration import _controller

    root = slice_project[0]
    custom_stack(root, browser=True)
    select(root, ["custom"])
    ctrl, store = _controller(slice_project, tmp_path, ScriptedExecutor())
    state = store.read()
    state["delivery_stack_snapshot"] = _delivery_stack_snapshot(resolve_verification_stacks(root, root))
    store.write(state)
    # Recovery has not admitted a current stack; policy belongs to saved input.
    ctrl._config.resolved_stacks = None
    ctrl._config.resolved_runnability = None
    reference, required = ctrl._controlled_documentation_runnability(root)
    assert reference is None
    assert required is True


def test_contract_drift_does_not_replace_pending_browser_operation(slice_project, tmp_path, monkeypatch):
    from tests.unit.test_delivery_browser_handoff_execution import _handoff_project, _drive

    ctrl, store, executor, captures, retained = _handoff_project(slice_project, tmp_path, monkeypatch)
    ctrl._verification_admission = lambda: "verification_prerequisite: changed owner" if captures else None
    result = _drive(ctrl, slice_project)
    assert not result["passed"]
    assert "verification_prerequisite" in result["build_reason"]
    assert len(executor.calls) == 1
    assert "browser_handoff" not in store.read()["delivery_slice_operation"]
    assert retained and all(path.read_bytes() == data for path, data in retained.items())


@pytest.mark.parametrize("change", ["selection", "definition", "source_empty"])
def test_saved_contract_is_not_replaced_on_drift(tmp_path, change):
    from harness.state import StateStore

    raw, path = custom_stack(tmp_path)
    select(tmp_path, ["custom"])
    directory = spec(tmp_path, targets=("sources/a",))
    source = tmp_path / "sources/a"
    source.mkdir(parents=True)
    ctrl = delivery(tmp_path)
    context = ctrl._resolve_run_context(RunIntent(spec_id=directory.name))
    store = StateStore(tmp_path / "state", directory.name)
    store.initialize("test-run", "semi", source_root=str(source),
        implementation_target="sources/a", workspace_root=str(tmp_path),
        delivery_stack_snapshot=_delivery_stack_snapshot(resolve_verification_stacks(tmp_path, source)))
    before = deepcopy(store.read()["delivery_stack_snapshot"])
    if change == "selection":
        select(tmp_path, ["generic"])
    elif change == "source_empty":
        select(source, [])
    else:
        raw["coverage_observers"][0]["command"] += " --different"
        path.write_text(yaml.safe_dump(raw))
    reason = ctrl._verification_admission(context, store)
    assert reason
    assert store.read()["delivery_stack_snapshot"] == before


def test_delivery_prompt_uses_the_admitted_source_contract(tmp_path, monkeypatch):
    from harness.state import StateStore

    custom_stack(tmp_path)
    select(tmp_path, ["generic"])
    select(tmp_path / "sources/a", ["custom"])
    directory = spec(tmp_path, targets=("sources/a",))
    monkeypatch.setenv("ECHELON_SOURCE_ROOT", str(tmp_path / "sources/a"))
    ctrl = delivery(tmp_path)
    context = ctrl._resolve_run_context(RunIntent(spec_id=directory.name))
    assert ctrl._verification_admission(context, StateStore(tmp_path / "state", directory.name)) is None
    prompt = ctrl._build_stack_context(directory)
    assert "Custom verification" in prompt
    assert "Generic" not in prompt


def test_direct_delivery_cannot_use_workspace_contract_for_unbound_target(tmp_path):
    from harness.state import StateStore

    custom_stack(tmp_path)
    select(tmp_path, ["custom"])
    directory = spec(tmp_path, targets=("sources/a",))
    ctrl = delivery(tmp_path)
    context = ctrl._resolve_run_context(RunIntent(spec_id=directory.name))
    reason = ctrl._verification_admission(context, StateStore(tmp_path / "state", directory.name))
    assert reason and "source" in reason


def test_spec_prompt_uses_source_owner_instead_of_workspace(tmp_path):
    custom_stack(tmp_path)
    select(tmp_path, ["generic"])
    select(tmp_path / "sources/a", ["custom"])
    directory = spec(tmp_path, targets=("sources/a",))
    ctrl, _, _ = squad_controller(tmp_path)
    prompt = ctrl._executors["agent"]._stack_context(str(directory))
    assert "Custom verification" in prompt
    assert "Generic" not in prompt


def test_spec_browser_visual_guidance_separates_source_cases_from_controller_receipt(tmp_path):
    select(tmp_path / "sources/demo", ["browser-threejs-npm"])
    directory = spec(tmp_path, targets=("sources/demo",), types=("e2e",))
    ctrl, _, _ = squad_controller(tmp_path)

    prompt = " ".join(ctrl._executors["agent"]._stack_context(str(directory)).split())

    assert "[echelon:<case-id>]" in prompt
    assert "candidate-authored Playwright tests" in prompt
    assert "controller-owned semantic visual receipt is not a source test" in prompt
    assert "normal Playwright run" in prompt
    assert "timed and resized screenshots" in prompt


def test_supported_contract_reaches_real_first_delivery_dispatch(slice_project, monkeypatch):
    import shutil
    from tests.unit.test_delivery_controller import MockProvider, _initialize_git_worktree
    from tests.unit.test_delivery_controller_integration import _admit_delivery_fixture
    from tests.unit.test_delivery_slice_recovery import ProcessLost

    root, directory, _ = slice_project
    owner = root.parent
    shutil.copytree(root / ".echelon", owner / ".echelon")
    _admit_delivery_fixture(slice_project, owner)
    _initialize_git_worktree(root)
    def stop_at_external_dispatch(assignment, payload, candidate):
        raise ProcessLost("admission probe reached provider")
    executor = ScriptedExecutor(stop_at_external_dispatch)
    monkeypatch.setattr("harness.delivery_controller.AICodingCliProvider", lambda config: executor)
    ctrl = delivery(owner)
    ctrl._gitops.create_worktree.return_value = str(root)
    ctrl._provider = MockProvider()
    with pytest.raises(ProcessLost, match="admission probe"):
        ctrl.run(RunIntent(spec_id=directory.name, max_outer=1, max_inner=1))
    assert _steps(executor) == ["implementer"]
    assert ctrl.state()["delivery_slice_operation"]["id"]
    assert ctrl.state()["delivery_stack_snapshot"]["resolved_stack_hash"]


@pytest.mark.parametrize("missing", ["none", "role", "readonly", "executor"])
def test_semantic_visual_availability_requires_role_and_supported_executor(slice_project, missing):
    import shutil
    from harness.semantic_visual_validator import semantic_visual_execution_available

    root = slice_project[0]
    if missing != "role":
        role = Path(__file__).resolve().parents[2] / "prosaic/subagents/echelon.delivery-visual-validator.md"
        shutil.copy2(role, root / ".echelon/prosaic/subagents" / role.name)
    config = HarnessConfig()
    config.llm.enabled = missing != "executor"
    executor = ScriptedExecutor()
    executor.supports_read_only_review = missing != "readonly"
    assert semantic_visual_execution_available(root, config=config, executor=executor) is (missing == "none")


def test_controller_recovers_receipt_then_blocks_current_contract_drift(slice_project, monkeypatch):
    import shutil
    from tests.unit.test_delivery_controller import MockProvider, _initialize_git_worktree
    from tests.unit.test_delivery_controller_integration import _admit_delivery_fixture
    from tests.unit.test_delivery_slice_recovery import ProcessLost, _crash_after_receipt

    root, directory, _ = slice_project
    owner = root.parent
    shutil.copytree(root / ".echelon", owner / ".echelon")
    _admit_delivery_fixture(slice_project, owner)
    _initialize_git_worktree(root)
    def make_controller():
        ctrl = delivery(owner)
        ctrl._provider = MockProvider()
        ctrl._gitops.create_worktree.return_value = str(root)
        ctrl._gitops.get_latest_worktree.return_value = str(root)
        return ctrl
    first = ScriptedExecutor()
    monkeypatch.setattr("harness.delivery_controller.AICodingCliProvider", lambda config: first)
    with monkeypatch.context() as crash:
        _crash_after_receipt(crash, 1)
        with pytest.raises(ProcessLost):
            make_controller().run(RunIntent(spec_id=directory.name, max_outer=1, max_inner=1))
    journal = next(owner.glob("runs/**/journal.json"))
    before = json.loads(journal.read_text())
    select(owner, ["generic"])
    resumed = ScriptedExecutor()
    monkeypatch.setattr("harness.delivery_controller.AICodingCliProvider", lambda config: resumed)
    result = make_controller().run(RunIntent(spec_id=directory.name, resume=True, max_outer=1, max_inner=1))
    after = json.loads(journal.read_text())
    assert result.status == "blocked"
    assert result.termination_reason == "verification_prerequisite"
    assert resumed.calls == []
    assert after["records"] == before["records"]
    assert after["input_fingerprint"] == before["input_fingerprint"]
    assert after["binding"] == before["binding"]
    select(owner, ["custom"])
    restored = ScriptedExecutor()
    monkeypatch.setattr("harness.delivery_controller.AICodingCliProvider", lambda config: restored)
    with monkeypatch.context() as crash:
        _crash_after_receipt(crash, 2)
        with pytest.raises(ProcessLost):
            make_controller().run(RunIntent(spec_id=directory.name, resume=True, max_outer=1, max_inner=1))
    assert _steps(restored) == ["spec_guard"]
    assert json.loads(journal.read_text())["records"][0] == before["records"][0]


@pytest.mark.parametrize("effect", ["publication", "review"])
def test_sealed_delivery_effects_settle_before_current_contract_admission(tmp_path, monkeypatch, effect):
    import subprocess
    from harness.product_inventory import product_evidence_fingerprint
    from harness.review_loop import ReviewLoopController
    from harness.state import StateStore
    from tests.unit.test_delivery_controller import _initialize_git_worktree

    owner = tmp_path / "owner"
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "product.txt").write_text("verified product\n")
    _initialize_git_worktree(candidate)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=candidate, text=True).strip()
    custom_stack(owner)
    select(owner, ["custom"])
    directory = spec(owner)
    ctrl = delivery(owner)
    ctrl._gitops.create_draft_pr.return_value = None
    executor = ScriptedExecutor()
    monkeypatch.setattr("harness.delivery_controller.AICodingCliProvider", lambda config: executor)
    store = StateStore(ctrl._state_dir, directory.name)
    store.initialize("sealed-effects", "semi", source_root=str(owner),
                     delivery_stack_snapshot=_delivery_stack_snapshot(resolve_verification_stacks(owner, owner)))
    store.transition("running")
    state = store.read()
    state.update(status="blocked", blocked_phase="implementation" if effect == "publication" else "review",
                 termination_reason="publish_failed" if effect == "publication" else "review_side_effects_pending",
                 last_verify_result={"passed": True},
                 registered_worktree=str(candidate), verified_commit=commit,
                 enabled_phases=["implementation", "review", "finalization"],
                 delivery_slice_operation={"id": "settled", "progress_applied": True})
    if effect == "publication":
        state["verified_publish_checkpoint"] = {
            "schema_version": 1, "stage": "pr", "worktree_path": str(candidate),
            "branch": "main", "commit": commit,
            "product_evidence_fingerprint": product_evidence_fingerprint(candidate),
        }
    else:
        state["pending_review_reentry"] = {
            "attempt_id": "settled-review", "task_ids": ["T-001"],
            "artifact_paths": [], "phase1_verified": True,
        }
        review = ReviewLoopController(gitops=ctrl._gitops, config=ctrl._config,
                                      spec_id=directory.name, base_dir=str(owner), spec_dir=directory)
        review._save_pending_batch("settled-review", {
            "review_requested": True, "comment_ids": [], "resolved_comment_ids": [],
        })
    store.write(state)
    select(owner, ["generic"])

    result = ctrl.run(RunIntent(spec_id=directory.name, resume=True))

    after = store.read()
    if effect == "publication":
        assert "verified_publish_checkpoint" not in after
        assert after["verified_publish_recovery"]["status"] == "completed"
        ctrl._gitops.create_draft_pr.assert_called_once()
    else:
        assert after["pending_review_reentry"] is None
    assert result.status == "blocked"
    assert "coverage_observer_unavailable" in result.termination_reason
    assert executor.calls == []
    assert after["delivery_stack_snapshot"] == state["delivery_stack_snapshot"]


def test_spec_rechecks_owner_after_settling_previous_phase(tmp_path, monkeypatch):
    from harness.phase_graph import PhaseGraph
    from harness.squad import SquadController
    from harness.squad_provider import SquadAgentResult
    from harness.squad_state import SquadStateStore
    from tests.unit.test_spec_stack_prerequisites import ROOT

    monkeypatch.setenv("ECHELON_SQUAD_ACTIVE", "")
    select(tmp_path, ["generic"])
    definition = tmp_path / "workflow.yaml"
    definition.write_text(yaml.safe_dump({"phases": [
        {"id": "probe-first", "type": "agent", "agent": "echelon.scout",
         "artifact_contract": {"mode": "result_only"}, "allowed_state_updates": [],
         "allowed_verdicts": ["DONE"], "transitions": [{"condition": "always", "to": "probe-second"}]},
        {"id": "probe-second", "type": "agent", "agent": "echelon.scout",
         "artifact_contract": {"mode": "result_only"}, "allowed_state_updates": [],
         "allowed_verdicts": ["DONE"], "transitions": [{"condition": "always", "to": "done"}]},
    ]}))
    provider = MagicMock()
    def respond(*args, **kwargs):
        select(tmp_path, [])
        return SquadAgentResult(exit_code=0, echelon_result={"verdict": "DONE", "state_updates": {}},
                                raw_output="", duration_ms=1, timed_out=False)
    provider.exec_agent.side_effect = respond
    store = SquadStateStore(tmp_path / "runs/spec-probe")
    ctrl = SquadController(provider=provider, state_store=store,
        phase_graph=PhaseGraph(definition, prosaic_subagents_dir=ROOT / "prosaic/subagents"),
        ext_dir=ROOT / "runtime", project_root=tmp_path, squad_dir=store.squad_dir, token_budget=0)
    result = ctrl.run(user_message="Discover", mode="semi")
    assert result.status == "blocked"
    assert "stack_selection_required" in result.summary
    assert provider.exec_agent.call_count == 1
    state = store.load()
    assert state["phase"] == "probe-second"
    assert "pending_spec_step" not in state
    assert state["last_dispatch"]["phase_id"] == "probe-first"
