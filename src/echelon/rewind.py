"""Checkpoint-backed branch rewind."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from pathlib import PurePosixPath
import stat

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
    load_checkpoint_ledger,
    resolve_rewind_checkpoint,
    rewindable_checkpoint_targets,
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


def _allowed_recovery_dirty_paths(
    project_root: Path,
    spec_dir: Path,
    names: frozenset[str],
) -> frozenset[str]:
    if type(names) is not frozenset:
        raise RewindError("recovery-owned dirty path set is invalid")
    try:
        spec_path = spec_dir.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError as exc:
        raise RewindError("recovery-owned dirty path root is invalid") from exc
    resolved: set[str] = set()
    for name in names:
        candidate = PurePosixPath(name) if type(name) is str else PurePosixPath("/")
        if (
            type(name) is not str
            or not name
            or candidate.is_absolute()
            or candidate.as_posix() != name
            or any(part in {"", ".", ".."} for part in candidate.parts)
        ):
            raise RewindError("recovery-owned dirty path set is invalid")
        resolved.add(f"{spec_path}/{name}")
    return frozenset(resolved)


def _discard_recovery_dirty_paths(project_root: Path, paths: tuple[str, ...]) -> None:
    root = project_root.resolve()
    for relative in paths:
        target = root / PurePosixPath(relative)
        in_head = run_git(
            root,
            "cat-file",
            "-e",
            f"HEAD:{relative}",
            check=False,
        ).returncode == 0
        if in_head:
            run_git(root, "checkout", "HEAD", "--", relative)
            continue
        run_git(root, "reset", "HEAD", "--", relative)
        try:
            metadata = os.lstat(target)
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise RewindError("recovery-owned dirty path is not a regular file")
        target.unlink()
        directory = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def prepare_rewind(
    *,
    project_root: Path,
    spec: str,
    target: str,
    confirm: bool,
    spec_dir: Path | None = None,
    checkpoint_commit: str = "",
    checkpoint_next_phase: str = "",
    discard_active_spec_dirty_paths: frozenset[str] = frozenset(),
) -> RewindResult:
    resolved_spec_dir = spec_dir or _find_spec_dir(project_root, spec)
    ledger = load_checkpoint_ledger(resolved_spec_dir)
    try:
        checkpoint = resolve_rewind_checkpoint(
            ledger,
            target,
            commit=checkpoint_commit,
            next_phase=checkpoint_next_phase,
        )
    except (KeyError, ValueError) as exc:
        available = rewindable_checkpoint_targets(ledger)
        message = str(exc.args[0]) if exc.args else f"checkpoint not found: {target}"
        suffix = (
            f"\nAvailable checkpoints: {', '.join(available)}"
            if available
            else "\nNo checkpoints are recorded for this spec."
        )
        raise RewindError(message + suffix) from exc
    if checkpoint.rewind != "supported":
        raise RewindError(
            f"checkpoint {checkpoint.id!r} does not support rewind: "
            f"{checkpoint.rewind_reason}"
        )
    branch = current_branch(project_root)
    if checkpoint.spec_id not in branch:
        raise RewindError(
            f"active branch {branch!r} does not match spec {checkpoint.spec_id!r}"
        )
    dirty_paths = worktree_dirty_paths(project_root)
    active_spec_dirty_paths = _active_spec_dirty_paths(
        project_root, resolved_spec_dir, dirty_paths
    )
    allowed_dirty_paths = _allowed_recovery_dirty_paths(
        project_root,
        resolved_spec_dir,
        discard_active_spec_dirty_paths,
    )
    blocking_dirty_paths = [
        path for path in active_spec_dirty_paths if path not in allowed_dirty_paths
    ]
    recovery_dirty_paths = tuple(
        path for path in active_spec_dirty_paths if path in allowed_dirty_paths
    )
    if blocking_dirty_paths:
        raise RewindError(
            "dirty active spec paths block rewind; commit, stash, or discard them first:\n  "
            + "\n  ".join(blocking_dirty_paths)
        )

    head = run_git(project_root, "rev-parse", "HEAD").stdout.strip()
    same_head = head == checkpoint.commit
    if same_head and not recovery_dirty_paths:
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
    action = (
        f"Recovery retry will keep branch {branch} at {checkpoint.commit[:7]} "
        "and discard only recorded recovery-owned spec changes."
        if same_head
        else (
            f"Rewind will move branch {branch}:\n"
            f"  from: {head[:7]} current HEAD\n"
            f"  to:   {checkpoint.commit[:7]} {checkpoint.phase} checkpoint"
        )
    )
    message = (
        f"{action}\n\n"
        f"Backup branch:\n  {backup_ref}\n\n"
        "Continue with:\n  "
        f"echelon spec rewind {target}"
        + (f" --commit {checkpoint_commit}" if checkpoint_commit else "")
        + (
            f" --next-phase {checkpoint_next_phase}"
            if checkpoint_next_phase
            else ""
        )
        + " --confirm"
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
        _discard_recovery_dirty_paths(project_root, recovery_dirty_paths)
        remaining_active_dirt = _active_spec_dirty_paths(
            project_root,
            resolved_spec_dir,
            worktree_dirty_paths(project_root),
        )
        if remaining_active_dirt:
            raise RewindError("recovery-owned dirty paths could not be discarded")
        if not same_head:
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
        "Already at checkpoint; recovery-owned changes cleared."
        if same_head
        else "Rewind complete.",
    )
