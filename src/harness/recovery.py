"""Recovery helpers for blocked harness runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Any, Optional

from harness.errors import GitOpsError
from harness.gitops import _clean_branch_listing, _run_git
from harness.build_result import BUILD_STATUS_FILENAME


RECOVERABLE_REASONS = {"build_incomplete", "publish_failed", "blocker_escalation"}


class HarnessRecoveryError(RuntimeError):
    """Raised when a blocked harness run cannot be recovered automatically."""


@dataclass(frozen=True)
class RecoveryResult:
    """Result of applying a recovered harness commit to the real project repo."""

    source: str
    commit: str
    target_branch: str
    applied: bool
    backed_up_untracked: tuple[str, ...] = ()
    backup_dir: str = ""


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

    target_repo_raw = state.get("target_repo_path") or state.get("target_path")
    target_branch_raw = state.get("target_branch")
    target_commit_raw = state.get("target_commit")
    if target_repo_raw and target_branch_raw and target_commit_raw:
        target_repo = Path(str(target_repo_raw))
        if target_repo.exists():
            inside = _run_git(
                ["rev-parse", "--is-inside-work-tree"],
                cwd=str(target_repo),
                check=False,
            )
            current = _run_git(
                ["rev-parse", "HEAD"],
                cwd=str(target_repo),
                check=False,
            )
            if inside.returncode == 0 and current.returncode == 0:
                return RecoveryResult(
                    source="target_repo",
                    commit=str(target_commit_raw),
                    target_branch=str(target_branch_raw),
                    applied=False,
                )

    target_branch = _resolve_target_branch(project_dir, spec_id, state, gitops)

    source = _find_preserved_worktree_source(
        spec_id=spec_id,
        strategy_id=strategy_id,
        gitops=gitops,
        build_id=build_id,
        checkpoint_commits=state.get("checkpoint_commits"),
        salvage_commit=str(state.get("salvage_commit") or ""),
        preferred_commit=_documentation_evidence_head(state),
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
        commit = _find_delivery_branch_head(
            repo=mirror_path,
            ref=target_branch,
        )
    if commit is None:
        target_head = _find_delivery_branch_head(
            repo=project_dir,
            ref=target_branch,
        )
        if target_head is not None:
            return RecoveryResult(
                source="target_branch",
                commit=target_head,
                target_branch=target_branch,
                applied=False,
            )
        raise HarnessRecoveryError(
            f"No committed strategy result found on branch {target_branch!r}"
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
    checkpoint_commits: Any = None,
    salvage_commit: str = "",
    preferred_commit: str = "",
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

    if preferred_commit:
        exists = _run_git(
            ["cat-file", "-e", f"{preferred_commit}^{{commit}}"],
            cwd=str(worktree_path),
            check=False,
        )
        if exists.returncode == 0:
            return worktree_path, preferred_commit

    checkpoint_commit = _latest_existing_checkpoint_commit(
        worktree_path,
        checkpoint_commits,
    )
    if checkpoint_commit:
        return worktree_path, checkpoint_commit

    if salvage_commit:
        exists = _run_git(
            ["cat-file", "-e", f"{salvage_commit}^{{commit}}"],
            cwd=str(worktree_path),
            check=False,
        )
        if exists.returncode == 0:
            return worktree_path, salvage_commit

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
    if commit is not None:
        return worktree_path, commit

    head = _run_git(
        ["rev-parse", "HEAD"],
        cwd=str(worktree_path),
        check=False,
    )
    if head.returncode == 0 and head.stdout.strip():
        return worktree_path, head.stdout.strip()
    return None


def _documentation_evidence_head(state: dict[str, Any]) -> str:
    evidence = state.get("documentation_evidence")
    if not isinstance(evidence, dict):
        return ""
    return str(evidence.get("head") or "").strip()


def _latest_existing_checkpoint_commit(repo: Path, checkpoint_commits: Any) -> Optional[str]:
    if not isinstance(checkpoint_commits, list):
        return None
    for entry in reversed(checkpoint_commits):
        if not isinstance(entry, dict):
            continue
        commit = str(entry.get("commit") or "").strip()
        if not commit:
            continue
        exists = _run_git(
            ["cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=str(repo),
            check=False,
        )
        if exists.returncode == 0:
            return commit
    return None


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
    if state_branch and _branch_exists(mirror_path, state_branch):
        return state_branch
    if state_branch and _branch_exists(project_dir, state_branch):
        return state_branch

    branch = _find_branch_without_fetch(mirror_path, spec_id)
    if branch:
        return branch

    branch = _find_branch_without_fetch(project_dir, spec_id)
    if branch:
        return branch

    raise HarnessRecoveryError(f"No feature branch found for spec {spec_id!r}")


def _branch_exists(repo: Path, branch: str) -> bool:
    if not repo.exists():
        return False
    local = _run_git(
        ["rev-parse", "--verify", "--quiet", branch],
        cwd=str(repo),
        check=False,
    )
    if local.returncode == 0:
        return True
    remote = _run_git(
        ["rev-parse", "--verify", "--quiet", f"origin/{branch}"],
        cwd=str(repo),
        check=False,
    )
    return remote.returncode == 0


def _find_branch_without_fetch(repo: Path, spec_id: str) -> Optional[str]:
    if not repo.exists():
        return None
    for pattern in (spec_id, f"{spec_id}-*", f"harness/{spec_id}/*"):
        result = _run_git(["branch", "--list", pattern], cwd=str(repo), check=False)
        branches = [_clean_branch_listing(b) for b in result.stdout.splitlines() if b.strip()]
        if branches:
            return branches[0]
        remote_result = _run_git(
            ["branch", "--remotes", "--list", f"origin/{pattern}"],
            cwd=str(repo),
            check=False,
        )
        remote_branches = [
            _clean_branch_listing(b)
            for b in remote_result.stdout.splitlines()
            if b.strip()
        ]
        if remote_branches:
            return remote_branches[0].removeprefix("origin/")
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


def _find_delivery_branch_head(*, repo: Path, ref: str) -> Optional[str]:
    head = _run_git(
        ["rev-parse", "--verify", "--quiet", ref],
        cwd=str(repo),
        check=False,
    )
    if head.returncode != 0:
        return None
    commit = head.stdout.strip()
    if not commit:
        return None
    if not _commit_changes_delivery_files(repo, commit):
        return None
    return commit


def _commit_changes_delivery_files(repo: Path, commit: str) -> bool:
    result = _run_git(
        ["diff-tree", "--no-commit-id", "--name-only", "-r", commit],
        cwd=str(repo),
        check=False,
    )
    if result.returncode != 0:
        return False
    for raw_path in result.stdout.splitlines():
        path = raw_path.strip()
        if path and not _is_recovery_metadata_path(path):
            return True
    return False


def _is_recovery_metadata_path(path: str) -> bool:
    return (
        path == BUILD_STATUS_FILENAME
        or path.startswith(".echelon/")
        or path.startswith("runs/")
        or path.startswith("specs/")
    )


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
    if _ref_contains_commit(project_dir, target_branch, commit):
        return RecoveryResult(
            source=source_label,
            commit=commit,
            target_branch=target_branch,
            applied=False,
        )

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

    backed_up_untracked, backup_dir = _prepare_untracked_cherry_pick_collisions(
        project_dir=project_dir,
        source_repo=source_repo,
        commit=commit,
    )
    try:
        _run_git(["cherry-pick", commit], cwd=str(project_dir))
    except GitOpsError as e:
        if "previous cherry-pick is now empty" in str(e):
            _run_git(["cherry-pick", "--abort"], cwd=str(project_dir), check=False)
            return RecoveryResult(
                source=source_label,
                commit=commit,
                target_branch=target_branch,
                applied=False,
                backed_up_untracked=backed_up_untracked,
                backup_dir=backup_dir,
            )
        if _resolve_only_build_status_marker_conflict(project_dir):
            return RecoveryResult(
                source=source_label,
                commit=commit,
                target_branch=target_branch,
                applied=True,
                backed_up_untracked=backed_up_untracked,
                backup_dir=backup_dir,
            )
        raise HarnessRecoveryError(f"Could not cherry-pick recovered commit {commit}: {e}") from e
    return RecoveryResult(
        source=source_label,
        commit=commit,
        target_branch=target_branch,
        applied=True,
        backed_up_untracked=backed_up_untracked,
        backup_dir=backup_dir,
    )


def _ref_contains_commit(repo: Path, ref: str, commit: str) -> bool:
    """Return whether ``ref`` already contains ``commit`` in ``repo``.

    This intentionally runs before dirty-worktree validation. If recovery has
    nothing to apply, a tracked edit in the user's current checkout should not
    block resuming from an already-checkpointed feature branch.
    """
    exists = _run_git(
        ["cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=str(repo),
        check=False,
    )
    if exists.returncode != 0:
        return False

    ref_exists = _run_git(
        ["rev-parse", "--verify", "--quiet", ref],
        cwd=str(repo),
        check=False,
    )
    if ref_exists.returncode != 0:
        return False

    contains = _run_git(
        ["merge-base", "--is-ancestor", commit, ref],
        cwd=str(repo),
        check=False,
    )
    return contains.returncode == 0


def _prepare_untracked_cherry_pick_collisions(
    *,
    project_dir: Path,
    source_repo: Path,
    commit: str,
) -> tuple[tuple[str, ...], str]:
    """Clear untracked files that would block cherry-pick of ``commit``.

    Git refuses to cherry-pick when an untracked target path would be
    overwritten. For harness recovery this commonly happens when Phase A/spec
    artifacts exist in the project checkout but the salvage commit also adds
    them. Identical duplicates are safe to remove because cherry-pick restores
    the same bytes as tracked files. Differing duplicates are copied to a
    recovery backup before removal so the salvage commit can still be applied
    without data loss.
    """
    untracked = _run_git(
        ["ls-files", "--others", "--exclude-standard"],
        cwd=str(project_dir),
        check=False,
    )
    untracked_paths = {
        line.strip()
        for line in untracked.stdout.splitlines()
        if line.strip()
    }
    if not untracked_paths:
        return (), ""

    commit_files = _run_git(
        ["diff-tree", "-r", "--no-commit-id", "--name-only", commit],
        cwd=str(source_repo),
        check=False,
    )
    commit_paths = {
        line.strip()
        for line in commit_files.stdout.splitlines()
        if line.strip()
    }
    collisions = sorted(untracked_paths & commit_paths)
    if not collisions:
        return (), ""

    backup_dir = project_dir / ".echelon" / "recovery-backups" / commit[:12]
    backed_up: list[str] = []
    for relpath in collisions:
        target = project_dir / relpath
        if not target.is_file() and not target.is_symlink():
            raise HarnessRecoveryError(
                f"Untracked path would be overwritten by recovered commit and is not a file: {relpath}"
            )

        blob = _read_commit_blob(source_repo, commit, relpath)
        current = target.read_bytes()
        if blob != current:
            backup = backup_dir / relpath
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(current)
            backed_up.append(relpath)
        target.unlink()

    return tuple(backed_up), str(backup_dir) if backed_up else ""


def _read_commit_blob(repo: Path, commit: str, relpath: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relpath}"],
        cwd=repo,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise HarnessRecoveryError(
            f"Could not read {relpath!r} from recovered commit {commit}"
        )
    return result.stdout


def _resolve_only_build_status_marker_conflict(project_dir: Path) -> bool:
    unmerged = _run_git(["diff", "--name-only", "--diff-filter=U"], cwd=str(project_dir), check=False)
    paths = [line.strip() for line in unmerged.stdout.splitlines() if line.strip()]
    if paths != [BUILD_STATUS_FILENAME]:
        return False

    _run_git(["rm", BUILD_STATUS_FILENAME], cwd=str(project_dir), check=False)
    continued = _run_git(
        ["-c", "core.editor=true", "cherry-pick", "--continue"],
        cwd=str(project_dir),
        check=False,
    )
    if continued.returncode == 0:
        return True

    if "previous cherry-pick is now empty" in (continued.stderr or ""):
        _run_git(["cherry-pick", "--abort"], cwd=str(project_dir), check=False)
        return True
    return False


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
