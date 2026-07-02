from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from echelon.workspace_git_migration import (
    MigrationError,
    build_migration_plan,
    migrate_workspace,
)


def _write_workspace(path: Path) -> None:
    (path / ".specify").mkdir()
    spec_dir = path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")


@pytest.mark.unit
def test_migration_plan_ignores_child_source_roots(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    source = tmp_path / "og-platform"
    (source / ".git").mkdir(parents=True)
    (source / "package.json").write_text("{}\n", encoding="utf-8")

    plan = build_migration_plan(tmp_path)

    assert plan.workspace_root == tmp_path.resolve()
    assert plan.source_ignore_entries == ("/og-platform/",)
    assert plan.runtime_ignore_entries == ("/.specify/", "/runs/")
    assert plan.stage_paths == (".gitignore", "specs")
    assert plan.already_git_backed is False


@pytest.mark.unit
def test_migration_write_initializes_git_and_stages_only_workspace_files(
    tmp_path: Path,
) -> None:
    _write_workspace(tmp_path)
    source = tmp_path / "og-platform"
    (source / ".git").mkdir(parents=True)
    (source / "package.json").write_text("{}\n", encoding="utf-8")

    result = migrate_workspace(tmp_path, write=True, commit=False)

    assert result.git_initialized is True
    assert result.committed is False
    assert (tmp_path / ".git").exists()
    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "/og-platform/" in gitignore
    assert "/.specify/" in gitignore
    assert "/runs/" in gitignore
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert ".gitignore" in staged
    assert ".specify" not in staged
    assert "specs/001-demo/spec.md" in staged
    assert not any(path.startswith("og-platform/") for path in staged)


@pytest.mark.unit
def test_existing_git_workspace_migration_only_stages_gitignore(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    source = tmp_path / "og-platform"
    (source / ".git").mkdir(parents=True)
    (source / "package.json").write_text("{}\n", encoding="utf-8")

    result = migrate_workspace(tmp_path, write=True, commit=False)

    assert result.git_initialized is False
    assert result.staged_paths == (".gitignore",)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert staged == [".gitignore"]


@pytest.mark.unit
def test_existing_gitignore_runtime_entries_satisfy_runtime_ignore(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    (tmp_path / ".gitignore").write_text(".specify\nruns\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    result = migrate_workspace(tmp_path, write=True, commit=False)

    assert result.gitignore_updated is False
    assert result.staged_paths == ()
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == ".specify\nruns\n"


@pytest.mark.unit
def test_migration_refuses_non_echelon_workspace(tmp_path: Path) -> None:
    (tmp_path / "source").mkdir()

    with pytest.raises(MigrationError, match="not an Echelon workspace"):
        build_migration_plan(tmp_path)


@pytest.mark.unit
def test_migration_dry_run_does_not_write(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    (tmp_path / "repo" / ".git").mkdir(parents=True)

    result = migrate_workspace(tmp_path, write=False, commit=False)

    assert result.git_initialized is False
    assert result.committed is False
    assert not (tmp_path / ".git").exists()
    assert not (tmp_path / ".gitignore").exists()
