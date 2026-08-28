"""Shared typed acceptance import and frozen workspace-checkpoint adoption."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from harness.re_v2.canonical import content_digest
from harness.re_v2.ledger import ObjectStore, ReV2LedgerError, TREE_OBJECT_MAGIC
from harness.re_v2.protocol_22.baseline import (
    ArtifactAcceptanceReceiptV2,
    CandidateAssessmentReceiptV1,
    CertificationReceiptV2,
    CompactCertificationAssessmentV2,
)
from harness.re_v2.protocol_22.ledger import Protocol22Ledger
from harness.re_v2.protocol_22.model import WorkItemV2
from harness.re_v2.protocol_22.schema import load_canonical_object
from harness.re_v2.protocol_25.artifacts import SemanticCertificationReceiptV1
from harness.re_v2.protocol_25.ledger import Protocol25Ledger

from .inputs import ValidatedProtocol26Inputs


CertificationAuthorityV1 = CertificationReceiptV2 | SemanticCertificationReceiptV1


class Protocol26AdoptionError(RuntimeError):
    """Raised when frozen checkpoint authority cannot be imported exactly."""


def _freeze_required_objects(values: Mapping[str, bytes]) -> Mapping[str, bytes]:
    if not isinstance(values, Mapping):
        raise Protocol26AdoptionError("required_objects must be a mapping")
    copied: dict[str, bytes] = {}
    for object_hash, payload in values.items():
        if (
            not isinstance(object_hash, str)
            or not isinstance(payload, bytes)
            or content_digest(payload) != object_hash
            or payload.startswith(TREE_OBJECT_MAGIC)
        ):
            raise Protocol26AdoptionError("required object authority is invalid")
        copied[object_hash] = payload
    return MappingProxyType(dict(sorted(copied.items())))


@dataclass(frozen=True, slots=True)
class FrozenAcceptancePackageV1:
    work_item: WorkItemV2
    certification: CertificationAuthorityV1
    candidate_assessment: CandidateAssessmentReceiptV1 | None
    acceptance: ArtifactAcceptanceReceiptV2
    required_objects: Mapping[str, bytes]

    def __post_init__(self) -> None:
        if not isinstance(self.work_item, WorkItemV2):
            raise Protocol26AdoptionError("frozen acceptance work item is invalid")
        if not isinstance(
            self.certification,
            (CertificationReceiptV2, SemanticCertificationReceiptV1),
        ):
            raise Protocol26AdoptionError("frozen certification is invalid")
        if self.candidate_assessment is not None and not isinstance(
            self.candidate_assessment, CandidateAssessmentReceiptV1
        ):
            raise Protocol26AdoptionError("frozen candidate assessment is invalid")
        if not isinstance(self.acceptance, ArtifactAcceptanceReceiptV2):
            raise Protocol26AdoptionError("frozen acceptance receipt is invalid")
        objects = _freeze_required_objects(self.required_objects)
        object.__setattr__(self, "required_objects", objects)
        certification = self.certification
        if isinstance(certification, CertificationReceiptV2):
            key = certification.certification_key
            bound = (
                key.artifact_key == self.work_item.output_key
                and key.verifier_id == self.work_item.verifier_id
                and key.verifier_version == self.work_item.verifier_version
                and key.verifier_implementation_digest
                == self.work_item.verifier_implementation_digest
            )
            artifact_hash = key.artifact_hash
            artifact_key_id = key.artifact_key.identity
        else:
            bound = certification.artifact_key_id == self.work_item.output_key.identity
            artifact_hash = certification.artifact_hash
            artifact_key_id = certification.artifact_key_id
        if (
            certification.verdict != "accepted"
            or not bound
            or self.acceptance.certification_receipt_id != certification.identity
            or self.acceptance.artifact_key != self.work_item.output_key
            or self.acceptance.artifact_key.identity != artifact_key_id
            or self.acceptance.artifact_hash != artifact_hash
            or artifact_hash not in objects
        ):
            raise Protocol26AdoptionError(
                "frozen acceptance package is not exactly cross-bound"
            )
        candidate = self.candidate_assessment
        if isinstance(certification, CertificationReceiptV2):
            requires_candidate = isinstance(
                certification.assessment,
                CompactCertificationAssessmentV2,
            )
            if requires_candidate != (candidate is not None):
                raise Protocol26AdoptionError(
                    "frozen candidate presence disagrees with certification kind"
                )
        if candidate is not None:
            required_candidate_objects = {candidate.execution_capture_hash}
            if candidate.normalized_authorial_payload_hash is not None:
                required_candidate_objects.add(
                    candidate.normalized_authorial_payload_hash
                )
            if (
                candidate.outcome != "certified"
                or candidate.work_item_id != self.work_item.work_item_id
                or candidate.artifact_hash != artifact_hash
                or candidate.certification_receipt_id != certification.identity
                or not required_candidate_objects <= set(objects)
            ):
                raise Protocol26AdoptionError(
                    "frozen candidate assessment is not exactly cross-bound"
                )
        elif isinstance(certification, SemanticCertificationReceiptV1):
            raise Protocol26AdoptionError(
                "semantic frozen acceptance requires candidate authority"
            )


@dataclass(frozen=True, slots=True)
class ImportedAcceptanceV1:
    artifact_key_id: str
    work_item_id: str
    receipt_ids: tuple[str, ...]
    object_ids: tuple[str, ...]

    @classmethod
    def from_package(
        cls,
        package: FrozenAcceptancePackageV1,
    ) -> "ImportedAcceptanceV1":
        receipts = {package.certification.identity, package.acceptance.identity}
        if package.candidate_assessment is not None:
            receipts.add(package.candidate_assessment.identity)
        return cls(
            artifact_key_id=package.acceptance.artifact_key.identity,
            work_item_id=package.work_item.work_item_id,
            receipt_ids=tuple(sorted(receipts)),
            object_ids=tuple(sorted(package.required_objects)),
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "artifact_key_id": self.artifact_key_id,
            "work_item_id": self.work_item_id,
            "receipt_ids": list(self.receipt_ids),
            "object_ids": list(self.object_ids),
        }


@dataclass(frozen=True, slots=True)
class CheckpointAdoptionReportV1:
    imports: tuple[ImportedAcceptanceV1, ...]

    def __post_init__(self) -> None:
        values = tuple(self.imports)
        if any(not isinstance(item, ImportedAcceptanceV1) for item in values):
            raise Protocol26AdoptionError("checkpoint adoption report is invalid")
        keys = tuple(item.artifact_key_id for item in values)
        if len(keys) != len(set(keys)):
            raise Protocol26AdoptionError(
                "checkpoint adoption report contains duplicate artifact keys"
            )
        object.__setattr__(self, "imports", values)

    @property
    def artifact_key_ids(self) -> tuple[str, ...]:
        return tuple(item.artifact_key_id for item in self.imports)

    @property
    def work_item_ids(self) -> tuple[str, ...]:
        return tuple(item.work_item_id for item in self.imports)

    @property
    def receipt_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted({value for item in self.imports for value in item.receipt_ids})
        )

    @property
    def object_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted({value for item in self.imports for value in item.object_ids})
        )

    def to_json_dict(self) -> dict[str, object]:
        return {"imports": [item.to_json_dict() for item in self.imports]}


def import_typed_acceptance(
    package: FrozenAcceptancePackageV1,
    destination_objects: ObjectStore,
    destination_ledger: Protocol22Ledger,
) -> ImportedAcceptanceV1:
    """Import one exact receipt package in the established ledger order."""
    if not isinstance(package, FrozenAcceptancePackageV1):
        raise Protocol26AdoptionError("typed acceptance package is invalid")
    if not isinstance(destination_objects, ObjectStore) or not isinstance(
        destination_ledger, Protocol22Ledger
    ):
        raise Protocol26AdoptionError(
            "typed acceptance requires object-store and ledger facades"
        )
    try:
        for object_hash, payload in package.required_objects.items():
            if destination_objects.put_blob(payload) != object_hash:
                raise Protocol26AdoptionError(
                    f"copied object changed identity: {object_hash}"
                )
        if isinstance(package.certification, SemanticCertificationReceiptV1):
            if not isinstance(destination_ledger, Protocol25Ledger):
                raise Protocol26AdoptionError(
                    "semantic acceptance requires a protocol-2.5 ledger"
                )
            destination_ledger.record_semantic_certification(package.certification)
        else:
            destination_ledger.record_certification(
                package.certification,
                package.work_item,
            )
        if package.candidate_assessment is not None:
            destination_ledger.record_candidate_assessment(package.candidate_assessment)
        destination_ledger.record_artifact_acceptance(package.acceptance)
        _verify_imported_acceptance(package, destination_ledger)
    except Protocol26AdoptionError:
        raise
    except ReV2LedgerError as exc:
        raise Protocol26AdoptionError(
            f"typed acceptance import conflict: {exc}"
        ) from exc
    return ImportedAcceptanceV1.from_package(package)


def import_frozen_checkpoint_closure(
    inputs: ValidatedProtocol26Inputs,
    objects: ObjectStore,
    ledger: Protocol22Ledger,
) -> CheckpointAdoptionReportV1:
    """Import workspace checkpoints from the child's frozen local authority."""
    if not isinstance(inputs, ValidatedProtocol26Inputs):
        raise Protocol26AdoptionError(
            "checkpoint import requires ValidatedProtocol26Inputs"
        )
    imported: list[ImportedAcceptanceV1] = []
    for selection in inputs.checkpoint_selection.selected:
        if selection.source_kind != "workspace_checkpoint":
            continue
        try:
            work_item = load_canonical_object(
                inputs.authority_objects[selection.expected_work_item_id],
                WorkItemV2.from_json_dict,
            )
            authority = selection.adopted_artifact_authority
            certification = _load_certification(
                inputs.authority_objects[authority.certification_receipt_id]
            )
            candidate = (
                None
                if authority.candidate_assessment_id is None
                else load_canonical_object(
                    inputs.authority_objects[authority.candidate_assessment_id],
                    CandidateAssessmentReceiptV1.from_json_dict,
                )
            )
            acceptance = load_canonical_object(
                inputs.authority_objects[authority.artifact_acceptance_receipt_id],
                ArtifactAcceptanceReceiptV2.from_json_dict,
            )
            required = {
                object_hash: inputs.authority_objects[object_hash]
                for object_hash in selection.copied_object_ids
            }
            package = FrozenAcceptancePackageV1(
                work_item,
                certification,
                candidate,
                acceptance,
                required,
            )
            imported.append(import_typed_acceptance(package, objects, ledger))
        except Protocol26AdoptionError:
            raise
        except (KeyError, ReV2LedgerError, ValueError) as exc:
            raise Protocol26AdoptionError(
                f"frozen checkpoint authority is incomplete: {exc}"
            ) from exc
    return CheckpointAdoptionReportV1(tuple(imported))


def _load_certification(payload: bytes) -> CertificationAuthorityV1:
    try:
        return load_canonical_object(payload, CertificationReceiptV2.from_json_dict)
    except Exception:
        try:
            return load_canonical_object(
                payload,
                SemanticCertificationReceiptV1.from_json_dict,
            )
        except Exception as semantic_error:
            raise Protocol26AdoptionError(
                "frozen certification object is invalid"
            ) from semantic_error


def _verify_imported_acceptance(
    package: FrozenAcceptancePackageV1,
    ledger: Protocol22Ledger,
) -> None:
    replayed = ledger.replay()
    certification = package.certification
    if isinstance(certification, SemanticCertificationReceiptV1):
        certifications = getattr(replayed, "semantic_certifications", {})
        certification_matches = (
            certifications.get(certification.identity) == certification
        )
    else:
        certification_matches = (
            replayed.certifications.get(certification.identity) == certification
            and replayed.certification_work_items.get(certification.identity)
            == package.work_item
        )
    candidate = package.candidate_assessment
    if (
        not certification_matches
        or replayed.accepted_artifacts.get(package.acceptance.artifact_key.identity)
        != package.acceptance
        or (
            candidate is not None
            and replayed.candidate_assessments.get(candidate.identity) != candidate
        )
    ):
        raise Protocol26AdoptionError(
            "imported ledger does not equal frozen acceptance authority"
        )


__all__ = (
    "CheckpointAdoptionReportV1",
    "FrozenAcceptancePackageV1",
    "ImportedAcceptanceV1",
    "Protocol26AdoptionError",
    "import_frozen_checkpoint_closure",
    "import_typed_acceptance",
)
