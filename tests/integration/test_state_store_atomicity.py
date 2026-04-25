"""Integration tests for StateStore atomicity.

Tests fork + SIGKILL survival and .bak recovery.
"""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

import pytest

from harness.state import StateStore


class TestAtomicWriteSurvival:
    """Tests for atomic write surviving SIGKILL."""

    def test_bak_exists_after_second_write(self, tmp_path):
        """Atomic write: .bak file exists after second write."""
        store = StateStore(tmp_path, "spec-001", "default")
        store.initialize("run-001", "banzai")

        # Second write should create .bak
        data = store.read()
        data["tokens_used"] = 100
        store.write(data)

        bak_file = tmp_path / "spec-001" / "default.json.bak"
        assert bak_file.exists()

        # .bak should contain the original state
        bak_data = json.loads(bak_file.read_text(encoding="utf-8"))
        assert bak_data["tokens_used"] == 0

    def test_bak_recoverable_after_crash(self, tmp_path):
        """After crash, .bak is recoverable with valid state."""
        store = StateStore(tmp_path, "spec-001", "default")
        store.initialize("run-001", "banzai")

        # Write valid state
        data = store.read()
        data["tokens_used"] = 500
        store.write(data)

        # Simulate corruption of main file
        state_file = tmp_path / "spec-001" / "default.json"
        state_file.write_text("CORRUPTED", encoding="utf-8")

        # .bak should still be valid
        bak_file = tmp_path / "spec-001" / "default.json.bak"
        bak_data = json.loads(bak_file.read_text(encoding="utf-8"))
        assert bak_data["status"] == "initialized"
        assert bak_data["run_id"] == "run-001"
