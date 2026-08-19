"""Run-local execution lease coverage for Phase A controllers."""

from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread
from unittest.mock import MagicMock

import pytest

from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
from harness.human_input import HumanInputPolicyRegistry
from harness.squad import SquadController
from harness.squad_state import SquadStateStore


@contextmanager
def _external_execution_owner(run_dir: Path):
    acquired = Event()
    release = Event()
    failures: list[BaseException] = []

    def hold() -> None:
        try:
            with SpecRunExecutionLock.acquire(
                run_dir,
                "other-owner",
            ):
                acquired.set()
                assert release.wait(timeout=5)
        except BaseException as error:
            failures.append(error)
            acquired.set()

    owner = Thread(target=hold)
    owner.start()
    assert acquired.wait(timeout=5)
    assert not failures
    try:
        yield
    finally:
        release.set()
        owner.join(timeout=5)
        assert not failures
        assert not owner.is_alive()


@contextmanager
def _external_phase_a_owner(project_root: Path):
    acquired = Event()
    release = Event()
    failures: list[BaseException] = []

    def hold() -> None:
        try:
            with PhaseAExecutionLock.acquire(project_root, "other-owner"):
                acquired.set()
                assert release.wait(timeout=5)
        except BaseException as error:
            failures.append(error)
            acquired.set()

    owner = Thread(target=hold)
    owner.start()
    assert acquired.wait(timeout=5)
    assert not failures
    try:
        yield
    finally:
        release.set()
        owner.join(timeout=5)
        assert not failures
        assert not owner.is_alive()


class _TerminalGraph:
    def entry_phase(self) -> str:
        return "DONE"

    def all_phase_ids(self) -> set[str]:
        return {"DONE"}

    def human_input_policy_registry(self) -> HumanInputPolicyRegistry:
        return HumanInputPolicyRegistry(())


def _controller(tmp_path: Path) -> tuple[SquadController, SquadStateStore, MagicMock]:
    run_dir = tmp_path / "runs" / "run-a"
    store = SquadStateStore(run_dir)
    provider = MagicMock()
    controller = SquadController(
        provider=provider,
        state_store=store,
        phase_graph=_TerminalGraph(),
        ext_dir=tmp_path / "extension",
        project_root=tmp_path,
        squad_dir=run_dir,
    )
    return controller, store, provider


@pytest.mark.unit
def test_run_refuses_a_live_execution_owner_before_state_or_provider_mutation(
    tmp_path: Path,
) -> None:
    controller, store, provider = _controller(tmp_path)
    before = store.load()

    with _external_execution_owner(store.squad_dir):
        result = controller.run(user_message="Build export API")

    assert result.status == "busy"
    assert result.run_id == store.squad_dir.name
    assert store.load() == before
    provider.exec_agent.assert_not_called()


@pytest.mark.unit
def test_manual_phase_refuses_a_live_execution_owner_before_state_mutation(
    tmp_path: Path,
) -> None:
    controller, store, provider = _controller(tmp_path)
    before = store.load()

    with _external_execution_owner(store.squad_dir):
        result = controller.run_single_phase("DONE", user_message="Build export API")

    assert result.status == "busy"
    assert result.run_id == store.squad_dir.name
    assert store.load() == before
    provider.exec_agent.assert_not_called()


@pytest.mark.unit
def test_run_refuses_a_live_phase_a_owner_before_state_or_provider_mutation(
    tmp_path: Path,
) -> None:
    controller, store, provider = _controller(tmp_path)
    before = store.load()

    with PhaseAExecutionLock.acquire(tmp_path, "other-workspace-owner"):
        result = controller.run(user_message="Build export API")

    assert result.status == "busy"
    assert result.run_id == store.squad_dir.name
    assert store.load() == before
    provider.exec_agent.assert_not_called()


@pytest.mark.unit
def test_phase_a_execution_lease_is_independent_per_worktree(
    tmp_path: Path,
) -> None:
    first_worktree = tmp_path / "worktree-a"
    second_worktree = tmp_path / "worktree-b"

    with _external_phase_a_owner(first_worktree):
        with PhaseAExecutionLock.acquire(second_worktree, "owner-b") as second:
            assert second.path.is_dir()
            assert not second.path.is_relative_to(first_worktree)
