from __future__ import annotations

from pathlib import Path

import pytest


pytestmark = pytest.mark.unit


def test_inspect_workspace_returns_typed_findings(tmp_path: Path) -> None:
    from echelon.workspace_service import inspect_workspace

    result = inspect_workspace(tmp_path)

    assert result.buildable is False
    assert {finding.code for finding in result.findings} >= {
        "workspace_not_git_backed",
        "canonical_config_missing",
    }


def test_migrate_workspace_layout_applies_legacy_config(tmp_path: Path) -> None:
    from echelon.workspace_service import migrate_workspace_layout

    legacy = tmp_path / ".specify" / "extensions" / "echelon"
    legacy.mkdir(parents=True)
    (legacy / "echelon-config.yml").write_text(
        "verify_command: pytest\n",
        encoding="utf-8",
    )
    (tmp_path / "specs").mkdir()

    result = migrate_workspace_layout(
        tmp_path,
        write=True,
        commit=False,
        commit_message="chore: initialize echelon workspace",
    )

    assert result.canonical_config_copied is True
    assert (tmp_path / ".echelon" / "config.yml").read_text(encoding="utf-8") == (
        "verify_command: pytest\n"
    )


def test_sync_workspace_sources_reports_changes_without_writing(tmp_path: Path) -> None:
    from echelon.workspace_service import sync_workspace_sources

    (tmp_path / ".echelon").mkdir()
    config_path = tmp_path / ".echelon" / "config.yml"
    config_path.write_text(
        "workspace:\n  git_role: orchestration\nsources: []\n",
        encoding="utf-8",
    )
    source = tmp_path / "sources" / "api"
    source.mkdir(parents=True)
    (source / "package.json").write_text("{}\n", encoding="utf-8")

    result = sync_workspace_sources(tmp_path, write=False)

    assert result.dry_run is True
    assert result.added == ("api",)
    assert config_path.read_text(encoding="utf-8") == (
        "workspace:\n  git_role: orchestration\nsources: []\n"
    )
