"""Path-safe, rollback-capable workspace artifact publication primitives."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable


class PublicationTransactionError(RuntimeError):
    """Raised when a workspace artifact transaction is unsafe or incomplete."""


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
    _states: list[dict[str, bool]] = field(init=False, repr=False)

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
        seen: set[PurePosixPath] = set()
        for operation in self.operations:
            if operation.final in seen:
                raise PublicationTransactionError("duplicate final publication operation")
            seen.add(operation.final)
            _contained(self.workspace_root, operation.final)
            _contained(self.staging_root, operation.backup)
            if operation.staged is not None:
                _contained(self.staging_root, operation.staged)
        self._states = [{"backed_up": False, "installed": False} for _ in self.operations]

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
        states: list[dict[str, bool]] = []
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
            states.append({"backed_up": backed_up, "installed": installed})
        transaction = cls(
            workspace_root=workspace_root,
            staging_root=staging_root,
            journal=journal,
            operations=tuple(operations),
        )
        transaction._states = states
        return transaction


def write_publication_journal(transaction: PublicationTransaction, status: str) -> None:
    if status not in {"prepared", "replacing", "complete", "rolled_back"}:
        raise PublicationTransactionError(f"unknown transaction status: {status!r}")
    operations = []
    for operation, state in zip(transaction.operations, transaction._states, strict=True):
        operations.append(
            {
                "final": operation.final.as_posix(),
                "staged": operation.staged.as_posix() if operation.staged else None,
                "backup": operation.backup.as_posix(),
                "backed_up": state["backed_up"],
                "installed": state["installed"],
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
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(final, backup)
                transaction._states[index]["backed_up"] = True
                write_publication_journal(transaction, "replacing")
                if fault_hook:
                    fault_hook(f"after_backup:{operation.final.as_posix()}")
            if staged is not None:
                if fault_hook:
                    fault_hook(f"before_replace:{operation.final.as_posix()}")
                final.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged, final)
                transaction._states[index]["installed"] = True
                write_publication_journal(transaction, "replacing")
                if fault_hook:
                    fault_hook(f"after_replace:{operation.final.as_posix()}")
        write_publication_journal(transaction, "complete")
    except Exception:
        rollback_publication_transaction(transaction)
        raise


def rollback_publication_transaction(transaction: PublicationTransaction) -> None:
    """Idempotently restore only paths recorded as replaced by this transaction."""
    for index in range(len(transaction.operations) - 1, -1, -1):
        operation = transaction.operations[index]
        state = transaction._states[index]
        final = _contained(transaction.workspace_root, operation.final)
        backup = _contained(transaction.staging_root, operation.backup)
        if state["installed"] and (final.exists() or final.is_symlink()):
            _remove_path(final)
            state["installed"] = False
        if state["backed_up"] and (backup.exists() or backup.is_symlink()):
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(backup, final)
            state["backed_up"] = False
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
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
