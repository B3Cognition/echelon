"""Spec-scoped Phase A checkpoint metadata."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Callable, Iterator, Mapping

from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message
from echelon.git_helpers import GitHelperError, run_git
from echelon.strict_json import loads_strict_json
from harness.controller_lock_order import controller_lock_order


CHECKPOINT_LEDGER_REL = Path(".echelon") / "checkpoints.json"
CHECKPOINT_LOCK_REL = Path(".echelon") / "checkpoints.lock"
_COMPLETION_ID_PATTERN = re.compile(r"\A[0-9a-f]{32}\Z")
_GIT_OBJECT_ID_PATTERN = re.compile(r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_TRAILER_PATTERN = re.compile(r"\A([A-Za-z0-9-]+):[ \t]*(.*)\Z")
_COMPLETION_TRAILER_KEYS = (
    "Echelon-Origin",
    "Echelon-Action",
    "Echelon-Spec",
    "Echelon-Run",
    "Echelon-Phase",
    "Echelon-Next-Phase",
    "Echelon-Checkpoint",
    "Echelon-Completion",
    "Echelon-Retarget-Revision",
    "Echelon-Baseline-Run",
    "Echelon-Replacement-Run",
)
_CHECKPOINT_GIT_EXCLUDES = (
    "**/.echelon/checkpoints.lock",
    "**/.echelon/.checkpoints.json.*.tmp",
)
_RETARGET_CHECKPOINT_LEDGER_MAX_BYTES = 1024 * 1024
_RETARGET_CHECKPOINT_LEDGER_MAX_ROWS = 512
_RETARGET_CHECKPOINT_STRING_MAX = 1024
_CHECKPOINT_LEDGER_KEYS = frozenset({"spec_id", "checkpoints"})
_CHECKPOINT_ROW_KEYS = frozenset(
    {
        "id",
        "spec_id",
        "phase",
        "next_phase",
        "commit",
        "metadata_commit",
        "source",
        "run_id",
        "created_at",
    }
)


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
    completion_id: str = ""


@dataclass(frozen=True)
class CheckpointLedger:
    spec_id: str
    checkpoints: list[PhaseCheckpoint]


def checkpoint_ledger_path(spec_dir: Path) -> Path:
    return spec_dir / CHECKPOINT_LEDGER_REL


def checkpoint_lock_path(spec_dir: Path) -> Path:
    return spec_dir / CHECKPOINT_LOCK_REL


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


def _strict_checkpoint_string(
    value: object,
    *,
    field: str,
    allow_empty: bool = False,
) -> str:
    if (
        type(value) is not str
        or len(value) > _RETARGET_CHECKPOINT_STRING_MAX
        or (not value and not allow_empty)
        or value != " ".join(value.strip().split())
    ):
        raise PhaseCheckpointError(f"invalid retarget checkpoint ledger {field}")
    return value


def _strict_checkpoint_timestamp(value: object) -> str:
    text = _strict_checkpoint_string(value, field="created_at")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PhaseCheckpointError(
            "invalid retarget checkpoint ledger created_at"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PhaseCheckpointError("invalid retarget checkpoint ledger created_at")
    return text


def _strict_checkpoint_row(value: object, *, spec_id: str) -> PhaseCheckpoint:
    if type(value) is not dict:
        raise PhaseCheckpointError("invalid retarget checkpoint ledger row")
    keys = frozenset(value)
    allowed = (_CHECKPOINT_ROW_KEYS, _CHECKPOINT_ROW_KEYS | {"completion_id"})
    if keys not in allowed:
        raise PhaseCheckpointError("invalid retarget checkpoint ledger row keys")
    row_spec_id = _strict_checkpoint_string(value["spec_id"], field="spec_id")
    if row_spec_id != spec_id:
        raise PhaseCheckpointError("retarget checkpoint ledger spec_id drift")
    commit = _strict_checkpoint_string(value["commit"], field="commit")
    if _GIT_OBJECT_ID_PATTERN.fullmatch(commit) is None:
        raise PhaseCheckpointError("invalid retarget checkpoint ledger commit")
    metadata_commit = _strict_checkpoint_string(
        value["metadata_commit"],
        field="metadata_commit",
        allow_empty=True,
    )
    if (
        metadata_commit
        and _GIT_OBJECT_ID_PATTERN.fullmatch(metadata_commit) is None
    ):
        raise PhaseCheckpointError(
            "invalid retarget checkpoint ledger metadata_commit"
        )
    completion_id = value.get("completion_id", "")
    if completion_id:
        completion_id = _strict_checkpoint_string(
            completion_id,
            field="completion_id",
        )
        if _COMPLETION_ID_PATTERN.fullmatch(completion_id) is None:
            raise PhaseCheckpointError(
                "invalid retarget checkpoint ledger completion_id"
            )
    elif type(completion_id) is not str:
        raise PhaseCheckpointError(
            "invalid retarget checkpoint ledger completion_id"
        )
    return PhaseCheckpoint(
        id=_strict_checkpoint_string(value["id"], field="id"),
        spec_id=row_spec_id,
        phase=_strict_checkpoint_string(value["phase"], field="phase"),
        next_phase=_strict_checkpoint_string(
            value["next_phase"],
            field="next_phase",
        ),
        commit=commit,
        metadata_commit=metadata_commit,
        source=_strict_checkpoint_string(value["source"], field="source"),
        run_id=_strict_checkpoint_string(value["run_id"], field="run_id"),
        created_at=_strict_checkpoint_timestamp(value["created_at"]),
        completion_id=completion_id,
    )


def _read_strict_checkpoint_ledger_bytes(path: Path) -> bytes:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        raise
    if not stat.S_ISREG(metadata.st_mode):
        raise PhaseCheckpointError(
            "retarget checkpoint ledger must be a regular file"
        )
    if metadata.st_size > _RETARGET_CHECKPOINT_LEDGER_MAX_BYTES:
        raise PhaseCheckpointError("retarget checkpoint ledger exceeds size limit")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise PhaseCheckpointError("could not read retarget checkpoint ledger") from exc
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino)
            != (metadata.st_dev, metadata.st_ino)
        ):
            raise PhaseCheckpointError("retarget checkpoint ledger identity changed")
        content = bytearray()
        while len(content) <= _RETARGET_CHECKPOINT_LEDGER_MAX_BYTES:
            chunk = os.read(
                descriptor,
                min(
                    64 * 1024,
                    _RETARGET_CHECKPOINT_LEDGER_MAX_BYTES + 1 - len(content),
                ),
            )
            if not chunk:
                break
            content.extend(chunk)
        if len(content) > _RETARGET_CHECKPOINT_LEDGER_MAX_BYTES:
            raise PhaseCheckpointError(
                "retarget checkpoint ledger exceeds size limit"
            )
        return bytes(content)
    finally:
        os.close(descriptor)


def _load_retarget_checkpoint_ledger_strict(spec_dir: Path) -> CheckpointLedger:
    spec_id = _spec_id_from_dir(spec_dir)
    path = checkpoint_ledger_path(spec_dir)
    try:
        content = _read_strict_checkpoint_ledger_bytes(path)
    except FileNotFoundError:
        return CheckpointLedger(spec_id=spec_id, checkpoints=[])
    try:
        raw = loads_strict_json(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhaseCheckpointError(
            f"invalid retarget checkpoint ledger JSON: {exc}"
        ) from exc
    if type(raw) is not dict or frozenset(raw) != _CHECKPOINT_LEDGER_KEYS:
        raise PhaseCheckpointError("invalid retarget checkpoint ledger keys")
    stored_spec_id = _strict_checkpoint_string(raw["spec_id"], field="spec_id")
    if stored_spec_id != spec_id:
        raise PhaseCheckpointError("retarget checkpoint ledger spec_id drift")
    values = raw["checkpoints"]
    if type(values) is not list:
        raise PhaseCheckpointError("invalid retarget checkpoint ledger checkpoints")
    if len(values) > _RETARGET_CHECKPOINT_LEDGER_MAX_ROWS:
        raise PhaseCheckpointError("too many retarget checkpoint ledger rows")
    return CheckpointLedger(
        spec_id=stored_spec_id,
        checkpoints=[
            _strict_checkpoint_row(item, spec_id=stored_spec_id)
            for item in values
        ],
    )


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _reject_nonregular_file(path: Path, *, missing_ok: bool) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if missing_ok:
            return
        raise PhaseCheckpointError("checkpoint metadata is missing")
    if not stat.S_ISREG(metadata.st_mode):
        raise PhaseCheckpointError("checkpoint metadata must be a regular file")


def _ensure_checkpoint_directory(spec_dir: Path) -> Path:
    directory = checkpoint_ledger_path(spec_dir).parent
    created = False
    try:
        metadata = directory.lstat()
    except FileNotFoundError:
        try:
            directory.mkdir(mode=0o700)
            created = True
        except FileExistsError:
            pass
        metadata = directory.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise PhaseCheckpointError(
            "checkpoint metadata directory must be a directory"
        )
    if created:
        _fsync_directory(spec_dir)
    return directory


@contextmanager
def _checkpoint_ledger_lock(spec_dir: Path) -> Iterator[None]:
    identity = str(checkpoint_lock_path(spec_dir).absolute())
    with controller_lock_order("checkpoint", identity):
        with _checkpoint_ledger_lock_ordered(spec_dir):
            yield


@contextmanager
def _checkpoint_ledger_lock_ordered(spec_dir: Path) -> Iterator[None]:
    _ensure_checkpoint_runtime_ignored(spec_dir)
    directory = _ensure_checkpoint_directory(spec_dir)
    path = checkpoint_lock_path(spec_dir)
    _reject_nonregular_file(path, missing_ok=True)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise PhaseCheckpointError("could not open checkpoint lock") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise PhaseCheckpointError(
                "checkpoint lock must be a regular file"
            )
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        current = os.lstat(path)
        if (
            not stat.S_ISREG(current.st_mode)
            or (current.st_dev, current.st_ino)
            != (metadata.st_dev, metadata.st_ino)
        ):
            raise PhaseCheckpointError(
                "checkpoint lock identity changed"
            )
        yield
    except OSError as exc:
        raise PhaseCheckpointError("checkpoint lock operation failed") from exc
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
    if not directory.is_dir():
        raise PhaseCheckpointError("checkpoint metadata directory changed")


def _checkpoint_ledger_bytes(ledger: CheckpointLedger) -> bytes:
    checkpoints: list[dict[str, str]] = []
    for item in ledger.checkpoints:
        record = asdict(item)
        if not item.completion_id:
            record.pop("completion_id")
        checkpoints.append(record)
    payload = {
        "spec_id": ledger.spec_id,
        "checkpoints": checkpoints,
    }
    return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


def _write_checkpoint_ledger_unlocked(
    spec_dir: Path,
    ledger: CheckpointLedger,
) -> None:
    path = checkpoint_ledger_path(spec_dir)
    directory = _ensure_checkpoint_directory(spec_dir)
    _reject_nonregular_file(path, missing_ok=True)
    temporary = directory / (
        f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(temporary, flags, 0o600)
        content = _checkpoint_ledger_bytes(ledger)
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written <= 0:
                raise OSError("short checkpoint ledger write")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
        _fsync_directory(directory)
    except (OSError, ValueError) as exc:
        raise PhaseCheckpointError("could not durably write checkpoint ledger") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_checkpoint_ledger(spec_dir: Path, ledger: CheckpointLedger) -> None:
    with _checkpoint_ledger_lock(spec_dir):
        _write_checkpoint_ledger_unlocked(spec_dir, ledger)


def record_phase_checkpoint(
    spec_dir: Path,
    checkpoint: PhaseCheckpoint,
) -> CheckpointLedger:
    spec_id = _spec_id_from_dir(spec_dir)
    if checkpoint.spec_id != spec_id and not _spec_dir_allows_external_spec_id(spec_dir):
        raise ValueError(
            f"checkpoint spec_id {checkpoint.spec_id!r} does not match spec directory {spec_id!r}"
        )
    with _checkpoint_ledger_lock(spec_dir):
        return _record_phase_checkpoint_unlocked(spec_dir, checkpoint)


def _record_phase_checkpoint_unlocked(
    spec_dir: Path,
    checkpoint: PhaseCheckpoint,
) -> CheckpointLedger:
    """Record one validated checkpoint while the caller holds the ledger lock."""

    ledger = load_checkpoint_ledger(spec_dir)
    if checkpoint.completion_id:
        matches = [
            item
            for item in ledger.checkpoints
            if item.completion_id == checkpoint.completion_id
        ]
        if len(matches) > 1:
            raise ValueError("duplicate checkpoint completion identity")
        if matches:
            if matches[0] != checkpoint:
                raise ValueError("checkpoint completion identity drift")
            return ledger
        checkpoints = [*ledger.checkpoints, checkpoint]
    else:
        matches = [item for item in ledger.checkpoints if item.id == checkpoint.id]
        if len(matches) > 1:
            raise ValueError("duplicate checkpoint identity")
        if matches and matches[0] == checkpoint:
            return ledger
        checkpoints = [
            item
            for item in ledger.checkpoints
            if item.id != checkpoint.id
        ]
        checkpoints.append(checkpoint)
    updated = CheckpointLedger(
        spec_id=checkpoint.spec_id,
        checkpoints=checkpoints,
    )
    _write_checkpoint_ledger_unlocked(spec_dir, updated)
    return updated


def _record_retarget_checkpoint_unlocked(
    spec_dir: Path,
    ledger: CheckpointLedger,
    checkpoint: PhaseCheckpoint,
) -> CheckpointLedger:
    """Strictly append one retarget row while the checkpoint lock is held."""

    spec_id = _spec_id_from_dir(spec_dir)
    if ledger.spec_id != spec_id or checkpoint.spec_id != spec_id:
        raise PhaseCheckpointError("retarget checkpoint ledger spec_id drift")
    validated = _strict_checkpoint_row(asdict(checkpoint), spec_id=spec_id)
    matches = [item for item in ledger.checkpoints if item.id == checkpoint.id]
    if len(matches) > 1:
        raise PhaseCheckpointError("duplicate checkpoint identity")
    if matches:
        if matches[0] != validated:
            raise PhaseCheckpointError("retarget checkpoint identity drift")
        return ledger
    checkpoints = [*ledger.checkpoints, validated]
    if len(checkpoints) > _RETARGET_CHECKPOINT_LEDGER_MAX_ROWS:
        raise PhaseCheckpointError("too many retarget checkpoint ledger rows")
    updated = CheckpointLedger(spec_id=spec_id, checkpoints=checkpoints)
    content = _checkpoint_ledger_bytes(updated)
    if len(content) > _RETARGET_CHECKPOINT_LEDGER_MAX_BYTES:
        raise PhaseCheckpointError("retarget checkpoint ledger exceeds size limit")
    _write_checkpoint_ledger_unlocked(spec_dir, updated)
    persisted = _load_retarget_checkpoint_ledger_strict(spec_dir)
    if persisted != updated:
        raise PhaseCheckpointError("retarget checkpoint ledger persistence mismatch")
    return updated


def record_checkpoint_metadata(
    spec_dir: Path,
    checkpoint: PhaseCheckpoint,
) -> CheckpointLedger:
    return record_phase_checkpoint(spec_dir, checkpoint)


def resolve_checkpoint(
    ledger: CheckpointLedger,
    target: str,
    commit: str = "",
) -> PhaseCheckpoint:
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
    commit_prefix = commit.strip().lower()
    if not commit_prefix:
        return matches[-1]
    if re.fullmatch(r"[0-9a-f]+", commit_prefix) is None:
        raise ValueError("checkpoint commit must be hexadecimal")
    commit_matches = [
        item
        for item in matches
        if item.commit.lower().startswith(commit_prefix)
    ]
    candidates = ", ".join(
        f"{item.commit} ({item.created_at})"
        for item in matches
    )
    if not commit_matches:
        raise KeyError(
            f"checkpoint commit {commit_prefix} not found for target {target}; "
            f"candidates: {candidates}"
        )
    if len({item.commit.lower() for item in commit_matches}) > 1:
        raise ValueError(
            f"ambiguous checkpoint commit prefix {commit_prefix} "
            f"for target {target}; candidates: {candidates}"
        )
    return commit_matches[-1]


def checkpoint_targets(ledger: CheckpointLedger) -> list[str]:
    """Return the distinct phase/id selectors accepted by one checkpoint ledger."""

    seen: set[str] = set()
    targets: list[str] = []
    for checkpoint in ledger.checkpoints:
        for value in (checkpoint.phase, checkpoint.id):
            if not value or value in seen:
                continue
            seen.add(value)
            targets.append(value)
    return targets


def new_checkpoint_id(phase: str, source: str = "auto") -> str:
    if source == "auto":
        return phase
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{source}-{phase}-{stamp}"


def _has_staged_or_unstaged_changes(project_root: Path) -> bool:
    return bool(run_git(project_root, "status", "--porcelain", check=False).stdout.strip())


def _owned_pathspecs(
    project_root: Path,
    spec_dirs: tuple[Path, ...],
    additional_owned_paths: tuple[Path, ...] = (),
) -> tuple[str, ...]:
    root = Path(project_root).resolve()
    pathspecs: list[str] = []
    seen_dirs: set[Path] = set()
    for spec_dir in spec_dirs:
        resolved_spec_dir = Path(spec_dir).resolve()
        if resolved_spec_dir in seen_dirs:
            continue
        try:
            relative = resolved_spec_dir.relative_to(root)
        except ValueError as exc:
            raise PhaseCheckpointError(
                "owned spec directory must be inside the project root"
            ) from exc
        if relative == Path("."):
            raise PhaseCheckpointError("owned spec directory cannot be the project root")
        seen_dirs.add(resolved_spec_dir)
        pathspecs.extend(
            [
                relative.as_posix(),
                f":(exclude){(relative / CHECKPOINT_LEDGER_REL).as_posix()}",
                f":(exclude){(relative / CHECKPOINT_LOCK_REL).as_posix()}",
                (
                    f":(exclude)"
                    f"{(relative / CHECKPOINT_LEDGER_REL.parent).as_posix()}"
                    "/.checkpoints.json.*.tmp"
                ),
            ]
        )
    seen_paths: set[Path] = set()
    for owned_path in additional_owned_paths:
        resolved_path = Path(owned_path).resolve()
        if resolved_path in seen_paths:
            continue
        try:
            relative = resolved_path.relative_to(root)
        except ValueError as exc:
            raise PhaseCheckpointError(
                "additional owned path must be inside the project root"
            ) from exc
        if relative == Path(".") or not resolved_path.is_file():
            raise PhaseCheckpointError("additional owned path must be an existing file")
        seen_paths.add(resolved_path)
        pathspecs.append(relative.as_posix())
    if not pathspecs:
        raise PhaseCheckpointError("at least one owned path is required")
    return tuple(pathspecs)


def _commit_spec_changes(
    project_root: Path,
    spec_dirs: tuple[Path, ...],
    message: str,
    additional_owned_paths: tuple[Path, ...] = (),
) -> str | None:
    """Commit only Git-visible changes owned by supplied Echelon paths."""

    root = Path(project_root).resolve()
    pathspecs = _owned_pathspecs(root, spec_dirs, additional_owned_paths)
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


class _CheckpointLedgerDecodeError(PhaseCheckpointError):
    """A truncated ledger that only a bound receipt may repair."""


def _validate_completion_identity(
    value: object,
    *,
    field: str,
    allow_empty: bool = False,
) -> str:
    if (
        type(value) is not str
        or len(value) > 1024
        or (not value and not allow_empty)
        or value != " ".join(value.strip().split())
    ):
        raise PhaseCheckpointError(
            f"invalid completion checkpoint {field}"
        )
    return value


def _validate_completion_checkpoint_inputs(
    *,
    spec_dir: Path | None,
    phase: object,
    next_phase: object,
    run_id: object,
    spec_id: object,
    completion_id: object,
    checkpoint_prestate: object,
    fault_hook: object,
) -> tuple[str, str, str, str, str, str]:
    phase_value = _validate_completion_identity(phase, field="phase")
    next_value = _validate_completion_identity(
        next_phase,
        field="next phase",
    )
    run_value = _validate_completion_identity(run_id, field="run")
    spec_value = _validate_completion_identity(
        spec_id,
        field="spec",
        allow_empty=spec_dir is None,
    )
    completion_value = _validate_completion_identity(
        completion_id,
        field="completion",
    )
    if _COMPLETION_ID_PATTERN.fullmatch(completion_value) is None:
        raise PhaseCheckpointError(
            "invalid completion checkpoint completion"
        )
    if spec_dir is None and spec_value:
        raise PhaseCheckpointError(
            "not-applicable checkpoint must have an empty spec"
        )
    if (
        type(checkpoint_prestate) is not dict
        or frozenset(checkpoint_prestate) != frozenset({"kind", "head"})
        or checkpoint_prestate.get("kind") != "git_head"
    ):
        raise PhaseCheckpointError("invalid checkpoint prestate")
    head = checkpoint_prestate.get("head")
    if (
        type(head) is not str
        or _GIT_OBJECT_ID_PATTERN.fullmatch(head) is None
    ):
        raise PhaseCheckpointError("invalid checkpoint prestate")
    if fault_hook is not None and not callable(fault_hook):
        raise PhaseCheckpointError("invalid checkpoint fault hook")
    return (
        phase_value,
        next_value,
        run_value,
        spec_value,
        completion_value,
        head,
    )


def _checkpoint_receipt_common(
    *,
    completion_id: str,
    run_id: str,
    spec_id: str,
    phase: str,
    next_phase: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "completion_id": completion_id,
        "run_id": run_id,
        "spec_id": spec_id,
        "phase": phase,
        "next_phase": next_phase,
    }


def _validate_expected_checkpoint_receipt(
    receipt: object,
    *,
    common: Mapping[str, object],
    spec_dir: Path | None,
    checkpoint_head: str,
) -> dict[str, object] | None:
    if receipt is None:
        return None
    if type(receipt) is not dict:
        raise PhaseCheckpointError("checkpoint receipt mismatch")
    outcome = receipt.get("outcome")
    if (
        type(receipt.get("schema_version")) is not int
        or receipt.get("schema_version") != 1
        or any(
            type(receipt.get(key)) is not str
            for key in (
                "completion_id",
                "run_id",
                "spec_id",
                "phase",
                "next_phase",
            )
        )
        or type(outcome) is not str
    ):
        raise PhaseCheckpointError("checkpoint receipt mismatch")
    suffix: frozenset[str]
    if outcome == "committed":
        suffix = frozenset({"outcome", "commit"})
    elif outcome == "no_change":
        suffix = frozenset({"outcome", "head"})
    elif outcome == "not_applicable":
        suffix = frozenset({"outcome"})
    else:
        raise PhaseCheckpointError("checkpoint receipt mismatch")
    if frozenset(receipt) != frozenset(common) | suffix:
        raise PhaseCheckpointError("checkpoint receipt mismatch")
    if any(receipt.get(key) != value for key, value in common.items()):
        raise PhaseCheckpointError("checkpoint receipt mismatch")
    if outcome == "committed":
        commit = receipt.get("commit")
        if (
            spec_dir is None
            or type(commit) is not str
            or _GIT_OBJECT_ID_PATTERN.fullmatch(commit) is None
        ):
            raise PhaseCheckpointError("checkpoint receipt mismatch")
    elif outcome == "no_change":
        if spec_dir is None or receipt.get("head") != checkpoint_head:
            raise PhaseCheckpointError("checkpoint receipt mismatch")
    elif spec_dir is not None:
        raise PhaseCheckpointError("checkpoint receipt mismatch")
    return dict(receipt)


def _read_regular_file(path: Path, *, maximum_bytes: int) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise PhaseCheckpointError("could not read checkpoint ledger") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise PhaseCheckpointError(
                "checkpoint ledger must be a regular file"
            )
        content = bytearray()
        while True:
            chunk = os.read(descriptor, min(65_536, maximum_bytes + 1))
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > maximum_bytes:
                raise PhaseCheckpointError("checkpoint ledger is too large")
        return bytes(content)
    except OSError as exc:
        raise PhaseCheckpointError("could not read checkpoint ledger") from exc
    finally:
        os.close(descriptor)


def _load_completion_checkpoint_ledger(
    spec_dir: Path,
) -> tuple[CheckpointLedger, bool]:
    path = checkpoint_ledger_path(spec_dir)
    try:
        path.lstat()
    except FileNotFoundError:
        return (
            CheckpointLedger(
                spec_id=_spec_id_from_dir(spec_dir),
                checkpoints=[],
            ),
            False,
        )
    _reject_nonregular_file(path, missing_ok=False)
    content = _read_regular_file(path, maximum_bytes=4_194_304)
    try:
        raw = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _CheckpointLedgerDecodeError(
            "checkpoint ledger is truncated"
        ) from exc
    if (
        type(raw) is not dict
        or frozenset(raw) != frozenset({"spec_id", "checkpoints"})
        or type(raw.get("spec_id")) is not str
        or type(raw.get("checkpoints")) is not list
    ):
        raise PhaseCheckpointError("checkpoint ledger shape mismatch")
    checkpoints: list[PhaseCheckpoint] = []
    legacy_keys = {
        "id",
        "spec_id",
        "phase",
        "next_phase",
        "commit",
        "metadata_commit",
        "source",
        "run_id",
        "created_at",
    }
    for item in raw["checkpoints"]:
        if (
            type(item) is not dict
            or set(item) not in (legacy_keys, legacy_keys | {"completion_id"})
        ):
            raise PhaseCheckpointError("checkpoint ledger row mismatch")
        try:
            checkpoint = PhaseCheckpoint(**item)
        except TypeError as exc:
            raise PhaseCheckpointError(
                "checkpoint ledger row mismatch"
            ) from exc
        if any(
            type(value) is not str
            for value in asdict(checkpoint).values()
        ):
            raise PhaseCheckpointError("checkpoint ledger row mismatch")
        if (
            checkpoint.completion_id
            and _COMPLETION_ID_PATTERN.fullmatch(
                checkpoint.completion_id
            )
            is None
        ):
            raise PhaseCheckpointError("checkpoint ledger row mismatch")
        checkpoints.append(checkpoint)
    return (
        CheckpointLedger(
            spec_id=raw["spec_id"],
            checkpoints=checkpoints,
        ),
        True,
    )


def _parse_commit_trailers(message: str) -> dict[str, list[str]]:
    lines = message.splitlines()
    while lines and not lines[-1]:
        lines.pop()
    trailers: list[tuple[str, str]] = []
    while lines:
        match = _TRAILER_PATTERN.fullmatch(lines[-1])
        if match is None:
            break
        trailers.append((match.group(1), match.group(2)))
        lines.pop()
    values: dict[str, list[str]] = {}
    for key, value in reversed(trailers):
        if key in _COMPLETION_TRAILER_KEYS:
            values.setdefault(key, []).append(value)
    return values


def _parse_log_records(output: str) -> list[dict[str, str]]:
    fields = output.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    if len(fields) % 4 != 0:
        raise PhaseCheckpointError("could not parse checkpoint history")
    records: list[dict[str, str]] = []
    for offset in range(0, len(fields), 4):
        commit, parents, created_at, message = fields[offset : offset + 4]
        if _GIT_OBJECT_ID_PATTERN.fullmatch(commit) is None or not created_at:
            raise PhaseCheckpointError("could not parse checkpoint history")
        records.append(
            {
                "commit": commit,
                "parents": parents,
                "created_at": created_at,
                "message": message,
            }
        )
    return records


def _completion_commit_identity(
    *,
    completion_id: str,
    run_id: str,
    spec_id: str,
    phase: str,
    next_phase: str,
) -> dict[str, str]:
    return {
        "Echelon-Origin": "phase-a",
        "Echelon-Action": "checkpoint",
        "Echelon-Spec": spec_id,
        "Echelon-Run": run_id,
        "Echelon-Phase": phase,
        "Echelon-Next-Phase": next_phase,
        "Echelon-Checkpoint": phase,
        "Echelon-Completion": completion_id,
    }


def _record_has_completion_id(
    record: Mapping[str, str],
    completion_id: str,
) -> bool:
    return completion_id in _parse_commit_trailers(
        record["message"]
    ).get("Echelon-Completion", ())


def _record_has_exact_identity(
    record: Mapping[str, str],
    identity: Mapping[str, str],
    checkpoint_head: str,
) -> bool:
    trailers = _parse_commit_trailers(record["message"])
    return (
        record.get("parents") == checkpoint_head
        and all(
            trailers.get(key) == [value]
            for key, value in identity.items()
        )
    )


def _record_has_exact_retarget_identity(
    record: Mapping[str, str],
    identity: Mapping[str, str],
) -> bool:
    trailers = _parse_commit_trailers(record["message"])
    parents = record.get("parents", "").split()
    return (
        len(parents) == 1
        and _GIT_OBJECT_ID_PATTERN.fullmatch(parents[0]) is not None
        and frozenset(trailers) == frozenset(identity)
        and all(trailers.get(key) == [value] for key, value in identity.items())
    )


def _bounded_completion_commit(
    project_root: Path,
    *,
    identity: Mapping[str, str],
    checkpoint_head: str,
) -> dict[str, str] | None:
    try:
        output = run_git(
            project_root,
            "log",
            "--all",
            "--max-count=256",
            "-z",
            "--format=%H%x00%P%x00%cI%x00%B",
        ).stdout
    except GitHelperError as exc:
        raise PhaseCheckpointError(str(exc)) from exc
    candidates = [
        record
        for record in _parse_log_records(output)
        if _record_has_completion_id(
            record,
            identity["Echelon-Completion"],
        )
    ]
    if any(
        not _record_has_exact_identity(
            record,
            identity,
            checkpoint_head,
        )
        for record in candidates
    ):
        raise PhaseCheckpointError("checkpoint completion identity drift")
    if len(candidates) > 1:
        raise PhaseCheckpointError("duplicate checkpoint completion identity")
    return candidates[0] if candidates else None


def _show_completion_commit(
    project_root: Path,
    commit: str,
) -> dict[str, str]:
    try:
        output = run_git(
            project_root,
            "show",
            "-s",
            "--format=%H%x00%P%x00%cI%x00%B",
            commit,
        ).stdout
    except GitHelperError as exc:
        raise PhaseCheckpointError(str(exc)) from exc
    fields = output.split("\0", 3)
    if len(fields) != 4:
        raise PhaseCheckpointError("could not parse checkpoint commit")
    record = {
        "commit": fields[0],
        "parents": fields[1],
        "created_at": fields[2],
        "message": fields[3],
    }
    if (
        record["commit"] != commit
        or not record["created_at"]
        or _GIT_OBJECT_ID_PATTERN.fullmatch(record["commit"]) is None
    ):
        raise PhaseCheckpointError("checkpoint commit mismatch")
    return record


def _completion_checkpoint_from_commit(
    *,
    record: Mapping[str, str],
    completion_id: str,
    run_id: str,
    spec_id: str,
    phase: str,
    next_phase: str,
) -> PhaseCheckpoint:
    return PhaseCheckpoint(
        id=phase,
        spec_id=spec_id,
        phase=phase,
        next_phase=next_phase,
        commit=record["commit"],
        metadata_commit="",
        source="auto",
        run_id=run_id,
        created_at=record["created_at"],
        completion_id=completion_id,
    )


def _committed_checkpoint_receipt(
    common: Mapping[str, object],
    commit: str,
) -> dict[str, object]:
    return {**common, "outcome": "committed", "commit": commit}


def _record_completion_checkpoint_unlocked(
    spec_dir: Path,
    ledger: CheckpointLedger,
    checkpoint: PhaseCheckpoint,
) -> None:
    updated = CheckpointLedger(
        spec_id=checkpoint.spec_id,
        checkpoints=[*ledger.checkpoints, checkpoint],
    )
    _write_checkpoint_ledger_unlocked(spec_dir, updated)


def _owned_paths_have_changes(
    project_root: Path,
    spec_dirs: tuple[Path, ...],
    additional_owned_paths: tuple[Path, ...],
) -> bool:
    pathspecs = _owned_pathspecs(
        project_root,
        spec_dirs,
        additional_owned_paths,
    )
    try:
        result = run_git(
            project_root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            *pathspecs,
        )
    except GitHelperError as exc:
        raise PhaseCheckpointError(str(exc)) from exc
    return bool(result.stdout.strip())


def _ensure_checkpoint_runtime_ignored(project_root: Path) -> None:
    """Keep persistent checkpoint coordination files out of old repos."""

    result = run_git(
        project_root,
        "rev-parse",
        "--git-path",
        "info/exclude",
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return
    path = Path(result.stdout.strip())
    if not path.is_absolute():
        path = project_root / path
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise PhaseCheckpointError(
            "could not update checkpoint Git excludes"
        ) from exc
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        with os.fdopen(os.dup(descriptor), "r+", encoding="utf-8") as handle:
            content = handle.read()
            lines = content.splitlines()
            missing = [
                pattern
                for pattern in _CHECKPOINT_GIT_EXCLUDES
                if pattern not in lines
            ]
            if missing:
                handle.seek(0, os.SEEK_END)
                if content and not content.endswith("\n"):
                    handle.write("\n")
                handle.write("\n".join(missing) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
    except OSError as exc:
        raise PhaseCheckpointError(
            "could not update checkpoint Git excludes"
        ) from exc
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def create_or_recover_completion_checkpoint(
    *,
    project_root: Path,
    spec_dir: Path | None,
    phase: str,
    next_phase: str,
    run_id: str,
    spec_id: str,
    completion_id: str,
    checkpoint_prestate: Mapping[str, object],
    additional_spec_dirs: tuple[Path, ...] = (),
    additional_owned_paths: tuple[Path, ...] = (),
    expected_receipt: object | None = None,
    fault_hook: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Create or recover one checkpoint bound to dispatch-time Git state."""

    (
        phase_value,
        next_value,
        run_value,
        spec_value,
        completion_value,
        checkpoint_head,
    ) = _validate_completion_checkpoint_inputs(
        spec_dir=spec_dir,
        phase=phase,
        next_phase=next_phase,
        run_id=run_id,
        spec_id=spec_id,
        completion_id=completion_id,
        checkpoint_prestate=checkpoint_prestate,
        fault_hook=fault_hook,
    )
    common = _checkpoint_receipt_common(
        completion_id=completion_value,
        run_id=run_value,
        spec_id=spec_value,
        phase=phase_value,
        next_phase=next_value,
    )
    expected = _validate_expected_checkpoint_receipt(
        expected_receipt,
        common=common,
        spec_dir=spec_dir,
        checkpoint_head=checkpoint_head,
    )
    if spec_dir is None:
        receipt = {**common, "outcome": "not_applicable"}
        if expected is not None and expected != receipt:
            raise PhaseCheckpointError("checkpoint receipt mismatch")
        return receipt

    root = Path(project_root).resolve()
    active_spec = Path(spec_dir).resolve()
    try:
        active_spec.relative_to(root)
    except ValueError as exc:
        raise PhaseCheckpointError(
            "owned spec directory must be inside the project root"
        ) from exc
    if not active_spec.is_dir():
        raise PhaseCheckpointError("active spec directory is missing")
    derived_spec = _spec_id_from_dir(active_spec)
    if (
        spec_value != derived_spec
        and not _spec_dir_allows_external_spec_id(active_spec)
    ):
        raise PhaseCheckpointError(
            "checkpoint spec does not match active spec directory"
        )
    owned_spec_dirs = (
        active_spec,
        *(Path(path).resolve() for path in additional_spec_dirs),
    )
    identity = _completion_commit_identity(
        completion_id=completion_value,
        run_id=run_value,
        spec_id=spec_value,
        phase=phase_value,
        next_phase=next_value,
    )
    with _checkpoint_ledger_lock(active_spec):
        ledger_was_present = checkpoint_ledger_path(active_spec).exists()
        try:
            ledger, _ = _load_completion_checkpoint_ledger(active_spec)
        except _CheckpointLedgerDecodeError:
            if expected is None or expected.get("outcome") != "committed":
                raise
            ledger = CheckpointLedger(
                spec_id=spec_value,
                checkpoints=[],
            )
        if ledger_was_present and ledger.spec_id != spec_value:
            raise PhaseCheckpointError("checkpoint ledger spec mismatch")
        rows = [
            item
            for item in ledger.checkpoints
            if item.completion_id == completion_value
        ]
        if len(rows) > 1:
            raise PhaseCheckpointError(
                "duplicate checkpoint completion identity"
            )
        candidate = _bounded_completion_commit(
            root,
            identity=identity,
            checkpoint_head=checkpoint_head,
        )

        if rows:
            checkpoint = rows[0]
            record = _show_completion_commit(root, checkpoint.commit)
            expected_checkpoint = _completion_checkpoint_from_commit(
                record=record,
                completion_id=completion_value,
                run_id=run_value,
                spec_id=spec_value,
                phase=phase_value,
                next_phase=next_value,
            )
            if (
                not _record_has_exact_identity(
                    record,
                    identity,
                    checkpoint_head,
                )
                or checkpoint != expected_checkpoint
                or (
                    candidate is not None
                    and candidate["commit"] != checkpoint.commit
                )
            ):
                raise PhaseCheckpointError(
                    "checkpoint completion identity drift"
                )
            receipt = _committed_checkpoint_receipt(
                common,
                checkpoint.commit,
            )
            if expected is not None and expected != receipt:
                raise PhaseCheckpointError("checkpoint receipt mismatch")
            return receipt

        if candidate is not None:
            receipt = _committed_checkpoint_receipt(
                common,
                candidate["commit"],
            )
            if expected is not None and expected != receipt:
                raise PhaseCheckpointError("checkpoint receipt mismatch")
            checkpoint = _completion_checkpoint_from_commit(
                record=candidate,
                completion_id=completion_value,
                run_id=run_value,
                spec_id=spec_value,
                phase=phase_value,
                next_phase=next_value,
            )
            _record_completion_checkpoint_unlocked(
                active_spec,
                ledger,
                checkpoint,
            )
            if fault_hook is not None:
                fault_hook("after_ledger")
            return receipt

        if expected is not None and expected.get("outcome") == "committed":
            raise PhaseCheckpointError("checkpoint receipt mismatch")
        try:
            current_head = run_git(
                root,
                "rev-parse",
                "HEAD^{commit}",
            ).stdout.strip()
        except GitHelperError as exc:
            raise PhaseCheckpointError(str(exc)) from exc
        if current_head != checkpoint_head:
            raise PhaseCheckpointError("checkpoint prestate mismatch")

        if expected is not None:
            receipt = {
                **common,
                "outcome": "no_change",
                "head": checkpoint_head,
            }
            changed = _owned_paths_have_changes(
                root,
                owned_spec_dirs,
                additional_owned_paths,
            )
            try:
                verified_head = run_git(
                    root,
                    "rev-parse",
                    "HEAD^{commit}",
                ).stdout.strip()
            except GitHelperError as exc:
                raise PhaseCheckpointError(str(exc)) from exc
            if (
                expected != receipt
                or changed
                or verified_head != checkpoint_head
            ):
                raise PhaseCheckpointError("checkpoint receipt mismatch")
            return receipt

        subject = f"echelon-checkpoint: {spec_value} {phase_value}"
        message = build_echelon_commit_message(
            subject,
            EchelonCommitMetadata(
                origin="phase-a",
                action="checkpoint",
                spec_id=spec_value,
                run_id=run_value,
                phase=phase_value,
                checkpoint_id=phase_value,
                next_phase=next_value,
                completion_id=completion_value,
            ),
        )
        commit = _commit_spec_changes(
            root,
            owned_spec_dirs,
            message,
            additional_owned_paths,
        )
        if commit is None:
            try:
                verified_head = run_git(
                    root,
                    "rev-parse",
                    "HEAD^{commit}",
                ).stdout.strip()
            except GitHelperError as exc:
                raise PhaseCheckpointError(str(exc)) from exc
            if verified_head != checkpoint_head:
                raise PhaseCheckpointError("checkpoint prestate mismatch")
            return {
                **common,
                "outcome": "no_change",
                "head": checkpoint_head,
            }
        if fault_hook is not None:
            fault_hook("after_commit")
        record = _show_completion_commit(root, commit)
        if not _record_has_exact_identity(
            record,
            identity,
            checkpoint_head,
        ):
            raise PhaseCheckpointError(
                "created checkpoint commit identity mismatch"
            )
        checkpoint = _completion_checkpoint_from_commit(
            record=record,
            completion_id=completion_value,
            run_id=run_value,
            spec_id=spec_value,
            phase=phase_value,
            next_phase=next_value,
        )
        _record_completion_checkpoint_unlocked(
            active_spec,
            ledger,
            checkpoint,
        )
        if fault_hook is not None:
            fault_hook("after_ledger")
        return _committed_checkpoint_receipt(common, commit)


def _verify_retarget_commit_tree(
    project_root: Path,
    spec_dir: Path,
    commit: str,
    expected_history: object,
) -> None:
    from echelon.spec_retarget_history import (
        RETARGET_HISTORY_FILENAME,
        _MAX_HISTORY_BYTES,
        _history_from_raw,
    )

    root = Path(project_root).resolve()
    resolved_spec = Path(spec_dir).resolve()
    try:
        relative = resolved_spec.relative_to(root)
    except ValueError as exc:
        raise PhaseCheckpointError(
            "owned spec directory must be inside the project root"
        ) from exc
    ledger_path = (relative / RETARGET_HISTORY_FILENAME).as_posix()
    try:
        entries = tuple(
            entry
            for entry in run_git(
                root,
                "ls-tree",
                "-z",
                commit,
                "--",
                ledger_path,
            ).stdout.split("\0")
            if entry
        )
    except (GitHelperError, UnicodeError) as exc:
        raise PhaseCheckpointError(
            "retarget checkpoint does not contain the prepared revision ledger"
        ) from exc
    if len(entries) != 1 or "\t" not in entries[0]:
        raise PhaseCheckpointError(
            "retarget checkpoint does not contain the prepared revision ledger"
        )
    metadata, committed_path = entries[0].split("\t", 1)
    fields = metadata.split()
    if (
        len(fields) != 3
        or fields[0] != "100644"
        or fields[1] != "blob"
        or _GIT_OBJECT_ID_PATTERN.fullmatch(fields[2]) is None
        or committed_path != ledger_path
    ):
        raise PhaseCheckpointError(
            "retarget checkpoint history must use regular blob mode 100644"
        )
    blob = fields[2]
    try:
        size_text = run_git(root, "cat-file", "-s", blob).stdout.strip()
        size = int(size_text)
    except (GitHelperError, UnicodeError, ValueError) as exc:
        raise PhaseCheckpointError(
            "could not inspect retarget checkpoint history blob"
        ) from exc
    if size < 0 or size > _MAX_HISTORY_BYTES:
        raise PhaseCheckpointError(
            "retarget checkpoint history blob exceeds size limit"
        )
    try:
        content = run_git(root, "cat-file", "blob", blob).stdout
        if len(content.encode("utf-8")) != size:
            raise ValueError("retarget checkpoint history blob size changed")
        raw = loads_strict_json(content)
        committed_history = _history_from_raw(
            raw,
            spec_id=_spec_id_from_dir(resolved_spec),
        )
    except (GitHelperError, json.JSONDecodeError, UnicodeError, ValueError) as exc:
        raise PhaseCheckpointError(
            "retarget checkpoint does not contain the prepared revision ledger"
        ) from exc
    if committed_history != expected_history:
        raise PhaseCheckpointError(
            "retarget checkpoint prepared revision ledger drift"
        )


def _verify_retarget_commit_scope(
    project_root: Path,
    spec_dir: Path,
    record: Mapping[str, str],
) -> None:
    root = Path(project_root).resolve()
    resolved_spec = Path(spec_dir).resolve()
    try:
        relative_spec = resolved_spec.relative_to(root).as_posix()
    except ValueError as exc:
        raise PhaseCheckpointError(
            "owned spec directory must be inside the project root"
        ) from exc
    try:
        output = run_git(
            root,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            "-z",
            record["commit"],
        ).stdout
    except GitHelperError as exc:
        raise PhaseCheckpointError(str(exc)) from exc
    changed_paths = tuple(path for path in output.split("\0") if path)
    ledger_path = (Path(relative_spec) / "retarget-history.json").as_posix()
    if (
        ledger_path not in changed_paths
        or not changed_paths
        or any(
            path != relative_spec and not path.startswith(relative_spec + "/")
            for path in changed_paths
        )
    ):
        raise PhaseCheckpointError("retarget checkpoint commit scope mismatch")


def _current_git_head(project_root: Path) -> str:
    try:
        head = run_git(
            project_root,
            "rev-parse",
            "HEAD^{commit}",
        ).stdout.strip()
    except GitHelperError as exc:
        raise PhaseCheckpointError(str(exc)) from exc
    if _GIT_OBJECT_ID_PATTERN.fullmatch(head) is None:
        raise PhaseCheckpointError("invalid current Git HEAD")
    return head


def _single_line_ref_storage_value(output: str) -> str | None:
    if output.endswith("\r\n"):
        line = output[:-2]
    elif output.endswith("\n"):
        line = output[:-1]
    else:
        line = output
    if "\r" in line or "\n" in line:
        return None
    value = line.strip(" \t")
    return value or None


def _git_ref_storage_backend(project_root: Path) -> str:
    """Return an authoritative Git ref backend or fail closed."""

    try:
        format_probe = run_git(
            project_root,
            "rev-parse",
            "--show-ref-format",
            check=False,
        )
        config_probe = run_git(
            project_root,
            "config",
            "--local",
            "--get-all",
            "extensions.refStorage",
            check=False,
        )
    except GitHelperError as exc:
        raise PhaseCheckpointError(
            "could not determine Git ref storage backend"
        ) from exc

    legacy_probe = (
        format_probe.returncode == 0
        and format_probe.stdout == "--show-ref-format\n"
        and not format_probe.stderr
    )
    reported = _single_line_ref_storage_value(format_probe.stdout)
    if not legacy_probe and (
        format_probe.returncode != 0
        or format_probe.stderr
        or reported not in {"files", "reftable"}
    ):
        raise PhaseCheckpointError(
            "could not determine Git ref storage backend"
        )

    if (
        config_probe.returncode == 1
        and not config_probe.stdout
        and not config_probe.stderr
    ):
        configured = None
    elif config_probe.returncode == 0:
        configured = _single_line_ref_storage_value(config_probe.stdout)
        if config_probe.stderr or configured not in {"files", "reftable"}:
            raise PhaseCheckpointError(
                "could not determine Git ref storage backend"
            )
    else:
        raise PhaseCheckpointError(
            "could not determine Git ref storage backend"
        )

    if legacy_probe:
        return configured or "files"
    if configured is not None and reported != configured:
        raise PhaseCheckpointError(
            "ambiguous Git ref storage backend: "
            f"rev-parse={reported}, config={configured}"
        )
    if reported is None:
        raise PhaseCheckpointError(
            "could not determine Git ref storage backend"
        )
    return reported


def _require_files_ref_storage(project_root: Path) -> None:
    """Fail closed unless Git authoritatively identifies the files backend."""

    backend = _git_ref_storage_backend(project_root)
    if backend != "files":
        raise PhaseCheckpointError(
            f"unsupported Git ref storage backend: {backend}"
        )


def _current_git_head_state(project_root: Path) -> tuple[str, str | None]:
    try:
        symbolic = run_git(
            project_root,
            "symbolic-ref",
            "--no-recurse",
            "-q",
            "HEAD",
            check=False,
        )
    except GitHelperError as exc:
        raise PhaseCheckpointError(str(exc)) from exc
    if symbolic.returncode not in {0, 1}:
        raise PhaseCheckpointError("could not inspect current Git HEAD")
    symbolic_ref = symbolic.stdout.strip() if symbolic.returncode == 0 else None
    if symbolic_ref is not None:
        valid_ref = run_git(
            project_root,
            "check-ref-format",
            symbolic_ref,
            check=False,
        )
        if not symbolic_ref.startswith("refs/") or valid_ref.returncode != 0:
            raise PhaseCheckpointError("invalid symbolic Git HEAD")
        if not symbolic_ref.startswith("refs/heads/"):
            raise PhaseCheckpointError("unsupported symbolic Git HEAD topology")
        try:
            intermediate = run_git(
                project_root,
                "symbolic-ref",
                "--no-recurse",
                "-q",
                symbolic_ref,
                check=False,
            )
        except GitHelperError as exc:
            raise PhaseCheckpointError(
                "could not inspect symbolic Git HEAD topology"
            ) from exc
        if intermediate.returncode == 0:
            raise PhaseCheckpointError("unsupported symbolic Git HEAD topology")
        if intermediate.returncode != 1 or intermediate.stdout:
            raise PhaseCheckpointError(
                "could not inspect symbolic Git HEAD topology"
            )
    return _current_git_head(project_root), symbolic_ref


def _git_lock_path(project_root: Path, ref: str) -> Path:
    try:
        value = run_git(project_root, "rev-parse", "--git-path", ref).stdout.strip()
    except GitHelperError as exc:
        raise PhaseCheckpointError(str(exc)) from exc
    if not value:
        raise PhaseCheckpointError("could not resolve Git ref lock path")
    path = Path(value)
    if not path.is_absolute():
        path = project_root / path
    return path.with_name(path.name + ".lock")


@contextmanager
def _git_head_lease(project_root: Path, expected_head: str) -> Iterator[None]:
    """Hold Git-compatible ref locks while validating and recording a HEAD."""

    _require_files_ref_storage(project_root)
    head, symbolic_ref = _current_git_head_state(project_root)
    if head != expected_head:
        raise PhaseCheckpointError(
            "Git HEAD changed before retarget checkpoint recording"
        )
    refs = ["HEAD"]
    if symbolic_ref is not None:
        refs.append(symbolic_ref)
    owned: list[tuple[Path, int, tuple[int, int]]] = []
    try:
        for ref in refs:
            path = _git_lock_path(project_root, ref)
            try:
                path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            except OSError as exc:
                raise PhaseCheckpointError(
                    "could not prepare Git HEAD lease"
                ) from exc
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(path, flags, 0o600)
            except OSError as exc:
                raise PhaseCheckpointError(
                    "could not acquire Git HEAD lease"
                ) from exc
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                os.close(descriptor)
                raise PhaseCheckpointError("Git ref lease must be a regular file")
            owned.append(
                (path, descriptor, (metadata.st_dev, metadata.st_ino))
            )
        verified_head, verified_ref = _current_git_head_state(project_root)
        if verified_head != expected_head or verified_ref != symbolic_ref:
            raise PhaseCheckpointError(
                "Git HEAD changed before retarget checkpoint recording"
            )
        yield
        final_head, final_ref = _current_git_head_state(project_root)
        if final_head != expected_head or final_ref != symbolic_ref:
            raise PhaseCheckpointError(
                "Git HEAD changed before retarget checkpoint recording"
            )
    finally:
        for path, descriptor, identity in reversed(owned):
            try:
                current = path.lstat()
                if (
                    stat.S_ISREG(current.st_mode)
                    and (current.st_dev, current.st_ino) == identity
                ):
                    path.unlink()
            except FileNotFoundError:
                pass
            finally:
                os.close(descriptor)


def _require_commit_on_current_lineage(
    project_root: Path,
    commit: str,
    current_head: str,
) -> None:
    try:
        result = run_git(
            project_root,
            "merge-base",
            "--is-ancestor",
            commit,
            current_head,
            check=False,
        )
    except GitHelperError as exc:
        raise PhaseCheckpointError(str(exc)) from exc
    if result.returncode != 0:
        raise PhaseCheckpointError(
            "recorded retarget checkpoint is not on the current lineage"
        )


def _retarget_checkpoint_from_record(
    *,
    record: Mapping[str, str],
    checkpoint_id: str,
    spec_id: str,
    run_id: str,
) -> PhaseCheckpoint:
    return PhaseCheckpoint(
        id=checkpoint_id,
        spec_id=spec_id,
        phase="retarget",
        next_phase="phase0-constitution",
        commit=record["commit"],
        metadata_commit="",
        source="retarget-preflight",
        run_id=run_id,
        created_at=record["created_at"],
    )


def _record_claims_retarget_identity(
    record: Mapping[str, str],
    *,
    checkpoint_id: str,
    revision_id: str,
) -> bool:
    trailers = _parse_commit_trailers(record["message"])
    return (
        checkpoint_id in trailers.get("Echelon-Checkpoint", ())
        or revision_id in trailers.get("Echelon-Retarget-Revision", ())
    )


def _validate_retarget_commit_record(
    *,
    project_root: Path,
    spec_dir: Path,
    record: Mapping[str, str],
    identity: Mapping[str, str],
    expected_history: object,
    expected_parent: str,
) -> None:
    if not _record_has_exact_retarget_identity(record, identity):
        raise PhaseCheckpointError("retarget checkpoint identity drift")
    if record.get("parents") != expected_parent:
        raise PhaseCheckpointError(
            "retarget checkpoint does not have the expected parent"
        )
    _verify_retarget_commit_tree(
        project_root,
        spec_dir,
        record["commit"],
        expected_history,
    )
    _verify_retarget_commit_scope(project_root, spec_dir, record)


def commit_retarget_checkpoint(
    *,
    project_root: Path,
    spec_dir: Path,
    run_id: str,
    revision_id: str,
) -> PhaseCheckpoint:
    """Commit and record the immutable preflight boundary for one retarget."""

    from echelon.spec_retarget_history import (
        _seal_retarget_checkpoint_parent_unlocked,
        load_retarget_history,
    )

    root = Path(project_root).resolve()
    resolved_spec = Path(spec_dir).resolve()
    spec_id = _spec_id_from_dir(resolved_spec)
    _require_files_ref_storage(root)
    _current_git_head_state(root)
    with _checkpoint_ledger_lock(resolved_spec):
        checkpoint_ledger = _load_retarget_checkpoint_ledger_strict(resolved_spec)
        history = load_retarget_history(resolved_spec)
        if not history.revisions:
            raise PhaseCheckpointError("retarget revision is missing")
        revision = history.revisions[-1]
        if revision.revision_id != revision_id or revision.status != "prepared":
            raise PhaseCheckpointError(
                "retarget checkpoint requires the latest prepared revision"
            )
        if revision.baseline_run_id != run_id:
            raise PhaseCheckpointError(
                "retarget checkpoint baseline run does not match"
            )
        if revision.checkpoint_parent is None:
            observed_parent = _current_git_head(root)
            with _git_head_lease(root, observed_parent):
                try:
                    revision = _seal_retarget_checkpoint_parent_unlocked(
                        resolved_spec,
                        revision.revision_id,
                        checkpoint_parent=observed_parent,
                    )
                except ValueError as exc:
                    raise PhaseCheckpointError(str(exc)) from exc
            history = load_retarget_history(resolved_spec)
        checkpoint_parent = revision.checkpoint_parent
        if (
            checkpoint_parent is None
            or _GIT_OBJECT_ID_PATTERN.fullmatch(checkpoint_parent) is None
        ):
            raise PhaseCheckpointError("invalid retarget checkpoint parent")

        checkpoint_id = f"retarget-preflight-{revision.revision_id}"
        identity = {
            "Echelon-Origin": "phase-a",
            "Echelon-Action": "retarget-preflight",
            "Echelon-Spec": spec_id,
            "Echelon-Run": run_id,
            "Echelon-Phase": "retarget",
            "Echelon-Next-Phase": "phase0-constitution",
            "Echelon-Checkpoint": checkpoint_id,
            "Echelon-Retarget-Revision": revision.revision_id,
            "Echelon-Baseline-Run": revision.baseline_run_id,
            "Echelon-Replacement-Run": revision.replacement_run_id,
        }
        message = build_echelon_commit_message(
            f"checkpoint: prepare retarget {revision.revision_id}",
            EchelonCommitMetadata(
                origin="phase-a",
                action="retarget-preflight",
                spec_id=spec_id,
                run_id=run_id,
                phase="retarget",
                next_phase="phase0-constitution",
                checkpoint_id=checkpoint_id,
                retarget_revision=revision.revision_id,
                baseline_run_id=revision.baseline_run_id,
                replacement_run_id=revision.replacement_run_id,
            ),
        )

        recorded_rows = [
            item
            for item in checkpoint_ledger.checkpoints
            if item.id == checkpoint_id
        ]
        if len(recorded_rows) > 1:
            raise PhaseCheckpointError("duplicate checkpoint identity")
        if recorded_rows:
            recorded_checkpoint = recorded_rows[0]
            try:
                record = _show_completion_commit(
                    root,
                    recorded_checkpoint.commit,
                )
            except PhaseCheckpointError as exc:
                raise PhaseCheckpointError(
                    "retarget checkpoint identity drift"
                ) from exc
            expected_checkpoint = _retarget_checkpoint_from_record(
                record=record,
                checkpoint_id=checkpoint_id,
                spec_id=spec_id,
                run_id=run_id,
            )
            if recorded_checkpoint != expected_checkpoint:
                raise PhaseCheckpointError("retarget checkpoint identity drift")
            current_head = _current_git_head(root)
            with _git_head_lease(root, current_head):
                _require_commit_on_current_lineage(
                    root,
                    recorded_checkpoint.commit,
                    current_head,
                )
                _validate_retarget_commit_record(
                    project_root=root,
                    spec_dir=resolved_spec,
                    record=record,
                    identity=identity,
                    expected_history=history,
                    expected_parent=checkpoint_parent,
                )
            return recorded_checkpoint

        checkpoint_head = _current_git_head(root)
        head_record = _show_completion_commit(root, checkpoint_head)
        if _record_claims_retarget_identity(
            head_record,
            checkpoint_id=checkpoint_id,
            revision_id=revision.revision_id,
        ):
            with _git_head_lease(root, checkpoint_head):
                _validate_retarget_commit_record(
                    project_root=root,
                    spec_dir=resolved_spec,
                    record=head_record,
                    identity=identity,
                    expected_history=history,
                    expected_parent=checkpoint_parent,
                )
                checkpoint = _retarget_checkpoint_from_record(
                    record=head_record,
                    checkpoint_id=checkpoint_id,
                    spec_id=spec_id,
                    run_id=run_id,
                )
                _record_retarget_checkpoint_unlocked(
                    resolved_spec,
                    checkpoint_ledger,
                    checkpoint,
                )
            return checkpoint

        if checkpoint_head != checkpoint_parent:
            raise PhaseCheckpointError("retarget checkpoint prestate mismatch")
        commit = _commit_spec_changes(root, (resolved_spec,), message)
        if commit is None:
            raise PhaseCheckpointError(
                "retarget checkpoint produced no selected-spec change"
            )
        with _git_head_lease(root, commit):
            record = _show_completion_commit(root, commit)
            _validate_retarget_commit_record(
                project_root=root,
                spec_dir=resolved_spec,
                record=record,
                identity=identity,
                expected_history=history,
                expected_parent=checkpoint_parent,
            )
            checkpoint = _retarget_checkpoint_from_record(
                record=record,
                checkpoint_id=checkpoint_id,
                spec_id=spec_id,
                run_id=run_id,
            )
            _record_retarget_checkpoint_unlocked(
                resolved_spec,
                checkpoint_ledger,
                checkpoint,
            )
        return checkpoint


def create_phase_checkpoint(
    *,
    project_root: Path,
    spec_dir: Path,
    phase: str,
    next_phase: str,
    run_id: str,
    spec_id: str = "",
    additional_spec_dirs: tuple[Path, ...] = (),
    additional_owned_paths: tuple[Path, ...] = (),
    checkpoint_owned_paths: tuple[Path, ...] = (),
    force_commit: bool = False,
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
    if checkpoint_owned_paths:
        commit = _commit_spec_changes(
            project_root,
            (),
            message,
            checkpoint_owned_paths,
        )
    else:
        commit = _commit_spec_changes(
            project_root,
            (spec_dir, *additional_spec_dirs),
            message,
            additional_owned_paths,
        )
    if commit is None:
        try:
            if force_commit:
                forced_pathspecs = _owned_pathspecs(
                    project_root,
                    (
                        ()
                        if checkpoint_owned_paths
                        else (spec_dir, *additional_spec_dirs)
                    ),
                    checkpoint_owned_paths or additional_owned_paths,
                )
                run_git(
                    project_root,
                    "commit",
                    "--allow-empty",
                    "--only",
                    "-m",
                    message,
                    "--",
                    *forced_pathspecs,
                )
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


def restore_checkpoint_artifacts(
    *,
    project_root: Path,
    spec_dir: Path,
    checkpoint_commit: str,
    artifact_digests: Mapping[str, str],
) -> None:
    """Restore a narrow, digest-bound set of spec files from one commit.

    This intentionally reads individual blobs and never changes Git HEAD,
    the index, or files outside the explicit candidate artifact allowlist.
    """
    allowed = frozenset(
        {"spec.md", "requirements-overview.md", "quality-gates.md", "issues.md"}
    )
    required = frozenset({"spec.md", "quality-gates.md", "issues.md"})
    if type(artifact_digests) is not dict:
        raise PhaseCheckpointError("candidate artifact digests are malformed")
    names = frozenset(artifact_digests)
    if not required <= names or not names <= allowed:
        raise PhaseCheckpointError("candidate artifact path is missing or unsafe")
    if any(
        type(name) is not str
        or type(digest) is not str
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        for name, digest in artifact_digests.items()
    ):
        raise PhaseCheckpointError("candidate artifact digests are malformed")
    if (
        type(checkpoint_commit) is not str
        or _GIT_OBJECT_ID_PATTERN.fullmatch(checkpoint_commit) is None
    ):
        raise PhaseCheckpointError("candidate checkpoint commit is invalid")

    root = Path(project_root).resolve()
    resolved_spec = Path(spec_dir).resolve()
    try:
        spec_relative = resolved_spec.relative_to(root)
    except ValueError as exc:
        raise PhaseCheckpointError("candidate spec directory escapes project root") from exc
    if not resolved_spec.is_dir():
        raise PhaseCheckpointError("candidate spec directory is missing")
    relative_paths = tuple(
        (spec_relative / name).as_posix() for name in sorted(names)
    )
    try:
        commit_probe = run_git(
            root, "cat-file", "-e", f"{checkpoint_commit}^{{commit}}", check=False
        )
        if commit_probe.returncode != 0:
            raise PhaseCheckpointError("candidate checkpoint commit is missing")
        dirty = run_git(
            root, "status", "--porcelain", "--", *relative_paths, check=False
        )
        if dirty.returncode != 0 or dirty.stdout.strip():
            raise PhaseCheckpointError("candidate artifact path is dirty")
        restored: dict[str, bytes] = {}
        for name, relative in zip(sorted(names), relative_paths, strict=True):
            result = run_git(
                root, "show", f"{checkpoint_commit}:{relative}", check=False
            )
            if result.returncode != 0:
                raise PhaseCheckpointError(
                    f"candidate owned artifact is missing: {name}"
                )
            content = result.stdout.encode("utf-8")
            if hashlib.sha256(content).hexdigest() != artifact_digests[name]:
                raise PhaseCheckpointError(f"candidate artifact digest mismatch: {name}")
            restored[name] = content
    except GitHelperError as exc:
        raise PhaseCheckpointError(str(exc)) from exc

    temporary_paths: list[Path] = []
    try:
        for name in sorted(restored):
            destination = resolved_spec / name
            temporary = destination.with_name(
                f".{destination.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
            )
            temporary_paths.append(temporary)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(temporary, flags, 0o600)
            try:
                offset = 0
                content = restored[name]
                while offset < len(content):
                    written = os.write(descriptor, content[offset:])
                    if written <= 0:
                        raise OSError("short candidate artifact write")
                    offset += written
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        for name, temporary in zip(sorted(restored), temporary_paths, strict=True):
            os.replace(temporary, resolved_spec / name)
        _fsync_directory(resolved_spec)
        for name, expected in artifact_digests.items():
            if (
                hashlib.sha256((resolved_spec / name).read_bytes()).hexdigest()
                != expected
            ):
                raise PhaseCheckpointError(f"restored candidate digest mismatch: {name}")
    except (OSError, ValueError) as exc:
        raise PhaseCheckpointError("could not restore candidate artifacts") from exc
    finally:
        for temporary in temporary_paths:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


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
