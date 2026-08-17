"""Recoverable completion effects for proportional quality lifecycle work."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
from typing import Mapping

from harness.git_first_restore import (
    GitFirstRestoreError,
    GitFirstRestorePlan,
    build_git_first_restore_commit,
    recover_git_first_restore_plan,
)
from harness.phase1_quality_debt import apply_or_verify_quality_debt_effect
from harness.proportional_quality import (
    _LEGACY_RESTORE_GUIDANCE,
    QualityCandidateIntegrityError,
    _is_candidate_id,
    _is_sha256,
    _legacy_restore_authority_present,
    _validate_committed_checkpoint_receipt_shape,
    _validate_restore_candidate,
    classify_quality_candidate_restore_receipt,
    materialize_quality_candidate,
    materialize_quality_candidate_restore,
    preflight_quality_candidate_restore,
    quality_candidate_from_effect_payload,
    validate_repair_state,
)
from harness.squad_completion import CompletionError


def _inside_project(root: Path, reference: object) -> Path:
    if type(reference) is not str or not reference:
        raise QualityCandidateIntegrityError("quality effect path is invalid")
    path = (root / reference).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise QualityCandidateIntegrityError(
            "quality effect path escapes project"
        ) from exc
    return path


def _routed_quality_checkpoint_context(
    *,
    route: Mapping[str, object],
    completion_id: str,
    sealed_prestate: object,
    preceding_checkpoint_receipt: object,
) -> tuple[str, dict[str, object]]:
    """Bind a quality checkpoint to its routed completion and prior effect."""
    if (
        not isinstance(route, Mapping)
        or route.get("kind") != "routed"
        or type(route.get("from_phase")) is not str
        or not route.get("from_phase")
        or type(route.get("to_phase")) is not str
        or not route.get("to_phase")
        or type(sealed_prestate) is not dict
    ):
        raise QualityCandidateIntegrityError(
            "quality checkpoint route is invalid"
        )
    if preceding_checkpoint_receipt is None:
        return str(route["to_phase"]), dict(sealed_prestate)
    if not isinstance(preceding_checkpoint_receipt, Mapping):
        raise QualityCandidateIntegrityError(
            "preceding routed checkpoint receipt is invalid"
        )
    receipt = dict(preceding_checkpoint_receipt)
    if (
        receipt.get("completion_id") != completion_id
        or receipt.get("phase") != route["from_phase"]
        or receipt.get("next_phase") != route["to_phase"]
        or receipt.get("outcome") not in {"committed", "no_change"}
    ):
        raise QualityCandidateIntegrityError(
            "preceding routed checkpoint receipt changed"
        )
    head_key = "commit" if receipt["outcome"] == "committed" else "head"
    head = receipt.get(head_key)
    if type(head) is not str:
        raise QualityCandidateIntegrityError(
            "preceding routed checkpoint receipt is invalid"
        )
    return str(route["to_phase"]), {"kind": "git_head", "head": head}


def _quality_completion_id(completion_id: str, effect: str) -> str:
    return hashlib.sha256(
        f"{completion_id}:quality-{effect}".encode("utf-8")
    ).hexdigest()[:32]


def _validate_candidate_effect_receipt(value: object) -> dict[str, object]:
    if type(value) is not dict or frozenset(value) != frozenset(
        {"schema_version", "candidate_id", "checkpoint", "manifest_sha256"}
    ):
        raise QualityCandidateIntegrityError("candidate effect receipt shape mismatch")
    _validate_committed_checkpoint_receipt_shape(value.get("checkpoint"))
    if (
        type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
        or not _is_candidate_id(value.get("candidate_id"))
        or not _is_sha256(value.get("manifest_sha256"))
    ):
        raise QualityCandidateIntegrityError("candidate effect receipt shape mismatch")
    return dict(value)


def _preflight_quality_effect_receipt(
    effect: Mapping[str, object],
    operation: object,
    value: object | None,
) -> Mapping[str, object] | None:
    if value is None:
        return None
    if type(value) is not dict:
        raise QualityCandidateIntegrityError("quality effect receipt shape mismatch")
    if operation == "candidate":
        if frozenset(value) != frozenset(
            {"schema_version", "operation", "candidate", "restore"}
        ):
            raise QualityCandidateIntegrityError(
                "quality effect receipt shape mismatch"
            )
        _validate_candidate_effect_receipt(value.get("candidate"))
        restore_planned = effect.get("restore_candidate_id") is not None
        if restore_planned:
            kind, _receipt = classify_quality_candidate_restore_receipt(
                value.get("restore")
            )
            if kind == "legacy":
                raise QualityCandidateIntegrityError(_LEGACY_RESTORE_GUIDANCE)
            if kind != "git_first":
                raise QualityCandidateIntegrityError(
                    "quality effect restore receipt shape mismatch"
                )
        elif value.get("restore") is not None:
            raise QualityCandidateIntegrityError(
                "quality effect restore receipt shape mismatch"
            )
    elif operation == "restore":
        if frozenset(value) != frozenset(
            {"schema_version", "operation", "restore"}
        ):
            raise QualityCandidateIntegrityError(
                "quality effect receipt shape mismatch"
            )
        kind, _receipt = classify_quality_candidate_restore_receipt(
            value.get("restore")
        )
        if kind == "legacy":
            raise QualityCandidateIntegrityError(_LEGACY_RESTORE_GUIDANCE)
        if kind != "git_first":
            raise QualityCandidateIntegrityError(
                "quality effect restore receipt shape mismatch"
            )
    else:
        return value
    if (
        type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
        or value.get("operation") != operation
    ):
        raise QualityCandidateIntegrityError("quality effect receipt shape mismatch")
    return value


def _git_first_selected_entries(
    *,
    project_root: Path,
    spec_dir: Path,
    selected_restore: object,
) -> tuple[object, ...]:
    try:
        relative_spec = Path(spec_dir).resolve().relative_to(
            Path(project_root).resolve()
        )
        entries = selected_restore.entries
    except (AttributeError, TypeError, ValueError) as exc:
        raise QualityCandidateIntegrityError(
            "candidate restore preflight changed"
        ) from exc
    return tuple(
        replace(
            entry,
            path=(relative_spec / entry.path).as_posix(),
        )
        for entry in entries
    )


def _build_git_first_plan(
    *,
    project_root: Path,
    spec_dir: Path,
    selected_restore: object,
    completion_id: str,
    base_commit: str,
    run_id: str,
    spec_id: str,
    next_phase: str,
) -> GitFirstRestorePlan:
    entries = _git_first_selected_entries(
        project_root=project_root,
        spec_dir=spec_dir,
        selected_restore=selected_restore,
    )
    values = {
        "project_root": project_root,
        "journal_root": Path(
            selected_restore.snapshot.manifest.run_artifact_root
        ),
        "completion_id": completion_id,
        "base_commit": base_commit,
        "selected_candidate_id": (
            selected_restore.snapshot.manifest.candidate_id
        ),
        "selected_manifest_sha256": selected_restore.snapshot.sha256,
        "selected_entries": entries,
        "run_id": run_id,
        "spec_id": spec_id,
        "next_phase": next_phase,
    }
    try:
        return build_git_first_restore_commit(**values)
    except GitFirstRestoreError:
        try:
            return recover_git_first_restore_plan(**values)
        except GitFirstRestoreError as exc:
            raise QualityCandidateIntegrityError(
                f"candidate restore commit authority failed: {exc}"
            ) from exc
    except (AttributeError, TypeError, ValueError, GitFirstRestoreError) as exc:
        raise QualityCandidateIntegrityError(
            f"candidate restore commit authority failed: {exc}"
        ) from exc


def apply_or_verify_proportional_quality_effect(
    effect: Mapping[str, object],
    *,
    completion_id: str,
    project_root: Path,
    state: Mapping[str, object],
    route: Mapping[str, object],
    preceding_checkpoint_receipt: object = None,
    expected_receipt: object | None = None,
) -> dict[str, object]:
    """Apply or verify the exact state-authorized proportional quality effect."""
    try:
        if (
            not isinstance(effect, Mapping)
            or effect.get("kind") != "proportional_quality"
        ):
            raise QualityCandidateIntegrityError(
                "quality completion effect is invalid"
            )
        operation = effect.get("operation")
        root = Path(project_root).resolve()
        expected = _preflight_quality_effect_receipt(
            effect,
            operation,
            expected_receipt,
        )
        if operation == "candidate":
            if set(effect) != {
                "kind",
                "operation",
                "spec_dir",
                "run_id",
                "spec_id",
                "candidate",
                "checkpoint_prestate",
                "restore_candidate_id",
                "restore_candidate_manifest_sha256",
                "restore_artifact_preimage_digests",
            }:
                raise QualityCandidateIntegrityError("candidate effect is invalid")
            repair = validate_repair_state(state.get("phase1_quality_repair"))
            draft = quality_candidate_from_effect_payload(effect.get("candidate"))
            evidence = state.get("proportional_quality_candidate_evidence")
            if (
                not repair["candidate_ids"]
                or repair["candidate_ids"][-1] != draft.candidate_id
                or not isinstance(evidence, Mapping)
                or evidence.get("current_candidate_id") != draft.candidate_id
            ):
                raise QualityCandidateIntegrityError(
                    "candidate effect lacks state authority"
                )
            spec_dir = _inside_project(root, effect.get("spec_dir"))
            run_id = effect.get("run_id")
            spec_id = effect.get("spec_id")
            prestate = effect.get("checkpoint_prestate")
            if (
                type(run_id) is not str
                or not run_id
                or type(spec_id) is not str
                or not spec_id
            ):
                raise QualityCandidateIntegrityError(
                    "candidate effect identity is invalid"
                )
            if type(prestate) is not dict:
                raise QualityCandidateIntegrityError("candidate checkpoint prestate is invalid")
            next_phase, effective_prestate = (
                _routed_quality_checkpoint_context(
                    route=route,
                    completion_id=completion_id,
                    sealed_prestate=prestate,
                    preceding_checkpoint_receipt=(
                        preceding_checkpoint_receipt
                    ),
                )
            )
            candidate_expected = expected.get("candidate") if expected else None
            restore_id = effect.get("restore_candidate_id")
            restore_manifest_sha = effect.get(
                "restore_candidate_manifest_sha256"
            )
            restore_preimages = effect.get(
                "restore_artifact_preimage_digests"
            )
            selected_restore = None
            if restore_id is not None:
                if (
                    type(restore_id) is not str
                    or restore_id not in repair["candidate_ids"]
                    or type(restore_manifest_sha) is not str
                    or len(restore_manifest_sha) != 64
                    or type(restore_preimages) is not dict
                ):
                    raise QualityCandidateIntegrityError(
                        "candidate restore lacks state authority"
                    )
                if (
                    evidence.get("selected_candidate_id") != restore_id
                    or evidence.get("candidate_manifest_sha256")
                    != restore_manifest_sha
                ):
                    raise QualityCandidateIntegrityError(
                        "candidate restore selection changed"
                    )
                selected_restore = preflight_quality_candidate_restore(
                    project_root=root,
                    spec_dir=spec_dir,
                    manifest_path=(
                        Path(draft.run_artifact_root)
                        / "quality-candidates"
                        / f"{restore_id}.json"
                    ),
                    expected_candidate_id=restore_id,
                    expected_manifest_sha256=restore_manifest_sha,
                )
                _validate_restore_candidate(
                    root,
                    selected_restore.snapshot.manifest,
                    run_id=run_id,
                    spec_id=spec_id,
                )
                selected = selected_restore.snapshot.manifest
                restore_completion_id = _quality_completion_id(
                    completion_id,
                    "restore",
                )
                if _legacy_restore_authority_present(
                    spec_dir=spec_dir,
                    candidate=selected,
                    completion_id=restore_completion_id,
                    expected_receipt=None,
                ):
                    raise QualityCandidateIntegrityError(
                        _LEGACY_RESTORE_GUIDANCE
                    )
            materialized, candidate_receipt = materialize_quality_candidate(
                project_root=root,
                spec_dir=spec_dir,
                candidate=draft,
                run_id=run_id,
                spec_id=spec_id,
                completion_id=_quality_completion_id(
                    completion_id,
                    "candidate",
                ),
                next_phase=next_phase,
                checkpoint_prestate=effective_prestate,
                require_current_artifacts=restore_id is None,
                expected_receipt=candidate_expected,
            )
            restore_receipt: dict[str, object] | None = None
            if selected_restore is not None:
                selected = selected_restore.snapshot.manifest
                if selected.candidate_id != restore_id:
                    raise QualityCandidateIntegrityError(
                        "candidate restore identity changed"
                    )
                restore_completion_id = _quality_completion_id(
                    completion_id,
                    "restore",
                )
                restore_expected = (
                    expected.get("restore") if expected else None
                )
                candidate_checkpoint = candidate_receipt.get("checkpoint")
                if (
                    not isinstance(candidate_checkpoint, Mapping)
                    or type(candidate_checkpoint.get("commit")) is not str
                ):
                    raise QualityCandidateIntegrityError(
                        "current candidate checkpoint authority changed"
                    )
                restore_plan = _build_git_first_plan(
                    project_root=root,
                    spec_dir=spec_dir,
                    selected_restore=selected_restore,
                    completion_id=restore_completion_id,
                    base_commit=str(candidate_checkpoint["commit"]),
                    run_id=run_id,
                    spec_id=spec_id,
                    next_phase=next_phase,
                )
                restore_receipt = materialize_quality_candidate_restore(
                    project_root=root,
                    spec_dir=spec_dir,
                    candidate=selected,
                    run_id=run_id,
                    spec_id=spec_id,
                    completion_id=restore_completion_id,
                    next_phase=next_phase,
                    checkpoint_prestate={
                        "kind": "git_head",
                        "head": candidate_checkpoint["commit"],
                    },
                    artifact_preimage_digests=restore_preimages,
                    preflighted_restore=selected_restore,
                    restore_plan=restore_plan,
                    expected_receipt=restore_expected,
                )
            receipt = {
                "schema_version": 1,
                "operation": "candidate",
                "candidate": candidate_receipt,
                "restore": restore_receipt,
            }
        elif operation == "restore":
            if set(effect) != {
                "kind",
                "operation",
                "spec_dir",
                "run_id",
                "spec_id",
                "candidate_id",
                "candidate_manifest_sha256",
                "artifact_preimage_digests",
                "checkpoint_prestate",
            }:
                raise QualityCandidateIntegrityError("candidate restore effect is invalid")
            repair = validate_repair_state(state.get("phase1_quality_repair"))
            candidate_id = effect.get("candidate_id")
            candidate_manifest_sha = effect.get(
                "candidate_manifest_sha256"
            )
            artifact_preimages = effect.get("artifact_preimage_digests")
            evidence = state.get("proportional_quality_candidate_evidence")
            if (
                type(candidate_id) is not str
                or candidate_id not in repair["candidate_ids"]
                or type(candidate_manifest_sha) is not str
                or len(candidate_manifest_sha) != 64
                or type(artifact_preimages) is not dict
                or not isinstance(evidence, Mapping)
                or evidence.get("selected_candidate_id") != candidate_id
                or evidence.get("candidate_manifest_sha256")
                != candidate_manifest_sha
            ):
                raise QualityCandidateIntegrityError("candidate restore lacks state authority")
            spec_dir = _inside_project(root, effect.get("spec_dir"))
            run_id = effect.get("run_id")
            spec_id = effect.get("spec_id")
            prestate = effect.get("checkpoint_prestate")
            if (
                type(run_id) is not str
                or not run_id
                or type(spec_id) is not str
                or not spec_id
                or type(prestate) is not dict
            ):
                raise QualityCandidateIntegrityError(
                    "candidate restore identity is invalid"
                )
            next_phase, effective_prestate = (
                _routed_quality_checkpoint_context(
                    route=route,
                    completion_id=completion_id,
                    sealed_prestate=prestate,
                    preceding_checkpoint_receipt=(
                        preceding_checkpoint_receipt
                    ),
                )
            )
            manifest_ref = evidence.get("candidate_manifest")
            manifest_path = _inside_project(root, manifest_ref)
            selected_restore = preflight_quality_candidate_restore(
                project_root=root,
                spec_dir=spec_dir,
                manifest_path=manifest_path,
                expected_candidate_id=candidate_id,
                expected_manifest_sha256=candidate_manifest_sha,
            )
            candidate = selected_restore.snapshot.manifest
            _validate_restore_candidate(
                root,
                candidate,
                run_id=run_id,
                spec_id=spec_id,
            )
            restore_completion_id = _quality_completion_id(
                completion_id,
                "restore",
            )
            restore_expected = (
                expected.get("restore") if expected else None
            )
            if _legacy_restore_authority_present(
                spec_dir=spec_dir,
                candidate=candidate,
                completion_id=restore_completion_id,
                expected_receipt=None,
            ):
                raise QualityCandidateIntegrityError(
                    _LEGACY_RESTORE_GUIDANCE
                )
            restore_plan = _build_git_first_plan(
                project_root=root,
                spec_dir=spec_dir,
                selected_restore=selected_restore,
                completion_id=restore_completion_id,
                base_commit=str(effective_prestate["head"]),
                run_id=run_id,
                spec_id=spec_id,
                next_phase=next_phase,
            )
            restore_receipt = materialize_quality_candidate_restore(
                project_root=root,
                spec_dir=spec_dir,
                candidate=candidate,
                run_id=run_id,
                spec_id=spec_id,
                completion_id=restore_completion_id,
                next_phase=next_phase,
                checkpoint_prestate=effective_prestate,
                artifact_preimage_digests=artifact_preimages,
                preflighted_restore=selected_restore,
                restore_plan=restore_plan,
                expected_receipt=restore_expected,
            )
            receipt = {
                "schema_version": 1,
                "operation": "restore",
                "restore": restore_receipt,
            }
        elif operation in {"debt_write", "debt_remove"}:
            if set(effect) != {"kind", "operation", "payload"}:
                raise QualityCandidateIntegrityError("quality-debt effect is invalid")
            payload = effect.get("payload")
            if (
                not isinstance(payload, Mapping)
                or payload.get("operation") != operation
            ):
                raise QualityCandidateIntegrityError(
                    "quality-debt effect binding changed"
                )
            if operation == "debt_write":
                authorization = payload.get("authorization")
                if not isinstance(authorization, Mapping) or state.get(
                    "spec_quality_debt_authorization"
                ) != authorization:
                    raise QualityCandidateIntegrityError(
                        "quality-debt effect lacks state authority"
                    )
            elif "spec_quality_debt_authorization" in state:
                raise QualityCandidateIntegrityError(
                    "quality-debt removal authority conflicts"
                )
            debt_receipt = apply_or_verify_quality_debt_effect(
                root,
                payload,
                expected_receipt=(expected.get("debt") if expected else None),
            )
            receipt = {
                "schema_version": 1,
                "operation": operation,
                "debt": debt_receipt,
            }
        else:
            raise QualityCandidateIntegrityError("quality effect operation is invalid")
        if expected is not None and dict(expected) != receipt:
            raise QualityCandidateIntegrityError("quality effect receipt mismatch")
        return receipt
    except CompletionError:
        raise
    except (
        QualityCandidateIntegrityError,
        OSError,
        TypeError,
        ValueError,
        KeyError,
    ) as exc:
        raise CompletionError("receipts_mismatch") from exc
