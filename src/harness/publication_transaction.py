"""Path-safe, rollback-capable workspace artifact publication primitives."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable


class PublicationTransactionError(RuntimeError):
    """Raised when a workspace artifact transaction is unsafe or incomplete."""


_PHASES = frozenset({"pending", "backup_intent", "backed_up", "install_intent", "installed", "rollback_remove_intent", "restore_intent"})
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _relative_path(value: PurePosixPath | str, field: str) -> PurePosixPath:
    if not isinstance(value, (PurePosixPath, str)):
        raise PublicationTransactionError(f"{field} path is malformed")
    raw = value.as_posix() if isinstance(value, PurePosixPath) else value
    if not raw:
        raise PublicationTransactionError(f"{field} path is malformed")
    path = PurePosixPath(raw)
    if path.is_absolute() or "." in path.parts or ".." in path.parts or "\\" in raw:
        raise PublicationTransactionError(f"{field} path is unsafe")
    return path


def _contained(root: Path, relative: PurePosixPath, *, exists: bool = False) -> Path:
    canonical_root = root.resolve(strict=True)
    candidate = canonical_root.joinpath(*relative.parts)
    try:
        resolved = candidate.resolve(strict=exists)
        resolved.relative_to(canonical_root)
    except (OSError, ValueError) as exc:
        raise PublicationTransactionError(f"transaction path escapes declared root: {relative}") from exc
    return candidate


@dataclass(frozen=True, slots=True)
class PublicationOperation:
    """Replace or remove one artifact relative to a declared workspace root."""

    final: PurePosixPath
    staged: PurePosixPath | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "final", _relative_path(self.final, "final"))
        if self.staged is not None:
            object.__setattr__(self, "staged", _relative_path(self.staged, "staged"))

    @property
    def backup(self) -> PurePosixPath:
        return PurePosixPath("rollback") / self.final


@dataclass(slots=True)
class PublicationTransaction:
    """Durable state for a deterministic set of replace/remove operations."""

    workspace_root: Path
    staging_root: Path
    journal: Path
    operations: tuple[PublicationOperation, ...]
    expected_generation: int | None = None
    _recovery_mode: bool = field(default=False, repr=False)
    _states: list[dict[str, object]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.workspace_root = self.workspace_root.resolve()
        self.staging_root = self.staging_root.resolve()
        self.journal = self.journal.resolve()
        if not self.workspace_root.is_dir() or not self.staging_root.is_dir():
            raise PublicationTransactionError("transaction roots must exist directories")
        try:
            self.journal.relative_to(self.staging_root)
        except ValueError as exc:
            raise PublicationTransactionError("journal path is outside staging root") from exc
        if os.stat(self.workspace_root).st_dev != os.stat(self.staging_root).st_dev:
            raise PublicationTransactionError("workspace and staging roots must share a filesystem")
        finals: list[tuple[PurePosixPath, Path]] = []
        staged: list[PurePosixPath] = []
        backups: list[PurePosixPath] = []
        for operation in self.operations:
            final_path = _contained(self.workspace_root, operation.final)
            if _absolute_overlap(final_path, self.staging_root):
                raise PublicationTransactionError("final path overlaps staging root")
            if any(operation.final == previous for previous, _ in finals):
                raise PublicationTransactionError("duplicate final publication operation")
            if any(_relative_overlap(operation.final, previous) for previous, _ in finals):
                raise PublicationTransactionError("final publication operations overlap")
            finals.append((operation.final, final_path))
            _contained(self.workspace_root, operation.final)
            _contained(self.staging_root, operation.backup)
            if any(_relative_overlap(operation.backup, previous) for previous in backups):
                raise PublicationTransactionError("backup publication operations overlap")
            backups.append(operation.backup)
            if operation.staged is not None:
                _contained(self.staging_root, operation.staged)
                if any(_relative_overlap(operation.staged, previous) for previous in staged):
                    raise PublicationTransactionError("staged publication operations overlap")
                if any(_relative_overlap(operation.staged, backup) for backup in backups):
                    raise PublicationTransactionError("staged and backup paths overlap")
                staged.append(operation.staged)
        for staged_path in staged:
            if any(_relative_overlap(staged_path, backup) for backup in backups):
                raise PublicationTransactionError("staged and backup paths overlap")
        journal_relative = PurePosixPath(self.journal.relative_to(self.staging_root).as_posix())
        if any(_relative_overlap(journal_relative, path) for path in [*staged, *backups]):
            raise PublicationTransactionError("journal path overlaps a staged or backup artifact")
        self._states = [
            {"phase": "pending", "had_final": False, "staged_digest": _staged_digest(self.staging_root, operation.staged, required=not self._recovery_mode)}
            for operation in self.operations
        ]

    @classmethod
    def from_journal(
        cls, *, workspace_root: Path, staging_root: Path, journal: Path
    ) -> "PublicationTransaction":
        try:
            raw = json.loads(journal.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PublicationTransactionError(f"cannot read rollback journal: {journal}") from exc
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            raise PublicationTransactionError("rollback journal is malformed")
        entries = raw.get("operations")
        if not isinstance(entries, list):
            raise PublicationTransactionError("rollback journal operations must be a list")
        operations: list[PublicationOperation] = []
        states: list[dict[str, object]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise PublicationTransactionError("rollback journal operation must be an object")
            final = _relative_path(entry.get("final"), "final")
            staged_raw = entry.get("staged")
            staged = _relative_path(staged_raw, "staged") if staged_raw is not None else None
            operation = PublicationOperation(final, staged)
            backup = _relative_path(entry.get("backup"), "backup")
            if backup != operation.backup:
                raise PublicationTransactionError("rollback journal backup path is unsafe")
            backed_up, installed = entry.get("backed_up"), entry.get("installed")
            if not isinstance(backed_up, bool) or not isinstance(installed, bool):
                raise PublicationTransactionError("rollback journal operation flags must be booleans")
            operations.append(operation)
            phase = entry.get("phase")
            legacy_marker = entry.get("legacy")
            if legacy_marker is not None and not isinstance(legacy_marker, bool):
                raise PublicationTransactionError("rollback journal legacy marker is malformed")
            raw_legacy = legacy_marker is None and phase is None
            legacy = raw_legacy or legacy_marker is True
            if raw_legacy:
                phase = phase or ("installed" if installed else "backed_up" if backed_up else "pending")
            if not isinstance(phase, str) or phase not in _PHASES:
                raise PublicationTransactionError("rollback journal operation phase is malformed")
            if legacy and not raw_legacy and "had_final" not in entry:
                raise PublicationTransactionError("rewritten legacy operation has no final ownership state")
            had_final = entry.get("had_final", backed_up)
            staged_digest = entry.get("staged_digest")
            rollback_digest = entry.get("rollback_digest")
            if not isinstance(had_final, bool) or (staged_digest is not None and (not isinstance(staged_digest, str) or not _DIGEST.fullmatch(staged_digest))):
                raise PublicationTransactionError("rollback journal operation state is malformed")
            if rollback_digest is not None and (
                not isinstance(rollback_digest, str) or not _DIGEST.fullmatch(rollback_digest)
            ):
                raise PublicationTransactionError("rollback journal ownership digest is malformed")
            if not raw_legacy:
                expected_backed_up = had_final and phase in {"backed_up", "install_intent", "installed", "rollback_remove_intent", "restore_intent"}
                expected_installed = phase in {"installed", "rollback_remove_intent"}
                if backed_up != expected_backed_up or installed != expected_installed:
                    raise PublicationTransactionError("rollback journal operation flags contradict its phase")
                if phase == "pending" and had_final:
                    raise PublicationTransactionError("rollback journal pending operation cannot have a final backup")
                if phase in {"backup_intent", "backed_up", "restore_intent"} and not had_final:
                    raise PublicationTransactionError("rollback journal backup phase requires an original final path")
                if operation.staged is None and staged_digest is not None:
                    raise PublicationTransactionError("rollback journal deletion operation has a staged digest")
                if operation.staged is None and phase in {"install_intent", "installed", "rollback_remove_intent"}:
                    raise PublicationTransactionError("rollback journal deletion operation cannot have an install phase")
                if not legacy and operation.staged is not None and staged_digest is None:
                    raise PublicationTransactionError("rollback journal staged operation has no digest")
                if legacy and operation.staged is not None and staged_digest is None and rollback_digest is None and phase not in {"pending", "backup_intent", "backed_up", "restore_intent"}:
                    raise PublicationTransactionError("rewritten legacy operation may delete a final without an ownership digest")
                if legacy and phase in {"install_intent", "installed", "rollback_remove_intent"} and rollback_digest is None:
                    raise PublicationTransactionError("rewritten legacy operation has no ownership digest")
                if not legacy and rollback_digest is not None:
                    raise PublicationTransactionError("new rollback journal cannot carry a legacy ownership digest")
            states.append({"phase": phase, "had_final": had_final, "staged_digest": staged_digest, "rollback_digest": rollback_digest, "legacy": legacy, "raw_legacy": raw_legacy})
        transaction = cls(
            workspace_root=workspace_root,
            staging_root=staging_root,
            journal=journal,
            operations=tuple(operations), _recovery_mode=True,
        )
        transaction._states = states
        return transaction


def write_publication_journal(transaction: PublicationTransaction, status: str) -> None:
    if status not in {"prepared", "replacing", "rolling_back", "complete", "rolled_back"}:
        raise PublicationTransactionError(f"unknown transaction status: {status!r}")
    operations = []
    for operation, state in zip(transaction.operations, transaction._states, strict=True):
        operations.append(
            {
                "final": operation.final.as_posix(),
                "staged": operation.staged.as_posix() if operation.staged else None,
                "backup": operation.backup.as_posix(),
                "backed_up": state["had_final"] and state["phase"] in {"backed_up", "install_intent", "installed", "rollback_remove_intent", "restore_intent"},
                "installed": state["phase"] in {"installed", "rollback_remove_intent"},
                "phase": state["phase"],
                "had_final": state["had_final"],
                "staged_digest": state["staged_digest"],
                "rollback_digest": state.get("rollback_digest"),
                "legacy": bool(state.get("legacy")),
            }
        )
    write_json_atomic(transaction.journal, {"schema_version": 1, "status": status, "operations": operations})


def apply_publication_transaction(
    transaction: PublicationTransaction, *, fault_hook: Callable[[str], None] | None = None
) -> None:
    """Apply operations in declared order, rolling back exact prior bytes on failure."""
    write_publication_journal(transaction, "replacing")
    try:
        for index, operation in enumerate(transaction.operations):
            final = _contained(transaction.workspace_root, operation.final)
            backup = _contained(transaction.staging_root, operation.backup)
            staged = (
                _contained(transaction.staging_root, operation.staged, exists=True)
                if operation.staged is not None
                else None
            )
            if fault_hook:
                fault_hook(f"before_operation:{operation.final.as_posix()}")
            if final.exists() or final.is_symlink():
                _contained(transaction.workspace_root, operation.final, exists=True)
                transaction._states[index]["had_final"] = True
                transaction._states[index]["phase"] = "backup_intent"
                write_publication_journal(transaction, "replacing")
                if fault_hook:
                    fault_hook(f"after_backup_intent:{operation.final.as_posix()}")
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(final, backup)
                _fsync_directory(final.parent)
                _fsync_directory(backup.parent)
                if fault_hook:
                    fault_hook(f"after_backup_rename:{operation.final.as_posix()}")
                transaction._states[index]["phase"] = "backed_up"
                write_publication_journal(transaction, "replacing")
                if fault_hook:
                    fault_hook(f"after_backup:{operation.final.as_posix()}")
            if staged is not None:
                if fault_hook:
                    fault_hook(f"before_replace:{operation.final.as_posix()}")
                transaction._states[index]["phase"] = "install_intent"
                write_publication_journal(transaction, "replacing")
                if fault_hook:
                    fault_hook(f"after_install_intent:{operation.final.as_posix()}")
                expected_digest = transaction._states[index].get("staged_digest")
                if not isinstance(expected_digest, str) or _path_digest(staged) != expected_digest:
                    raise PublicationTransactionError("staged artifact changed before install")
                final.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged, final)
                _fsync_directory(final.parent)
                _fsync_directory(staged.parent)
                if fault_hook:
                    fault_hook(f"after_install_rename:{operation.final.as_posix()}")
                transaction._states[index]["phase"] = "installed"
                write_publication_journal(transaction, "replacing")
                if fault_hook:
                    fault_hook(f"after_replace:{operation.final.as_posix()}")
        write_publication_journal(transaction, "complete")
    except Exception:
        rollback_publication_transaction(transaction)
        raise


def rollback_publication_transaction(
    transaction: PublicationTransaction,
    *,
    fault_hook: Callable[[str], None] | None = None,
) -> None:
    """Idempotently restore only paths recorded as replaced by this transaction."""
    if not any(state.get("raw_legacy") for state in transaction._states):
        write_publication_journal(transaction, "rolling_back")
    for index in range(len(transaction.operations) - 1, -1, -1):
        operation = transaction.operations[index]
        state = transaction._states[index]
        final = _contained(transaction.workspace_root, operation.final)
        backup = _contained(transaction.staging_root, operation.backup)
        staged = _contained(transaction.staging_root, operation.staged) if operation.staged is not None else None
        phase = state["phase"]
        final_exists = final.exists() or final.is_symlink()
        backup_exists = backup.exists() or backup.is_symlink()
        if state.get("legacy") and phase == "installed" and state.get("had_final") and final_exists and not backup_exists:
            # A legacy rollback may have restored the original just before its
            # boolean journal update; it is already safe and must be retained.
            state["phase"] = "pending"
            state["had_final"] = False
            state["raw_legacy"] = False
            write_publication_journal(transaction, "rolling_back")
            continue
        if state.get("legacy") and phase in {"installed", "restore_intent"} and state.get("had_final") and not final_exists and backup_exists:
            # Old rollback removed the installed final before it persisted the
            # next boolean state. The original backup remains authoritative.
            state["phase"] = "backed_up"
            phase = "backed_up"
            state["raw_legacy"] = False
        elif state.get("legacy") and backup_exists and not final_exists:
            if staged is not None and not (staged.exists() or staged.is_symlink()):
                raise PublicationTransactionError(
                    "legacy rollback journal has an incoherent backup-rename state"
                )
            state["phase"] = "backed_up"
            state["had_final"] = True
            phase = "backed_up"
            state["raw_legacy"] = False
        elif state.get("legacy") and backup_exists and final_exists and phase == "backed_up" and staged is not None and not (staged.exists() or staged.is_symlink()):
            state["phase"] = "installed"
            phase = "installed"
        elif state.get("legacy") and not backup_exists and final_exists and phase == "pending" and staged is not None and not (staged.exists() or staged.is_symlink()):
            state["phase"] = "installed"
            state["had_final"] = False
            phase = "installed"
        elif state.get("legacy") and phase == "pending" and backup_exists and final_exists:
            raise PublicationTransactionError("legacy rollback journal has ambiguous final and backup paths")
        if phase == "pending":
            if state.get("raw_legacy"):
                state["raw_legacy"] = False
                write_publication_journal(transaction, "rolling_back")
            continue
        installed = phase in {"install_intent", "installed", "rollback_remove_intent"}
        if state.get("had_final") and installed and final_exists and not backup_exists:
            raise PublicationTransactionError("rollback required backup is missing before final removal")
        if not state.get("had_final") and backup_exists and not (state.get("legacy") and not final_exists):
            raise PublicationTransactionError("rollback found a stray backup for a no-original operation")
        if final_exists and installed:
            if state.get("legacy"):
                if state.get("raw_legacy"):
                    state["rollback_digest"] = _path_digest(final)
                    state["raw_legacy"] = False
                    write_publication_journal(transaction, "rolling_back")
                expected = state.get("rollback_digest")
            else:
                expected = state.get("staged_digest")
            if not isinstance(expected, str) or _path_digest(final) != expected:
                raise PublicationTransactionError("rollback refuses to delete a final path not installed by this transaction")
            state["phase"] = "rollback_remove_intent"
            write_publication_journal(transaction, "rolling_back")
            _remove_path(final)
            _fsync_directory(final.parent)
            final_exists = False
        elif final_exists and backup_exists:
            raise PublicationTransactionError("rollback found an unrelated final path beside its backup")
        if backup_exists:
            state["phase"] = "restore_intent"
            if state.get("raw_legacy"):
                state["raw_legacy"] = False
            write_publication_journal(transaction, "rolling_back")
            if fault_hook:
                fault_hook(f"before_restore:{operation.final.as_posix()}")
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(backup, final)
            _fsync_directory(final.parent)
            _fsync_directory(backup.parent)
        elif state.get("had_final") and not final_exists:
            raise PublicationTransactionError("rollback backup is missing after a replacement intent")
        state["phase"] = "pending"
        state["had_final"] = False
        state["raw_legacy"] = False
        write_publication_journal(transaction, "rolling_back")
    write_publication_journal(transaction, "rolled_back")


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
        _fsync_directory(path.parent)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _relative_overlap(left: PurePosixPath, right: PurePosixPath) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _absolute_overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _path_digest(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_symlink():
        raise PublicationTransactionError("transaction artifacts must not be symlinks")
    if path.is_file():
        digest.update(b"file\0")
        digest.update(path.read_bytes())
    elif path.is_dir():
        digest.update(b"dir\0")
        for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
            relative = child.relative_to(path).as_posix()
            if child.is_symlink():
                raise PublicationTransactionError("transaction artifacts must not contain symlinks")
            content = b"" if child.is_dir() else child.read_bytes()
            entry = json.dumps({"path": relative, "type": "dir" if child.is_dir() else "file", "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}, sort_keys=True, separators=(",", ":")).encode("utf-8")
            digest.update(len(entry).to_bytes(8, "big"))
            digest.update(entry)
    else:
        raise PublicationTransactionError(f"transaction staged artifact is missing: {path}")
    return "sha256:" + digest.hexdigest()


def _staged_digest(
    root: Path, relative: PurePosixPath | None, *, required: bool
) -> str | None:
    if relative is None:
        return None
    path = _contained(root, relative)
    if not path.exists() or path.is_symlink():
        if required:
            raise PublicationTransactionError("staged artifact is missing or symlinked")
        return None
    return _path_digest(path)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
