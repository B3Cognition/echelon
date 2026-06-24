"""Opt-in Docker smoke for harness.app visual runtime lifecycle."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from harness.config import AppRuntimeConfig, HarnessConfig, VisualTestsConfig
from harness.docker_provider import DockerWorktreeProvider
from harness.visual_ralph import VisualRalphController


PLAYWRIGHT_IMAGE = "mcr.microsoft.com/playwright:v1.42.0-jammy"


def _docker_available() -> bool:
    try:
        return subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
            check=False,
        ).returncode == 0
    except FileNotFoundError:
        return False


def _image_available(image: str) -> bool:
    try:
        return subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            timeout=10,
            check=False,
        ).returncode == 0
    except FileNotFoundError:
        return False


@pytest.mark.integration
def test_visual_runtime_command_lifecycle_with_real_docker(tmp_path: Path) -> None:
    if not _docker_available():
        pytest.skip("Docker is not reachable")
    if not _image_available(PLAYWRIGHT_IMAGE):
        pytest.skip(f"Required local Docker image is missing: {PLAYWRIGHT_IMAGE}")

    (tmp_path / "server.js").write_text(
        """
const http = require('http');
const server = http.createServer((_req, res) => {
  res.writeHead(200, {'content-type': 'text/plain'});
  res.end('ok');
});
server.listen(4173, '127.0.0.1');
""",
        encoding="utf-8",
    )
    (tmp_path / "playwright-result.json").write_text(
        json.dumps({"suites": [], "errors": []}),
        encoding="utf-8",
    )

    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        base_image=PLAYWRIGHT_IMAGE,
        visual_tests=VisualTestsConfig(
            enabled=True,
            test_command="cat /workspace/playwright-result.json",
            max_iterations=1,
            timeout_ms=30_000,
        ),
        app=AppRuntimeConfig(
            enabled=True,
            mode="command",
            app="fixture",
            setup_commands=["node --version"],
            start_commands=["node server.js"],
            stop_commands=[],
            url="http://127.0.0.1:4173",
            readiness_timeout_ms=30_000,
        ),
    )
    provider = DockerWorktreeProvider()
    controller = VisualRalphController(
        provider=provider,
        config=config,
        spec_id="smoke",
        strategy_id="docker",
    )

    result = controller.run_loop(str(tmp_path))

    assert result.status == "converged"
    assert result.termination_reason == "converged"
