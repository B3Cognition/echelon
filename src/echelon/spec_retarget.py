"""Deterministic, read-only evidence for safe Phase A spec retargeting."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import shlex
from typing import Any, Iterable, Mapping

import yaml

from echelon.artifact_index import artifact_definitions
from echelon.git_helpers import GitHelperError, current_branch, worktree_dirty_paths
from echelon.spec_lifecycle import (
    SpecLifecycleError,
    resolve_active_spec_run,
    resolve_spec_run,
)
from harness.spec_frontmatter import read_frontmatter


class RetargetError(RuntimeError):
    """Base error for deterministic spec retarget operations."""


class RetargetEligibilityError(RetargetError):
    pass


class RetargetArtifactError(RetargetError):
    pass


class RetargetCheckpointError(RetargetError):
    pass


class RetargetRebuildError(RetargetError):
    pass


@dataclass(frozen=True)
class RetargetEvidence:
    spec_id: str
    run_id: str
    run_dir: Path
    spec_dir: Path
    feature_branch: str
    current_branch: str
    active_run_id: str
    canonical_targets: tuple[str, ...]
    state_targets: tuple[str, ...]
    replacement_targets: tuple[str, ...]
    lifecycle_status: str
    phase_b_history: tuple[str, ...]
    delivery_state_paths: tuple[str, ...]
    completed_task_ids: tuple[str, ...]
    post_phase_a_artifacts: tuple[str, ...]
    selected_spec_dirty_paths: tuple[str, ...]
    original_user_message: str
    autonomy_mode: str
    product_inputs_recoverable: bool
    published_re_recoverable: bool


@dataclass(frozen=True)
class RetargetEligibility:
    eligible: bool
    reason_codes: tuple[str, ...]
    next_command: str


_POST_PHASE_A_STATUSES = frozenset(
    {"in-progress", "implemented", "ready_to_land", "landed"}
)
_PRE_DELIVERY_STATUSES = frozenset({"planned"})
_COMPLETED_TASK = re.compile(r"^\s*-\s*\[[xX]\]\s+([A-Za-z0-9][A-Za-z0-9_.-]*)")
_RECOVERABLE_RE_STATUSES = frozenset({"attached", "absent", "ignored"})
_HISTORY_FILES = ("run-history.json", "harness-run-history.json")


def classify_retarget(evidence: RetargetEvidence) -> RetargetEligibility:
    """Classify already-collected evidence without performing any I/O.

    Eligibility deliberately never calls ``artifact_index.infer_lifecycle_stage``:
    Phase A history is a build marker for that presentation-only helper.
    """

    reasons: list[str] = []
    canonical_targets = _normalized_targets(evidence.canonical_targets)
    state_targets = _normalized_targets(evidence.state_targets)
    replacement_targets = _normalized_targets(evidence.replacement_targets)
    active_matches = (
        evidence.active_run_id == evidence.run_id
        and evidence.current_branch == evidence.feature_branch
    )
    if not active_matches:
        reasons.append("retarget_active_spec_mismatch")
    if state_targets != canonical_targets:
        reasons.append("retarget_target_contract_mismatch")
    if not replacement_targets:
        reasons.append("retarget_target_set_empty")
    elif replacement_targets == canonical_targets:
        reasons.append("retarget_target_set_unchanged")
    if (
        evidence.phase_b_history
        or evidence.delivery_state_paths
        or evidence.completed_task_ids
        or evidence.post_phase_a_artifacts
        or evidence.lifecycle_status in _POST_PHASE_A_STATUSES
    ):
        reasons.append("retarget_delivery_already_started")
    elif evidence.lifecycle_status not in _PRE_DELIVERY_STATUSES:
        reasons.append("retarget_lifecycle_ambiguous")
    if evidence.selected_spec_dirty_paths:
        reasons.append("retarget_selected_spec_dirty")
    if not evidence.original_user_message or not evidence.product_inputs_recoverable:
        reasons.append("retarget_original_intent_missing")
    if not evidence.published_re_recoverable:
        reasons.append("retarget_re_context_missing")
    new_spec_command = shlex.join(
        [
            "echelon",
            "spec",
            "run",
            evidence.original_user_message,
            *(
                token
                for target in replacement_targets
                for token in ("--target", target)
            ),
        ]
    )
    next_command = (
        f"echelon spec switch {evidence.spec_id}"
        if "retarget_active_spec_mismatch" in reasons
        else new_spec_command
    )
    return RetargetEligibility(not reasons, tuple(dict.fromkeys(reasons)), next_command)


def collect_retarget_evidence(project_root: Path, spec_id: str) -> RetargetEvidence:
    """Read the complete retarget safety record for one selected spec run.

    The collector is intentionally separate from classification and only reads
    canonical spec data, run state, delivery evidence, and selected-spec Git
    status.  It does not acquire locks or write preview data.
    """

    root = Path(project_root).resolve()
    selected_id = str(spec_id).strip()
    if not selected_id:
        raise RetargetEligibilityError("spec id is empty")
    try:
        run = resolve_spec_run(root, selected_id)
        active = resolve_active_spec_run(root)
        observed_branch = current_branch(root)
    except (SpecLifecycleError, GitHelperError) as exc:
        raise RetargetEligibilityError(str(exc)) from exc

    if run.spec_id != selected_id or run.feature_branch != selected_id:
        raise RetargetEligibilityError(
            f"selected spec identity does not agree with requested spec: {selected_id!r}"
        )
    state = _read_json_object(run.run_dir / "state.json")
    spec_dir = run.spec_dir
    canonical_targets = _canonical_targets(spec_dir)
    state_targets = _state_targets(state)
    lifecycle_status = str(read_frontmatter(spec_dir).get("status") or "").strip().lower()
    return RetargetEvidence(
        spec_id=run.spec_id,
        run_id=run.run_id,
        run_dir=run.run_dir,
        spec_dir=spec_dir,
        feature_branch=run.feature_branch,
        current_branch=observed_branch,
        active_run_id=active.run_id,
        canonical_targets=canonical_targets,
        state_targets=state_targets,
        replacement_targets=canonical_targets,
        lifecycle_status=lifecycle_status,
        phase_b_history=_phase_b_history(spec_dir),
        delivery_state_paths=_delivery_state_paths(root, run.spec_id),
        completed_task_ids=_completed_task_ids(spec_dir),
        post_phase_a_artifacts=_post_phase_a_artifacts(spec_dir),
        selected_spec_dirty_paths=_selected_spec_dirty_paths(root, spec_dir),
        original_user_message=_first_text(state, "original_user_message", "user_message"),
        autonomy_mode=_first_text(state, "autonomy_mode", "mode"),
        product_inputs_recoverable=_product_inputs_recoverable(spec_dir, state),
        published_re_recoverable=_published_re_recoverable(spec_dir, state),
    )


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RetargetEligibilityError(f"cannot read active run state {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RetargetEligibilityError(f"active run state must be a JSON object: {path}")
    return value


def _canonical_targets(spec_dir: Path) -> tuple[str, ...]:
    """Use targets.yml only; frontmatter fallback is not a retarget contract."""

    path = spec_dir / "targets.yml"
    if not path.is_file():
        return ()
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return ()
    if not isinstance(payload, dict) or not isinstance(payload.get("targets"), list):
        return ()
    raw_targets = payload["targets"]
    if not raw_targets:
        return ()
    paths: list[str] = []
    for entry in raw_targets:
        if isinstance(entry, str):
            candidate = entry
        elif isinstance(entry, Mapping) and isinstance(entry.get("path"), str):
            candidate = entry["path"]
        else:
            return ()
        normalized = _normalized_targets((candidate,))
        if not normalized:
            return ()
        paths.append(normalized[0])
    return _normalized_targets(paths)


def _state_targets(state: Mapping[str, object]) -> tuple[str, ...]:
    value = state.get("implementation_targets")
    if value is None:
        value = state.get("targets")
    if value is None:
        value = state.get("target_paths")
    if isinstance(value, Mapping):
        value = value.get("targets")
    if isinstance(value, str):
        value = (value,)
    return _normalized_targets(value if isinstance(value, Iterable) else ())


def _normalized_targets(values: Iterable[object]) -> tuple[str, ...]:
    ordered: list[str] = []
    for value in values:
        target = str(value or "").strip().rstrip("/")
        if target and target not in ordered:
            ordered.append(target)
    return tuple(ordered)


def _phase_b_history(spec_dir: Path) -> tuple[str, ...]:
    evidence: list[str] = []
    for filename in _HISTORY_FILES:
        path = spec_dir / filename
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            evidence.append(f"{filename}:unreadable")
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("runs"), list):
            evidence.append(f"{filename}:unreadable")
            continue
        for index, row in enumerate(payload["runs"]):
            if not isinstance(row, dict):
                evidence.append(f"{filename}:unreadable")
                continue
            is_phase_b = filename == "harness-run-history.json" or str(
                row.get("phase") or ""
            ).strip().upper() == "B"
            if is_phase_b:
                identity = _first_text(row, "build_id", "run_id") or str(index + 1)
                evidence.append(f"{filename}:{identity}")
    return tuple(sorted(set(evidence)))


def _delivery_state_paths(project_root: Path, spec_id: str) -> tuple[str, ...]:
    runs = project_root / "runs"
    if not runs.is_dir():
        return ()
    paths: list[str] = []
    for build_dir in sorted(runs.glob("build-*")):
        if not build_dir.is_dir() or build_dir.is_symlink():
            continue
        candidates = [build_dir / "state.json"]
        state_dir = build_dir / "state"
        if state_dir.is_dir() and not state_dir.is_symlink():
            candidates.extend(sorted(state_dir.rglob("*.json")))
        for path in candidates:
            if not path.is_file() or path.is_symlink():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and str(payload.get("spec_id") or "").strip() == spec_id:
                paths.append(path.relative_to(project_root).as_posix())
    return tuple(sorted(set(paths)))


def _completed_task_ids(spec_dir: Path) -> tuple[str, ...]:
    path = spec_dir / "tasks.md"
    if not path.is_file():
        return ()
    try:
        matches = (
            match.group(1)
            for line in path.read_text(encoding="utf-8").splitlines()
            if (match := _COMPLETED_TASK.match(line)) is not None
        )
        return tuple(sorted(set(matches)))
    except OSError:
        return ("tasks.md:unreadable",)


def _post_phase_a_artifacts(spec_dir: Path) -> tuple[str, ...]:
    """Enumerate registry-declared build/verification outputs, never infer a stage."""

    return tuple(
        definition.path
        for definition in artifact_definitions()
        if definition.phase in {"Build", "Verification"}
        and definition.path not in _HISTORY_FILES
        and (spec_dir / definition.path).exists()
    )


def _selected_spec_dirty_paths(project_root: Path, spec_dir: Path) -> tuple[str, ...]:
    try:
        dirty_paths = worktree_dirty_paths(project_root)
    except GitHelperError as exc:
        raise RetargetEligibilityError(f"cannot inspect selected spec Git status: {exc}") from exc
    relative_spec = spec_dir.resolve().relative_to(project_root).as_posix()
    prefix = f"{relative_spec}/"
    return tuple(sorted(path for path in dirty_paths if path == relative_spec or path.startswith(prefix)))


def _product_inputs_recoverable(spec_dir: Path, state: Mapping[str, object]) -> bool:
    inputs = state.get("product_inputs")
    if inputs is None or inputs == {}:
        # No declared product-input package is itself a complete, recoverable
        # record; do not reject ordinary prompt-only specifications.
        return True
    if isinstance(inputs, Mapping) and inputs.get("recoverable") is True:
        return True
    if (spec_dir / "inputs").exists() or (spec_dir / "inputs.yml").is_file():
        return True
    if isinstance(inputs, Mapping):
        return any(
            isinstance(inputs.get(key), str) and str(inputs[key]).strip()
            for key in ("inputs_dir", "manifest", "catalog", "traceability")
        )
    return False


def _published_re_recoverable(spec_dir: Path, state: Mapping[str, object]) -> bool:
    context = state.get("published_re_context")
    if isinstance(context, Mapping):
        status = str(context.get("status") or "").strip().lower()
        if status in _RECOVERABLE_RE_STATUSES:
            return True
    path = spec_dir / "re-context.json"
    if not path.is_file():
        return False
    try:
        return isinstance(json.loads(path.read_text(encoding="utf-8")), dict)
    except (OSError, json.JSONDecodeError):
        return False


def _first_text(values: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
