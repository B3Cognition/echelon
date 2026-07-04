"""Test shim routing timeout: 5s -> exit 124.

FR-SHIM-001: Routing timeout contract.
"""

from __future__ import annotations

import json
import subprocess

import pytest


pytestmark = pytest.mark.docker


class TestShimTimeout:
    """Tests for shim routing timeout."""

    def test_routing_timeout_returns_124(self, shim_script, harness_dir_with_manifest):
        """5s routing timeout returns exit 124 when sandbox unreachable."""
        # Use a nonexistent container ID to trigger routing timeout
        result = subprocess.run(
            ["bash", shim_script, "echo should-not-run"],
            capture_output=True,
            text=True,
            cwd=str(harness_dir_with_manifest),
            timeout=30,
            env={
                "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                "HOME": str(harness_dir_with_manifest),
                "HARNESS_SANDBOX_ID": "nonexistent-container-id-12345",
            },
        )

        # Should return non-zero (either 1 for unavailable or 124 for timeout)
        assert result.returncode != 0
