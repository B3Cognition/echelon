"""Lock hierarchy guards for squad-controller durable side effects."""

from __future__ import annotations

import inspect
import re
import threading
from contextlib import ExitStack, contextmanager

import pytest

import echelon.spec_lifecycle as spec_lifecycle_module
import echelon.telemetry.store as telemetry_store_module
import harness.phase_checkpoints as checkpoints_module
import harness.reasoning_journal_store as journal_store_module
import harness.squad as squad_module
import harness.squad_publication as publication_module
import harness.squad_state as state_module
from harness.controller_lock_order import (
    CONTROLLER_LOCK_RANKS,
    LockOrderViolation,
    controller_lock_order,
)
from harness.reasoning_journal_store import reasoning_journal_lock
from harness.squad_state import SquadStateStore


def test_controller_lock_ranks_are_complete_and_globally_ordered() -> None:
    assert CONTROLLER_LOCK_RANKS == {
        "phase_a": 1,
        "spec_run": 2,
        "publication": 3,
        "completion": 4,
        "checkpoint": 5,
        "journal": 6,
        "telemetry": 7,
        "state": 8,
    }


def test_lock_order_rejects_inversion_before_the_inner_lock_is_entered() -> None:
    inner_entered = False

    with controller_lock_order("state", "state-a"):
        with pytest.raises(LockOrderViolation, match="state.*journal"):
            with controller_lock_order("journal", "journal-a"):
                inner_entered = True

    assert not inner_entered


def test_same_rank_reentry_requires_the_exact_lock_identity() -> None:
    with controller_lock_order("telemetry", "telemetry-a"):
        with controller_lock_order("telemetry", "telemetry-a"):
            pass
        with pytest.raises(
            LockOrderViolation,
            match="same-rank.*telemetry-a.*telemetry-b",
        ):
            with controller_lock_order("telemetry", "telemetry-b"):
                pass


def test_lock_order_stack_unwinds_after_body_exception() -> None:
    with pytest.raises(RuntimeError, match="body failure"):
        with controller_lock_order("state", "state-a"):
            raise RuntimeError("body failure")

    with controller_lock_order("phase_a", "phase-a"):
        pass


def test_shared_journal_writer_participates_in_the_rank_six_guard(
    tmp_path,
) -> None:
    squad_dir = tmp_path / "run"
    squad_dir.mkdir()

    with controller_lock_order("state", "state-a"):
        with pytest.raises(LockOrderViolation, match="state.*journal"):
            with reasoning_journal_lock(squad_dir):
                pass


def test_state_store_acquires_the_terminal_state_rank(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SquadStateStore(tmp_path / "run")
    observed: list[tuple[str, str]] = []
    original = state_module.controller_lock_order

    @contextmanager
    def observe(name: str, identity: str):
        observed.append((name, identity))
        with original(name, identity):
            yield

    monkeypatch.setattr(state_module, "controller_lock_order", observe)
    assert store.load() == {}

    assert observed == [
        ("state", str(store._lock_path.absolute())),
    ]


def test_state_store_exposes_no_callback_executor_under_its_file_lock() -> None:
    assert not hasattr(SquadStateStore, "_mutate")
    assert "Callable[" not in inspect.getsource(SquadStateStore)


@pytest.mark.parametrize(
    ("rank", "acquire"),
    [
        (
            "phase_a",
            lambda root: spec_lifecycle_module.PhaseAExecutionLock.acquire(
                root,
                "phase-a-test",
            ),
        ),
        (
            "spec_run",
            lambda root: spec_lifecycle_module.SpecRunExecutionLock.acquire(
                root / "run",
                "spec-run-test",
            ),
        ),
    ],
)
def test_execution_lock_owners_reject_acquisition_under_state(
    tmp_path,
    rank,
    acquire,
) -> None:
    acquired = None
    try:
        with controller_lock_order("state", "state-a"):
            with pytest.raises(
                LockOrderViolation,
                match=rf"state.*{rank}",
            ):
                acquired = acquire(tmp_path)
    finally:
        if acquired is not None:
            acquired.release()


def test_all_controller_lock_owners_are_bound_to_the_global_guard() -> None:
    owners = {
        squad_module: ("completion", "telemetry"),
        publication_module: ("publication",),
        checkpoints_module: ("checkpoint",),
        journal_store_module: ("journal",),
        telemetry_store_module: ("telemetry",),
        state_module: ("state",),
    }

    for module, ranks in owners.items():
        source = inspect.getsource(module)
        for rank in ranks:
            assert re.search(
                rf'controller_lock_order\(\s*"{rank}",',
                source,
            )
    lifecycle_source = inspect.getsource(spec_lifecycle_module)
    for rank in ("phase_a", "spec_run"):
        assert f'controller_rank="{rank}"' in lifecycle_source


@pytest.mark.parametrize(
    ("outer", "inner"),
    [
        ("phase_a", "spec_run"),
        ("spec_run", "publication"),
        ("publication", "completion"),
        ("completion", "checkpoint"),
        ("checkpoint", "journal"),
        ("journal", "telemetry"),
        ("telemetry", "state"),
    ],
)
def test_every_nested_lock_pair_completes_two_contending_threads(
    outer: str,
    inner: str,
) -> None:
    """Each approved nesting stays live when two threads contend."""
    physical = {
        outer: threading.Lock(),
        inner: threading.Lock(),
    }
    first_holds_outer = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    complete = [threading.Event(), threading.Event()]
    failures: list[BaseException] = []

    def acquire_pair(index: int) -> None:
        try:
            if index == 1:
                assert first_holds_outer.wait(timeout=2)
                second_started.set()
            with ExitStack() as stack:
                stack.enter_context(
                    controller_lock_order(outer, f"{outer}-lock")
                )
                stack.enter_context(physical[outer])
                if index == 0:
                    first_holds_outer.set()
                    assert second_started.wait(timeout=2)
                    assert release_first.wait(timeout=2)
                stack.enter_context(
                    controller_lock_order(inner, f"{inner}-lock")
                )
                stack.enter_context(physical[inner])
                complete[index].set()
        except BaseException as error:  # pragma: no cover - reported below
            failures.append(error)

    workers = [
        threading.Thread(target=acquire_pair, args=(index,))
        for index in range(2)
    ]
    for worker in workers:
        worker.start()
    assert first_holds_outer.wait(timeout=2)
    assert second_started.wait(timeout=2)
    release_first.set()
    for worker in workers:
        worker.join(timeout=3)

    assert not failures
    assert all(event.is_set() for event in complete)
    assert all(not worker.is_alive() for worker in workers)


@pytest.mark.parametrize(
    ("outer", "inner"),
    [
        ("spec_run", "phase_a"),
        ("publication", "spec_run"),
        ("completion", "publication"),
        ("checkpoint", "completion"),
        ("journal", "checkpoint"),
        ("telemetry", "journal"),
        ("state", "telemetry"),
    ],
)
def test_every_reverse_nested_pair_fails_before_inner_entry(
    outer: str,
    inner: str,
) -> None:
    inner_entered = False

    with controller_lock_order(outer, f"{outer}-lock"):
        with pytest.raises(LockOrderViolation):
            with controller_lock_order(inner, f"{inner}-lock"):
                inner_entered = True

    assert inner_entered is False
