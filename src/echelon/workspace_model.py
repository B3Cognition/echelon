from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

import yaml

from echelon.topology_model import (
    TopologyValidationError,
    normalize_source_root_path,
    normalize_source_path,
    validate_source_id,
)
from harness.config import CANONICAL_CONFIG_PATH, LEGACY_CONFIG_PATH

GitRole = Literal["orchestration", "source"]
WorkspaceConfigProvenance = Literal["canonical", "legacy"]
WorkspaceDeclarationMode = Literal["explicit", "empty", "implicit"]

_SAFE_SOURCE_ID = re.compile(r"^[A-Za-z0-9._-]+$")

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
class WorkspaceSourceDeclaration:
    id: str
    path: str
    git_role: GitRole = "source"


@dataclass(frozen=True)
class WorkspaceSourceDeclarations:
    workspace_git_role: GitRole
    sources: tuple[WorkspaceSourceDeclaration, ...]
    mode: WorkspaceDeclarationMode
    provenance: WorkspaceConfigProvenance
    config_path: Path
    config_relative_path: str
    config_sha256: str

    @property
    def source_paths(self) -> dict[str, str]:
        return {source.id: source.path for source in self.sources}


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
        dirnames[:] = [name for name in dirnames if not _is_ignored_source_dir(name)]
        count += len(filenames)
    return count


def _is_ignored_source_dir(name: str) -> bool:
    return name.startswith(".") or name in IGNORED_SOURCE_DIRS


def _source_roots_under(candidate_root: Path, workspace_root: Path) -> tuple[SourceRoot, ...]:
    sources: list[SourceRoot] = []
    for child in sorted(candidate_root.iterdir(), key=lambda item: item.name):
        if not child.is_dir() or _is_ignored_source_dir(child.name):
            continue
        markers = project_markers(child)
        git_present = has_git_marker(child)
        if not markers and not git_present:
            continue
        try:
            rel_path = child.relative_to(workspace_root).as_posix()
        except ValueError:
            rel_path = child.name
        sources.append(
            SourceRoot(
                id=child.name,
                path=rel_path,
                git_present=git_present,
                project_markers=markers,
                source_file_count=count_source_files(child),
            )
        )
    return tuple(sources)


def _sources_directory_child_roots(root: Path) -> tuple[SourceRoot, ...]:
    sources_container = root / "sources"
    if not sources_container.is_dir():
        return ()
    return _source_roots_under(sources_container, root)


def discover_sources_directory_roots(root: Path) -> tuple[SourceRoot, ...]:
    """Discover implementation roots under the canonical sources/ directory."""
    return _sources_directory_child_roots(root.resolve())


def _child_source_roots(root: Path) -> tuple[SourceRoot, ...]:
    return _source_roots_under(root, root) + _sources_directory_child_roots(root)


def load_workspace_source_declarations(
    root: Path,
) -> WorkspaceSourceDeclarations | None:
    """Parse source declarations and config provenance without reading source roots."""
    workspace_root = root.resolve()
    canonical_bytes = _read_authenticated_config(
        workspace_root, CANONICAL_CONFIG_PATH
    )
    if canonical_bytes is not None:
        config_path = workspace_root / CANONICAL_CONFIG_PATH
        relative_path = CANONICAL_CONFIG_PATH.as_posix()
        provenance: WorkspaceConfigProvenance = "canonical"
        config_bytes = canonical_bytes
    else:
        legacy_bytes = _read_authenticated_config(
            workspace_root, LEGACY_CONFIG_PATH
        )
        if legacy_bytes is None:
            return None
        config_path = workspace_root / LEGACY_CONFIG_PATH
        relative_path = LEGACY_CONFIG_PATH.as_posix()
        provenance = "legacy"
        config_bytes = legacy_bytes

    try:
        raw = yaml.safe_load(config_bytes.decode("utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(
            f"cannot parse workspace config {relative_path}: invalid YAML"
        ) from exc
    config_sha256 = "sha256:" + hashlib.sha256(config_bytes).hexdigest()
    if raw is None:
        raise ValueError("workspace config must be a mapping, not null")
    if not isinstance(raw, dict):
        raise ValueError("workspace config must be a mapping")

    if "workspace" in raw:
        workspace_raw = raw["workspace"]
        if not isinstance(workspace_raw, dict):
            raise ValueError("workspace config workspace must be a mapping")
    else:
        workspace_raw = {}

    sources_present = False
    if "sources" in raw:
        sources_raw = raw["sources"]
        sources_present = True
    elif "sources" in workspace_raw:
        sources_raw = workspace_raw["sources"]
        sources_present = True
    else:
        sources_raw = None
    git_role_value = str(workspace_raw.get("git_role") or "orchestration")
    workspace_git_role: GitRole = (
        git_role_value
        if git_role_value in {"orchestration", "source"}
        else "orchestration"
    )  # type: ignore[assignment]
    if not sources_present:
        return WorkspaceSourceDeclarations(
            workspace_git_role=workspace_git_role,
            sources=(),
            mode="implicit",
            provenance=provenance,
            config_path=config_path,
            config_relative_path=relative_path,
            config_sha256=config_sha256,
        )
    if not isinstance(sources_raw, list):
        raise ValueError("workspace config sources must be a list")
    if not sources_raw:
        return WorkspaceSourceDeclarations(
            workspace_git_role=workspace_git_role,
            sources=(),
            mode="empty",
            provenance=provenance,
            config_path=config_path,
            config_relative_path=relative_path,
            config_sha256=config_sha256,
        )

    sources: list[WorkspaceSourceDeclaration] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(sources_raw):
        entry = f"workspace config sources entry {index + 1}"
        if isinstance(item, str):
            source_path = item.strip()
            if not source_path:
                raise ValueError(f"{entry} must not be blank")
            source_id = source_path
            source_git_role: GitRole = "source"
        elif isinstance(item, dict):
            path_value = item.get("path")
            if path_value is None:
                path_value = item.get("repo")
            if path_value is None:
                raise ValueError(f"{entry} requires a path")
            if not isinstance(path_value, str):
                raise ValueError(f"{entry} path must be a string")
            source_path = path_value.strip()
            if not source_path:
                raise ValueError(f"{entry} requires a path")
            id_value = item.get("id")
            if id_value is not None and not isinstance(id_value, str):
                raise ValueError(f"{entry} id must be a string")
            source_id = id_value.strip() if isinstance(id_value, str) else source_path
            if not source_id:
                raise ValueError(f"{entry} id must not be blank")
            source_git_role = "source" if item.get("git_role") != "orchestration" else "orchestration"
        else:
            raise ValueError(f"{entry} must be a string or mapping")
        _validate_declared_source_id(source_id, entry)
        _validate_declared_source_path(source_path, entry)
        if source_id in seen_ids:
            raise ValueError(f"{entry} has duplicate source id: {source_id}")
        seen_ids.add(source_id)
        sources.append(
            WorkspaceSourceDeclaration(
                id=source_id,
                path=source_path,
                git_role=source_git_role,
            )
        )
    return WorkspaceSourceDeclarations(
        workspace_git_role=workspace_git_role,
        sources=tuple(sources),
        mode="explicit",
        provenance=provenance,
        config_path=config_path,
        config_relative_path=relative_path,
        config_sha256=config_sha256,
    )


def _read_authenticated_config(root: Path, relative: Path) -> bytes | None:
    """Read one regular config without following any descendant symlink."""
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    file_flags = os.O_RDONLY
    file_flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        current_fd = os.open(root, directory_flags)
    except OSError as exc:
        raise ValueError(f"unsafe workspace config root: {root}") from exc
    try:
        for component in relative.parts[:-1]:
            try:
                observed = os.stat(component, dir_fd=current_fd, follow_symlinks=False)
            except FileNotFoundError:
                return None
            except OSError as exc:
                raise ValueError(
                    f"unsafe workspace config path: {relative.as_posix()}"
                ) from exc
            if stat.S_ISLNK(observed.st_mode) or not stat.S_ISDIR(observed.st_mode):
                raise ValueError(
                    f"unsafe workspace config path: {relative.as_posix()}"
                )
            try:
                next_fd = os.open(component, directory_flags, dir_fd=current_fd)
            except OSError as exc:
                raise ValueError(
                    f"unsafe workspace config path: {relative.as_posix()}"
                ) from exc
            opened = os.fstat(next_fd)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != (observed.st_dev, observed.st_ino)
            ):
                os.close(next_fd)
                raise ValueError(
                    f"unsafe workspace config path: {relative.as_posix()}"
                )
            os.close(current_fd)
            current_fd = next_fd

        try:
            observed = os.stat(relative.name, dir_fd=current_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ValueError(
                f"unsafe workspace config path: {relative.as_posix()}"
            ) from exc
        if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
            raise ValueError(f"unsafe workspace config path: {relative.as_posix()}")
        try:
            config_fd = os.open(relative.name, file_flags, dir_fd=current_fd)
        except OSError as exc:
            raise ValueError(
                f"unsafe workspace config path: {relative.as_posix()}"
            ) from exc
        try:
            opened = os.fstat(config_fd)
            if (
                not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != (observed.st_dev, observed.st_ino)
            ):
                raise ValueError(
                    f"unsafe workspace config path: {relative.as_posix()}"
                )
            with os.fdopen(os.dup(config_fd), "rb") as handle:
                content = handle.read()
            rebound = os.stat(relative.name, dir_fd=current_fd, follow_symlinks=False)
            if (
                stat.S_ISLNK(rebound.st_mode)
                or (rebound.st_dev, rebound.st_ino, rebound.st_size, rebound.st_mtime_ns)
                != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            ):
                raise ValueError(
                    f"unsafe workspace config path: {relative.as_posix()}"
                )
            return content
        finally:
            os.close(config_fd)
    finally:
        os.close(current_fd)


def _validate_declared_source_id(source_id: str, entry: str) -> None:
    if not _SAFE_SOURCE_ID.fullmatch(source_id):
        raise ValueError(f"{entry} has unsafe source id: {source_id!r}")


def _validate_declared_source_path(source_path: str, entry: str) -> None:
    if (
        "\\" in source_path
        or "\x00" in source_path
        or source_path.startswith("/")
        or re.match(r"^[A-Za-z]:/", source_path)
        or any(part == ".." for part in source_path.split("/"))
        or posixpath.normpath(source_path) != source_path
    ):
        raise ValueError(f"{entry} has unsafe source path: {source_path!r}")


def validate_topology_source_declarations(sources: Iterable[object]) -> None:
    """Validate declarations for opt-in canonical topology publication."""
    for source in sources:
        source_id = getattr(source, "id", None)
        source_path = getattr(source, "path", None)
        try:
            validate_source_id(source_id)
            normalize_source_root_path(source_path)
        except (TopologyValidationError, TypeError) as exc:
            raise ValueError(
                f"workspace source {source_id!r} is not publishable as topology: {exc}"
            ) from exc


def _configured_workspace(root: Path) -> WorkspaceManifest | None:
    declarations = load_workspace_source_declarations(root)
    if declarations is None or declarations.mode == "implicit":
        return None
    if declarations.mode == "empty":
        discovered_sources = _sources_directory_child_roots(root)
        if discovered_sources:
            return WorkspaceManifest(
                schema_version=1,
                workspace=WorkspaceInfo(
                    root=root,
                    git_role=declarations.workspace_git_role,
                    git_present=has_git_marker(root),
                ),
                sources=discovered_sources,
            )

    sources: list[SourceRoot] = []
    for declaration in declarations.sources:
        resolved_source = root if declaration.path == "." else root / declaration.path
        sources.append(
            SourceRoot(
                id=declaration.id,
                path=declaration.path,
                git_present=has_git_marker(resolved_source),
                git_role=declaration.git_role,
                project_markers=(
                    project_markers(resolved_source) if resolved_source.exists() else ()
                ),
                source_file_count=(
                    count_source_files(resolved_source) if resolved_source.exists() else 0
                ),
            )
        )

    return WorkspaceManifest(
        schema_version=1,
        workspace=WorkspaceInfo(
            root=root,
            git_role=declarations.workspace_git_role,
            git_present=has_git_marker(root),
        ),
        sources=tuple(sources),
    )


def discover_workspace(root: Path) -> WorkspaceManifest:
    resolved = root.resolve()
    configured = _configured_workspace(resolved)
    if configured is not None:
        return configured

    workspace_git_present = has_git_marker(resolved)
    child_sources = _child_source_roots(resolved)
    root_markers = project_markers(resolved)

    child_git_sources = tuple(source for source in child_sources if source.git_present)

    if child_git_sources:
        git_role: GitRole = "orchestration"
        sources = child_sources
    elif root_markers and (workspace_git_present or not child_sources):
        git_role: GitRole = "source"
        sources = (
            SourceRoot(
                id=".",
                path=".",
                git_present=workspace_git_present,
                project_markers=root_markers,
                source_file_count=count_source_files(resolved),
            ),
        )
    elif child_sources:
        git_role = "orchestration"
        sources = child_sources
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
