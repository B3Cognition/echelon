"""Resolve the immutable Git source used to generate Echelon's human wiki."""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from echelon.git_helpers import GitHelperError, run_git
from echelon.phase_a_git import PhaseAGitError, resolve_phase_a_default_branch
from harness.config import get_full_resolved_config


class WikiCatalogError(RuntimeError):
    """Raised when a default-branch wiki source cannot be prepared safely."""


@dataclass(frozen=True)
class WikiCatalogSource:
    """One resolved, stable source tree for wiki discovery and hashing."""

    workspace_root: Path
    source_root: Path
    branch: str | None
    revision: str | None
    dirty: bool
    temporary: bool


def _configured_default_branch(project_root: Path) -> str:
    resolved = get_full_resolved_config(project_root)
    configured = resolved.get("target_default_branch", "")
    if not configured and isinstance(resolved.get("harness"), dict):
        configured = resolved["harness"].get("target_default_branch", "")
    return str(configured or "")


def _catalog_dirty(project_root: Path) -> bool:
    result = run_git(
        project_root,
        "status",
        "--porcelain",
        "--",
        "specs",
        "re",
    )
    return bool(result.stdout.strip())


def _remove_temporary_parent(path: Path) -> None:
    shutil.rmtree(path)


@contextmanager
def wiki_catalog_source(project_root: Path) -> Iterator[WikiCatalogSource]:
    """Yield the caller root or a pinned local default-branch worktree."""

    root = project_root.resolve()
    try:
        probe = run_git(root, "rev-parse", "--is-inside-work-tree", check=False)
    except GitHelperError as exc:
        if "git is not available" in str(exc):
            yield WikiCatalogSource(root, root, None, None, False, False)
            return
        raise WikiCatalogError(str(exc)) from exc
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        yield WikiCatalogSource(root, root, None, None, False, False)
        return

    configured = _configured_default_branch(root)
    try:
        branch, revision = resolve_phase_a_default_branch(root, configured)
    except PhaseAGitError as exc:
        if configured.strip():
            raise WikiCatalogError(str(exc)) from exc
        try:
            revision_result = run_git(root, "rev-parse", "HEAD", check=False)
            live_revision = (
                revision_result.stdout.strip()
                if revision_result.returncode == 0
                else None
            )
            dirty = _catalog_dirty(root)
        except GitHelperError as git_exc:
            raise WikiCatalogError(str(git_exc)) from git_exc
        yield WikiCatalogSource(root, root, None, live_revision, dirty, False)
        return
    except (GitHelperError, OSError) as exc:
        raise WikiCatalogError(str(exc)) from exc

    try:
        current = run_git(root, "branch", "--show-current").stdout.strip()
    except GitHelperError as exc:
        raise WikiCatalogError(str(exc)) from exc

    if current == branch:
        try:
            dirty = _catalog_dirty(root)
        except GitHelperError as exc:
            raise WikiCatalogError(str(exc)) from exc
        yield WikiCatalogSource(root, root, branch, revision, dirty, False)
        return

    temporary_parent = Path(tempfile.mkdtemp(prefix="echelon-wiki-catalog-"))
    source_root = temporary_parent / "catalog"
    added = False
    try:
        run_git(
            root,
            "worktree",
            "add",
            "--detach",
            "--quiet",
            str(source_root),
            revision,
        )
        added = True
        local_config = root / ".echelon/local.yml"
        if local_config.is_file():
            target = source_root / ".echelon/local.yml"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local_config, target)
    except (GitHelperError, OSError) as exc:
        if added:
            run_git(
                root,
                "worktree",
                "remove",
                "--force",
                str(source_root),
                check=False,
            )
            run_git(root, "worktree", "prune", check=False)
        try:
            _remove_temporary_parent(temporary_parent)
        except OSError:
            pass
        raise WikiCatalogError(str(exc)) from exc
    try:
        yield WikiCatalogSource(root, source_root, branch, revision, False, True)
    finally:
        cleanup_error: Exception | None = None
        if added:
            try:
                run_git(root, "worktree", "remove", "--force", str(source_root))
                run_git(root, "worktree", "prune")
            except (GitHelperError, OSError) as exc:
                cleanup_error = exc
        if cleanup_error is None:
            try:
                _remove_temporary_parent(temporary_parent)
            except OSError as exc:
                cleanup_error = exc
        if cleanup_error is not None:
            raise WikiCatalogError(
                f"could not remove temporary wiki catalog worktree; retained at "
                f"{temporary_parent}: {cleanup_error}"
            ) from cleanup_error
