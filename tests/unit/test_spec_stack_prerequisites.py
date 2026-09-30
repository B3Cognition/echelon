"""Real owner configuration and dispatch-boundary stack prerequisites."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from harness.phase_graph import PhaseGraph
from harness.squad import SquadController
from harness.squad_provider import SquadAgentResult
from harness.squad_state import SquadStateStore
from harness.stacks.errors import StackError
from harness import verification_stack_runtime as runtime

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def isolate_squad_environment(monkeypatch):
    # The real controller sets this sentinel; restore it after each probe.
    monkeypatch.setenv("ECHELON_SQUAD_ACTIVE", "")


def select(root, ids):
    path = root / ".echelon/config.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"stacks": {"selected": ids}}))


def controller(root):
    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0, echelon_result={"verdict": "DONE", "state_updates": {}},
        raw_output="", duration_ms=1, timed_out=False,
    )
    store = SquadStateStore(root / "runs/spec-probe")
    ctrl = SquadController(
        provider=provider, state_store=store,
        phase_graph=PhaseGraph(ROOT / "runtime/workflow/definition.yaml",
                              prosaic_subagents_dir=ROOT / "prosaic/subagents"),
        ext_dir=ROOT / "runtime", project_root=root,
        squad_dir=store.squad_dir, token_budget=0,
    )
    return ctrl, store, provider


@pytest.mark.parametrize("entry", ["run", "run_single_phase"])
def test_empty_selection_blocks_before_new_state_or_provider(tmp_path, monkeypatch, entry):
    monkeypatch.delenv("ECHELON_SQUAD_ACTIVE", raising=False)
    ctrl, store, provider = controller(tmp_path)
    before = store.load()
    result = (ctrl.run(user_message="Discover a demo") if entry == "run"
              else ctrl.run_single_phase("phase1-constitution"))
    assert result.status == "blocked"
    assert "stack_selection_required" in result.summary
    assert store.load() == before
    assert provider.exec_agent.call_count == 0


def test_empty_spec_selection_is_actionable(tmp_path):
    with pytest.raises(runtime.VerificationStackResolutionError, match="stack_selection_required"):
        runtime.require_spec_stack_selection(tmp_path)


@pytest.mark.parametrize("ids", [["generic"], ["browser-3d-game"], ["generic", "browser-3d-game"]])
def test_explicit_selection_uses_real_bundled_contract(tmp_path, ids):
    select(tmp_path, ids)
    resolved, = runtime.require_spec_stack_selection(tmp_path)
    assert resolved.selected_ids == ids
    if ids == ["generic"]:
        assert not resolved.capabilities
        assert not resolved.coverage_observers
        assert not resolved.runnability.sources
        assert not resolved.required_commands
        assert not resolved.provisioners


@pytest.mark.parametrize("ids", [["unknown-stack"], ["browser-3d-game", "browser-wasm-game"]])
def test_invalid_selection_retains_resolver_error(tmp_path, ids):
    select(tmp_path, ids)
    with pytest.raises(StackError):
        runtime.require_spec_stack_selection(tmp_path)


def test_source_owned_empty_does_not_inherit_workspace_selection(tmp_path):
    select(tmp_path, ["browser-3d-game"])
    target = tmp_path / "sources/backend"
    select(target, [])
    with pytest.raises(runtime.VerificationStackResolutionError, match=str(target)):
        runtime.require_spec_stack_selection(tmp_path, target_roots=(target,))


def test_new_service_selection_does_not_allocate_without_stack(tmp_path, monkeypatch, capsys):
    from echelon.spec_service import _select_squad_dir

    monkeypatch.delenv("ECHELON_SQUAD_ACTIVE", raising=False)
    with pytest.raises(SystemExit) as failure:
        _select_squad_dir(tmp_path, "Discover a demo")
    assert failure.value.code == 2
    assert "stack_selection_required" in capsys.readouterr().err
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize("entry", ["run", "run_single_phase"])
def test_generic_reaches_real_dispatch(tmp_path, entry):
    select(tmp_path, ["generic"])
    ctrl, store, provider = controller(tmp_path)
    if entry == "run":
        ctrl.run(user_message="Discover a demo")
    else:
        ctrl.run_single_phase("phase1-constitution", user_message="Discover a demo")
    assert provider.exec_agent.call_count == 1
    assert store.load()["run_id"]


def test_source_empty_blocks_controller_even_when_workspace_selected(tmp_path):
    select(tmp_path, ["browser-3d-game"])
    select(tmp_path / "sources/api", [])
    ctrl, store, provider = controller(tmp_path)
    ctrl._implementation_targets = ["sources/api"]
    result = ctrl.run(user_message="Discover a demo")
    assert "sources/api" in result.summary
    assert "stack_selection_required" in result.summary
    assert provider.exec_agent.call_count == 0
    assert store.load() == {}


@pytest.mark.parametrize("ids", [["unknown-stack"], ["browser-3d-game", "browser-wasm-game"]])
def test_invalid_selection_blocks_dispatch(tmp_path, ids):
    select(tmp_path, ids)
    ctrl, store, provider = controller(tmp_path)
    result = ctrl.run(user_message="Discover a demo")
    assert result.status == "blocked"
    assert result.summary
    assert provider.exec_agent.call_count == 0
    assert store.load() == {}


def test_service_valid_selection_allocates_real_run(tmp_path):
    import subprocess
    from echelon.spec_service import _ensure_runs_gitignore, _select_squad_dir

    select(tmp_path, ["generic"])
    (tmp_path / "runs").mkdir()
    _ensure_runs_gitignore(tmp_path / "runs/.gitignore")
    for args in (["init", "-b", "main"], ["config", "user.name", "Test"],
                 ["config", "user.email", "test@example.test"], ["add", "."],
                 ["commit", "-m", "fixture"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    run, fresh = _select_squad_dir(tmp_path, "Discover a demo", configured_default_branch="main")
    assert fresh
    assert run.is_dir()
