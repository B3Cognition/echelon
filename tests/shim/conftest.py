"""Shim test conftest — manifest presence/absence fixture."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


SHIM_SCRIPT = str(
    Path(__file__).resolve().parent.parent.parent / "scripts" / "sandbox-exec.sh"
)


@pytest.fixture
def shim_script():
    """Path to sandbox-exec.sh."""
    return SHIM_SCRIPT


@pytest.fixture
def harness_dir_with_manifest(tmp_path):
    """Create a directory with harness manifest present."""
    manifest_dir = tmp_path / ".specify" / "extensions" / "harness"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "manifest.json").write_text('{"name": "spec-kit-harness"}')
    return tmp_path


@pytest.fixture
def harness_dir_without_manifest(tmp_path):
    """Create a directory without harness manifest."""
    return tmp_path
