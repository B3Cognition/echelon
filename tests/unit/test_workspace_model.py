from __future__ import annotations

import json
from pathlib import Path

import pytest

from echelon.workspace_model import (
    count_source_files,
    discover_workspace,
    load_workspace_source_declarations,
    load_workspace_manifest,
    validate_topology_source_declarations,
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
    validate_topology_source_declarations(manifest.sources)


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


def test_workspace_uses_sources_directory_children_as_source_roots(tmp_path: Path) -> None:
    _git_dir(tmp_path)
    (tmp_path / ".specify").mkdir()
    (tmp_path / "specs").mkdir()
    sources_dir = tmp_path / "sources"
    for name, marker in [("spec-kit", "pyproject.toml"), ("ruler", "package.json")]:
        repo = sources_dir / name
        repo.mkdir(parents=True)
        (repo / marker).write_text("{}\n", encoding="utf-8")

    manifest = discover_workspace(tmp_path)

    assert manifest.workspace.git_role == "orchestration"
    assert [source.id for source in manifest.sources] == ["ruler", "spec-kit"]
    assert [source.path for source in manifest.sources] == [
        "sources/ruler",
        "sources/spec-kit",
    ]


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


def test_declaration_loader_reports_canonical_config_without_reading_sources(
    tmp_path: Path,
) -> None:
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon/config.yml").write_text(
        "workspace:\n  git_role: orchestration\n  sources:\n"
        "    - id: api\n      path: sources/api\n",
        encoding="utf-8",
    )

    declarations = load_workspace_source_declarations(tmp_path)

    assert declarations is not None
    assert declarations.provenance == "canonical"
    assert declarations.config_relative_path == ".echelon/config.yml"
    assert declarations.config_sha256.startswith("sha256:")
    assert len(declarations.config_sha256) == 71
    assert declarations.mode == "explicit"
    assert [(source.id, source.path) for source in declarations.sources] == [
        ("api", "sources/api")
    ]


def test_declaration_loader_reports_legacy_config_provenance(tmp_path: Path) -> None:
    config = tmp_path / ".specify/extensions/echelon/echelon-config.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "workspace:\n  sources:\n    - id: api\n      path: sources/api\n",
        encoding="utf-8",
    )

    declarations = load_workspace_source_declarations(tmp_path)

    assert declarations is not None
    assert declarations.provenance == "legacy"
    assert declarations.config_relative_path == (
        ".specify/extensions/echelon/echelon-config.yml"
    )
    assert declarations.mode == "explicit"


@pytest.mark.parametrize(
    ("provenance", "symlink_component"),
    (
        ("canonical", "file"),
        ("canonical", "parent"),
        ("legacy", "file"),
        ("legacy", "parent"),
    ),
)
def test_declaration_loader_rejects_symlinked_config_components(
    tmp_path: Path,
    provenance: str,
    symlink_component: str,
) -> None:
    forbidden = tmp_path / "sources/web/config"
    forbidden.mkdir(parents=True)
    config_name = (
        "config.yml"
        if provenance == "canonical"
        else "echelon-config.yml"
    )
    (forbidden / config_name).write_text(
        "workspace:\n  sources:\n    - id: api\n      path: sources/api\n",
        encoding="utf-8",
    )
    relative = (
        Path(".echelon/config.yml")
        if provenance == "canonical"
        else Path(".specify/extensions/echelon/echelon-config.yml")
    )
    config = tmp_path / relative
    if symlink_component == "file":
        config.parent.mkdir(parents=True)
        config.symlink_to(forbidden / config_name)
    elif provenance == "canonical":
        (tmp_path / ".echelon").symlink_to(forbidden, target_is_directory=True)
    else:
        (tmp_path / ".specify").symlink_to(forbidden, target_is_directory=True)

    with pytest.raises(ValueError, match="unsafe workspace config path"):
        load_workspace_source_declarations(tmp_path)


@pytest.mark.parametrize("provenance", ("canonical", "legacy"))
def test_ordinary_discovery_normalizes_malformed_workspace_yaml(
    tmp_path: Path,
    provenance: str,
) -> None:
    config = (
        tmp_path / ".echelon/config.yml"
        if provenance == "canonical"
        else tmp_path / ".specify/extensions/echelon/echelon-config.yml"
    )
    config.parent.mkdir(parents=True)
    config.write_text("workspace:\n  sources: [api\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"cannot parse workspace config .*config\.yml: invalid YAML",
    ):
        discover_workspace(tmp_path)


def test_declaration_loader_supports_repo_and_null_or_missing_id_fallback(
    tmp_path: Path,
) -> None:
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon/config.yml").write_text(
        "sources:\n"
        "  - repo: api\n"
        "  - id: null\n    path: web\n"
        "  - path: docs\n",
        encoding="utf-8",
    )

    declarations = load_workspace_source_declarations(tmp_path)

    assert declarations is not None
    assert [(source.id, source.path) for source in declarations.sources] == [
        ("api", "api"),
        ("web", "web"),
        ("docs", "docs"),
    ]


@pytest.mark.parametrize(
    ("sources", "message"),
    (
        ("  - id: '../api'\n    path: sources/api\n", "unsafe source id"),
        ("  - id: api\n    path: ../api\n", "unsafe source path"),
        (
            "  - id: api\n    path: sources/api\n"
            "  - id: api\n    path: sources/web\n",
            "duplicate source id",
        ),
    ),
)
def test_declaration_loader_rejects_unsafe_or_duplicate_sources(
    tmp_path: Path,
    sources: str,
    message: str,
) -> None:
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon/config.yml").write_text(
        "sources:\n" + sources,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        load_workspace_source_declarations(tmp_path)


def test_ordinary_discovery_preserves_topology_incompatible_declarations(
    tmp_path: Path,
) -> None:
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon/config.yml").write_text(
        "workspace:\n  sources:\n    - id: -api\n      path: .\n",
        encoding="utf-8",
    )

    manifest = discover_workspace(tmp_path)

    assert [(source.id, source.path) for source in manifest.sources] == [("-api", ".")]


def test_configured_empty_sources_without_sources_directory_means_planning_only(
    tmp_path: Path,
) -> None:
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


def test_configured_empty_sources_discovers_sources_directory_children(
    tmp_path: Path,
) -> None:
    _git_dir(tmp_path)
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "workspace:\n"
        "  git_role: orchestration\n"
        "sources: []\n",
        encoding="utf-8",
    )
    source = tmp_path / "sources" / "optasearch-pro"
    source.mkdir(parents=True)
    (source / "package.json").write_text("{}\n", encoding="utf-8")

    manifest = discover_workspace(tmp_path)

    assert manifest.workspace.git_role == "orchestration"
    assert [source.id for source in manifest.sources] == ["optasearch-pro"]
    assert [source.path for source in manifest.sources] == ["sources/optasearch-pro"]


@pytest.mark.parametrize(
    ("document", "message"),
    (
        ("workspace: null\nsources: []\n", "workspace must be a mapping"),
        ("workspace: []\nsources: []\n", "workspace must be a mapping"),
        ("workspace: source\nsources: []\n", "workspace must be a mapping"),
        ("sources: null\n", "sources must be a list"),
        ("sources:\n  api: sources/api\n", "sources must be a list"),
        ("sources: api\n", "sources must be a list"),
        ("sources:\n  - 42\n", "sources entry 1 must be"),
        ("sources:\n  - ''\n", "sources entry 1 must not be blank"),
        ("sources:\n  - id: api\n", "sources entry 1 requires a path"),
        ("sources:\n  - path: 42\n", "sources entry 1 path must be a string"),
        ("sources:\n  - id: 42\n    path: sources/api\n", "sources entry 1 id must be a string"),
    ),
)
def test_explicit_malformed_workspace_shapes_never_fall_back_to_discovery(
    tmp_path: Path,
    document: str,
    message: str,
) -> None:
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon/config.yml").write_text(document, encoding="utf-8")
    auto = tmp_path / "auto-discovered"
    auto.mkdir()
    (auto / "package.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        discover_workspace(tmp_path)


def test_config_without_workspace_or_sources_intentionally_uses_discovery(
    tmp_path: Path,
) -> None:
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon/config.yml").write_text(
        "telemetry:\n  enabled: true\n",
        encoding="utf-8",
    )
    source = tmp_path / "auto-discovered"
    source.mkdir()
    (source / "package.json").write_text("{}\n", encoding="utf-8")

    manifest = discover_workspace(tmp_path)

    assert [row.path for row in manifest.sources] == ["auto-discovered"]


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


def test_source_file_count_ignores_dependency_and_hidden_dirs(tmp_path: Path) -> None:
    (tmp_path / "node_modules" / "left-pad").mkdir(parents=True)
    (tmp_path / "node_modules" / "left-pad" / "index.js").write_text(
        "module.exports = 1;\n",
        encoding="utf-8",
    )
    (tmp_path / ".git" / "objects").mkdir(parents=True)
    (tmp_path / ".git" / "objects" / "ignored").write_text("git data\n", encoding="utf-8")
    (tmp_path / ".github" / "skills").mkdir(parents=True)
    (tmp_path / ".github" / "skills" / "logger.ts").write_text(
        "export const ignored = true;\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")

    assert count_source_files(tmp_path) == 1
