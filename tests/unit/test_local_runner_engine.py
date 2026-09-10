"""Engine-neutral rendering and preflight tests."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from harness.local_runner_compose import parse_canonical_compose_plan
from harness.local_runner_engine import (
    DockerDesktopMacOSAdapter,
    LocalEngineError,
    PodmanMacOSAdapter,
)


class _RecordingExecutor:
    def __init__(self, outputs: dict[tuple[str, ...], str]) -> None:
        self.outputs = outputs
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: tuple[str, ...], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, self.outputs.get(argv, ""), "")


def _plan(tmp_path: Path):
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services:\n  postgres:\n    image: postgres:17-alpine\n", encoding="utf-8")
    return parse_canonical_compose_plan(tmp_path, compose.name, {"postgres"})


@pytest.mark.unit
def test_docker_adapter_accepts_only_local_unix_context(tmp_path: Path) -> None:
    executor = _RecordingExecutor(
        {
            ("docker", "context", "show"): "desktop-linux\n",
            (
                "docker", "context", "inspect", "desktop-linux", "--format", "{{.Endpoints.docker.Host}}"
            ): "unix:///Users/test/.docker/run/docker.sock\n",
        }
    )

    profile = DockerDesktopMacOSAdapter(executor=executor, platform="darwin").probe()

    assert profile.profile_id == "docker-desktop-macos-v1"


@pytest.mark.unit
def test_podman_adapter_rejects_non_macos_host(tmp_path: Path) -> None:
    with pytest.raises(LocalEngineError, match="macOS"):
        PodmanMacOSAdapter(executor=_RecordingExecutor({}), platform="linux").probe()


@pytest.mark.unit
def test_engine_render_generates_loopback_only_override(tmp_path: Path) -> None:
    adapter = DockerDesktopMacOSAdapter(executor=_RecordingExecutor({}), platform="darwin")

    rendered = adapter.render_plan(_plan(tmp_path), "local-run-1", tmp_path / "generated")

    assert "127.0.0.1::5432" in rendered.generated_override_path.read_text(encoding="utf-8")
    assert "local-run-1" in " ".join(rendered.command_argv)
    assert rendered.generated_override_path.parent == tmp_path / "generated"
