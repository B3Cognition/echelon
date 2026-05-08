"""Land — idempotent spec completion: merge PR, delete branch, clean worktrees, mark done."""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Optional

from harness.paths import harness_dir
from harness.spec_frontmatter import find_spec_dir, write_status

logger = logging.getLogger(__name__)


def find_pr_url(spec_id: str, state_dir: Path) -> Optional[str]:
    """Return the first PR URL found in any strategy state file for spec_id."""
    spec_state_dir = state_dir / spec_id
    if not spec_state_dir.exists():
        return None
    for state_file in sorted(spec_state_dir.glob("*.json")):
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            if data.get("pr_url"):
                return data["pr_url"]
        except (json.JSONDecodeError, OSError):
            continue
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
    if state_dir is None:
        state_dir = harness_dir(project_dir) / "state"

    feature_branch = gitops.find_feature_branch(spec_id)
    if feature_branch is None:
        logger.info("land: %s — feature branch not found, already landed", spec_id)
        _cleanup_worktrees(spec_id, project_dir, gitops)
        _delete_harness_branches(spec_id, project_dir)
        return True

    pr_url = find_pr_url(spec_id, state_dir)
    if pr_url:
        merged = gitops.merge_pr(pr_url)
        if not merged:
            logger.warning(
                "land: %s — PR merge blocked; branch protection requires manual merge", spec_id
            )
            return False
    else:
        logger.warning("land: %s — no PR URL in state, skipping merge step", spec_id)

    if not gitops.delete_remote_branch(feature_branch, project_dir=str(project_dir)):
        logger.warning("land: remote branch %s could not be deleted; continuing", feature_branch)
    _cleanup_worktrees(spec_id, project_dir, gitops)
    _delete_harness_branches(spec_id, project_dir)
    gitops.ensure_on_default_branch(str(project_dir))

    spec_dir = find_spec_dir(spec_id, project_dir)
    if spec_dir:
        write_status(spec_dir, "landed")

    logger.info("land: %s — landed successfully", spec_id)
    return True


def _cleanup_worktrees(spec_id: str, project_dir: Path, gitops: Any) -> None:
    worktree_base = harness_dir(project_dir) / "worktrees" / spec_id
    if not worktree_base.exists():
        return
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
            ["git", "branch", "--list", f"harness/{spec_id}-*"],
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
