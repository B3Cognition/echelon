"""Land — idempotent spec completion: merge PR, delete branch, clean worktrees, mark done."""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Optional

from echelon.ui import banner as _banner

from harness.paths import runs_dir
from harness.spec_frontmatter import find_spec_dir, write_status

logger = logging.getLogger(__name__)


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
) -> bool:
    """Idempotent: merge PR, delete remote branch, clean worktrees, mark spec landed.

    Returns True if spec is now in landed state.
    Returns False only when PR merge is blocked — caller must retry or merge manually.
    """
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

    if pr_url:
        merged = gitops.merge_pr(pr_url)
        if not merged:
            _banner(
                "LAND — ACTION NEEDED",
                [
                    ("spec", spec_id),
                    ("problem", "PR merge blocked by branch protection or conflicts"),
                    ("PR", pr_url),
                    ("next step", f"echelon land {spec_id}"),
                ],
                subtitle="Merge the PR on GitHub, then re-run land.",
            )
            return False
    else:
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
