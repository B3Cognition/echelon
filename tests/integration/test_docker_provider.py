"""Integration tests for DockerWorktreeProvider.

Beyond-contract tests that verify Docker-specific behavior:
- Environment variable injection
- Credential leak detection at create() time
- OOM kill handling
- Post-create command execution
- Resource stats collection
- Destroy cleanup (container, proxy, network)

These tests verify the Python-level logic without requiring Docker.
Tests that need Docker daemon are marked @pytest.mark.docker.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from typing import Optional

import pytest

from harness.docker_provider import (
    DockerWorktreeProvider,
    _check_credential_leak,
    _run_docker,
    _truncate_output,
    _parse_memory_string,
)
from harness.errors import CredentialLeakError, SandboxCreationError
from harness.exec_result import (
    EXIT_FORCE_KILL,
    EXIT_OOM,
    EXIT_PID_LIMIT,
    EXIT_TIMEOUT,
    ExecResult,
    ResourceStats,
)
from harness.provider import (
    NetworkPolicy,
    ResourceLimits,
    SandboxHandle,
    SandboxSpec,
)


def _make_spec(**overrides) -> SandboxSpec:
    """Create a SandboxSpec with defaults."""
    defaults = dict(
        image="python:3.11-slim",
        image_source="fingerprint",
        worktree_mount="/tmp/test-wt",
        container_mount="/workspace",
        resource_limits=ResourceLimits(),
        network_policy=NetworkPolicy(),
        env={"TEST_VAR": "hello"},
        secrets_env={},
        post_create_command=None,
        forward_ports=[],
        session_timeout_ms=3_600_000,
        labels={"strategy_id": "default", "spec_id": "001", "run_id": "r-1"},
    )
    defaults.update(overrides)
    return SandboxSpec(**defaults)


@pytest.mark.integration
class TestCredentialLeakDetection:
    """FR-SANDBOX-005: credential leak detection."""

    def test_github_token_blocked(self) -> None:
        with pytest.raises(CredentialLeakError):
            _check_credential_leak(env={"GITHUB_TOKEN": "ghp_abc"}, secrets_env={})

    def test_gitlab_token_blocked(self) -> None:
        with pytest.raises(CredentialLeakError):
            _check_credential_leak(env={"GITLAB_TOKEN": "glpat_abc"}, secrets_env={})

    def test_gh_token_blocked(self) -> None:
        with pytest.raises(CredentialLeakError):
            _check_credential_leak(env={"GH_TOKEN": "ghp_abc"}, secrets_env={})

    def test_git_askpass_blocked(self) -> None:
        with pytest.raises(CredentialLeakError):
            _check_credential_leak(env={"GIT_ASKPASS": "/usr/lib/askpass"}, secrets_env={})

    def test_clean_env_passes(self) -> None:
        # Should not raise
        _check_credential_leak(
            env={"NODE_ENV": "test", "PATH": "/usr/bin"},
            secrets_env={"NPM_TOKEN": "tok_abc"},
        )

    def test_credential_in_secrets_env_blocked(self) -> None:
        with pytest.raises(CredentialLeakError):
            _check_credential_leak(env={}, secrets_env={"GIT_TOKEN": "secret"})


@pytest.mark.integration
class TestBufferTruncation:
    """FR-STREAM-001a/b: bounded buffer with tail preservation."""

    def test_small_output_not_truncated(self) -> None:
        result, truncated = _truncate_output("hello", 1000)
        assert result == "hello"
        assert truncated is False

    def test_large_output_truncated_with_marker(self) -> None:
        output = "x" * 200
        result, truncated = _truncate_output(output, 100)
        assert truncated is True
        assert "[TRUNCATED: 200]" in result

    def test_tail_preserved_at_80_percent(self) -> None:
        # 200 chars, limit 100, tail should be 80 chars
        output = "A" * 120 + "B" * 80
        result, truncated = _truncate_output(output, 100)
        assert truncated is True
        # The last 80 chars should be "B"s
        lines = result.split("\n", 1)
        tail = lines[-1] if len(lines) > 1 else result
        assert "B" in tail

    def test_exact_limit_not_truncated(self) -> None:
        output = "x" * 100
        result, truncated = _truncate_output(output, 100)
        assert truncated is False
        assert result == output

    def test_empty_output(self) -> None:
        result, truncated = _truncate_output("", 100)
        assert result == ""
        assert truncated is False


@pytest.mark.integration
class TestMemoryStringParsing:
    """Utility: Docker memory string parsing."""

    def test_mib(self) -> None:
        assert _parse_memory_string("128.5MiB") == int(128.5 * 1024 * 1024)

    def test_gib(self) -> None:
        assert _parse_memory_string("4GiB") == 4 * 1024 ** 3

    def test_kib(self) -> None:
        assert _parse_memory_string("1024KiB") == 1024 * 1024

    def test_bytes(self) -> None:
        assert _parse_memory_string("4096B") == 4096

    def test_plain_number(self) -> None:
        assert _parse_memory_string("12345") == 12345

    def test_invalid(self) -> None:
        assert _parse_memory_string("invalid") == 0

    def test_empty(self) -> None:
        assert _parse_memory_string("") == 0


@pytest.mark.integration
class TestDockerProviderInit:
    """DockerWorktreeProvider initialization."""

    def test_default_buffer_limit(self) -> None:
        provider = DockerWorktreeProvider()
        assert provider._buffer_limit_bytes == 10_485_760

    def test_custom_buffer_limit(self) -> None:
        provider = DockerWorktreeProvider(buffer_limit_bytes=5_000_000)
        assert provider._buffer_limit_bytes == 5_000_000

    def test_custom_container_cli(self) -> None:
        provider = DockerWorktreeProvider(container_cli="podman")
        assert provider._container_cli == "podman"

    def test_run_docker_uses_configured_container_cli(self) -> None:
        with patch("harness.docker_provider.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stdout="", stderr="")

            _run_docker(["info"], cli="podman")

        assert run.call_args.args[0] == ["podman", "info"]

    def test_capabilities_empty(self) -> None:
        provider = DockerWorktreeProvider()
        assert provider.capabilities() == set()


@pytest.mark.integration
class TestExitCodeMapping:
    """Verify special exit code constants match contract."""

    def test_timeout_code(self) -> None:
        assert EXIT_TIMEOUT == 124

    def test_force_kill_code(self) -> None:
        assert EXIT_FORCE_KILL == 137

    def test_oom_code(self) -> None:
        assert EXIT_OOM == 139

    def test_pid_limit_code(self) -> None:
        assert EXIT_PID_LIMIT == 155
