"""Checkpoint-only recovery for one destructive spec retarget revision."""

from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import stat
from typing import Mapping

from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message
from echelon.git_helpers import (
    GitHelperError,
    current_branch,
    run_git,
    worktree_dirty_paths,
)
from echelon.mempalace_retarget import (
    RetargetMemoryReceipt,
    purge_retarget_spec_memory,
    refresh_retarget_spec_memory,
)
from echelon.spec_retarget_graph import (
    RetargetGraphError,
    RetargetGraphReceipt,
    finalize_retarget_graphs,
    invalidate_retarget_graphs_from_recovered_baseline,
)
from echelon.spec_retarget_history import (
    RetargetRevision,
    _history_from_raw,
    advance_retarget_revision,
    bind_failed_recovery_effects,
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
    CHECKPOINT_LEDGER_REL,
    CHECKPOINT_LOCK_REL,
    PhaseCheckpoint,
    PhaseCheckpointError,
    _commit_spec_changes,
)
from harness.squad_state import SquadStateStore


_SPEC_ID = re.compile(r"^(?:[0-9]{3,})-[a-z0-9]+(?:-[a-z0-9]+)*$")
_GIT_OID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_TRAILER = re.compile(r"^([A-Za-z0-9-]+):[ \t]*(.*?)\s*$")

def _artifact_invalidation_from_revision(
    revision: RetargetRevision,
) -> tuple[str, ...]:
    paths: list[str] = []
    for item in revision.artifact_inventory:
        if (
            type(item) is not dict
            or frozenset(item) != {"path", "disposition"}
            or item.get("disposition") != "invalidate"
            or type(item.get("path")) is not str
        ):
            raise RetargetRecoveryError("retarget recovery artifact inventory is invalid")
        path = str(item["path"])
        candidate = PurePosixPath(path)
        if (
            not path
            or candidate.is_absolute()
            or len(candidate.parts) != 1
            or candidate.as_posix() != path
            or path in {".", "..", ".echelon", "retarget-history.json"}
        ):
            raise RetargetRecoveryError("retarget recovery artifact inventory is invalid")
        paths.append(path)
    if not paths or len(paths) != len(set(paths)) or tuple(paths) != tuple(sorted(paths)):
        raise RetargetRecoveryError("retarget recovery artifact inventory is invalid")
    return tuple(paths)


def _checkpoint_revision(
    project_root: Path,
    spec_dir: Path,
    commit: str,
    revision_id: object,
) -> RetargetRevision:
    if type(commit) is not str or _GIT_OID.fullmatch(commit) is None:
        raise RetargetRecoveryError("retarget recovery checkpoint proof is invalid")
    shown = run_git(
        project_root,
        "show",
        f"{commit}:specs/{spec_dir.name}/retarget-history.json",
        check=False,
    )
    if shown.returncode != 0:
        raise RetargetRecoveryError("retarget recovery checkpoint proof is unavailable")
    try:
        history = _history_from_raw(
            loads_strict_json(shown.stdout),
            spec_id=spec_dir.name,
        )
    except (TypeError, ValueError) as exc:
        raise RetargetRecoveryError(
            "retarget recovery checkpoint proof is invalid"
        ) from exc
    matches = tuple(
        revision for revision in history.revisions if revision.revision_id == revision_id
    )
    if len(matches) != 1:
        raise RetargetRecoveryError("retarget recovery checkpoint proof is invalid")
    return matches[0]


def retarget_recovery_dirty_paths(
    project_root: Path,
    spec_dir: Path,
    replacement_state: Mapping[str, object],
) -> frozenset[str]:
    """Return only authenticated controller-owned dirt eligible for reset."""

    root = Path(project_root).resolve()
    directory = Path(spec_dir).resolve()
    retarget = replacement_state.get("retarget")
    raw_invalidation = (
        retarget.get("artifact_invalidation") if type(retarget) is dict else None
    )
    raw_targets = retarget.get("replacement_targets") if type(retarget) is dict else None
    if (
        type(replacement_state) is not dict
        or type(retarget) is not dict
        or type(raw_invalidation) is not list
        or not raw_invalidation
        or type(raw_targets) is not list
        or not raw_targets
        or directory.parent != root / "specs"
        or not directory.is_dir()
        or Path(spec_dir).is_symlink()
    ):
        raise RetargetRecoveryError("retarget recovery artifact plan is invalid")
    invalidation: set[str] = set()
    for value in raw_invalidation:
        candidate = PurePosixPath(value) if type(value) is str else PurePosixPath("/")
        if (
            type(value) is not str
            or not value
            or candidate.is_absolute()
            or len(candidate.parts) != 1
            or candidate.as_posix() != value
            or value in {".", "..", ".echelon", "retarget-history.json"}
        ):
            raise RetargetRecoveryError("retarget recovery artifact plan is invalid")
        invalidation.add(value)
    if len(invalidation) != len(raw_invalidation):
        raise RetargetRecoveryError("retarget recovery artifact plan is invalid")
    targets: list[str] = []
    for value in raw_targets:
        if type(value) is not str or not value or "\n" in value or "\r" in value:
            raise RetargetRecoveryError("retarget recovery target plan is invalid")
        targets.append(value)
    try:
        history = load_retarget_history(directory)
    except (OSError, TypeError, ValueError) as exc:
        raise RetargetRecoveryError(
            "retarget recovery target plan is unavailable"
        ) from exc
    if (
        not history.revisions
        or history.revisions[-1].revision_id != retarget.get("revision_id")
        or history.revisions[-1].replacement_run_id
        != replacement_state.get("run_id")
        or tuple(targets) != history.revisions[-1].replacement_targets
    ):
        raise RetargetRecoveryError("retarget recovery target plan drifted")
    live_revision = history.revisions[-1]
    checkpoint_revision = _checkpoint_revision(
        root,
        directory,
        str(retarget.get("checkpoint_commit") or ""),
        retarget.get("revision_id"),
    )
    immutable_fields = (
        "revision_id",
        "operation_id",
        "baseline_run_id",
        "replacement_run_id",
        "old_targets",
        "replacement_targets",
        "original_prompt_digest",
        "recovery",
        "checkpoint_parent",
        "artifact_inventory",
    )
    if any(
        getattr(live_revision, field) != getattr(checkpoint_revision, field)
        for field in immutable_fields
    ):
        raise RetargetRecoveryError("retarget recovery checkpoint proof drifted")
    mutable_state_fields = {
        "status": live_revision.status,
        "checkpoint_id": live_revision.checkpoint_id,
        "checkpoint_commit": live_revision.checkpoint_commit,
        "failure_code": live_revision.failure_code,
    }
    if live_revision.memory_purge is not None:
        mutable_state_fields["memory_purge"] = live_revision.memory_purge
    if live_revision.graph_invalidation is not None:
        mutable_state_fields["graph_invalidation"] = live_revision.graph_invalidation
    if any(retarget.get(field) != value for field, value in mutable_state_fields.items()):
        raise RetargetRecoveryError("retarget recovery controller history drifted")
    authenticated_invalidation = _artifact_invalidation_from_revision(
        checkpoint_revision
    )
    if tuple(raw_invalidation) != authenticated_invalidation:
        raise RetargetRecoveryError("retarget recovery artifact plan drifted")
    expected_targets = (
        "targets:\n" + "".join(f"- {target}\n" for target in targets)
    ).encode("utf-8")
    relative_spec = directory.relative_to(root).as_posix()
    prefix = f"{relative_spec}/"
    staged_result = run_git(
        root,
        "diff",
        "--cached",
        "--name-only",
        "--",
        relative_spec,
        check=False,
    )
    if staged_result.returncode != 0:
        raise RetargetRecoveryError("retarget recovery staged paths are unavailable")
    staged_paths = frozenset(staged_result.stdout.splitlines())
    allowed: set[str] = set()
    for repo_path in worktree_dirty_paths(root):
        if not repo_path.startswith(prefix):
            continue
        if repo_path in staged_paths:
            continue
        relative = repo_path.removeprefix(prefix)
        if relative == "retarget-history.json":
            allowed.add(relative)
            continue
        if relative == ".spec.md.retarget-recovery":
            staging = directory / relative
            canonical = directory / "spec.md"
            checkpoint_spec = run_git(
                root,
                "show",
                f"{retarget['checkpoint_commit']}:specs/{directory.name}/spec.md",
                check=False,
            )
            try:
                if (
                    checkpoint_spec.returncode == 0
                    and not canonical.exists()
                    and not canonical.is_symlink()
                    and staging.is_file()
                    and not staging.is_symlink()
                    and staging.read_bytes() == checkpoint_spec.stdout.encode("utf-8")
                ):
                    allowed.add(relative)
            except OSError:
                pass
            continue
        candidate = PurePosixPath(relative)
        if not candidate.parts or candidate.parts[0] not in invalidation:
            continue
        invalidated_root = directory / candidate.parts[0]
        if candidate.parts[0] == "targets.yml":
            if relative != "targets.yml":
                continue
            try:
                if invalidated_root.read_bytes() == expected_targets:
                    allowed.add(relative)
            except OSError:
                continue
        elif not invalidated_root.exists() and not invalidated_root.is_symlink():
            allowed.add(relative)
    return frozenset(allowed)


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


def _recovered_retarget_contract(
    revision: RetargetRevision,
    recovery_commit: str,
) -> dict[str, object]:
    return {
        "operation_id": revision.operation_id,
        "revision_id": revision.revision_id,
        "status": "recovered",
        "baseline_run_id": revision.baseline_run_id,
        "replacement_run_id": revision.replacement_run_id,
        "old_targets": list(revision.old_targets),
        "replacement_targets": list(revision.replacement_targets),
        "artifact_invalidation": list(_artifact_invalidation_from_revision(revision)),
        "checkpoint_id": revision.checkpoint_id,
        "checkpoint_commit": revision.checkpoint_commit,
        "failure_code": None,
        "recovery_commit": recovery_commit,
    }


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
        preserve_recovered = False
        if state_path.exists() or state_path.is_symlink():
            state_stat = os.lstat(state_path)
            if stat.S_ISLNK(state_stat.st_mode) or not stat.S_ISREG(state_stat.st_mode):
                raise RetargetRecoveryError("retarget baseline state is invalid")
            existing = SquadStateStore(run_dir).load()
            existing_spec_ref = Path(
                str(existing.get("published_spec_dir") or existing.get("spec_dir") or "")
            )
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
            if (
                revision.status == "recovered"
                and revision.recovery_commit is not None
                and existing.get("status") == revision.recovery.status
                and existing.get("phase") == revision.recovery.phase
                and existing.get("completed_phases")
                == list(revision.recovery.completed_phases)
                and existing.get("implementation_targets")
                == list(revision.recovery.implementation_targets)
                and existing.get("spec_status") == revision.recovery.spec_status
                and existing.get("ready_to_build") is revision.recovery.ready_to_build
                and "blocked_reason" not in existing
                and existing.get("retarget")
                == _recovered_retarget_contract(
                    revision,
                    revision.recovery_commit,
                )
            ):
                preserve_recovered = True
        if preserve_recovered:
            return SpecRun(
                run_dir=run_dir.resolve(),
                run_dir_name=run_dir.name,
                run_id=revision.baseline_run_id,
                spec_id=canonical_spec_dir.name,
                feature_branch=feature_branch,
                spec_dir=canonical_spec_dir,
                published_spec_dir=canonical_spec_dir,
            )
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
    *,
    required_existing_commit: str | None = None,
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
        or (
            required_existing_commit is not None
            and (
                type(required_existing_commit) is not str
                or _GIT_OID.fullmatch(required_existing_commit) is None
            )
        )
    ):
        raise RetargetRecoveryError("retarget recovery commit identity is invalid")
    identity = _recovery_commit_identity(directory, revision, checkpoint)
    try:
        matches = list(
            _verified_existing_recovery_commits(
                root,
                directory,
                revision,
                identity,
            )
        )
        if len(matches) > 1:
            raise RetargetRecoveryError("duplicate retarget recovery commits")
        if matches:
            candidate = matches[0]
            if (
                required_existing_commit is not None
                and candidate != required_existing_commit
            ):
                raise RetargetRecoveryError("retarget recovery commit proof drifted")
            if revision.recovery_commit not in {None, candidate}:
                raise RetargetRecoveryError("retarget recovery commit binding drifted")
            if not _verify_live_recovery_postimage(
                root,
                directory,
                revision,
                candidate,
            ):
                raise RetargetRecoveryError(
                    "retarget recovery live postimage drifted"
                )
            return candidate
        if required_existing_commit is not None:
            raise RetargetRecoveryError("required retarget recovery commit is unavailable")
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
        if not _verify_live_recovery_postimage(root, directory, revision, commit):
            raise RetargetRecoveryError("retarget recovery live postimage drifted")
        return commit
    except RetargetRecoveryError:
        raise
    except (GitHelperError, PhaseCheckpointError, OSError, TypeError, ValueError) as exc:
        raise RetargetRecoveryError("retarget recovery commit is unavailable") from exc


def _verified_existing_recovery_commits(
    project_root: Path,
    spec_dir: Path,
    revision: RetargetRevision,
    identity: Mapping[str, str],
) -> tuple[str, ...]:
    discovered = run_git(
        project_root,
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
            project_root,
            spec_dir,
            revision,
            candidate,
            identity,
        ):
            raise RetargetRecoveryError("retarget recovery commit proof drifted")
        matches.append(candidate)
    return tuple(matches)


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


def _verify_live_recovery_postimage(
    project_root: Path,
    spec_dir: Path,
    revision: RetargetRevision,
    commit: str,
) -> bool:
    spec_path = f"specs/{spec_dir.name}"
    history_path = f"{spec_path}/retarget-history.json"
    tracked = run_git(
        project_root,
        "diff",
        "--quiet",
        commit,
        "--",
        spec_path,
        f":(exclude){history_path}",
        check=False,
    )
    untracked = run_git(
        project_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "--",
        spec_path,
        f":(exclude){spec_path}/{CHECKPOINT_LEDGER_REL.as_posix()}",
        f":(exclude){spec_path}/{CHECKPOINT_LOCK_REL.as_posix()}",
        f":(exclude){spec_path}/.echelon/.checkpoints.json.*.tmp",
        check=False,
    )
    try:
        history = load_retarget_history(spec_dir)
    except (OSError, TypeError, ValueError):
        return False
    return (
        tracked.returncode == 0
        and untracked.returncode == 0
        and not untracked.stdout.strip()
        and bool(history.revisions)
        and history.revisions[-1] == revision
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
    if revision.checkpoint_id is None or revision.checkpoint_commit is None:
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
                "phase": revision.recovery.phase,
                "completed_phases": list(revision.recovery.completed_phases),
                "implementation_targets": list(
                    revision.recovery.implementation_targets
                ),
                "spec_status": revision.recovery.spec_status,
                "ready_to_build": revision.recovery.ready_to_build,
                "retarget": _recovered_retarget_contract(
                    revision,
                    recovery_commit,
                ),
            }
        )
        state.pop("blocked_reason", None)
        store.save(state)
        durable = store.load()
        controlled = (
            "status",
            "phase",
            "completed_phases",
            "implementation_targets",
            "spec_status",
            "ready_to_build",
            "retarget",
        )
        if "blocked_reason" in durable or any(
            durable.get(key) != state[key] for key in controlled
        ):
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
    state_run_id = replacement_state.get("run_id")
    state_status = retarget.get("status") if type(retarget) is dict else None
    state_run_matches = state_run_id == revision.replacement_run_id or (
        revision.status == "recovered"
        and state_status == "recovered"
        and state_run_id == revision.baseline_run_id
    )
    if (
        type(replacement_state) is not dict
        or type(retarget) is not dict
        or not state_run_matches
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
        ):
            raise RetargetRecoveryError("retarget recovery graph baseline is unavailable")
        if raw_graph is not None:
            try:
                graph = RetargetGraphReceipt.from_dict(raw_graph)
                raw_memory = retarget.get("memory_purge")
                memory = _memory_receipt_from_history(raw_memory)
            except (
                RetargetGraphError,
                TypeError,
                ValueError,
                RetargetRecoveryError,
            ) as exc:
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
        except (RetargetGraphError, TypeError, ValueError) as exc:
            raise RetargetRecoveryError(
                "retarget recovery captured graph is invalid"
            ) from exc
        if captured_graph.to_dict() != revision.graph_invalidation:
            raise RetargetRecoveryError("retarget recovery captured graph drifted")
    return spec_dir, revision


def verified_committed_retarget_recovery(
    project_root: Path,
    checkpoint: PhaseCheckpoint,
    replacement_state: Mapping[str, object],
) -> str | None:
    """Return one verified existing recovery commit without mutating state."""

    root = Path(project_root).resolve()
    if type(checkpoint) is not PhaseCheckpoint or checkpoint.source != "retarget-preflight":
        return None
    spec_dir = root / "specs" / checkpoint.spec_id
    try:
        history = load_retarget_history(spec_dir)
        if not history.revisions or history.revisions[-1].status != "recovered":
            return None
        spec_dir, revision = _require_recovery_revision(
            root,
            checkpoint,
            replacement_state,
        )
        identity = _recovery_commit_identity(spec_dir, revision, checkpoint)
        matches = _verified_existing_recovery_commits(
            root,
            spec_dir,
            revision,
            identity,
        )
    except RetargetRecoveryError:
        raise
    except (GitHelperError, OSError, TypeError, ValueError) as exc:
        raise RetargetRecoveryError(
            "retarget recovery commit proof is unavailable"
        ) from exc
    if len(matches) > 1:
        raise RetargetRecoveryError("duplicate retarget recovery commits")
    if not matches:
        return None
    candidate = matches[0]
    if revision.recovery_commit not in {None, candidate}:
        raise RetargetRecoveryError("retarget recovery commit binding drifted")
    if not _verify_live_recovery_postimage(root, spec_dir, revision, candidate):
        raise RetargetRecoveryError("retarget recovery live postimage drifted")
    return candidate


def resume_committed_retarget_recovery(
    project_root: Path,
    checkpoint: PhaseCheckpoint,
    replacement_state: Mapping[str, object],
) -> RetargetRecoveryResult | None:
    """Finish publication only when the same recovery commit already exists."""

    recovery_commit = verified_committed_retarget_recovery(
        project_root,
        checkpoint,
        replacement_state,
    )
    if recovery_commit is None:
        return None
    return recover_retarget_checkpoint(
        project_root,
        checkpoint,
        replacement_state,
        required_existing_commit=recovery_commit,
    )


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
    *,
    required_existing_commit: str | None = None,
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
                updates={
                    "checkpoint_id": checkpoint.id,
                    "checkpoint_commit": checkpoint.commit,
                    "failure_code": "retarget_recovery_requested",
                },
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
            if revision.graph_invalidation is None:
                invalidated = invalidate_retarget_graphs_from_recovered_baseline(
                    project_root,
                    spec_dir,
                )
                if (
                    type(invalidated) is not RetargetGraphReceipt
                    or invalidated.spec_id != checkpoint.spec_id
                    or invalidated.spec_status != "invalidated"
                ):
                    raise RetargetRecoveryError(
                        "retarget recovery graph invalidation receipt is invalid"
                    )
                revision = bind_failed_recovery_effects(
                    spec_dir,
                    revision.revision_id,
                    checkpoint_id=checkpoint.id,
                    checkpoint_commit=checkpoint.commit,
                    memory_purge=purged.to_dict(),
                    graph_invalidation=invalidated.to_dict(),
                )
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
        if required_existing_commit is None:
            recovery_commit = create_or_recover_retarget_recovery_commit(
                project_root,
                spec_dir,
                revision,
                checkpoint,
            )
        else:
            recovery_commit = create_or_recover_retarget_recovery_commit(
                project_root,
                spec_dir,
                revision,
                checkpoint,
                required_existing_commit=required_existing_commit,
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
