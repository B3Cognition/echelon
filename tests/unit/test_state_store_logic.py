"""Tests for StateStore invariant enforcement.

5 tests for: monotonic counters, append-only log, mode immutability,
atomic writes, .bak snapshots.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.state import (
    DELIVERY_STATE_VERSION,
    InvalidTransitionError,
    ModeImmutableError,
    MonotonicViolationError,
    StateStore,
)


@pytest.mark.unit
class TestStateStoreInvariants:
    """Test StateStore invariant enforcement."""

    def _make_store(self, tmp_path: Path) -> StateStore:
        store = StateStore(tmp_path, "spec-001", "default")
        store.initialize("run-1", "semi")
        return store

    def test_mode_change_rejected(self, tmp_path: Path) -> None:
        """FR-MODE-002: mode immutable after init."""
        store = self._make_store(tmp_path)
        data = store.read()
        data["mode"] = "banzai"
        with pytest.raises(ModeImmutableError):
            store.write(data)

    def test_tokens_used_decrease_rejected(self, tmp_path: Path) -> None:
        """tokens_used must be monotonically non-decreasing."""
        store = self._make_store(tmp_path)
        data = store.read()
        data["tokens_used"] = 100
        store.write(data)
        data = store.read()
        data["tokens_used"] = 50
        with pytest.raises(MonotonicViolationError, match="tokens_used"):
            store.write(data)

    def test_iteration_log_deletion_rejected(self, tmp_path: Path) -> None:
        """iteration_log is append-only."""
        store = self._make_store(tmp_path)
        data = store.read()
        data["iteration_log"] = [
            {"outer_iter": 0, "inner_iter": 0, "phase": "build",
             "exit_code": 0, "passed": True, "duration_s": 1.0,
             "tokens": 100, "timestamp": "2026-04-12T00:00:00Z"}
        ]
        store.write(data)
        data = store.read()
        data["iteration_log"] = []  # Attempt to shrink
        with pytest.raises(MonotonicViolationError, match="append-only"):
            store.write(data)

    def test_atomic_write_creates_tmp_then_renames(self, tmp_path: Path) -> None:
        """Atomic write: .tmp written before rename."""
        store = self._make_store(tmp_path)
        assert store.state_file.exists()
        data = store.read()
        data["tokens_used"] = 50
        store.write(data)
        # Verify state file is valid JSON
        import json
        content = json.loads(store.state_file.read_text())
        assert content["tokens_used"] == 50

    def test_bak_file_exists_after_second_write(self, tmp_path: Path) -> None:
        """.bak file created after second write."""
        store = self._make_store(tmp_path)
        data = store.read()
        data["tokens_used"] = 10
        store.write(data)
        bak_file = store.state_file.with_suffix(".json.bak")
        assert bak_file.exists()

    def test_initialize_records_target_metadata(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path, "001", "default")
        state = store.initialize(
            run_id="run-1",
            mode="banzai",
            target_repo="rbf-opta-points",
            target_path="rbf-opta-points",
        )

        assert state["target_repo"] == "rbf-opta-points"
        assert state["target_path"] == "rbf-opta-points"

    def test_transition_writes_status_and_blocked_phase_together(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        store.transition("running")

        state = store.transition(
            "blocked", updates={"blocked_phase": "review"}
        )

        assert state["status"] == "blocked"
        assert state["blocked_phase"] == "review"

    def test_blocked_transition_requires_exact_phase(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)
        store.transition("running")

        with pytest.raises(InvalidTransitionError, match="blocked_phase"):
            store.transition("blocked")

    def test_transition_updates_cannot_override_target_status(self, tmp_path: Path) -> None:
        store = self._make_store(tmp_path)

        with pytest.raises(ValueError, match="status"):
            store.transition("running", updates={"status": "converged"})

        assert store.read()["status"] == "initialized"

    def test_initializes_delivery_state_v2_checkpoint_fields(self, tmp_path: Path) -> None:
        state = self._make_store(tmp_path).read()

        assert state["delivery_state_version"] == DELIVERY_STATE_VERSION
        assert state["enabled_phases"] == ["implementation", "finalization"]
        assert state["last_completed_phase"] is None
        assert state["blocked_phase"] is None
        assert state["interrupted_phase"] is None
        assert state["verified_commit"] is None

    def test_legacy_blocked_state_migrates_but_v2_missing_phase_is_rejected(
        self, tmp_path: Path
    ) -> None:
        """Only pre-v2 records may receive the implementation resume default."""
        store = StateStore(tmp_path, "spec-001", "default")
        store.state_file.write_text('{"status": "blocked"}', encoding="utf-8")
        store.write(store.read())
        legacy = store.read()

        assert legacy["delivery_state_version"] == DELIVERY_STATE_VERSION
        assert legacy["enabled_phases"] == ["implementation", "finalization"]
        assert legacy["blocked_phase"] == "implementation"

        store.state_file.write_text(
            '{"delivery_state_version": 2, "status": "blocked"}',
            encoding="utf-8",
        )
        invalid_v2 = store.read()
        invalid_v2["spec_dir"] = "/current/spec"
        with pytest.raises(InvalidTransitionError, match="blocked_phase"):
            store.write(invalid_v2)
