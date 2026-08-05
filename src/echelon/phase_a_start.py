"""Transactional Echelon-owned bootstrap for a fresh Phase A spec."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from typing import Mapping
from uuid import uuid4

from echelon import atomic_install, durable_tree
from echelon.git_helpers import GitHelperError, current_branch, run_git
from echelon.product_inputs import (
    ProductInputError,
    clone_product_input_contract,
    project_cloned_product_input_contract,
    validate_immutable_product_input_package,
    validate_product_input_contract_pointers,
)
from echelon.phase_a_git import (
    PhaseAGitError,
    PhaseASpecBootstrap,
    create_phase_a_spec_branch_ref,
    plan_phase_a_spec,
)
from echelon.spec_lifecycle import (
    PhaseAExecutionLock,
    SpecLifecycleError,
    SpecLifecycleLock,
    SpecRun,
    SpecSwitchIntent,
    activate_initial_spec_run,
    begin_spec_switch,
    commit_spec_switch_pointer,
    load_spec_switch_intent,
    mark_spec_switch_checked_out,
    recover_spec_switch,
    resolve_active_spec_run,
    resolve_spec_run,
)
from echelon.spec_switch import (
    DirtySpecWorktreeError,
    SpecSwitchError,
    ValidatedSpecCheckpoint,
    discard_spec_worktree,
    spec_worktree_paths,
    stash_spec_worktree,
    validate_spec_checkpoint,
)
from echelon.speckit_git import SpecKitGitOwnershipError, require_speckit_git_disabled
from echelon.strict_json import loads_strict_json
from echelon.target_normalization import normalize_target_set
from harness.published_re_context import explicit_re_sources


class PhaseAStartError(RuntimeError):
    """Raised when a fresh spec cannot be activated safely."""


@dataclass(frozen=True)
class PhaseAStartOutcome:
    run_dir: Path
    bootstrap: PhaseASpecBootstrap
    source: SpecRun | None = None
    source_checkpoint: ValidatedSpecCheckpoint | None = None
    stash_commit: str = ""


@dataclass(frozen=True)
class RetargetPhaseAStartOutcome:
    """Prepared replacement run selected on the baseline feature branch."""

    run_dir: Path
    run: SpecRun
    baseline: SpecRun


_SAFE_REPLACEMENT_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SAFE_OPERATION_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_CANONICAL_SPEC_ID = re.compile(
    r"^(?P<number>\d{3,})-(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)$"
)
_RETARGET_STAGING_MARKER = ".echelon-retarget-bootstrap.json"
_RETARGET_OWNER_KEYS = frozenset(
    {"operation_id", "source_run", "target_run", "spec_id"}
)
_RETARGET_RESERVATION_KEYS = frozenset(
    {"schema_version", "owner", "staging_name"}
)
_RETARGET_MARKER_KEYS = frozenset({"schema_version", "owner"})
_RETARGET_STAGING_NAME = re.compile(r"^\.retarget-run-[0-9a-f]{32}$")
_RETARGET_CONTRACT_KEYS = frozenset(
    {
        "operation_id",
        "revision_id",
        "status",
        "baseline_run_id",
        "replacement_run_id",
        "old_targets",
        "replacement_targets",
        "artifact_invalidation",
        "checkpoint_id",
        "checkpoint_commit",
        "failure_code",
    }
)
_MAX_RETARGET_ID_LENGTH = 256
_MAX_RETARGET_TARGET_LENGTH = 1024
_MAX_RETARGET_TARGETS = 128
_CANONICAL_OWNED_DIRECTORY_MODE = 0o755


def _load_state(run_dir: Path) -> dict[str, object]:
    state_path = Path(run_dir) / "state.json"
    if state_path.is_symlink() or not state_path.is_file():
        raise PhaseAStartError(f"baseline state is not a regular file: {state_path}")
    try:
        payload = loads_strict_json(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PhaseAStartError(f"cannot read baseline state {state_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PhaseAStartError(f"baseline state must be a JSON object: {state_path}")
    return payload


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}-",
        suffix=".tmp",
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        _sync_parent_directory(path.parent)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _sync_parent_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_retarget_prepared_state(
    run_dir: Path,
    prepared_state: Mapping[str, object],
) -> None:
    spec_id = str(prepared_state["spec_id"])
    run_spec_dir = run_dir / "specs" / spec_id
    run_spec_dir.mkdir(parents=True)
    (run_dir / "specs").chmod(_CANONICAL_OWNED_DIRECTORY_MODE)
    run_spec_dir.chmod(_CANONICAL_OWNED_DIRECTORY_MODE)
    (run_dir / "staging").mkdir()
    (run_dir / "staging").chmod(_CANONICAL_OWNED_DIRECTORY_MODE)
    _write_json_atomic(run_dir / "state.json", prepared_state)


def _require_bounded_identity(value: object, *, field: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > _MAX_RETARGET_ID_LENGTH
        or _SAFE_OPERATION_ID.fullmatch(value) is None
    ):
        raise PhaseAStartError(f"retarget contract has invalid {field}")
    return value


def _json_values_exact(actual: object, expected: object) -> bool:
    """Compare decoded JSON without Python's cross-type scalar equality."""

    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        actual_dict = actual
        expected_dict = expected
        assert isinstance(actual_dict, dict) and isinstance(expected_dict, dict)
        return (
            set(actual_dict) == set(expected_dict)
            and all(
                _json_values_exact(actual_dict[key], expected_dict[key])
                for key in expected_dict
            )
        )
    if type(expected) is list:
        actual_list = actual
        expected_list = expected
        assert isinstance(actual_list, list) and isinstance(expected_list, list)
        return len(actual_list) == len(expected_list) and all(
            _json_values_exact(actual_item, expected_item)
            for actual_item, expected_item in zip(actual_list, expected_list)
        )
    return actual == expected


def _require_canonical_targets(value: object, *, field: str) -> tuple[str, ...]:
    if (
        type(value) is not list
        or not value
        or len(value) > _MAX_RETARGET_TARGETS
        or any(
            type(target) is not str
            or not target
            or len(target) > _MAX_RETARGET_TARGET_LENGTH
            for target in value
        )
    ):
        raise PhaseAStartError(f"retarget contract has invalid {field}")
    normalized = normalize_target_set(value)
    if tuple(value) != normalized:
        raise PhaseAStartError(f"retarget contract has noncanonical {field}")
    return normalized


def _validate_retarget_contract(
    retarget_state: Mapping[str, object],
    *,
    baseline: SpecRun,
    baseline_state: Mapping[str, object],
    replacement_run_id: str,
    replacement_targets: tuple[str, ...],
    checkpoint_commit: str,
) -> dict[str, object]:
    if type(retarget_state) is not dict or set(retarget_state) != _RETARGET_CONTRACT_KEYS:
        raise PhaseAStartError("retarget contract has invalid keys")
    operation_id = _require_bounded_identity(
        retarget_state["operation_id"], field="operation_id"
    )
    _require_bounded_identity(retarget_state["revision_id"], field="revision_id")
    _require_bounded_identity(retarget_state["checkpoint_id"], field="checkpoint_id")
    if retarget_state["status"] != "checkpointed":
        raise PhaseAStartError("retarget contract has invalid status")
    if retarget_state["failure_code"] is not None:
        raise PhaseAStartError("retarget contract has invalid failure_code")
    if retarget_state["baseline_run_id"] != baseline.run_id:
        raise PhaseAStartError("retarget contract has mismatched baseline_run_id")
    if retarget_state["replacement_run_id"] != replacement_run_id:
        raise PhaseAStartError("retarget contract has mismatched replacement_run_id")
    raw_old_targets = baseline_state.get("implementation_targets")
    old_targets = _require_canonical_targets(raw_old_targets, field="baseline old_targets")
    if _require_canonical_targets(
        retarget_state["old_targets"], field="old_targets"
    ) != old_targets:
        raise PhaseAStartError("retarget contract has mismatched old_targets")
    if _require_canonical_targets(
        retarget_state["replacement_targets"], field="replacement_targets"
    ) != replacement_targets:
        raise PhaseAStartError("retarget contract has mismatched replacement_targets")
    raw_invalidation = retarget_state["artifact_invalidation"]
    if (
        type(raw_invalidation) is not list
        or not raw_invalidation
        or len(raw_invalidation) > 512
    ):
        raise PhaseAStartError("retarget contract has invalid artifact_invalidation")
    invalidation: list[str] = []
    for value in raw_invalidation:
        candidate = Path(value) if type(value) is str else Path("/")
        if (
            type(value) is not str
            or not value
            or candidate.is_absolute()
            or len(candidate.parts) != 1
            or candidate.as_posix() != value
            or value in {".", "..", ".echelon", "retarget-history.json"}
        ):
            raise PhaseAStartError(
                "retarget contract has invalid artifact_invalidation"
            )
        invalidation.append(value)
    if invalidation != sorted(set(invalidation)):
        raise PhaseAStartError("retarget contract has invalid artifact_invalidation")
    if retarget_state["checkpoint_commit"] != checkpoint_commit:
        raise PhaseAStartError("retarget contract has mismatched checkpoint_commit")
    if old_targets == replacement_targets:
        raise PhaseAStartError("retarget contract replacement targets are unchanged")
    checked = dict(retarget_state)
    checked["operation_id"] = operation_id
    checked["artifact_invalidation"] = invalidation
    return checked


def _expected_retarget_prepared_state(
    root: Path,
    run_dir: Path,
    *,
    baseline: SpecRun,
    baseline_state: Mapping[str, object],
    replacement_run_id: str,
    replacement_targets: tuple[str, ...],
    retarget_contract: Mapping[str, object],
    product_inputs: Mapping[str, object],
    ignore_re: bool,
    requested_re_sources: tuple[str, ...],
) -> dict[str, object]:
    published_spec_dir = baseline.published_spec_dir
    if published_spec_dir is None:
        raise PhaseAStartError("baseline run has no canonical published spec directory")
    installed_spec_dir = run_dir / "specs" / baseline.spec_id
    return {
        "run_id": replacement_run_id,
        "status": "preparing",
        "phase": "phase0-constitution",
        "completed_phases": [],
        "user_message": baseline_state["user_message"],
        "autonomy_mode": baseline_state["autonomy_mode"],
        "implementation_targets": list(replacement_targets),
        "product_inputs": dict(product_inputs),
        "ignore_re": ignore_re,
        "requested_re_sources": list(requested_re_sources),
        "spec_id": baseline.spec_id,
        "spec_number": baseline_state["spec_number"],
        "spec_dir": installed_spec_dir.relative_to(root).as_posix(),
        "published_spec_dir": published_spec_dir.relative_to(root).as_posix(),
        "feature_branch": baseline.feature_branch,
        "phase_a_default_branch": baseline_state["phase_a_default_branch"],
        "phase_a_base_commit": baseline_state["phase_a_base_commit"],
        "specify_feature_directory": installed_spec_dir.relative_to(root).as_posix(),
        "retarget": dict(retarget_contract),
    }


def _recover_original_re_policy(
    baseline_state: Mapping[str, object],
) -> tuple[bool, tuple[str, ...]]:
    prior_context = baseline_state.get("published_re_context")
    raw_ignore = baseline_state.get("ignore_re")
    if "ignore_re" in baseline_state:
        if not isinstance(raw_ignore, bool):
            raise PhaseAStartError(
                "baseline run has a malformed original reverse-engineering policy"
            )
        ignore_re = raw_ignore
    elif (
        isinstance(prior_context, Mapping)
        and prior_context.get("status") in {"attached", "absent", "ignored"}
    ):
        ignore_re = prior_context.get("status") == "ignored"
    else:
        raise PhaseAStartError("baseline run is missing its original reverse-engineering policy")

    raw_sources = baseline_state.get("requested_re_sources")
    if "requested_re_sources" in baseline_state:
        if not (
            isinstance(raw_sources, list)
            and all(isinstance(source, str) and source for source in raw_sources)
        ):
            raise PhaseAStartError(
                "baseline run has malformed original reverse-engineering source selections"
            )
        requested = tuple(dict.fromkeys(raw_sources))
    elif ignore_re:
        requested = ()
    elif isinstance(prior_context, Mapping):
        try:
            requested = explicit_re_sources(prior_context)
        except ValueError as exc:
            raise PhaseAStartError(str(exc)) from exc
    else:
        raise PhaseAStartError(
            "baseline run is missing its original reverse-engineering source selections"
        )
    return ignore_re, requested


def _require_retarget_git_position(
    root: Path,
    *,
    expected_branch: str,
    expected_commit: str,
) -> str:
    try:
        observed_branch = current_branch(root)
        observed_commit = run_git(root, "rev-parse", "HEAD^{commit}").stdout.strip()
    except GitHelperError as exc:
        raise PhaseAStartError(str(exc)) from exc
    if observed_branch != expected_branch or observed_commit != expected_commit:
        raise PhaseAStartError(
            "retarget Git position drifted: expected "
            f"{expected_branch!r} at {expected_commit}, found "
            f"{observed_branch!r} at {observed_commit}"
        )
    return observed_branch


def _require_matching_retarget_intent(
    intent: SpecSwitchIntent,
    *,
    baseline: SpecRun,
    target: SpecRun,
    operation_id: str,
    allowed_stages: frozenset[str],
) -> None:
    expected = {
        "operation_id": operation_id,
        "source_run": baseline.run_dir_name,
        "target_run": target.run_dir_name,
        "source_branch": baseline.feature_branch,
        "target_branch": target.feature_branch,
    }
    for field, value in expected.items():
        if getattr(intent, field) != value:
            raise PhaseAStartError(f"retarget switch intent identity mismatches {field}")
    if intent.stage not in allowed_stages:
        raise PhaseAStartError(
            f"retarget switch intent stage {intent.stage!r} is not valid for this retry"
        )


def _retarget_reservation_path(
    root: Path,
    *,
    replacement_run_id: str,
    operation_id: str,
) -> Path:
    digest = hashlib.sha256(
        f"{operation_id}\0{replacement_run_id}".encode("utf-8")
    ).hexdigest()[:32]
    return root / "runs" / f".retarget-bootstrap-{digest}.json"


def _retarget_staging_identity(
    *,
    baseline: SpecRun,
    replacement_run_id: str,
    operation_id: str,
) -> dict[str, object]:
    identity: dict[str, object] = {
        "operation_id": operation_id,
        "source_run": baseline.run_dir_name,
        "target_run": replacement_run_id,
        "spec_id": baseline.spec_id,
    }
    _validate_retarget_owner(identity)
    return identity


def _validate_retarget_owner(owner: object) -> None:
    if type(owner) is not dict or set(owner) != _RETARGET_OWNER_KEYS:
        raise PhaseAStartError("retarget ownership artifact has invalid owner schema")
    for field in _RETARGET_OWNER_KEYS:
        value = owner[field]
        if type(value) is not str or not value or len(value) > _MAX_RETARGET_ID_LENGTH:
            raise PhaseAStartError(f"retarget ownership artifact has invalid {field}")
    if _SAFE_OPERATION_ID.fullmatch(owner["operation_id"]) is None:
        raise PhaseAStartError("retarget ownership artifact has invalid operation_id")
    for field in ("source_run", "target_run"):
        if _SAFE_REPLACEMENT_RUN_ID.fullmatch(owner[field]) is None:
            raise PhaseAStartError(f"retarget ownership artifact has invalid {field}")
    if _CANONICAL_SPEC_ID.fullmatch(owner["spec_id"]) is None:
        raise PhaseAStartError("retarget ownership artifact has invalid spec_id")


def _read_regular_json(path: Path, *, label: str) -> dict[str, object]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise PhaseAStartError(f"cannot open {label}: {path}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise PhaseAStartError(f"{label} is not an exclusive regular file: {path}")
        chunks: list[bytes] = []
        size = 0
        while chunk := os.read(descriptor, 65536):
            size += len(chunk)
            if size > 65536:
                raise PhaseAStartError(f"{label} is oversized: {path}")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (
            after.st_dev != before.st_dev
            or after.st_ino != before.st_ino
            or after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns
            or after.st_ctime_ns != before.st_ctime_ns
        ):
            raise PhaseAStartError(f"{label} changed while being read: {path}")
    finally:
        os.close(descriptor)
    try:
        payload = loads_strict_json(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PhaseAStartError(f"{label} is malformed: {path}") from exc
    if type(payload) is not dict:
        raise PhaseAStartError(f"{label} must be a JSON object: {path}")
    return payload


def _create_retarget_reservation(
    reservation_path: Path,
    staging_identity: Mapping[str, object],
) -> dict[str, object]:
    staging_name = f".retarget-run-{uuid4().hex}"
    payload = {
        "schema_version": 1,
        "owner": dict(staging_identity),
        "staging_name": staging_name,
    }
    temporary = reservation_path.parent / f".retarget-reservation-{uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        encoded = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
        offset = 0
        while offset < len(encoded):
            offset += os.write(descriptor, encoded[offset:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        atomic_install.atomic_rename_no_replace(temporary, reservation_path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return payload


def _load_retarget_reservation(
    reservation_path: Path,
    staging_identity: Mapping[str, object],
) -> dict[str, object]:
    payload = _read_regular_json(reservation_path, label="retarget staging reservation")
    if set(payload) != _RETARGET_RESERVATION_KEYS:
        raise PhaseAStartError("retarget staging reservation has invalid keys")
    if not _json_values_exact(payload.get("schema_version"), 1):
        raise PhaseAStartError("retarget staging reservation has invalid schema_version")
    owner = payload.get("owner")
    _validate_retarget_owner(owner)
    if not _json_values_exact(owner, dict(staging_identity)):
        raise PhaseAStartError("retarget staging reservation has mismatched owner")
    staging_name = payload.get("staging_name")
    if type(staging_name) is not str or _RETARGET_STAGING_NAME.fullmatch(staging_name) is None:
        raise PhaseAStartError("retarget staging reservation has invalid staging_name")
    return payload


def _remove_retarget_reservation(
    reservation_path: Path,
    staging_identity: Mapping[str, object],
) -> None:
    _load_retarget_reservation(reservation_path, staging_identity)
    reservation_path.unlink()
    _sync_parent_directory(reservation_path.parent)


def _create_retarget_staging_directory(staging_dir: Path) -> None:
    staging_dir.mkdir(mode=_CANONICAL_OWNED_DIRECTORY_MODE)
    staging_dir.chmod(_CANONICAL_OWNED_DIRECTORY_MODE)


def _write_retarget_staging_marker(
    staging_dir: Path,
    staging_identity: Mapping[str, object],
) -> None:
    _write_json_atomic(
        staging_dir / _RETARGET_STAGING_MARKER,
        {"schema_version": 1, "owner": dict(staging_identity)},
    )


def _require_owned_retarget_staging(
    staging_dir: Path,
    expected_identity: Mapping[str, object],
) -> None:
    if staging_dir.is_symlink() or not staging_dir.is_dir():
        raise PhaseAStartError(
            f"retarget staging path is not an owned directory: {staging_dir}"
        )
    marker = staging_dir / _RETARGET_STAGING_MARKER
    if marker.is_symlink() or not marker.is_file():
        raise PhaseAStartError(
            f"retarget staging directory has no ownership marker: {staging_dir}"
        )
    payload = _read_regular_json(marker, label="retarget staging ownership marker")
    _validate_retarget_owner(payload.get("owner"))
    if (
        set(payload) != _RETARGET_MARKER_KEYS
        or not _json_values_exact(payload.get("schema_version"), 1)
        or not _json_values_exact(payload.get("owner"), dict(expected_identity))
    ):
        raise PhaseAStartError(
            f"retarget staging directory has a different owner: {staging_dir}"
        )


def _install_prepared_retarget_run(
    run_dir: Path,
    staging_dir: Path,
    staging_identity: Mapping[str, object],
) -> None:
    if run_dir.exists() or run_dir.is_symlink():
        raise PhaseAStartError(f"replacement run directory already exists: {run_dir}")
    _require_owned_retarget_staging(staging_dir, staging_identity)
    durable_tree.durably_sync_owned_tree(
        staging_dir,
        directory_mode=_CANONICAL_OWNED_DIRECTORY_MODE,
        normalize_directory_modes=True,
    )
    atomic_install.atomic_rename_no_replace(staging_dir, run_dir)


def _remove_installed_retarget_marker(
    run_dir: Path,
    staging_identity: Mapping[str, object],
) -> None:
    marker = run_dir / _RETARGET_STAGING_MARKER
    if not marker.exists() and not marker.is_symlink():
        return
    _require_owned_retarget_staging(run_dir, staging_identity)
    marker.unlink()
    _sync_parent_directory(run_dir)


def _require_real_directory(path: Path, *, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise PhaseAStartError(f"prepared run structure is missing {label}") from exc
    if path.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise PhaseAStartError(f"prepared run structure has invalid {label}")
    if stat.S_IMODE(metadata.st_mode) != _CANONICAL_OWNED_DIRECTORY_MODE:
        raise PhaseAStartError(f"prepared run structure has invalid {label} mode")


def _require_canonical_baseline_paths(
    root: Path,
    baseline: SpecRun,
    baseline_state: Mapping[str, object],
) -> None:
    base_name = baseline.run_dir.parent.name
    if base_name not in {"runs", "squad"}:
        raise PhaseAStartError("canonical baseline run directory is invalid")
    expected_run_dir = root / base_name / baseline.run_dir_name
    if (
        baseline.run_dir != expected_run_dir
        or expected_run_dir.is_symlink()
        or not expected_run_dir.is_dir()
    ):
        raise PhaseAStartError("canonical baseline run directory is invalid")
    expected_specs_dir = expected_run_dir / "specs"
    expected_spec_dir = expected_specs_dir / baseline.spec_id
    raw_spec_dir = baseline_state.get("spec_dir")
    if (
        type(raw_spec_dir) is not str
        or raw_spec_dir != expected_spec_dir.relative_to(root).as_posix()
        or baseline.spec_dir != expected_spec_dir
        or expected_specs_dir.is_symlink()
        or not expected_specs_dir.is_dir()
        or expected_spec_dir.is_symlink()
        or not expected_spec_dir.is_dir()
    ):
        raise PhaseAStartError("canonical baseline run-local spec directory is invalid")
    expected_published_dir = root / "specs" / baseline.spec_id
    raw_published_dir = baseline_state.get("published_spec_dir")
    if (
        type(raw_published_dir) is not str
        or raw_published_dir != expected_published_dir.relative_to(root).as_posix()
        or baseline.published_spec_dir != expected_published_dir
        or expected_published_dir.parent.is_symlink()
        or not expected_published_dir.parent.is_dir()
        or expected_published_dir.is_symlink()
        or not expected_published_dir.is_dir()
    ):
        raise PhaseAStartError("canonical baseline published spec directory is invalid")


def _validate_prepared_run_structure(
    run_dir: Path,
    *,
    spec_id: str,
    has_product_inputs: bool,
    has_ownership_marker: bool,
) -> None:
    _require_real_directory(run_dir, label="run directory")
    specs_dir = run_dir / "specs"
    spec_dir = specs_dir / spec_id
    staging_dir = run_dir / "staging"
    _require_real_directory(specs_dir, label="specs directory")
    _require_real_directory(spec_dir, label="run-local spec directory")
    _require_real_directory(staging_dir, label="staging directory")
    expected_top = {"state.json", "specs", "staging"}
    if has_ownership_marker:
        expected_top.add(_RETARGET_STAGING_MARKER)
    if has_product_inputs:
        _require_real_directory(run_dir / "inputs", label="product input directory")
        expected_top.add("inputs")
    if {path.name for path in run_dir.iterdir()} != expected_top:
        raise PhaseAStartError("prepared run structure has unexpected top-level entries")
    if {path.name for path in specs_dir.iterdir()} != {spec_id}:
        raise PhaseAStartError("prepared run structure has unexpected spec directories")
    if any(spec_dir.iterdir()) or any(staging_dir.iterdir()):
        raise PhaseAStartError("prepared run structure has nonempty prepared directories")


def _validate_existing_retarget_run(
    root: Path,
    run_dir: Path,
    *,
    baseline: SpecRun,
    replacement_run_id: str,
    expected_state: Mapping[str, object],
    expected_product_inputs: Mapping[str, object],
    has_ownership_marker: bool,
) -> SpecRun:
    _validate_prepared_run_structure(
        run_dir,
        spec_id=baseline.spec_id,
        has_product_inputs=bool(expected_product_inputs),
        has_ownership_marker=has_ownership_marker,
    )
    state = _load_state(run_dir)
    if not _json_values_exact(state, dict(expected_state)):
        raise PhaseAStartError("existing replacement prepared state postimage is mismatched")
    product_inputs = state.get("product_inputs")
    try:
        if isinstance(product_inputs, Mapping) and product_inputs:
            expected_inputs = run_dir / "inputs"
            validate_product_input_contract_pointers(root, product_inputs, expected_inputs)
            validate_immutable_product_input_package(expected_inputs, product_inputs)
        if product_inputs != expected_product_inputs:
            raise PhaseAStartError("existing replacement run has mismatched product inputs")
        if not expected_product_inputs and (
            (run_dir / "inputs").exists() or (run_dir / "inputs").is_symlink()
        ):
            raise PhaseAStartError("existing replacement run has unexpected product inputs")
    except ProductInputError as exc:
        raise PhaseAStartError(str(exc)) from exc
    return resolve_spec_run(root, replacement_run_id)


def start_retarget_phase_a_spec(
    project_root: Path,
    *,
    replacement_run_id: str,
    baseline: SpecRun,
    checkpoint_commit: str,
    replacement_targets: tuple[str, ...],
    retarget_state: Mapping[str, object],
) -> RetargetPhaseAStartOutcome:
    """Create and select a new run for the same spec identity and Git branch.

    The caller must hold ``SpecMutationLock`` for ``baseline.spec_id`` and this
    operation ID across the entire call.  This routine deliberately composes
    the inner durable switch transaction without reacquiring that outer lock.
    """

    root = Path(project_root).resolve()
    if (
        type(replacement_run_id) is not str
        or len(replacement_run_id) > _MAX_RETARGET_ID_LENGTH
        or _SAFE_REPLACEMENT_RUN_ID.fullmatch(replacement_run_id) is None
    ):
        raise PhaseAStartError(f"unsafe replacement run ID: {replacement_run_id!r}")
    if (
        type(replacement_targets) is not tuple
        or not replacement_targets
        or any(type(target) is not str for target in replacement_targets)
    ):
        raise PhaseAStartError("replacement target set is not canonical")
    normalized_targets = normalize_target_set(replacement_targets)
    if normalized_targets != replacement_targets:
        raise PhaseAStartError("replacement target set is not canonical")
    if type(checkpoint_commit) is not str or not checkpoint_commit:
        raise PhaseAStartError("retarget checkpoint commit is invalid")

    canonical_baseline = resolve_spec_run(root, baseline.run_dir_name)
    if canonical_baseline != baseline:
        raise PhaseAStartError("retarget baseline identity changed")
    if baseline.published_spec_dir is None:
        raise PhaseAStartError("baseline run has no canonical published spec directory")
    baseline_state = _load_state(baseline.run_dir)
    _require_canonical_baseline_paths(root, baseline, baseline_state)
    user_message = baseline_state.get("user_message")
    if not isinstance(user_message, str) or not user_message.strip():
        raise PhaseAStartError("baseline run is missing its original user message")
    autonomy_mode = baseline_state.get("autonomy_mode")
    if not isinstance(autonomy_mode, str) or not autonomy_mode.strip():
        raise PhaseAStartError("baseline run is missing its original autonomy mode")
    ignore_re, requested_re_sources = _recover_original_re_policy(baseline_state)
    for field in ("spec_number", "phase_a_default_branch", "phase_a_base_commit"):
        value = baseline_state.get(field)
        if type(value) is not str or not value:
            raise PhaseAStartError(f"baseline run has invalid {field}")
    spec_number = baseline_state["spec_number"]
    parsed_spec = _CANONICAL_SPEC_ID.fullmatch(baseline.spec_id)
    if (
        len(baseline.spec_id) > _MAX_RETARGET_ID_LENGTH
        or parsed_spec is None
        or len(spec_number) > _MAX_RETARGET_ID_LENGTH
        or spec_number != parsed_spec.group("number")
    ):
        raise PhaseAStartError("baseline run has invalid spec_number binding")
    base_commit = baseline_state["phase_a_base_commit"]
    try:
        resolved_base_commit = run_git(
            root, "rev-parse", f"{base_commit}^{{commit}}"
        ).stdout.strip()
    except GitHelperError as exc:
        raise PhaseAStartError("baseline run has invalid phase_a_base_commit") from exc
    if base_commit != resolved_base_commit:
        raise PhaseAStartError(
            "baseline run has noncanonical phase_a_base_commit"
        )

    try:
        resolved_checkpoint = run_git(
            root, "rev-parse", f"{checkpoint_commit}^{{commit}}"
        ).stdout.strip()
    except GitHelperError as exc:
        raise PhaseAStartError(str(exc)) from exc
    if checkpoint_commit != resolved_checkpoint:
        raise PhaseAStartError("retarget checkpoint commit is not a canonical object ID")
    retarget_contract = _validate_retarget_contract(
        retarget_state,
        baseline=baseline,
        baseline_state=baseline_state,
        replacement_run_id=replacement_run_id,
        replacement_targets=normalized_targets,
        checkpoint_commit=resolved_checkpoint,
    )
    operation_id = retarget_contract["operation_id"]
    assert type(operation_id) is str
    observed = _require_retarget_git_position(
        root,
        expected_branch=baseline.feature_branch,
        expected_commit=resolved_checkpoint,
    )

    run_dir = root / "runs" / replacement_run_id
    try:
        expected_product_inputs = project_cloned_product_input_contract(
            root,
            baseline_state,
            run_dir,
            baseline_run_dir=baseline.run_dir,
        )
    except ProductInputError as exc:
        raise PhaseAStartError(str(exc)) from exc
    expected_state = _expected_retarget_prepared_state(
        root,
        run_dir,
        baseline=baseline,
        baseline_state=baseline_state,
        replacement_run_id=replacement_run_id,
        replacement_targets=normalized_targets,
        retarget_contract=retarget_contract,
        product_inputs=expected_product_inputs,
        ignore_re=ignore_re,
        requested_re_sources=requested_re_sources,
    )
    reservation_path = _retarget_reservation_path(
        root,
        replacement_run_id=replacement_run_id,
        operation_id=operation_id,
    )
    staging_identity = _retarget_staging_identity(
        baseline=baseline,
        replacement_run_id=replacement_run_id,
        operation_id=operation_id,
    )
    active = resolve_active_spec_run(root)
    if active != baseline and active.run_dir != run_dir.resolve():
        raise PhaseAStartError("active run drifted from the retarget baseline")

    reservation: dict[str, object] | None = None
    if reservation_path.exists() or reservation_path.is_symlink():
        reservation = _load_retarget_reservation(reservation_path, staging_identity)
    elif not run_dir.exists() and not run_dir.is_symlink():
        reservation = _create_retarget_reservation(reservation_path, staging_identity)

    if not run_dir.exists() and not run_dir.is_symlink():
        if reservation is None:
            raise PhaseAStartError("replacement run has no staging reservation")
        staging_dir = run_dir.parent / str(reservation["staging_name"])
        if staging_dir.exists() or staging_dir.is_symlink():
            _require_real_directory(staging_dir, label="reserved staging directory")
            shutil.rmtree(staging_dir)
        _create_retarget_staging_directory(staging_dir)
        _write_retarget_staging_marker(staging_dir, staging_identity)
        product_inputs = clone_product_input_contract(
            root,
            baseline_state,
            staging_dir,
            baseline_run_dir=baseline.run_dir,
            contract_run_dir=run_dir,
        )
        if product_inputs != expected_product_inputs:
            raise PhaseAStartError("cloned product inputs differ from the validated baseline")
        _write_retarget_prepared_state(
            staging_dir,
            expected_state,
        )
        _install_prepared_retarget_run(
            run_dir,
            staging_dir,
            staging_identity,
        )

    marker_path = run_dir / _RETARGET_STAGING_MARKER
    has_ownership_marker = marker_path.exists() or marker_path.is_symlink()
    if has_ownership_marker:
        _require_owned_retarget_staging(run_dir, staging_identity)
    target = _validate_existing_retarget_run(
        root,
        run_dir,
        baseline=baseline,
        replacement_run_id=replacement_run_id,
        expected_state=expected_state,
        expected_product_inputs=expected_product_inputs,
        has_ownership_marker=has_ownership_marker,
    )
    if has_ownership_marker:
        _remove_installed_retarget_marker(run_dir, staging_identity)
    try:
        intent = load_spec_switch_intent(root)
    except SpecLifecycleError as exc:
        raise PhaseAStartError(str(exc)) from exc

    if active.run_dir == run_dir.resolve():
        if intent is None:
            if reservation is not None:
                _remove_retarget_reservation(reservation_path, staging_identity)
            return RetargetPhaseAStartOutcome(
                run_dir=run_dir,
                run=target,
                baseline=baseline,
            )
        _require_matching_retarget_intent(
            intent,
            baseline=baseline,
            target=target,
            operation_id=operation_id,
            allowed_stages=frozenset({"checked_out"}),
        )
        observed = _require_retarget_git_position(
            root,
            expected_branch=baseline.feature_branch,
            expected_commit=resolved_checkpoint,
        )
        try:
            selected = commit_spec_switch_pointer(
                root,
                operation_id,
                observed_branch=observed,
            )
        except SpecLifecycleError as exc:
            raise PhaseAStartError(str(exc)) from exc
        if reservation is not None:
            _remove_retarget_reservation(reservation_path, staging_identity)
        return RetargetPhaseAStartOutcome(
            run_dir=run_dir,
            run=selected,
            baseline=baseline,
        )

    if intent is None:
        observed = _require_retarget_git_position(
            root,
            expected_branch=baseline.feature_branch,
            expected_commit=resolved_checkpoint,
        )
        try:
            intent = begin_spec_switch(
                root,
                baseline,
                target,
                observed_branch=observed,
                operation_id=operation_id,
            )
        except SpecLifecycleError as exc:
            raise PhaseAStartError(str(exc)) from exc
    else:
        _require_matching_retarget_intent(
            intent,
            baseline=baseline,
            target=target,
            operation_id=operation_id,
            allowed_stages=frozenset({"prepared", "checked_out"}),
        )

    if intent.stage == "prepared":
        observed = _require_retarget_git_position(
            root,
            expected_branch=baseline.feature_branch,
            expected_commit=resolved_checkpoint,
        )
        try:
            mark_spec_switch_checked_out(root, operation_id, observed_branch=observed)
        except SpecLifecycleError as exc:
            raise PhaseAStartError(str(exc)) from exc
    observed = _require_retarget_git_position(
        root,
        expected_branch=baseline.feature_branch,
        expected_commit=resolved_checkpoint,
    )
    try:
        selected = commit_spec_switch_pointer(root, operation_id, observed_branch=observed)
    except SpecLifecycleError as exc:
        raise PhaseAStartError(str(exc)) from exc
    if reservation is not None:
        _remove_retarget_reservation(reservation_path, staging_identity)
    return RetargetPhaseAStartOutcome(run_dir=run_dir, run=selected, baseline=baseline)


def _write_prepared_state(
    run_dir: Path,
    run_id: str,
    description: str,
    bootstrap: PhaseASpecBootstrap,
) -> None:
    run_dir.mkdir(parents=True)
    (run_dir / "staging").mkdir()
    (run_dir / "specs" / bootstrap.spec_id).mkdir(parents=True)
    payload: dict[str, object] = {
        "run_id": run_id,
        "status": "preparing",
        "user_message": description,
        **bootstrap.state_updates(),
    }
    (run_dir / "state.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def _resolve_source(root: Path) -> SpecRun | None:
    pointer = root / "runs" / ".current"
    if not pointer.exists():
        return None
    return resolve_active_spec_run(root)


def start_phase_a_spec(
    project_root: Path,
    run_id: str,
    description: str,
    *,
    configured_default_branch: str = "",
    dirty_action: str = "refuse",
    confirm_discard: bool = False,
) -> PhaseAStartOutcome:
    """Create and select a fresh sibling spec branch without invoking an LLM."""

    if dirty_action not in {"refuse", "stash", "discard"}:
        raise PhaseAStartError(f"unsupported dirty action: {dirty_action!r}")
    if dirty_action == "discard" and not confirm_discard:
        raise PhaseAStartError("discard requires explicit confirmation via --discard --confirm")
    if confirm_discard and dirty_action != "discard":
        raise PhaseAStartError("discard confirmation requires dirty_action='discard'")

    root = Path(project_root).resolve()
    target_dir = root / "runs" / run_id
    operation_id = f"start-{uuid4().hex}"
    created_branch = ""
    try:
        with SpecLifecycleLock.acquire(root, operation_id):
            with PhaseAExecutionLock.acquire(root, operation_id):
                require_speckit_git_disabled(root)
                observed = current_branch(root)
                if not observed:
                    raise PhaseAStartError("detached HEAD blocks a fresh spec start")
                if load_spec_switch_intent(root) is not None:
                    recover_spec_switch(root, observed_branch=observed)
                    observed = current_branch(root)

                source = _resolve_source(root)
                source_checkpoint = None
                stash_commit = ""
                if source is not None:
                    if observed != source.feature_branch:
                        raise PhaseAStartError(
                            f"active run branch is {source.feature_branch!r}, but Git is on {observed!r}"
                        )
                    source_checkpoint = validate_spec_checkpoint(root, source)

                dirty_paths = spec_worktree_paths(root)
                if dirty_paths:
                    if source is None:
                        raise DirtySpecWorktreeError(dirty_paths)
                    if dirty_action == "refuse":
                        raise DirtySpecWorktreeError(dirty_paths)
                    if dirty_action == "stash":
                        stash_commit = stash_spec_worktree(root, source, source_checkpoint)
                    else:
                        discard_spec_worktree(root, source_checkpoint)

                if target_dir.exists():
                    raise PhaseAStartError(f"target run directory already exists: {target_dir}")
                bootstrap = plan_phase_a_spec(
                    root,
                    target_dir,
                    description,
                    configured_default_branch,
                )
                if source is None and observed != bootstrap.default_branch:
                    raise PhaseAStartError(
                        "first spec start requires the configured default branch "
                        f"{bootstrap.default_branch!r}; found {observed!r}"
                    )
                create_phase_a_spec_branch_ref(root, bootstrap, clean_verified=True)
                created_branch = bootstrap.feature_branch
                _write_prepared_state(target_dir, run_id, description, bootstrap)
                target = resolve_spec_run(root, run_id)

                if source is not None:
                    begin_spec_switch(
                        root,
                        source,
                        target,
                        observed_branch=observed,
                        operation_id=operation_id,
                    )
                run_git(root, "switch", bootstrap.feature_branch)
                selected_branch = current_branch(root)
                if source is None:
                    activate_initial_spec_run(
                        root,
                        target,
                        observed_branch=selected_branch,
                    )
                else:
                    mark_spec_switch_checked_out(
                        root,
                        operation_id,
                        observed_branch=selected_branch,
                    )
                    commit_spec_switch_pointer(
                        root,
                        operation_id,
                        observed_branch=selected_branch,
                    )
                return PhaseAStartOutcome(
                    run_dir=target_dir,
                    bootstrap=bootstrap,
                    source=source,
                    source_checkpoint=source_checkpoint,
                    stash_commit=stash_commit,
                )
    except PhaseAStartError:
        raise
    except DirtySpecWorktreeError as exc:
        raise PhaseAStartError(str(exc)) from exc
    except (
        GitHelperError,
        PhaseAGitError,
        SpecKitGitOwnershipError,
        SpecLifecycleError,
        SpecSwitchError,
    ) as exc:
        intent_exists = load_spec_switch_intent(root) is not None
        try:
            branch_after_error = current_branch(root)
        except GitHelperError:
            branch_after_error = ""
        if not intent_exists:
            if created_branch and branch_after_error == created_branch:
                run_git(root, "switch", bootstrap.default_branch, check=False)
            if target_dir.exists():
                shutil.rmtree(target_dir)
            if created_branch:
                run_git(root, "branch", "-D", created_branch, check=False)
        raise PhaseAStartError(str(exc)) from exc
