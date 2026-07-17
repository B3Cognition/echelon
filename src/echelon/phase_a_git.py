"""Echelon-owned Git bootstrap primitives for Phase A spec authoring."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from echelon.git_helpers import (
    GitHelperError,
    commit_exists,
    current_branch,
    is_worktree_dirty,
    ref_contains_commit,
    run_git,
)


_FILLER_WORDS = frozenset(
    {"i", "we", "want", "need", "to", "a", "an", "the", "please", "now"}
)


class PhaseAGitError(RuntimeError):
    """Raised when Echelon cannot establish a safe Phase A Git context."""


@dataclass(frozen=True)
class PhaseASpecBootstrap:
    """Immutable identity and Git base selected for one Phase A spec run."""

    spec_id: str
    spec_number: str
    slug: str
    feature_branch: str
    spec_dir: str
    published_spec_dir: str
    default_branch: str
    default_commit: str

    def state_updates(self) -> dict[str, str]:
        """Return the state values consumed by the Phase A workflow."""

        return {
            "spec_id": self.spec_id,
            "spec_number": self.spec_number,
            "spec_dir": self.spec_dir,
            "published_spec_dir": self.published_spec_dir,
            "feature_branch": self.feature_branch,
            "phase_a_default_branch": self.default_branch,
            "phase_a_base_commit": self.default_commit,
            "specify_feature_directory": self.spec_dir,
        }


def slugify_spec_description(description: str) -> str:
    """Derive a bounded, deterministic slug from a spec description."""

    tokens = [
        token.lower()
        for token in re.findall(r"[A-Za-z0-9]+", description)
        if token.lower() not in _FILLER_WORDS
    ][:4]
    if not tokens:
        raise PhaseAGitError("spec description must contain a meaningful word")
    if len(tokens) == 1:
        tokens.insert(0, "spec")
    return "-".join(tokens)


def _local_branch_exists(project_root: Path, branch: str) -> bool:
    result = run_git(
        project_root,
        "show-ref",
        "--verify",
        "--quiet",
        f"refs/heads/{branch}",
        check=False,
    )
    return result.returncode == 0


def _auto_detect_phase_a_default_branch(project_root: Path) -> str:
    if _local_branch_exists(project_root, "main"):
        return "main"
    if _local_branch_exists(project_root, "master"):
        return "master"
    origin_head = run_git(
        project_root,
        "symbolic-ref",
        "--quiet",
        "--short",
        "refs/remotes/origin/HEAD",
        check=False,
    )
    branch = origin_head.stdout.strip().removeprefix("origin/")
    if origin_head.returncode != 0 or not branch or not _local_branch_exists(project_root, branch):
        raise PhaseAGitError(
            "cannot resolve a local Phase A default branch; configure one explicitly"
        )
    return branch


def resolve_phase_a_default_branch(
    project_root: Path,
    configured: str = "",
) -> tuple[str, str]:
    """Resolve the local default branch and its exact commit."""

    root = Path(project_root).resolve()
    requested = configured.strip()
    try:
        if requested:
            if not _local_branch_exists(root, requested):
                # HarnessConfig historically supplies "main" when a project
                # has no explicit branch setting. Treat that compatibility
                # default as unconfigured so established master/trunk repos
                # still use the normal local-resolution order.
                if requested == "main":
                    requested = ""
                else:
                    raise PhaseAGitError(
                        f"configured default branch {requested!r} is missing locally"
                    )
            branch = requested or _auto_detect_phase_a_default_branch(root)
        else:
            branch = _auto_detect_phase_a_default_branch(root)

        commit = run_git(root, "rev-parse", f"refs/heads/{branch}^{{commit}}").stdout.strip()
    except GitHelperError as exc:
        raise PhaseAGitError(str(exc)) from exc

    return branch, commit


def _identity_number(name: str) -> int | None:
    match = re.search(r"(?:^|/)(\d{3,})-[^/]+$", name)
    return int(match.group(1)) if match else None


def _directory_identity_numbers(parent: Path) -> set[int]:
    if not parent.is_dir():
        return set()
    return {
        number
        for path in parent.iterdir()
        if path.is_dir() and (number := _identity_number(path.name)) is not None
    }


def _allocated_spec_numbers(project_root: Path) -> set[int]:
    numbers = _directory_identity_numbers(project_root / "specs")
    runs_dir = project_root / "runs"
    if runs_dir.is_dir():
        for run_dir in runs_dir.iterdir():
            if run_dir.is_dir():
                numbers.update(_directory_identity_numbers(run_dir / "specs"))

    try:
        refs = run_git(
            project_root,
            "for-each-ref",
            "--format=%(refname:short)",
            "refs/heads",
            "refs/remotes",
        ).stdout.splitlines()
    except GitHelperError as exc:
        raise PhaseAGitError(str(exc)) from exc
    numbers.update(
        number
        for ref in refs
        if (number := _identity_number(ref.strip())) is not None
    )
    return numbers


def plan_phase_a_spec(
    project_root: Path,
    run_dir: Path,
    description: str,
    configured_default_branch: str = "",
) -> PhaseASpecBootstrap:
    """Plan a collision-safe spec identity without mutating Git or the filesystem."""

    root = Path(project_root).resolve()
    resolved_run_dir = Path(run_dir).resolve()
    try:
        run_relative = resolved_run_dir.relative_to(root)
    except ValueError as exc:
        raise PhaseAGitError("run directory must be inside the project root") from exc

    slug = slugify_spec_description(description)
    default_branch, default_commit = resolve_phase_a_default_branch(
        root,
        configured_default_branch,
    )
    allocated = _allocated_spec_numbers(root)
    spec_number = f"{max(allocated, default=0) + 1:03d}"
    spec_id = f"{spec_number}-{slug}"
    spec_dir = (run_relative / "specs" / spec_id).as_posix()

    return PhaseASpecBootstrap(
        spec_id=spec_id,
        spec_number=spec_number,
        slug=slug,
        feature_branch=spec_id,
        spec_dir=spec_dir,
        published_spec_dir=f"specs/{spec_id}",
        default_branch=default_branch,
        default_commit=default_commit,
    )


def create_phase_a_spec_branch(
    project_root: Path,
    bootstrap: PhaseASpecBootstrap,
) -> PhaseASpecBootstrap:
    """Create and verify a clean sibling spec branch from its recorded base."""

    root = Path(project_root).resolve()
    try:
        observed_branch = current_branch(root)
        if observed_branch != bootstrap.default_branch:
            raise PhaseAGitError(
                "current branch must equal the planned default branch "
                f"{bootstrap.default_branch!r}; found {observed_branch!r}"
            )
        if is_worktree_dirty(root, include_untracked=True):
            raise PhaseAGitError("Phase A branch creation requires a clean worktree")
        if not commit_exists(root, bootstrap.default_commit):
            raise PhaseAGitError(
                f"planned default commit {bootstrap.default_commit!r} no longer exists"
            )

        default_commit = run_git(
            root,
            "rev-parse",
            f"refs/heads/{bootstrap.default_branch}^{{commit}}",
        ).stdout.strip()
        if default_commit != bootstrap.default_commit:
            raise PhaseAGitError(
                f"default branch {bootstrap.default_branch!r} moved after planning"
            )
        if _local_branch_exists(root, bootstrap.feature_branch):
            raise PhaseAGitError(
                f"target branch {bootstrap.feature_branch!r} already exists"
            )

        run_git(
            root,
            "switch",
            "-c",
            bootstrap.feature_branch,
            bootstrap.default_commit,
        )
        created_branch = current_branch(root)
        created_commit = run_git(root, "rev-parse", "HEAD^{commit}").stdout.strip()
        if created_branch != bootstrap.feature_branch:
            raise PhaseAGitError(
                f"created branch verification failed: found {created_branch!r}"
            )
        if created_commit != bootstrap.default_commit:
            raise PhaseAGitError(
                f"created branch has unexpected HEAD {created_commit!r}"
            )
        if not ref_contains_commit(
            root,
            bootstrap.feature_branch,
            bootstrap.default_commit,
        ):
            raise PhaseAGitError("created branch does not contain its planned default commit")
    except GitHelperError as exc:
        raise PhaseAGitError(str(exc)) from exc

    return bootstrap


def create_phase_a_spec_branch_ref(
    project_root: Path,
    bootstrap: PhaseASpecBootstrap,
    *,
    clean_verified: bool = False,
) -> PhaseASpecBootstrap:
    """Create a sibling branch ref without changing the checked-out branch.

    ``clean_verified`` is reserved for a lifecycle-lock holder that has already
    inspected the worktree while its own untracked lock metadata exists.
    """

    root = Path(project_root).resolve()
    try:
        if not clean_verified and is_worktree_dirty(root, include_untracked=True):
            raise PhaseAGitError("Phase A branch creation requires a clean worktree")
        if not commit_exists(root, bootstrap.default_commit):
            raise PhaseAGitError(
                f"planned default commit {bootstrap.default_commit!r} no longer exists"
            )
        default_commit = run_git(
            root,
            "rev-parse",
            f"refs/heads/{bootstrap.default_branch}^{{commit}}",
        ).stdout.strip()
        if default_commit != bootstrap.default_commit:
            raise PhaseAGitError(
                f"default branch {bootstrap.default_branch!r} moved after planning"
            )
        if _local_branch_exists(root, bootstrap.feature_branch):
            raise PhaseAGitError(
                f"target branch {bootstrap.feature_branch!r} already exists"
            )
        run_git(root, "branch", bootstrap.feature_branch, bootstrap.default_commit)
        created_commit = run_git(
            root,
            "rev-parse",
            f"refs/heads/{bootstrap.feature_branch}^{{commit}}",
        ).stdout.strip()
        if created_commit != bootstrap.default_commit:
            raise PhaseAGitError(
                f"created branch has unexpected commit {created_commit!r}"
            )
        if not ref_contains_commit(
            root,
            bootstrap.feature_branch,
            bootstrap.default_commit,
        ):
            raise PhaseAGitError("created branch does not contain its planned default commit")
    except GitHelperError as exc:
        raise PhaseAGitError(str(exc)) from exc
    return bootstrap
