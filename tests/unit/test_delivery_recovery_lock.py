"""Only the controller that owns the run may record execution failure."""
import pytest
from harness.run_intent import RunIntent
from harness.state import StateStore, LockContentionError, state_lock_owner_is_alive
from tests.unit.test_delivery_controller import _make_controller


@pytest.mark.parametrize("status,phase", [("running", "implementation"), ("reviewing", "review")])
def test_execution_exception_blocks_at_owned_phase(tmp_path, monkeypatch, status, phase):
    controller = _make_controller(tmp_path)
    store = StateStore(controller._state_dir, "001")
    store.initialize("owned", "semi", enabled_phases=["implementation", "review", "finalization"])
    store.transition("running")
    if status == "reviewing":
        store.transition("verified")
        store.transition("reviewing")
    state = store.read()
    state.update(status=status, tokens_used=123, outer_iter=2)
    store.write(state)
    def crash(**kwargs):
        assert state_lock_owner_is_alive(store.state_file)
        raise RuntimeError("unexpected execution error")
    monkeypatch.setattr(controller, "_run_delivery_phases", crash)
    with pytest.raises(RuntimeError, match="unexpected execution"):
        controller.run(RunIntent("001", resume=True))
    state = store.read()
    assert state["status"] == "blocked"
    assert state["termination_reason"] == "harness_error"
    assert state["blocked_phase"] == phase
    assert state["tokens_used"] == 123
    assert state["outer_iter"] == 2
    assert not state_lock_owner_is_alive(store.state_file)


def test_lock_rejection_does_not_rewrite_active_run(tmp_path):
    controller = _make_controller(tmp_path)
    store = StateStore(controller._state_dir, "001")
    store.initialize("owned", "semi")
    store.transition("running")
    before = store.state_file.read_bytes()
    store.acquire_lock("owned")
    try:
        with pytest.raises(LockContentionError):
            controller.run(RunIntent("001", resume=True))
        assert store.state_file.read_bytes() == before
        assert state_lock_owner_is_alive(store.state_file)
    finally:
        store.release_lock()
