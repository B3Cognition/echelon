"""Tests for state machine transition logic.

10 tests per test-strategy 3.1:
- 7 valid transitions
- 6+ invalid transition rejections
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.state import InvalidTransitionError, StateStore


@pytest.mark.parametrize("path", [
    ["running", "verified", "finalizing", "converged"],
    ["running", "verified", "validating", "finalizing", "converged"],
    ["running", "verified", "reviewing", "finalizing", "converged"],
    ["running", "verified", "validating", "reviewing", "finalizing", "converged"],
])
def test_delivery_state_paths(tmp_path: Path, path: list[str]) -> None:
    store = StateStore(tmp_path, "042", "default")
    store.initialize("run-1", "semi")
    for status in path:
        store.transition(status)
    assert store.read()["status"] == "converged"


def test_converged_cannot_reopen(tmp_path: Path) -> None:
    store = StateStore(tmp_path, "042", "default")
    store.initialize("run-1", "semi")
    for status in ("running", "verified", "finalizing", "converged"):
        store.transition(status)
    with pytest.raises(InvalidTransitionError):
        store.transition("blocked", updates={"blocked_phase": "review"})


@pytest.mark.unit
class TestValidTransitions:
    """Test all valid state transitions per data-model."""

    def _make_store(self, tmp_path: Path) -> StateStore:
        store = StateStore(tmp_path, "spec-001", "default")
        return store

    def test_initialized_to_running(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        store.initialize("run-1", "semi")
        data = store.transition("running")
        assert data["status"] == "running"

    def test_running_to_converged(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        store.initialize("run-1", "semi")
        store.transition("running")
        store.transition("verified")
        store.transition("finalizing")
        data = store.transition("converged")
        assert data["status"] == "converged"

    def test_running_to_blocked(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        store.initialize("run-1", "semi")
        store.transition("running")
        data = store.transition("blocked", updates={"blocked_phase": "implementation"})
        assert data["status"] == "blocked"

    def test_running_to_failed(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        store.initialize("run-1", "semi")
        store.transition("running")
        data = store.transition("failed")
        assert data["status"] == "failed"

    def test_running_to_interrupted(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        store.initialize("run-1", "semi")
        store.transition("running")
        data = store.transition(
            "interrupted", updates={"interrupted_phase": "implementation"}
        )
        assert data["status"] == "interrupted"

    def test_running_to_cancelled(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        store.initialize("run-1", "semi")
        store.transition("running")
        data = store.transition("cancelled_by_coordinator")
        assert data["status"] == "cancelled_by_coordinator"

    def test_blocked_to_running(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        store.initialize("run-1", "semi")
        store.transition("running")
        store.transition("blocked", updates={"blocked_phase": "implementation"})
        data = store.transition("running")
        assert data["status"] == "running"

    def test_interrupted_to_running(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        store.initialize("run-1", "semi")
        store.transition("running")
        store.transition(
            "interrupted", updates={"interrupted_phase": "implementation"}
        )
        data = store.transition("running")
        assert data["status"] == "running"


@pytest.mark.unit
class TestInvalidTransitions:
    """Test invalid state transition rejection."""

    def _make_store(self, tmp_path: Path) -> StateStore:
        store = StateStore(tmp_path, "spec-001", "default")
        return store

    def test_initialized_to_converged_rejected(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        store.initialize("run-1", "semi")
        with pytest.raises(InvalidTransitionError):
            store.transition("converged")

    def test_initialized_to_blocked_rejected(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        store.initialize("run-1", "semi")
        with pytest.raises(InvalidTransitionError):
            store.transition("blocked")

    def test_converged_to_running_rejected(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        store.initialize("run-1", "semi")
        store.transition("running")
        store.transition("verified")
        store.transition("finalizing")
        store.transition("converged")
        with pytest.raises(InvalidTransitionError):
            store.transition("running")

    def test_failed_to_running_rejected(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        store.initialize("run-1", "semi")
        store.transition("running")
        store.transition("failed")
        with pytest.raises(InvalidTransitionError):
            store.transition("running")

    def test_cancelled_to_running_rejected(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        store.initialize("run-1", "semi")
        store.transition("running")
        store.transition("cancelled_by_coordinator")
        with pytest.raises(InvalidTransitionError):
            store.transition("running")
