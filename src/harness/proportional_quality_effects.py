"""Recoverable completion effects for proportional quality lifecycle work."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Mapping

from harness.phase1_quality_debt import apply_or_verify_quality_debt_effect
from harness.proportional_quality import (
    QualityCandidateIntegrityError,
    load_quality_candidate_manifest,
    materialize_quality_candidate,
    materialize_quality_candidate_restore,
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


def apply_or_verify_proportional_quality_effect(
    effect: Mapping[str, object],
    *,
    completion_id: str,
    project_root: Path,
    state: Mapping[str, object],
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
        expected = (
            expected_receipt
            if isinstance(expected_receipt, Mapping)
            else None
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
            candidate_expected = expected.get("candidate") if expected else None
            restore_id = effect.get("restore_candidate_id")
            materialized, candidate_receipt = materialize_quality_candidate(
                project_root=root,
                spec_dir=spec_dir,
                candidate=draft,
                run_id=run_id,
                spec_id=spec_id,
                completion_id=completion_id,
                checkpoint_prestate=prestate,
                require_current_artifacts=restore_id is None,
                expected_receipt=candidate_expected,
            )
            restore_receipt: dict[str, object] | None = None
            if restore_id is not None:
                if (
                    type(restore_id) is not str
                    or restore_id not in repair["candidate_ids"]
                ):
                    raise QualityCandidateIntegrityError(
                        "candidate restore lacks state authority"
                    )
                if (
                    evidence.get("selected_candidate_id") != restore_id
                ):
                    raise QualityCandidateIntegrityError(
                        "candidate restore selection changed"
                    )
                selected = (
                    materialized
                    if restore_id == materialized.candidate_id
                    else load_quality_candidate_manifest(
                        Path(materialized.run_artifact_root)
                        / "quality-candidates"
                        / f"{restore_id}.json"
                    )
                )
                restore_completion_id = hashlib.sha256(
                    f"{completion_id}:quality-restore".encode("utf-8")
                ).hexdigest()[:32]
                restore_receipt = materialize_quality_candidate_restore(
                    project_root=root,
                    spec_dir=spec_dir,
                    candidate=selected,
                    run_id=run_id,
                    spec_id=spec_id,
                    completion_id=restore_completion_id,
                    checkpoint_prestate={
                        "kind": "git_head",
                        "head": candidate_receipt["checkpoint"]["commit"],
                    },
                    expected_receipt=(
                        expected.get("restore") if expected else None
                    ),
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
                "checkpoint_prestate",
            }:
                raise QualityCandidateIntegrityError("candidate restore effect is invalid")
            repair = validate_repair_state(state.get("phase1_quality_repair"))
            candidate_id = effect.get("candidate_id")
            evidence = state.get("proportional_quality_candidate_evidence")
            if (
                type(candidate_id) is not str
                or candidate_id not in repair["candidate_ids"]
                or not isinstance(evidence, Mapping)
                or evidence.get("selected_candidate_id") != candidate_id
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
            manifest_ref = evidence.get("candidate_manifest")
            manifest_path = _inside_project(root, manifest_ref)
            candidate = load_quality_candidate_manifest(manifest_path)
            restore_receipt = materialize_quality_candidate_restore(
                project_root=root,
                spec_dir=spec_dir,
                candidate=candidate,
                run_id=run_id,
                spec_id=spec_id,
                completion_id=completion_id,
                checkpoint_prestate=prestate,
                expected_receipt=(
                    expected.get("restore") if expected else None
                ),
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
