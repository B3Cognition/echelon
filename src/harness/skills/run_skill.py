"""Run skill orchestration entry point.

Wires RunIntent parsing to the single DeliveryController and terminal output.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import logging
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from harness.config import load_config
from harness.delivery_controller import DeliveryController
from harness.gc import run_gc
from harness.harness_run_history import append_run, summarize_history
from harness.delivery_results import DeliveryResult, DeliveryRunOutcome, LandingOutcome
from harness.delivery_execution_lease import DeliveryExecutionLocked, target_delivery_execution_lease
from harness.paths import make_build_id, current_build_marker, runs_dir
from harness.run_intent import parse_intent
from harness.spec_frontmatter import find_spec_dir, read_targets
from harness.state import state_lock_owner_is_alive

logger = logging.getLogger(__name__)

_CHECKPOINT_REASONS = {"build_incomplete", "publish_failed", "checkpoint_outer_cap"}
_RECOVERABLE_BASELINE_REASONS = {
    "build_blocked",
    "outer_cap",
    "checkpoint_outer_cap",
    "task_progress_incomplete",
    "publish_failed",
}


class RunContextError(ValueError):
    """The delivery caller supplied an invalid orchestration context."""


@dataclass(frozen=True)
class _AmendedDeliveryAdmission:
    task_ids: tuple[str, ...]
    amendment_id: str
    spec_commit: str
    target_id: str
    baseline_commit: str | None
    input_hash: str

    def durable_identity(self) -> dict[str, str]:
        return {
            "amendment_id": self.amendment_id,
            "spec_commit": self.spec_commit,
            "target_id": self.target_id,
            "input_hash": self.input_hash,
        }


@dataclass
class _DeliverySummaryScope:
    intent: Any
    harness_root: Path
    workspace_root: Path
    spec_dir: Path | None
    config: Any
    summary_command: str
    emitted: bool = False


_ACTIVE_DELIVERY_SUMMARY: ContextVar[_DeliverySummaryScope | None] = ContextVar(
    "echelon_delivery_summary_scope",
    default=None,
)


def print_run_context_error(spec_id: str, error: RunContextError) -> None:
    """Render an invalid explicit orchestration context at adapter boundaries."""
    from echelon.ui import banner

    banner(
        "HARNESS — INVALID ORCHESTRATION CONTEXT",
        [
            ("spec", spec_id),
            ("problem", str(error)),
            (
                "next step",
                "run delivery from the workspace that owns specs/, or repair "
                "the supplied orchestration root",
            ),
        ],
        file=sys.stderr,
    )


def _resolve_run_roots(
    base_dir: str | Path,
    orchestration_root: str | Path | None,
) -> tuple[Path, Path]:
    harness_root = Path(base_dir).resolve()
    workspace_root = (
        Path(orchestration_root).resolve()
        if orchestration_root is not None
        else harness_root
    )
    if orchestration_root is not None and not workspace_root.is_dir():
        raise RunContextError(
            f"orchestration root is not a directory: {workspace_root}"
        )
    return harness_root, workspace_root


def _fresh_delivery_repaired_candidate(
    *,
    gitops: Any | None,
    state: Mapping[str, object],
    spec_id: str,
    build_id: str,
    checkpoint: str,
) -> str | None:
    """Retain a clean post-block repair without granting checkpoint authority.

    A build-blocked run may be repaired manually after Ralph has salvaged its
    last candidate.  The next budget may start from that committed descendant,
    but task recovery remains bound to the actual checkpoint entries in state.
    This preserves the repair for fresh verification/review without fabricating
    a receipt or treating the salvaged task as complete.
    """
    if gitops is None or not _has_retainable_salvage(state):
        return None
    salvage = state.get("salvage_commit")
    if not isinstance(salvage, str) or not re.fullmatch(r"[0-9a-f]{40}", salvage):
        return None
    clean_head = getattr(gitops, "get_clean_worktree_head", None)
    ancestry = getattr(gitops, "commit_is_ancestor", None)
    if not callable(clean_head) or not callable(ancestry):
        return None
    try:
        candidate = clean_head(spec_id, build_id=build_id)
    except Exception as error:
        logger.warning("Could not inspect preserved worktree for %s: %s", build_id, error)
        return None
    if not isinstance(candidate, str) or not re.fullmatch(r"[0-9a-f]{40}", candidate):
        return None
    if state.get("status") == "interrupted" and candidate != salvage:
        return None
    try:
        checkpoint_contains_salvage = ancestry(checkpoint, salvage) is True
        salvage_contains_candidate = ancestry(salvage, candidate) is True
    except Exception as error:
        logger.warning("Could not verify repaired candidate lineage for %s: %s", build_id, error)
        return None
    if not checkpoint_contains_salvage or not salvage_contains_candidate:
        return None
    if candidate != checkpoint:
        logger.info(
            "Retaining clean unreviewed candidate %s from %s; checkpoint authority remains %s",
            candidate[:12],
            build_id,
            checkpoint[:12],
        )
    return candidate


def _fresh_delivery_checkpointless_salvage(
    *,
    gitops: Any | None,
    state: Mapping[str, object],
    spec_id: str,
    build_id: str,
) -> str | None:
    """Retain only the recorded, clean salvage on the current target lineage."""
    if gitops is None:
        return None
    salvage = state.get("salvage_commit")
    if not isinstance(salvage, str) or not re.fullmatch(r"[0-9a-f]{40}", salvage):
        return None
    try:
        candidate = gitops.get_clean_worktree_head(spec_id, build_id=build_id)
        default_branch = gitops.get_default_branch()
        if (
            candidate != salvage
            or not isinstance(default_branch, str)
            or not default_branch
            or gitops.commit_is_ancestor(default_branch, salvage) is not True
            or _checkpoint_is_landed(gitops, salvage)
        ):
            return None
    except Exception as error:
        logger.warning("Could not verify checkpointless salvage for %s: %s", build_id, error)
        return None
    logger.info(
        "Retaining clean unreviewed salvage %s from %s; no task checkpoint was recorded",
        salvage[:12],
        build_id,
    )
    return salvage


def _has_retainable_salvage(state: Mapping[str, object]) -> bool:
    return (
        state.get("status") == "blocked"
        and state.get("termination_reason") == "build_blocked"
    ) or (
        state.get("status") == "interrupted"
        and state.get("termination_reason") == "user_cancel"
    )


def _reject_unretained_pending_candidate(
    state: Mapping[str, object],
    *,
    build_dir: Path,
) -> None:
    """A new budget must not silently bypass loose, unreviewed provider output."""
    operation = state.get("delivery_slice_operation")
    if not isinstance(operation, dict) or operation.get("progress_applied") is True:
        return
    candidate = operation.get("worktree_path")
    if not isinstance(candidate, str):
        return
    worktree = Path(candidate)
    if (
        not worktree.is_absolute()
        or worktree.is_symlink()
        or not worktree.is_dir()
        or not worktree.resolve().is_relative_to((build_dir / "worktrees").resolve())
    ):
        raise RunContextError(
            f"pending delivery candidate is missing or unsafe: {candidate}"
        )
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=worktree, capture_output=True, text=True, timeout=30, check=False,
    )
    if status.returncode != 0 or status.stdout.strip():
        raise RunContextError(
            f"prior delivery has an uncommitted candidate: {worktree}; "
            "retain or reconcile it before starting a new run"
        )


def _fresh_delivery_baseline(
    harness_root: Path,
    intent: Any,
    gitops: Any | None = None,
) -> str | None:
    """Return prior delivery work a new budget may safely reverify.

    A normal fresh delivery intentionally restarts from the target default branch.
    The exception is a prior stopped run for the same spec with a durable
    checkpoint or a clean recorded salvage candidate.  A state left ``running`` by
    an ungraceful process exit is recoverable only after its lock owner is dead;
    a live owner prevents a competing delivery.  This decision is made before the
    current-build marker is advanced, so the new build cannot accidentally erase
    the only recoverable candidate branch.
    """
    if getattr(intent, "reset", False) or getattr(intent, "resume", False):
        return None
    marker = current_build_marker(harness_root, intent.spec_id)
    try:
        marked_build_id = marker.read_text(encoding="utf-8").strip()
    except OSError:
        marked_build_id = ""

    # A cancelled or failed fresh attempt can advance the marker without ever
    # writing a durable checkpoint.  Search the remaining build directories as
    # well, newest first, so that bookkeeping failure cannot strand an older
    # recoverable candidate.
    build_ids = [marked_build_id] if marked_build_id else []
    build_ids.extend(
        path.name
        for path in sorted(runs_dir(harness_root).glob("build-*"), reverse=True)
        if path.is_dir() and path.name != marked_build_id
    )

    pending_repair_states: list[tuple[str, Mapping[str, object]]] = []
    latest_recoverable_checked = False
    for prior_build_id in build_ids:
        state_path = runs_dir(harness_root) / prior_build_id / "state" / "delivery.json"
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(state, dict) or state.get("spec_id") != intent.spec_id:
            continue
        status = str(state.get("status") or "")
        if status == "running" and state_lock_owner_is_alive(state_path):
            raise RunContextError(
                f"delivery is already active for {intent.spec_id} in {prior_build_id}"
            )
        recoverable = (
            status in {"interrupted", "running"}
            or (
                status == "blocked"
                and state.get("termination_reason")
                in _RECOVERABLE_BASELINE_REASONS
            )
        )
        if not recoverable:
            continue
        if not latest_recoverable_checked:
            _reject_unretained_pending_candidate(
                state,
                build_dir=state_path.parent.parent,
            )
            latest_recoverable_checked = True
        checkpoints = state.get("checkpoint_commits")
        if not isinstance(checkpoints, list):
            if _has_retainable_salvage(state) and isinstance(state.get("salvage_commit"), str):
                pending_repair_states.append((prior_build_id, state))
            continue
        for checkpoint in reversed(checkpoints):
            if not isinstance(checkpoint, dict):
                continue
            commit = checkpoint.get("commit")
            if isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit):
                if _checkpoint_is_landed(gitops, commit):
                    logger.info(
                        "Latest checkpoint %s is already contained in the target "
                        "default branch; starting fresh",
                        commit[:12],
                    )
                    # A newer durable checkpoint supersedes every older run.
                    # Once it has landed, an old abandoned candidate must not
                    # be revived merely because its state still says running.
                    return None
                for repair_build_id, repair_state in pending_repair_states:
                    repaired_candidate = _fresh_delivery_repaired_candidate(
                        gitops=gitops,
                        state=repair_state,
                        spec_id=intent.spec_id,
                        build_id=repair_build_id,
                        checkpoint=commit,
                    )
                    if repaired_candidate:
                        return repaired_candidate
                repaired_candidate = _fresh_delivery_repaired_candidate(
                    gitops=gitops,
                    state=state,
                    spec_id=intent.spec_id,
                    build_id=prior_build_id,
                    checkpoint=commit,
                )
                return repaired_candidate or commit
        if _has_retainable_salvage(state) and isinstance(state.get("salvage_commit"), str):
            pending_repair_states.append((prior_build_id, state))
    for salvage_build_id, salvage_state in pending_repair_states:
        candidate = _fresh_delivery_checkpointless_salvage(
            gitops=gitops,
            state=salvage_state,
            spec_id=intent.spec_id,
            build_id=salvage_build_id,
        )
        if candidate is not None:
            return candidate
    return None


def _fresh_delivery_completed_tasks(
    harness_root: Path,
    intent: Any,
    baseline: str | None,
    gitops: Any | None = None,
    *,
    spec_dir: Path | None = None,
) -> tuple[str, ...]:
    """Recover Python-checkpointed task progress on the retained lineage.

    Provider task results are intentionally insufficient: a process can exit
    after writing its status marker but before Ralph commits the corresponding
    checkpoint.  Only task IDs recorded on checkpoint commits that are
    ancestors of the selected baseline are inherited by a fresh budget.
    """
    if baseline is None or gitops is None:
        return ()
    from harness.task_progress import checkpoint_input_hash

    current_input_hash = checkpoint_input_hash(spec_dir)
    if current_input_hash is None:
        return ()
    ancestry = getattr(gitops, "commit_is_ancestor", None)
    if not callable(ancestry):
        return ()

    recovered: set[str] = set()
    for state_path in sorted(runs_dir(harness_root).glob("build-*/state/delivery.json")):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(state.get("spec_id") or "") != str(intent.spec_id):
            continue
        checkpoints = state.get("checkpoint_commits")
        if not isinstance(checkpoints, list):
            continue
        for checkpoint in checkpoints:
            if not isinstance(checkpoint, dict):
                continue
            if checkpoint.get("checkpoint_input_hash") != current_input_hash:
                continue
            commit = checkpoint.get("commit")
            task_ids = checkpoint.get("task_ids")
            if (
                not isinstance(commit, str)
                or not re.fullmatch(r"[0-9a-f]{40}", commit)
                or not isinstance(task_ids, list)
            ):
                continue
            try:
                retained = ancestry(commit, baseline) is True
            except Exception:
                retained = False
            if not retained:
                continue
            recovered.update(
                task_id.strip()
                for task_id in task_ids
                if isinstance(task_id, str)
                and re.fullmatch(r"T-\d+", task_id.strip())
            )
    return tuple(sorted(recovered))


def _amended_delivery_completed_tasks(
    *,
    workspace_root: Path,
    harness_root: Path,
    spec_dir: Path | None,
    intent: Any,
    candidate: str | None,
    gitops: Any,
    config: Any,
    resume_build_id: str | None = None,
    handoff_locks: ExitStack | None = None,
) -> _AmendedDeliveryAdmission | None:
    """Validate a settled plan amendment before inheriting old task checkpoints.

    None means no promoted amendment applies and preserves the original exact-
    hash path. An admission with empty task IDs proves no old task.
    """
    from echelon.spec_amendment import _amendment_root
    from echelon.runnability_amendment import (
        _LIFECYCLE_STATUSES, _canonical_targets, _git, _published_blob, _sha256,
    )
    from harness.amendment_lineage import AmendmentLineageError, proven_amended_task_ids
    from harness.fulfillment_runner import SCOPE_INPUT_FILENAMES
    from harness.paths import mirror_path
    from harness.publication_transaction import PublicationTransaction
    from harness.runnability_amendment_plan import (
        plan_owner_tasks, render_owner_tasks, validate_progress_only,
    )
    from harness.stacks.resolver import resolved_stack_contract_sha256
    from harness.spec_frontmatter import render_status_markdown
    from harness.task_progress import (
        checkpoint_input_hash, checkpoint_input_hash_from_contents,
        summarize_task_progress,
    )
    from harness.terminal_documentation_handoff import prove_terminal_documentation_handoff
    from harness.verification_stack_runtime import resolve_verification_stacks
    from kernel.task_contract import parse_task_rows

    if spec_dir is None:
        return None
    root = workspace_root.resolve()
    if not (root / ".git").exists():
        return None
    amendment_root = _amendment_root(root, intent.spec_id)
    if not amendment_root.is_dir():
        return None
    amendments: list[tuple[Path, dict[str, object]]] = []
    for state_path in sorted(amendment_root.glob("[0-9]*/state.json")):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RunContextError(f"unreadable Spec amendment state: {state_path}") from exc
        if isinstance(state, dict) and state.get("kind") == "runnability_owner":
            amendments.append((state_path, state))
    if not amendments:
        return None
    for state_path, state in amendments:
        if state.get("status") in {"promoting", "needs_attention"}:
            raise RunContextError(f"unsettled runnability amendment: {state_path}")
    if not any(state.get("status") == "promoted" for _, state in amendments):
        return None
    current_ref = _git(root, "rev-parse", f"refs/heads/{intent.spec_id}")
    promoted: dict[str, object] | None = None
    promoted_path: Path | None = None
    for state_path, state in amendments:
        if state.get("status") == "promoted" and state.get("proposed_commit") == current_ref:
            if promoted is not None:
                raise RunContextError("multiple promoted amendments name the current Spec commit")
            promoted, promoted_path = state, state_path
    if promoted is None or promoted_path is None:
        return None
    if (promoted.get("spec_id") != intent.spec_id
            or promoted.get("spec_branch") != intent.spec_id
            or promoted.get("amendment_id")
            != f"{intent.spec_id}/{promoted_path.parent.name}"):
        raise RunContextError("promoted amendment identity differs from current Spec")
    if _git(root, "branch", "--show-current") != intent.spec_id:
        raise RunContextError("active checkout is not the promoted Spec branch")
    old_ref = promoted.get("baseline_commit")
    new_ref = promoted.get("proposed_commit")
    if not isinstance(old_ref, str) or not isinstance(new_ref, str):
        raise RunContextError("promoted amendment has no pinned commits")
    task_path = f"specs/{intent.spec_id}/tasks.md"
    if _git(root, "rev-parse", f"{new_ref}^") != old_ref:
        raise RunContextError("promoted amendment is not a direct child of baseline")
    changed = _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", old_ref, new_ref)
    if changed.splitlines() != [task_path]:
        raise RunContextError("promoted amendment changed files outside tasks.md")
    old_tasks = _published_blob(root, old_ref, task_path)
    new_tasks = _published_blob(root, new_ref, task_path)
    if old_tasks is None or new_tasks is None or _sha256(old_tasks) != promoted.get("old_tasks_sha256"):
        raise RunContextError("promoted amendment old task definition changed")
    paths = promoted.get("target_paths")
    contracts = promoted.get("contract_paths")
    if not isinstance(paths, list) or not isinstance(contracts, list):
        raise RunContextError("promoted amendment target declarations are malformed")
    target_paths = _canonical_targets(root, intent.spec_id, new_ref)
    if list(target_paths) != paths:
        raise RunContextError("promoted amendment target identity changed")
    required = tuple(
        target for target in target_paths
        if (Path(target) / ".echelon/runnability.yml").as_posix() in contracts
    )
    proposals = plan_owner_tasks(old_tasks.decode("utf-8"), old_tasks.decode("utf-8"),
                                 target_paths, required)
    if ([item.task_id for item in proposals] != promoted.get("new_task_ids")
            or [item.contract_path for item in proposals] != contracts
            or render_owner_tasks(old_tasks.decode("utf-8"), proposals).encode("utf-8") != new_tasks
            or [row.task_id for row in parse_task_rows(old_tasks.decode("utf-8"))]
            != promoted.get("old_task_ids")):
        raise RunContextError("promoted amendment altered older task definitions")
    for commit, key in ((old_ref, "published_input_hash"),
                        (new_ref, "proposed_published_hash")):
        contents = {
            name: blob for name in SCOPE_INPUT_FILENAMES
            if (blob := _published_blob(root, commit, f"specs/{intent.spec_id}/{name}"))
            is not None
        }
        if checkpoint_input_hash_from_contents(contents) != promoted.get(key):
            raise RunContextError(f"promoted amendment {key} differs from Git")
    if _git(root, "rev-parse", f":{task_path}") != promoted.get("new_index_blob"):
        raise RunContextError("promoted amendment index entry is unsettled")
    try:
        validate_progress_only(
            new_tasks.decode("utf-8"), (root / task_path).read_text(encoding="utf-8"),
        )
    except ValueError as exc:
        raise RunContextError("amended working plan changed outside Delivery progress") from exc
    journal = promoted_path.parent / "file-publication.json"
    try:
        file_state = json.loads(journal.read_text(encoding="utf-8"))
        if file_state.get("status") != "complete":
            raise ValueError("file publication did not complete")
        PublicationTransaction.from_journal(
            workspace_root=root, staging_root=promoted_path.parent, journal=journal,
        )
    except (OSError, ValueError) as exc:
        raise RunContextError("promoted amendment file publication is unsettled") from exc
    current_hash = checkpoint_input_hash(spec_dir)
    if current_hash is None:
        raise RunContextError("current Spec input hash is unavailable")
    lineage_hash = current_hash
    if current_hash != promoted.get("projected_working_hash"):
        # The CLI sets in_progress before this admission. A published Spec with
        # no status frontmatter gains a new block, which changes the historical
        # checkpoint hash even though only controller-owned lifecycle changed.
        # Reconstruct the pinned preimage, then accept only the exact CLI edit;
        # other scope inputs must still hash to the promoted working plan.
        published_spec = _published_blob(root, old_ref, f"specs/{intent.spec_id}/spec.md")
        if published_spec is None:
            raise RunContextError("promoted amendment published Spec is missing")
        source = published_spec.decode("utf-8")
        possible_preimages = (source, *(
            render_status_markdown(source, status)
            for status in sorted(_LIFECYCLE_STATUSES)
        ))
        preimage = next((item for item in possible_preimages
                         if _sha256(item.encode("utf-8"))
                         == promoted.get("working_spec_sha256")), None)
        current_spec = (spec_dir / "spec.md").read_text(encoding="utf-8")
        if preimage is None or current_spec != render_status_markdown(preimage, "in_progress"):
            raise RunContextError("current Spec input hash differs from promoted amendment")
        contents = {
            name: (spec_dir / name).read_bytes()
            for name in SCOPE_INPUT_FILENAMES
            if (spec_dir / name).is_file()
        }
        contents["spec.md"] = preimage.encode("utf-8")
        lineage_hash = checkpoint_input_hash_from_contents(contents)
        if lineage_hash != promoted.get("projected_working_hash"):
            raise RunContextError("current Spec input hash differs from promoted amendment")
    for target in target_paths:
        resolved = resolve_verification_stacks(root, root / target)
        expected = promoted.get("stack_contracts")
        if (not isinstance(expected, dict)
                or resolved_stack_contract_sha256(resolved) != expected.get(target)):
            raise RunContextError(f"stack contract changed after amendment: {target}")
    configured_target = Path(getattr(config, "target_repo", None) or root)
    target_root = (
        configured_target if configured_target.is_absolute()
        else root / configured_target
    ).resolve()
    try:
        target_id = target_root.relative_to(root).as_posix()
    except ValueError as exc:
        raise RunContextError("Delivery target is outside amended workspace") from exc
    target_info = promoted.get("targets")
    record = target_info.get(target_id) if isinstance(target_info, dict) else None
    if (not isinstance(record, dict)
            or record.get("source_root") != str(target_root)
            or record.get("source_git_root") != _git(target_root, "rev-parse", "--show-toplevel")):
        raise RunContextError("Delivery target repository differs from amendment")
    actual_default: str | None = None
    if (candidate is None and record.get("checkpoint_refs")
            and not getattr(intent, "resume", False)):
        default_branch = getattr(gitops, "get_default_branch", None)
        if not callable(default_branch):
            raise RunContextError("target default branch proof is unavailable")
        actual_default = _git(
            mirror_path(harness_root), "rev-parse", f"refs/heads/{default_branch()}",
        )
    states: list[dict[str, object]] = []
    for path in sorted(runs_dir(harness_root).glob("build-*/state/delivery.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get("spec_id") == intent.spec_id:
            states.append(dict(value, build_id=path.parents[1].name, target_id=target_id))
    identity = {
        "amendment_id": promoted["amendment_id"],
        "spec_commit": new_ref,
        "target_id": target_id,
        "input_hash": current_hash,
    }
    admitted = [state for state in states if state.get("amendment_admission") == identity]
    if getattr(intent, "resume", False):
        if not resume_build_id or not any(
            state.get("build_id") == resume_build_id for state in admitted
        ):
            raise RunContextError("resume build was not admitted under this Spec amendment")
        return _AmendedDeliveryAdmission((), str(promoted["amendment_id"]),
                                         new_ref, target_id, None, current_hash)
    owned_locks = ExitStack()
    locks = handoff_locks if handoff_locks is not None else owned_locks
    try:
        terminal_handoffs: set[tuple[str, str]] = set()
        if isinstance(candidate, str):
            for state in admitted:
                operation = state.get("delivery_slice_operation")
                if (isinstance(operation, dict)
                        and operation.get("kind") == "documentation"
                        and operation.get("progress_applied") is not True):
                    proof = prove_terminal_documentation_handoff(
                        state=state,
                        build_dir=runs_dir(harness_root) / str(state["build_id"]),
                        spec_dir=spec_dir,
                        candidate=candidate,
                        amendment_identity=identity,
                        lock_stack=locks,
                    )
                    if proof is not None:
                        terminal_handoffs.add(proof)
        ancestry = getattr(gitops, "commit_is_ancestor", None)
        if not callable(ancestry):
            raise RunContextError("target Git ancestry check is unavailable")
        try:
            proven = proven_amended_task_ids(
                promoted, target_id=target_id, candidate=candidate,
                current_input_hash=lineage_hash, states=states,
                commit_is_ancestor=ancestry,
                landed_baseline_commit=actual_default,
                allow_descendant=bool(admitted),
                terminal_documentation_handoffs=frozenset(terminal_handoffs),
            )
        except AmendmentLineageError as exc:
            raise RunContextError(str(exc)) from exc
        progress = summarize_task_progress((root / task_path).read_text(encoding="utf-8"))
        if not progress.valid:
            raise RunContextError("amended working task progress is invalid")
        proof_base = candidate or actual_default
        same_hash_proven = _fresh_delivery_completed_tasks(
            harness_root, intent, proof_base, gitops, spec_dir=spec_dir,
        )
        all_proven = tuple(sorted(set(proven) | set(same_hash_proven)))
        target_task_ids = {
            row.task_id for row in parse_task_rows(new_tasks.decode("utf-8"))
            if (row.target or ".") == target_id
        }
        unproven = sorted(
            task_id for task_id in target_task_ids.difference(all_proven)
            if progress.task_statuses.get(task_id) in {"DONE", "DONE_WITH_CONCERNS"}
        )
        if unproven:
            raise RunContextError(
                "unproven task progress: " + ", ".join(unproven)
                + "; recover checkpoint evidence or re-plan the task"
            )
        return _AmendedDeliveryAdmission(all_proven, str(promoted["amendment_id"]),
                                         new_ref, target_id, proof_base, current_hash)
    finally:
        owned_locks.close()


def _fresh_delivery_repair_task_id(
    harness_root: Path,
    intent: Any,
    baseline: str | None,
    gitops: Any | None = None,
    *,
    spec_dir: Path | None = None,
    completed_task_ids: tuple[str, ...] = (),
) -> str | None:
    """Recover the last accepted slice target, never an unreviewed salvage task.

    Checkpoints are ordered within each run; newer run IDs take precedence.
    A candidate on a different lineage or changed spec inputs grants no repair
    target, even if its provider reported a task as done.
    """
    if baseline is None or gitops is None or not completed_task_ids:
        return None
    from harness.task_progress import checkpoint_input_hash

    input_hash = checkpoint_input_hash(spec_dir)
    ancestry = getattr(gitops, "commit_is_ancestor", None)
    if input_hash is None or not callable(ancestry):
        return None
    completed = set(completed_task_ids)
    for state_path in sorted(
        runs_dir(harness_root).glob("build-*/state/delivery.json"), reverse=True,
    ):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(state, dict) or state.get("spec_id") != intent.spec_id:
            continue
        checkpoints = state.get("checkpoint_commits")
        if not isinstance(checkpoints, list):
            continue
        for checkpoint in reversed(checkpoints):
            if not isinstance(checkpoint, dict) or checkpoint.get("checkpoint_input_hash") != input_hash:
                continue
            commit = checkpoint.get("commit")
            task_ids = checkpoint.get("task_ids")
            if (
                not isinstance(commit, str)
                or not re.fullmatch(r"[0-9a-f]{40}", commit)
                or not isinstance(task_ids, list)
                or len(task_ids) != 1
                or not isinstance(task_ids[0], str)
                or task_ids[0] not in completed
            ):
                continue
            try:
                if ancestry(commit, baseline) is True:
                    return task_ids[0]
            except Exception:
                continue
    return None


def _checkpoint_is_landed(gitops: Any | None, commit: str) -> bool:
    """Return whether a prior delivery checkpoint is already on target main."""
    if gitops is None:
        return False
    checker = getattr(gitops, "commit_is_ancestor_of_default", None)
    if not callable(checker):
        return False
    try:
        return checker(commit) is True
    except Exception as error:  # pragma: no cover - defensive: stale recovery must remain available
        logger.warning("Could not inspect stale checkpoint %s: %s", commit[:12], error)
        return False


def _count_tasks(spec_id: str, base_dir: str) -> int:
    """Return count of canonical task rows in tasks.md, or 0 if absent."""
    try:
        from harness.task_validation import count_tasks_for_spec
        return count_tasks_for_spec(spec_id, Path(base_dir))
    except FileNotFoundError:
        return 0


def _fulfillment_gap_recommendation(spec_dir: Path | None) -> str:
    """Read the first deterministic remediation from a verified gaps artifact."""
    if spec_dir is None:
        return ""
    gaps_path = spec_dir / "fulfillment-gaps.md"
    try:
        text = gaps_path.read_text(encoding="utf-8")
    except OSError:
        return ""

    match = re.search(
        r"(?ms)^-\s+\*\*Remediation[^:]*:\*\*\s*(.+?)(?=^\s*$|^##\s|\Z)",
        text,
    )
    if match is None:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _has_fulfillment_gap_failure(result: Any) -> bool:
    verify_result = getattr(result, "final_verify", None)
    return any(
        getattr(failure, "id", "") == "fulfillment-gaps"
        for failure in (getattr(verify_result, "failures", None) or [])
    )


def _should_print_suggested_answers(reason: object, result: Any) -> bool:
    if _has_fulfillment_gap_failure(result):
        return True
    return str(reason or "") == "blocker_escalation"


def _is_provider_limited_summary_row(info: dict[str, Any], result: Any = None) -> bool:
    reason = (
        getattr(result, "termination_reason", None)
        if result is not None
        else info.get("termination_reason")
    )
    return (
        not info.get("converged", False)
        and str(reason or "") == "provider_session_limit"
        and str(info.get("build_status") or "") == "provider_session_limit"
    )


def _json_section(text: str, heading: str) -> dict[str, Any]:
    marker = f"## {heading}"
    start = text.find(marker)
    if start == -1:
        return {}
    fence_start = text.find("```json", start)
    if fence_start == -1:
        return {}
    fence_start += len("```json")
    fence_end = text.find("```", fence_start)
    if fence_end == -1:
        return {}
    try:
        payload = json.loads(text[fence_start:fence_end].strip())
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _suggested_answer_lines(escalation_file: object, spec_id: str) -> list[str]:
    path_text = str(escalation_file or "").strip()
    if not path_text:
        return []
    try:
        text = Path(path_text).read_text(encoding="utf-8")
    except OSError:
        return []
    metadata = _json_section(text, "Decision Metadata")
    suggestions = metadata.get("suggested_answers")
    if not isinstance(suggestions, list):
        return []

    lines = ["suggested answers:"]
    for raw in suggestions:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip()
        answer = str(raw.get("answer") or "").strip()
        consequence = str(raw.get("consequence") or "").strip()
        if not label or not answer:
            continue
        marker = " (recommended)" if bool(raw.get("recommended")) else ""
        safe_answer = answer.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f"- {label}{marker}: echelon delivery resume {spec_id} \"{safe_answer}\"")
        if consequence:
            lines.append(f"  {consequence}")
    return lines if len(lines) > 1 else []


def _verified_ledger_line(info: dict[str, Any]) -> str:
    refresh = info.get("fulfillment_refresh")
    if not isinstance(refresh, dict):
        return ""
    ledger = refresh.get("verified_ledger")
    if not isinstance(ledger, dict):
        return ""
    return (
        "verified ledger: "
        f"reused {int(ledger.get('reused') or 0)}, "
        f"rechecked {int(ledger.get('rechecked') or 0)}, "
        f"invalidated {int(ledger.get('invalidated') or 0)}, "
        f"unresolved {int(ledger.get('unresolved') or 0)}"
    )


def _delivery_summary_facts(
    result: DeliveryResult,
    state: Mapping[str, object],
) -> dict[str, object]:
    return {
        "status": result.status,
        "termination_reason": result.termination_reason,
        "outer_iterations": result.outer_iterations,
        "inner_iterations": result.inner_iterations,
        "tokens_used": result.tokens_used,
        "build_status": state.get("build_status"),
        "provider_limit_message": state.get("provider_limit_message"),
        "completed_task_ids": state.get("completed_task_ids") or [],
    }


def _delivery_run_summary_facts(
    result: DeliveryResult,
    state: Mapping[str, object],
):
    from harness.run_summary import (
        SummaryFact,
        SummaryFactCategory,
        SummaryFactImportance,
    )

    converged = result.status == "converged"
    provider_limited = _is_provider_limited_summary_row(dict(state), result)
    checkpointed = not converged and not provider_limited and (
        result.termination_reason in _CHECKPOINT_REASONS
    )
    outcome = (
        "converged"
        if converged
        else "provider-limited"
        if provider_limited
        else "checkpointed"
        if checkpointed
        else "failed"
    )
    facts = [
        SummaryFact(
            SummaryFactCategory.OUTCOME,
            SummaryFactImportance.HIGH,
            f"Delivery finished {outcome}.",
            0,
        )
    ]
    if converged:
        category = SummaryFactCategory.WORK
        importance = SummaryFactImportance.HIGH
        text = "Delivery converged successfully."
    elif provider_limited or checkpointed:
        category = SummaryFactCategory.HANDOFF
        importance = SummaryFactImportance.HIGH
        text = "Prepared delivery for durable continuation."
    else:
        category = SummaryFactCategory.BLOCKER
        importance = SummaryFactImportance.CRITICAL
        text = "Delivery stopped before convergence."
    facts.append(SummaryFact(category, importance, text, len(facts)))
    verification = result.final_verify
    if verification is not None:
        verdict = "passed" if verification.passed else "failed"
        facts.append(
            SummaryFact(
                SummaryFactCategory.VERIFICATION,
                SummaryFactImportance.HIGH,
                f"Delivery verification {verdict}.",
                len(facts),
            )
        )
    return tuple(facts)


def _print_delivery_summary(
    intent: Any,
    result: DeliveryResult,
    state: Mapping[str, object],
    workspace_root: Path,
    spec_dir: Path | None,
    config: Any = None,
    landing: LandingOutcome | None = None,
    summary_command: str = "echelon delivery run",
) -> None:
    """Print a structured delivery summary to stderr."""
    from echelon.ui import banner as _banner

    scope = _ACTIVE_DELIVERY_SUMMARY.get()
    if scope is not None:
        if scope.emitted:
            return

    task_count = _count_tasks(intent.spec_id, str(workspace_root))
    task_note = f"  ({task_count} tasks)" if task_count else ""
    target_repo = getattr(config, "target_repo", None) if config is not None else None
    fulfillment_recommendation = _fulfillment_gap_recommendation(spec_dir)

    fields: list[tuple[str, str]] = [("spec", f"{intent.spec_id}{task_note}")]
    if target_repo:
        fields.append(("target", target_repo))
    fields.append(("mode", str(intent.mode)))

    info = dict(state)
    converged = result.status == "converged"
    reason = result.termination_reason
    provider_limited = _is_provider_limited_summary_row(info, result)
    checkpointed = not converged and reason in _CHECKPOINT_REASONS and not provider_limited
    if converged:
        status_icon, status_str = "✓", "CONVERGED"
    elif provider_limited:
        status_icon, status_str = "◐", "PROVIDER SESSION LIMIT"
    elif checkpointed:
        status_icon, status_str = "◐", "CHECKPOINTED"
    else:
        status_icon, status_str = "✗", result.status.upper()
    outer = result.outer_iterations
    inner = result.inner_iterations
    branch = result.branch or state.get("branch") or f"harness/{intent.spec_id}/iter-{max(outer - 1, 0)}"
    pr_url = state.get("pr_url") or result.pr_url
    lines = [
        f"{status_icon} {status_str}",
        f"branch: {branch}",
        f"PR: {pr_url}" if pr_url else "PR: not created (gh/glab unavailable or pr_host unset)",
        f"iterations: {outer} outer, {inner} inner retries",
    ]
    convergence = state.get("convergence_lease")
    if isinstance(convergence, Mapping):
        from harness.convergence import DEFAULT_STALL_PATIENCE

        meaningful = int(convergence.get("meaningful_attempts") or 0)
        ceiling = int(state.get("max_outer") or intent.max_outer)
        stalled = int(convergence.get("stalled_attempts") or 0)
        infrastructure = int(convergence.get("infrastructure_attempts") or 0)
        lines.extend(
            [
                f"meaningful attempts: {meaningful}/{ceiling}",
                f"stall patience: {stalled}/{DEFAULT_STALL_PATIENCE}",
                f"excluded infrastructure attempts: {infrastructure}",
            ]
        )
        outcome = str(convergence.get("last_outcome") or "").strip()
        outcome_reason = str(convergence.get("last_reason") or "").strip()
        if outcome:
            lines.append(
                "convergence: "
                + (f"{outcome}: {outcome_reason}" if outcome_reason else outcome)
            )
        best_checkpoint = str(convergence.get("best_checkpoint_commit") or "").strip()
        if best_checkpoint:
            lines.append(f"best checkpoint: {best_checkpoint[:12]}")
    if reason and reason != "converged":
        if provider_limited:
            lines.append("stopped: provider session limit")
            for key, label in (
                ("provider_limit_message", "provider"),
                ("provider_reset_hint", "reset"),
                ("salvage_branch", "salvage branch"),
                ("salvage_verified", "salvage verified"),
            ):
                value = str(state.get(key) or "").strip()
                if value:
                    lines.append(f"{label}: {value}")
            salvage_commit = str(state.get("salvage_commit") or "").strip()
            if salvage_commit:
                lines.append(f"salvage commit: {salvage_commit[:12]}")
            lines.append(f"continue: echelon delivery continue {intent.spec_id}")
        elif checkpointed:
            stopped = (
                "checkpoint continuation needed"
                if reason == "checkpoint_outer_cap"
                else "checkpoint recovery needed"
            )
            lines.append(f"stopped: {stopped}")
            lines.append(f"continue: echelon delivery continue {intent.spec_id}")
        else:
            lines.append(f"stopped: {reason}")
            if reason == "outer_cap":
                lines.append(
                    f"next: echelon delivery run {intent.spec_id}  "
                    "# continue with a fresh outer-loop budget"
                )
        if reason == "publish_failed":
            failure = state.get("publication_failure")
            if isinstance(failure, Mapping):
                stage = str(failure.get("stage") or "publication")
                error = str(failure.get("error") or "unknown error")
                lines.append(f"publish failure: {stage}: {error}")
    fv = result.final_verify
    if fv is not None:
        duration = f"  ({fv.duration_s:.1f}s)" if fv.duration_s else ""
        if not fv.passed and fv.verification_evidence.get("passed") is True:
            lines.append("candidate sandbox: ✓ passed")
        deferred = (
            reason == "checkpoint_outer_cap"
            and not fv.passed
            and any(
                getattr(failure, "id", "") == "fulfillment-refresh-deferred"
                for failure in (fv.failures or [])
            )
        )
        if deferred:
            lines.append(f"verify: deferred{duration}")
        else:
            v_icon = "✓" if fv.passed else "✗"
            lines.append(f"verify: {v_icon} {'passed' if fv.passed else 'FAILED'}{duration}")
        for failure in (fv.failures or []):
            prefix = "deferred" if deferred else "✗"
            lines.append(f"        {prefix} [{failure.category.value}] {failure.error}")
    else:
        lines.append("verify: not completed")
    if fulfillment_recommendation and _has_fulfillment_gap_failure(result):
        lines.append(f"recommended action: {fulfillment_recommendation}")
    verified_ledger = _verified_ledger_line(info)
    if verified_ledger:
        lines.append(verified_ledger)
    if _should_print_suggested_answers(reason, result):
        lines.extend(_suggested_answer_lines(state.get("escalation_file"), intent.spec_id))
    fields.append(("delivery", "\n".join(lines)))

    outcome = (
        "converged"
        if converged
        else "provider-limited"
        if provider_limited
        else "checkpointed"
        if checkpointed
        else "failed"
    )
    if result.tokens_used:
        outcome += f"  ·  {result.tokens_used:,} tokens"
    fields.append(("outcome", outcome))
    provider_limit_message = (
        str(state.get("provider_limit_message") or "").strip()
        if provider_limited
        else ""
    )
    if provider_limited and not provider_limit_message:
        provider_limit_message = "Delivery reached its provider limit"
    if provider_limit_message:
        fields.append(("provider limit", provider_limit_message))
    next_step = ""
    if checkpointed or provider_limited:
        next_step = f"echelon delivery continue {intent.spec_id}"
    elif not converged:
        next_step = f"echelon delivery run {intent.spec_id}"
    elif landing is None or landing.status != "landed":
        next_step = f"echelon delivery land {intent.spec_id}"
    if landing is not None:
        landing_text = landing.status
        if landing.reason:
            landing_text += f" ({landing.reason})"
        fields.append(("landing", landing_text))

    if not os.environ.get("ECHELON_SUPPRESS_RUN_SUMMARY"):
        from harness.run_summary import RunSummaryContext, summarize_run_for_cli

        worked_on = summarize_run_for_cli(
            RunSummaryContext(
                project_root=workspace_root,
                command=summary_command,
                task=str(
                    getattr(intent, "task_description", "")
                    or f"Deliver spec {intent.spec_id}"
                ),
                status=(
                    "done"
                    if converged
                    else "blocked"
                ),
                facts=_delivery_run_summary_facts(result, state),
                next_step=next_step,
                provider_limit_message=provider_limit_message,
            )
        )
        fields.append(("worked on", worked_on))
        if next_step:
            fields.append(("next", next_step))

    _banner("DELIVERY SUMMARY", fields, file=sys.stderr)
    if scope is not None:
        scope.emitted = True


def _print_delivery_exception_summary(
    intent: Any,
    harness_root: Path,
    workspace_root: Path,
    spec_dir: Path | None,
    *,
    config: Any,
    summary_command: str,
) -> None:
    """Render the durable command handoff without masking its exception."""

    def durable_counter(value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    state: dict[str, object] = {}
    try:
        build_id = current_build_marker(
            harness_root,
            str(intent.spec_id),
        ).read_text(encoding="utf-8").strip()
        state_path = runs_dir(harness_root) / build_id / "state" / "delivery.json"
        value = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            state = value
    except (OSError, ValueError, json.JSONDecodeError):
        state = {}
    reason = str(
        state.get("termination_reason")
        or state.get("blocked_reason")
        or "controller_exception"
    )
    result = DeliveryResult(
        status="blocked",
        termination_reason=reason,
        outer_iterations=durable_counter(
            state.get("outer_iter") or state.get("outer_iteration")
        ),
        inner_iterations=durable_counter(
            state.get("inner_iter") or state.get("inner_iteration")
        ),
        pr_url=str(state.get("pr_url") or "") or None,
        tokens_used=durable_counter(state.get("tokens_used")),
        final_verify=None,
        blocked_phase=(
            str(state.get("blocked_phase"))
            if state.get("blocked_phase")
            in {"implementation", "visual", "review", "finalization"}
            else "implementation"
        ),
        branch=str(state.get("branch") or "") or None,
    )
    _print_delivery_summary(
        intent,
        result,
        state,
        workspace_root,
        spec_dir,
        config,
        LandingOutcome("not_requested"),
        summary_command,
    )


@contextmanager
def _delivery_summary_session(scope: _DeliverySummaryScope):
    active = _ACTIVE_DELIVERY_SUMMARY.get()
    if active is not None:
        yield active
        return
    token = _ACTIVE_DELIVERY_SUMMARY.set(scope)
    try:
        yield scope
    finally:
        try:
            if not scope.emitted:
                _print_delivery_exception_summary(
                    scope.intent,
                    scope.harness_root,
                    scope.workspace_root,
                    scope.spec_dir,
                    config=scope.config,
                    summary_command=scope.summary_command,
                )
        except BaseException:
            pass
        finally:
            _ACTIVE_DELIVERY_SUMMARY.reset(token)


def _print_harness_history_summary(
    *,
    spec_dir: Path | None,
    title: str,
) -> None:
    if spec_dir is None:
        return
    summary = summarize_history(spec_dir)
    recent = summary.get("recent", [])
    if not recent:
        return

    fields: list[tuple[str, str]] = []
    for row in recent:
        if not isinstance(row, dict):
            continue
        build_id = str(row.get("build_id") or "?")
        short_build = build_id.replace("build-", "")
        status = str(row.get("status") or "?")
        reason = str(row.get("termination_reason") or "?")
        tokens = int(row.get("tokens_used") or 0)
        fields.append(
            (
                short_build,
                f"{status}  |  {reason}  |  {tokens:,} tokens",
            )
        )
    if not fields:
        return

    subtitle = f"{summary['count']} runs tracked · {summary['total_tokens']:,} tokens total"
    from echelon.ui import banner as _banner
    _banner(title, fields, subtitle=subtitle, file=sys.stderr)


def _append_harness_history(
    *,
    spec_dir: Path | None,
    spec_id: str,
    build_id: str,
    mode: str,
    result: DeliveryResult,
    state: Mapping[str, object],
) -> None:
    if spec_dir is None:
        return
    append_run(
        spec_dir,
        spec_id=spec_id,
        build_id=build_id,
        mode=mode,
        result=result,
        pr_url=str(state.get("pr_url") or result.pr_url or "") or None,
        started_at=str(state.get("started_at") or "") or None,
    )


def _execute_delivery_run(
    *,
    intent: Any,
    provider: Any,
    gitops: Any,
    harness_root: Path,
    workspace_root: Path,
    spec_dir: Path | None,
    config: Any,
    resume_build_id: str | None,
    summary_command: str,
) -> DeliveryRunOutcome:
    """Serialize native admission and its controller for one target root."""
    try:
        with target_delivery_execution_lease(harness_root):
            return _execute_delivery_run_locked(
                intent=intent, provider=provider, gitops=gitops,
                harness_root=harness_root, workspace_root=workspace_root,
                spec_dir=spec_dir, config=config, resume_build_id=resume_build_id,
                summary_command=summary_command,
            )
    except DeliveryExecutionLocked as exc:
        raise RunContextError(str(exc)) from exc


def _execute_delivery_run_locked(
    *,
    intent: Any,
    provider: Any,
    gitops: Any,
    harness_root: Path,
    workspace_root: Path,
    spec_dir: Path | None,
    config: Any,
    resume_build_id: str | None,
    summary_command: str,
) -> DeliveryRunOutcome:
    """Execute one already-identified delivery command inside its summary scope."""

    # The CLI reserves a new build directory before this adapter runs and passes
    # that ID here.  A build ID therefore does not itself mean "resume"; intent
    # is the authority for whether a prior checkpoint must be retained.
    with ExitStack() as admission_locks:
        fresh_branch_base = (
            None
            if getattr(intent, "resume", False)
            else _fresh_delivery_baseline(harness_root, intent, gitops)
        )
        amended_completed = _amended_delivery_completed_tasks(
            workspace_root=workspace_root,
            harness_root=harness_root,
            spec_dir=spec_dir,
            intent=intent,
            candidate=fresh_branch_base,
            gitops=gitops,
            config=config,
            resume_build_id=resume_build_id,
            handoff_locks=admission_locks,
        )
        fresh_completed_task_ids = (
            amended_completed.task_ids if amended_completed is not None
            else _fresh_delivery_completed_tasks(
                harness_root,
                intent,
                fresh_branch_base,
                gitops,
                spec_dir=spec_dir,
            )
        )
        fresh_repair_task_id = _fresh_delivery_repair_task_id(
            harness_root,
            intent,
            fresh_branch_base,
            gitops,
            spec_dir=spec_dir,
            completed_task_ids=fresh_completed_task_ids,
        )
        build_id = resume_build_id or make_build_id()
        rd = runs_dir(harness_root)
        rd.mkdir(parents=True, exist_ok=True)
        current_build_marker(harness_root, intent.spec_id).write_text(build_id)
    logger.info("Build ID: %s", build_id)

    controller = DeliveryController(
        provider=provider,
        gitops=gitops,
        config=config,
        base_dir=harness_root,
        build_id=build_id,
        orchestration_root=workspace_root,
        fresh_branch_base=fresh_branch_base,
        fresh_completed_task_ids=fresh_completed_task_ids,
        fresh_repair_task_id=fresh_repair_task_id,
        amendment_admission=(
            amended_completed.durable_identity() if amended_completed is not None else None
        ),
    )
    if fresh_branch_base:
        logger.info(
            "Starting new delivery budget from retained delivery candidate: %s",
            fresh_branch_base[:12],
        )
    try:
        run_gc(config, base_dir=str(harness_root))
    except Exception as exc:
        logger.warning("GC failed (continuing): %s", exc)

    _print_harness_history_summary(spec_dir=spec_dir, title="HARNESS HISTORY")
    result = controller.run(intent)
    state = controller.state()
    _append_harness_history(
        spec_dir=spec_dir,
        spec_id=intent.spec_id,
        build_id=build_id,
        mode=intent.mode,
        result=result,
        state=state,
    )
    _print_harness_history_summary(spec_dir=spec_dir, title="HARNESS HISTORY")

    landing = LandingOutcome("not_requested")
    converged = result.status == "converged"
    if intent.auto_merge and converged:
        targets = read_targets(spec_dir) if spec_dir is not None else []
        if len(targets) > 1:
            logger.warning(
                "auto-land skipped for spec %s: aggregate multi-target landing is "
                "unsupported (%d targets)",
                intent.spec_id,
                len(targets),
            )
            landing = LandingOutcome("skipped", "multi_target")
        else:
            from harness.land import land

            try:
                landed = land(
                    intent.spec_id,
                    project_dir=workspace_root,
                    gitops=gitops,
                    harness_root=harness_root,
                )
                if landed:
                    print("  Auto-landed successfully!", file=sys.stderr)
                    landing = LandingOutcome("landed")
                else:
                    logger.warning(
                        "auto-land: land() returned False for spec %s",
                        intent.spec_id,
                    )
                    landing = LandingOutcome("blocked", "land_returned_false")
            except Exception as exc:
                logger.warning(
                    "auto-land: land() raised for spec %s: %s",
                    intent.spec_id,
                    exc,
                )
                landing = LandingOutcome("blocked", "land_exception")

    _print_delivery_summary(
        intent,
        result,
        state,
        workspace_root,
        spec_dir,
        config,
        landing,
        summary_command,
    )
    return DeliveryRunOutcome(results=(result,), landing=landing)


def run(
    user_message: str,
    provider: Any,
    gitops: Any,
    base_dir: str = ".",
    config: Any = None,
    resume_build_id: str | None = None,
    orchestration_root: str | Path | None = None,
    summary_command: str = "echelon delivery run",
    reconcile_unknown_dispatch: bool = False,
) -> DeliveryRunOutcome:
    """Execute an Echelon delivery run.

    Args:
        user_message: Natural-language run request.
        provider: SandboxProvider instance.
        gitops: GitOpsManager instance.
        base_dir: Base directory for harness state.
        resume_build_id: Existing build id to continue, when resuming.
        orchestration_root: Workspace that owns canonical specs and history.
    """
    harness_root, workspace_root = _resolve_run_roots(base_dir, orchestration_root)

    # 1. Parse intent
    intent = parse_intent(user_message)
    if reconcile_unknown_dispatch and not intent.resume:
        raise RunContextError("unknown dispatch reconciliation requires explicit continuation")
    intent.reconcile_unknown_dispatch = reconcile_unknown_dispatch
    logger.info("Parsed run intent: spec=%s, mode=%s", intent.spec_id, intent.mode)

    spec_dir = find_spec_dir(intent.spec_id, workspace_root)
    if orchestration_root is not None and spec_dir is None:
        raise RunContextError(
            f"spec directory for {intent.spec_id} was not found from "
            f"orchestration root {workspace_root}"
        )

    scope = _DeliverySummaryScope(
        intent=intent,
        harness_root=harness_root,
        workspace_root=workspace_root,
        spec_dir=spec_dir,
        config=config,
        summary_command=summary_command,
    )
    with _delivery_summary_session(scope):
        # Load config only after the valid run identity is inside emit-once scope.
        config = config or load_config()
        scope.config = config
        return _execute_delivery_run(
            intent=intent,
            provider=provider,
            gitops=gitops,
            harness_root=harness_root,
            workspace_root=workspace_root,
            spec_dir=spec_dir,
            config=config,
            resume_build_id=resume_build_id,
            summary_command=summary_command,
        )
