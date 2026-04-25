"""Test shim absent path: no manifest.json -> transparent host execution.

FR-FALLBACK-ABSENT: zero warnings, zero errors.
"""

from __future__ import annotations

import json
import subprocess

import pytest


class TestShimAbsent:
    """Tests for absent path (no harness manifest)."""

    def test_absent_path_runs_on_host(self, shim_script, harness_dir_without_manifest):
        """No manifest.json -> command runs on host, zero errors/warnings."""
        result = subprocess.run(
            ["bash", shim_script, "echo hello-from-host"],
            capture_output=True,
            text=True,
            cwd=str(harness_dir_without_manifest),
            timeout=10,
            env={
                "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                "HOME": str(harness_dir_without_manifest),
            },
        )

        assert result.returncode == 0
        # stdout should be valid JSON ExecResult
        exec_result = json.loads(result.stdout.strip())
        assert exec_result["exit_code"] == 0
        assert "hello-from-host" in exec_result["stdout"]
        # stderr should be empty (no warnings)
        assert result.stderr == ""
