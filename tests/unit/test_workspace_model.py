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


def test_git_backed_root_with_project_marker_remains_single_source_root(
    tmp_path: Path,
) -> None:
    _git_dir(tmp_path)
    (tmp_path / ".specify").mkdir()
    (tmp_path / "specs").mkdir()
    (tmp_path / "App.xcodeproj").mkdir()
    (tmp_path / "App.xcodeproj" / "project.xcworkspace").mkdir()
    package = tmp_path / "Lambda"
    package.mkdir()
    (package / "Package.swift").write_text("// swift package\n", encoding="utf-8")

    manifest = discover_workspace(tmp_path)

    assert manifest.workspace.git_role == "source"
    assert [source.path for source in manifest.sources] == ["."]
    assert manifest.sources[0].git_present is True


def test_branchless_wrapper_with_project_marker_and_children_uses_child_sources(
    tmp_path: Path,
) -> None:
    (tmp_path / "package.json").write_text('{"name":"workspace-wrapper"}\n', encoding="utf-8")
    for name in ("app-a", "lib"):
        source = tmp_path / name
        source.mkdir()
        (source / "package.json").write_text(f'{{"name":"{name}"}}\n', encoding="utf-8")

    manifest = discover_workspace(tmp_path)

    assert manifest.workspace.git_role == "orchestration"
    assert [source.path for source in manifest.sources] == ["app-a", "lib"]


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


def test_configured_sources_override_auto_discovery(tmp_path: Path) -> None:
    _git_dir(tmp_path)
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "workspace:\n"
        "  git_role: orchestration\n"
        "sources:\n"
        "  - id: app\n"
        "    path: services/app\n",
        encoding="utf-8",
    )
    auto = tmp_path / "auto-detected"
    auto.mkdir()
    (auto / "package.json").write_text("{}\n", encoding="utf-8")
    configured = tmp_path / "services" / "app"
    configured.mkdir(parents=True)
    (configured / "pyproject.toml").write_text("[project]\nname='app'\n", encoding="utf-8")

    manifest = discover_workspace(tmp_path)

    assert manifest.workspace.git_role == "orchestration"
    assert [source.id for source in manifest.sources] == ["app"]
    assert [source.path for source in manifest.sources] == ["services/app"]
    assert "pyproject.toml" in manifest.sources[0].project_markers


def test_configured_empty_sources_means_planning_only(tmp_path: Path) -> None:
    _git_dir(tmp_path)
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "workspace:\n"
        "  git_role: orchestration\n"
        "sources: []\n",
        encoding="utf-8",
    )
    source = tmp_path / "app"
    source.mkdir()
    (source / "package.json").write_text("{}\n", encoding="utf-8")

    manifest = discover_workspace(tmp_path)

    assert manifest.workspace.git_role == "orchestration"
    assert manifest.sources == ()


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


def test_workspace_model_matches_legacy_discovery_markers(tmp_path: Path) -> None:
    _git_dir(tmp_path)
    markers = {
        "php-lib": "composer.json",
        "ruby-lib": "Gemfile",
        "python-setup": "setup.py",
        "dotnet-solution": "Example.sln",
        "delphi-project": "Example.dpr",
    }
    for dirname, marker in markers.items():
        source = tmp_path / dirname
        source.mkdir()
        (source / marker).write_text("marker\n", encoding="utf-8")

    manifest = discover_workspace(tmp_path)

    assert [source.path for source in manifest.sources] == sorted(markers)
    marker_by_source = {
        source.path: source.project_markers[0] for source in manifest.sources
    }
    assert marker_by_source == markers


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
