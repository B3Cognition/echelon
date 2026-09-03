"""SandboxProvider abstract base class and registration system.

Per contracts/sandbox-provider.md: defines the interface that ALL sandbox
providers must implement. Registration validates mandatory methods at
registration time (FR-SANDBOX-001).

Dataclasses: Capability, SandboxSpec, SandboxHandle, ResourceLimits,
NetworkPolicy -- all matching the contract exactly.
"""

from __future__ import annotations

import abc
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Type

from harness.errors import NotSupportedError
from harness.exec_result import ExecResult, ResourceStats


# --- Enums and dataclasses per contract ---

class Capability(str, Enum):
    """Optional capabilities a provider may support."""
    BULK_WRITE = "bulk_write"
    BULK_READ = "bulk_read"
    STREAMING = "streaming"
    SNAPSHOT = "snapshot"
    COST_TRACKING = "cost_tracking"


@dataclass
class ResourceLimits:
    """Resource limits for sandbox containers."""
    memory: str = "4g"
    cpu: float = 2.0
    pids: int = 256
    storage: str = "10g"


@dataclass
class NetworkPolicy:
    """Network policy configuration."""
    allowlist: List[str] = field(default_factory=list)
    proxy_image: str = "ubuntu/squid:latest"
    deny_log: bool = True


@dataclass
class SandboxSpec:
    """Declarative specification of a sandbox instance."""
    image: str
    image_source: str  # devcontainer | harness_dockerfile | fingerprint | config_override
    worktree_mount: str  # Host path to bind-mount
    container_mount: str  # Container-side path (default: /workspace)
    resource_limits: ResourceLimits
    network_policy: NetworkPolicy
    env: Dict[str, str]
    secrets_env: Dict[str, str]
    post_create_command: Optional[str]
    forward_ports: List[int]
    session_timeout_ms: int = 3_600_000  # 1 hour default
    labels: Dict[str, str] = field(default_factory=dict)
    ephemeral_volumes: List[str] = field(default_factory=list)


@dataclass
class SandboxHandle:
    """Handle to a created sandbox instance."""
    id: str
    session_id: str  # FR-SANDBOX-007c: unique per instance, non-null


@dataclass
class MonetaryCost:
    """Cost tracking for cloud providers."""
    usd: float
    currency: str = "USD"


# --- Abstract base class ---

class SandboxProvider(abc.ABC):
    """Abstract interface for sandbox execution environments.

    All methods are synchronous in Phase 1.
    Invariants:
    - create() must be called before any other operation
    - destroy() must be called to clean up resources
    - After destroy(), the handle is invalid
    """

    # === MANDATORY METHODS ===

    @abc.abstractmethod
    def create(self, spec: SandboxSpec) -> SandboxHandle:
        """Create a new sandbox from the given spec."""
        ...

    @abc.abstractmethod
    def exec(
        self,
        handle: SandboxHandle,
        cmd: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout_ms: int = 1_200_000,
    ) -> ExecResult:
        """Execute a command in the sandbox."""
        ...

    @abc.abstractmethod
    def write_file(self, handle: SandboxHandle, path: str, content: bytes) -> None:
        """Write a file into the sandbox filesystem."""
        ...

    @abc.abstractmethod
    def read_file(self, handle: SandboxHandle, path: str) -> bytes:
        """Read a file from the sandbox filesystem."""
        ...

    @abc.abstractmethod
    def destroy(self, handle: SandboxHandle) -> None:
        """Destroy the sandbox and release all resources."""
        ...

    def capabilities(self) -> Set[Capability]:
        """Return optional capabilities this provider supports."""
        return set()

    # === OPTIONAL METHODS ===

    def snapshot(self, handle: SandboxHandle) -> str:
        """Take a snapshot. Raise NotSupportedError if not supported."""
        raise NotSupportedError("snapshot not supported by this provider")

    def restore(self, handle: SandboxHandle, snapshot_id: str) -> SandboxHandle:
        """Restore from snapshot. Raise NotSupportedError if not supported."""
        raise NotSupportedError("restore not supported by this provider")

    def stream_exec(
        self,
        handle: SandboxHandle,
        cmd: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout_ms: int = 1_200_000,
    ) -> Any:
        """Stream execution output. Phase 2 feature."""
        raise NotSupportedError("stream_exec not supported by this provider")

    def get_cost(self, handle: SandboxHandle) -> Optional[MonetaryCost]:
        """Return monetary cost. Returns None for local providers."""
        return None

    def start_services(self, handle: SandboxHandle, services: tuple[Any, ...]) -> tuple[str, ...]:
        """Start attempt-scoped sidecars when supported by the provider."""
        raise NotSupportedError("verification services not supported by this provider")

    def exec_service(
        self,
        handle: SandboxHandle,
        service_name: str,
        argv: tuple[str, ...],
        timeout_ms: int = 1_200_000,
    ) -> ExecResult:
        """Execute argv directly inside an attempt-owned named sidecar."""
        raise NotSupportedError("service execution not supported by this provider")


# --- Provider registration ---

_REGISTRY: Dict[str, Type[SandboxProvider]] = {}

MANDATORY_METHODS = {"create", "exec", "write_file", "read_file", "destroy"}


class ProviderNotFoundError(Exception):
    """Raised when a provider name is not registered."""


def register_provider(name: str, provider_class: Type[SandboxProvider]) -> None:
    """Register a SandboxProvider implementation.

    Validates at registration time that all mandatory methods are
    implemented (FR-SANDBOX-001).

    Raises:
        TypeError: If mandatory methods are not implemented.
    """
    for method_name in MANDATORY_METHODS:
        method = getattr(provider_class, method_name, None)
        if method is None:
            raise TypeError(
                f"Provider '{name}' missing mandatory method: {method_name}"
            )
        # Check it's actually overridden (not just inherited abstract)
        if getattr(method, "__isabstractmethod__", False):
            raise TypeError(
                f"Provider '{name}' does not implement mandatory method: {method_name}"
            )
    _REGISTRY[name] = provider_class


def get_provider(name: str) -> Type[SandboxProvider]:
    """Look up a registered provider by name.

    Raises:
        ProviderNotFoundError: If no provider is registered with that name.
    """
    if name not in _REGISTRY:
        raise ProviderNotFoundError(
            f"No provider registered with name '{name}'. "
            f"Available: {sorted(_REGISTRY.keys())}"
        )
    return _REGISTRY[name]


def clear_registry() -> None:
    """Clear the provider registry. For testing only."""
    _REGISTRY.clear()
