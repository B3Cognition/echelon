"""Tests for polyrepo delivery runtime extension sync."""
from __future__ import annotations

from pathlib import Path

from echelon.cli import _sync_polyrepo_runtime_extension


def test_polyrepo_runtime_extension_excludes_python_migration_helpers(
    tmp_path: Path,
) -> None:
    """Target-specific harness roots should not expose workspace migration helpers."""
    source = tmp_path / "workspace" / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "scripts" / "python").mkdir(parents=True)
    (source / "agents" / "control" / "commander.md").write_text(
        "commander\n", encoding="utf-8"
    )
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    (source / "scripts" / "python" / "migrate_workspace_git.py").write_text(
        "print('migration helper')\n", encoding="utf-8"
    )

    harness_base = tmp_path / "workspace" / "runs" / "targets" / "prosaic"

    _sync_polyrepo_runtime_extension(tmp_path / "workspace", harness_base)

    runtime = harness_base / ".specify" / "extensions" / "echelon"
    assert (runtime / "agents" / "control" / "commander.md").exists()
    assert (runtime / "workflow" / "definition.yaml").exists()
    assert not (runtime / "scripts" / "python").exists()
