"""Checkpoint-backed branch rewind."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from echelon.git_helpers import (
    create_backup_ref,
    current_branch,
    is_worktree_dirty,
    reset_branch_to_commit,
    run_git,
)
from harness.phase_checkpoints import load_checkpoint_ledger, resolve_checkpoint


class RewindError(RuntimeError):
    pass


@dataclass(frozen=True)
class RewindResult:
    applied: bool
    spec_id: str
    checkpoint_id: str
    from_commit: str
    to_commit: str
    backup_ref: str
    message: str


def _find_spec_dir(project_root: Path, spec: str) -> Path:
    specs_dir = project_root / "specs"
    matches = (
        sorted(path for path in specs_dir.iterdir() if path.is_dir() and path.name.startswith(spec))
        if specs_dir.exists()
        else []
    )
    if not matches:
        raise RewindError(f"no spec directory found for {spec!r}")
    return matches[0]


def prepare_rewind(
    *,
    project_root: Path,
    spec: str,
    target: str,
    confirm: bool,
) -> RewindResult:
    spec_dir = _find_spec_dir(project_root, spec)
    ledger = load_checkpoint_ledger(spec_dir)
    checkpoint = resolve_checkpoint(ledger, target)
    branch = current_branch(project_root)
    if checkpoint.spec_id not in branch:
        raise RewindError(
            f"active branch {branch!r} does not match spec {checkpoint.spec_id!r}"
        )
    if is_worktree_dirty(project_root):
        raise RewindError("dirty worktree blocks rewind; commit, stash, or discard changes first")

    head = run_git(project_root, "rev-parse", "HEAD").stdout.strip()
    if head == checkpoint.commit:
        return RewindResult(
            True,
            checkpoint.spec_id,
            checkpoint.id,
            head,
            checkpoint.commit,
            "",
            "Already at checkpoint.",
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_ref = f"echelon/backup/{checkpoint.spec_id}-before-rewind-{stamp}"
    message = (
        f"Rewind will move branch {branch}:\n"
        f"  from: {head[:7]} current HEAD\n"
        f"  to:   {checkpoint.commit[:7]} {checkpoint.phase} checkpoint\n\n"
        f"Backup branch:\n  {backup_ref}\n\n"
        f"Continue with:\n  echelon rewind {checkpoint.phase} --confirm"
    )
    if not confirm:
        return RewindResult(
            False,
            checkpoint.spec_id,
            checkpoint.id,
            head,
            checkpoint.commit,
            backup_ref,
            message,
        )

    created = create_backup_ref(project_root, backup_ref, "HEAD")
    reset_branch_to_commit(project_root, checkpoint.commit)
    return RewindResult(
        True,
        checkpoint.spec_id,
        checkpoint.id,
        head,
        checkpoint.commit,
        created,
        "Rewind complete.",
    )
