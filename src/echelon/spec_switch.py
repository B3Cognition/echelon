"""Checkpoint-gated Git switching for existing Phase A spec runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from echelon.git_helpers import (
    GitHelperError,
    commit_exists,
    current_branch,
    ref_contains_commit,
    run_git,
)
from echelon.spec_lifecycle import (
    SpecLifecycleError,
    SpecLifecycleLock,
    SpecRun,
    begin_spec_switch,
    commit_spec_switch_pointer,
    load_spec_switch_intent,
    mark_spec_switch_checked_out,
    recover_spec_switch,
    resolve_active_spec_run,
    resolve_spec_run,
)
from echelon.speckit_git import (
    SpecKitGitOwnershipError,
    require_speckit_git_disabled,
)
from harness.phase_checkpoints import load_checkpoint_ledger


class SpecSwitchError(RuntimeError):
    """Raised when an existing spec run cannot be switched safely."""


class DirtySpecWorktreeError(SpecSwitchError):
    """Raised when Git-visible changes require an explicit switch action."""

    def __init__(self, paths: tuple[str, ...]) -> None:
        self.paths = paths
        super().__init__(
            "dirty worktree blocks spec switching: " + ", ".join(paths)
        )


@dataclass(frozen=True)
class ValidatedSpecCheckpoint:
    """A run-owned checkpoint proven reachable from its feature branch."""

    checkpoint_id: str
    phase: str
    commit: str
    run: SpecRun


@dataclass(frozen=True)
class SpecSwitchOutcome:
    """Verified result of selecting an existing Phase A spec run."""

    action: str
    source: SpecRun
    target: SpecRun
    source_checkpoint: ValidatedSpecCheckpoint
    target_checkpoint: ValidatedSpecCheckpoint
    stash_commit: str = ""
    stash_restored: bool = False
    restored_stash_commit: str = ""


def _local_branch_exists(project_root: Path, branch: str) -> bool:
    result = run_git(
        project_root,
        "show-ref",
        "--verify",
        "--quiet",
        f"refs/heads/{branch}",
        check=False,
    )
    return result.returncode == 0


def validate_spec_checkpoint(
    project_root: Path,
    run: SpecRun,
) -> ValidatedSpecCheckpoint:
    """Return the latest checkpoint owned by ``run`` after Git validation."""

    try:
        ledger = load_checkpoint_ledger(run.spec_dir)
    except (OSError, TypeError, ValueError, KeyError) as exc:
        raise SpecSwitchError(
            f"cannot read checkpoint ledger for {run.run_dir_name!r}: {exc}"
        ) from exc

    checkpoint = next(
        (
            item
            for item in reversed(ledger.checkpoints)
            if item.run_id == run.run_id and item.spec_id == run.spec_id
        ),
        None,
    )
    if checkpoint is None:
        raise SpecSwitchError(
            f"no checkpoint for run {run.run_dir_name!r} "
            f"({run.run_id}, {run.spec_id})"
        )
    if not commit_exists(project_root, checkpoint.commit):
        raise SpecSwitchError(
            f"checkpoint commit {checkpoint.commit!r} does not exist for "
            f"run {run.run_dir_name!r}"
        )
    if not _local_branch_exists(project_root, run.feature_branch):
        raise SpecSwitchError(
            f"feature branch {run.feature_branch!r} does not exist locally"
        )
    if not ref_contains_commit(project_root, run.feature_branch, checkpoint.commit):
        raise SpecSwitchError(
            f"feature branch {run.feature_branch!r} does not contain checkpoint "
            f"{checkpoint.commit!r}"
        )
    return ValidatedSpecCheckpoint(
        checkpoint_id=checkpoint.id,
        phase=checkpoint.phase,
        commit=checkpoint.commit,
        run=run,
    )


def _worktree_paths(project_root: Path) -> tuple[str, ...]:
    status = run_git(
        project_root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        check=False,
    )
    if status.returncode != 0:
        detail = (status.stderr or status.stdout or "unknown status error").strip()
        raise SpecSwitchError(f"cannot inspect Git worktree: {detail}")
    records = status.stdout.split("\0")
    paths: set[str] = set()
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 4:
            raise SpecSwitchError(f"cannot parse Git status record: {record!r}")
        code = record[:2]
        paths.add(record[3:])
        if "R" in code or "C" in code:
            if index >= len(records) or not records[index]:
                raise SpecSwitchError("cannot parse renamed Git status path")
            paths.add(records[index])
            index += 1
    return tuple(
        sorted(
            path
            for path in paths
            if not path.startswith(".echelon/runtime/")
        )
    )


def _load_run_state(run: SpecRun) -> dict[str, object]:
    path = run.run_dir / "state.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecSwitchError(f"cannot read run state {path}: {exc}") from exc
    if not isinstance(state, dict):
        raise SpecSwitchError(f"run state must be a JSON object: {path}")
    return state


def _write_run_state(run: SpecRun, state: dict[str, object]) -> None:
    path = run.run_dir / "state.json"
    fd, temporary = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=".state-switch-",
        suffix=".tmp",
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _managed_stash(run: SpecRun) -> dict[str, str] | None:
    raw = _load_run_state(run).get("phase_a_stash")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SpecSwitchError(
            f"managed stash record for {run.run_dir_name!r} must be an object"
        )
    required = (
        "commit",
        "branch",
        "checkpoint_id",
        "checkpoint_commit",
        "created_at",
    )
    record: dict[str, str] = {}
    for key in required:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise SpecSwitchError(
                f"managed stash field {key!r} for {run.run_dir_name!r} is invalid"
            )
        record[key] = value.strip()
    if record["branch"] != run.feature_branch:
        raise SpecSwitchError(
            f"managed stash branch {record['branch']!r} does not match "
            f"run branch {run.feature_branch!r}"
        )
    return record


def _stash_selector(project_root: Path, commit: str) -> str | None:
    listing = run_git(
        project_root,
        "stash",
        "list",
        "--format=%gd%x00%H",
    ).stdout
    for line in listing.splitlines():
        selector, separator, candidate = line.partition("\0")
        if separator and candidate.strip() == commit:
            return selector.strip()
    return None


def _create_managed_stash(
    project_root: Path,
    run: SpecRun,
    checkpoint: ValidatedSpecCheckpoint,
) -> str:
    if _managed_stash(run) is not None:
        raise SpecSwitchError(
            f"run {run.run_dir_name!r} already has a managed stash; restore it first"
        )
    message = (
        f"echelon spec switch: run={run.run_id} spec={run.spec_id} "
        f"branch={run.feature_branch}"
    )
    result = run_git(
        project_root,
        "stash",
        "push",
        "--include-untracked",
        "--message",
        message,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown stash error").strip()
        raise SpecSwitchError(f"managed stash failed: {detail}")
    try:
        commit = run_git(
            project_root,
            "rev-parse",
            "--verify",
            "refs/stash^{commit}",
        ).stdout.strip()
    except GitHelperError as exc:
        raise SpecSwitchError(f"cannot resolve managed stash commit: {exc}") from exc
    if not commit or _stash_selector(project_root, commit) is None:
        raise SpecSwitchError("managed stash commit is not present in the stash ledger")
    if dirty := _worktree_paths(project_root):
        raise DirtySpecWorktreeError(dirty)

    state = _load_run_state(run)
    state["phase_a_stash"] = {
        "commit": commit,
        "branch": run.feature_branch,
        "checkpoint_id": checkpoint.checkpoint_id,
        "checkpoint_commit": checkpoint.commit,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_run_state(run, state)
    return commit


def _require_restorable_stash(project_root: Path, run: SpecRun) -> dict[str, str]:
    record = _managed_stash(run)
    if record is None:
        raise SpecSwitchError(f"run {run.run_dir_name!r} has no managed stash to restore")
    if _stash_selector(project_root, record["commit"]) is None:
        raise SpecSwitchError(
            f"managed stash commit {record['commit']!r} is missing from the stash ledger"
        )
    return record


def _restore_managed_stash(
    project_root: Path,
    run: SpecRun,
    record: dict[str, str],
) -> str:
    commit = record["commit"]
    applied = run_git(project_root, "stash", "apply", commit, check=False)
    if applied.returncode != 0:
        detail = (applied.stderr or applied.stdout or "unknown apply error").strip()
        raise SpecSwitchError(f"managed stash apply failed for {commit}: {detail}")
    selector = _stash_selector(project_root, commit)
    if selector is None:
        raise SpecSwitchError(
            f"managed stash {commit!r} disappeared after apply; run state was preserved"
        )
    dropped = run_git(project_root, "stash", "drop", selector, check=False)
    if dropped.returncode != 0:
        detail = (dropped.stderr or dropped.stdout or "unknown drop error").strip()
        raise SpecSwitchError(f"managed stash drop failed for {commit}: {detail}")

    state = _load_run_state(run)
    current = state.get("phase_a_stash")
    if not isinstance(current, dict) or current.get("commit") != commit:
        raise SpecSwitchError(
            f"managed stash state changed before clearing commit {commit!r}"
        )
    state.pop("phase_a_stash")
    _write_run_state(run, state)
    return commit


def _discard_to_checkpoint(
    project_root: Path,
    checkpoint: ValidatedSpecCheckpoint,
) -> None:
    run_git(project_root, "reset", "--hard", checkpoint.commit)
    run_git(project_root, "clean", "-fd")
    if dirty := _worktree_paths(project_root):
        raise DirtySpecWorktreeError(dirty)


def spec_worktree_paths(project_root: Path) -> tuple[str, ...]:
    """Return Git-visible dirty paths using the spec-switch parser."""

    return _worktree_paths(Path(project_root).resolve())


def stash_spec_worktree(
    project_root: Path,
    run: SpecRun,
    checkpoint: ValidatedSpecCheckpoint,
) -> str:
    """Stash dirty state under the source run's managed stash record."""

    return _create_managed_stash(Path(project_root).resolve(), run, checkpoint)


def discard_spec_worktree(
    project_root: Path,
    checkpoint: ValidatedSpecCheckpoint,
) -> None:
    """Discard dirty state back to the exact validated checkpoint."""

    _discard_to_checkpoint(Path(project_root).resolve(), checkpoint)


def _switch_spec_locked(
    project_root: Path,
    identity: str,
    *,
    operation_id: str,
    dirty_action: str,
    confirm_discard: bool,
    restore_stash: bool,
) -> SpecSwitchOutcome:
    observed_branch = current_branch(project_root)
    if not observed_branch:
        raise SpecSwitchError("detached HEAD blocks spec switching")

    if load_spec_switch_intent(project_root) is not None:
        recover_spec_switch(project_root, observed_branch=observed_branch)
        observed_branch = current_branch(project_root)

    source = resolve_active_spec_run(project_root)
    target = resolve_spec_run(project_root, identity)
    source_checkpoint = validate_spec_checkpoint(project_root, source)
    if observed_branch != source.feature_branch:
        raise SpecSwitchError(
            f"active run branch is {source.feature_branch!r}, "
            f"but Git is on {observed_branch!r}"
        )
    target_checkpoint = validate_spec_checkpoint(project_root, target)
    restore_record = (
        _require_restorable_stash(project_root, target) if restore_stash else None
    )
    if source.run_dir == target.run_dir:
        restored_commit = ""
        if restore_record is not None:
            if dirty := _worktree_paths(project_root):
                raise DirtySpecWorktreeError(dirty)
            restored_commit = _restore_managed_stash(
                project_root,
                target,
                restore_record,
            )
        return SpecSwitchOutcome(
            action="already_active",
            source=source,
            target=target,
            source_checkpoint=source_checkpoint,
            target_checkpoint=target_checkpoint,
            stash_restored=bool(restored_commit),
            restored_stash_commit=restored_commit,
        )
    dirty_paths = _worktree_paths(project_root)
    stash_commit = ""
    if dirty_paths:
        if dirty_action == "refuse":
            raise DirtySpecWorktreeError(dirty_paths)
        if dirty_action == "stash":
            stash_commit = _create_managed_stash(
                project_root,
                source,
                source_checkpoint,
            )
        elif dirty_action == "discard":
            if not confirm_discard:
                raise SpecSwitchError(
                    "discard requires explicit confirmation via --discard --confirm"
                )
            _discard_to_checkpoint(project_root, source_checkpoint)
        else:
            raise SpecSwitchError(f"unsupported dirty action: {dirty_action!r}")

    begin_spec_switch(
        project_root,
        source,
        target,
        observed_branch=observed_branch,
        operation_id=operation_id,
    )
    try:
        run_git(project_root, "switch", target.feature_branch)
    except GitHelperError as exc:
        raise SpecSwitchError(str(exc)) from exc

    observed_target = current_branch(project_root)
    if observed_target != target.feature_branch:
        raise SpecSwitchError(
            f"target checkout verification failed: expected {target.feature_branch!r}, "
            f"found {observed_target!r}"
        )
    mark_spec_switch_checked_out(
        project_root,
        operation_id,
        observed_branch=observed_target,
    )
    selected = commit_spec_switch_pointer(
        project_root,
        operation_id,
        observed_branch=observed_target,
    )
    restored_commit = ""
    if restore_record is not None:
        restored_commit = _restore_managed_stash(
            project_root,
            selected,
            restore_record,
        )
    return SpecSwitchOutcome(
        action="switched",
        source=source,
        target=selected,
        source_checkpoint=source_checkpoint,
        target_checkpoint=target_checkpoint,
        stash_commit=stash_commit,
        stash_restored=bool(restored_commit),
        restored_stash_commit=restored_commit,
    )


def switch_spec(
    project_root: Path,
    identity: str,
    *,
    dirty_action: str = "refuse",
    confirm_discard: bool = False,
    restore_stash: bool = False,
) -> SpecSwitchOutcome:
    """Switch to an existing checkpointed run without invoking a provider."""

    if dirty_action not in {"refuse", "stash", "discard"}:
        raise SpecSwitchError(f"unsupported dirty action: {dirty_action!r}")
    if dirty_action == "discard" and not confirm_discard:
        raise SpecSwitchError(
            "discard requires explicit confirmation via --discard --confirm"
        )
    if confirm_discard and dirty_action != "discard":
        raise SpecSwitchError("discard confirmation requires dirty_action='discard'")
    root = Path(project_root).resolve()
    operation_id = f"switch-{uuid4().hex}"
    try:
        with SpecLifecycleLock.acquire(root, operation_id):
            require_speckit_git_disabled(root)
            return _switch_spec_locked(
                root,
                identity,
                operation_id=operation_id,
                dirty_action=dirty_action,
                confirm_discard=confirm_discard,
                restore_stash=restore_stash,
            )
    except SpecSwitchError:
        raise
    except (GitHelperError, SpecKitGitOwnershipError, SpecLifecycleError) as exc:
        raise SpecSwitchError(str(exc)) from exc
