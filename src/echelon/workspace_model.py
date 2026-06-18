from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

GitRole = Literal["orchestration", "source"]

SOURCE_MARKERS = (
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "CMakeLists.txt",
    "composer.json",
    "Gemfile",
    "setup.py",
    "Package.swift",
    "*.xcodeproj",
    "*.xcworkspace",
    "*.sln",
    "*.dpr",
    "nx.json",
    "Makefile",
)

IGNORED_SOURCE_DIRS = {
    ".git",
    ".specify",
    ".echelon",
    ".venv",
    "__pycache__",
    "node_modules",
    "runs",
    "specs",
    ".worktrees",
}


@dataclass(frozen=True)
class WorkspaceInfo:
    root: Path
    git_role: GitRole
    git_present: bool

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "git_role": self.git_role,
            "git_present": self.git_present,
        }

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> WorkspaceInfo:
        return cls(
            root=Path(str(data["root"])).resolve(),
            git_role=data["git_role"],
            git_present=bool(data["git_present"]),
        )


@dataclass(frozen=True)
class SourceRoot:
    id: str
    path: str
    git_present: bool
    git_role: GitRole = "source"
    project_markers: tuple[str, ...] = ()
    source_file_count: int = 0

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "git_role": self.git_role,
            "git_present": self.git_present,
            "project_markers": list(self.project_markers),
            "source_file_count": self.source_file_count,
        }

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> SourceRoot:
        return cls(
            id=str(data["id"]),
            path=str(data["path"]),
            git_role=data.get("git_role", "source"),
            git_present=bool(data.get("git_present", False)),
            project_markers=tuple(str(item) for item in data.get("project_markers", [])),
            source_file_count=int(data.get("source_file_count", 0)),
        )


@dataclass(frozen=True)
class WorkspaceManifest:
    schema_version: int
    workspace: WorkspaceInfo
    sources: tuple[SourceRoot, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "workspace": self.workspace.to_json_dict(),
            "sources": [source.to_json_dict() for source in self.sources],
        }

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> WorkspaceManifest:
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            workspace=WorkspaceInfo.from_json_dict(data["workspace"]),
            sources=tuple(
                SourceRoot.from_json_dict(item) for item in data.get("sources", [])
            ),
        )


def has_git_marker(path: Path) -> bool:
    marker = path / ".git"
    return marker.is_dir() or marker.is_file()


def project_markers(path: Path) -> tuple[str, ...]:
    found: list[str] = []
    for marker in SOURCE_MARKERS:
        if "*" in marker:
            found.extend(sorted(item.name for item in path.glob(marker) if item.exists()))
        elif (path / marker).exists():
            found.append(marker)
    return tuple(found)


def count_source_files(path: Path) -> int:
    count = 0
    for _, dirnames, filenames in os.walk(path):
        dirnames[:] = [name for name in dirnames if name not in IGNORED_SOURCE_DIRS]
        count += len(filenames)
    return count


def _child_source_roots(root: Path) -> tuple[SourceRoot, ...]:
    sources: list[SourceRoot] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if not child.is_dir() or child.name in IGNORED_SOURCE_DIRS:
            continue
        markers = project_markers(child)
        git_present = has_git_marker(child)
        if not markers and not git_present:
            continue
        sources.append(
            SourceRoot(
                id=child.name,
                path=child.name,
                git_present=git_present,
                project_markers=markers,
                source_file_count=count_source_files(child),
            )
        )
    return tuple(sources)


def discover_workspace(root: Path) -> WorkspaceManifest:
    resolved = root.resolve()
    workspace_git_present = has_git_marker(resolved)
    child_sources = _child_source_roots(resolved)
    root_markers = project_markers(resolved)

    if child_sources:
        git_role: GitRole = "orchestration"
        sources = child_sources
    elif root_markers:
        git_role = "source"
        sources = (
            SourceRoot(
                id=".",
                path=".",
                git_present=workspace_git_present,
                project_markers=root_markers,
                source_file_count=count_source_files(resolved),
            ),
        )
    else:
        git_role = "orchestration"
        sources = ()

    return WorkspaceManifest(
        schema_version=1,
        workspace=WorkspaceInfo(
            root=resolved,
            git_role=git_role,
            git_present=workspace_git_present,
        ),
        sources=sources,
    )


def load_workspace_manifest(path: Path) -> WorkspaceManifest:
    return WorkspaceManifest.from_json_dict(json.loads(path.read_text(encoding="utf-8")))


def write_workspace_manifest(root: Path, output: Path) -> WorkspaceManifest:
    manifest = discover_workspace(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest.to_json_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write Echelon workspace manifest")
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    write_workspace_manifest(args.root, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
