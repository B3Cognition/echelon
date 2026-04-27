"""Root conftest for spec-kit-harness tests.

Registers pytest markers and provides Docker availability skip logic.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest

# Add src/ to path so codegen module is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _docker_available() -> bool:
    """Check if Docker daemon is running and accessible."""
    if not shutil.which("docker"):
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


# Cache result at module level so we only check once per test session
_DOCKER_IS_AVAILABLE: Optional[bool] = None


def docker_is_available() -> bool:
    """Return cached Docker availability check."""
    global _DOCKER_IS_AVAILABLE
    if _DOCKER_IS_AVAILABLE is None:
        _DOCKER_IS_AVAILABLE = _docker_available()
    return _DOCKER_IS_AVAILABLE


# --- Pytest markers ---

def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests (no external deps)")
    config.addinivalue_line("markers", "contract: Contract tests (provider interface)")
    config.addinivalue_line("markers", "integration: Integration tests (may need Docker/git)")
    config.addinivalue_line("markers", "system: System tests (full Docker + fixture repos)")
    config.addinivalue_line("markers", "e2e: End-to-end smoke tests")
    config.addinivalue_line("markers", "docker: Tests that require Docker daemon")
    config.addinivalue_line("markers", "slow: Tests that take > 30s")


# --- Auto-skip for Docker-dependent tests ---

def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip docker-marked tests when Docker is not available."""
    if docker_is_available():
        return

    skip_docker = pytest.mark.skip(reason="Docker daemon not available")
    for item in items:
        if "docker" in item.keywords:
            item.add_marker(skip_docker)
