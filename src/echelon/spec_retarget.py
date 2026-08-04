"""Deterministic, read-only evidence for safe Phase A spec retargeting."""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import stat
import subprocess
import tempfile
from typing import Any, Callable, Iterable, Mapping

import yaml

from echelon.artifact_index import (
    RetargetArtifactPlan,
    artifact_definitions,
    plan_retarget_artifacts,
)
from echelon.git_helpers import GitHelperError, current_branch, worktree_dirty_paths
from echelon.mempalace_retarget import (
    RetargetMemoryError,
    RetargetMemoryReceipt,
    purge_retarget_spec_memory,
)
from echelon.phase_a_start import (
    PhaseAStartError,
    RetargetPhaseAStartOutcome,
    start_retarget_phase_a_spec,
)
from echelon.spec_retarget_graph import (
    RetargetGraphError,
    invalidate_retarget_graphs,
)
from echelon.spec_retarget_history import (
    RetargetRecoveryProjection,
    RetargetRevision,
    advance_retarget_revision,
    append_prepared_revision,
    load_retarget_history,
)
from echelon.target_normalization import normalize_target_set
from echelon.spec_lifecycle import (
    PhaseAExecutionLock,
    SpecRun,
    SpecMutationLock,
    SpecRunExecutionLock,
    SpecLifecycleError,
    resolve_active_spec_run,
    resolve_spec_run,
)
from harness.phase_checkpoints import (
    PhaseCheckpoint,
    PhaseCheckpointError,
    commit_retarget_checkpoint,
    load_checkpoint_ledger,
    resolve_checkpoint,
)
from harness.spec_frontmatter import read_frontmatter


class RetargetError(RuntimeError):
    """Base error for deterministic spec retarget operations."""


class RetargetEligibilityError(RetargetError):
    pass


class RetargetArtifactError(RetargetError):
    pass


class RetargetCheckpointError(RetargetError):
    pass


class RetargetRebuildError(RetargetError):
    pass


class RetargetDestructiveError(RetargetError):
    def __init__(self, checkpoint: PhaseCheckpoint, cause: BaseException) -> None:
        self.checkpoint = checkpoint
        self.cause = cause
        super().__init__(
            f"{cause}\n  Recovery: {preview_recovery_command(checkpoint.id)}"
        )


@dataclass(frozen=True)
class RetargetPreview:
    project_root: Path
    spec_id: str
    baseline: SpecRun
    spec_dir: Path
    old_targets: tuple[str, ...]
    replacement_targets: tuple[str, ...]
    artifact_plan: RetargetArtifactPlan
    operation_id: str
    original_user_message: str
    autonomy_mode: str
    ignore_re: bool
    explicit_re_sources: tuple[str, ...]


@dataclass(frozen=True)
class RetargetCommandResult:
    applied: bool
    resume_existing: bool
    spec_id: str
    baseline_run_id: str
    replacement_run_id: str | None
    replacement_targets: tuple[str, ...]
    checkpoint_id: str | None
    checkpoint_commit: str | None
    recovery_command: str
    invalidated_paths: tuple[str, ...]
    original_user_message: str
    autonomy_mode: str
    ignore_re: bool
    explicit_re_sources: tuple[str, ...]
    old_targets: tuple[str, ...] = ()
    baseline_ready_to_build: bool = False


@dataclass(frozen=True)
class RetargetEvidence:
    spec_id: str
    run_id: str
    run_dir: Path
    spec_dir: Path
    feature_branch: str
    current_branch: str
    active_run_id: str
    canonical_targets: tuple[str, ...]
    state_targets: tuple[str, ...]
    replacement_targets: tuple[str, ...]
    lifecycle_status: str
    phase_b_history: tuple[str, ...]
    delivery_state_paths: tuple[str, ...]
    completed_task_ids: tuple[str, ...]
    post_phase_a_artifacts: tuple[str, ...]
    selected_spec_dirty_paths: tuple[str, ...]
    original_user_message: str
    autonomy_mode: str
    product_inputs_recoverable: bool
    published_re_recoverable: bool


@dataclass(frozen=True)
class RetargetEligibility:
    eligible: bool
    reason_codes: tuple[str, ...]
    next_command: str


_POST_PHASE_A_STATUSES = frozenset(
    {"in-progress", "implemented", "ready_to_land", "landed"}
)
_PRE_DELIVERY_STATUSES = frozenset({"planned"})
_COMPLETED_TASK = re.compile(r"^\s*-\s*\[[xX]\]\s+([A-Za-z0-9][A-Za-z0-9_.-]*)")
_RECOVERABLE_RE_STATUSES = frozenset({"attached", "absent", "ignored"})
_HISTORY_FILES = ("run-history.json", "harness-run-history.json")
_RETARGET_CONTEXT_PATHS = ("spec.md", "plan.md", "tasks.md", "targets.yml")
_RETARGET_CONTEXT_FILE_CAP = 256 * 1024
_RETARGET_CONTEXT_TOTAL_CAP = 768 * 1024
_RETARGET_ARTIFACT_ENTRY_CAP = 16_384
_RETARGET_ARTIFACT_DEPTH_CAP = 64
_CANONICAL_SPEC_ID = re.compile(r"\A[0-9]{3,}-[A-Za-z0-9][A-Za-z0-9._-]*\Z")

_RETARGET_FAILURE_CODES = {
    RetargetEligibilityError: "retarget_delivery_already_started",
    RetargetCheckpointError: "retarget_checkpoint_failed",
    RetargetMemoryError: "retarget_memory_purge_failed",
    RetargetArtifactError: "retarget_artifact_invalidation_failed",
    RetargetGraphError: "retarget_graph_refresh_failed",
    RetargetRebuildError: "retarget_rebuild_blocked",
}


def bounded_failure_code(error: BaseException) -> str:
    for error_type, code in _RETARGET_FAILURE_CODES.items():
        if isinstance(error, error_type):
            return code
    return "retarget_rebuild_blocked"


def preview_recovery_command(prospective_checkpoint_id: str) -> str:
    return f"echelon spec rewind checkpoint:{prospective_checkpoint_id} --confirm"


def _strict_replacement_targets(values: tuple[str, ...]) -> tuple[str, ...]:
    if type(values) is not tuple or not values:
        raise RetargetEligibilityError("retarget_target_set_empty")
    normalized: list[str] = []
    for value in values:
        if type(value) is not str:
            raise RetargetEligibilityError("retarget target must be text")
        item = normalize_target_set((value,))
        if len(item) != 1:
            raise RetargetEligibilityError("retarget_target_set_empty")
        if item[0] in normalized:
            raise RetargetEligibilityError(
                f"duplicate retarget target after normalization: {item[0]}"
            )
        normalized.append(item[0])
    return tuple(normalized)


def _git_head(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD^{commit}"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    if result.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) is None:
        raise RetargetEligibilityError("retarget Git baseline is unavailable")
    return value


def _original_re_policy(run_dir: Path) -> tuple[bool, tuple[str, ...]]:
    state = _read_json_object(run_dir / "state.json")
    ignore_re = state.get("ignore_re") is True
    raw_sources = state.get("requested_re_sources")
    if raw_sources is None:
        raw_sources = state.get("explicit_re_sources")
    if raw_sources is None:
        raw_sources = ()
    if type(raw_sources) not in {list, tuple} or any(
        type(item) is not str or not item.strip() for item in raw_sources
    ):
        raise RetargetEligibilityError("retarget RE selection evidence is invalid")
    sources = tuple(item.strip() for item in raw_sources)
    if len(set(sources)) != len(sources):
        raise RetargetEligibilityError("retarget RE selection evidence is invalid")
    return ignore_re, sources


def _require_canonical_published_spec(project_root: Path, run: SpecRun) -> Path:
    root = Path(project_root).resolve()
    expected = root / "specs" / run.spec_id
    expected_shadow = run.run_dir / "specs" / run.spec_id
    for path, label in (
        (expected, "canonical published spec directory"),
        (expected_shadow, "baseline run shadow directory"),
    ):
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise RetargetEligibilityError(f"{label} is unavailable") from exc
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise RetargetEligibilityError(f"{label} must be a real directory")
    if run.published_spec_dir != expected.resolve():
        raise RetargetEligibilityError(
            "baseline published spec directory is not canonical"
        )
    if run.spec_dir != expected_shadow.resolve():
        raise RetargetEligibilityError("baseline run shadow binding is not canonical")
    return expected.resolve()


def _build_retarget_preview(
    project_root: Path,
    spec_id: str,
    replacement_targets: tuple[str, ...],
) -> RetargetPreview:
    root = Path(project_root).resolve()
    targets = _strict_replacement_targets(replacement_targets)
    evidence = collect_retarget_evidence(root, spec_id)
    evidence = replace(evidence, replacement_targets=targets)
    eligibility = classify_retarget(evidence)
    if not eligibility.eligible:
        reasons = ", ".join(eligibility.reason_codes)
        raise RetargetEligibilityError(
            f"{reasons}\n  Next: {eligibility.next_command}"
        )
    baseline = resolve_spec_run(root, spec_id)
    canonical_spec_dir = _require_canonical_published_spec(root, baseline)
    if evidence.spec_dir != canonical_spec_dir:
        raise RetargetEligibilityError("retarget canonical spec evidence changed")
    ignore_re, explicit_re_sources = _original_re_policy(baseline.run_dir)
    identity = json.dumps(
        {
            "head": _git_head(root),
            "spec_id": evidence.spec_id,
            "baseline_run_id": baseline.run_id,
            "old_targets": evidence.canonical_targets,
            "replacement_targets": targets,
            "original_prompt_digest": hashlib.sha256(
                evidence.original_user_message.encode("utf-8")
            ).hexdigest(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    operation_id = f"retarget-{hashlib.sha256(identity).hexdigest()[:32]}"
    return RetargetPreview(
        project_root=root,
        spec_id=evidence.spec_id,
        baseline=baseline,
        spec_dir=canonical_spec_dir,
        old_targets=evidence.canonical_targets,
        replacement_targets=targets,
        artifact_plan=plan_retarget_artifacts(canonical_spec_dir),
        operation_id=operation_id,
        original_user_message=evidence.original_user_message,
        autonomy_mode=evidence.autonomy_mode,
        ignore_re=ignore_re,
        explicit_re_sources=explicit_re_sources,
    )


def _preview_result(preview: RetargetPreview) -> RetargetCommandResult:
    checkpoint_id = f"retarget-preflight-{preview.operation_id}"
    baseline_state = _read_json_object(preview.baseline.run_dir / "state.json")
    return RetargetCommandResult(
        applied=False,
        resume_existing=False,
        spec_id=preview.spec_id,
        baseline_run_id=preview.baseline.run_id,
        replacement_run_id=None,
        replacement_targets=preview.replacement_targets,
        checkpoint_id=None,
        checkpoint_commit=None,
        recovery_command=preview_recovery_command(checkpoint_id),
        invalidated_paths=preview.artifact_plan.invalidate,
        original_user_message=preview.original_user_message,
        autonomy_mode=preview.autonomy_mode,
        ignore_re=preview.ignore_re,
        explicit_re_sources=preview.explicit_re_sources,
        old_targets=preview.old_targets,
        baseline_ready_to_build=baseline_state.get("status") == "done",
    )


def _sync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise RetargetArtifactError(f"retarget output parent is not a real directory: {parent}")
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        metadata = None
    if metadata is not None and not stat.S_ISREG(metadata.st_mode):
        raise RetargetArtifactError(f"retarget output must be a regular file: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _sync_directory(parent)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_relative_artifact_path(value: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise RetargetArtifactError("invalid retarget artifact path")
    relative = Path(value)
    if relative.is_absolute() or relative.parts != (value,) or value in {".", ".."}:
        raise RetargetArtifactError(f"retarget artifact path is not confined: {value!r}")
    return value


def _open_directory_at(parent_fd: int, name: str) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(name, flags, dir_fd=parent_fd)


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        stat.S_IFMT(left.st_mode),
    ) == (
        right.st_dev,
        right.st_ino,
        stat.S_IFMT(right.st_mode),
    )


def _validate_entry_at(
    parent_fd: int,
    name: str,
    *,
    budget: list[int],
    depth: int = 0,
) -> os.stat_result:
    budget[0] += 1
    if budget[0] > _RETARGET_ARTIFACT_ENTRY_CAP or depth > _RETARGET_ARTIFACT_DEPTH_CAP:
        raise RetargetArtifactError("retarget artifact traversal exceeds safety cap")
    metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if stat.S_ISLNK(metadata.st_mode):
        raise RetargetArtifactError(f"retarget artifact must not be a symlink: {name}")
    if stat.S_ISREG(metadata.st_mode):
        return metadata
    if not stat.S_ISDIR(metadata.st_mode):
        raise RetargetArtifactError(f"retarget artifact has unsupported type: {name}")
    try:
        child_fd = _open_directory_at(parent_fd, name)
    except OSError as exc:
        raise RetargetArtifactError(f"retarget artifact changed during validation: {name}") from exc
    try:
        if not _same_inode(metadata, os.fstat(child_fd)):
            raise RetargetArtifactError(
                f"retarget artifact changed during validation: {name}"
            )
        child_names = sorted(entry.name for entry in os.scandir(child_fd))
        for child_name in child_names:
            _validate_entry_at(
                child_fd,
                child_name,
                budget=budget,
                depth=depth + 1,
            )
    finally:
        os.close(child_fd)
    return metadata


def _delete_entry_at(
    parent_fd: int,
    name: str,
    *,
    budget: list[int],
    depth: int = 0,
) -> None:
    metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    budget[0] += 1
    if budget[0] > _RETARGET_ARTIFACT_ENTRY_CAP or depth > _RETARGET_ARTIFACT_DEPTH_CAP:
        raise RetargetArtifactError("retarget artifact deletion exceeds safety cap")
    if stat.S_ISLNK(metadata.st_mode) or stat.S_ISREG(metadata.st_mode):
        os.unlink(name, dir_fd=parent_fd)
        return
    if not stat.S_ISDIR(metadata.st_mode):
        raise RetargetArtifactError(f"retarget quarantine has unsupported type: {name}")
    try:
        child_fd = _open_directory_at(parent_fd, name)
    except OSError as exc:
        raise RetargetArtifactError(
            f"retarget artifact changed during invalidation: {name}"
        ) from exc
    try:
        if not _same_inode(metadata, os.fstat(child_fd)):
            raise RetargetArtifactError(
                f"retarget artifact changed during invalidation: {name}"
            )
        child_names = sorted(entry.name for entry in os.scandir(child_fd))
        for child_name in child_names:
            _delete_entry_at(
                child_fd,
                child_name,
                budget=budget,
                depth=depth + 1,
            )
    finally:
        os.close(child_fd)
    current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not _same_inode(metadata, current):
        raise RetargetArtifactError(
            f"retarget artifact changed during invalidation: {name}"
        )
    os.rmdir(name, dir_fd=parent_fd)


def _quarantine_invalidations(
    root: Path,
    identities: Mapping[str, os.stat_result],
) -> None:
    if not identities:
        return
    root_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        root_flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        root_flags |= os.O_NOFOLLOW
    root_fd = os.open(root, root_flags)
    quarantine_name = f".retarget-quarantine-{secrets.token_hex(16)}"
    quarantine_fd = -1
    try:
        os.mkdir(quarantine_name, 0o700, dir_fd=root_fd)
        quarantine_fd = _open_directory_at(root_fd, quarantine_name)
        for relative, expected in identities.items():
            try:
                observed = os.stat(
                    relative,
                    dir_fd=root_fd,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise RetargetArtifactError(
                    f"retarget artifact changed during invalidation: {relative}"
                ) from exc
            if not _same_inode(expected, observed):
                raise RetargetArtifactError(
                    f"retarget artifact changed during invalidation: {relative}"
                )
            os.rename(
                relative,
                relative,
                src_dir_fd=root_fd,
                dst_dir_fd=quarantine_fd,
            )
            quarantined = os.stat(
                relative,
                dir_fd=quarantine_fd,
                follow_symlinks=False,
            )
            if not _same_inode(expected, quarantined):
                if stat.S_ISLNK(quarantined.st_mode) or stat.S_ISREG(
                    quarantined.st_mode
                ):
                    os.unlink(relative, dir_fd=quarantine_fd)
                raise RetargetArtifactError(
                    f"retarget artifact changed during invalidation: {relative}"
                )
        deletion_budget = [0]
        for relative in identities:
            _delete_entry_at(
                quarantine_fd,
                relative,
                budget=deletion_budget,
            )
        os.close(quarantine_fd)
        quarantine_fd = -1
        os.rmdir(quarantine_name, dir_fd=root_fd)
        _sync_directory(root)
    finally:
        if quarantine_fd >= 0:
            os.close(quarantine_fd)
        try:
            os.rmdir(quarantine_name, dir_fd=root_fd)
        except OSError:
            pass
        os.close(root_fd)


def _require_real_directory(path: Path, *, label: str) -> Path:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise RetargetArtifactError(f"{label} is missing: {path}") from exc
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise RetargetArtifactError(f"{label} must be a real directory: {path}")
    return path.resolve()


def invalidate_retarget_artifacts(
    spec_dir: Path,
    run_shadow_dir: Path,
    artifact_plan: RetargetArtifactPlan,
    replacement_targets: tuple[str, ...],
) -> tuple[str, ...]:
    """Remove only public-plan invalidations and durably replace targets.yml."""

    canonical = _require_real_directory(Path(spec_dir), label="canonical spec directory")
    shadow = _require_real_directory(Path(run_shadow_dir), label="active run shadow")
    targets = _strict_replacement_targets(replacement_targets)
    if type(artifact_plan) is not RetargetArtifactPlan:
        raise RetargetArtifactError("invalid public retarget artifact plan")
    shadow_plan = plan_retarget_artifacts(shadow)
    for plan in (artifact_plan, shadow_plan):
        groups = (plan.preserve, plan.invalidate, plan.not_applicable)
        flattened = tuple(item for group in groups for item in group)
        for item in flattened:
            _validate_relative_artifact_path(item)
        if len(flattened) != len(set(flattened)):
            raise RetargetArtifactError("retarget artifact plan overlaps")
    invalidated = tuple(
        sorted((set(artifact_plan.invalidate) | set(shadow_plan.invalidate)) - {"targets.yml"})
    )
    root_identities: list[tuple[Path, dict[str, os.stat_result]]] = []
    traversal_budget = [0]
    for root, plan in ((canonical, artifact_plan), (shadow, shadow_plan)):
        root_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        identities: dict[str, os.stat_result] = {}
        try:
            for relative in (*plan.preserve, *plan.invalidate):
                try:
                    metadata = _validate_entry_at(
                        root_fd,
                        relative,
                        budget=traversal_budget,
                    )
                except FileNotFoundError:
                    continue
                if relative in invalidated:
                    identities[relative] = metadata
        finally:
            os.close(root_fd)
        root_identities.append((root, identities))
    for root, identities in root_identities:
        _quarantine_invalidations(root, identities)
    content = ("targets:\n" + "".join(f"- {target}\n" for target in targets)).encode(
        "utf-8"
    )
    for root in (canonical, shadow):
        _write_bytes_atomic(root / "targets.yml", content)
    return invalidated


def checkpoint_artifact_bytes(
    project_root: Path,
    commit: str,
    spec_id: str,
    name: str,
) -> bytes:
    """Read one bounded baseline artifact from an exact Git commit object."""

    root = _require_real_directory(Path(project_root), label="project root")
    if type(commit) is not str or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit) is None:
        raise RetargetError("checkpoint context commit is invalid")
    resolved = subprocess.run(
        ["git", "rev-parse", f"{commit}^{{commit}}"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if resolved.returncode != 0 or resolved.stdout.strip() != commit:
        raise RetargetError("checkpoint context commit is unavailable or noncanonical")
    if type(spec_id) is not str or _CANONICAL_SPEC_ID.fullmatch(spec_id) is None:
        raise RetargetError("checkpoint context spec identity is invalid")
    if name not in _RETARGET_CONTEXT_PATHS:
        raise RetargetError(f"checkpoint context path is not allowed: {name!r}")
    git_path = f"specs/{spec_id}/{name}"
    tree = subprocess.run(
        ["git", "ls-tree", "-z", commit, "--", git_path],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if tree.returncode != 0:
        raise RetargetError(f"cannot inspect checkpoint context Git entry: {name}")
    if not tree.stdout:
        return b""
    rows = tuple(row for row in tree.stdout.split(b"\0") if row)
    if len(rows) != 1 or len(rows[0]) > 4096 or b"\t" not in rows[0]:
        raise RetargetError(f"checkpoint context Git entry is ambiguous: {name}")
    header, raw_path = rows[0].split(b"\t", 1)
    fields = header.split()
    if (
        len(fields) != 3
        or fields[0] not in {b"100644", b"100755"}
        or fields[1] != b"blob"
        or raw_path != git_path.encode("utf-8")
    ):
        raise RetargetError(f"checkpoint context must be a regular Git blob: {name}")
    blob_oid = fields[2].decode("ascii")
    result = subprocess.run(
        ["git", "cat-file", "blob", blob_oid],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RetargetError(f"cannot read checkpoint context Git blob: {name}")
    data = bytes(result.stdout)
    if len(data) > _RETARGET_CONTEXT_FILE_CAP:
        raise RetargetError(f"checkpoint context file exceeds cap: {name}")
    return data


def _validate_context_destination(project_root: Path, replacement_run_dir: Path) -> Path:
    root = Path(project_root).resolve()
    run_dir = _require_real_directory(
        Path(replacement_run_dir),
        label="replacement run directory",
    )
    try:
        relative = run_dir.relative_to(root)
    except ValueError as exc:
        raise RetargetError("checkpoint context destination escapes project root") from exc
    if len(relative.parts) != 2 or relative.parts[0] != "runs":
        raise RetargetError("checkpoint context destination is not a replacement run")
    context_parent = run_dir / "context"
    destination = context_parent / "retarget-baseline"
    for path, label in (
        (context_parent, "context parent"),
        (destination, "retarget context directory"),
    ):
        if path.exists() or path.is_symlink():
            try:
                metadata = path.lstat()
            except OSError as exc:
                raise RetargetError(f"cannot inspect {label}") from exc
            if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                raise RetargetError(f"{label} must be a real directory")
    for name in (*_RETARGET_CONTEXT_PATHS, "README.md", "manifest.json"):
        target = destination / name
        if target.exists() or target.is_symlink():
            metadata = target.lstat()
            if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                raise RetargetError(f"checkpoint context output must be regular: {name}")
    return destination


def write_checkpoint_coverage_context(
    project_root: Path,
    commit: str,
    spec_id: str,
    replacement_run_dir: Path,
) -> dict[str, object]:
    """Materialize bounded, non-authoritative baseline bytes read only from Git."""

    destination = _validate_context_destination(project_root, replacement_run_dir)
    payloads = tuple(
        (name, checkpoint_artifact_bytes(project_root, commit, spec_id, name))
        for name in _RETARGET_CONTEXT_PATHS
    )
    total = sum(len(content) for _name, content in payloads)
    if total > _RETARGET_CONTEXT_TOTAL_CAP:
        raise RetargetError("checkpoint context total exceeds cap")
    manifest: dict[str, object] = {
        "label": "NON-AUTHORITATIVE RETARGET COVERAGE CONTEXT",
        "checkpoint_commit": commit,
        "spec_id": spec_id,
        "files": [
            {
                "path": name,
                "bytes": len(content),
                "sha256": f"sha256:{hashlib.sha256(content).hexdigest()}",
            }
            for name, content in payloads
            if content
        ],
    }
    destination.parent.mkdir(exist_ok=True)
    _sync_directory(destination.parent.parent)
    destination.mkdir(exist_ok=True)
    _sync_directory(destination.parent)
    for name, content in payloads:
        if content:
            _write_bytes_atomic(destination / name, content)
    _write_bytes_atomic(
        destination / "README.md",
        b"NON-AUTHORITATIVE RETARGET COVERAGE CONTEXT\n",
    )
    _write_bytes_atomic(
        destination / "manifest.json",
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return manifest


def _baseline_state(preview: RetargetPreview) -> dict[str, Any]:
    return _read_json_object(preview.baseline.run_dir / "state.json")


def _replacement_run_id(preview: RetargetPreview) -> str:
    return f"squad-retarget-{preview.operation_id.removeprefix('retarget-')[:24]}"


def append_prepared_revision_from_preview(preview: RetargetPreview) -> RetargetRevision:
    state = _baseline_state(preview)
    completed = state.get("completed_phases", ())
    if type(completed) is not list or any(type(item) is not str for item in completed):
        raise RetargetRebuildError("baseline completed phase evidence is invalid")
    projection = RetargetRecoveryProjection(
        run_id=preview.baseline.run_id,
        status=str(state.get("status") or "preparing"),
        phase=str(state.get("phase") or "phase0-constitution"),
        spec_status=str(read_frontmatter(preview.spec_dir).get("status") or "planned"),
        completed_phases=tuple(completed),
        implementation_targets=preview.old_targets,
        ready_to_build=state.get("status") == "done",
    )
    return append_prepared_revision(
        preview.spec_dir,
        operation_id=preview.operation_id,
        baseline_run_id=preview.baseline.run_id,
        replacement_run_id=_replacement_run_id(preview),
        old_targets=preview.old_targets,
        replacement_targets=preview.replacement_targets,
        original_prompt_digest=(
            "sha256:"
            + hashlib.sha256(preview.original_user_message.encode("utf-8")).hexdigest()
        ),
        recovery=projection,
    )


def require_same_retarget_preflight(preview: RetargetPreview) -> RetargetPreview:
    observed = _build_retarget_preview(
        preview.project_root,
        preview.spec_id,
        preview.replacement_targets,
    )
    if observed != preview:
        raise RetargetEligibilityError("retarget preflight evidence changed while locking")
    return observed


def start_retarget_phase_a_spec_from_preview(
    preview: RetargetPreview,
    revision: RetargetRevision,
    checkpoint: PhaseCheckpoint,
) -> RetargetPhaseAStartOutcome:
    retarget_state = {
        "operation_id": preview.operation_id,
        "revision_id": revision.revision_id,
        "status": "checkpointed",
        "failure_code": None,
        "baseline_run_id": preview.baseline.run_id,
        "replacement_run_id": revision.replacement_run_id,
        "old_targets": list(preview.old_targets),
        "replacement_targets": list(preview.replacement_targets),
        "checkpoint_id": checkpoint.id,
        "checkpoint_commit": checkpoint.commit,
    }
    try:
        return start_retarget_phase_a_spec(
            preview.project_root,
            replacement_run_id=revision.replacement_run_id,
            baseline=preview.baseline,
            checkpoint_commit=checkpoint.commit,
            replacement_targets=preview.replacement_targets,
            retarget_state=retarget_state,
        )
    except PhaseAStartError as exc:
        raise RetargetRebuildError(str(exc)) from exc


def _update_run_retarget(run_dir: Path, **updates: object) -> dict[str, Any]:
    state_path = Path(run_dir) / "state.json"
    state = _read_json_object(state_path)
    retarget = state.get("retarget")
    if type(retarget) is not dict:
        raise RetargetRebuildError("replacement run retarget state is missing")
    revised = dict(retarget)
    revised.update(updates)
    state["retarget"] = revised
    content = (json.dumps(state, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        _write_bytes_atomic(state_path, content)
    except RetargetArtifactError as exc:
        raise RetargetRebuildError(str(exc)) from exc
    return state


def persist_retarget_memory_exclusion(run_dir: Path, receipt: object) -> None:
    to_dict = getattr(receipt, "to_dict", None)
    if not callable(to_dict):
        raise RetargetMemoryError("retarget memory receipt is invalid")
    _update_run_retarget(
        run_dir,
        memory_excluded=True,
        memory_purge=to_dict(),
    )


def mark_retarget_rebuilding(
    run_dir: Path,
    spec_dir: Path,
    memory: object,
    graph: object,
) -> None:
    memory_dict = memory.to_dict()
    graph_dict = graph.to_dict()
    state = _update_run_retarget(
        run_dir,
        status="rebuilding",
        failure_code=None,
        memory_purge=memory_dict,
        graph_invalidation=graph_dict,
    )
    revision_id = str(state["retarget"]["revision_id"])
    try:
        advance_retarget_revision(
            spec_dir,
            revision_id,
            expected_status="invalidating",
            status="rebuilding",
            updates={
                "memory_purge": memory_dict,
                "graph_invalidation": graph_dict,
            },
        )
    except ValueError as exc:
        raise RetargetRebuildError(str(exc)) from exc


def mark_retarget_failed(run_dir: Path, spec_dir: Path, failure_code: str) -> None:
    history = load_retarget_history(spec_dir)
    if not history.revisions:
        raise RetargetRebuildError("retarget revision is missing while recording failure")
    latest = history.revisions[-1]
    if latest.status not in {"prepared", "invalidating", "rebuilding", "finalizing"}:
        raise RetargetRebuildError("retarget revision is not failure-eligible")
    state = _update_run_retarget(run_dir, status="failed", failure_code=failure_code)
    retarget = state["retarget"]
    assert isinstance(retarget, dict)
    revision_id = str(retarget["revision_id"])
    if latest.revision_id != revision_id:
        raise RetargetRebuildError("retarget revision identity changed while failing")
    try:
        advance_retarget_revision(
            spec_dir,
            revision_id,
            expected_status=latest.status,
            status="failed",
            updates={"failure_code": failure_code},
        )
    except ValueError as exc:
        raise RetargetRebuildError(str(exc)) from exc


def mark_retarget_failed_before_bootstrap(
    preview: RetargetPreview,
    revision: RetargetRevision,
    checkpoint: PhaseCheckpoint,
    failure_code: str,
) -> None:
    replacement_dir = preview.project_root / "runs" / revision.replacement_run_id
    state_path = replacement_dir / "state.json"
    if state_path.exists() or state_path.is_symlink():
        mark_retarget_failed(replacement_dir, preview.spec_dir, failure_code)
        return
    history = load_retarget_history(preview.spec_dir)
    if (
        not history.revisions
        or history.revisions[-1].revision_id != revision.revision_id
        or history.revisions[-1].status != "prepared"
    ):
        raise RetargetRebuildError("prepared retarget revision changed while failing")
    try:
        advance_retarget_revision(
            preview.spec_dir,
            revision.revision_id,
            expected_status="prepared",
            status="failed",
            updates={
                "checkpoint_id": checkpoint.id,
                "checkpoint_commit": checkpoint.commit,
                "failure_code": failure_code,
            },
        )
    except ValueError as exc:
        raise RetargetRebuildError(str(exc)) from exc


def _applied_result(
    preview: RetargetPreview,
    revision: RetargetRevision,
    replacement: object,
    checkpoint: PhaseCheckpoint,
    invalidated: tuple[str, ...],
    *,
    resume_existing: bool = False,
) -> RetargetCommandResult:
    replacement_run = getattr(replacement, "run", None)
    replacement_id = getattr(replacement_run, "run_id", None) or revision.replacement_run_id
    recovery = getattr(revision, "recovery", None)
    return RetargetCommandResult(
        applied=True,
        resume_existing=resume_existing,
        spec_id=preview.spec_id,
        baseline_run_id=preview.baseline.run_id,
        replacement_run_id=replacement_id,
        replacement_targets=preview.replacement_targets,
        checkpoint_id=checkpoint.id,
        checkpoint_commit=checkpoint.commit,
        recovery_command=preview_recovery_command(checkpoint.id),
        invalidated_paths=invalidated,
        original_user_message=preview.original_user_message,
        autonomy_mode=preview.autonomy_mode,
        ignore_re=preview.ignore_re,
        explicit_re_sources=preview.explicit_re_sources,
        old_targets=preview.old_targets,
        baseline_ready_to_build=getattr(recovery, "ready_to_build", False) is True,
    )


def _recorded_checkpoint(
    spec_dir: Path,
    revision: RetargetRevision,
    checkpoint_id: str,
    checkpoint_commit: str,
) -> PhaseCheckpoint:
    try:
        checkpoint = resolve_checkpoint(
            load_checkpoint_ledger(spec_dir),
            f"checkpoint:{checkpoint_id}",
        )
    except (KeyError, OSError, ValueError, PhaseCheckpointError) as exc:
        raise RetargetEligibilityError(
            f"recorded retarget checkpoint is unavailable\n"
            f"  Recovery: {preview_recovery_command(checkpoint_id)}"
        ) from exc
    if (
        checkpoint.id != checkpoint_id
        or checkpoint.commit != checkpoint_commit
        or checkpoint.spec_id != spec_dir.name
        or checkpoint.run_id != revision.baseline_run_id
        or checkpoint.phase != "retarget"
        or checkpoint.next_phase != "phase0-constitution"
        or checkpoint.source != "retarget-preflight"
    ):
        raise RetargetEligibilityError(
            f"recorded retarget checkpoint identity drifted\n"
            f"  Recovery: {preview_recovery_command(checkpoint_id)}"
        )
    return checkpoint


_MEMORY_RECEIPT_LIST_FIELDS = frozenset(
    {
        "deleted_ids",
        "remaining_owned_ids",
        "unrelated_missing_ids",
        "unrelated_changed_ids",
        "unexpected_added_ids",
    }
)


def _persisted_memory_receipt(run_dir: Path) -> RetargetMemoryReceipt | None:
    state = _read_json_object(Path(run_dir) / "state.json")
    retarget = state.get("retarget")
    if type(retarget) is not dict or retarget.get("memory_excluded") is not True:
        return None
    raw = retarget.get("memory_purge")
    expected = frozenset(RetargetMemoryReceipt.__dataclass_fields__)
    if type(raw) is not dict or frozenset(raw) != expected:
        raise RetargetMemoryError("persisted retarget memory receipt is invalid")
    values = dict(raw)
    for field in _MEMORY_RECEIPT_LIST_FIELDS:
        value = values[field]
        if type(value) is not list:
            raise RetargetMemoryError("persisted retarget memory receipt is invalid")
        values[field] = tuple(value)
    try:
        return RetargetMemoryReceipt(**values)
    except (TypeError, ValueError) as exc:
        raise RetargetMemoryError(
            "persisted retarget memory receipt is invalid"
        ) from exc


def _finish_retarget_invalidation(
    preview: RetargetPreview,
    revision: RetargetRevision,
    checkpoint: PhaseCheckpoint,
    replacement: RetargetPhaseAStartOutcome,
    *,
    starting_status: str,
    reuse_persisted_memory: bool = False,
) -> tuple[str, ...]:
    run_dir = replacement.run.run_dir
    try:
        if starting_status == "checkpointed":
            advance_retarget_revision(
                preview.spec_dir,
                revision.revision_id,
                expected_status="prepared",
                status="invalidating",
                updates={
                    "checkpoint_id": checkpoint.id,
                    "checkpoint_commit": checkpoint.commit,
                },
            )
            _update_run_retarget(run_dir, status="invalidating")
        elif starting_status != "invalidating":
            raise RetargetRebuildError(
                f"retarget destructive stage cannot resume from {starting_status!r}"
            )

        memory = _persisted_memory_receipt(run_dir) if reuse_persisted_memory else None
        if memory is None:
            memory = purge_retarget_spec_memory(
                preview.project_root,
                preview.spec_id,
            )
            persist_retarget_memory_exclusion(run_dir, memory)
        shadow_dir = run_dir / "specs" / preview.spec_id
        invalidated = invalidate_retarget_artifacts(
            preview.spec_dir,
            shadow_dir,
            preview.artifact_plan,
            preview.replacement_targets,
        )
        graph = invalidate_retarget_graphs(
            preview.project_root,
            preview.spec_dir,
        )
        write_checkpoint_coverage_context(
            preview.project_root,
            checkpoint.commit,
            preview.spec_id,
            run_dir,
        )
        mark_retarget_rebuilding(
            run_dir,
            preview.spec_dir,
            memory,
            graph,
        )
        return invalidated
    except Exception as exc:
        code = bounded_failure_code(exc)
        try:
            mark_retarget_failed(run_dir, preview.spec_dir, code)
        except Exception as state_exc:
            raise RetargetDestructiveError(checkpoint, state_exc) from exc
        raise RetargetDestructiveError(checkpoint, exc) from exc


def _apply_retarget(
    preview: RetargetPreview,
    *,
    checkpoint_created: Callable[[PhaseCheckpoint], None] | None,
) -> RetargetCommandResult:
    operation_id = preview.operation_id
    with SpecMutationLock.acquire(preview.project_root, preview.spec_id, operation_id):
        with PhaseAExecutionLock.acquire(preview.project_root, operation_id):
            with SpecRunExecutionLock.acquire(preview.baseline.run_dir, operation_id):
                rechecked = require_same_retarget_preflight(preview)
                revision = append_prepared_revision_from_preview(rechecked)
                try:
                    checkpoint = commit_retarget_checkpoint(
                        project_root=preview.project_root,
                        spec_dir=preview.spec_dir,
                        run_id=preview.baseline.run_id,
                        revision_id=revision.revision_id,
                    )
                except PhaseCheckpointError as exc:
                    raise RetargetCheckpointError(str(exc)) from exc
                if checkpoint_created is not None:
                    checkpoint_created(checkpoint)
                try:
                    replacement = start_retarget_phase_a_spec_from_preview(
                        rechecked,
                        revision,
                        checkpoint,
                    )
                except Exception as exc:
                    code = bounded_failure_code(exc)
                    try:
                        mark_retarget_failed_before_bootstrap(
                            rechecked,
                            revision,
                            checkpoint,
                            code,
                        )
                    except Exception as state_exc:
                        raise RetargetDestructiveError(checkpoint, state_exc) from exc
                    raise RetargetDestructiveError(checkpoint, exc) from exc
                invalidated = _finish_retarget_invalidation(
                    rechecked,
                    revision,
                    checkpoint,
                    replacement,
                    starting_status="checkpointed",
                )
    return _applied_result(preview, revision, replacement, checkpoint, invalidated)


_RESUMABLE_RETARGET_STATUSES = frozenset(
    {"checkpointed", "invalidating", "rebuilding", "finalizing"}
)


def _detect_existing_retarget(
    project_root: Path,
    spec_id: str,
    replacement_targets: tuple[str, ...],
    *,
    confirm: bool,
) -> RetargetCommandResult | None:
    """Resolve a durable active retarget before ordinary ambiguous-run preflight."""

    root = Path(project_root).resolve()
    try:
        active = resolve_active_spec_run(root)
    except SpecLifecycleError:
        return None
    state = _read_json_object(active.run_dir / "state.json")
    raw_retarget = state.get("retarget")
    if raw_retarget is None:
        return None
    if type(raw_retarget) is not dict:
        raise RetargetEligibilityError("active retarget state is corrupt")
    checkpoint_id = raw_retarget.get("checkpoint_id")
    if type(checkpoint_id) is not str or not checkpoint_id:
        raise RetargetEligibilityError("active retarget checkpoint identity is corrupt")
    recovery = preview_recovery_command(checkpoint_id)
    status = raw_retarget.get("status")
    if status in {"complete", "recovered"}:
        return None
    recorded_raw = raw_retarget.get("replacement_targets")
    try:
        recorded = _strict_replacement_targets(
            tuple(recorded_raw) if type(recorded_raw) is list else recorded_raw
        )
    except (RetargetEligibilityError, TypeError) as exc:
        raise RetargetEligibilityError(
            f"active retarget target evidence is corrupt\n  Recovery: {recovery}"
        ) from exc
    if active.spec_id != spec_id or recorded != replacement_targets:
        raise RetargetEligibilityError(
            "retarget retry does not match the recorded operation"
            f"\n  Recovery: {recovery}"
        )
    if status not in _RESUMABLE_RETARGET_STATUSES | {"failed"}:
        raise RetargetEligibilityError(
            f"active retarget status is not resumable: {status!r}"
            f"\n  Recovery: {recovery}"
        )
    baseline_id = raw_retarget.get("baseline_run_id")
    replacement_id = raw_retarget.get("replacement_run_id")
    checkpoint_commit = raw_retarget.get("checkpoint_commit")
    revision_id = raw_retarget.get("revision_id")
    operation_id = raw_retarget.get("operation_id")
    if (
        type(baseline_id) is not str
        or not baseline_id
        or type(replacement_id) is not str
        or replacement_id != active.run_id
        or type(checkpoint_commit) is not str
        or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", checkpoint_commit) is None
        or type(revision_id) is not str
        or not revision_id
        or type(operation_id) is not str
        or not operation_id
    ):
        raise RetargetEligibilityError(
            f"active retarget identity is corrupt\n  Recovery: {recovery}"
        )
    try:
        history = load_retarget_history(root / "specs" / spec_id)
    except ValueError as exc:
        raise RetargetEligibilityError(
            f"active retarget history is corrupt\n  Recovery: {recovery}"
        ) from exc
    expected_history_status = "prepared" if status == "checkpointed" else status
    if not history.revisions:
        raise RetargetEligibilityError(
            f"active retarget history is missing\n  Recovery: {recovery}"
        )
    latest = history.revisions[-1]
    checkpoint_matches = (
        latest.checkpoint_id == checkpoint_id
        and latest.checkpoint_commit == checkpoint_commit
    ) or (
        status == "checkpointed"
        and latest.checkpoint_id is None
        and latest.checkpoint_commit is None
    )
    if (
        latest.revision_id != revision_id
        or latest.operation_id != operation_id
        or latest.status != expected_history_status
        or latest.baseline_run_id != baseline_id
        or latest.replacement_run_id != replacement_id
        or latest.replacement_targets != recorded
        or not checkpoint_matches
    ):
        raise RetargetEligibilityError(
            f"active retarget history does not match runtime state\n  Recovery: {recovery}"
        )
    if status == "failed":
        raise RetargetEligibilityError(
            "retarget is durably failed and requires rewind"
            f"\n  Recovery: {recovery}"
        )
    user_message = _first_text(state, "original_user_message", "user_message")
    autonomy_mode = _first_text(state, "autonomy_mode", "mode")
    if not user_message or not autonomy_mode:
        raise RetargetEligibilityError(
            f"active retarget original intent is missing\n  Recovery: {recovery}"
        )
    ignore_re, explicit_re_sources = _original_re_policy(active.run_dir)
    return RetargetCommandResult(
        applied=confirm,
        resume_existing=True,
        spec_id=spec_id,
        baseline_run_id=baseline_id,
        replacement_run_id=replacement_id,
        replacement_targets=recorded,
        checkpoint_id=checkpoint_id,
        checkpoint_commit=checkpoint_commit,
        recovery_command=recovery,
        invalidated_paths=(),
        original_user_message=user_message,
        autonomy_mode=autonomy_mode,
        ignore_re=ignore_re,
        explicit_re_sources=explicit_re_sources,
        old_targets=latest.old_targets,
        baseline_ready_to_build=latest.recovery.ready_to_build,
    )


def _active_retry_preview(
    project_root: Path,
    active: SpecRun,
    baseline: SpecRun,
    revision: RetargetRevision,
    result: RetargetCommandResult,
) -> RetargetPreview:
    root = Path(project_root).resolve()
    canonical = _require_canonical_published_spec(root, baseline)
    if _require_canonical_published_spec(root, active) != canonical:
        raise RetargetEligibilityError("replacement published spec binding drifted")
    return RetargetPreview(
        project_root=root,
        spec_id=result.spec_id,
        baseline=baseline,
        spec_dir=canonical,
        old_targets=revision.old_targets,
        replacement_targets=result.replacement_targets,
        artifact_plan=plan_retarget_artifacts(canonical),
        operation_id=revision.operation_id,
        original_user_message=result.original_user_message,
        autonomy_mode=result.autonomy_mode,
        ignore_re=result.ignore_re,
        explicit_re_sources=result.explicit_re_sources,
    )


def _resume_existing_retarget(
    project_root: Path,
    result: RetargetCommandResult,
    *,
    checkpoint_created: Callable[[PhaseCheckpoint], None] | None,
) -> RetargetCommandResult:
    root = Path(project_root).resolve()
    baseline = resolve_spec_run(root, result.baseline_run_id)
    history = load_retarget_history(root / "specs" / result.spec_id)
    if not history.revisions:
        raise RetargetEligibilityError("active retarget history is missing")
    operation_id = history.revisions[-1].operation_id
    with SpecMutationLock.acquire(root, result.spec_id, operation_id):
        with PhaseAExecutionLock.acquire(root, operation_id):
            with SpecRunExecutionLock.acquire(baseline.run_dir, operation_id):
                observed = _detect_existing_retarget(
                    root,
                    result.spec_id,
                    result.replacement_targets,
                    confirm=True,
                )
                if observed != result:
                    raise RetargetEligibilityError(
                        "active retarget evidence changed while locking"
                    )
                active = resolve_active_spec_run(root)
                state = _read_json_object(active.run_dir / "state.json")
                retarget = state.get("retarget")
                if type(retarget) is not dict:
                    raise RetargetEligibilityError("active retarget state is corrupt")
                status = retarget.get("status")
                if status in {"rebuilding", "finalizing"}:
                    return result
                if status not in {"checkpointed", "invalidating"}:
                    raise RetargetEligibilityError(
                        f"active retarget status is not resumable: {status!r}"
                    )
                history = load_retarget_history(root / "specs" / result.spec_id)
                revision = history.revisions[-1]
                assert result.checkpoint_id is not None
                assert result.checkpoint_commit is not None
                checkpoint = _recorded_checkpoint(
                    root / "specs" / result.spec_id,
                    revision,
                    result.checkpoint_id,
                    result.checkpoint_commit,
                )
                preview = _active_retry_preview(
                    root,
                    active,
                    baseline,
                    revision,
                    result,
                )
                if checkpoint_created is not None:
                    checkpoint_created(checkpoint)
                replacement = RetargetPhaseAStartOutcome(
                    run_dir=active.run_dir,
                    run=active,
                    baseline=baseline,
                )
                invalidated = _finish_retarget_invalidation(
                    preview,
                    revision,
                    checkpoint,
                    replacement,
                    starting_status=status,
                    reuse_persisted_memory=True,
                )
    return _applied_result(
        preview,
        revision,
        replacement,
        checkpoint,
        invalidated,
        resume_existing=True,
    )


def _detect_prepared_retarget(
    project_root: Path,
    spec_id: str,
    replacement_targets: tuple[str, ...],
) -> tuple[RetargetPreview, RetargetRevision, PhaseCheckpoint] | None:
    root = Path(project_root).resolve()
    canonical = root / "specs" / spec_id
    try:
        history = load_retarget_history(canonical)
    except ValueError as exc:
        raise RetargetEligibilityError("prepared retarget history is corrupt") from exc
    if not history.revisions or history.revisions[-1].status != "prepared":
        return None
    revision = history.revisions[-1]
    checkpoint_id = f"retarget-preflight-{revision.revision_id}"
    recovery = preview_recovery_command(checkpoint_id)
    if revision.replacement_targets != replacement_targets:
        raise RetargetEligibilityError(
            f"retarget retry does not match the recorded operation\n  Recovery: {recovery}"
        )
    try:
        ledger_checkpoint = resolve_checkpoint(
            load_checkpoint_ledger(canonical),
            f"checkpoint:{checkpoint_id}",
        )
    except (KeyError, OSError, ValueError, PhaseCheckpointError) as exc:
        raise RetargetEligibilityError(
            f"prepared retarget checkpoint is unavailable\n  Recovery: {recovery}"
        ) from exc
    checkpoint = _recorded_checkpoint(
        canonical,
        revision,
        checkpoint_id,
        ledger_checkpoint.commit,
    )
    try:
        baseline = resolve_spec_run(root, revision.baseline_run_id)
        active = resolve_active_spec_run(root)
    except SpecLifecycleError as exc:
        raise RetargetEligibilityError(
            f"prepared retarget baseline is unavailable\n  Recovery: {recovery}"
        ) from exc
    if active != baseline:
        raise RetargetEligibilityError(
            f"prepared retarget baseline is no longer active\n  Recovery: {recovery}"
        )
    published = _require_canonical_published_spec(root, baseline)
    baseline_state = _read_json_object(baseline.run_dir / "state.json")
    if (
        _canonical_targets(published) != revision.old_targets
        or _state_targets(baseline_state) != revision.old_targets
    ):
        raise RetargetEligibilityError(
            f"prepared retarget baseline target evidence drifted\n  Recovery: {recovery}"
        )
    user_message = _first_text(
        baseline_state,
        "original_user_message",
        "user_message",
    )
    autonomy_mode = _first_text(baseline_state, "autonomy_mode", "mode")
    digest = "sha256:" + hashlib.sha256(user_message.encode("utf-8")).hexdigest()
    if not user_message or not autonomy_mode or digest != revision.original_prompt_digest:
        raise RetargetEligibilityError(
            f"prepared retarget original intent drifted\n  Recovery: {recovery}"
        )
    ignore_re, explicit_re_sources = _original_re_policy(baseline.run_dir)
    preview = RetargetPreview(
        project_root=root,
        spec_id=spec_id,
        baseline=baseline,
        spec_dir=published,
        old_targets=revision.old_targets,
        replacement_targets=revision.replacement_targets,
        artifact_plan=plan_retarget_artifacts(published),
        operation_id=revision.operation_id,
        original_user_message=user_message,
        autonomy_mode=autonomy_mode,
        ignore_re=ignore_re,
        explicit_re_sources=explicit_re_sources,
    )
    if _replacement_run_id(preview) != revision.replacement_run_id:
        raise RetargetEligibilityError(
            f"prepared retarget replacement identity drifted\n  Recovery: {recovery}"
        )
    return preview, revision, checkpoint


def _prepared_retry_result(
    preview: RetargetPreview,
    revision: RetargetRevision,
    checkpoint: PhaseCheckpoint,
    *,
    applied: bool,
) -> RetargetCommandResult:
    result = _applied_result(
        preview,
        revision,
        None,
        checkpoint,
        (),
        resume_existing=True,
    )
    return replace(result, applied=applied)


def _adopt_prepared_retarget(
    prepared: tuple[RetargetPreview, RetargetRevision, PhaseCheckpoint],
    *,
    checkpoint_created: Callable[[PhaseCheckpoint], None] | None,
) -> RetargetCommandResult:
    preview, revision, checkpoint = prepared
    operation_id = revision.operation_id
    with SpecMutationLock.acquire(preview.project_root, preview.spec_id, operation_id):
        with PhaseAExecutionLock.acquire(preview.project_root, operation_id):
            with SpecRunExecutionLock.acquire(preview.baseline.run_dir, operation_id):
                observed = _detect_prepared_retarget(
                    preview.project_root,
                    preview.spec_id,
                    preview.replacement_targets,
                )
                if observed != prepared:
                    raise RetargetEligibilityError(
                        "prepared retarget evidence changed while locking"
                    )
                if checkpoint_created is not None:
                    checkpoint_created(checkpoint)
                try:
                    replacement = start_retarget_phase_a_spec_from_preview(
                        preview,
                        revision,
                        checkpoint,
                    )
                except Exception as exc:
                    code = bounded_failure_code(exc)
                    try:
                        mark_retarget_failed_before_bootstrap(
                            preview,
                            revision,
                            checkpoint,
                            code,
                        )
                    except Exception as state_exc:
                        raise RetargetDestructiveError(checkpoint, state_exc) from exc
                    raise RetargetDestructiveError(checkpoint, exc) from exc
                invalidated = _finish_retarget_invalidation(
                    preview,
                    revision,
                    checkpoint,
                    replacement,
                    starting_status="checkpointed",
                )
    return _applied_result(
        preview,
        revision,
        replacement,
        checkpoint,
        invalidated,
        resume_existing=True,
    )


def prepare_spec_retarget(
    project_root: Path,
    spec_id: str,
    replacement_targets: tuple[str, ...],
    *,
    confirm: bool,
    checkpoint_created: Callable[[PhaseCheckpoint], None] | None = None,
) -> RetargetCommandResult:
    """Preview or prepare one complete target-set replacement."""

    targets = _strict_replacement_targets(replacement_targets)
    retry = _detect_existing_retarget(
        project_root,
        spec_id,
        targets,
        confirm=confirm,
    )
    if retry is not None:
        if confirm:
            return _resume_existing_retarget(
                project_root,
                retry,
                checkpoint_created=checkpoint_created,
            )
        return retry
    prepared = _detect_prepared_retarget(project_root, spec_id, targets)
    if prepared is not None:
        if not confirm:
            return _prepared_retry_result(*prepared, applied=False)
        return _adopt_prepared_retarget(
            prepared,
            checkpoint_created=checkpoint_created,
        )
    preview = _build_retarget_preview(project_root, spec_id, targets)
    if not confirm:
        return _preview_result(preview)
    return _apply_retarget(preview, checkpoint_created=checkpoint_created)


def classify_retarget(evidence: RetargetEvidence) -> RetargetEligibility:
    """Classify already-collected evidence without performing any I/O.

    Eligibility deliberately never calls ``artifact_index.infer_lifecycle_stage``:
    Phase A history is a build marker for that presentation-only helper.
    """

    reasons: list[str] = []
    canonical_targets = _normalized_targets(evidence.canonical_targets)
    state_targets = _normalized_targets(evidence.state_targets)
    replacement_targets = _normalized_targets(evidence.replacement_targets)
    active_matches = (
        evidence.active_run_id == evidence.run_id
        and evidence.current_branch == evidence.feature_branch
    )
    if not active_matches:
        reasons.append("retarget_active_spec_mismatch")
    if not canonical_targets:
        reasons.append("retarget_target_contract_invalid")
    if state_targets != canonical_targets:
        reasons.append("retarget_target_contract_mismatch")
    if not replacement_targets:
        reasons.append("retarget_target_set_empty")
    elif replacement_targets == canonical_targets:
        reasons.append("retarget_target_set_unchanged")
    if (
        evidence.phase_b_history
        or evidence.delivery_state_paths
        or evidence.completed_task_ids
        or evidence.post_phase_a_artifacts
        or evidence.lifecycle_status in _POST_PHASE_A_STATUSES
    ):
        reasons.append("retarget_delivery_already_started")
    elif evidence.lifecycle_status not in _PRE_DELIVERY_STATUSES:
        reasons.append("retarget_lifecycle_ambiguous")
    if evidence.selected_spec_dirty_paths:
        reasons.append("retarget_selected_spec_dirty")
    if not evidence.original_user_message or not evidence.product_inputs_recoverable:
        reasons.append("retarget_original_intent_missing")
    if not evidence.published_re_recoverable:
        reasons.append("retarget_re_context_missing")
    new_spec_command = shlex.join(
        [
            "echelon",
            "spec",
            "run",
            evidence.original_user_message,
            *(
                token
                for target in replacement_targets
                for token in ("--target", target)
            ),
        ]
    )
    next_command = (
        f"echelon spec switch {evidence.spec_id}"
        if "retarget_active_spec_mismatch" in reasons
        else new_spec_command
    )
    return RetargetEligibility(not reasons, tuple(dict.fromkeys(reasons)), next_command)


def collect_retarget_evidence(project_root: Path, spec_id: str) -> RetargetEvidence:
    """Read the complete retarget safety record for one selected spec run.

    The collector is intentionally separate from classification and only reads
    canonical spec data, run state, delivery evidence, and selected-spec Git
    status.  It does not acquire locks or write preview data.
    """

    root = Path(project_root).resolve()
    selected_id = str(spec_id).strip()
    if not selected_id:
        raise RetargetEligibilityError("spec id is empty")
    try:
        run = resolve_spec_run(root, selected_id)
        active = resolve_active_spec_run(root)
        observed_branch = current_branch(root)
    except (SpecLifecycleError, GitHelperError) as exc:
        raise RetargetEligibilityError(str(exc)) from exc

    if run.spec_id != selected_id or run.feature_branch != selected_id:
        raise RetargetEligibilityError(
            f"selected spec identity does not agree with requested spec: {selected_id!r}"
        )
    state = _read_json_object(run.run_dir / "state.json")
    spec_dir = _require_canonical_published_spec(root, run)
    canonical_targets = _canonical_targets(spec_dir)
    state_targets = _state_targets(state)
    lifecycle_status = str(read_frontmatter(spec_dir).get("status") or "").strip().lower()
    return RetargetEvidence(
        spec_id=run.spec_id,
        run_id=run.run_id,
        run_dir=run.run_dir,
        spec_dir=spec_dir,
        feature_branch=run.feature_branch,
        current_branch=observed_branch,
        active_run_id=active.run_id,
        canonical_targets=canonical_targets,
        state_targets=state_targets,
        replacement_targets=canonical_targets,
        lifecycle_status=lifecycle_status,
        phase_b_history=_phase_b_history(spec_dir),
        delivery_state_paths=_delivery_state_paths(root, run.spec_id),
        completed_task_ids=_completed_task_ids(spec_dir),
        post_phase_a_artifacts=_post_phase_a_artifacts(spec_dir),
        selected_spec_dirty_paths=_selected_spec_dirty_paths(root, spec_dir),
        original_user_message=_first_text(state, "original_user_message", "user_message"),
        autonomy_mode=_first_text(state, "autonomy_mode", "mode"),
        product_inputs_recoverable=_product_inputs_recoverable(spec_dir, state),
        published_re_recoverable=_published_re_recoverable(spec_dir, state),
    )


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RetargetEligibilityError(f"cannot read active run state {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RetargetEligibilityError(f"active run state must be a JSON object: {path}")
    return value


def _canonical_targets(spec_dir: Path) -> tuple[str, ...]:
    """Use targets.yml only; frontmatter fallback is not a retarget contract."""

    path = spec_dir / "targets.yml"
    if not path.is_file():
        return ()
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return ()
    if not isinstance(payload, dict) or not isinstance(payload.get("targets"), list):
        return ()
    raw_targets = payload["targets"]
    if not raw_targets:
        return ()
    paths: list[str] = []
    for entry in raw_targets:
        if isinstance(entry, str):
            candidate = entry
        elif isinstance(entry, Mapping) and isinstance(entry.get("path"), str):
            candidate = entry["path"]
        else:
            return ()
        normalized = _normalized_targets((candidate,))
        if not normalized:
            return ()
        paths.append(normalized[0])
    return _normalized_targets(paths)


def _state_targets(state: Mapping[str, object]) -> tuple[str, ...]:
    value = state.get("implementation_targets")
    if value is None:
        value = state.get("targets")
    if value is None:
        value = state.get("target_paths")
    if isinstance(value, Mapping):
        value = value.get("targets")
    if isinstance(value, str):
        value = (value,)
    return _normalized_targets(value if isinstance(value, Iterable) else ())


def _normalized_targets(values: Iterable[object]) -> tuple[str, ...]:
    return normalize_target_set(values)


def _phase_b_history(spec_dir: Path) -> tuple[str, ...]:
    evidence: list[str] = []
    for filename in _HISTORY_FILES:
        path = spec_dir / filename
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            evidence.append(f"{filename}:unreadable")
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("runs"), list):
            evidence.append(f"{filename}:unreadable")
            continue
        for index, row in enumerate(payload["runs"]):
            if not isinstance(row, dict):
                evidence.append(f"{filename}:unreadable")
                continue
            is_phase_b = filename == "harness-run-history.json" or str(
                row.get("phase") or ""
            ).strip().upper() == "B"
            if is_phase_b:
                identity = _first_text(row, "build_id", "run_id") or str(index + 1)
                evidence.append(f"{filename}:{identity}")
    return tuple(sorted(set(evidence)))


def _delivery_state_paths(project_root: Path, spec_id: str) -> tuple[str, ...]:
    runs = project_root / "runs"
    if not runs.is_dir():
        return ()
    paths: list[str] = []
    build_dirs = list(runs.glob("build-*"))
    target_runs = runs / "targets"
    if target_runs.is_dir() and not target_runs.is_symlink():
        for target_dir in sorted(target_runs.iterdir()):
            if not target_dir.is_dir() or target_dir.is_symlink():
                continue
            scoped_runs = target_dir / "runs"
            if scoped_runs.is_dir() and not scoped_runs.is_symlink():
                build_dirs.extend(scoped_runs.glob("build-*"))
    for build_dir in sorted(build_dirs):
        if not build_dir.is_dir() or build_dir.is_symlink():
            continue
        candidates = [build_dir / "state.json"]
        state_dir = build_dir / "state"
        if state_dir.is_dir() and not state_dir.is_symlink():
            candidates.extend(sorted(state_dir.rglob("*.json")))
        for path in candidates:
            if not path.is_file() or path.is_symlink():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and str(payload.get("spec_id") or "").strip() == spec_id:
                paths.append(path.relative_to(project_root).as_posix())
    return tuple(sorted(set(paths)))


def _completed_task_ids(spec_dir: Path) -> tuple[str, ...]:
    path = spec_dir / "tasks.md"
    if not path.is_file():
        return ()
    try:
        matches = (
            match.group(1)
            for line in path.read_text(encoding="utf-8").splitlines()
            if (match := _COMPLETED_TASK.match(line)) is not None
        )
        return tuple(sorted(set(matches)))
    except OSError:
        return ("tasks.md:unreadable",)


def _post_phase_a_artifacts(spec_dir: Path) -> tuple[str, ...]:
    """Enumerate registry-declared build/verification outputs, never infer a stage."""

    return tuple(
        definition.path
        for definition in artifact_definitions()
        if definition.phase in {"Build", "Verification"}
        and definition.path not in _HISTORY_FILES
        and (spec_dir / definition.path).exists()
    )


def _selected_spec_dirty_paths(project_root: Path, spec_dir: Path) -> tuple[str, ...]:
    try:
        dirty_paths = worktree_dirty_paths(project_root)
    except GitHelperError as exc:
        raise RetargetEligibilityError(f"cannot inspect selected spec Git status: {exc}") from exc
    relative_spec = spec_dir.resolve().relative_to(project_root).as_posix()
    prefix = f"{relative_spec}/"
    return tuple(sorted(path for path in dirty_paths if path == relative_spec or path.startswith(prefix)))


def _product_inputs_recoverable(spec_dir: Path, state: Mapping[str, object]) -> bool:
    inputs = state.get("product_inputs")
    if inputs is None or inputs == {}:
        # No declared product-input package is itself a complete, recoverable
        # record; do not reject ordinary prompt-only specifications.
        return True
    if isinstance(inputs, Mapping) and inputs.get("recoverable") is True:
        return True
    if (spec_dir / "inputs").exists() or (spec_dir / "inputs.yml").is_file():
        return True
    if isinstance(inputs, Mapping):
        return any(
            isinstance(inputs.get(key), str) and str(inputs[key]).strip()
            for key in ("inputs_dir", "manifest", "catalog", "traceability")
        )
    return False


def _published_re_recoverable(spec_dir: Path, state: Mapping[str, object]) -> bool:
    context = state.get("published_re_context")
    if isinstance(context, Mapping):
        status = str(context.get("status") or "").strip().lower()
        if status in _RECOVERABLE_RE_STATUSES:
            return True
    path = spec_dir / "re-context.json"
    if not path.is_file():
        return False
    try:
        return isinstance(json.loads(path.read_text(encoding="utf-8")), dict)
    except (OSError, json.JSONDecodeError):
        return False


def _first_text(values: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
