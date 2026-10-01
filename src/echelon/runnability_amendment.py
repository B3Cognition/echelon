"""Typed, isolated correction of a published Spec's runnability owner."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Any

from echelon.spec_amendment import (
    AmendmentLock,
    _amendment_state_path,
    _next_revision,
    create_amendment_worktree,
    resolve_control_baseline,
)
from echelon.spec_lifecycle import PhaseAExecutionLock, active_phase_a_execution_owner
from harness.durable_json import write_json_atomic
from harness.fulfillment_runner import SCOPE_INPUT_FILENAMES
from harness.runnability_amendment_plan import (
    plan_owner_tasks,
    project_progress,
    render_owner_tasks,
)
from harness.runnability_disposition import read_runnability_disposition
from harness.spec_frontmatter import (
    read_canonical_target_entries,
    read_frontmatter,
    render_status_markdown,
    spec_content_ignoring_status,
)
from harness.stacks.resolver import resolved_stack_contract_sha256
from harness.task_progress import checkpoint_input_hash_from_contents
from kernel.task_contract import parse_task_rows
from harness.verification_stack_runtime import resolve_verification_stacks


class RunnabilityAmendmentError(ValueError):
    """The typed published-plan correction cannot be prepared safely."""


_LIFECYCLE_STATUSES = frozenset({"in_progress", "ready_to_land", "landed"})


@dataclass(frozen=True)
class _Preview:
    public: dict[str, object]
    published_tasks: str
    working_tasks: str
    proposed_tasks: str
    projected_working_tasks: str


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise RunnabilityAmendmentError(
            f"git {' '.join(args)} failed: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _published_blob(root: Path, commit: str, relative: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=root, capture_output=True, check=False,
    )
    if result.returncode:
        return None
    return result.stdout


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _verified_scope_inputs(
    root: Path,
    spec_id: str,
    commit: str,
) -> tuple[dict[str, bytes], dict[str, bytes]]:
    spec_dir = root / "specs" / spec_id
    published = {
        name: blob
        for name in SCOPE_INPUT_FILENAMES
        if (blob := _published_blob(root, commit, f"specs/{spec_id}/{name}")) is not None
    }
    working = {
        name: (spec_dir / name).read_bytes()
        for name in SCOPE_INPUT_FILENAMES
        if (spec_dir / name).is_file()
    }
    if "spec.md" not in published or "tasks.md" not in published:
        raise RunnabilityAmendmentError("published spec is missing spec.md or tasks.md")
    if "spec.md" not in working or "tasks.md" not in working:
        raise RunnabilityAmendmentError("working spec is missing spec.md or tasks.md")
    for name in SCOPE_INPUT_FILENAMES:
        if name in {"spec.md", "tasks.md"}:
            continue
        if published.get(name) != working.get(name):
            raise RunnabilityAmendmentError(f"unrecognized working input edit: {name}")
    published_spec = published["spec.md"].decode("utf-8")
    working_spec = working["spec.md"].decode("utf-8")
    if published_spec != working_spec:
        status = read_frontmatter(spec_dir).get("status")
        if (
            not isinstance(status, str)
            or status not in _LIFECYCLE_STATUSES
            or spec_content_ignoring_status(working_spec) is None
            or render_status_markdown(published_spec, status) != working_spec
        ):
            raise RunnabilityAmendmentError("unrecognized working spec lifecycle edit")
    return published, working


def _canonical_targets(root: Path, spec_id: str, commit: str) -> tuple[str, ...]:
    spec_dir = root / "specs" / spec_id
    published_targets = _published_blob(root, commit, f"specs/{spec_id}/targets.yml")
    working_targets_path = spec_dir / "targets.yml"
    working_targets = working_targets_path.read_bytes() if working_targets_path.is_file() else None
    if published_targets != working_targets:
        raise RunnabilityAmendmentError("canonical targets changed after publication")
    entries = read_canonical_target_entries(spec_dir, strict=True)
    if working_targets is not None and not entries:
        raise RunnabilityAmendmentError("targets.yml declares no valid targets")
    paths = tuple(str(entry["path"]) for entry in entries) or (".",)
    for target in paths:
        candidate = (root / target).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise RunnabilityAmendmentError(f"target escapes workspace: {target}") from exc
        if not candidate.is_dir():
            raise RunnabilityAmendmentError(f"target directory is absent: {target}")
    return paths


def _deferred_target(root: Path, spec_dir: Path, targets: tuple[str, ...]) -> str | None:
    disposition = read_runnability_disposition(spec_dir)
    if disposition is None or disposition.status != "deferred":
        return None
    matches = [
        target for target in targets
        if disposition.target in ({target, (root / target).name}
                                  | ({"workspace"} if target == "." else set()))
    ]
    if len(matches) != 1:
        raise RunnabilityAmendmentError("runnability deferral target is ambiguous or missing")
    return matches[0]


def _target_evidence(root: Path, spec_id: str, target: str) -> dict[str, object]:
    from harness.config import load_config
    from harness.gitops import GitOpsManager
    from harness.paths import mirror_path, runs_dir
    from harness.skills.run_skill import _fresh_delivery_baseline

    target_root = (root / target).resolve()
    source_git_root = _git(target_root, "rev-parse", "--show-toplevel")
    harness_root = root / "runs" / "targets" / target_root.name
    candidate: str | None = None
    gitops = None
    if mirror_path(harness_root).exists():
        config = load_config(project_root=root, squad_only=True)
        config.target_repo = str(target_root)
        gitops = GitOpsManager(config, base_dir=str(harness_root))
    # A clean worktree does not imply that a sealed Delivery operation has
    # settled. Do this before native baseline selection, which may otherwise
    # retain the candidate and allow publication over its original Spec input.
    for state_path in sorted(runs_dir(harness_root).glob("build-*/state/delivery.json")):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (isinstance(state, dict) and state.get("spec_id") == spec_id
                and isinstance(state.get("delivery_slice_operation"), dict)
                and state["delivery_slice_operation"].get("progress_applied") is not True):
            raise RunnabilityAmendmentError(
                f"pending Delivery operation must settle before amendment: {state_path}"
            )
    intent = SimpleNamespace(spec_id=spec_id, reset=False, resume=False)
    candidate = _fresh_delivery_baseline(harness_root, intent, gitops)
    checkpoint_refs: list[dict[str, object]] = []
    for state_path in sorted(runs_dir(harness_root).glob("build-*/state/delivery.json")):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(state, dict) or state.get("spec_id") != spec_id:
            continue
        for checkpoint in state.get("checkpoint_commits") or []:
            if isinstance(checkpoint, dict) and isinstance(checkpoint.get("commit"), str):
                checkpoint_refs.append({
                    "build_id": state_path.parents[1].name,
                    "commit": checkpoint["commit"],
                    "checkpoint_input_hash": checkpoint.get("checkpoint_input_hash"),
                    "task_ids": checkpoint.get("task_ids"),
                })
    landed_baseline = None
    if candidate is None and checkpoint_refs and gitops is not None:
        landed_baseline = _git(
            mirror_path(harness_root), "rev-parse",
            f"refs/heads/{gitops.get_default_branch()}",
        )
    return {
        "target_path": target,
        "source_root": str(target_root),
        "source_git_root": source_git_root,
        "candidate_commit": candidate,
        "landed_baseline_commit": landed_baseline,
        "checkpoint_refs": checkpoint_refs,
    }


def _reject_pending_spec_step(root: Path, spec_id: str) -> None:
    for state_path in (root / "runs").glob("spec-*/state.json"):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (isinstance(state, dict) and state.get("spec_id") == spec_id
                and state.get("pending_spec_step") is not None):
            raise RunnabilityAmendmentError(
                f"pending Spec step must settle before amendment: {state_path}"
            )


def _build_preview(
    project_root: Path, spec_id: str, *, check_phase_a_owner: bool = True,
) -> _Preview:
    root = Path(project_root).resolve()
    baseline = resolve_control_baseline(root, spec_id)
    if baseline.used_default_branch or baseline.branch != spec_id:
        raise RunnabilityAmendmentError("published spec branch is required")
    if _git(root, "branch", "--show-current") != spec_id:
        raise RunnabilityAmendmentError("active checkout is not the published spec branch")
    if check_phase_a_owner and active_phase_a_execution_owner(root) is not None:
        raise RunnabilityAmendmentError("active Spec execution must finish first")
    _reject_pending_spec_step(root, spec_id)
    spec_dir = root / "specs" / spec_id
    published, working = _verified_scope_inputs(root, spec_id, baseline.commit)
    targets = _canonical_targets(root, spec_id, baseline.commit)
    deferred = _deferred_target(root, spec_dir, targets)
    required: list[str] = []
    stack_contracts: dict[str, str] = {}
    for target in targets:
        resolved = resolve_verification_stacks(root, root / target)
        if not resolved.selected_ids:
            raise RunnabilityAmendmentError(f"stack_selection_required: {target}")
        if not set(resolved.resolved_ids).difference({"generic"}):
            raise RunnabilityAmendmentError(f"stack_capabilities_unresolved: {target}")
        stack_contracts[target] = resolved_stack_contract_sha256(resolved)
        if resolved.runnability.policy == "required" and target != deferred:
            required.append(target)
    published_tasks = published["tasks.md"].decode("utf-8")
    working_tasks = working["tasks.md"].decode("utf-8")
    proposals = plan_owner_tasks(published_tasks, working_tasks, targets, tuple(required))
    proposed_tasks = (
        render_owner_tasks(published_tasks, proposals) if proposals else published_tasks
    )
    projected_working_tasks = (
        project_progress(published_tasks, working_tasks, proposed_tasks)
        if proposals else working_tasks
    )
    proposed_published = dict(published, **{"tasks.md": proposed_tasks.encode("utf-8")})
    projected_working = dict(working, **{"tasks.md": projected_working_tasks.encode("utf-8")})
    target_evidence = {
        target: _target_evidence(root, spec_id, target) for target in targets
    }
    public: dict[str, object] = {
        "schema_version": 1,
        "kind": "runnability_owner",
        "status": "proposed" if proposals else "no_change",
        "spec_id": spec_id,
        "spec_branch": baseline.branch,
        "baseline_commit": baseline.commit,
        "new_task_ids": [item.task_id for item in proposals],
        "old_task_ids": [row.task_id for row in parse_task_rows(published_tasks)],
        "contract_paths": [item.contract_path for item in proposals],
        "target_paths": list(targets),
        "stack_contracts": stack_contracts,
        "targets": target_evidence,
        "published_input_hash": checkpoint_input_hash_from_contents(published),
        "pre_amendment_working_hash": checkpoint_input_hash_from_contents(working),
        "proposed_published_hash": checkpoint_input_hash_from_contents(proposed_published),
        "projected_working_hash": checkpoint_input_hash_from_contents(projected_working),
        "old_tasks_sha256": _sha256(published["tasks.md"]),
        "working_preimage_sha256": _sha256(working["tasks.md"]),
        "working_projected_sha256": _sha256(projected_working["tasks.md"]),
        "working_spec_sha256": _sha256(working["spec.md"]),
    }
    return _Preview(public, published_tasks, working_tasks, proposed_tasks,
                    projected_working_tasks)


def preview_runnability_owner(project_root: Path, spec_id: str) -> dict[str, object]:
    """Inspect one published-plan correction without allocating mutable state."""
    return _build_preview(project_root, spec_id).public


def prepare_runnability_owner(project_root: Path, spec_id: str) -> dict[str, object]:
    """Commit an isolated correction proposal while keeping canonical work intact."""
    root = Path(project_root).resolve()
    owner = f"runnability-owner-{spec_id}"
    with AmendmentLock.acquire(root, spec_id, owner):
        with PhaseAExecutionLock.acquire(root, owner):
            # The owner above is our own lease; preview's external-owner check
            # is performed before taking it, then all inputs are re-read under lock.
            preview = _build_preview(root, spec_id, check_phase_a_owner=False)
            if not preview.public["new_task_ids"]:
                return preview.public
            baseline = resolve_control_baseline(root, spec_id)
            revision = _next_revision(root, spec_id)
            amendment_id = f"{spec_id}/{revision:03d}"
            worktree = create_amendment_worktree(root, baseline, revision=revision)
            state_path = _amendment_state_path(root, spec_id, revision)
            try:
                tasks_path = worktree.path / "specs" / spec_id / "tasks.md"
                tasks_path.write_text(preview.proposed_tasks, encoding="utf-8")
                _git(worktree.path, "add", f"specs/{spec_id}/tasks.md")
                _git(worktree.path, "commit", "-m", "Plan required runnability contract owner")
                proposed_commit = _git(worktree.path, "rev-parse", "HEAD")
                state: dict[str, object] = {
                    **preview.public,
                    "amendment_id": amendment_id,
                    "status": "prepared",
                    "proposed_commit": proposed_commit,
                    "worktree_path": str(worktree.path),
                    "state_path": str(state_path),
                }
                state_path.parent.mkdir(parents=True, exist_ok=True)
                write_json_atomic(state_path, state)
                return state
            except Exception:
                state_path.unlink(missing_ok=True)
                if state_path.parent.is_dir():
                    state_path.parent.rmdir()
                _git(root, "worktree", "remove", "--force", str(worktree.path))
                _git(root, "branch", "-D", worktree.branch)
                raise


def promote_runnability_owner(
    project_root: Path, amendment_id: str,
) -> dict[str, object]:
    """Delegate promotion to the amendment-owned recoverable transaction."""
    from echelon.runnability_amendment_transaction import promote_runnability_owner as promote

    return promote(project_root, amendment_id)
