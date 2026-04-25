"""Test shim routing: command reaches Docker container when harness operational.

This test requires Docker to be running.
"""

from __future__ import annotations

import json
import subprocess

import pytest


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=10, check=False,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
class TestShimRouting:
    """Tests for sandbox routing path."""

    def test_command_reaches_container(self, shim_script, harness_dir_with_manifest):
        """Command reaches Docker container when harness operational."""
        # Start a test container
        container_result = subprocess.run(
            ["docker", "run", "-d", "--rm", "alpine:latest", "tail", "-f", "/dev/null"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        container_id = container_result.stdout.strip()

        try:
            result = subprocess.run(
                ["bash", shim_script, "echo hello-from-sandbox"],
                capture_output=True,
                text=True,
                cwd=str(harness_dir_with_manifest),
                timeout=30,
                env={
                    "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                    "HOME": str(harness_dir_with_manifest),
                    "HARNESS_SANDBOX_ID": container_id,
                    "HARNESS_WORKDIR": "/",
                },
            )

            assert result.returncode == 0
            exec_result = json.loads(result.stdout.strip())
            assert exec_result["exit_code"] == 0
            assert "hello-from-sandbox" in exec_result["stdout"]

        finally:
            subprocess.run(
                ["docker", "rm", "-f", container_id],
                capture_output=True, check=False, timeout=10,
            )
