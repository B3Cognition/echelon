"""Canonical path functions for echelon harness runtime artifacts.

All runtime artifacts live under runs/ at the project root:
  runs/
    mirror.git               -- bare mirror of the target repo
    strategies/              -- user-managed strategy config (project-level)
    .current-build-{spec_id} -- marker: latest build_id for a spec
    build-{timestamp}/       -- one directory per harness run
      state/                 -- per-strategy state JSON files
      worktrees/             -- ephemeral git worktrees per strategy+iter
  spec-{timestamp}/          -- squad (Phase A) run output
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

RUNS_REL_BASE = "runs"


def runs_dir(base: Path) -> Path:
    """Return the echelon runs directory for a given project root."""
    return base / RUNS_REL_BASE


def mirror_path(base: Path) -> Path:
    """Return the bare mirror repository path."""
    return runs_dir(base) / "mirror.git"


def strategies_dir(base: Path) -> Path:
    """Return the project-level strategies directory (shared across all builds)."""
    return runs_dir(base) / "strategies"


def build_dir(base: Path, build_id: str) -> Path:
    """Return the directory for a specific harness build."""
    return runs_dir(base) / build_id


def current_build_marker(base: Path, spec_id: str) -> Path:
    """Return the marker file that holds the latest build_id for a spec."""
    return runs_dir(base) / f".current-build-{spec_id}"


def make_build_id() -> str:
    """Generate a unique build directory name: build-YYYYMMDD-HHMMSS-ffffff."""
    return f"build-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"


def make_spec_run_id() -> str:
    """Generate a unique squad run directory name: spec-YYYYMMDD-HHMMSS-ffffff."""
    return f"spec-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
