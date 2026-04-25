"""Tests for SandboxProvider ABC and registration system.

Tests per T007 acceptance criteria:
- SandboxProvider cannot be instantiated directly (ABC)
- All dataclasses match contract field-for-field
- register_provider validates mandatory methods
- get_provider returns registered provider
- Unregistered provider raises ProviderNotFoundError
- Capability enum has all 5 values
"""

from __future__ import annotations

from typing import Dict, Optional, Set

import pytest

from harness.errors import NotSupportedError
from harness.exec_result import ExecResult
from harness.provider import (
    Capability,
    MonetaryCost,
    NetworkPolicy,
    ProviderNotFoundError,
    ResourceLimits,
    SandboxHandle,
    SandboxProvider,
    SandboxSpec,
    clear_registry,
    get_provider,
    register_provider,
)


class _ValidProvider(SandboxProvider):
    """Minimal valid provider for testing."""
    def create(self, spec: SandboxSpec) -> SandboxHandle:
        return SandboxHandle(id="test", session_id="test-session")
    def exec(self, handle: SandboxHandle, cmd: str, **kw) -> ExecResult:  # type: ignore[override]
        return ExecResult(exit_code=0, stdout="", stderr="", duration_ms=0, resource_stats=None)
    def write_file(self, handle: SandboxHandle, path: str, content: bytes) -> None:
        pass
    def read_file(self, handle: SandboxHandle, path: str) -> bytes:
        return b""
    def destroy(self, handle: SandboxHandle) -> None:
        pass


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    """Clear provider registry between tests."""
    clear_registry()


@pytest.mark.unit
class TestSandboxProviderABC:
    """Test that SandboxProvider is abstract."""

    def test_cannot_instantiate_directly(self) -> None:
        with pytest.raises(TypeError, match="abstract"):
            SandboxProvider()  # type: ignore[abstract]

    def test_optional_methods_raise_not_supported(self) -> None:
        provider = _ValidProvider()
        handle = SandboxHandle(id="test", session_id="s")
        with pytest.raises(NotSupportedError):
            provider.snapshot(handle)
        with pytest.raises(NotSupportedError):
            provider.restore(handle, "snap-1")
        with pytest.raises(NotSupportedError):
            provider.stream_exec(handle, "echo hi")

    def test_get_cost_returns_none(self) -> None:
        provider = _ValidProvider()
        handle = SandboxHandle(id="test", session_id="s")
        assert provider.get_cost(handle) is None

    def test_capabilities_returns_empty_set(self) -> None:
        provider = _ValidProvider()
        assert provider.capabilities() == set()


@pytest.mark.unit
class TestDataclasses:
    """Test that dataclasses match contract fields."""

    def test_resource_limits_defaults(self) -> None:
        rl = ResourceLimits()
        assert rl.memory == "4g"
        assert rl.cpu == 2.0
        assert rl.pids == 256
        assert rl.storage == "10g"

    def test_network_policy_defaults(self) -> None:
        np = NetworkPolicy()
        assert np.allowlist == []
        assert np.proxy_image == "ubuntu/squid:latest"
        assert np.deny_log is True

    def test_sandbox_handle_fields(self) -> None:
        h = SandboxHandle(id="c-123", session_id="s-456")
        assert h.id == "c-123"
        assert h.session_id == "s-456"

    def test_sandbox_spec_all_fields(self) -> None:
        spec = SandboxSpec(
            image="node:20",
            image_source="fingerprint",
            worktree_mount="/tmp/wt",
            container_mount="/workspace",
            resource_limits=ResourceLimits(),
            network_policy=NetworkPolicy(),
            env={"NODE_ENV": "test"},
            secrets_env={},
            post_create_command="npm install",
            forward_ports=[3000],
            session_timeout_ms=3_600_000,
            labels={"strategy_id": "default", "spec_id": "001", "run_id": "r-1"},
        )
        assert spec.image == "node:20"
        assert spec.session_timeout_ms == 3_600_000
        assert "strategy_id" in spec.labels


@pytest.mark.unit
class TestCapabilityEnum:
    """Test Capability enum has all 5 values."""

    def test_all_5_capabilities(self) -> None:
        assert len(Capability) == 5
        assert Capability.BULK_WRITE.value == "bulk_write"
        assert Capability.BULK_READ.value == "bulk_read"
        assert Capability.STREAMING.value == "streaming"
        assert Capability.SNAPSHOT.value == "snapshot"
        assert Capability.COST_TRACKING.value == "cost_tracking"


@pytest.mark.unit
class TestProviderRegistration:
    """Test provider registration and lookup."""

    def test_register_valid_provider(self) -> None:
        register_provider("test", _ValidProvider)
        result = get_provider("test")
        assert result is _ValidProvider

    def test_unregistered_provider_raises_error(self) -> None:
        with pytest.raises(ProviderNotFoundError, match="nonexistent"):
            get_provider("nonexistent")

    def test_register_validates_mandatory_methods(self) -> None:
        # A provider missing 'create' should fail registration
        class _BadProvider(SandboxProvider):
            pass

        with pytest.raises(TypeError):
            register_provider("bad", _BadProvider)
