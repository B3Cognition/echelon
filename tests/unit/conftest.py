"""Unit test fixtures for the Echelon harness."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
CONFIGS_DIR = FIXTURES_DIR / "configs"


@pytest.fixture
def configs_dir() -> Path:
    """Path to config fixture directory."""
    return CONFIGS_DIR


@pytest.fixture
def valid_minimal_config(configs_dir: Path) -> Path:
    """Path to valid minimal config fixture."""
    return configs_dir / "valid-minimal.yml"


@pytest.fixture
def valid_full_config(configs_dir: Path) -> Path:
    """Path to valid full config fixture."""
    return configs_dir / "valid-full.yml"
