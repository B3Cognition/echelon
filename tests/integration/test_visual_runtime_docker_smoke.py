"""Opt-in Docker smoke for harness.app visual runtime lifecycle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.config import AppRuntimeConfig, HarnessConfig, VisualTestsConfig
from harness.docker_provider import DockerWorktreeProvider
from harness.visual_ralph import VisualRalphController


PLAYWRIGHT_IMAGE = "mcr.microsoft.com/playwright:v1.42.0-jammy"


@pytest.mark.integration
@pytest.mark.docker
@pytest.mark.docker_image(PLAYWRIGHT_IMAGE)
def test_visual_runtime_command_lifecycle_with_real_docker(tmp_path: Path) -> None:
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
        json.dumps({
            "suites": [{
                "specs": [{
                    "title": "journey",
                    "file": "journey.spec.ts",
                    "tests": [{
                        "projectName": "chromium",
                        "expectedStatus": "passed",
                        "results": [{"status": "passed"}],
                    }],
                }],
            }],
            "errors": [],
        }),
        encoding="utf-8",
    )
    screenshot_dir = tmp_path / "playwright-report"
    screenshot_dir.mkdir()
    (screenshot_dir / "journey.png").write_bytes(b"visual-proof")

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
        base_dir=str(tmp_path),
        build_id="build-smoke",
    )

    result = controller.run_loop(str(tmp_path))

    assert result.status == "passed"
    assert result.termination_reason == "converged"
