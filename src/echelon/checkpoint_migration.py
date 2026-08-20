"""Explicit promotion of legacy Phase A checkpoint state."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message
from echelon.git_helpers import run_git, worktree_dirty_paths
from echelon.spec_lifecycle import (
    PhaseAExecutionLock,
    SpecLifecycleLocked,
    SpecRun,
    SpecRunExecutionLock,
    resolve_spec_run,
)
from harness.phase_checkpoints import (
    PhaseCheckpoint,
    create_or_recover_completion_checkpoint,
    load_checkpoint_ledger,
)
from harness.squad_state import SquadStateStore


LEGACY_EARLY_ARTIFACTS = frozenset({
    "glossary.md",
    "mental-model.md",
    "boundaries.md",
    "assumptions.md",
    "unknowns.md",
    "reference-architectures.md",
    "contradictions-and-gaps.md",
    "risks.md",
    "mental-model-code.md",
    "codebase-graph.md",
    "user-intent.md",
    "stakeholder-model.md",
})
_INTENT_RELATIVE = Path(".echelon") / "checkpoint-migration.json"


class LegacyCheckpointMigrationError(RuntimeError):
    """Raised when legacy checkpoint migration cannot be proven safe."""


@dataclass(frozen=True)
class LegacyCheckpointMigrationFile:
    name: str
    source: Path
    destination: Path
    size: int
    sha256: str
    disposition: str
    destination_preimage: bytes | None


@dataclass(frozen=True)
class LegacyCheckpointMigrationPlan:
    project_root: Path
    run_dir_name: str
    run_id: str
    spec_id: str
    run_dir: Path
    spec_dir: Path
    staging_dir: Path
    captured_head: str
    next_phase: str
    completion_id: str
    operation_id: str
    files: tuple[LegacyCheckpointMigrationFile, ...]
    ignored: tuple[str, ...]


def _regular_bytes(path: Path, *, label: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise LegacyCheckpointMigrationError(f"could not inspect {label}: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise LegacyCheckpointMigrationError(f"{label} must be a regular file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino)
                != (metadata.st_dev, metadata.st_ino)
            ):
                raise LegacyCheckpointMigrationError(
                    f"{label} identity changed: {path}"
                )
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 65_536):
                chunks.append(chunk)
            after = os.fstat(descriptor)
            current = path.lstat()
            if (
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
                or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)
            ):
                raise LegacyCheckpointMigrationError(
                    f"{label} identity changed: {path}"
                )
            return b"".join(chunks)
        finally:
            os.close(descriptor)
    except LegacyCheckpointMigrationError:
        raise
    except OSError as exc:
        raise LegacyCheckpointMigrationError(f"could not read {label}: {path}") from exc


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise LegacyCheckpointMigrationError("migration path escapes project") from exc


def _assert_destination_clean(root: Path, spec_dir: Path, staging_dir: Path) -> None:
    if spec_dir.resolve() == staging_dir.resolve():
        return
    prefix = _relative(root, spec_dir).rstrip("/") + "/"
    dirty = sorted(path for path in worktree_dirty_paths(root) if path.startswith(prefix))
    if dirty:
        raise LegacyCheckpointMigrationError(
            "dirty owned paths block checkpoint migration:\n  " + "\n  ".join(dirty)
        )


def _plan_identity(
    run: SpecRun,
    head: str,
    next_phase: str,
    files: tuple[LegacyCheckpointMigrationFile, ...],
) -> str:
    payload = {
        "run": run.run_dir_name,
        "run_id": run.run_id,
        "spec_id": run.spec_id,
        "head": head,
        "next_phase": next_phase,
        "files": [(item.name, item.sha256, item.disposition) for item in files],
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return digest[:32]


def prepare_legacy_checkpoint_migration(
    project_root: Path,
    run: SpecRun,
) -> LegacyCheckpointMigrationPlan:
    """Build an immutable, non-mutating legacy migration preview."""

    root = Path(project_root).resolve()
    try:
        with PhaseAExecutionLock.acquire(
            root,
            f"checkpoint-migration-preview-{os.getpid()}",
        ):
            canonical = resolve_spec_run(root, run.run_dir_name)
    except SpecLifecycleLocked as exc:
        raise LegacyCheckpointMigrationError(
            f"Phase A execution lease is owned by {exc.operation_id}"
        ) from exc
    if canonical != run:
        raise LegacyCheckpointMigrationError("spec run identity changed")
    state = SquadStateStore(canonical.run_dir).load()
    if state.get("checkpoint_policy_version") == 2:
        raise LegacyCheckpointMigrationError("spec run already uses checkpoint policy version 2")
    staging = canonical.run_dir / "staging"
    try:
        staging_metadata = staging.lstat()
    except OSError as exc:
        raise LegacyCheckpointMigrationError("legacy staging directory is missing") from exc
    if stat.S_ISLNK(staging_metadata.st_mode) or not stat.S_ISDIR(staging_metadata.st_mode):
        raise LegacyCheckpointMigrationError("legacy staging path must be a directory")
    files: list[LegacyCheckpointMigrationFile] = []
    ignored: list[str] = []
    for source in sorted(staging.iterdir(), key=lambda path: path.name):
        if source.name not in LEGACY_EARLY_ARTIFACTS:
            if source.is_file() and not source.is_symlink():
                ignored.append(source.name)
            continue
        content = _regular_bytes(source, label="legacy migration source")
        destination = canonical.spec_dir / source.name
        preimage: bytes | None = None
        disposition = "copy"
        if destination.exists() or destination.is_symlink():
            preimage = _regular_bytes(destination, label="legacy migration destination")
            if preimage != content:
                raise LegacyCheckpointMigrationError(
                    f"legacy migration destination collision: {destination}"
                )
            disposition = "unchanged"
        files.append(
            LegacyCheckpointMigrationFile(
                name=source.name,
                source=source,
                destination=destination,
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                disposition=disposition,
                destination_preimage=preimage,
            )
        )
    _assert_destination_clean(root, canonical.spec_dir, staging)
    head = run_git(root, "rev-parse", "HEAD^{commit}").stdout.strip()
    planned = tuple(files)
    next_phase = str(state.get("phase") or "legacy-migration")
    completion_id = _plan_identity(canonical, head, next_phase, planned)
    return LegacyCheckpointMigrationPlan(
        project_root=root,
        run_dir_name=canonical.run_dir_name,
        run_id=canonical.run_id,
        spec_id=canonical.spec_id,
        run_dir=canonical.run_dir,
        spec_dir=canonical.spec_dir,
        staging_dir=staging,
        captured_head=head,
        next_phase=next_phase,
        completion_id=completion_id,
        operation_id=f"checkpoint-migration-{completion_id}",
        files=planned,
        ignored=tuple(ignored),
    )


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _intent_payload(
    plan: LegacyCheckpointMigrationPlan,
    *,
    stage: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "stage": stage,
        "run_dir_name": plan.run_dir_name,
        "run_id": plan.run_id,
        "spec_id": plan.spec_id,
        "captured_head": plan.captured_head,
        "next_phase": plan.next_phase,
        "completion_id": plan.completion_id,
        "files": [
            {
                "name": item.name,
                "size": item.size,
                "sha256": item.sha256,
                "disposition": item.disposition,
                "destination_preimage": (
                    base64.b64encode(item.destination_preimage).decode("ascii")
                    if item.destination_preimage is not None
                    else None
                ),
            }
            for item in plan.files
        ],
    }


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
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
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _revalidate_plan(plan: LegacyCheckpointMigrationPlan, run: SpecRun) -> None:
    if (
        run.run_dir != plan.run_dir
        or run.run_id != plan.run_id
        or run.spec_id != plan.spec_id
        or run.spec_dir != plan.spec_dir
    ):
        raise LegacyCheckpointMigrationError("spec run identity changed")
    head = run_git(plan.project_root, "rev-parse", "HEAD^{commit}").stdout.strip()
    if head != plan.captured_head and not _migration_commit_at_head(plan):
        raise LegacyCheckpointMigrationError("Git HEAD changed after migration preview")
    for item in plan.files:
        content = _regular_bytes(item.source, label="legacy migration source")
        if len(content) != item.size or hashlib.sha256(content).hexdigest() != item.sha256:
            raise LegacyCheckpointMigrationError("legacy migration source changed")
        if item.destination.exists() or item.destination.is_symlink():
            current = _regular_bytes(item.destination, label="legacy migration destination")
            if current not in {content, item.destination_preimage}:
                raise LegacyCheckpointMigrationError("legacy migration destination changed")
        elif item.destination_preimage is not None:
            raise LegacyCheckpointMigrationError("legacy migration destination changed")


def _migration_commit_at_head(plan: LegacyCheckpointMigrationPlan) -> bool:
    result = run_git(
        plan.project_root,
        "show",
        "-s",
        "--format=%P%x00%B",
        "HEAD",
        check=False,
    )
    if result.returncode != 0 or "\0" not in result.stdout:
        return False
    parents, message = result.stdout.split("\0", 1)
    expected = build_echelon_commit_message(
        f"echelon-checkpoint: {plan.spec_id} legacy-migration",
        EchelonCommitMetadata(
            origin="phase-a",
            action="checkpoint",
            spec_id=plan.spec_id,
            run_id=plan.run_id,
            phase="legacy-migration",
            checkpoint_id="legacy-migration",
            next_phase=plan.next_phase,
            completion_id=plan.completion_id,
            checkpoint_source="legacy-migration",
        ),
    )
    return (
        parents.strip() == plan.captured_head
        and message.rstrip("\n") == expected
    )


def _restore_destinations(plan: LegacyCheckpointMigrationPlan) -> None:
    for item in plan.files:
        if item.destination_preimage is None:
            item.destination.unlink(missing_ok=True)
        else:
            _atomic_write_bytes(item.destination, item.destination_preimage)


def _legacy_outcomes(plan: LegacyCheckpointMigrationPlan, state: dict) -> list[dict[str, object]]:
    completed = state.get("completed_phases", [])
    if type(completed) is not list or not all(
        isinstance(phase, str) and phase for phase in completed
    ):
        raise LegacyCheckpointMigrationError("legacy completed phases are invalid")
    outcomes: list[dict[str, object]] = []
    for index, phase in enumerate(completed):
        completion_id = hashlib.sha256(
            f"{plan.run_id}\0{index}\0{phase}".encode("utf-8")
        ).hexdigest()
        outcomes.append(
            {
                "completion_id": completion_id,
                "phase": phase,
                "next_phase": phase,
                "outcome": "executed",
                "legacy": True,
            }
        )
    return outcomes


def _matching_checkpoint(plan: LegacyCheckpointMigrationPlan) -> PhaseCheckpoint | None:
    matches = [
        row
        for row in load_checkpoint_ledger(plan.spec_dir).checkpoints
        if row.completion_id == plan.completion_id
    ]
    if len(matches) > 1:
        raise LegacyCheckpointMigrationError("duplicate migration checkpoint identity")
    if matches:
        checkpoint = matches[0]
        if (
            checkpoint.source != "legacy-migration"
            or checkpoint.spec_id != plan.spec_id
            or checkpoint.run_id != plan.run_id
            or checkpoint.phase != "legacy-migration"
            or checkpoint.next_phase != plan.next_phase
            or checkpoint.boundary_completion_id
            or checkpoint.rewind != "none"
            or checkpoint.rewind_reason != "legacy-migration-boundary"
        ):
            raise LegacyCheckpointMigrationError("migration checkpoint identity drift")
    return matches[0] if matches else None


def apply_legacy_checkpoint_migration(
    project_root: Path,
    plan: LegacyCheckpointMigrationPlan,
) -> PhaseCheckpoint:
    """Apply or recover one sealed legacy checkpoint migration."""

    root = Path(project_root).resolve()
    if root != plan.project_root:
        raise LegacyCheckpointMigrationError("migration project identity changed")
    try:
        with PhaseAExecutionLock.acquire(root, plan.operation_id):
            with SpecRunExecutionLock.acquire(plan.run_dir, plan.operation_id):
                run = resolve_spec_run(root, plan.run_dir_name)
                state_store = SquadStateStore(run.run_dir)
                state = state_store.load()
                if str(state.get("phase") or "legacy-migration") != plan.next_phase:
                    raise LegacyCheckpointMigrationError(
                        "legacy run phase changed after migration preview"
                    )
                existing = _matching_checkpoint(plan)
                if state.get("checkpoint_policy_version") == 2:
                    if existing is None:
                        raise LegacyCheckpointMigrationError(
                            "versioned state has no migration checkpoint"
                        )
                    return existing
                _revalidate_plan(plan, run)
                intent_path = run.run_dir / _INTENT_RELATIVE
                _write_json_atomic(intent_path, _intent_payload(plan, stage="prepared"))
                try:
                    for item in plan.files:
                        if item.disposition == "copy":
                            _atomic_write_bytes(item.destination, item.source.read_bytes())
                    receipt = create_or_recover_completion_checkpoint(
                        project_root=root,
                        spec_dir=run.spec_dir,
                        phase="legacy-migration",
                        next_phase=plan.next_phase,
                        run_id=run.run_id,
                        spec_id=run.spec_id,
                        completion_id=plan.completion_id,
                        checkpoint_prestate={"kind": "git_head", "head": plan.captured_head},
                        force_commit=True,
                        owned_paths_only=tuple(
                            item.destination for item in plan.files
                        ),
                        source="legacy-migration",
                        rewind="none",
                        rewind_reason="legacy-migration-boundary",
                    )
                    if receipt.get("outcome") != "committed":
                        raise LegacyCheckpointMigrationError(
                            "migration checkpoint commit was not created"
                        )
                    checkpoint = _matching_checkpoint(plan)
                    if checkpoint is None:
                        raise LegacyCheckpointMigrationError(
                            "migration checkpoint ledger row is missing"
                        )
                    promoted = dict(state)
                    promoted["checkpoint_policy_version"] = 2
                    promoted["phase_completion_outcomes"] = _legacy_outcomes(plan, state)
                    state_store.save(promoted)
                    _write_json_atomic(
                        intent_path,
                        _intent_payload(plan, stage="complete"),
                    )
                    return checkpoint
                except Exception:
                    if (
                        _matching_checkpoint(plan) is None
                        and not _migration_commit_at_head(plan)
                    ):
                        _restore_destinations(plan)
                    raise
    except SpecLifecycleLocked as exc:
        raise LegacyCheckpointMigrationError(
            f"checkpoint migration lease is owned by {exc.operation_id}"
        ) from exc
