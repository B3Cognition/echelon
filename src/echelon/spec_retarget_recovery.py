"""Checkpoint-only recovery for one destructive spec retarget revision."""

from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
import re
import stat
from typing import Mapping

from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message
from echelon.git_helpers import GitHelperError, current_branch, run_git
from echelon.mempalace_retarget import (
    RetargetMemoryReceipt,
    purge_retarget_spec_memory,
    refresh_retarget_spec_memory,
)
from echelon.spec_retarget_graph import (
    RetargetGraphReceipt,
    finalize_retarget_graphs,
)
from echelon.spec_retarget_history import (
    RetargetRevision,
    _history_from_raw,
    advance_retarget_revision,
    bind_recovered_revision_commit as _bind_recovered_revision_commit,
    load_retarget_history,
)
from echelon.strict_json import loads_strict_json
from echelon.spec_lifecycle import (
    SpecLifecycleError,
    SpecRun,
    activate_same_branch_spec_run,
    resolve_spec_run,
)
from harness.phase_checkpoints import (
    PhaseCheckpoint,
    PhaseCheckpointError,
    _commit_spec_changes,
)
from harness.squad_state import SquadStateStore


_SPEC_ID = re.compile(r"^(?:[0-9]{3,})-[a-z0-9]+(?:-[a-z0-9]+)*$")
_GIT_OID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_TRAILER = re.compile(r"^([A-Za-z0-9-]+):[ \t]*(.*?)\s*$")


class RetargetRecoveryError(RuntimeError):
    """Checkpoint recovery could not prove one exact retarget postimage."""


@dataclass(frozen=True)
class RetargetRecoveryResult:
    spec_id: str
    baseline_run_id: str
    replacement_run_id: str
    revision_id: str
    recovery_commit: str
    memory: RetargetMemoryReceipt
    graph: RetargetGraphReceipt

    def __post_init__(self) -> None:
        if (
            type(self.spec_id) is not str
            or _SPEC_ID.fullmatch(self.spec_id) is None
            or type(self.baseline_run_id) is not str
            or not self.baseline_run_id
            or type(self.replacement_run_id) is not str
            or not self.replacement_run_id
            or self.baseline_run_id == self.replacement_run_id
            or type(self.revision_id) is not str
            or not self.revision_id
            or type(self.recovery_commit) is not str
            or _GIT_OID.fullmatch(self.recovery_commit) is None
            or type(self.memory) is not RetargetMemoryReceipt
            or self.memory.spec_id != self.spec_id
            or type(self.graph) is not RetargetGraphReceipt
            or self.graph.spec_id != self.spec_id
        ):
            raise RetargetRecoveryError("retarget recovery result is invalid")


def restore_or_recreate_baseline_state(
    project_root: Path,
    spec_dir: Path,
    revision: RetargetRevision,
    *,
    feature_branch: str,
) -> SpecRun:
    """Materialize the blocked baseline cache from the committed projection."""

    root = Path(project_root).resolve()
    supplied_spec_dir = Path(spec_dir)
    canonical_spec_dir = supplied_spec_dir.resolve()
    if (
        type(revision) is not RetargetRevision
        or type(feature_branch) is not str
        or not feature_branch.strip()
        or canonical_spec_dir.parent != root / "specs"
        or canonical_spec_dir.name != canonical_spec_dir.name.strip()
        or not canonical_spec_dir.is_dir()
        or supplied_spec_dir.is_symlink()
    ):
        raise RetargetRecoveryError("retarget baseline projection is invalid")
    runs_dir = root / "runs"
    if runs_dir.exists() and (runs_dir.is_symlink() or not runs_dir.is_dir()):
        raise RetargetRecoveryError("retarget baseline runs directory is invalid")
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_dir = runs_dir / revision.baseline_run_id
    if run_dir.exists() and (run_dir.is_symlink() or not run_dir.is_dir()):
        raise RetargetRecoveryError("retarget baseline run directory is invalid")
    run_dir.mkdir(exist_ok=True)
    state_path = run_dir / "state.json"
    try:
        if state_path.exists() or state_path.is_symlink():
            state_stat = os.lstat(state_path)
            if stat.S_ISLNK(state_stat.st_mode) or not stat.S_ISREG(state_stat.st_mode):
                raise RetargetRecoveryError("retarget baseline state is invalid")
            existing = SquadStateStore(run_dir).load()
            existing_spec_ref = Path(str(existing.get("spec_dir") or ""))
            if not existing_spec_ref.is_absolute():
                existing_spec_ref = root / existing_spec_ref
            if (
                type(existing) is not dict
                or existing.get("run_id") != revision.baseline_run_id
                or existing.get("spec_id") != canonical_spec_dir.name
                or existing.get("feature_branch") != feature_branch
                or existing_spec_ref.resolve() != canonical_spec_dir
            ):
                raise RetargetRecoveryError("retarget baseline state identity drifted")
        store = SquadStateStore(run_dir)
        store.initialize(
            revision.baseline_run_id,
            "greenfield",
            "",
            0,
            revision.recovery.phase,
            implementation_targets=list(revision.recovery.implementation_targets),
        )
        state = store.load()
        state.update(
            {
                "run_id": revision.baseline_run_id,
                "spec_id": canonical_spec_dir.name,
                "feature_branch": feature_branch,
                "spec_dir": str(canonical_spec_dir),
                "published_spec_dir": str(canonical_spec_dir),
                "phase": revision.recovery.phase,
                "completed_phases": list(revision.recovery.completed_phases),
                "implementation_targets": list(
                    revision.recovery.implementation_targets
                ),
                "spec_status": revision.recovery.spec_status,
                "status": "blocked",
                "blocked_reason": "retarget_recovery_refresh_failed",
                "retarget": {
                    "revision_id": revision.revision_id,
                    "baseline_run_id": revision.baseline_run_id,
                    "replacement_run_id": revision.replacement_run_id,
                },
            }
        )
        store.save(state)
        durable = store.load()
        controlled = {
            key: state[key]
            for key in (
                "run_id",
                "spec_id",
                "feature_branch",
                "spec_dir",
                "published_spec_dir",
                "phase",
                "completed_phases",
                "implementation_targets",
                "spec_status",
                "status",
                "blocked_reason",
                "retarget",
            )
        }
        if any(durable.get(key) != value for key, value in controlled.items()):
            raise RetargetRecoveryError("retarget baseline state was not durable")
    except RetargetRecoveryError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise RetargetRecoveryError("retarget baseline state is unavailable") from exc
    return SpecRun(
        run_dir=run_dir.resolve(),
        run_dir_name=run_dir.name,
        run_id=revision.baseline_run_id,
        spec_id=canonical_spec_dir.name,
        feature_branch=feature_branch,
        spec_dir=canonical_spec_dir,
        published_spec_dir=canonical_spec_dir,
    )


def create_or_recover_retarget_recovery_commit(
    project_root: Path,
    spec_dir: Path,
    revision: RetargetRevision,
    checkpoint: PhaseCheckpoint,
) -> str:
    root = Path(project_root).resolve()
    supplied_spec_dir = Path(spec_dir)
    directory = supplied_spec_dir.resolve()
    if (
        type(revision) is not RetargetRevision
        or revision.status != "recovered"
        or type(checkpoint) is not PhaseCheckpoint
        or checkpoint.source != "retarget-preflight"
        or checkpoint.spec_id != directory.name
        or checkpoint.id != revision.checkpoint_id
        or checkpoint.commit != revision.checkpoint_commit
        or checkpoint.run_id != revision.baseline_run_id
        or directory.parent != root / "specs"
        or not directory.is_dir()
        or supplied_spec_dir.is_symlink()
    ):
        raise RetargetRecoveryError("retarget recovery commit identity is invalid")
    identity = _recovery_commit_identity(directory, revision, checkpoint)
    try:
        discovered = run_git(
            root,
            "log",
            "--all",
            "--fixed-strings",
            "--all-match",
            "--grep=Echelon-Action: retarget-recovered",
            f"--grep=Echelon-Retarget-Revision: {revision.revision_id}",
            "--format=%H",
        )
        candidates = tuple(line for line in discovered.stdout.splitlines() if line)
        matches: list[str] = []
        for candidate in candidates:
            if not _verify_recovery_commit(
                root,
                directory,
                revision,
                candidate,
                identity,
            ):
                raise RetargetRecoveryError("retarget recovery commit proof drifted")
            matches.append(candidate)
        if len(matches) > 1:
            raise RetargetRecoveryError("duplicate retarget recovery commits")
        if matches:
            candidate = matches[0]
            if revision.recovery_commit not in {None, candidate}:
                raise RetargetRecoveryError("retarget recovery commit binding drifted")
            return candidate
        if revision.recovery_commit is not None:
            raise RetargetRecoveryError("bound retarget recovery commit is unavailable")
        message = build_echelon_commit_message(
            "chore: recover retargeted spec",
            EchelonCommitMetadata(
                origin="phase-a",
                action="retarget-recovered",
                spec_id=directory.name,
                run_id=revision.baseline_run_id,
                checkpoint_id=checkpoint.id,
                retarget_revision=revision.revision_id,
                baseline_run_id=revision.baseline_run_id,
                replacement_run_id=revision.replacement_run_id,
            ),
        )
        commit = _commit_spec_changes(root, (directory,), message)
        if commit is None or not _verify_recovery_commit(
            root,
            directory,
            revision,
            commit,
            identity,
        ):
            raise RetargetRecoveryError("retarget recovery commit cannot be verified")
        return commit
    except RetargetRecoveryError:
        raise
    except (GitHelperError, PhaseCheckpointError, OSError, TypeError, ValueError) as exc:
        raise RetargetRecoveryError("retarget recovery commit is unavailable") from exc


def _recovery_commit_identity(
    spec_dir: Path,
    revision: RetargetRevision,
    checkpoint: PhaseCheckpoint,
) -> dict[str, str]:
    return {
        "Echelon-Origin": "phase-a",
        "Echelon-Action": "retarget-recovered",
        "Echelon-Spec": spec_dir.name,
        "Echelon-Run": revision.baseline_run_id,
        "Echelon-Checkpoint": checkpoint.id,
        "Echelon-Retarget-Revision": revision.revision_id,
        "Echelon-Baseline-Run": revision.baseline_run_id,
        "Echelon-Replacement-Run": revision.replacement_run_id,
    }


def _exact_recovery_trailers(message: str, identity: Mapping[str, str]) -> bool:
    values: dict[str, list[str]] = {}
    for line in message.splitlines():
        match = _TRAILER.fullmatch(line)
        if match is not None and match.group(1).startswith("Echelon-"):
            values.setdefault(match.group(1), []).append(match.group(2))
    return frozenset(values) == frozenset(identity) and all(
        values.get(key) == [value] for key, value in identity.items()
    )


def _verify_recovery_commit(
    project_root: Path,
    spec_dir: Path,
    revision: RetargetRevision,
    commit: str,
    identity: Mapping[str, str],
) -> bool:
    if type(commit) is not str or _GIT_OID.fullmatch(commit) is None:
        return False
    resolved = run_git(
        project_root,
        "rev-parse",
        "--verify",
        f"{commit}^{{commit}}",
        check=False,
    )
    parents = run_git(
        project_root,
        "rev-list",
        "--parents",
        "-n",
        "1",
        commit,
        check=False,
    )
    message = run_git(project_root, "show", "-s", "--format=%B", commit, check=False)
    paths = run_git(
        project_root,
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "-r",
        commit,
        check=False,
    )
    history_blob = run_git(
        project_root,
        "show",
        f"{commit}:specs/{spec_dir.name}/retarget-history.json",
        check=False,
    )
    changed = tuple(line for line in paths.stdout.splitlines() if line)
    prefix = f"specs/{spec_dir.name}/"
    if (
        resolved.returncode != 0
        or resolved.stdout.strip() != commit
        or parents.returncode != 0
        or len(parents.stdout.split()) != 2
        or message.returncode != 0
        or paths.returncode != 0
        or history_blob.returncode != 0
        or not changed
        or any(not path.startswith(prefix) for path in changed)
        or not _exact_recovery_trailers(message.stdout, identity)
    ):
        return False
    try:
        raw = loads_strict_json(history_blob.stdout)
        committed = _history_from_raw(raw, spec_id=spec_dir.name)
    except (TypeError, ValueError):
        return False
    if not committed.revisions:
        return False
    projected = committed.revisions[-1]
    return (
        projected.status == "recovered"
        and projected.revision_id == revision.revision_id
        and projected.recovery_commit is None
        and replace(
            projected,
            updated_at=revision.updated_at,
            recovery_commit=revision.recovery_commit,
        )
        == revision
    )


def bind_retarget_recovery_commit(
    spec_dir: Path,
    revision_id: str,
    *,
    recovery_commit: str,
) -> None:
    try:
        _bind_recovered_revision_commit(
            spec_dir,
            revision_id,
            recovery_commit=recovery_commit,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise RetargetRecoveryError("retarget recovery commit binding failed") from exc


def persist_recovered_baseline_state(
    baseline: SpecRun,
    revision: RetargetRevision,
    recovery_commit: str,
) -> None:
    if (
        type(baseline) is not SpecRun
        or type(revision) is not RetargetRevision
        or revision.status != "recovered"
        or baseline.run_id != revision.baseline_run_id
        or baseline.spec_id != baseline.spec_dir.name
        or type(recovery_commit) is not str
        or _GIT_OID.fullmatch(recovery_commit) is None
        or revision.recovery_commit not in {None, recovery_commit}
    ):
        raise RetargetRecoveryError("retarget recovered baseline identity drifted")
    try:
        store = SquadStateStore(baseline.run_dir)
        state = store.load()
        if (
            type(state) is not dict
            or state.get("run_id") != baseline.run_id
            or state.get("spec_id") != baseline.spec_id
            or state.get("feature_branch") != baseline.feature_branch
        ):
            raise RetargetRecoveryError("retarget recovered baseline identity drifted")
        state.update(
            {
                "status": revision.recovery.status,
                "blocked_reason": None,
                "phase": revision.recovery.phase,
                "completed_phases": list(revision.recovery.completed_phases),
                "implementation_targets": list(
                    revision.recovery.implementation_targets
                ),
                "spec_status": revision.recovery.spec_status,
                "ready_to_build": revision.recovery.ready_to_build,
                "retarget": {
                    "revision_id": revision.revision_id,
                    "baseline_run_id": revision.baseline_run_id,
                    "replacement_run_id": revision.replacement_run_id,
                    "status": "recovered",
                    "recovery_commit": recovery_commit,
                },
            }
        )
        store.save(state)
        durable = store.load()
        controlled = (
            "status",
            "blocked_reason",
            "phase",
            "completed_phases",
            "implementation_targets",
            "spec_status",
            "ready_to_build",
            "retarget",
        )
        if any(durable.get(key) != state[key] for key in controlled):
            raise RetargetRecoveryError("retarget recovered baseline was not durable")
    except RetargetRecoveryError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise RetargetRecoveryError("retarget recovered baseline persistence failed") from exc


def activate_recovered_spec_run(
    project_root: Path,
    baseline: SpecRun,
    revision: RetargetRevision,
) -> None:
    try:
        replacement = resolve_spec_run(project_root, revision.replacement_run_id)
        if (
            type(baseline) is not SpecRun
            or baseline.run_id != revision.baseline_run_id
            or replacement.run_id != revision.replacement_run_id
            or baseline.spec_id != replacement.spec_id
            or baseline.feature_branch != replacement.feature_branch
        ):
            raise RetargetRecoveryError("retarget recovery pointer identity drifted")
        activated = activate_same_branch_spec_run(
            project_root,
            replacement,
            baseline,
            observed_branch=current_branch(Path(project_root).resolve()),
            operation_id=f"recover-{revision.operation_id}",
        )
        if activated.run_dir != baseline.run_dir:
            raise RetargetRecoveryError("retarget recovery pointer activation drifted")
    except RetargetRecoveryError:
        raise
    except (GitHelperError, OSError, SpecLifecycleError, TypeError, ValueError) as exc:
        raise RetargetRecoveryError("retarget recovery pointer activation failed") from exc


def _require_recovery_revision(
    project_root: Path,
    checkpoint: PhaseCheckpoint,
    replacement_state: Mapping[str, object],
) -> tuple[Path, RetargetRevision]:
    root = Path(project_root).resolve()
    if type(checkpoint) is not PhaseCheckpoint or checkpoint.source != "retarget-preflight":
        raise RetargetRecoveryError("checkpoint is not a retarget preflight")
    spec_dir = root / "specs" / checkpoint.spec_id
    if not spec_dir.is_dir() or spec_dir.is_symlink():
        raise RetargetRecoveryError("retarget recovery spec directory is unavailable")
    history = load_retarget_history(spec_dir)
    if not history.revisions:
        raise RetargetRecoveryError("retarget recovery revision is unavailable")
    revision = history.revisions[-1]
    retarget = replacement_state.get("retarget")
    checkpoint_bound = (
        revision.checkpoint_id == checkpoint.id
        and revision.checkpoint_commit == checkpoint.commit
    )
    checkpoint_unbound = (
        revision.checkpoint_id is None and revision.checkpoint_commit is None
    )
    if (
        type(replacement_state) is not dict
        or type(retarget) is not dict
        or replacement_state.get("run_id") != revision.replacement_run_id
        or replacement_state.get("spec_id") != checkpoint.spec_id
        or type(replacement_state.get("feature_branch")) is not str
        or not replacement_state.get("feature_branch")
        or retarget.get("revision_id") != revision.revision_id
        or retarget.get("baseline_run_id") != revision.baseline_run_id
        or retarget.get("replacement_run_id") != revision.replacement_run_id
        or not (checkpoint_bound or checkpoint_unbound)
        or checkpoint.run_id != revision.baseline_run_id
    ):
        raise RetargetRecoveryError("retarget recovery identity drifted")
    raw_graph = retarget.get("graph_invalidation")
    if revision.graph_invalidation is None:
        if (
            revision.status not in {"prepared", "invalidating", "rebuilding", "finalizing"}
            or retarget.get("checkpoint_id") != checkpoint.id
            or retarget.get("checkpoint_commit") != checkpoint.commit
            or type(raw_graph) is not dict
        ):
            raise RetargetRecoveryError("retarget recovery graph baseline is unavailable")
        try:
            graph = RetargetGraphReceipt.from_dict(raw_graph)
            raw_memory = retarget.get("memory_purge")
            memory = _memory_receipt_from_history(raw_memory)
        except (TypeError, ValueError, RetargetRecoveryError) as exc:
            raise RetargetRecoveryError(
                "retarget recovery captured projection is invalid"
            ) from exc
        if graph.spec_id != checkpoint.spec_id or memory.spec_id != checkpoint.spec_id:
            raise RetargetRecoveryError("retarget recovery captured projection drifted")
        revision = advance_retarget_revision(
            spec_dir,
            revision.revision_id,
            expected_status=revision.status,
            status="failed",
            updates={
                "checkpoint_id": checkpoint.id,
                "checkpoint_commit": checkpoint.commit,
                "memory_purge": memory.to_dict(),
                "graph_invalidation": graph.to_dict(),
                "failure_code": "retarget_recovery_requested",
            },
        )
    elif type(raw_graph) is dict:
        try:
            captured_graph = RetargetGraphReceipt.from_dict(raw_graph)
        except (TypeError, ValueError) as exc:
            raise RetargetRecoveryError(
                "retarget recovery captured graph is invalid"
            ) from exc
        if captured_graph.to_dict() != revision.graph_invalidation:
            raise RetargetRecoveryError("retarget recovery captured graph drifted")
    return spec_dir, revision


def _memory_receipt_from_history(value: object) -> RetargetMemoryReceipt:
    if type(value) is not dict or frozenset(value) != frozenset(
        RetargetMemoryReceipt.__dataclass_fields__
    ):
        raise RetargetRecoveryError("retarget recovery memory receipt is invalid")
    fields = dict(value)
    for name in (
        "deleted_ids",
        "remaining_owned_ids",
        "unrelated_missing_ids",
        "unrelated_changed_ids",
        "unexpected_added_ids",
    ):
        if type(fields[name]) is not list:
            raise RetargetRecoveryError("retarget recovery memory receipt is invalid")
        fields[name] = tuple(fields[name])
    try:
        return RetargetMemoryReceipt(**fields)
    except (TypeError, ValueError) as exc:
        raise RetargetRecoveryError("retarget recovery memory receipt is invalid") from exc


def _block_recovered_baseline_state(baseline: object) -> None:
    if type(baseline) is not SpecRun:
        return
    store = SquadStateStore(baseline.run_dir)
    state = store.load()
    if type(state) is not dict or state.get("run_id") != baseline.run_id:
        raise RetargetRecoveryError("retarget recovery blocked state identity drifted")
    state.update(
        {
            "status": "blocked",
            "blocked_reason": "retarget_recovery_refresh_failed",
            "ready_to_build": False,
        }
    )
    store.save(state)


def recover_retarget_checkpoint(
    project_root: Path,
    checkpoint: PhaseCheckpoint,
    replacement_state: Mapping[str, object],
) -> RetargetRecoveryResult:
    """Recover one authenticated destructive revision from its checkpoint."""
    spec_dir, revision = _require_recovery_revision(
        project_root,
        checkpoint,
        replacement_state,
    )
    baseline: object | None = None
    try:
        baseline = restore_or_recreate_baseline_state(
            project_root,
            spec_dir,
            revision,
            feature_branch=str(replacement_state["feature_branch"]),
        )
        if revision.status in {"prepared", "invalidating", "rebuilding", "finalizing"}:
            revision = advance_retarget_revision(
                spec_dir,
                revision.revision_id,
                expected_status=revision.status,
                status="failed",
                updates={"failure_code": "retarget_recovery_requested"},
            )
        if revision.status == "recovered":
            memory = _memory_receipt_from_history(revision.memory_finalization)
            graph = RetargetGraphReceipt.from_dict(revision.graph_finalization)
        elif revision.status == "failed":
            purged = purge_retarget_spec_memory(project_root, checkpoint.spec_id)
            if type(purged) is not RetargetMemoryReceipt or purged.spec_id != checkpoint.spec_id:
                raise RetargetRecoveryError("retarget recovery purge receipt is invalid")
            memory = refresh_retarget_spec_memory(project_root, spec_dir)
            if type(memory) is not RetargetMemoryReceipt or memory.spec_id != checkpoint.spec_id:
                raise RetargetRecoveryError("retarget recovery memory receipt is invalid")
            graph = finalize_retarget_graphs(
                project_root,
                spec_dir,
                RetargetGraphReceipt.from_dict(revision.graph_invalidation),
            )
            if type(graph) is not RetargetGraphReceipt or graph.spec_id != checkpoint.spec_id:
                raise RetargetRecoveryError("retarget recovery graph receipt is invalid")
            revision = advance_retarget_revision(
                spec_dir,
                revision.revision_id,
                expected_status="failed",
                status="recovered",
                updates={
                    "memory_finalization": memory.to_dict(),
                    "graph_finalization": graph.to_dict(),
                    "failure_code": None,
                },
            )
        else:
            raise RetargetRecoveryError("retarget revision is not recoverable")
        recovery_commit = create_or_recover_retarget_recovery_commit(
            project_root,
            spec_dir,
            revision,
            checkpoint,
        )
        bind_retarget_recovery_commit(
            spec_dir,
            revision.revision_id,
            recovery_commit=recovery_commit,
        )
        persist_recovered_baseline_state(baseline, revision, recovery_commit)
        activate_recovered_spec_run(project_root, baseline, revision)
        return RetargetRecoveryResult(
            spec_id=checkpoint.spec_id,
            baseline_run_id=revision.baseline_run_id,
            replacement_run_id=revision.replacement_run_id,
            revision_id=revision.revision_id,
            recovery_commit=recovery_commit,
            memory=memory,
            graph=graph,
        )
    except Exception as exc:
        try:
            _block_recovered_baseline_state(baseline)
        except Exception:
            pass
        if isinstance(exc, RetargetRecoveryError) and str(exc).startswith(
            "retarget_recovery_refresh_failed"
        ):
            raise
        raise RetargetRecoveryError(
            f"retarget_recovery_refresh_failed: {type(exc).__name__}"
        ) from exc
