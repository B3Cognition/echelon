"""Recoverable publication of a prepared runnability-owner plan amendment.

The branch ref is the commit point. The file transaction owns only tasks.md;
the index update owns only that entry. Unrelated staged or working files are
never reset or checked out.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
from typing import Callable

from echelon.spec_amendment import AmendmentLock, _amendment_state_path
from echelon.spec_lifecycle import PhaseAExecutionLock
from harness.durable_json import write_json_atomic
from harness.publication_transaction import (
    PublicationOperation,
    PublicationTransaction,
    apply_publication_transaction,
    rollback_publication_transaction,
)

from echelon.runnability_amendment import (
    RunnabilityAmendmentError,
    _build_preview,
    _git,
    _published_blob,
    _sha256,
)


_AMENDMENT_ID = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)/([0-9]{3,})\Z")
_PINNED_FIELDS = (
    "baseline_commit", "new_task_ids", "contract_paths", "target_paths",
    "stack_contracts", "targets", "published_input_hash",
    "pre_amendment_working_hash", "proposed_published_hash",
    "projected_working_hash", "old_tasks_sha256",
    "working_preimage_sha256", "working_projected_sha256",
    "working_spec_sha256",
)


def _load(root: Path, amendment_id: str) -> tuple[Path, dict[str, object], str]:
    match = _AMENDMENT_ID.fullmatch(amendment_id)
    if match is None:
        raise RunnabilityAmendmentError("invalid runnability amendment ID")
    spec_id, revision = match.group(1), int(match.group(2))
    path = _amendment_state_path(root, spec_id, revision)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnabilityAmendmentError("runnability amendment state is missing or malformed") from exc
    if (not isinstance(state, dict) or state.get("kind") != "runnability_owner"
            or state.get("amendment_id") != amendment_id
            or state.get("spec_id") != spec_id):
        raise RunnabilityAmendmentError("runnability amendment state identity mismatch")
    return path, state, spec_id


def _save(path: Path, state: dict[str, object], *, status: str, phase: str) -> None:
    state["status"] = status
    state["promotion_phase"] = phase
    write_json_atomic(path, state)


def _task_path(spec_id: str) -> str:
    return f"specs/{spec_id}/tasks.md"


def _sha_file(path: Path) -> str:
    return _sha256(path.read_bytes())


def _index_blob(root: Path, task_path: str) -> str:
    return _git(root, "rev-parse", f":{task_path}")


def _publication(root: Path, state_path: Path, spec_id: str, *, recover: bool) -> PublicationTransaction:
    journal = state_path.parent / "file-publication.json"
    if recover:
        return PublicationTransaction.from_journal(
            workspace_root=root, staging_root=state_path.parent, journal=journal,
        )
    return PublicationTransaction(
        workspace_root=root,
        staging_root=state_path.parent,
        journal=journal,
        operations=(PublicationOperation(
            PurePosixPath(_task_path(spec_id)), PurePosixPath("staged/tasks.md"),
        ),),
    )


def _verify_prepared(
    root: Path, state: dict[str, object], spec_id: str,
) -> tuple[bytes, str, str]:
    task_path = _task_path(spec_id)
    old_ref = state.get("baseline_commit")
    new_ref = state.get("proposed_commit")
    if not isinstance(old_ref, str) or not isinstance(new_ref, str):
        raise RunnabilityAmendmentError("amendment commit identity is missing")
    if _git(root, "branch", "--show-current") != spec_id:
        raise RunnabilityAmendmentError("active branch is not the amended spec branch")
    if _git(root, "rev-parse", f"refs/heads/{spec_id}") != old_ref:
        raise RunnabilityAmendmentError("spec branch advanced before promotion")
    if _git(root, "rev-parse", f"{new_ref}^") != old_ref:
        raise RunnabilityAmendmentError("proposed commit is not a direct child of baseline")
    changed = _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", old_ref, new_ref)
    if changed.splitlines() != [task_path]:
        raise RunnabilityAmendmentError("proposal changes files outside tasks.md")
    preview = _build_preview(root, spec_id, check_phase_a_owner=False)
    if any(state.get(key) != preview.public.get(key) for key in _PINNED_FIELDS):
        raise RunnabilityAmendmentError("amendment inputs or target lineage changed")
    proposed = _published_blob(root, new_ref, task_path)
    if proposed != preview.proposed_tasks.encode("utf-8"):
        raise RunnabilityAmendmentError("proposed commit differs from deterministic owner task")
    old_blob = _git(root, "rev-parse", f"{old_ref}:{task_path}")
    new_blob = _git(root, "rev-parse", f"{new_ref}:{task_path}")
    if _index_blob(root, task_path) != old_blob:
        raise RunnabilityAmendmentError("tasks.md index entry differs from published baseline")
    tasks = root / task_path
    if _sha_file(tasks) != state.get("working_preimage_sha256"):
        raise RunnabilityAmendmentError("working tasks.md changed before promotion")
    return preview.projected_working_tasks.encode("utf-8"), old_blob, new_blob


def promote_runnability_owner(
    project_root: Path, amendment_id: str,
    *, fault_hook: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Publish only the prepared task append, index blob, and branch ref."""
    root = Path(project_root).resolve()
    _, _, spec_id = _load(root, amendment_id)
    owner = f"runnability-promote-{amendment_id.replace('/', '-')}"
    with AmendmentLock.acquire(root, spec_id, owner):
        with PhaseAExecutionLock.acquire(root, owner):
            state_path, state, spec_id = _load(root, amendment_id)
            if state.get("status") != "prepared":
                raise RunnabilityAmendmentError("amendment is not prepared for promotion")
            projected, old_blob, new_blob = _verify_prepared(root, state, spec_id)
            task_path = _task_path(spec_id)
            old_ref = str(state["baseline_commit"])
            new_ref = str(state["proposed_commit"])
            state.update({
                "old_index_blob": old_blob,
                "new_index_blob": new_blob,
                "publication_journal": str(state_path.parent / "file-publication.json"),
            })
            _save(state_path, state, status="promoting", phase="intent")
            staged = state_path.parent / "staged/tasks.md"
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(projected)
            if fault_hook:
                fault_hook("before_file")
            if _sha_file(root / task_path) != state["working_preimage_sha256"]:
                raise RunnabilityAmendmentError("working tasks.md changed before file installation")
            transaction = _publication(root, state_path, spec_id, recover=False)
            apply_publication_transaction(transaction)
            _save(state_path, state, status="promoting", phase="file_installed")
            if fault_hook:
                fault_hook("after_file")
            if _index_blob(root, task_path) != old_blob:
                raise RunnabilityAmendmentError("tasks.md index entry changed before installation")
            _git(root, "update-index", "--cacheinfo", f"100644,{new_blob},{task_path}")
            if _index_blob(root, task_path) != new_blob:
                raise RunnabilityAmendmentError("new tasks.md index entry failed verification")
            _save(state_path, state, status="promoting", phase="index_installed")
            if fault_hook:
                fault_hook("after_index")
            _git(root, "update-ref", f"refs/heads/{spec_id}", new_ref, old_ref)
            _save(state_path, state, status="promoting", phase="ref_installed")
            if fault_hook:
                fault_hook("after_ref")
            _save(state_path, state, status="promoted", phase="complete")
            return state


def _needs_attention(path: Path, state: dict[str, object], reason: str) -> str:
    state["attention_reason"] = reason
    _save(path, state, status="needs_attention", phase="blocked")
    return "needs_attention"


def recover_runnability_promotion(project_root: Path, amendment_id: str) -> str:
    """Settle exact owned effects according to the current branch ref."""
    root = Path(project_root).resolve()
    state_path, _, spec_id = _load(root, amendment_id)
    owner = f"runnability-recover-{amendment_id.replace('/', '-')}"
    with AmendmentLock.acquire(root, spec_id, owner):
        with PhaseAExecutionLock.acquire(root, owner):
            state_path, state, spec_id = _load(root, amendment_id)
            if state.get("status") not in {"promoting", "promoted", "needs_attention", "rolled_back"}:
                raise RunnabilityAmendmentError("amendment has no promotion transaction")
            task_path = _task_path(spec_id)
            current_ref = _git(root, "rev-parse", f"refs/heads/{spec_id}")
            current_index = _index_blob(root, task_path)
            current_file = _sha_file(root / task_path)
            old_ref, new_ref = state.get("baseline_commit"), state.get("proposed_commit")
            old_blob, new_blob = state.get("old_index_blob"), state.get("new_index_blob")
            old_sha, new_sha = state.get("working_preimage_sha256"), state.get("working_projected_sha256")
            if current_ref == new_ref:
                if current_index != new_blob or current_file != new_sha:
                    return _needs_attention(state_path, state, "committed amendment has changed index or working file")
                journal = state_path.parent / "file-publication.json"
                if not journal.is_file():
                    return _needs_attention(state_path, state, "file publication journal is missing")
                _publication(root, state_path, spec_id, recover=True)
                _save(state_path, state, status="promoted", phase="complete")
                return "promoted"
            if current_ref != old_ref:
                return _needs_attention(state_path, state, "spec branch moved outside amendment")
            if current_index not in {old_blob, new_blob} or current_file not in {old_sha, new_sha}:
                return _needs_attention(state_path, state, "owned file or index changed before rollback")
            journal = state_path.parent / "file-publication.json"
            if journal.is_file():
                try:
                    rollback_publication_transaction(_publication(root, state_path, spec_id, recover=True))
                except Exception as exc:
                    return _needs_attention(state_path, state, f"file rollback could not verify ownership: {exc}")
            elif current_file != old_sha:
                return _needs_attention(state_path, state, "file publication journal is missing")
            if _sha_file(root / task_path) != old_sha:
                return _needs_attention(state_path, state, "working file did not restore")
            if current_index == new_blob:
                _git(root, "update-index", "--cacheinfo", f"100644,{old_blob},{task_path}")
            if _index_blob(root, task_path) != old_blob:
                return _needs_attention(state_path, state, "index did not restore")
            _save(state_path, state, status="rolled_back", phase="complete")
            return "rolled_back"
