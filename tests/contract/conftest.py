"""Contract test conftest with parametrized provider fixture.

The contract test suite runs against ANY SandboxProvider implementation.
Providers are registered here and parametrized across all contract tests.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Type

import pytest

from harness.exec_result import ExecResult
from harness.provider import (
    Capability,
    SandboxHandle,
    SandboxProvider,
    SandboxSpec,
)


class MockSandboxProvider(SandboxProvider):
    """Minimal mock provider for contract testing without Docker."""

    def __init__(self) -> None:
        self._created = False
        self._files: Dict[str, bytes] = {}

    def create(self, spec: SandboxSpec) -> SandboxHandle:
        self._created = True
        self._spec = spec
        return SandboxHandle(id="mock-container-1", session_id="mock-session-1")

    def exec(
        self,
        handle: SandboxHandle,
        cmd: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout_ms: int = 1_200_000,
    ) -> ExecResult:
        return ExecResult(
            exit_code=0,
            stdout=f"mock output for: {cmd}",
            stderr="",
            duration_ms=100,
            resource_stats=None,
            truncated=False,
        )

    def write_file(self, handle: SandboxHandle, path: str, content: bytes) -> None:
        self._files[path] = content

    def read_file(self, handle: SandboxHandle, path: str) -> bytes:
        return self._files.get(path, b"")

    def destroy(self, handle: SandboxHandle) -> None:
        self._created = False
        self._files.clear()

    def capabilities(self) -> Set[Capability]:
        return set()


@pytest.fixture(params=["mock"])
def provider_class(request: pytest.FixtureRequest) -> Type[SandboxProvider]:
    """Parametrized provider fixture. Add real providers as they're implemented."""
    if request.param == "mock":
        return MockSandboxProvider
    raise ValueError(f"Unknown provider: {request.param}")
