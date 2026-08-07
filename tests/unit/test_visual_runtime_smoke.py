"""Fixture-style smoke test for command app visual runtime lifecycle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.config import AppRuntimeConfig, HarnessConfig, VisualTestsConfig
from harness.exec_result import ExecResult, ResourceStats
from harness.provider import SandboxHandle
from harness.visual_ralph import VisualRalphController


def _ok(stdout: str = "") -> ExecResult:
    return ExecResult(
        stdout=stdout,
        stderr="",
        exit_code=0,
        duration_ms=100,
        resource_stats=ResourceStats(peak_memory_bytes=0, cpu_time_ms=0, wall_time_ms=100),
    )


class RecordingProvider:
    """Tiny provider double that records the runtime lifecycle command order."""

    def __init__(self) -> None:
        self.commands: list[str] = []
        self.destroyed = False

    def create(self, spec):
        return SandboxHandle(id="fixture-container", session_id="fixture-session")

    def exec(self, handle, cmd, cwd=None, env=None, timeout_ms=1_200_000):
        self.commands.append(cmd)
        if "playwright" in cmd:
            return _ok(json.dumps({"suites": [], "errors": []}))
        return _ok("ready")

    def write_file(self, handle, path, content):
        raise NotImplementedError

    def read_file(self, handle, path):
        raise NotImplementedError

    def destroy(self, handle):
        self.destroyed = True


@pytest.mark.unit
def test_command_app_visual_runtime_smoke_order(tmp_path: Path) -> None:
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        visual_tests=VisualTestsConfig(
            enabled=True,
            test_command="npx playwright test --reporter=json",
            max_iterations=1,
        ),
        app=AppRuntimeConfig(
            enabled=True,
            mode="command",
            app="fixture",
            setup_commands=["./scripts/setup.sh"],
            start_commands=["./scripts/start.sh"],
            stop_commands=["./scripts/stop.sh"],
            url="http://localhost:4173",
            readiness_timeout_ms=30_000,
        ),
    )
    provider = RecordingProvider()
    controller = VisualRalphController(
        provider=provider,
        config=config,
        spec_id="001",
        strategy_id="default",
    )

    result = controller.run_loop(str(tmp_path))

    assert result.status == "passed"
    assert provider.destroyed is True
    assert provider.commands[0] == "./scripts/setup.sh"
    assert "./scripts/start.sh" in provider.commands[1]
    assert "curl -fsS http://localhost:4173" in provider.commands[2]
    assert provider.commands[3] == "npx playwright test --reporter=json"
    assert provider.commands[4] == "./scripts/stop.sh"
