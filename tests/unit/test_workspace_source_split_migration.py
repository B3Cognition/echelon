from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from echelon.workspace_source_split_migration import (
    SplitMigrationError,
    split_workspace_source_repo,
)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def _workspace_app_repo(root: Path) -> None:
    (root / ".specify").mkdir()
    (root / "runs").mkdir()
    spec_dir = root / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
    (root / ".gitignore").write_text("runs\n.build/\n", encoding="utf-8")
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")
    (root / ".harness-build-status.json").write_text('{"status":"done"}\n', encoding="utf-8")
    (root / ".swiftlint.yml").write_text("disabled_rules: []\n", encoding="utf-8")
    (root / "project.yml").write_text("name: Demo\n", encoding="utf-8")
    (root / "App.xcodeproj").mkdir()
    (root / "App.xcodeproj" / "project.pbxproj").write_text("proj\n", encoding="utf-8")
    (root / "Sources").mkdir()
    (root / "Sources" / "main.swift").write_text("print(\"hi\")\n", encoding="utf-8")
    _git(root, "init")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-m", "initial")


@pytest.mark.unit
def test_split_dry_run_lists_source_paths_without_writing(tmp_path: Path) -> None:
    _workspace_app_repo(tmp_path)

    result = split_workspace_source_repo(tmp_path, source_dir="app", write=False, commit=False)

    assert result.write_requested is False
    assert result.moved_paths == ()
    assert result.plan.source_dir == tmp_path / "app"
    assert result.plan.keep_names >= {".git", ".specify", "specs", "runs", ".gitignore"}
    assert result.plan.move_names == (".github", ".swiftlint.yml", "App.xcodeproj", "Sources", "project.yml")
    assert result.plan.drop_names == (".harness-build-status.json",)
    assert not (tmp_path / "app").exists()


@pytest.mark.unit
def test_split_write_moves_source_initializes_child_git_and_stages_root(
    tmp_path: Path,
) -> None:
    _workspace_app_repo(tmp_path)

    result = split_workspace_source_repo(tmp_path, source_dir="app", write=True, commit=False)

    assert result.write_requested is True
    assert result.child_git_initialized is True
    assert result.child_committed is True
    assert set(result.moved_paths) == {".github", ".swiftlint.yml", "App.xcodeproj", "Sources", "project.yml"}
    assert (tmp_path / "app" / ".git").exists()
    assert (tmp_path / "app" / ".gitignore").read_text(encoding="utf-8") == "runs\n.build/\n"
    assert (tmp_path / "app" / ".github" / "workflows" / "ci.yml").exists()
    assert not (tmp_path / "app" / ".harness-build-status.json").exists()
    assert not (tmp_path / ".harness-build-status.json").exists()
    assert (tmp_path / "app" / ".swiftlint.yml").exists()
    assert (tmp_path / "app" / "Sources" / "main.swift").exists()
    assert not (tmp_path / "Sources").exists()
    assert "/app/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")

    staged = _git(tmp_path, "diff", "--cached", "--name-status").stdout
    assert "D\tSources/main.swift" in staged
    assert "D\tproject.yml" in staged
    assert "D\tApp.xcodeproj/project.pbxproj" in staged
    assert "D\t.github/workflows/ci.yml" in staged
    assert "D\t.harness-build-status.json" in staged
    assert "D\t.swiftlint.yml" in staged
    assert "M\t.gitignore" in staged
    assert ".harness-build-status.json" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "?? app/" not in _git(tmp_path, "status", "--short").stdout
    assert "!! app/" in _git(tmp_path, "status", "--short", "--ignored").stdout

    child_status = _git(tmp_path / "app", "status", "--short", "--branch").stdout
    assert child_status == "## main\n"


@pytest.mark.unit
def test_split_refuses_tracked_dirty_workspace(tmp_path: Path) -> None:
    _workspace_app_repo(tmp_path)
    (tmp_path / "project.yml").write_text("name: Changed\n", encoding="utf-8")

    with pytest.raises(SplitMigrationError, match="tracked changes"):
        split_workspace_source_repo(tmp_path, source_dir="app", write=True, commit=False)


@pytest.mark.unit
def test_split_refuses_existing_source_dir(tmp_path: Path) -> None:
    _workspace_app_repo(tmp_path)
    (tmp_path / "app").mkdir()

    with pytest.raises(SplitMigrationError, match="source dir already exists"):
        split_workspace_source_repo(tmp_path, source_dir="app", write=False, commit=False)
