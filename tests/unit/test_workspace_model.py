from __future__ import annotations

import json
from pathlib import Path

from echelon.workspace_model import (
    count_source_files,
    discover_workspace,
    load_workspace_manifest,
)


def _git_dir(path: Path) -> None:
    (path / ".git").mkdir(parents=True)


def test_single_repo_workspace_is_source_root(tmp_path: Path) -> None:
    _git_dir(tmp_path)
    (tmp_path / ".specify").mkdir()
    (tmp_path / "specs").mkdir()
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")

    manifest = discover_workspace(tmp_path)

    assert manifest.workspace.root == tmp_path.resolve()
    assert manifest.workspace.git_present is True
    assert manifest.workspace.git_role == "source"
    assert [source.path for source in manifest.sources] == ["."]
    assert manifest.sources[0].id == "."
    assert manifest.sources[0].git_present is True
    assert "package.json" in manifest.sources[0].project_markers


def test_polyrepo_workspace_uses_child_source_roots(tmp_path: Path) -> None:
    _git_dir(tmp_path)
    (tmp_path / ".specify").mkdir()
    (tmp_path / "specs").mkdir()
    for name, marker in [("og-platform", "package.json"), ("pbg-api", "pom.xml")]:
        repo = tmp_path / name
        repo.mkdir()
        _git_dir(repo)
        (repo / marker).write_text("{}", encoding="utf-8")

    manifest = discover_workspace(tmp_path)

    assert manifest.workspace.git_role == "orchestration"
    assert [source.id for source in manifest.sources] == ["og-platform", "pbg-api"]
    assert [source.path for source in manifest.sources] == ["og-platform", "pbg-api"]
    assert all(source.git_present for source in manifest.sources)


def test_planning_only_workspace_has_no_sources(tmp_path: Path) -> None:
    _git_dir(tmp_path)
    (tmp_path / ".specify").mkdir()
    (tmp_path / "specs").mkdir()

    manifest = discover_workspace(tmp_path)

    assert manifest.workspace.git_role == "orchestration"
    assert manifest.workspace.git_present is True
    assert manifest.sources == ()


def test_git_file_counts_as_git_presence_for_worktree_or_submodule(tmp_path: Path) -> None:
    _git_dir(tmp_path)
    source = tmp_path / "source-a"
    source.mkdir()
    (source / ".git").write_text("gitdir: ../.git/modules/source-a\n", encoding="utf-8")
    (source / "pyproject.toml").write_text("[project]\nname='source-a'\n", encoding="utf-8")

    manifest = discover_workspace(tmp_path)

    assert manifest.workspace.git_role == "orchestration"
    assert len(manifest.sources) == 1
    assert manifest.sources[0].id == "source-a"
    assert manifest.sources[0].git_present is True


def test_cmake_marker_qualifies_child_source_root(tmp_path: Path) -> None:
    _git_dir(tmp_path)
    source = tmp_path / "native-lib"
    source.mkdir()
    (source / "CMakeLists.txt").write_text("project(native-lib)\n", encoding="utf-8")

    manifest = discover_workspace(tmp_path)

    assert [source.path for source in manifest.sources] == ["native-lib"]
    assert manifest.sources[0].project_markers == ("CMakeLists.txt",)


def test_manifest_json_round_trips(tmp_path: Path) -> None:
    _git_dir(tmp_path)
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    manifest = discover_workspace(tmp_path)
    path = tmp_path / "workspace-manifest.json"
    path.write_text(json.dumps(manifest.to_json_dict(), indent=2), encoding="utf-8")

    loaded = load_workspace_manifest(path)

    assert loaded == manifest


def test_source_file_count_ignores_dependency_and_git_dirs(tmp_path: Path) -> None:
    (tmp_path / "node_modules" / "left-pad").mkdir(parents=True)
    (tmp_path / "node_modules" / "left-pad" / "index.js").write_text(
        "module.exports = 1;\n",
        encoding="utf-8",
    )
    (tmp_path / ".git" / "objects").mkdir(parents=True)
    (tmp_path / ".git" / "objects" / "ignored").write_text("git data\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")

    assert count_source_files(tmp_path) == 1
