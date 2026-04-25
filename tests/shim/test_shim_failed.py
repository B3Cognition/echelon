"""Test shim failed path: manifest exists + Docker down -> hard error.

FR-FALLBACK-FAILED-001: NEVER fall back to host execution.
"""

from __future__ import annotations

import json
import subprocess

import pytest


class TestShimFailed:
    """Tests for failed path (harness installed, sandbox unavailable)."""

    def test_failed_path_hard_error(self, shim_script, harness_dir_with_manifest):
        """Manifest exists + no HARNESS_SANDBOX_ID -> hard error JSON, exit 1."""
        result = subprocess.run(
            ["bash", shim_script, "echo should-not-run"],
            capture_output=True,
            text=True,
            cwd=str(harness_dir_with_manifest),
            timeout=10,
            env={
                "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                "HOME": str(harness_dir_with_manifest),
                # Intentionally NOT setting HARNESS_SANDBOX_ID
            },
        )

        assert result.returncode == 1
        # stderr should contain the hard error JSON
        error_json = json.loads(result.stderr.strip())
        assert error_json["exit_code"] == 1
        assert "sandbox" in error_json["stderr"].lower()
        assert "unavailable" in error_json["stderr"].lower()
