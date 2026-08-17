"""Workspace-aware source planning for immutable RE v2 snapshots."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

from .snapshot import ReV2SnapshotError

_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")


class ReV2WorkspaceSourceError(ReV2SnapshotError):
    """Raised when declared workspace sources cannot be frozen safely."""


@dataclass(frozen=True, slots=True)
class WorkspaceSourceProof:
    source_id: str
    git_role: str
    workspace_path: str
    repository: Path
    repository_path: str
    commit: str


@dataclass(frozen=True, slots=True)
class WorkspaceCapturePlan:
    workspace_root: Path
    sources: tuple[WorkspaceSourceProof, ...]
    repositories: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class _ResolvedSource:
    source_id: str
    git_role: str
    workspace_path: str
    path: Path
    repository: Path
    repository_path: str


def plan_clean_workspace_sources(
    workspace_root: Path,
    sources: Iterable[object],
) -> WorkspaceCapturePlan:
    """Resolve declared source roots and prove their Git repositories are clean."""
    issues: list[str] = []
    if workspace_root.is_symlink():
        raise ReV2WorkspaceSourceError(
            f"RE v2 workspace root must not be a symlink: {workspace_root}"
        )
    try:
        root = workspace_root.resolve(strict=True)
    except OSError as exc:
        raise ReV2WorkspaceSourceError(
            f"RE v2 workspace root is unavailable: {workspace_root}: {exc}"
        ) from exc
    if not root.is_dir():
        raise ReV2WorkspaceSourceError(f"RE v2 workspace root is not a directory: {root}")

    declared = tuple(sources)
    if not declared:
        raise ReV2WorkspaceSourceError("RE v2 requires at least one declared source")

    resolved: list[_ResolvedSource] = []
    seen_ids: set[str] = set()
    seen_paths: dict[str, str] = {}
    for source in declared:
        source_id = getattr(source, "id", None)
        path_value = getattr(source, "path", None)
        git_role = getattr(source, "git_role", "source")
        label = source_id if isinstance(source_id, str) and source_id else "<unknown>"

        if not isinstance(source_id, str) or not _SAFE_ID_RE.fullmatch(source_id):
            issues.append(f"source {label!r}: ID must be a nonempty safe ID")
            continue
        if source_id in seen_ids:
            issues.append(f"source {source_id!r}: duplicate source ID")
            continue
        seen_ids.add(source_id)
        if not isinstance(git_role, str) or not _SAFE_ID_RE.fullmatch(git_role):
            issues.append(f"source {source_id!r}: git_role must be a nonempty safe ID")
            continue

        workspace_path = _canonical_workspace_path(path_value)
        if workspace_path is None:
            issues.append(
                f"source {source_id!r}: path must be a canonical relative workspace path"
            )
            continue
        if workspace_path in seen_paths:
            issues.append(
                f"source {source_id!r}: path duplicates source {seen_paths[workspace_path]!r}"
            )
            continue
        seen_paths[workspace_path] = source_id

        lexical_path = root if workspace_path == "." else root / workspace_path
        symlink = _first_symlink(root, workspace_path)
        if symlink is not None:
            issues.append(f"source {source_id!r}: source path contains symlink {symlink}")
            continue
        if not lexical_path.exists() or not lexical_path.is_dir():
            issues.append(f"source {source_id!r}: source directory is missing: {workspace_path}")
            continue

        top_level = _run_git_text(lexical_path, "rev-parse", "--show-toplevel")
        if top_level.returncode != 0:
            issues.append(f"source {source_id!r}: source must be backed by a Git repository")
            continue
        try:
            repository = Path(top_level.stdout.strip()).resolve(strict=True)
            repository.relative_to(root)
            repository_path = lexical_path.relative_to(repository).as_posix()
        except (OSError, ValueError):
            issues.append(
                f"source {source_id!r}: Git repository must remain inside the workspace"
            )
            continue
        if repository_path == "":
            repository_path = "."
        resolved.append(
            _ResolvedSource(
                source_id=source_id,
                git_role=git_role,
                workspace_path=workspace_path,
                path=lexical_path,
                repository=repository,
                repository_path=repository_path,
            )
        )

    _append_overlap_issues(resolved, issues)

    repository_commits: dict[Path, str] = {}
    for repository in sorted(
        {source.repository for source in resolved},
        key=lambda path: path.relative_to(root).as_posix(),
    ):
        source_ids = sorted(
            source.source_id for source in resolved if source.repository == repository
        )
        source_label = ", ".join(source_ids)
        commit_result = _run_git_text(repository, "rev-parse", "--verify", "HEAD^{commit}")
        if commit_result.returncode != 0 or not commit_result.stdout.strip():
            issues.append(
                f"source(s) {source_label}: Git repository has no resolvable HEAD commit"
            )
            continue
        repository_commits[repository] = commit_result.stdout.strip()

        categories = _repository_dirty_categories(repository)
        if categories:
            summary = ", ".join(
                f"{name} ({count})" for name, count in sorted(categories.items())
            )
            issues.append(f"source(s) {source_label}: Git repository is dirty: {summary}")

    if issues:
        detail = "\n".join(f"- {issue}" for issue in issues)
        raise ReV2WorkspaceSourceError(
            "RE v2 requires every declared source to be Git-backed and clean.\n"
            f"{detail}\n"
            "Commit the source changes, stash them including untracked files "
            "(`git stash --include-untracked`), or revert/remove them before proceeding."
        )

    proofs = tuple(
        WorkspaceSourceProof(
            source_id=source.source_id,
            git_role=source.git_role,
            workspace_path=source.workspace_path,
            repository=source.repository,
            repository_path=source.repository_path,
            commit=repository_commits[source.repository],
        )
        for source in sorted(resolved, key=lambda item: (item.source_id, item.workspace_path))
    )
    repositories = tuple(
        sorted(
            repository_commits,
            key=lambda path: path.relative_to(root).as_posix(),
        )
    )
    return WorkspaceCapturePlan(
        workspace_root=root,
        sources=proofs,
        repositories=repositories,
    )


def _canonical_workspace_path(value: object) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        return None
    canonical = path.as_posix()
    if canonical != value or canonical.startswith("./"):
        return None
    return canonical


def _first_symlink(root: Path, workspace_path: str) -> str | None:
    current = root
    if workspace_path == ".":
        return "." if current.is_symlink() else None
    for part in PurePosixPath(workspace_path).parts:
        current = current / part
        if current.is_symlink():
            return current.relative_to(root).as_posix()
    return None


def _append_overlap_issues(sources: list[_ResolvedSource], issues: list[str]) -> None:
    ordered = sorted(sources, key=lambda source: PurePosixPath(source.workspace_path).parts)
    for index, first in enumerate(ordered):
        first_parts = PurePosixPath(first.workspace_path).parts
        for second in ordered[index + 1 :]:
            second_parts = PurePosixPath(second.workspace_path).parts
            if second_parts[: len(first_parts)] == first_parts:
                issues.append(
                    f"sources {first.source_id!r} and {second.source_id!r}: "
                    "declared source paths overlap"
                )


def _repository_dirty_categories(repository: Path) -> dict[str, int]:
    status = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignore-submodules=none",
        ],
        check=False,
        capture_output=True,
    )
    if status.returncode != 0:
        return {"unreadable Git status": 1}

    categories: dict[str, int] = {}
    records = status.stdout.split(b"\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        code = record[:2].decode("ascii", errors="replace")
        if code == "??":
            _increment(categories, "untracked")
            continue
        if "U" in code or code in {"AA", "DD"}:
            _increment(categories, "conflicted")
        if code[0] not in {" ", "?", "!"}:
            _increment(categories, "staged")
        if code[1] not in {" ", "?", "!"}:
            _increment(categories, "modified")
        if code[0] in {"R", "C"}:
            index += 1

    submodules = _run_git_text(repository, "submodule", "status", "--recursive")
    if submodules.returncode != 0:
        _increment(categories, "submodule")
    else:
        for line in submodules.stdout.splitlines():
            if line[:1] in {"-", "+", "U"}:
                _increment(categories, "submodule")
    return categories


def _increment(categories: dict[str, int], category: str) -> None:
    categories[category] = categories.get(category, 0) + 1


def _run_git_text(repository: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        text=True,
        capture_output=True,
    )
