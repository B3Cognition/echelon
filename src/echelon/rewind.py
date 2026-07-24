"""Checkpoint-backed branch rewind."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from echelon.git_helpers import (
    GitHelperError,
    create_backup_ref,
    current_branch,
    reset_branch_to_commit,
    run_git,
    worktree_dirty_paths,
)
from harness.phase_checkpoints import (
    CHECKPOINT_LEDGER_REL,
    CHECKPOINT_LOCK_REL,
    checkpoint_targets,
    load_checkpoint_ledger,
    resolve_checkpoint,
)


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


def _active_spec_dirty_paths(project_root: Path, spec_dir: Path, paths: set[str]) -> list[str]:
    """Find changed paths that would be overwritten as part of this spec rewind."""
    try:
        spec_path = spec_dir.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        # A run-local spec directory outside the project cannot be classified safely.
        return sorted(paths)
    prefix = f"{spec_path}/"
    runtime_files = {
        f"{spec_path}/{CHECKPOINT_LEDGER_REL.as_posix()}",
        f"{spec_path}/{CHECKPOINT_LOCK_REL.as_posix()}",
    }
    temporary_prefix = f"{spec_path}/.echelon/.checkpoints.json."
    return sorted(
        path
        for path in paths
        if (path == spec_path or path.startswith(prefix))
        and path not in runtime_files
        and not (
            path.startswith(temporary_prefix)
            and path.endswith(".tmp")
        )
    )


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
    spec_dir: Path | None = None,
) -> RewindResult:
    resolved_spec_dir = spec_dir or _find_spec_dir(project_root, spec)
    ledger = load_checkpoint_ledger(resolved_spec_dir)
    try:
        checkpoint = resolve_checkpoint(ledger, target)
    except KeyError as exc:
        available = checkpoint_targets(ledger)
        message = str(exc.args[0]) if exc.args else f"checkpoint not found: {target}"
        suffix = (
            f"\nAvailable checkpoints: {', '.join(available)}"
            if available
            else "\nNo checkpoints are recorded for this spec."
        )
        raise RewindError(message + suffix) from exc
    branch = current_branch(project_root)
    if checkpoint.spec_id not in branch:
        raise RewindError(
            f"active branch {branch!r} does not match spec {checkpoint.spec_id!r}"
        )
    dirty_paths = worktree_dirty_paths(project_root)
    active_spec_dirty_paths = _active_spec_dirty_paths(
        project_root, resolved_spec_dir, dirty_paths
    )
    if active_spec_dirty_paths:
        raise RewindError(
            "dirty active spec paths block rewind; commit, stash, or discard them first:\n  "
            + "\n  ".join(active_spec_dirty_paths)
        )

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
        f"Continue with:\n  echelon spec rewind {checkpoint.phase} --confirm"
    )
    if dirty_paths:
        message += "\n\nWorkspace changes to preserve:\n  " + "\n  ".join(sorted(dirty_paths))
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

    try:
        created = create_backup_ref(project_root, backup_ref, "HEAD")
        reset_branch_to_commit(
            project_root,
            checkpoint.commit,
            preserve_worktree=bool(dirty_paths),
        )
    except GitHelperError as exc:
        if dirty_paths:
            raise RewindError(
                "cannot rewind while preserving workspace changes; stash or resolve "
                "the conflicting changes first"
            ) from exc
        raise RewindError(str(exc)) from exc
    return RewindResult(
        True,
        checkpoint.spec_id,
        checkpoint.id,
        head,
        checkpoint.commit,
        created,
        "Rewind complete.",
    )
