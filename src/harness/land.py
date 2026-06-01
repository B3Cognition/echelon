"""Land — idempotent spec completion: merge PR, delete branch, clean worktrees, mark done."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Optional

from echelon.ui import banner as _banner

from harness.gitops import _run_git
from harness.paths import runs_dir
from harness.spec_frontmatter import find_spec_dir, write_status

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LandOptions:
    autoresolve: bool = True
    prepare_only: bool = False
    continue_existing: bool = False
    strategy: str = "merge"


@dataclass(frozen=True)
class LandPrepareResult:
    status: str
    branch: str
    prepared_commit: str | None = None
    pushed: bool = False
    conflicted_files: list[str] = field(default_factory=list)
    autoresolved_files: list[str] = field(default_factory=list)
    message: str = ""


def prepare_feature_branch(
    *,
    spec_id: str,
    feature_branch: str,
    project_dir: Path,
    gitops: Any,
    options: LandOptions,
) -> LandPrepareResult:
    """Prepare a feature branch by bringing it up to date with the default branch."""
    if options.strategy != "merge":
        return LandPrepareResult(
            status="blocked",
            branch=feature_branch,
            message=f"unsupported land strategy: {options.strategy}",
        )

    dirty = _run_git(
        ["status", "--porcelain", "--untracked-files=no"],
        cwd=str(project_dir),
        check=False,
    )
    if dirty.stdout.strip():
        return LandPrepareResult(
            status="blocked",
            branch=feature_branch,
            message="working tree has tracked changes",
        )

    default_branch = gitops.get_default_branch()
    _run_git(["checkout", feature_branch], cwd=str(project_dir))

    result = _run_git(
        [
            "merge",
            "--no-ff",
            default_branch,
            "-m",
            f"Merge {default_branch} into {feature_branch}",
        ],
        cwd=str(project_dir),
        check=False,
    )
    if result.returncode == 0:
        commit = _run_git(["rev-parse", "HEAD"], cwd=str(project_dir)).stdout.strip()
        gitops.push_prepared_branch(
            str(project_dir), feature_branch, force_with_lease=False
        )
        return LandPrepareResult(
            status="prepared",
            branch=feature_branch,
            prepared_commit=commit,
            pushed=True,
        )

    conflicted = _list_unmerged_files(project_dir)
    autoresolved: list[str] = []
    if options.autoresolve and conflicted == [".gitignore"] and _autoresolve_gitignore(project_dir):
        autoresolved.append(".gitignore")
        conflicted = _list_unmerged_files(project_dir)
        if not conflicted:
            _run_git(["commit", "--no-edit"], cwd=str(project_dir))
            commit = _run_git(["rev-parse", "HEAD"], cwd=str(project_dir)).stdout.strip()
            gitops.push_prepared_branch(
                str(project_dir), feature_branch, force_with_lease=False
            )
            return LandPrepareResult(
                status="prepared",
                branch=feature_branch,
                prepared_commit=commit,
                pushed=True,
                autoresolved_files=autoresolved,
            )

    return LandPrepareResult(
        status="blocked",
        branch=feature_branch,
        conflicted_files=conflicted,
        autoresolved_files=autoresolved,
        message="merge conflicts remain",
    )


def _list_unmerged_files(project_dir: Path) -> list[str]:
    result = _run_git(
        ["diff", "--name-only", "--diff-filter=U"],
        cwd=str(project_dir),
        check=False,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _autoresolve_gitignore(project_dir: Path) -> bool:
    base = _run_git(["show", ":1:.gitignore"], cwd=str(project_dir), check=False)
    if base.returncode == 0:
        return False

    ours = _run_git(["show", ":2:.gitignore"], cwd=str(project_dir), check=False)
    theirs = _run_git(["show", ":3:.gitignore"], cwd=str(project_dir), check=False)
    if ours.returncode != 0 or theirs.returncode != 0:
        return False

    lines: list[str] = []
    seen: set[str] = set()
    for content in (ours.stdout, theirs.stdout):
        for raw_line in content.splitlines():
            line = raw_line.rstrip()
            key = line.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            lines.append(line)

    (project_dir / ".gitignore").write_text("\n".join(lines) + "\n", encoding="utf-8")
    add = _run_git(["add", ".gitignore"], cwd=str(project_dir), check=False)
    return add.returncode == 0


def find_pr_url(spec_id: str, state_dir: Path) -> Optional[str]:
    """Return the first PR URL found in any strategy state file for spec_id.

    When state_dir is given, scans it directly.
    When state_dir is the runs/ root (no spec_id subdir), delegates to
    _find_pr_url_all_builds which scans all build dirs.
    """
    # Direct scan: state files are at state_dir/*.json (no spec_id subdir)
    if state_dir.exists():
        for state_file in sorted(state_dir.glob("*.json")):
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                if data.get("pr_url") and data.get("spec_id") == spec_id:
                    return data["pr_url"]
            except (json.JSONDecodeError, OSError):
                continue
    return None


def _find_pr_url_all_builds(spec_id: str, project_dir: Path) -> Optional[str]:
    """Scan all runs/build-*/state/ directories for a PR URL matching spec_id."""
    rd = runs_dir(project_dir)
    if not rd.exists():
        return None
    for build in sorted(rd.glob("build-*/"), reverse=True):
        state_dir = build / "state"
        url = find_pr_url(spec_id, state_dir)
        if url:
            return url
    return None


def land(
    spec_id: str,
    *,
    project_dir: Path,
    gitops: Any,
    state_dir: Optional[Path] = None,
    options: Optional[LandOptions] = None,
) -> bool:
    """Idempotent: merge PR, delete remote branch, clean worktrees, mark spec landed.

    Returns True if spec is now in landed state.
    Returns False only when PR merge is blocked — caller must retry or merge manually.
    """
    options = options or LandOptions()
    feature_branch = gitops.find_feature_branch(spec_id)
    if feature_branch is None:
        logger.info("land: %s — feature branch not found, already landed", spec_id)
        _cleanup_worktrees(spec_id, project_dir, gitops)
        _delete_harness_branches(spec_id, project_dir)
        return True

    if state_dir is not None:
        pr_url = find_pr_url(spec_id, state_dir)
    else:
        pr_url = _find_pr_url_all_builds(spec_id, project_dir)

    if options.prepare_only:
        prepare_result = _prepare_for_land(
            spec_id=spec_id,
            feature_branch=feature_branch,
            project_dir=project_dir,
            gitops=gitops,
            options=options,
        )
        if prepare_result is None:
            return False
        _banner(
            "LAND — PREPARED",
            [
                ("spec", spec_id),
                ("branch", feature_branch),
                ("commit", prepare_result.prepared_commit or "(unchanged)"),
            ],
            subtitle="Feature branch is prepared; landing was not attempted.",
        )
        return True

    if pr_url:
        merged = gitops.merge_pr(pr_url)
        if merged:
            return _finish_landing(spec_id, feature_branch, project_dir, gitops)
        prepare_result = _prepare_for_land(
            spec_id=spec_id,
            feature_branch=feature_branch,
            project_dir=project_dir,
            gitops=gitops,
            options=options,
        )
        if prepare_result is None:
            return False
        _banner(
            "LAND — ACTION NEEDED",
            [
                ("spec", spec_id),
                ("problem", "PR merge blocked by branch protection, checks, or conflicts"),
                ("PR", pr_url),
                ("next step", f"re-run after checks/branch protection clear: echelon land {spec_id}"),
            ],
            subtitle="Feature branch was prepared, but Echelon will not bypass the PR.",
        )
        return False

    prepare_result = _prepare_for_land(
        spec_id=spec_id,
        feature_branch=feature_branch,
        project_dir=project_dir,
        gitops=gitops,
        options=options,
    )
    if prepare_result is None:
        return False

    # No PR URL — gh/glab not configured. Merge directly into the default branch.
    merged = gitops.merge_branch_into_default(feature_branch, str(project_dir))
    if not merged:
        _banner(
            "LAND — MERGE FAILED",
            [
                ("spec", spec_id),
                ("branch", feature_branch),
                ("problem", "direct merge into default branch failed (conflicts?)"),
                ("next step", f"git merge --no-ff {feature_branch}  # resolve conflicts, then re-run"),
            ],
            subtitle="Resolve conflicts manually, then re-run: echelon land " + spec_id,
        )
        return False

    return _finish_landing(spec_id, feature_branch, project_dir, gitops)


def _prepare_for_land(
    *,
    spec_id: str,
    feature_branch: str,
    project_dir: Path,
    gitops: Any,
    options: LandOptions,
) -> LandPrepareResult | None:
    prepare_result = prepare_feature_branch(
        spec_id=spec_id,
        feature_branch=feature_branch,
        project_dir=project_dir,
        gitops=gitops,
        options=options,
    )
    if prepare_result.status == "blocked":
        _banner(
            "LAND — FEATURE BRANCH NEEDS CONFLICT RESOLUTION",
            [
                ("spec", spec_id),
                ("branch", feature_branch),
                ("conflicts", "\n".join(prepare_result.conflicted_files) or "(none)"),
                ("next step", f"resolve conflicts, then run: echelon land {spec_id} --continue"),
            ],
            subtitle="Echelon stopped on semantic conflicts.",
        )
        return None
    return prepare_result


def _finish_landing(spec_id: str, feature_branch: str, project_dir: Path, gitops: Any) -> bool:
    """Clean up after a feature branch has merged."""

    if not gitops.delete_remote_branch(feature_branch, project_dir=str(project_dir)):
        _banner(
            "LAND — BRANCH CLEANUP NOTE",
            [
                ("branch", feature_branch),
                ("problem", "could not delete from origin — not configured or wrong remote"),
                ("safe to ignore?", "yes, if you pushed to a different remote (e.g. upstream)"),
                ("manual cleanup", f"git push origin --delete {feature_branch}"),
            ],
        )
    _delete_local_branch(feature_branch, str(project_dir))
    _cleanup_worktrees(spec_id, project_dir, gitops)
    _delete_harness_branches(spec_id, project_dir)
    gitops.ensure_on_default_branch(str(project_dir))

    spec_dir = find_spec_dir(spec_id, project_dir)
    if spec_dir:
        write_status(spec_dir, "landed")

    logger.info("land: %s — landed successfully", spec_id)
    return True


def _cleanup_worktrees(spec_id: str, project_dir: Path, gitops: Any) -> None:
    """Remove all worktrees for this spec across all build dirs."""
    rd = runs_dir(project_dir)
    if not rd.exists():
        return
    for build in sorted(rd.glob("build-*/")):
        worktree_base = build / "worktrees"
        if not worktree_base.exists():
            continue
        for strategy_dir in sorted(worktree_base.iterdir()):
            if not strategy_dir.is_dir():
                continue
            for iter_dir in sorted(strategy_dir.iterdir()):
                if iter_dir.is_dir():
                    try:
                        gitops.destroy_worktree(iter_dir, keep_branch=True)
                        logger.info("land: removed worktree %s", iter_dir)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("land: could not remove worktree %s: %s", iter_dir, e)


def _delete_local_branch(branch: str, project_dir: str) -> None:
    """Delete the local feature branch after a successful merge.

    Uses -d (safe delete) so git refuses if the branch is somehow not merged —
    this is a second safety net on top of the merge-success gate in land().
    For PR-merged branches where local main hasn't been pulled yet, -d will
    refuse; we log a notice and leave the branch rather than force-deleting.
    """
    try:
        subprocess.run(
            ["git", "branch", "-d", branch],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
            cwd=project_dir,
        )
        logger.info("land: deleted local branch %s", branch)
    except subprocess.CalledProcessError:
        # Most likely: PR was merged remotely but local main hasn't been pulled.
        # Branch is merged — just not visible to local git yet. Leave it.
        logger.info(
            "land: local branch %s not deleted (not yet in local history — run 'git pull' to clean up)",
            branch,
        )


def _delete_harness_branches(spec_id: str, project_dir: Path) -> None:
    """Delete local harness/{spec_id}-* branches left over from harness runs."""
    try:
        result = subprocess.run(
            ["git", "branch", "--list", f"harness/{spec_id}/*"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(project_dir),
        )
        branches = [b.strip() for b in result.stdout.splitlines() if b.strip()]
        for branch in branches:
            try:
                subprocess.run(
                    ["git", "branch", "-D", branch],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                    cwd=str(project_dir),
                )
                logger.info("land: deleted legacy branch %s", branch)
            except subprocess.CalledProcessError as e:
                logger.warning("land: could not delete legacy branch %s: %s", branch, e)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("land: could not list harness branches for %s: %s", spec_id, e)
