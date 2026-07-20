"""Transactional Echelon-owned bootstrap for a fresh Phase A spec."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
from uuid import uuid4

from echelon.git_helpers import GitHelperError, current_branch, run_git
from echelon.phase_a_git import (
    PhaseAGitError,
    PhaseASpecBootstrap,
    create_phase_a_spec_branch_ref,
    plan_phase_a_spec,
)
from echelon.spec_lifecycle import (
    PhaseAExecutionLock,
    SpecLifecycleError,
    SpecLifecycleLock,
    SpecRun,
    activate_initial_spec_run,
    begin_spec_switch,
    commit_spec_switch_pointer,
    load_spec_switch_intent,
    mark_spec_switch_checked_out,
    recover_spec_switch,
    resolve_active_spec_run,
    resolve_spec_run,
)
from echelon.spec_switch import (
    DirtySpecWorktreeError,
    SpecSwitchError,
    ValidatedSpecCheckpoint,
    discard_spec_worktree,
    spec_worktree_paths,
    stash_spec_worktree,
    validate_spec_checkpoint,
)
from echelon.speckit_git import SpecKitGitOwnershipError, require_speckit_git_disabled


class PhaseAStartError(RuntimeError):
    """Raised when a fresh spec cannot be activated safely."""


@dataclass(frozen=True)
class PhaseAStartOutcome:
    run_dir: Path
    bootstrap: PhaseASpecBootstrap
    source: SpecRun | None = None
    source_checkpoint: ValidatedSpecCheckpoint | None = None
    stash_commit: str = ""


def _write_prepared_state(
    run_dir: Path,
    run_id: str,
    description: str,
    bootstrap: PhaseASpecBootstrap,
) -> None:
    run_dir.mkdir(parents=True)
    (run_dir / "staging").mkdir()
    (run_dir / "specs" / bootstrap.spec_id).mkdir(parents=True)
    payload: dict[str, object] = {
        "run_id": run_id,
        "status": "preparing",
        "user_message": description,
        **bootstrap.state_updates(),
    }
    (run_dir / "state.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def _resolve_source(root: Path) -> SpecRun | None:
    pointer = root / "runs" / ".current"
    if not pointer.exists():
        return None
    return resolve_active_spec_run(root)


def start_phase_a_spec(
    project_root: Path,
    run_id: str,
    description: str,
    *,
    configured_default_branch: str = "",
    dirty_action: str = "refuse",
    confirm_discard: bool = False,
) -> PhaseAStartOutcome:
    """Create and select a fresh sibling spec branch without invoking an LLM."""

    if dirty_action not in {"refuse", "stash", "discard"}:
        raise PhaseAStartError(f"unsupported dirty action: {dirty_action!r}")
    if dirty_action == "discard" and not confirm_discard:
        raise PhaseAStartError("discard requires explicit confirmation via --discard --confirm")
    if confirm_discard and dirty_action != "discard":
        raise PhaseAStartError("discard confirmation requires dirty_action='discard'")

    root = Path(project_root).resolve()
    target_dir = root / "runs" / run_id
    operation_id = f"start-{uuid4().hex}"
    created_branch = ""
    try:
        with SpecLifecycleLock.acquire(root, operation_id):
            with PhaseAExecutionLock.acquire(root, operation_id):
                require_speckit_git_disabled(root)
                observed = current_branch(root)
                if not observed:
                    raise PhaseAStartError("detached HEAD blocks a fresh spec start")
                if load_spec_switch_intent(root) is not None:
                    recover_spec_switch(root, observed_branch=observed)
                    observed = current_branch(root)

                source = _resolve_source(root)
                source_checkpoint = None
                stash_commit = ""
                if source is not None:
                    if observed != source.feature_branch:
                        raise PhaseAStartError(
                            f"active run branch is {source.feature_branch!r}, but Git is on {observed!r}"
                        )
                    source_checkpoint = validate_spec_checkpoint(root, source)

                dirty_paths = spec_worktree_paths(root)
                if dirty_paths:
                    if source is None:
                        raise DirtySpecWorktreeError(dirty_paths)
                    if dirty_action == "refuse":
                        raise DirtySpecWorktreeError(dirty_paths)
                    if dirty_action == "stash":
                        stash_commit = stash_spec_worktree(root, source, source_checkpoint)
                    else:
                        discard_spec_worktree(root, source_checkpoint)

                if target_dir.exists():
                    raise PhaseAStartError(f"target run directory already exists: {target_dir}")
                bootstrap = plan_phase_a_spec(
                    root,
                    target_dir,
                    description,
                    configured_default_branch,
                )
                if source is None and observed != bootstrap.default_branch:
                    raise PhaseAStartError(
                        "first spec start requires the configured default branch "
                        f"{bootstrap.default_branch!r}; found {observed!r}"
                    )
                create_phase_a_spec_branch_ref(root, bootstrap, clean_verified=True)
                created_branch = bootstrap.feature_branch
                _write_prepared_state(target_dir, run_id, description, bootstrap)
                target = resolve_spec_run(root, run_id)

                if source is not None:
                    begin_spec_switch(
                        root,
                        source,
                        target,
                        observed_branch=observed,
                        operation_id=operation_id,
                    )
                run_git(root, "switch", bootstrap.feature_branch)
                selected_branch = current_branch(root)
                if source is None:
                    activate_initial_spec_run(
                        root,
                        target,
                        observed_branch=selected_branch,
                    )
                else:
                    mark_spec_switch_checked_out(
                        root,
                        operation_id,
                        observed_branch=selected_branch,
                    )
                    commit_spec_switch_pointer(
                        root,
                        operation_id,
                        observed_branch=selected_branch,
                    )
                return PhaseAStartOutcome(
                    run_dir=target_dir,
                    bootstrap=bootstrap,
                    source=source,
                    source_checkpoint=source_checkpoint,
                    stash_commit=stash_commit,
                )
    except PhaseAStartError:
        raise
    except DirtySpecWorktreeError as exc:
        raise PhaseAStartError(str(exc)) from exc
    except (
        GitHelperError,
        PhaseAGitError,
        SpecKitGitOwnershipError,
        SpecLifecycleError,
        SpecSwitchError,
    ) as exc:
        intent_exists = load_spec_switch_intent(root) is not None
        try:
            branch_after_error = current_branch(root)
        except GitHelperError:
            branch_after_error = ""
        if not intent_exists:
            if created_branch and branch_after_error == created_branch:
                run_git(root, "switch", bootstrap.default_branch, check=False)
            if target_dir.exists():
                shutil.rmtree(target_dir)
            if created_branch:
                run_git(root, "branch", "-D", created_branch, check=False)
        raise PhaseAStartError(str(exc)) from exc
