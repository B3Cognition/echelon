"""Spec-scoped Phase A checkpoint metadata."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Callable, Iterator, Mapping

from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message
from echelon.git_helpers import GitHelperError, run_git
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
)
_CHECKPOINT_GIT_EXCLUDES = (
    "**/.echelon/checkpoints.lock",
    "**/.echelon/.checkpoints.json.*.tmp",
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
        additional_owned_paths,
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
