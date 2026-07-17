"""Spec-scoped Phase A checkpoint metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message
from echelon.git_helpers import GitHelperError, run_git


CHECKPOINT_LEDGER_REL = Path(".echelon") / "checkpoints.json"


class PhaseCheckpointError(RuntimeError):
    """Raised when a Phase A checkpoint cannot be created safely."""


@dataclass(frozen=True)
class PhaseCheckpoint:
    id: str
    spec_id: str
    phase: str
    next_phase: str
    commit: str
    metadata_commit: str
    source: str
    run_id: str
    created_at: str


@dataclass(frozen=True)
class CheckpointLedger:
    spec_id: str
    checkpoints: list[PhaseCheckpoint]


def checkpoint_ledger_path(spec_dir: Path) -> Path:
    return spec_dir / CHECKPOINT_LEDGER_REL


def _spec_id_from_dir(spec_dir: Path) -> str:
    name = spec_dir.name
    if name.startswith("spec-"):
        return name.removeprefix("spec-")
    return name


def _spec_dir_allows_external_spec_id(spec_dir: Path) -> bool:
    return spec_dir.name in {"staging", "specs"} and "runs" in spec_dir.parts


def load_checkpoint_ledger(spec_dir: Path) -> CheckpointLedger:
    path = checkpoint_ledger_path(spec_dir)
    if not path.exists():
        return CheckpointLedger(spec_id=_spec_id_from_dir(spec_dir), checkpoints=[])
    raw = json.loads(path.read_text(encoding="utf-8"))
    checkpoints = [PhaseCheckpoint(**item) for item in raw.get("checkpoints", [])]
    return CheckpointLedger(
        spec_id=str(raw.get("spec_id") or _spec_id_from_dir(spec_dir)),
        checkpoints=checkpoints,
    )


def write_checkpoint_ledger(spec_dir: Path, ledger: CheckpointLedger) -> None:
    path = checkpoint_ledger_path(spec_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "spec_id": ledger.spec_id,
        "checkpoints": [asdict(item) for item in ledger.checkpoints],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def record_phase_checkpoint(
    spec_dir: Path,
    checkpoint: PhaseCheckpoint,
) -> CheckpointLedger:
    spec_id = _spec_id_from_dir(spec_dir)
    if checkpoint.spec_id != spec_id and not _spec_dir_allows_external_spec_id(spec_dir):
        raise ValueError(
            f"checkpoint spec_id {checkpoint.spec_id!r} does not match spec directory {spec_id!r}"
        )
    ledger = load_checkpoint_ledger(spec_dir)
    checkpoints = [item for item in ledger.checkpoints if item.id != checkpoint.id]
    checkpoints.append(checkpoint)
    updated = CheckpointLedger(spec_id=checkpoint.spec_id, checkpoints=checkpoints)
    write_checkpoint_ledger(spec_dir, updated)
    return updated


def record_checkpoint_metadata(
    spec_dir: Path,
    checkpoint: PhaseCheckpoint,
) -> CheckpointLedger:
    return record_phase_checkpoint(spec_dir, checkpoint)


def resolve_checkpoint(ledger: CheckpointLedger, target: str) -> PhaseCheckpoint:
    name = target.removeprefix("checkpoint:").strip()
    matches: list[PhaseCheckpoint] = []
    if target.startswith("checkpoint:"):
        matches = [item for item in ledger.checkpoints if item.id == name]
    else:
        matches = [item for item in ledger.checkpoints if item.phase == name]
        if not matches:
            matches = [item for item in ledger.checkpoints if item.id == name]
    if not matches:
        raise KeyError(f"checkpoint not found for spec {ledger.spec_id}: {target}")
    return matches[-1]


def new_checkpoint_id(phase: str, source: str = "auto") -> str:
    if source == "auto":
        return phase
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{source}-{phase}-{stamp}"


def _has_staged_or_unstaged_changes(project_root: Path) -> bool:
    return bool(run_git(project_root, "status", "--porcelain", check=False).stdout.strip())


def _spec_pathspecs(project_root: Path, spec_dirs: tuple[Path, ...]) -> tuple[str, ...]:
    root = Path(project_root).resolve()
    pathspecs: list[str] = []
    seen: set[Path] = set()
    for spec_dir in spec_dirs:
        resolved_spec_dir = Path(spec_dir).resolve()
        if resolved_spec_dir in seen:
            continue
        try:
            relative = resolved_spec_dir.relative_to(root)
        except ValueError as exc:
            raise PhaseCheckpointError(
                "owned spec directory must be inside the project root"
            ) from exc
        if relative == Path("."):
            raise PhaseCheckpointError("owned spec directory cannot be the project root")
        seen.add(resolved_spec_dir)
        pathspecs.extend(
            [
                relative.as_posix(),
                f":(exclude){(relative / CHECKPOINT_LEDGER_REL).as_posix()}",
            ]
        )
    if not pathspecs:
        raise PhaseCheckpointError("at least one owned spec directory is required")
    return tuple(pathspecs)


def _commit_spec_changes(
    project_root: Path,
    spec_dirs: tuple[Path, ...],
    message: str,
) -> str | None:
    """Commit only Git-visible changes owned by the supplied spec directories."""

    root = Path(project_root).resolve()
    pathspecs = _spec_pathspecs(root, spec_dirs)
    try:
        run_git(root, "add", "-f", "-A", "--", *pathspecs)
        staged = run_git(
            root,
            "diff",
            "--cached",
            "--quiet",
            "--",
            *pathspecs,
            check=False,
        )
        if staged.returncode == 0:
            return None
        run_git(root, "commit", "--only", "-m", message, "--", *pathspecs)
        return run_git(root, "rev-parse", "HEAD^{commit}").stdout.strip()
    except GitHelperError as exc:
        raise PhaseCheckpointError(str(exc)) from exc


def create_phase_checkpoint(
    *,
    project_root: Path,
    spec_dir: Path,
    phase: str,
    next_phase: str,
    run_id: str,
    spec_id: str = "",
    additional_spec_dirs: tuple[Path, ...] = (),
) -> PhaseCheckpoint:
    spec_id = spec_id or _spec_id_from_dir(spec_dir)
    subject = f"echelon-checkpoint: {spec_id} {phase}"
    message = build_echelon_commit_message(
        subject,
        EchelonCommitMetadata(
            origin="phase-a",
            action="checkpoint",
            spec_id=spec_id,
            run_id=run_id,
            phase=phase,
            checkpoint_id=phase,
        ),
    )
    commit = _commit_spec_changes(
        project_root,
        (spec_dir, *additional_spec_dirs),
        message,
    )
    if commit is None:
        try:
            commit = run_git(project_root, "rev-parse", "HEAD^{commit}").stdout.strip()
        except GitHelperError as exc:
            raise PhaseCheckpointError(str(exc)) from exc
    checkpoint = PhaseCheckpoint(
        id=phase,
        spec_id=spec_id,
        phase=phase,
        next_phase=next_phase,
        commit=commit,
        metadata_commit="",
        source="auto",
        run_id=run_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    record_phase_checkpoint(spec_dir, checkpoint)
    return checkpoint


def accept_checkpoint_baseline(
    *,
    project_root: Path,
    spec_dir: Path,
    phase: str,
    run_id: str,
) -> PhaseCheckpoint:
    if _has_staged_or_unstaged_changes(project_root):
        raise RuntimeError("dirty worktree cannot be accepted; commit, stash, or discard changes first")

    spec_id = _spec_id_from_dir(spec_dir)
    commit = run_git(project_root, "rev-parse", "HEAD").stdout.strip()
    checkpoint = PhaseCheckpoint(
        id=new_checkpoint_id(phase, "user-accepted"),
        spec_id=spec_id,
        phase=phase,
        next_phase=phase,
        commit=commit,
        metadata_commit="",
        source="user-accepted",
        run_id=run_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    record_phase_checkpoint(spec_dir, checkpoint)
    return checkpoint


def commit_manual_checkpoint(
    *,
    project_root: Path,
    spec_dir: Path,
    phase: str,
    run_id: str,
    message: str,
) -> PhaseCheckpoint:
    spec_id = _spec_id_from_dir(spec_dir)
    checkpoint_id = new_checkpoint_id(phase, "user-committed")
    commit_message = build_echelon_commit_message(
        message,
        EchelonCommitMetadata(
            origin="phase-a",
            action="user-committed-checkpoint",
            spec_id=spec_id,
            run_id=run_id,
            phase=phase,
            checkpoint_id=checkpoint_id,
        ),
    )
    commit = _commit_spec_changes(project_root, (spec_dir,), commit_message)
    if commit is None:
        raise RuntimeError("no changes in the active spec directory to commit")
    checkpoint = PhaseCheckpoint(
        id=checkpoint_id,
        spec_id=spec_id,
        phase=phase,
        next_phase=phase,
        commit=commit,
        metadata_commit="",
        source="user-committed",
        run_id=run_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    record_phase_checkpoint(spec_dir, checkpoint)
    return checkpoint
