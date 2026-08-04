"""Transactional Echelon-owned bootstrap for a fresh Phase A spec."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Mapping
from uuid import uuid4

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
_RETARGET_STAGING_MARKER = ".echelon-retarget-bootstrap.json"


def _load_state(run_dir: Path) -> dict[str, object]:
    state_path = Path(run_dir) / "state.json"
    if state_path.is_symlink() or not state_path.is_file():
        raise PhaseAStartError(f"baseline state is not a regular file: {state_path}")
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
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
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _write_retarget_prepared_state(
    root: Path,
    run_dir: Path,
    *,
    baseline: SpecRun,
    baseline_state: Mapping[str, object],
    replacement_run_id: str,
    checkpoint_commit: str,
    replacement_targets: tuple[str, ...],
    retarget_state: Mapping[str, object],
    product_inputs: Mapping[str, object],
    ignore_re: bool,
    requested_re_sources: tuple[str, ...],
    installed_run_dir: Path | None = None,
) -> None:
    run_spec_dir = run_dir / "specs" / baseline.spec_id
    installed_spec_dir = (installed_run_dir or run_dir) / "specs" / baseline.spec_id
    run_spec_dir.mkdir(parents=True)
    (run_dir / "staging").mkdir()
    retarget = dict(retarget_state)
    retarget.update(
        {
            "status": "checkpointed",
            "baseline_run_id": baseline.run_id,
            "replacement_run_id": replacement_run_id,
            "replacement_targets": list(replacement_targets),
            "checkpoint_commit": checkpoint_commit,
        }
    )
    published_spec_dir = baseline.published_spec_dir
    if published_spec_dir is None:
        raise PhaseAStartError("baseline run has no canonical published spec directory")
    spec_number = str(baseline_state.get("spec_number") or baseline.spec_id.split("-", 1)[0])
    payload: dict[str, object] = {
        "run_id": replacement_run_id,
        "status": "preparing",
        "phase": "phase0-constitution",
        "completed_phases": [],
        "user_message": str(baseline_state.get("user_message") or ""),
        "autonomy_mode": str(baseline_state.get("autonomy_mode") or "semi"),
        "implementation_targets": list(replacement_targets),
        "product_inputs": dict(product_inputs),
        "ignore_re": ignore_re,
        "requested_re_sources": list(requested_re_sources),
        "spec_id": baseline.spec_id,
        "spec_number": spec_number,
        "spec_dir": installed_spec_dir.relative_to(root).as_posix(),
        "published_spec_dir": published_spec_dir.relative_to(root).as_posix(),
        "feature_branch": baseline.feature_branch,
        "phase_a_default_branch": str(baseline_state.get("phase_a_default_branch") or ""),
        "phase_a_base_commit": str(baseline_state.get("phase_a_base_commit") or ""),
        "specify_feature_directory": installed_spec_dir.relative_to(root).as_posix(),
        "retarget": retarget,
    }
    _write_json_atomic(run_dir / "state.json", payload)


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


def _retarget_staging_path(
    root: Path,
    *,
    replacement_run_id: str,
    operation_id: str,
) -> Path:
    return root / "runs" / f".retarget-bootstrap-{operation_id}-{replacement_run_id}"


def _retarget_staging_identity(
    *,
    baseline: SpecRun,
    replacement_run_id: str,
    operation_id: str,
) -> dict[str, object]:
    return {
        "operation_id": operation_id,
        "source_run": baseline.run_dir_name,
        "target_run": replacement_run_id,
        "spec_id": baseline.spec_id,
    }


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
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PhaseAStartError(
            f"cannot validate retarget staging ownership: {staging_dir}"
        ) from exc
    if payload != dict(expected_identity):
        raise PhaseAStartError(
            f"retarget staging directory has a different owner: {staging_dir}"
        )


def _remove_owned_retarget_staging(
    staging_dir: Path,
    expected_identity: Mapping[str, object],
) -> None:
    if not staging_dir.exists() and not staging_dir.is_symlink():
        return
    _require_owned_retarget_staging(staging_dir, expected_identity)
    shutil.rmtree(staging_dir)


def _install_prepared_retarget_run(
    run_dir: Path,
    staging_dir: Path,
    staging_identity: Mapping[str, object],
) -> None:
    if run_dir.exists() or run_dir.is_symlink():
        raise PhaseAStartError(f"replacement run directory already exists: {run_dir}")
    _require_owned_retarget_staging(staging_dir, staging_identity)
    os.replace(staging_dir, run_dir)
    directory_fd = os.open(run_dir.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    (run_dir / _RETARGET_STAGING_MARKER).unlink()


def _discard_installed_retarget_marker(
    run_dir: Path,
    staging_identity: Mapping[str, object],
) -> None:
    marker = run_dir / _RETARGET_STAGING_MARKER
    if not marker.exists() and not marker.is_symlink():
        return
    _require_owned_retarget_staging(run_dir, staging_identity)
    marker.unlink()


def _validate_existing_retarget_run(
    root: Path,
    run_dir: Path,
    *,
    baseline: SpecRun,
    replacement_run_id: str,
    checkpoint_commit: str,
    replacement_targets: tuple[str, ...],
    operation_id: str,
    baseline_state: Mapping[str, object],
    ignore_re: bool,
    requested_re_sources: tuple[str, ...],
) -> SpecRun:
    state = _load_state(run_dir)
    retarget = state.get("retarget")
    expected = {
        "run_id": replacement_run_id,
        "spec_id": baseline.spec_id,
        "feature_branch": baseline.feature_branch,
        "implementation_targets": list(replacement_targets),
        "status": "preparing",
        "phase": "phase0-constitution",
        "user_message": baseline_state["user_message"],
        "autonomy_mode": baseline_state["autonomy_mode"],
        "ignore_re": ignore_re,
        "requested_re_sources": list(requested_re_sources),
        "spec_dir": (run_dir / "specs" / baseline.spec_id).relative_to(root).as_posix(),
        "published_spec_dir": (
            baseline.published_spec_dir.relative_to(root).as_posix()
            if baseline.published_spec_dir is not None
            else ""
        ),
        "specify_feature_directory": (
            run_dir / "specs" / baseline.spec_id
        ).relative_to(root).as_posix(),
    }
    for key, value in expected.items():
        if state.get(key) != value:
            raise PhaseAStartError(f"existing replacement run has mismatched {key}")
    if not isinstance(retarget, Mapping):
        raise PhaseAStartError("existing replacement run has no retarget identity")
    retarget_expected = {
        "operation_id": operation_id,
        "baseline_run_id": baseline.run_id,
        "replacement_run_id": replacement_run_id,
        "checkpoint_commit": checkpoint_commit,
        "replacement_targets": list(replacement_targets),
        "status": "checkpointed",
    }
    for key, value in retarget_expected.items():
        if retarget.get(key) != value:
            raise PhaseAStartError(f"existing replacement run has mismatched retarget {key}")
    product_inputs = state.get("product_inputs")
    try:
        expected_product_inputs = project_cloned_product_input_contract(
            root,
            baseline_state,
            run_dir,
            baseline_run_dir=baseline.run_dir,
        )
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
    if _SAFE_REPLACEMENT_RUN_ID.fullmatch(replacement_run_id) is None:
        raise PhaseAStartError(f"unsafe replacement run ID: {replacement_run_id!r}")
    normalized_targets = normalize_target_set(replacement_targets)
    if not normalized_targets:
        raise PhaseAStartError("replacement target set must not be empty")
    operation_id = str(retarget_state.get("operation_id") or "")
    if _SAFE_OPERATION_ID.fullmatch(operation_id) is None:
        raise PhaseAStartError(f"unsafe retarget operation ID: {operation_id!r}")

    canonical_baseline = resolve_spec_run(root, baseline.run_dir_name)
    if canonical_baseline != baseline:
        raise PhaseAStartError("retarget baseline identity changed")
    if baseline.published_spec_dir is None:
        raise PhaseAStartError("baseline run has no canonical published spec directory")
    baseline_state = _load_state(baseline.run_dir)
    user_message = baseline_state.get("user_message")
    if not isinstance(user_message, str) or not user_message.strip():
        raise PhaseAStartError("baseline run is missing its original user message")
    autonomy_mode = baseline_state.get("autonomy_mode")
    if not isinstance(autonomy_mode, str) or not autonomy_mode.strip():
        raise PhaseAStartError("baseline run is missing its original autonomy mode")
    ignore_re, requested_re_sources = _recover_original_re_policy(baseline_state)

    try:
        resolved_checkpoint = run_git(
            root, "rev-parse", f"{checkpoint_commit}^{{commit}}"
        ).stdout.strip()
    except GitHelperError as exc:
        raise PhaseAStartError(str(exc)) from exc
    if checkpoint_commit != resolved_checkpoint:
        raise PhaseAStartError("retarget checkpoint commit is not a canonical object ID")
    observed = _require_retarget_git_position(
        root,
        expected_branch=baseline.feature_branch,
        expected_commit=resolved_checkpoint,
    )

    run_dir = root / "runs" / replacement_run_id
    staging_dir = _retarget_staging_path(
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

    if staging_dir.exists() or staging_dir.is_symlink():
        _remove_owned_retarget_staging(staging_dir, staging_identity)

    if not run_dir.exists() and not run_dir.is_symlink():
        staging_dir.mkdir()
        _write_json_atomic(
            staging_dir / _RETARGET_STAGING_MARKER,
            staging_identity,
        )
        product_inputs = clone_product_input_contract(
            root,
            baseline_state,
            staging_dir,
            baseline_run_dir=baseline.run_dir,
            contract_run_dir=run_dir,
        )
        _write_retarget_prepared_state(
            root,
            staging_dir,
            baseline=baseline,
            baseline_state=baseline_state,
            replacement_run_id=replacement_run_id,
            checkpoint_commit=resolved_checkpoint,
            replacement_targets=normalized_targets,
            retarget_state=retarget_state,
            product_inputs=product_inputs,
            ignore_re=ignore_re,
            requested_re_sources=requested_re_sources,
            installed_run_dir=run_dir,
        )
        _install_prepared_retarget_run(
            run_dir,
            staging_dir,
            staging_identity,
        )

    _discard_installed_retarget_marker(run_dir, staging_identity)
    target = _validate_existing_retarget_run(
        root,
        run_dir,
        baseline=baseline,
        replacement_run_id=replacement_run_id,
        checkpoint_commit=resolved_checkpoint,
        replacement_targets=normalized_targets,
        operation_id=operation_id,
        baseline_state=baseline_state,
        ignore_re=ignore_re,
        requested_re_sources=requested_re_sources,
    )
    try:
        intent = load_spec_switch_intent(root)
    except SpecLifecycleError as exc:
        raise PhaseAStartError(str(exc)) from exc

    if active.run_dir == run_dir.resolve():
        if intent is None:
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
