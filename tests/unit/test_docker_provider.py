from __future__ import annotations

import subprocess
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
    # Docker's init process reaps orphaned verifier children; a bare `tail`
    # as PID 1 leaves zombies visible to kill(pid, 0) cleanup checks.
    assert "--init" in sandbox_command
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
def test_official_playwright_image_prefers_capable_native_variant(tmp_path, monkeypatch) -> None:
    """A capable native image must not run through x86 emulation."""
    monkeypatch.setenv("DOCKER_DEFAULT_PLATFORM", "linux/amd64")
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
        def docker_result(args, **_kwargs):
            if args[:2] == ["info", "--format"]:
                return MagicMock(returncode=0, stdout="aarch64\n", stderr="")
            if args[:2] == ["run", "--rm"]:
                return MagicMock(returncode=0, stdout="aarch64\n", stderr="")
            return MagicMock(returncode=0, stdout="sandbox-id\n", stderr="")

        docker.side_effect = docker_result
        handle = provider.create(spec)

    sandbox_command = next(
        call.args[0] for call in docker.call_args_list
        if call.args[0][:2] == ["run", "-d"] and spec.image in call.args[0]
    )
    assert sandbox_command[sandbox_command.index("--platform") + 1] == "linux/arm64"
    probe = next(
        call.args[0] for call in docker.call_args_list
        if call.args[0][:2] == ["run", "--rm"]
    )
    assert probe[probe.index("--platform") + 1] == "linux/arm64"
    assert handle.platform == "linux/arm64"


@pytest.mark.unit
def test_official_playwright_image_falls_back_when_native_probe_fails(tmp_path) -> None:
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
        def docker_result(args, **_kwargs):
            if args[:2] == ["info", "--format"]:
                return MagicMock(returncode=0, stdout="aarch64\n", stderr="")
            if args[:2] == ["run", "--rm"] and "--platform" in args and args[args.index("--platform") + 1] == "linux/arm64":
                return MagicMock(returncode=42, stdout="", stderr="browser missing")
            if args[:2] == ["run", "--rm"]:
                return MagicMock(returncode=0, stdout="x86_64\n", stderr="")
            return MagicMock(returncode=0, stdout="sandbox-id\n", stderr="")

        docker.side_effect = docker_result
        handle = provider.create(spec)

    sandbox_command = next(
        call.args[0] for call in docker.call_args_list
        if call.args[0][:2] == ["run", "-d"] and spec.image in call.args[0]
    )
    assert sandbox_command[sandbox_command.index("--platform") + 1] == "linux/amd64"
    assert handle.platform == "linux/amd64"
    assert len([call for call in docker.call_args_list if call.args[0][:2] == ["run", "--rm"]]) == 2


@pytest.mark.unit
def test_official_playwright_image_does_not_fallback_on_docker_failure(tmp_path) -> None:
    """A daemon or image-pull failure is not evidence that native is incapable."""
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

    with patch("harness.docker_provider._run_docker") as docker, patch(
        "harness.docker_provider.subprocess.run"
    ) as process:
        def docker_result(args, **_kwargs):
            if args[:2] == ["info", "--format"]:
                return MagicMock(returncode=0, stdout="aarch64\n", stderr="")
            if args[:2] == ["run", "--rm"] and (
                "--platform" not in args or args[args.index("--platform") + 1] == "linux/arm64"
            ):
                return MagicMock(returncode=125, stdout="", stderr="image pull failed")
            return MagicMock(returncode=0, stdout="sandbox-id\n", stderr="")

        docker.side_effect = docker_result
        with pytest.raises(SandboxCreationError, match="image pull failed"):
            provider.create(spec)

    assert len([call for call in docker.call_args_list if call.args[0][:2] == ["run", "--rm"]]) == 1
    # No resources exist before the platform probe succeeds. Never touch the
    # host Docker CLI to remove a merely planned network.
    process.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize("cleanup_failure", ["missing_cli", "timeout", "nonzero"])
def test_failed_creation_preserves_error_and_continues_cleanup(
    tmp_path, caplog, cleanup_failure,
) -> None:
    """A failed removal must not hide the copy failure or leak later resources."""
    generated_conf = tmp_path / "generated-squid.conf"
    generated_conf.write_text("test", encoding="utf-8")
    provider = DockerWorktreeProvider()
    spec = SandboxSpec(
        image="playwright:test", image_source="playwright",
        worktree_mount=str(tmp_path / "candidate"), container_mount="/workspace",
        resource_limits=ResourceLimits(), network_policy=NetworkPolicy(),
        env={}, secrets_env={}, post_create_command=None, forward_ports=[],
        isolate_candidate=True,
    )
    commands = []

    def process_result(command, **_kwargs):
        commands.append(command)
        if command[:2] == ["docker", "exec"]:
            return subprocess.CompletedProcess(command, 1, "", "copy failed")
        if command == ["docker", "rm", "-f", "sandbox-id"]:
            if cleanup_failure == "missing_cli":
                raise FileNotFoundError("docker disappeared")
            if cleanup_failure == "timeout":
                raise subprocess.TimeoutExpired(command, 10)
            return subprocess.CompletedProcess(command, 1, b"", b"daemon unavailable")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    with patch("harness.docker_provider._run_docker") as docker, patch(
        "harness.docker_provider.subprocess.run", side_effect=process_result,
    ), patch(
        "harness.docker_provider._generate_squid_conf", return_value=str(generated_conf),
    ):
        docker.side_effect = [
            subprocess.CompletedProcess([], 0, "network-id\n", ""),
            subprocess.CompletedProcess([], 0, "proxy-id\n", ""),
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "sandbox-id\n", ""),
        ]
        with pytest.raises(SandboxCreationError, match="isolated candidate copy failed"):
            provider.create(spec)

    assert commands[1:3] == [
        ["docker", "rm", "-f", "sandbox-id"],
        ["docker", "rm", "-f", "proxy-id"],
    ]
    assert commands[3][:3] == ["docker", "network", "rm"]
    assert commands[4][:4] == ["docker", "volume", "rm", "-f"]
    assert len(commands) == 5
    assert not generated_conf.exists()
    assert provider._containers == {}
    assert "cleanup" in caplog.text.lower()


@pytest.mark.unit
def test_failed_config_cleanup_preserves_creation_error(tmp_path, caplog) -> None:
    """A temporary-file permission error is secondary to failed proxy creation."""
    generated_conf = tmp_path / "generated-squid.conf"
    generated_conf.write_text("test", encoding="utf-8")
    original_error = SandboxCreationError("proxy image unavailable")
    provider = DockerWorktreeProvider()
    spec = SandboxSpec(
        image="playwright:test", image_source="playwright",
        worktree_mount=str(tmp_path / "candidate"), container_mount="/workspace",
        resource_limits=ResourceLimits(), network_policy=NetworkPolicy(),
        env={}, secrets_env={}, post_create_command=None, forward_ports=[],
    )
    with patch("harness.docker_provider._run_docker", side_effect=[
        subprocess.CompletedProcess([], 0, "network-id\n", ""), original_error,
    ]), patch("harness.docker_provider.subprocess.run", return_value=
        subprocess.CompletedProcess([], 0, b"", b""),
    ), patch("harness.docker_provider._generate_squid_conf", return_value=str(generated_conf)), patch(
        "harness.docker_provider.Path.unlink", side_effect=PermissionError("cannot remove config"),
    ):
        with pytest.raises(SandboxCreationError) as raised:
            provider.create(spec)

    assert raised.value is original_error
    assert generated_conf.exists()
    assert str(generated_conf) in caplog.text
    assert "cleanup" in caplog.text.lower()


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
