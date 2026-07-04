"""Spec-scoped Phase A checkpoint metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message
from echelon.git_helpers import run_git


CHECKPOINT_LEDGER_REL = Path(".echelon") / "checkpoints.json"


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
    if checkpoint.spec_id != spec_id:
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


def create_phase_checkpoint(
    *,
    project_root: Path,
    spec_dir: Path,
    phase: str,
    next_phase: str,
    run_id: str,
) -> PhaseCheckpoint | None:
    if not _has_staged_or_unstaged_changes(project_root):
        return None

    spec_id = _spec_id_from_dir(spec_dir)
    run_git(project_root, "add", "-A")
    if run_git(project_root, "diff", "--cached", "--quiet", check=False).returncode != 0:
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
        run_git(project_root, "commit", "-m", message)

    commit = run_git(project_root, "rev-parse", "HEAD").stdout.strip()
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
