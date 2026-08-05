"""Deterministic active-spec lifecycle state and transaction primitives."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import socket
import tempfile
from typing import Any

from harness.controller_lock_order import controller_lock_order


class SpecLifecycleError(RuntimeError):
    """Base error for deterministic spec lifecycle operations."""


class SpecRunNotFound(SpecLifecycleError):
    """Raised when no switchable run matches an identity."""


class SpecRunAmbiguous(SpecLifecycleError):
    """Raised when an identity matches more than one switchable run."""

    def __init__(self, identity: str, matches: tuple["SpecRun", ...]) -> None:
        self.identity = identity
        self.matches = matches
        names = ", ".join(run.run_dir_name for run in matches)
        super().__init__(f"spec run identity {identity!r} is ambiguous: {names}")


class SpecLifecycleLocked(SpecLifecycleError):
    """Raised when another live lifecycle operation owns the workspace lock."""

    def __init__(self, operation_id: str) -> None:
        self.operation_id = operation_id
        super().__init__(f"spec lifecycle lock is owned by {operation_id}")


class SpecLifecycleRecoveryRequired(SpecLifecycleError):
    """Raised when lifecycle runtime state cannot be recovered automatically."""


@dataclass(frozen=True)
class SpecRun:
    """Validated identity and artifact paths for one switchable Phase A run."""

    run_dir: Path
    run_dir_name: str
    run_id: str
    spec_id: str
    feature_branch: str
    spec_dir: Path
    published_spec_dir: Path | None


@dataclass(frozen=True)
class SpecSwitchIntent:
    """Durable journal for one active-run pointer transition."""

    operation_id: str
    source_run: str
    target_run: str
    source_branch: str
    target_branch: str
    stage: str
    created_at: str


@dataclass(frozen=True)
class SpecSwitchRecovery:
    """Result of reconciling an interrupted switch intent."""

    action: str
    source: SpecRun
    target: SpecRun


_SAFE_OPERATION_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_SAFE_SPEC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _runtime_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".echelon" / "runtime"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}-",
        suffix=".tmp",
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f"{path.name}-",
        suffix=".tmp",
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecLifecycleRecoveryRequired(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SpecLifecycleRecoveryRequired(f"{label} must be a JSON object: {path}")
    return payload


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass
class SpecLifecycleLock:
    """Atomic single-writer lock for active-spec lifecycle mutations."""

    path: Path
    operation_id: str
    _controller_guard: Any | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    @classmethod
    def _acquire_path(
        cls,
        lock_path: Path,
        operation_id: str,
        *,
        owner_label: str,
        controller_rank: str | None = None,
    ) -> "SpecLifecycleLock":
        guard = (
            controller_lock_order(
                controller_rank,
                str(lock_path.resolve()),
            )
            if controller_rank is not None
            else None
        )
        if guard is not None:
            guard.__enter__()
        try:
            acquired = cls._acquire_path_unordered(
                lock_path,
                operation_id,
                owner_label=owner_label,
            )
        except BaseException as error:
            if guard is not None:
                guard.__exit__(
                    type(error),
                    error,
                    error.__traceback__,
                )
            raise
        acquired._controller_guard = guard
        return acquired

    @classmethod
    def _acquire_path_unordered(
        cls,
        lock_path: Path,
        operation_id: str,
        *,
        owner_label: str,
    ) -> "SpecLifecycleLock":
        if not _SAFE_OPERATION_ID.fullmatch(operation_id):
            raise ValueError(f"unsafe lifecycle operation ID: {operation_id!r}")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                lock_path.mkdir()
                break
            except FileExistsError as exc:
                owner = _read_json_object(lock_path / "owner.json", label=owner_label)
                owner_id = str(owner.get("operation_id") or "")
                pid = owner.get("pid")
                hostname = owner.get("hostname")
                if not _SAFE_OPERATION_ID.fullmatch(owner_id):
                    raise SpecLifecycleRecoveryRequired(
                        f"{owner_label} operation ID is malformed: {owner_id!r}"
                    ) from exc
                if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
                    raise SpecLifecycleRecoveryRequired(
                        f"{owner_label} PID is malformed"
                    ) from exc
                if hostname != socket.gethostname():
                    raise SpecLifecycleRecoveryRequired(
                        f"cannot prove remote {owner_label} {owner_id!r} is stale"
                    ) from exc
                if _pid_alive(pid):
                    raise SpecLifecycleLocked(owner_id) from exc
                shutil.rmtree(lock_path)

        metadata = {
            "operation_id": operation_id,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "acquired_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            _write_json_atomic(lock_path / "owner.json", metadata)
        except Exception:
            shutil.rmtree(lock_path, ignore_errors=True)
            raise
        return cls(path=lock_path, operation_id=operation_id)

    @classmethod
    def acquire(cls, project_root: Path, operation_id: str) -> "SpecLifecycleLock":
        return cls._acquire_path(
            _runtime_dir(project_root) / "spec-lifecycle.lock",
            operation_id,
            owner_label="lifecycle lock owner",
        )

    def release(self) -> None:
        try:
            if not self.path.exists():
                return
            owner = _read_json_object(
                self.path / "owner.json",
                label="lifecycle lock owner",
            )
            owner_id = str(owner.get("operation_id") or "")
            if owner_id != self.operation_id:
                raise SpecLifecycleLocked(owner_id or "unknown")
            shutil.rmtree(self.path)
        finally:
            guard = self._controller_guard
            self._controller_guard = None
            if guard is not None:
                guard.__exit__(None, None, None)

    def __enter__(self) -> "SpecLifecycleLock":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


class SpecMutationLock(SpecLifecycleLock):
    """Outer serialization lease for one spec's lifecycle mutations."""

    @classmethod
    def acquire(
        cls,
        project_root: Path,
        spec_id: str,
        operation_id: str,
    ) -> "SpecMutationLock":
        if not _SAFE_SPEC_ID.fullmatch(spec_id):
            raise ValueError(f"unsafe spec identity: {spec_id!r}")
        return cls._acquire_path(
            _runtime_dir(project_root) / "spec-mutations" / f"{spec_id}.lock",
            operation_id,
            owner_label=f"spec mutation lock owner for {spec_id}",
        )


class SpecRunExecutionLock(SpecLifecycleLock):
    """Atomic single-writer lease for one Phase A squad run."""

    @classmethod
    def acquire(cls, run_dir: Path, operation_id: str) -> "SpecRunExecutionLock":
        return cls._acquire_path(
            Path(run_dir).resolve() / ".echelon" / "runtime" / "execution.lock",
            operation_id,
            owner_label="run execution lock owner",
            controller_rank="spec_run",
        )


class PhaseAExecutionLock(SpecLifecycleLock):
    """Atomic lease preventing a live controller from losing its checkout."""

    @classmethod
    def acquire(cls, project_root: Path, operation_id: str) -> "PhaseAExecutionLock":
        return cls._acquire_path(
            _runtime_dir(project_root) / "phase-a-execution.lock",
            operation_id,
            owner_label="Phase A execution lock owner",
            controller_rank="phase_a",
        )


def _project_path(project_root: Path, value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise SpecLifecycleError(f"lifecycle path escapes project root: {value!r}") from exc
    return resolved


def _read_spec_run(project_root: Path, run_dir: Path) -> SpecRun | None:
    state_path = run_dir / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict):
        return None

    values = {
        key: str(state.get(key) or "").strip()
        for key in ("run_id", "spec_id", "feature_branch", "spec_dir")
    }
    if not all(values.values()):
        return None
    try:
        spec_dir = _project_path(project_root, values["spec_dir"])
        published_ref = str(state.get("published_spec_dir") or "").strip()
        published_spec_dir = (
            _project_path(project_root, published_ref) if published_ref else None
        )
    except SpecLifecycleError:
        return None

    resolved_run_dir = run_dir.resolve()
    return SpecRun(
        run_dir=resolved_run_dir,
        run_dir_name=run_dir.name,
        run_id=values["run_id"],
        spec_id=values["spec_id"],
        feature_branch=values["feature_branch"],
        spec_dir=spec_dir,
        published_spec_dir=published_spec_dir,
    )


def discover_spec_runs(project_root: Path) -> tuple[SpecRun, ...]:
    """Return validated spec runs without timestamp or mtime inference."""

    root = Path(project_root).resolve()
    discovered: list[SpecRun] = []
    seen: set[Path] = set()
    for base_name in ("runs", "squad"):
        base = root / base_name
        if not base.is_dir():
            continue
        for candidate in base.iterdir():
            if not candidate.is_dir() or candidate.name.startswith("."):
                continue
            resolved = candidate.resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            if resolved in seen:
                continue
            run = _read_spec_run(root, candidate)
            if run is None:
                continue
            seen.add(resolved)
            discovered.append(run)
    return tuple(sorted(discovered, key=lambda run: (run.run_dir_name, str(run.run_dir))))


def _one_match(identity: str, matches: list[SpecRun]) -> SpecRun | None:
    ordered = tuple(sorted(matches, key=lambda run: (run.run_dir_name, str(run.run_dir))))
    if len(ordered) > 1:
        raise SpecRunAmbiguous(identity, ordered)
    return ordered[0] if ordered else None


def resolve_spec_run(project_root: Path, identity: str) -> SpecRun:
    """Resolve one spec run using deterministic identity priority."""

    name = identity.strip()
    if not name:
        raise SpecRunNotFound("spec run identity is empty")
    runs = discover_spec_runs(project_root)
    tiers = (
        [run for run in runs if run.run_dir_name == name],
        [run for run in runs if run.run_id == name],
        [run for run in runs if run.spec_id == name or run.feature_branch == name],
    )
    for matches in tiers:
        if resolved := _one_match(name, matches):
            return resolved

    if name.isdigit():
        prefix = re.compile(rf"^{re.escape(name)}(?:-|$)")
        matches = [
            run
            for run in runs
            if prefix.match(run.spec_id) or prefix.match(Path(run.feature_branch).name)
        ]
        if resolved := _one_match(name, matches):
            return resolved
    raise SpecRunNotFound(f"no switchable spec run matches {name!r}")


def resolve_active_spec_run(project_root: Path) -> SpecRun:
    """Resolve the exact run-directory name stored in ``runs/.current``."""

    root = Path(project_root).resolve()
    pointer = root / "runs" / ".current"
    try:
        name = pointer.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SpecRunNotFound(f"active spec pointer is missing: {pointer}") from exc
    if not name:
        raise SpecRunNotFound(f"active spec pointer is blank: {pointer}")
    matches = [run for run in discover_spec_runs(root) if run.run_dir_name == name]
    resolved = _one_match(name, matches)
    if resolved is None:
        raise SpecRunNotFound(
            f"active spec pointer {name!r} does not name a switchable run directory"
        )
    return resolved


def _resolve_run_dir_name(project_root: Path, run_dir_name: str) -> SpecRun:
    matches = [
        run for run in discover_spec_runs(project_root) if run.run_dir_name == run_dir_name
    ]
    resolved = _one_match(run_dir_name, matches)
    if resolved is None:
        raise SpecRunNotFound(
            f"switch intent run directory is unavailable: {run_dir_name!r}"
        )
    return resolved


def _active_pointer_name(project_root: Path) -> str:
    pointer = Path(project_root).resolve() / "runs" / ".current"
    try:
        name = pointer.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SpecLifecycleRecoveryRequired(
            f"cannot read active spec pointer {pointer}: {exc}"
        ) from exc
    if not name:
        raise SpecLifecycleRecoveryRequired(f"active spec pointer is blank: {pointer}")
    return name


def _intent_path(project_root: Path) -> Path:
    return _runtime_dir(project_root) / "spec-switch-intent.json"


def load_spec_switch_intent(project_root: Path) -> SpecSwitchIntent | None:
    """Load and strictly validate the durable switch intent, when present."""

    path = _intent_path(project_root)
    if not path.exists():
        return None
    payload = _read_json_object(path, label="switch intent")
    required = (
        "operation_id",
        "source_run",
        "target_run",
        "source_branch",
        "target_branch",
        "stage",
        "created_at",
    )
    values: dict[str, str] = {}
    for key in required:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise SpecLifecycleRecoveryRequired(
                f"switch intent field {key!r} must be a non-empty string"
            )
        values[key] = value.strip()
    if not _SAFE_OPERATION_ID.fullmatch(values["operation_id"]):
        raise SpecLifecycleRecoveryRequired("switch intent operation ID is malformed")
    if values["stage"] not in {"prepared", "checked_out"}:
        raise SpecLifecycleRecoveryRequired(
            f"switch intent stage is invalid: {values['stage']!r}"
        )
    return SpecSwitchIntent(**values)


def _write_switch_intent(project_root: Path, intent: SpecSwitchIntent) -> None:
    _write_json_atomic(_intent_path(project_root), asdict(intent))


def _clear_switch_intent(project_root: Path, operation_id: str) -> None:
    intent = load_spec_switch_intent(project_root)
    if intent is None:
        return
    if intent.operation_id != operation_id:
        raise SpecLifecycleRecoveryRequired(
            f"switch intent is owned by {intent.operation_id!r}, not {operation_id!r}"
        )
    _intent_path(project_root).unlink()


def _replace_active_run_pointer(project_root: Path, target: SpecRun) -> None:
    canonical = _resolve_run_dir_name(project_root, target.run_dir_name)
    if canonical.run_dir != target.run_dir:
        raise SpecLifecycleRecoveryRequired(
            f"target run changed during switch: {target.run_dir_name!r}"
        )
    pointer = Path(project_root).resolve() / "runs" / ".current"
    _write_text_atomic(pointer, f"{target.run_dir_name}\n")


def activate_initial_spec_run(
    project_root: Path,
    target: SpecRun,
    *,
    observed_branch: str,
) -> SpecRun:
    """Select the first discoverable run after its target branch is checked out."""

    root = Path(project_root).resolve()
    pointer = root / "runs" / ".current"
    if pointer.exists():
        raise SpecLifecycleError(
            "cannot activate an initial spec run while runs/.current already exists"
        )
    canonical = _resolve_run_dir_name(root, target.run_dir_name)
    if observed_branch != canonical.feature_branch:
        raise SpecLifecycleError(
            f"observed branch {observed_branch!r} does not match target branch "
            f"{canonical.feature_branch!r}"
        )
    _replace_active_run_pointer(root, canonical)
    return canonical


def begin_spec_switch(
    project_root: Path,
    source: SpecRun,
    target: SpecRun,
    *,
    observed_branch: str,
    operation_id: str,
) -> SpecSwitchIntent:
    """Persist a prepared intent after validating active pointer and branch."""

    if not _SAFE_OPERATION_ID.fullmatch(operation_id):
        raise ValueError(f"unsafe lifecycle operation ID: {operation_id!r}")
    if load_spec_switch_intent(project_root) is not None:
        raise SpecLifecycleRecoveryRequired("a spec switch intent already exists")
    canonical_source = _resolve_run_dir_name(project_root, source.run_dir_name)
    canonical_target = _resolve_run_dir_name(project_root, target.run_dir_name)
    active = resolve_active_spec_run(project_root)
    if active.run_dir != canonical_source.run_dir:
        raise SpecLifecycleError(
            f"active pointer names {active.run_dir_name!r}, not source {source.run_dir_name!r}"
        )
    if observed_branch != canonical_source.feature_branch:
        raise SpecLifecycleError(
            f"observed branch {observed_branch!r} does not match source branch "
            f"{canonical_source.feature_branch!r}"
        )
    intent = SpecSwitchIntent(
        operation_id=operation_id,
        source_run=canonical_source.run_dir_name,
        target_run=canonical_target.run_dir_name,
        source_branch=canonical_source.feature_branch,
        target_branch=canonical_target.feature_branch,
        stage="prepared",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    _write_switch_intent(project_root, intent)
    return intent


def mark_spec_switch_checked_out(
    project_root: Path,
    operation_id: str,
    *,
    observed_branch: str,
) -> SpecSwitchIntent:
    """Record that Git checkout reached the intent's target branch."""

    intent = load_spec_switch_intent(project_root)
    if intent is None:
        raise SpecLifecycleRecoveryRequired("no switch intent exists")
    if intent.operation_id != operation_id:
        raise SpecLifecycleRecoveryRequired(
            f"switch intent is owned by {intent.operation_id!r}, not {operation_id!r}"
        )
    if observed_branch != intent.target_branch:
        raise SpecLifecycleError(
            f"observed branch {observed_branch!r} does not match target branch "
            f"{intent.target_branch!r}"
        )
    checked_out = replace(intent, stage="checked_out")
    _write_switch_intent(project_root, checked_out)
    return checked_out


def commit_spec_switch_pointer(
    project_root: Path,
    operation_id: str,
    *,
    observed_branch: str,
) -> SpecRun:
    """Atomically select the checked-out target and clear its matching intent."""

    intent = load_spec_switch_intent(project_root)
    if intent is None:
        raise SpecLifecycleRecoveryRequired("no switch intent exists")
    if intent.operation_id != operation_id:
        raise SpecLifecycleRecoveryRequired(
            f"switch intent is owned by {intent.operation_id!r}, not {operation_id!r}"
        )
    if intent.stage != "checked_out":
        raise SpecLifecycleRecoveryRequired("switch intent has not recorded target checkout")
    if observed_branch != intent.target_branch:
        raise SpecLifecycleError(
            f"observed branch {observed_branch!r} does not match target branch "
            f"{intent.target_branch!r}"
        )
    pointer_name = _active_pointer_name(project_root)
    if pointer_name not in {intent.source_run, intent.target_run}:
        raise SpecLifecycleRecoveryRequired(
            f"active pointer {pointer_name!r} is inconsistent with switch intent"
        )
    target = _resolve_run_dir_name(project_root, intent.target_run)
    if pointer_name == intent.source_run:
        _replace_active_run_pointer(project_root, target)
    _clear_switch_intent(project_root, operation_id)
    return target


def activate_same_branch_spec_run(
    project_root: Path,
    source: SpecRun,
    target: SpecRun,
    *,
    observed_branch: str,
    operation_id: str,
) -> SpecRun:
    """Journal and complete an idempotent pointer-only same-branch switch."""

    canonical_source = _resolve_run_dir_name(project_root, source.run_dir_name)
    canonical_target = _resolve_run_dir_name(project_root, target.run_dir_name)
    if (
        canonical_source.run_dir == canonical_target.run_dir
        or canonical_source.feature_branch != canonical_target.feature_branch
        or observed_branch != canonical_source.feature_branch
    ):
        raise SpecLifecycleError("same-branch spec switch identity drifted")
    active = resolve_active_spec_run(project_root)
    intent = load_spec_switch_intent(project_root)
    if intent is None and active.run_dir == canonical_target.run_dir:
        return canonical_target
    if intent is None:
        if active.run_dir != canonical_source.run_dir:
            raise SpecLifecycleError("same-branch spec switch source is not active")
        intent = begin_spec_switch(
            project_root,
            canonical_source,
            canonical_target,
            observed_branch=observed_branch,
            operation_id=operation_id,
        )
    elif (
        intent.operation_id != operation_id
        or intent.source_run != canonical_source.run_dir_name
        or intent.target_run != canonical_target.run_dir_name
        or intent.source_branch != observed_branch
        or intent.target_branch != observed_branch
        or active.run_dir not in {canonical_source.run_dir, canonical_target.run_dir}
    ):
        raise SpecLifecycleRecoveryRequired("same-branch spec switch intent drifted")
    if intent.stage == "prepared":
        intent = mark_spec_switch_checked_out(
            project_root,
            operation_id,
            observed_branch=observed_branch,
        )
    if intent.stage != "checked_out":
        raise SpecLifecycleRecoveryRequired("same-branch spec switch stage drifted")
    return commit_spec_switch_pointer(
        project_root,
        operation_id,
        observed_branch=observed_branch,
    )


def recover_spec_switch(
    project_root: Path,
    *,
    observed_branch: str,
) -> SpecSwitchRecovery:
    """Reconcile one interrupted switch from its pointer and observed branch."""

    intent = load_spec_switch_intent(project_root)
    if intent is None:
        raise SpecLifecycleRecoveryRequired("no switch intent exists to recover")
    source = _resolve_run_dir_name(project_root, intent.source_run)
    target = _resolve_run_dir_name(project_root, intent.target_run)
    pointer_name = _active_pointer_name(project_root)

    if (
        intent.stage == "prepared"
        and pointer_name == intent.source_run
        and observed_branch == intent.source_branch
    ):
        _clear_switch_intent(project_root, intent.operation_id)
        return SpecSwitchRecovery("aborted_before_checkout", source, target)
    if pointer_name == intent.source_run and observed_branch == intent.target_branch:
        _replace_active_run_pointer(project_root, target)
        _clear_switch_intent(project_root, intent.operation_id)
        return SpecSwitchRecovery("completed_after_checkout", source, target)
    if (
        intent.stage == "checked_out"
        and pointer_name == intent.target_run
        and observed_branch == intent.target_branch
    ):
        _clear_switch_intent(project_root, intent.operation_id)
        return SpecSwitchRecovery("cleared_completed_intent", source, target)
    raise SpecLifecycleRecoveryRequired(
        "switch intent, active pointer, and observed branch are inconsistent"
    )
