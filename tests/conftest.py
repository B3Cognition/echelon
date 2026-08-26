"""Root conftest for Echelon harness tests.

Registers pytest markers and provides Docker availability skip logic.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest

# Neutralize GitHub Actions terminal detection for the whole test session.
# Under GITHUB_ACTIONS=true, typer/rich render CLI --help into an empty panel
# (rich's CI-terminal mode), which breaks every help-text assertion in CI while
# the same tests pass locally. Nothing in echelon reads this variable, so
# clearing it for the test process is safe and makes help rendering
# deterministic across local and CI runs.
os.environ.pop("GITHUB_ACTIONS", None)

REPO_ROOT = Path(__file__).parent.parent

# Add src/ to path so codegen module is importable
sys.path.insert(0, str(REPO_ROOT / "src"))


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
_DOCKER_IMAGE_AVAILABLE: dict[str, bool] = {}


def docker_is_available() -> bool:
    """Return cached Docker availability check."""
    global _DOCKER_IS_AVAILABLE
    if _DOCKER_IS_AVAILABLE is None:
        _DOCKER_IS_AVAILABLE = _docker_available()
    return _DOCKER_IS_AVAILABLE


def docker_image_is_available(image: str) -> bool:
    """Return cached Docker image availability check."""
    if image not in _DOCKER_IMAGE_AVAILABLE:
        if not docker_is_available():
            _DOCKER_IMAGE_AVAILABLE[image] = False
        else:
            try:
                result = subprocess.run(
                    ["docker", "image", "inspect", image],
                    capture_output=True,
                    timeout=10,
                )
                _DOCKER_IMAGE_AVAILABLE[image] = result.returncode == 0
            except (subprocess.TimeoutExpired, OSError):
                _DOCKER_IMAGE_AVAILABLE[image] = False
    return _DOCKER_IMAGE_AVAILABLE[image]


# --- Pytest markers ---

def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests (no external deps)")
    config.addinivalue_line("markers", "contract: Contract tests (provider interface)")
    config.addinivalue_line("markers", "integration: Integration tests (may need Docker/git)")
    config.addinivalue_line("markers", "system: System tests (full Docker + fixture repos)")
    config.addinivalue_line("markers", "e2e: End-to-end smoke tests")
    config.addinivalue_line("markers", "docker: Tests that require Docker daemon")
    config.addinivalue_line("markers", "docker_image(name): Tests that require a local Docker image")
    config.addinivalue_line("markers", "slow: Tests that take > 30s")


# --- Auto-deselect tests whose external substrate is unavailable ---

def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Deselect environment-dependent tests when their substrate is unavailable."""
    docker_available = docker_is_available()
    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []

    for item in items:
        if "docker" in item.keywords and not docker_available:
            deselected.append(item)
            continue
        missing_image = False
        for marker in item.iter_markers("docker_image"):
            image = str(marker.args[0]) if marker.args else ""
            if image and not docker_image_is_available(image):
                missing_image = True
                break
        if missing_image:
            deselected.append(item)
            continue
        selected.append(item)

    if deselected:
        items[:] = selected
        config.hook.pytest_deselected(items=deselected)
