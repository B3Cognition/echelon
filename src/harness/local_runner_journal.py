"""Crash-safe, host-local state for explicit Echelon local verification."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Mapping

from harness.durable_json import DurableJsonError, write_json_atomic


_ENVIRONMENT_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_PRESERVED_HOST_ENVIRONMENT = ("PATH", "LANG", "LC_ALL", "TERM")
_TERMINAL_STATUSES = frozenset({"passed", "failed", "cleaned", "host_preflight_failed"})


class LocalRunJournalError(RuntimeError):
    """Raised when locally persisted runner state is malformed or unsafe."""


class LocalRunRecoveryRequired(LocalRunJournalError):
    """Raised before a new run could overlap a previous local run."""


class LocalRunSideEffectError(LocalRunJournalError):
    """Raised when a run changes either protected user checkout."""


class WorkspaceLocalRunLocked(LocalRunJournalError):
    """Raised when an active local verifier owns the workspace lock."""


@dataclass(frozen=True)
class ResourceJournalEntry:
    engine: str
    resource_kind: str
    resource_id: str
    labels: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class LocalRunJournal:
    local_run_id: str
    status: str
    target_git_baseline: str
    workspace_git_baseline: str
    resources: tuple[ResourceJournalEntry, ...] = ()
    completed_actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class HostExecutionEnvironment:
    values: Mapping[str, str]


class WorkspaceLocalRunLock:
    """An OS-held lock that naturally releases when its process exits."""

    def __init__(self, workspace_root: Path, *, blocking: bool = True) -> None:
        self._workspace_root = Path(workspace_root)
        self._blocking = blocking
        self._fd: int | None = None

    def __enter__(self) -> "WorkspaceLocalRunLock":
        root = _regular_directory(self._workspace_root, "workspace root")
        runs = root / "runs"
        if runs.is_symlink():
            raise LocalRunJournalError("workspace runs directory is symlinked")
        runs.mkdir(parents=True, exist_ok=True)
        if not runs.is_dir():
            raise LocalRunJournalError("workspace runs directory is unavailable")
        path = runs / ".local-run.lock"
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags, 0o600)
            operation = fcntl.LOCK_EX | (0 if self._blocking else fcntl.LOCK_NB)
            fcntl.flock(fd, operation)
        except BlockingIOError as exc:
            try:
                os.close(fd)
            except (UnboundLocalError, OSError):
                pass
            raise WorkspaceLocalRunLocked(
                "another local verification currently owns this workspace"
            ) from exc
        except OSError as exc:
            try:
                os.close(fd)
            except (UnboundLocalError, OSError):
                pass
            raise LocalRunJournalError("could not acquire workspace local-run lock") from exc
        self._fd = fd
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None


def acquire_workspace_local_run_lock(
    workspace_root: Path, *, blocking: bool = True
) -> WorkspaceLocalRunLock:
    return WorkspaceLocalRunLock(workspace_root, blocking=blocking)


def journal_path(local_run_root: Path) -> Path:
    return Path(local_run_root) / "journal.json"


def write_local_run_journal(local_run_root: Path, journal: LocalRunJournal) -> Path:
    root = _regular_directory(local_run_root, "local-run root")
    path = journal_path(root)
    payload = {
        "schema_version": 1,
        "local_run_id": journal.local_run_id,
        "status": journal.status,
        "target_git_baseline": journal.target_git_baseline,
        "workspace_git_baseline": journal.workspace_git_baseline,
        "resources": [asdict(item) for item in journal.resources],
        "completed_actions": list(journal.completed_actions),
    }
    try:
        write_json_atomic(path, payload, trusted_root=root)
    except DurableJsonError as exc:
        raise LocalRunJournalError("could not write local-run journal") from exc
    return path


def load_local_run_journal(
    path: Path,
    trusted_local_run_root: Path,
) -> LocalRunJournal:
    root = _regular_directory(trusted_local_run_root, "trusted local-run root")
    requested = Path(path)
    try:
        resolved = requested.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise LocalRunJournalError("local-run journal escapes its trusted root") from exc
    if resolved.is_symlink() or not resolved.is_file() or resolved.name != "journal.json":
        raise LocalRunJournalError("local-run journal is unsafe")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalRunJournalError("local-run journal is unreadable") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise LocalRunJournalError("local-run journal is malformed")
    return _journal_from_mapping(payload)


def assert_no_recovery_journal(local_runs_root: Path) -> None:
    root = _regular_directory(local_runs_root, "local-runs root")
    paths = [journal_path(root)] + sorted(root.glob("*/journal.json"))
    for path in paths:
        if not path.exists() or path.is_symlink():
            continue
        journal = load_local_run_journal(path, root)
        if _requires_cleanup(journal):
            raise LocalRunRecoveryRequired(
                f"local verification recovery is required for {path.name}"
            )


def build_host_execution_environment(
    run_root: Path,
    bindings: Mapping[str, str],
    *,
    parent_environment: Mapping[str, str] | None = None,
) -> HostExecutionEnvironment:
    """Build the exact scrubbed environment used for host-local commands."""
    root = _regular_directory(run_root, "local run root")
    parent = parent_environment if parent_environment is not None else os.environ
    values = {
        name: str(parent[name])
        for name in _PRESERVED_HOST_ENVIRONMENT
        if isinstance(parent.get(name), str) and str(parent[name])
    }
    values.setdefault("PATH", "/usr/bin:/bin")
    directories = {
        "HOME": root / "home",
        "XDG_CONFIG_HOME": root / "xdg" / "config",
        "XDG_CACHE_HOME": root / "xdg" / "cache",
        "XDG_DATA_HOME": root / "xdg" / "data",
        "TMPDIR": root / "tmp",
        "PNPM_HOME": root / "pnpm",
        "npm_config_cache": root / "npm-cache",
        "PLAYWRIGHT_BROWSERS_PATH": root / "playwright-browsers",
    }
    for value in directories.values():
        value.mkdir(parents=True, exist_ok=True)
    values.update({name: str(path) for name, path in directories.items()})
    git_config = root / "gitconfig"
    if git_config.is_symlink():
        raise LocalRunJournalError("local Git config path is symlinked")
    git_config.touch(exist_ok=True)
    values["GIT_CONFIG_NOSYSTEM"] = "1"
    values["GIT_CONFIG_GLOBAL"] = str(git_config)
    for name, value in bindings.items():
        if not _ENVIRONMENT_NAME.fullmatch(str(name)) or not isinstance(value, str):
            raise LocalRunJournalError("local stack environment binding is invalid")
        values[str(name)] = value
    return HostExecutionEnvironment(values=values)


def git_porcelain_baseline(path: Path) -> str:
    root = _regular_directory(path, "Git baseline path")
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotePath=false", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise LocalRunJournalError("could not inspect Git baseline") from exc
    if result.returncode != 0:
        raise LocalRunJournalError("could not inspect Git baseline")
    return result.stdout


def assert_git_baseline_unchanged(
    path: Path,
    baseline: str,
    observed: str | None = None,
) -> None:
    current = git_porcelain_baseline(path) if observed is None else observed
    if current != baseline:
        raise LocalRunSideEffectError(
            "local verification changed a protected checkout; inspect its journal before cleanup"
        )


def _regular_directory(path: Path, label: str) -> Path:
    raw = Path(path).expanduser()
    if raw.is_symlink():
        raise LocalRunJournalError(f"{label} is symlinked")
    raw.mkdir(parents=True, exist_ok=True)
    try:
        resolved = raw.resolve(strict=True)
    except OSError as exc:
        raise LocalRunJournalError(f"{label} is unavailable") from exc
    if not resolved.is_dir():
        raise LocalRunJournalError(f"{label} is unavailable")
    return resolved


def _journal_from_mapping(payload: Mapping[str, object]) -> LocalRunJournal:
    local_run_id = payload.get("local_run_id")
    status = payload.get("status")
    target_baseline = payload.get("target_git_baseline")
    workspace_baseline = payload.get("workspace_git_baseline")
    actions = payload.get("completed_actions")
    resources = payload.get("resources")
    if not all(isinstance(item, str) for item in (local_run_id, status, target_baseline, workspace_baseline)):
        raise LocalRunJournalError("local-run journal is malformed")
    if not isinstance(actions, list) or not all(isinstance(item, str) for item in actions):
        raise LocalRunJournalError("local-run journal is malformed")
    if not isinstance(resources, list):
        raise LocalRunJournalError("local-run journal is malformed")
    parsed_resources: list[ResourceJournalEntry] = []
    for item in resources:
        if not isinstance(item, dict):
            raise LocalRunJournalError("local-run journal is malformed")
        labels = item.get("labels", [])
        if not isinstance(labels, list):
            raise LocalRunJournalError("local-run journal is malformed")
        parsed_labels: list[tuple[str, str]] = []
        for label in labels:
            if not isinstance(label, (list, tuple)) or len(label) != 2:
                raise LocalRunJournalError("local-run journal is malformed")
            key, value = label
            if not isinstance(key, str) or not isinstance(value, str):
                raise LocalRunJournalError("local-run journal is malformed")
            parsed_labels.append((key, value))
        fields = (item.get("engine"), item.get("resource_kind"), item.get("resource_id"))
        if not all(isinstance(value, str) and value for value in fields):
            raise LocalRunJournalError("local-run journal is malformed")
        parsed_resources.append(
            ResourceJournalEntry(
                engine=str(item["engine"]),
                resource_kind=str(item["resource_kind"]),
                resource_id=str(item["resource_id"]),
                labels=tuple(parsed_labels),
            )
        )
    return LocalRunJournal(
        local_run_id=local_run_id,
        status=status,
        target_git_baseline=target_baseline,
        workspace_git_baseline=workspace_baseline,
        resources=tuple(parsed_resources),
        completed_actions=tuple(actions),
    )


def _requires_cleanup(journal: LocalRunJournal) -> bool:
    return journal.status not in _TERMINAL_STATUSES or (
        bool(journal.resources) and "cleanup" not in journal.completed_actions
    )
