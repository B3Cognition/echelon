from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from harness.docker_provider import DockerWorktreeProvider
from harness.errors import SandboxCreationError
from harness.errors import NotSupportedError
from harness.provider import NetworkPolicy, ResourceLimits, SandboxHandle, SandboxSpec
from harness.verification_plan import SandboxServiceSpec


def _active_provider() -> tuple[DockerWorktreeProvider, SandboxHandle]:
    provider = DockerWorktreeProvider(buffer_limit_bytes=1024)
    handle = SandboxHandle(id="sandbox-id", session_id="session-id")
    provider._containers[handle.session_id] = SimpleNamespace(
        sandbox_id="sandbox-id",
        proxy_id=None,
        network_name="internal-net",
        service_ids=[],
        service_ids_by_name={},
    )
    return provider, handle


@pytest.mark.unit
def test_isolated_candidate_is_copied_from_read_only_mount(tmp_path) -> None:
    """Browser writes must land in a disposable volume, never in the host candidate."""
    squid_conf = tmp_path / "squid.conf"
    squid_conf.write_text("test", encoding="utf-8")
    provider = DockerWorktreeProvider(squid_conf_path=str(squid_conf))
    spec = SandboxSpec(
        image="playwright:test",
        image_source="playwright",
        worktree_mount=str(tmp_path / "candidate"),
        container_mount="/workspace",
        resource_limits=ResourceLimits(),
        network_policy=NetworkPolicy(),
        env={},
        secrets_env={},
        post_create_command=None,
        forward_ports=[],
        isolate_candidate=True,
    )

    with patch("harness.docker_provider._run_docker") as docker, patch(
        "harness.docker_provider.subprocess.run"
    ) as process:
        docker.return_value = MagicMock(stdout="sandbox-id\n")
        process.return_value = MagicMock(returncode=0, stderr="")
        handle = provider.create(spec)

    sandbox_command = next(
        call.args[0]
        for call in docker.call_args_list
        if call.args[0][:2] == ["run", "-d"] and "playwright:test" in call.args[0]
    )
    mounts = [sandbox_command[index + 1] for index, arg in enumerate(sandbox_command[:-1])
              if arg == "--volume"]
    assert f"{spec.worktree_mount}:/workspace-source:ro" in mounts
    assert any(mount.endswith(":/workspace") and mount.startswith("harness-volume-")
               for mount in mounts)
    assert f"{spec.worktree_mount}:/workspace" not in mounts
    assert process.call_args.args[0] == [
        "docker", "exec", "sandbox-id", "cp", "-a", "/workspace-source/.", "/workspace/",
    ]
    assert provider._containers[handle.session_id].volume_names


@pytest.mark.unit
def test_official_playwright_image_uses_browser_populated_amd64_variant(tmp_path) -> None:
    """The arm64 image may lack the pinned browser and current Node runtime."""
    squid_conf = tmp_path / "squid.conf"
    squid_conf.write_text("test", encoding="utf-8")
    provider = DockerWorktreeProvider(squid_conf_path=str(squid_conf))
    spec = SandboxSpec(
        image="mcr.microsoft.com/playwright:v1.63.0-noble",
        image_source="fingerprint",
        worktree_mount=str(tmp_path / "candidate"),
        container_mount="/workspace",
        resource_limits=ResourceLimits(),
        network_policy=NetworkPolicy(),
        env={}, secrets_env={}, post_create_command=None, forward_ports=[],
    )

    with patch("harness.docker_provider._run_docker") as docker:
        docker.return_value = MagicMock(stdout="sandbox-id\n")
        provider.create(spec)

    sandbox_command = next(
        call.args[0] for call in docker.call_args_list
        if call.args[0][:2] == ["run", "-d"] and spec.image in call.args[0]
    )
    assert sandbox_command[sandbox_command.index("--platform") + 1] == "linux/amd64"


@pytest.mark.unit
def test_failed_isolated_copy_releases_candidate_volume(tmp_path) -> None:
    squid_conf = tmp_path / "squid.conf"
    squid_conf.write_text("test", encoding="utf-8")
    provider = DockerWorktreeProvider(squid_conf_path=str(squid_conf))
    spec = SandboxSpec(
        image="playwright:test", image_source="playwright",
        worktree_mount=str(tmp_path / "candidate"), container_mount="/workspace",
        resource_limits=ResourceLimits(), network_policy=NetworkPolicy(),
        env={}, secrets_env={}, post_create_command=None, forward_ports=[],
        isolate_candidate=True,
    )
    with patch("harness.docker_provider._run_docker") as docker, patch(
        "harness.docker_provider.subprocess.run"
    ) as process:
        docker.return_value = MagicMock(stdout="sandbox-id\n")
        process.side_effect = [
            MagicMock(returncode=1, stderr="copy failed"),
            MagicMock(), MagicMock(), MagicMock(), MagicMock(),
        ]

        with pytest.raises(SandboxCreationError, match="isolated candidate copy failed"):
            provider.create(spec)

    cleanup = [call.args[0] for call in process.call_args_list[1:]]
    assert any(command[:4] == ["docker", "volume", "rm", "-f"] for command in cleanup)
    assert provider._containers == {}


@pytest.mark.unit
def test_exec_service_uses_attempt_owned_named_sidecar_without_shell() -> None:
    provider, handle = _active_provider()
    service = SandboxServiceSpec(
        service_name="postgres",
        image="postgres:16.4-alpine",
    )
    with patch("harness.docker_provider._run_docker") as run:
        run.return_value = MagicMock(stdout="service-id\n", stderr="", returncode=0)
        provider.start_services(handle, (service,))
    with patch("harness.docker_provider.subprocess.run") as run:
        run.return_value = MagicMock(
            stdout=b"1\n",
            stderr=b"",
            returncode=0,
        )

        result = provider.exec_service(
            handle,
            "postgres",
            ("psql", "-Atqc", "SELECT 1"),
            timeout_ms=30_000,
        )

    assert result.exit_code == 0
    assert result.stdout == "1\n"
    assert run.call_args.args[0] == [
        "docker",
        "exec",
        "service-id",
        "psql",
        "-Atqc",
        "SELECT 1",
    ]


@pytest.mark.unit
def test_exec_service_rejects_unknown_service() -> None:
    provider, handle = _active_provider()

    with pytest.raises(NotSupportedError, match="service.*not active"):
        provider.exec_service(handle, "postgres", ("true",))
