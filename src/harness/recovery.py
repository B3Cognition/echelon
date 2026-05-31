"""Recovery helpers for blocked harness runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from harness.gitops import _run_git


RECOVERABLE_REASONS = {"build_incomplete", "publish_failed"}


class HarnessRecoveryError(RuntimeError):
    """Raised when a blocked harness run cannot be recovered automatically."""


@dataclass(frozen=True)
class RecoveryResult:
    """Result of applying a recovered harness commit to the real project repo."""

    source: str
    commit: str
    target_branch: str
    applied: bool


def recover_blocked_run(
    *,
    project_dir: Path,
    spec_id: str,
    strategy_id: str,
    state: dict[str, Any],
    gitops: Any,
    build_id: str = "",
) -> RecoveryResult:
    """Recover the last committed strategy result for a blocked harness run.

    Recovery is intentionally conservative. It only applies an existing commit:
    first from a preserved worktree, then from ``runs/mirror.git``. Dirty
    worktrees with uncommitted edits are left for manual handling.
    """
    reason = state.get("termination_reason")
    if reason not in RECOVERABLE_REASONS:
        raise HarnessRecoveryError(f"Cannot recover blocked reason: {reason!r}")

    project_dir = project_dir.resolve()
    target_branch = _resolve_target_branch(project_dir, spec_id, state, gitops)

    source = _find_preserved_worktree_source(
        spec_id=spec_id,
        strategy_id=strategy_id,
        gitops=gitops,
        build_id=build_id,
    )
    if source is not None:
        source_path, commit = source
        return _apply_commit(
            project_dir=project_dir,
            source_repo=source_path,
            source_label="worktree",
            commit=commit,
            target_branch=target_branch,
        )

    mirror_path = Path(getattr(gitops, "mirror_path", project_dir / "runs" / "mirror.git"))
    if not mirror_path.exists():
        raise HarnessRecoveryError(f"Mirror not found: {mirror_path}")

    commit = _find_strategy_commit(
        repo=mirror_path,
        ref=target_branch,
        spec_id=spec_id,
        strategy_id=strategy_id,
    )
    if commit is None:
        raise HarnessRecoveryError(
            f"No committed strategy result found on mirror branch {target_branch!r}"
        )

    return _apply_commit(
        project_dir=project_dir,
        source_repo=mirror_path,
        source_label="mirror",
        commit=commit,
        target_branch=target_branch,
    )


def _find_preserved_worktree_source(
    *,
    spec_id: str,
    strategy_id: str,
    gitops: Any,
    build_id: str,
) -> Optional[tuple[Path, str]]:
    try:
        worktree = gitops.get_latest_worktree(spec_id, strategy_id, build_id=build_id)
    except Exception:
        worktree = None
    if not worktree:
        return None

    worktree_path = Path(worktree)
    if not worktree_path.exists():
        return None

    inside = _run_git(
        ["rev-parse", "--is-inside-work-tree"],
        cwd=str(worktree_path),
        check=False,
    )
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return None

    dirty = _run_git(
        ["status", "--porcelain", "--untracked-files=no"],
        cwd=str(worktree_path),
        check=False,
    )
    if dirty.stdout.strip():
        raise HarnessRecoveryError(
            f"Preserved worktree has uncommitted tracked changes: {worktree_path}"
        )

    commit = _find_strategy_commit(
        repo=worktree_path,
        ref="HEAD",
        spec_id=spec_id,
        strategy_id=strategy_id,
    )
    if commit is None:
        return None
    return worktree_path, commit


def _resolve_target_branch(
    project_dir: Path,
    spec_id: str,
    state: dict[str, Any],
    gitops: Any,
) -> str:
    state_branch = str(state.get("branch") or "").strip()
    if state_branch and not state_branch.startswith("harness/"):
        return state_branch

    mirror_path = Path(getattr(gitops, "mirror_path", project_dir / "runs" / "mirror.git"))
    branch = _find_branch_without_fetch(mirror_path, spec_id)
    if branch:
        return branch

    branch = _find_branch_without_fetch(project_dir, spec_id)
    if branch:
        return branch

    raise HarnessRecoveryError(f"No feature branch found for spec {spec_id!r}")


def _find_branch_without_fetch(repo: Path, spec_id: str) -> Optional[str]:
    if not repo.exists():
        return None
    for pattern in (spec_id, f"{spec_id}-*"):
        result = _run_git(["branch", "--list", pattern], cwd=str(repo), check=False)
        branches = [b.strip().lstrip("* ") for b in result.stdout.splitlines() if b.strip()]
        if branches:
            return branches[0]
    return None


def _find_strategy_commit(
    *,
    repo: Path,
    ref: str,
    spec_id: str,
    strategy_id: str,
) -> Optional[str]:
    result = _run_git(
        ["log", "--format=%H%x00%s", "-30", ref],
        cwd=str(repo),
        check=False,
    )
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        commit, _, subject = line.partition("\x00")
        if _looks_like_strategy_commit(subject, spec_id, strategy_id):
            return commit
    return None


def _looks_like_strategy_commit(subject: str, spec_id: str, strategy_id: str) -> bool:
    lowered = subject.lower()
    if "iter-" not in lowered:
        return False
    if "harness:" in lowered:
        return True
    if strategy_id and strategy_id.lower() in lowered:
        return True
    if spec_id and spec_id.lower() in lowered:
        return True
    if "codegen" in lowered:
        return True
    return False


def _apply_commit(
    *,
    project_dir: Path,
    source_repo: Path,
    source_label: str,
    commit: str,
    target_branch: str,
) -> RecoveryResult:
    dirty = _run_git(
        ["status", "--porcelain", "--untracked-files=no"],
        cwd=str(project_dir),
        check=False,
    )
    if dirty.stdout.strip():
        raise HarnessRecoveryError(
            f"Project has tracked changes; commit/stash them before recovery: {project_dir}"
        )

    _run_git(["fetch", str(source_repo), commit], cwd=str(project_dir))
    _checkout_target_branch(project_dir, target_branch)

    already_applied = _run_git(
        ["merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=str(project_dir),
        check=False,
    )
    if already_applied.returncode == 0:
        return RecoveryResult(
            source=source_label,
            commit=commit,
            target_branch=target_branch,
            applied=False,
        )

    _run_git(["cherry-pick", commit], cwd=str(project_dir))
    return RecoveryResult(
        source=source_label,
        commit=commit,
        target_branch=target_branch,
        applied=True,
    )


def _checkout_target_branch(project_dir: Path, target_branch: str) -> None:
    local = _run_git(
        ["show-ref", "--verify", f"refs/heads/{target_branch}"],
        cwd=str(project_dir),
        check=False,
    )
    if local.returncode == 0:
        _run_git(["checkout", target_branch], cwd=str(project_dir))
        return

    remote = _run_git(
        ["show-ref", "--verify", f"refs/remotes/origin/{target_branch}"],
        cwd=str(project_dir),
        check=False,
    )
    if remote.returncode == 0:
        _run_git(
            ["checkout", "-B", target_branch, f"origin/{target_branch}"],
            cwd=str(project_dir),
        )
        return

    _run_git(["checkout", "-B", target_branch], cwd=str(project_dir))
