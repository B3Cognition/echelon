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


def test_polyrepo_runtime_extension_excludes_reverse_engineering_bash_helpers(
    tmp_path: Path,
) -> None:
    """Target-specific harness roots should not expose RE shell helpers."""
    source = tmp_path / "workspace" / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "scripts" / "bash" / "re").mkdir(parents=True)
    (source / "scripts" / "bash").mkdir(exist_ok=True)
    (source / "agents" / "control" / "commander.md").write_text(
        "commander\n", encoding="utf-8"
    )
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    (source / "scripts" / "bash" / "echelon-config-get.sh").write_text(
        "#!/usr/bin/env bash\n", encoding="utf-8"
    )
    (source / "scripts" / "bash" / "re" / "discover-repos.sh").write_text(
        "#!/usr/bin/env bash\n", encoding="utf-8"
    )

    harness_base = tmp_path / "workspace" / "runs" / "targets" / "prosaic"

    _sync_polyrepo_runtime_extension(tmp_path / "workspace", harness_base)

    runtime = harness_base / ".specify" / "extensions" / "echelon"
    assert (runtime / "scripts" / "bash" / "echelon-config-get.sh").exists()
    assert not (runtime / "scripts" / "bash" / "re").exists()


def test_polyrepo_runtime_extension_excludes_phase_a_presets(
    tmp_path: Path,
) -> None:
    """Target-specific harness roots should not expose preset seed material."""
    source = tmp_path / "workspace" / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "presets" / "echelon-brownfield-cloud-native" / "templates").mkdir(
        parents=True
    )
    (source / "templates").mkdir()
    (source / "agents" / "control" / "commander.md").write_text(
        "commander\n", encoding="utf-8"
    )
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    (
        source
        / "presets"
        / "echelon-brownfield-cloud-native"
        / "templates"
        / "spec-template.md"
    ).write_text("# preset spec template\n", encoding="utf-8")
    (source / "templates" / "tasks-template.md").write_text(
        "# runtime task template\n", encoding="utf-8"
    )

    harness_base = tmp_path / "workspace" / "runs" / "targets" / "prosaic"

    _sync_polyrepo_runtime_extension(tmp_path / "workspace", harness_base)

    runtime = harness_base / ".specify" / "extensions" / "echelon"
    assert (runtime / "templates" / "tasks-template.md").exists()
    assert not (runtime / "presets").exists()
