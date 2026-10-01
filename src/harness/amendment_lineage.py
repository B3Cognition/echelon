"""Pure target-local proof for checkpoint progress across a plan amendment."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import re


class AmendmentLineageError(ValueError):
    """Amendment progress cannot be inherited before a safe Delivery dispatch."""


_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_TASK = re.compile(r"T-\d+\Z")


def _task_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not _TASK.fullmatch(item) for item in value
    ):
        raise AmendmentLineageError("amendment task inventory is malformed")
    result = tuple(value)
    if len(result) != len(set(result)):
        raise AmendmentLineageError("amendment task inventory is duplicated")
    return result


def proven_amended_task_ids(
    manifest: Mapping[str, object],
    *,
    target_id: str,
    candidate: str | None,
    current_input_hash: str,
    states: Iterable[Mapping[str, object]],
    commit_is_ancestor: Callable[[str, str], bool],
    landed_baseline_commit: str | None = None,
    allow_descendant: bool = False,
) -> tuple[str, ...]:
    """Return only older tasks proven by recorded checkpoints on one target.

    The caller validates published Git blobs, repository identity, the settled
    file/index/ref transaction, and target-local state directory before use.
    """
    if manifest.get("status") != "promoted":
        raise AmendmentLineageError("runnability amendment is not promoted")
    if manifest.get("projected_working_hash") != current_input_hash:
        raise AmendmentLineageError("current Spec input hash differs from promoted amendment")
    paths = manifest.get("target_paths")
    targets = manifest.get("targets")
    if (not isinstance(paths, list) or target_id not in paths
            or not isinstance(targets, Mapping)):
        raise AmendmentLineageError("target identity differs from amendment")
    target = targets.get(target_id)
    if not isinstance(target, Mapping):
        raise AmendmentLineageError("target evidence is missing")
    expected_candidate = target.get("candidate_commit")
    pinned_base = expected_candidate or target.get("landed_baseline_commit")
    proof_base = candidate or landed_baseline_commit or pinned_base
    if candidate != expected_candidate or (
        candidate is None and landed_baseline_commit is not None
        and landed_baseline_commit != target.get("landed_baseline_commit")
    ):
        try:
            descendant = (
                allow_descendant and isinstance(pinned_base, str)
                and isinstance(proof_base, str)
                and commit_is_ancestor(pinned_base, proof_base) is True
            )
        except Exception:
            descendant = False
        if not descendant:
            raise AmendmentLineageError("selected candidate differs from amendment")
    old_tasks = set(_task_ids(manifest.get("old_task_ids")))
    new_tasks = set(_task_ids(manifest.get("new_task_ids")))
    if old_tasks & new_tasks:
        raise AmendmentLineageError("new owner task overlaps prior task inventory")
    old_hash = manifest.get("pre_amendment_working_hash")
    if not isinstance(old_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", old_hash):
        raise AmendmentLineageError("verified pre-amendment working hash is missing")
    raw_refs = target.get("checkpoint_refs")
    if not isinstance(raw_refs, list):
        raise AmendmentLineageError("target checkpoint references are malformed")
    refs: set[tuple[str, str, str, tuple[str, ...]]] = set()
    for raw in raw_refs:
        if not isinstance(raw, Mapping):
            raise AmendmentLineageError("target checkpoint reference is malformed")
        build_id, commit = raw.get("build_id"), raw.get("commit")
        digest = raw.get("checkpoint_input_hash")
        task_ids = raw.get("task_ids")
        if (not isinstance(build_id, str) or not isinstance(commit, str)
                or not _COMMIT.fullmatch(commit) or not isinstance(digest, str)
                or not isinstance(task_ids, list)):
            raise AmendmentLineageError("target checkpoint reference is malformed")
        try:
            recorded_tasks = _task_ids(task_ids)
        except AmendmentLineageError as exc:
            raise AmendmentLineageError("target checkpoint reference is malformed") from exc
        refs.add((build_id, commit, digest, recorded_tasks))
    ref_builds = {ref[0] for ref in refs}
    target_states = [
        state for state in states
        if state.get("target_id") == target_id and state.get("spec_id") == manifest.get("spec_id")
    ]
    for state in target_states:
        build_id = state.get("build_id")
        pending = state.get("delivery_slice_operation")
        if (isinstance(build_id, str) and isinstance(pending, Mapping)
                and pending.get("progress_applied") is not True):
            raise AmendmentLineageError(
                f"pending Delivery operation in {build_id}; recover it under sealed inputs"
            )
    if proof_base is None:
        if not refs:
            return ()
        raise AmendmentLineageError("checkpoint references have no pinned landed baseline")
    if not isinstance(proof_base, str) or not _COMMIT.fullmatch(proof_base):
        raise AmendmentLineageError("selected candidate is malformed")
    recovered: set[str] = set()
    for state in target_states:
        build_id = state.get("build_id")
        if not isinstance(build_id, str) or build_id not in ref_builds:
            continue
        checkpoints = state.get("checkpoint_commits")
        if not isinstance(checkpoints, list):
            continue
        for checkpoint in checkpoints:
            if not isinstance(checkpoint, Mapping):
                continue
            commit = checkpoint.get("commit")
            digest = checkpoint.get("checkpoint_input_hash")
            task_ids = checkpoint.get("task_ids")
            if (not isinstance(commit, str) or not isinstance(digest, str)
                    or not isinstance(task_ids, list)
                    or any(not isinstance(item, str) or not _TASK.fullmatch(item)
                           for item in task_ids)
                    or (build_id, commit, digest, tuple(task_ids)) not in refs
                    or digest != old_hash):
                continue
            try:
                ancestor = commit_is_ancestor(commit, proof_base) is True
            except Exception:
                ancestor = False
            if ancestor:
                recovered.update(item for item in task_ids if item in old_tasks)
    return tuple(sorted(recovered))
