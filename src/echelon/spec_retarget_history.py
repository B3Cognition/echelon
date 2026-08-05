"""Durable, append-only change control for destructive spec retargets."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
from typing import Mapping

from echelon.strict_json import loads_strict_json
from echelon.target_normalization import normalize_target_set
from harness.phase_checkpoints import _checkpoint_ledger_lock


RETARGET_HISTORY_FILENAME = "retarget-history.json"
RETARGET_HISTORY_SCHEMA_VERSION = 1

_MAX_REVISIONS = 128
_MAX_HISTORY_BYTES = 2 * 1024 * 1024
_MAX_ID_LENGTH = 256
_MAX_TARGET_LENGTH = 1024
_MAX_TARGETS = 128
_MAX_COMPLETED_PHASES = 128
_MAX_ARTIFACTS = 512
_MAX_RECEIPT_ITEMS = 512
_MAX_RECEIPT_DEPTH = 8
_MAX_RECEIPT_STRING = 16 * 1024

_IDENTITY_PATTERN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")
_SHA256_PATTERN = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
_GIT_OBJECT_ID_PATTERN = re.compile(r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_TRAILER_PATTERN = re.compile(r"^([A-Za-z0-9-]+):[ \t]*(.*?)\s*$")
_COMPLETION_ID_PATTERN = re.compile(r"\A[0-9a-f]{32}\Z")
_TERMINAL_COMMIT_FIELDS = {
    "complete": ("replacement_commit", "retarget-complete"),
    "recovered": ("recovery_commit", "retarget-recovered"),
}

_TRANSITIONS = {
    "prepared": frozenset({"invalidating", "failed"}),
    "invalidating": frozenset({"rebuilding", "failed"}),
    "rebuilding": frozenset({"finalizing", "failed"}),
    "finalizing": frozenset({"complete", "failed"}),
    "failed": frozenset({"recovered"}),
    "complete": frozenset(),
    "recovered": frozenset(),
}
_TERMINAL_APPEND_STATUSES = frozenset({"complete", "recovered"})

_RECOVERY_KEYS = frozenset(
    {
        "run_id",
        "status",
        "phase",
        "spec_status",
        "completed_phases",
        "implementation_targets",
        "ready_to_build",
    }
)
_REVISION_KEYS = frozenset(
    {
        "revision_id",
        "operation_id",
        "status",
        "created_at",
        "updated_at",
        "baseline_run_id",
        "replacement_run_id",
        "old_targets",
        "replacement_targets",
        "original_prompt_digest",
        "recovery",
        "checkpoint_parent",
        "checkpoint_id",
        "checkpoint_commit",
        "artifact_inventory",
        "memory_purge",
        "graph_invalidation",
        "memory_finalization",
        "graph_finalization",
        "replacement_commit",
        "recovery_commit",
        "failure_code",
    }
)
_HISTORY_KEYS = frozenset({"schema_version", "spec_id", "revisions"})
_MUTABLE_FIELDS = frozenset(
    {
        "checkpoint_id",
        "checkpoint_commit",
        "artifact_inventory",
        "memory_purge",
        "graph_invalidation",
        "memory_finalization",
        "graph_finalization",
        "replacement_commit",
        "recovery_commit",
        "failure_code",
    }
)


@dataclass(frozen=True)
class RetargetRecoveryProjection:
    run_id: str
    status: str
    phase: str
    spec_status: str
    completed_phases: tuple[str, ...]
    implementation_targets: tuple[str, ...]
    ready_to_build: bool


@dataclass(frozen=True)
class RetargetRevision:
    revision_id: str
    operation_id: str
    status: str
    created_at: str
    updated_at: str
    baseline_run_id: str
    replacement_run_id: str
    old_targets: tuple[str, ...]
    replacement_targets: tuple[str, ...]
    original_prompt_digest: str
    recovery: RetargetRecoveryProjection
    checkpoint_parent: str | None = None
    checkpoint_id: str | None = None
    checkpoint_commit: str | None = None
    artifact_inventory: tuple[Mapping[str, object], ...] = ()
    memory_purge: Mapping[str, object] | None = None
    graph_invalidation: Mapping[str, object] | None = None
    memory_finalization: Mapping[str, object] | None = None
    graph_finalization: Mapping[str, object] | None = None
    replacement_commit: str | None = None
    recovery_commit: str | None = None
    failure_code: str | None = None


@dataclass(frozen=True)
class RetargetHistory:
    schema_version: int
    spec_id: str
    revisions: tuple[RetargetRevision, ...]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_exact_keys(
    value: object,
    expected: frozenset[str],
    *,
    label: str,
) -> dict[str, object]:
    if type(value) is not dict or frozenset(value) != expected:
        raise ValueError(f"invalid {label} keys")
    return value


def _require_identity(value: object, *, field: str) -> str:
    if type(value) is not str or _IDENTITY_PATTERN.fullmatch(value) is None:
        raise ValueError(f"invalid retarget {field}")
    return value


def _require_string(
    value: object,
    *,
    field: str,
    maximum: int = _MAX_ID_LENGTH,
    allow_empty: bool = False,
) -> str:
    if (
        type(value) is not str
        or len(value) > maximum
        or (not value and not allow_empty)
        or value != value.strip()
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError(f"invalid retarget {field}")
    return value


def _require_optional_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field=field)


def _require_timestamp(value: object, *, field: str) -> str:
    text = _require_string(value, field=field, maximum=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid retarget {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"invalid retarget {field}")
    return text


def _require_strings(
    value: object,
    *,
    field: str,
    maximum_items: int,
    maximum_length: int,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if type(value) not in {list, tuple} or len(value) > maximum_items:
        raise ValueError(f"invalid retarget {field}")
    items = tuple(
        _require_string(item, field=field, maximum=maximum_length)
        for item in value
    )
    if not items and not allow_empty:
        raise ValueError(f"invalid retarget {field}")
    if len(set(items)) != len(items):
        raise ValueError(f"duplicate retarget {field}")
    return items


def _require_targets(value: object, *, field: str) -> tuple[str, ...]:
    items = _require_strings(
        value,
        field=field,
        maximum_items=_MAX_TARGETS,
        maximum_length=_MAX_TARGET_LENGTH,
    )
    if normalize_target_set(items) != items:
        raise ValueError(f"invalid retarget canonical target set: {field}")
    return items


def _require_git_oid(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or _GIT_OBJECT_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"invalid retarget {field}")
    return value


def _require_receipt_value(value: object, *, field: str, depth: int = 0) -> object:
    if depth > _MAX_RECEIPT_DEPTH:
        raise ValueError(f"invalid retarget {field}")
    if value is None or type(value) in {bool, int}:
        return value
    if type(value) is str:
        return _require_string(
            value,
            field=field,
            maximum=_MAX_RECEIPT_STRING,
            allow_empty=True,
        )
    if type(value) is list:
        if len(value) > _MAX_RECEIPT_ITEMS:
            raise ValueError(f"invalid retarget {field}")
        return [
            _require_receipt_value(item, field=field, depth=depth + 1)
            for item in value
        ]
    if type(value) is dict:
        if len(value) > _MAX_RECEIPT_ITEMS:
            raise ValueError(f"invalid retarget {field}")
        result: dict[str, object] = {}
        for key, item in value.items():
            clean_key = _require_string(
                key,
                field=field,
                maximum=_MAX_ID_LENGTH,
            )
            normalized_key = clean_key.lower()
            if (
                normalized_key == "sha256"
                or normalized_key == "hash"
                or "digest" in normalized_key
                or normalized_key.endswith("_hash")
                or normalized_key.endswith("_sha256")
            ) and item is not None:
                if type(item) is not str or _SHA256_PATTERN.fullmatch(item) is None:
                    raise ValueError(f"invalid retarget {field}")
            if (
                normalized_key == "commit"
                or normalized_key.endswith("_commit")
            ) and item is not None:
                if type(item) is not str or _GIT_OBJECT_ID_PATTERN.fullmatch(item) is None:
                    raise ValueError(f"invalid retarget {field}")
            result[clean_key] = _require_receipt_value(
                item,
                field=field,
                depth=depth + 1,
            )
        return result
    raise ValueError(f"invalid retarget {field}")


def _require_optional_receipt(value: object, *, field: str) -> Mapping[str, object] | None:
    if value is None:
        return None
    checked = _require_receipt_value(value, field=field)
    if type(checked) is not dict:
        raise ValueError(f"invalid retarget {field}")
    return checked


def _recovery_from_raw(value: object) -> RetargetRecoveryProjection:
    raw = _require_exact_keys(value, _RECOVERY_KEYS, label="retarget recovery")
    ready = raw["ready_to_build"]
    if type(ready) is not bool:
        raise ValueError("invalid retarget recovery ready_to_build")
    return RetargetRecoveryProjection(
        run_id=_require_identity(raw["run_id"], field="recovery run_id"),
        status=_require_string(raw["status"], field="recovery status"),
        phase=_require_string(raw["phase"], field="recovery phase"),
        spec_status=_require_string(
            raw["spec_status"],
            field="recovery spec_status",
        ),
        completed_phases=_require_strings(
            raw["completed_phases"],
            field="recovery completed_phases",
            maximum_items=_MAX_COMPLETED_PHASES,
            maximum_length=_MAX_ID_LENGTH,
            allow_empty=True,
        ),
        implementation_targets=_require_targets(
            raw["implementation_targets"],
            field="recovery implementation_targets",
        ),
        ready_to_build=ready,
    )


def _revision_from_raw(value: object) -> RetargetRevision:
    raw = _require_exact_keys(value, _REVISION_KEYS, label="retarget revision")
    status_value = raw["status"]
    if type(status_value) is not str or status_value not in _TRANSITIONS:
        raise ValueError("invalid retarget revision status")
    prompt_digest = raw["original_prompt_digest"]
    if type(prompt_digest) is not str or _SHA256_PATTERN.fullmatch(prompt_digest) is None:
        raise ValueError("invalid retarget original_prompt_digest")
    recovery = _recovery_from_raw(raw["recovery"])
    baseline_run_id = _require_identity(raw["baseline_run_id"], field="baseline_run_id")
    if recovery.run_id != baseline_run_id:
        raise ValueError("retarget recovery run_id does not match baseline_run_id")
    replacement_run_id = _require_identity(
        raw["replacement_run_id"],
        field="replacement_run_id",
    )
    if replacement_run_id == baseline_run_id:
        raise ValueError("retarget replacement_run_id must differ from baseline_run_id")
    old_targets = _require_targets(raw["old_targets"], field="old_targets")
    replacement_targets = _require_targets(
        raw["replacement_targets"],
        field="replacement_targets",
    )
    if recovery.implementation_targets != old_targets:
        raise ValueError(
            "retarget recovery implementation_targets do not match old_targets"
        )
    if replacement_targets == old_targets:
        raise ValueError("retarget replacement_targets must differ from old_targets")
    artifact_value = raw["artifact_inventory"]
    if type(artifact_value) not in {list, tuple} or len(artifact_value) > _MAX_ARTIFACTS:
        raise ValueError("invalid retarget artifact_inventory")
    artifacts: list[Mapping[str, object]] = []
    for item in artifact_value:
        checked = _require_optional_receipt(item, field="artifact_inventory")
        if checked is None:
            raise ValueError("invalid retarget artifact_inventory")
        artifacts.append(checked)
    return RetargetRevision(
        revision_id=_require_identity(raw["revision_id"], field="revision_id"),
        operation_id=_require_identity(raw["operation_id"], field="operation_id"),
        status=status_value,
        created_at=_require_timestamp(raw["created_at"], field="created_at"),
        updated_at=_require_timestamp(raw["updated_at"], field="updated_at"),
        baseline_run_id=baseline_run_id,
        replacement_run_id=replacement_run_id,
        old_targets=old_targets,
        replacement_targets=replacement_targets,
        original_prompt_digest=prompt_digest,
        recovery=recovery,
        checkpoint_parent=_require_git_oid(
            raw["checkpoint_parent"],
            field="checkpoint_parent",
        ),
        checkpoint_id=_require_optional_string(
            raw["checkpoint_id"],
            field="checkpoint_id",
        ),
        checkpoint_commit=_require_git_oid(
            raw["checkpoint_commit"],
            field="checkpoint_commit",
        ),
        artifact_inventory=tuple(artifacts),
        memory_purge=_require_optional_receipt(raw["memory_purge"], field="memory_purge"),
        graph_invalidation=_require_optional_receipt(
            raw["graph_invalidation"],
            field="graph_invalidation",
        ),
        memory_finalization=_require_optional_receipt(
            raw["memory_finalization"],
            field="memory_finalization",
        ),
        graph_finalization=_require_optional_receipt(
            raw["graph_finalization"],
            field="graph_finalization",
        ),
        replacement_commit=_require_git_oid(
            raw["replacement_commit"],
            field="replacement_commit",
        ),
        recovery_commit=_require_git_oid(
            raw["recovery_commit"],
            field="recovery_commit",
        ),
        failure_code=_require_optional_string(
            raw["failure_code"],
            field="failure_code",
        ),
    )


def _history_from_raw(value: object, *, spec_id: str) -> RetargetHistory:
    raw = _require_exact_keys(value, _HISTORY_KEYS, label="retarget history")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise ValueError("unsupported retarget history schema_version")
    stored_spec_id = _require_identity(raw["spec_id"], field="history spec_id")
    if stored_spec_id != spec_id:
        raise ValueError("retarget history spec_id does not match spec directory")
    revision_values = raw["revisions"]
    if type(revision_values) is not list:
        raise ValueError("invalid retarget history revisions")
    if len(revision_values) > _MAX_REVISIONS:
        raise ValueError("too many retarget revisions")
    revisions = tuple(_revision_from_raw(item) for item in revision_values)
    revision_ids = [item.revision_id for item in revisions]
    if len(set(revision_ids)) != len(revision_ids):
        raise ValueError("duplicate retarget revision identity")
    operation_ids = [item.operation_id for item in revisions]
    if len(set(operation_ids)) != len(operation_ids):
        raise ValueError("duplicate retarget operation identity")
    if any(
        item.status not in _TERMINAL_APPEND_STATUSES
        for item in revisions[:-1]
    ):
        raise ValueError(
            "historical retarget revision is not complete or recovered"
        )
    return RetargetHistory(
        schema_version=RETARGET_HISTORY_SCHEMA_VERSION,
        spec_id=stored_spec_id,
        revisions=revisions,
    )


def _history_to_raw(history: RetargetHistory) -> dict[str, object]:
    return {
        "schema_version": history.schema_version,
        "spec_id": history.spec_id,
        "revisions": [asdict(revision) for revision in history.revisions],
    }


def _validate_history(history: RetargetHistory, *, spec_id: str) -> RetargetHistory:
    return _history_from_raw(_history_to_raw(history), spec_id=spec_id)


def _read_regular_file(path: Path) -> bytes:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        raise
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("retarget history must be a regular file")
    if metadata.st_size > _MAX_HISTORY_BYTES:
        raise ValueError("retarget history exceeds size limit")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("could not read retarget history") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError("retarget history must be a regular file")
        chunks: list[bytes] = []
        remaining = _MAX_HISTORY_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > _MAX_HISTORY_BYTES:
            raise ValueError("retarget history exceeds size limit")
        return content
    finally:
        os.close(descriptor)


def load_retarget_history(spec_dir: Path) -> RetargetHistory:
    directory = Path(spec_dir)
    spec_id = _require_identity(directory.name, field="spec_id")
    path = directory / RETARGET_HISTORY_FILENAME
    try:
        content = _read_regular_file(path)
    except FileNotFoundError:
        return RetargetHistory(
            schema_version=RETARGET_HISTORY_SCHEMA_VERSION,
            spec_id=spec_id,
            revisions=(),
        )
    try:
        raw = loads_strict_json(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid retarget history JSON") from exc
    history = _history_from_raw(raw, spec_id=spec_id)
    return _overlay_terminal_commit_binding(directory, history)


def _retarget_git_root(directory: Path) -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=directory,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    root = Path(result.stdout.strip()).resolve()
    if directory.resolve().parent != root / "specs":
        raise ValueError("retarget history is outside the repository spec root")
    return root


def _terminal_commit_trailers_match(
    message: str,
    revision: RetargetRevision,
    action: str,
    spec_id: str,
) -> bool:
    values: dict[str, list[str]] = {}
    for line in message.splitlines():
        match = _TRAILER_PATTERN.fullmatch(line)
        if match is not None and match.group(1).startswith("Echelon-"):
            values.setdefault(match.group(1), []).append(match.group(2))
    expected = {
        "Echelon-Origin": "phase-a",
        "Echelon-Action": action,
        "Echelon-Spec": spec_id,
        "Echelon-Run": (
            revision.replacement_run_id
            if revision.status == "complete"
            else revision.baseline_run_id
        ),
        "Echelon-Checkpoint": str(revision.checkpoint_id),
        "Echelon-Retarget-Revision": revision.revision_id,
        "Echelon-Baseline-Run": revision.baseline_run_id,
        "Echelon-Replacement-Run": revision.replacement_run_id,
    }
    if revision.status == "complete":
        completion = values.get("Echelon-Completion")
        if (
            completion is None
            or len(completion) != 1
            or _COMPLETION_ID_PATTERN.fullmatch(completion[0]) is None
        ):
            return False
        expected["Echelon-Completion"] = completion[0]
    return frozenset(values) == frozenset(expected) and all(
        values.get(key) == [value] for key, value in expected.items()
    )


def _verify_terminal_commit(
    directory: Path,
    history: RetargetHistory,
    commit: str,
) -> bool:
    if not history.revisions or _GIT_OBJECT_ID_PATTERN.fullmatch(commit) is None:
        return False
    revision = history.revisions[-1]
    terminal = _TERMINAL_COMMIT_FIELDS.get(revision.status)
    if terminal is None:
        return False
    field, action = terminal
    if getattr(revision, field) not in {None, commit}:
        return False
    root = _retarget_git_root(directory)
    if root is None:
        return False
    resolved = subprocess.run(
        ["git", "rev-parse", "--verify", f"{commit}^{{commit}}"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    parents = subprocess.run(
        ["git", "rev-list", "--parents", "-n", "1", commit],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    checkpoint_ancestor = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            str(revision.checkpoint_commit),
            f"{commit}^",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    message = subprocess.run(
        ["git", "show", "-s", "--format=%B", commit],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    paths = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    committed_history = subprocess.run(
        ["git", "show", f"{commit}:specs/{directory.name}/{RETARGET_HISTORY_FILENAME}"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    live_tree = subprocess.run(
        ["git", "diff", "--quiet", commit, "--", f"specs/{directory.name}"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    changed = tuple(line for line in paths.stdout.splitlines() if line)
    prefix = f"specs/{directory.name}/"
    parent_line = parents.stdout.split()
    try:
        live_history = _read_regular_file(directory / RETARGET_HISTORY_FILENAME)
    except (OSError, ValueError):
        return False
    return (
        resolved.returncode == 0
        and resolved.stdout.strip() == commit
        and parents.returncode == 0
        and len(parent_line) == 2
        and checkpoint_ancestor.returncode == 0
        and message.returncode == 0
        and paths.returncode == 0
        and committed_history.returncode == 0
        and live_tree.returncode == 0
        and committed_history.stdout == live_history
        and bool(changed)
        and all(path.startswith(prefix) for path in changed)
        and _terminal_commit_trailers_match(
            message.stdout,
            revision,
            action,
            directory.name,
        )
    )


def _overlay_terminal_commit_binding(
    directory: Path,
    history: RetargetHistory,
) -> RetargetHistory:
    if not history.revisions:
        return history
    revision = history.revisions[-1]
    terminal = _TERMINAL_COMMIT_FIELDS.get(revision.status)
    if terminal is None:
        return history
    _require_latest_terminal_commit_fields_null(history)
    field, action = terminal
    root = _retarget_git_root(directory)
    if root is None:
        return history
    discovered = subprocess.run(
        [
            "git",
            "log",
            "--all",
            "--fixed-strings",
            "--all-match",
            f"--grep=Echelon-Action: {action}",
            f"--grep=Echelon-Retarget-Revision: {revision.revision_id}",
            "--format=%H",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if discovered.returncode != 0:
        raise ValueError("retarget terminal commit history is unavailable")
    candidates = tuple(
        line for line in discovered.stdout.splitlines() if line
    )
    if not candidates:
        return history
    for commit in candidates:
        if not _verify_terminal_commit(directory, history, commit):
            raise ValueError("retarget terminal commit binding is invalid")
    if len(candidates) != 1:
        raise ValueError("duplicate retarget terminal commit bindings")
    commit = candidates[0]
    bound = replace(revision, **{field: commit})
    return replace(history, revisions=(*history.revisions[:-1], bound))


def _require_latest_terminal_commit_fields_null(history: RetargetHistory) -> None:
    if not history.revisions:
        return
    latest = history.revisions[-1]
    if (
        latest.status in _TERMINAL_COMMIT_FIELDS
        and (
            latest.replacement_commit is not None
            or latest.recovery_commit is not None
        )
    ):
        raise ValueError("latest terminal commit fields must be null")


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_history_atomic(spec_dir: Path, history: RetargetHistory) -> None:
    directory = Path(spec_dir)
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("retarget spec directory must be a real directory")
    validated = _validate_history(history, spec_id=directory.name)
    _require_latest_terminal_commit_fields_null(validated)
    path = directory / RETARGET_HISTORY_FILENAME
    try:
        existing = path.lstat()
    except FileNotFoundError:
        existing = None
    if existing is not None and not stat.S_ISREG(existing.st_mode):
        raise ValueError("retarget history must be a regular file")
    content = (
        json.dumps(_history_to_raw(validated), indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if len(content) > _MAX_HISTORY_BYTES:
        raise ValueError("retarget history exceeds size limit")
    temporary = directory / (
        f".{RETARGET_HISTORY_FILENAME}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(temporary, flags, 0o600)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("retarget history temporary must be a regular file")
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written <= 0:
                raise OSError("short retarget history write")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
        _fsync_directory(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def append_prepared_revision(
    spec_dir: Path,
    *,
    operation_id: str,
    baseline_run_id: str,
    replacement_run_id: str,
    old_targets: tuple[str, ...],
    replacement_targets: tuple[str, ...],
    original_prompt_digest: str,
    recovery: RetargetRecoveryProjection,
    artifact_inventory: tuple[Mapping[str, object], ...] = (),
) -> RetargetRevision:
    directory = Path(spec_dir)
    with _checkpoint_ledger_lock(directory):
        history = load_retarget_history(directory)
        if history.revisions and history.revisions[-1].status not in _TERMINAL_APPEND_STATUSES:
            raise ValueError("latest retarget revision is not terminal")
        timestamp = _now()
        revision = RetargetRevision(
            revision_id=f"retarget-{secrets.token_hex(16)}",
            operation_id=operation_id,
            status="prepared",
            created_at=timestamp,
            updated_at=timestamp,
            baseline_run_id=baseline_run_id,
            replacement_run_id=replacement_run_id,
            old_targets=tuple(old_targets),
            replacement_targets=tuple(replacement_targets),
            original_prompt_digest=original_prompt_digest,
            recovery=recovery,
            artifact_inventory=tuple(dict(item) for item in artifact_inventory),
        )
        updated = replace(history, revisions=(*history.revisions, revision))
        validated = _validate_history(updated, spec_id=directory.name)
        _write_history_atomic(directory, validated)
        return validated.revisions[-1]


def _seal_retarget_checkpoint_parent_unlocked(
    spec_dir: Path,
    revision_id: str,
    *,
    checkpoint_parent: str,
) -> RetargetRevision:
    directory = Path(spec_dir)
    parent = _require_git_oid(
        checkpoint_parent,
        field="checkpoint_parent",
    )
    if parent is None:
        raise ValueError("invalid retarget checkpoint_parent")
    history = load_retarget_history(directory)
    if not history.revisions:
        raise ValueError("retarget revision precondition changed")
    latest = history.revisions[-1]
    if latest.revision_id != revision_id or latest.status != "prepared":
        raise ValueError("retarget revision precondition changed")
    if latest.checkpoint_parent is not None:
        if latest.checkpoint_parent == parent:
            return latest
        raise ValueError("retarget checkpoint_parent is already sealed")
    sealed = replace(
        latest,
        checkpoint_parent=parent,
        updated_at=_now(),
    )
    updated = replace(
        history,
        revisions=(*history.revisions[:-1], sealed),
    )
    validated = _validate_history(updated, spec_id=directory.name)
    _write_history_atomic(directory, validated)
    return validated.revisions[-1]


def seal_retarget_checkpoint_parent(
    spec_dir: Path,
    revision_id: str,
    *,
    checkpoint_parent: str,
) -> RetargetRevision:
    directory = Path(spec_dir)
    with _checkpoint_ledger_lock(directory):
        return _seal_retarget_checkpoint_parent_unlocked(
            directory,
            revision_id,
            checkpoint_parent=checkpoint_parent,
        )


def advance_retarget_revision(
    spec_dir: Path,
    revision_id: str,
    *,
    expected_status: str,
    status: str,
    updates: Mapping[str, object],
) -> RetargetRevision:
    directory = Path(spec_dir)
    if type(updates) is not dict:
        updates = dict(updates)
    unknown = frozenset(updates) - _MUTABLE_FIELDS
    if unknown:
        field = sorted(unknown)[0]
        raise ValueError(f"immutable retarget revision field: {field}")
    with _checkpoint_ledger_lock(directory):
        history = load_retarget_history(directory)
        if not history.revisions:
            raise ValueError("retarget revision precondition changed")
        latest = history.revisions[-1]
        if latest.revision_id != revision_id or latest.status != expected_status:
            raise ValueError("retarget revision precondition changed")
        if expected_status not in _TRANSITIONS or status not in _TRANSITIONS[expected_status]:
            raise ValueError(f"invalid retarget transition: {expected_status} -> {status}")
        replacement_revision = replace(
            latest,
            status=status,
            updated_at=_now(),
            **dict(updates),
        )
        updated = replace(
            history,
            revisions=(*history.revisions[:-1], replacement_revision),
        )
        validated = _validate_history(updated, spec_id=directory.name)
        _write_history_atomic(directory, validated)
        return validated.revisions[-1]


def bind_failed_recovery_effects(
    spec_dir: Path,
    revision_id: str,
    *,
    checkpoint_id: str,
    checkpoint_commit: str,
    memory_purge: Mapping[str, object],
    graph_invalidation: Mapping[str, object],
) -> RetargetRevision:
    """Bind replayed destructive receipts once to the failed revision."""

    directory = Path(spec_dir)
    memory = dict(memory_purge)
    graph = dict(graph_invalidation)
    with _checkpoint_ledger_lock(directory):
        history = load_retarget_history(directory)
        if not history.revisions:
            raise ValueError("retarget revision precondition changed")
        latest = history.revisions[-1]
        if latest.revision_id != revision_id or latest.status != "failed":
            raise ValueError("retarget revision precondition changed")
        if latest.checkpoint_id not in {None, checkpoint_id}:
            raise ValueError("retarget checkpoint_id is already bound")
        if latest.checkpoint_commit not in {None, checkpoint_commit}:
            raise ValueError("retarget checkpoint_commit is already bound")
        if latest.memory_purge is not None and latest.memory_purge != memory:
            raise ValueError("retarget memory_purge is already bound")
        if latest.graph_invalidation is not None and latest.graph_invalidation != graph:
            raise ValueError("retarget graph_invalidation is already bound")
        if (
            latest.checkpoint_id == checkpoint_id
            and latest.checkpoint_commit == checkpoint_commit
            and latest.memory_purge == memory
            and latest.graph_invalidation == graph
        ):
            return latest
        bound = replace(
            latest,
            checkpoint_id=checkpoint_id,
            checkpoint_commit=checkpoint_commit,
            memory_purge=memory,
            graph_invalidation=graph,
            updated_at=_now(),
        )
        updated = replace(history, revisions=(*history.revisions[:-1], bound))
        validated = _validate_history(updated, spec_id=directory.name)
        _write_history_atomic(directory, validated)
        return validated.revisions[-1]


def bind_recovered_revision_commit(
    spec_dir: Path,
    revision_id: str,
    *,
    recovery_commit: str,
) -> RetargetRevision:
    """Bind the proven recovery commit once without dirtying committed history."""

    return _bind_terminal_revision_commit(
        spec_dir,
        revision_id,
        expected_status="recovered",
        field="recovery_commit",
        commit=recovery_commit,
    )


def bind_completed_revision_commit(
    spec_dir: Path,
    revision_id: str,
    *,
    replacement_commit: str,
) -> RetargetRevision:
    """Bind the proven replacement commit once without dirtying committed history."""

    return _bind_terminal_revision_commit(
        spec_dir,
        revision_id,
        expected_status="complete",
        field="replacement_commit",
        commit=replacement_commit,
    )


def _bind_terminal_revision_commit(
    spec_dir: Path,
    revision_id: str,
    *,
    expected_status: str,
    field: str,
    commit: str,
) -> RetargetRevision:
    if _TERMINAL_COMMIT_FIELDS.get(expected_status, (None, None))[0] != field:
        raise ValueError("invalid terminal retarget binding")

    directory = Path(spec_dir)
    checked_commit = _require_git_oid(commit, field=field)
    if checked_commit is None:
        raise ValueError(f"invalid retarget {field}")
    with _checkpoint_ledger_lock(directory):
        history = load_retarget_history(directory)
        if not history.revisions:
            raise ValueError("retarget revision precondition changed")
        latest = history.revisions[-1]
        if latest.revision_id != revision_id or latest.status != expected_status:
            raise ValueError("retarget revision precondition changed")
        bound_commit = getattr(latest, field)
        if bound_commit is None:
            raise ValueError(f"retarget {field} cannot be verified")
        if bound_commit != checked_commit:
            raise ValueError(f"retarget {field} is already bound")
        return latest
