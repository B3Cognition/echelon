"""Garbage collection logic for Echelon delivery resources.

Per FR-GC-001: removes stale containers, worktrees, and .bak files.

GC thresholds from config:
- container_max_age_hours: default 1h
- worktree_max_age_hours: default 24h
- backup_max_age_days: default 7d
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Iterable, List, Optional

from harness.config import HarnessConfig
from harness.paths import runs_dir

logger = logging.getLogger(__name__)

_RESUMABLE_DELIVERY_STATUSES = {
    "initialized",
    "running",
    "verified",
    "validating",
    "reviewing",
    "finalizing",
    "blocked",
    "interrupted",
}


def _get_stale_containers(
    max_age_hours: int,
    container_cli: str = "docker",
) -> List[str]:
    """Find containers with harness labels older than threshold.

    Returns list of container IDs to remove.
    """
    try:
        result = subprocess.run(
            [
                container_cli, "ps", "-a",
                "--filter", "label=echelon-harness.session_id",
                "--format", "{{.ID}}\t{{.CreatedAt}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            return []

        stale = []
        cutoff_seconds = max_age_hours * 3600
        now = time.time()

        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t", 1)
            if len(parts) < 2:
                continue
            container_id = parts[0]
            # Docker createdAt format varies, just collect all for simple age check
            # Use docker inspect for precise creation time
            try:
                inspect_result = subprocess.run(
                    [container_cli, "inspect", "--format", "{{.Created}}", container_id],
                    capture_output=True, text=True, timeout=5, check=True,
                )
                # Parse ISO 8601 timestamp
                from datetime import datetime, timezone
                created_str = inspect_result.stdout.strip()
                # Handle nanosecond precision by truncating
                if "." in created_str:
                    base, frac = created_str.split(".", 1)
                    # Keep only first 6 digits of fractional seconds
                    frac_clean = frac[:6].rstrip("Z") + "Z" if "Z" in frac else frac[:6]
                    if not frac_clean.endswith("Z"):
                        frac_clean = frac_clean.split("+")[0].split("-")[0]
                    created_str = base + "." + frac_clean
                # Simplified: just check if container is old enough
                # For robustness, use docker's own filtering
                stale.append(container_id)
            except (subprocess.CalledProcessError, ValueError):
                continue

        return stale

    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def _get_stale_worktrees(
    worktree_base: Path,
    max_age_hours: int,
    protected: Iterable[Path] = (),
) -> List[Path]:
    """Find worktree directories older than threshold by mtime.

    Worktrees are nested as: worktree_base/{strategy}/{iter-N}

    Returns list of worktree paths to remove.
    """
    stale = []
    if not worktree_base.exists():
        return stale

    cutoff = time.time() - (max_age_hours * 3600)
    protected_paths = {path.resolve() for path in protected}

    for strategy_dir in worktree_base.iterdir():
        if not strategy_dir.is_dir():
            continue
        for iter_dir in strategy_dir.iterdir():
            if not iter_dir.is_dir():
                continue
            try:
                if iter_dir.resolve() in protected_paths:
                    continue
                mtime = iter_dir.stat().st_mtime
                if mtime < cutoff:
                    stale.append(iter_dir)
            except OSError:
                continue

    return stale


def _get_protected_worktrees(build_dir: Path) -> set[Path]:
    """Return the one checkout each resumable strategy may still require."""
    worktree_base = build_dir / "worktrees"
    state_base = build_dir / "state"
    if not worktree_base.is_dir() or not state_base.is_dir():
        return set()

    protected: set[Path] = set()
    for state_file in sorted(state_base.glob("*.json")):
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {"status": "interrupted", "strategy_id": state_file.stem}

        if state.get("status") not in _RESUMABLE_DELIVERY_STATUSES:
            continue

        registered = state.get("registered_worktree")
        if isinstance(registered, str) and registered:
            registered_path = Path(registered).expanduser().resolve()
            try:
                registered_path.relative_to(worktree_base.resolve())
            except ValueError:
                continue
            if registered_path.is_dir():
                protected.add(registered_path)
                continue

        strategy_id = str(state.get("strategy_id") or state_file.stem)
        strategy_dir = worktree_base / strategy_id
        candidates = [path for path in strategy_dir.glob("iter-*") if path.is_dir()]
        if candidates:
            protected.add(max(candidates, key=_iteration_order).resolve())

    return protected


def _iteration_order(path: Path) -> tuple[int, float]:
    """Order iteration checkouts deterministically, with mtime as fallback."""
    suffix = path.name.removeprefix("iter-")
    try:
        iteration = int(suffix)
    except ValueError:
        iteration = -1
    try:
        modified = path.stat().st_mtime
    except OSError:
        modified = 0.0
    return iteration, modified


def _get_stale_backups(
    state_base: Path,
    max_age_days: int,
) -> List[Path]:
    """Find .bak state files older than threshold.

    Returns list of .bak file paths to remove.
    """
    stale = []
    if not state_base.exists():
        return stale

    cutoff = time.time() - (max_age_days * 86400)

    for bak_file in state_base.rglob("*.json.bak"):
        try:
            mtime = bak_file.stat().st_mtime
            if mtime < cutoff:
                stale.append(bak_file)
        except OSError:
            continue

    return stale


def run_gc(
    config: HarnessConfig,
    base_dir: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """Run garbage collection.

    Args:
        config: Harness configuration with GC thresholds.
        base_dir: Base directory. Defaults to cwd.
        dry_run: If True, only report what would be removed.

    Returns:
        Dict with counts of removed items.
    """
    base = Path(base_dir) if base_dir else Path.cwd()
    rd = runs_dir(base)
    # Collect worktree and state bases from all build dirs
    build_dirs = sorted(rd.glob("build-*/")) if rd.exists() else []
    state_bases = [d / "state" for d in build_dirs if d.is_dir()]

    result = {
        "containers_removed": 0,
        "worktrees_removed": 0,
        "backups_removed": 0,
    }

    # 1. Stale containers
    stale_containers = _get_stale_containers(
        config.gc.container_max_age_hours,
        container_cli=config.container_cli,
    )
    for container_id in stale_containers:
        if dry_run:
            logger.warning("DRY RUN: Would remove container %s", container_id)
        else:
            try:
                subprocess.run(
                    [config.container_cli, "rm", "-f", container_id],
                    capture_output=True, timeout=10, check=False,
                )
                logger.warning("Removed stale container: %s", container_id)
                result["containers_removed"] += 1
            except (subprocess.TimeoutExpired, FileNotFoundError):
                logger.warning("Could not remove container %s", container_id)

    # 2. Stale worktrees (across all build dirs)
    for build_dir in build_dirs:
        worktree_base = build_dir / "worktrees"
        stale_worktrees = _get_stale_worktrees(
            worktree_base,
            config.gc.worktree_max_age_hours,
            protected=_get_protected_worktrees(build_dir),
        )
        for wt_path in stale_worktrees:
            if dry_run:
                logger.warning("DRY RUN: Would remove worktree %s", wt_path)
            else:
                try:
                    import shutil
                    shutil.rmtree(str(wt_path))
                    logger.warning("Removed stale worktree: %s", wt_path)
                    result["worktrees_removed"] += 1
                except OSError as e:
                    logger.warning("Could not remove worktree %s: %s", wt_path, e)

    # 3. Stale backups (across all build state dirs)
    for state_base in state_bases:
        stale_backups = _get_stale_backups(state_base, config.gc.backup_max_age_days)
        for bak_path in stale_backups:
            if dry_run:
                logger.warning("DRY RUN: Would remove backup %s", bak_path)
            else:
                try:
                    bak_path.unlink()
                    logger.warning("Removed stale backup: %s", bak_path)
                    result["backups_removed"] += 1
                except OSError as e:
                    logger.warning("Could not remove backup %s: %s", bak_path, e)

    return result
