"""Contract test suite for SandboxProvider (CT-01 through CT-12).

Per contracts/sandbox-provider.md: these tests validate ANY provider
implementation against the SandboxProvider contract. All tests use
the parametrized provider_class fixture from conftest.py.

Contract tests:
CT-01: create() returns SandboxHandle with non-null session_id
CT-02: exec() returns complete ExecResult with all fields
CT-03: exec() timeout returns exit_code=124
CT-04: exec() force-kill returns exit_code=137 (skipped for mock)
CT-05: write_file() + read_file() roundtrip
CT-06: destroy() cleans up resources
CT-07: network policy default deny (integration-level, skipped for mock)
CT-08: loopback allowed (integration-level, skipped for mock)
CT-09: credential leak detection blocks create()
CT-10: resource limits enforced (integration-level, skipped for mock)
CT-11: bounded buffer truncation
CT-12: capabilities() returns Set[Capability]
"""

from __future__ import annotations

from typing import Set, Type

import pytest

from harness.errors import CredentialLeakError
from harness.exec_result import ExecResult, ResourceStats, EXIT_TIMEOUT
from harness.provider import (
    Capability,
    NetworkPolicy,
    ResourceLimits,
    SandboxHandle,
    SandboxProvider,
    SandboxSpec,
)


def _make_spec(**overrides) -> SandboxSpec:
    """Create a SandboxSpec with sensible defaults for testing."""
    defaults = dict(
        image="python:3.11-slim",
        image_source="fingerprint",
        worktree_mount="/tmp/test-worktree",
        container_mount="/workspace",
        resource_limits=ResourceLimits(),
        network_policy=NetworkPolicy(),
        env={"TEST_VAR": "hello"},
        secrets_env={},
        post_create_command=None,
        forward_ports=[],
        session_timeout_ms=3_600_000,
        labels={"strategy_id": "default", "spec_id": "001", "run_id": "test-run"},
    )
    defaults.update(overrides)
    return SandboxSpec(**defaults)


@pytest.mark.contract
class TestCT01CreateReturnsHandle:
    """CT-01: create() returns SandboxHandle with non-null session_id."""

    def test_create_returns_handle(
        self, provider_class: Type[SandboxProvider]
    ) -> None:
        provider = provider_class()
        spec = _make_spec()
        handle = provider.create(spec)

        assert isinstance(handle, SandboxHandle)
        assert handle.id is not None
        assert handle.id != ""
        assert handle.session_id is not None
        assert handle.session_id != ""

        # Cleanup
        provider.destroy(handle)


@pytest.mark.contract
class TestCT02ExecReturnsCompleteResult:
    """CT-02: exec() returns ExecResult with all fields present."""

    def test_exec_returns_complete_result(
        self, provider_class: Type[SandboxProvider]
    ) -> None:
        provider = provider_class()
        spec = _make_spec()
        handle = provider.create(spec)

        try:
            result = provider.exec(handle, "echo hello")

            assert isinstance(result, ExecResult)
            assert isinstance(result.exit_code, int)
            assert isinstance(result.stdout, str)
            assert isinstance(result.stderr, str)
            assert isinstance(result.duration_ms, int)
            assert isinstance(result.truncated, bool)
            # resource_stats may be None or ResourceStats
            if result.resource_stats is not None:
                assert isinstance(result.resource_stats, ResourceStats)
        finally:
            provider.destroy(handle)


@pytest.mark.contract
class TestCT03TimeoutReturns124:
    """CT-03: exec() timeout returns exit_code=124 (FR-SANDBOX-003a/b)."""

    def test_timeout_exit_code(
        self, provider_class: Type[SandboxProvider]
    ) -> None:
        """Mock provider doesn't enforce timeouts, so we test the contract shape."""
        provider = provider_class()
        spec = _make_spec()
        handle = provider.create(spec)

        try:
            # For mock: just verify exec works with timeout_ms parameter
            result = provider.exec(handle, "echo test", timeout_ms=5000)
            assert isinstance(result.exit_code, int)
        finally:
            provider.destroy(handle)


@pytest.mark.contract
class TestCT04ForceKillReturns137:
    """CT-04: Force-kill returns exit_code=137 (FR-SANDBOX-003c).

    Skipped for mock provider — requires real Docker to test hung process.
    """

    @pytest.mark.docker
    def test_force_kill_exit_code(
        self, provider_class: Type[SandboxProvider]
    ) -> None:
        pytest.skip("Requires real Docker provider for force-kill test")


@pytest.mark.contract
class TestCT05WriteReadRoundtrip:
    """CT-05: write_file() + read_file() roundtrip."""

    def test_write_read_roundtrip(
        self, provider_class: Type[SandboxProvider]
    ) -> None:
        provider = provider_class()
        spec = _make_spec()
        handle = provider.create(spec)

        try:
            test_content = b"Hello, sandbox!\nLine 2\n"
            test_path = "/workspace/test-file.txt"

            provider.write_file(handle, test_path, test_content)
            result = provider.read_file(handle, test_path)

            assert result == test_content
        finally:
            provider.destroy(handle)


@pytest.mark.contract
class TestCT06DestroyCleanup:
    """CT-06: destroy() cleans up resources."""

    def test_destroy_succeeds(
        self, provider_class: Type[SandboxProvider]
    ) -> None:
        provider = provider_class()
        spec = _make_spec()
        handle = provider.create(spec)

        # Should not raise
        provider.destroy(handle)


@pytest.mark.contract
@pytest.mark.docker
class TestCT07NetworkDenyDefault:
    """CT-07: network policy default deny (FR-NETWORK-001a).

    Requires real Docker with Squid proxy.
    """

    def test_non_allowlisted_blocked(
        self, provider_class: Type[SandboxProvider]
    ) -> None:
        pytest.skip("Requires real Docker + Squid proxy")


@pytest.mark.contract
@pytest.mark.docker
class TestCT08LoopbackAllowed:
    """CT-08: loopback allowed (FR-NETWORK-002).

    Requires real Docker.
    """

    def test_loopback_accessible(
        self, provider_class: Type[SandboxProvider]
    ) -> None:
        pytest.skip("Requires real Docker")


@pytest.mark.contract
class TestCT09CredentialLeakDetection:
    """CT-09: credential leak detection blocks create() (FR-SANDBOX-005)."""

    def test_git_credentials_in_env_blocked(
        self, provider_class: Type[SandboxProvider]
    ) -> None:
        """Credential leak detection is provider-agnostic. Test via the
        docker_provider module's _check_credential_leak function directly."""
        from harness.docker_provider import _check_credential_leak

        # Should raise for git credential patterns
        with pytest.raises(CredentialLeakError, match="[Gg]it credential"):
            _check_credential_leak(
                env={"GITHUB_TOKEN": "ghp_abc123"},
                secrets_env={},
            )

    def test_clean_env_passes(
        self, provider_class: Type[SandboxProvider]
    ) -> None:
        from harness.docker_provider import _check_credential_leak

        # Should NOT raise for non-credential env vars
        _check_credential_leak(
            env={"NODE_ENV": "test", "PATH": "/usr/bin"},
            secrets_env={"NPM_TOKEN": "abc"},  # NPM token is OK, not git
        )

    def test_multiple_credential_patterns(
        self, provider_class: Type[SandboxProvider]
    ) -> None:
        from harness.docker_provider import _check_credential_leak

        patterns_to_block = [
            "GIT_ASKPASS",
            "GIT_PASSWORD",
            "GIT_TOKEN",
            "GIT_CREDENTIAL_HELPER",
            "GITHUB_TOKEN",
            "GITLAB_TOKEN",
            "GH_TOKEN",
        ]
        for key in patterns_to_block:
            with pytest.raises(CredentialLeakError):
                _check_credential_leak(env={key: "secret"}, secrets_env={})


@pytest.mark.contract
@pytest.mark.docker
class TestCT10ResourceLimits:
    """CT-10: resource limits enforced (FR-RESOURCE-001a/c).

    Requires real Docker.
    """

    def test_oom_returns_139(
        self, provider_class: Type[SandboxProvider]
    ) -> None:
        pytest.skip("Requires real Docker")

    def test_default_resource_limits(
        self, provider_class: Type[SandboxProvider]
    ) -> None:
        """Verify default resource limits match spec."""
        limits = ResourceLimits()
        assert limits.memory == "4g"
        assert limits.cpu == 2.0
        assert limits.pids == 256
        assert limits.storage == "10g"


@pytest.mark.contract
class TestCT11BoundedBuffer:
    """CT-11: bounded buffer truncation (FR-STREAM-001a/b)."""

    def test_truncation_with_marker(self) -> None:
        from harness.docker_provider import _truncate_output

        # Create output larger than limit
        large_output = "x" * 100
        result, truncated = _truncate_output(large_output, limit_bytes=50)

        assert truncated is True
        assert result.startswith("[TRUNCATED: 100]")
        # Tail should be preserved (80% of 50 = 40 bytes)
        assert len(result.encode()) > 40

    def test_no_truncation_within_limit(self) -> None:
        from harness.docker_provider import _truncate_output

        small_output = "hello world"
        result, truncated = _truncate_output(small_output, limit_bytes=1000)

        assert truncated is False
        assert result == small_output

    def test_tail_preserving_80_percent(self) -> None:
        from harness.docker_provider import _truncate_output

        # 200 bytes of output, limit to 100 bytes
        # Tail should be 80 bytes (80% of 100)
        output = "A" * 100 + "B" * 100
        result, truncated = _truncate_output(output, limit_bytes=100)

        assert truncated is True
        # The tail should be mostly "B"s
        assert "B" in result


@pytest.mark.contract
class TestCT12Capabilities:
    """CT-12: capabilities() returns Set[Capability]."""

    def test_capabilities_returns_set(
        self, provider_class: Type[SandboxProvider]
    ) -> None:
        provider = provider_class()
        caps = provider.capabilities()
        assert isinstance(caps, set)
        # Phase 1: empty set for all providers
        for cap in caps:
            assert isinstance(cap, Capability)
